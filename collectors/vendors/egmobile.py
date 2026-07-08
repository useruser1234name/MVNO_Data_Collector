"""Collector implementation for EG모바일 (egmobile).

EG모바일 요금제 리스트 페이지는 동적 렌더링 요소가 있어 Playwright를 사용해
리스트 HTML을 로드한 뒤 BeautifulSoup으로 파싱합니다. 리스트 행(tr[onclick])에서
핵심 정보를 추출하여 표준 PlanRecord로 매핑합니다.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, List

from bs4 import BeautifulSoup

from collectors.base import BaseCollector
from collectors.registry import registry
from collectors.utils.playwright import browser_context
from schemas.plan_record import PlanRecord


logger = logging.getLogger(__name__)


LIST_URLS = [
    "https://www.egmobile.co.kr/charge/list?te=kt",
    "https://www.egmobile.co.kr/charge/list?te=lg",
]


@dataclass(slots=True)
class ListRow:
    href: str | None
    name: str | None
    data_text: str | None
    fee_price: str | None
    fee_fixed_price: str | None
    fee_note: str | None
    source_url: str | None


def _norm_text(node) -> str:
    if not node:
        return ""
    txt = node.get_text(" ", strip=True)
    return " ".join(txt.split())


def _extract_href_from_onclick(onclick: str | None) -> str | None:
    if not onclick:
        return None
    m = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", onclick)
    if m:
        return m.group(1).strip()
    m = re.search(r"location\.assign\(\s*['\"]([^'\"]+)['\"]\s*\)", onclick)
    if m:
        return m.group(1).strip()
    m = re.search(r"window\.location\s*=\s*['\"]([^'\"]+)['\"]", onclick)
    if m:
        return m.group(1).strip()
    return None


def _parse_rows_from_html(html: str, source_url: str) -> list[ListRow]:
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select("tr[onclick]")
    parsed: list[ListRow] = []
    for tr in rows:
        if tr.find("td") is None:
            continue
        onclick = tr.get("onclick", "") or ""
        href = _extract_href_from_onclick(onclick)

        # 각 td의 첫 번째 class를 키로 보고 대표 텍스트를 추출
        text_by_class: dict[str, str] = {}
        for td in tr.find_all("td"):
            classes = td.get("class", [])
            if not classes:
                continue
            key = classes[0]
            text_by_class[key] = _norm_text(td)

        fee_price = None
        fee_fixed = None
        fee_note = None
        fee_td = tr.find("td", class_="fee")
        if fee_td:
            fee_fixed_node = fee_td.find("span", class_="fixed_price")
            fee_price_node = fee_td.find("span", class_="price")
            fee_fixed = _norm_text(fee_fixed_node)
            fee_price = _norm_text(fee_price_node)
            remainder = _norm_text(fee_td)
            for part in (fee_fixed, fee_price):
                if part:
                    remainder = remainder.replace(part, " ").strip()
            fee_note = " ".join(remainder.split()) if remainder else None

        parsed.append(
            ListRow(
                href=href,
                name=text_by_class.get("name") or text_by_class.get("txt") or None,
                data_text=text_by_class.get("data") or None,
                fee_price=fee_price,
                fee_fixed_price=fee_fixed,
                fee_note=fee_note,
                source_url=source_url,
            )
        )
    return parsed


def _parse_money(text: str | None) -> int | None:
    if not text:
        return None
    cleaned = text.replace(",", "")
    digits = re.findall(r"\d+", cleaned)
    if not digits:
        return None
    return int("".join(digits))


def _parse_data_allowance(text: str | None) -> int:
    if not text:
        return 0
    normalized = re.sub(r"\s+", " ", text)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(TB|GB|MB)", normalized, flags=re.IGNORECASE)
    if not m:
        return 0
    value = float(m.group(1))
    unit = m.group(2).upper()
    if unit == "TB":
        return int(value * 1024 * 1024)
    if unit == "GB":
        return int(value * 1024)
    return int(value)


def _derive_plan_id(href: str | None) -> str:
    if not href:
        return "unknown"
    # 쿼리 파라미터에서 코드 추출
    m = re.search(r"(?:[?&](?:cd|code|id)=)([^&#]+)", href, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    # 숫자 시퀀스 우선 추출
    m = re.search(r"(\d{4,})", href)
    if m:
        return m.group(1)
    # 마지막 경로 조각 사용
    tail = href.rstrip("/").split("/")[-1]
    return tail or "unknown"


async def _fetch_list_html(url: str) -> str:
    # Playwright async helper 사용
    async with browser_context() as context:
        await context.set_extra_http_headers({
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        page = await context.new_page()
        page.set_default_timeout(10000)
        await page.goto(url, wait_until="domcontentloaded")
        # 리스트 렌더링 안정화 대기
        await page.wait_for_selector("tr[onclick]", timeout=8000)
        await page.wait_for_timeout(300)
        html = await page.content()
        await page.close()
        return html


class EGMobileCollector(BaseCollector):
    """Collector for EG모바일 요금제 리스트."""

    async def fetch_entries(self) -> Iterable[ListRow]:
        urls_env = os.environ.get("EGMOBILE_LIST_URLS")
        urls: list[str] = LIST_URLS
        if urls_env:
            # 쉼표 구분 허용
            urls = [u.strip() for u in urls_env.split(",") if u.strip()]
        rows: list[ListRow] = []
        for url in urls:
            try:
                html = await _fetch_list_html(url)
            except Exception as exc:
                logger.warning("Failed to load %s: %s", url, exc)
                continue
            parsed = _parse_rows_from_html(html, url)
            rows.extend(parsed)
            await asyncio.sleep(0.3)
        return rows

    async def parse_entries(self, entries: Iterable[ListRow]) -> List[PlanRecord]:
        records: list[PlanRecord] = []
        for row in entries:
            monthly_fee_source = row.fee_price or row.fee_fixed_price
            monthly_fee = _parse_money(monthly_fee_source) or 0
            data_allowance_mb = _parse_data_allowance(row.data_text)
            plan_id = _derive_plan_id(row.href)
            name = row.name or plan_id
            promotion_bits: list[str] = []
            if row.fee_note:
                promotion_bits.append(row.fee_note)

            metadata: dict[str, Any] = {
                "href": row.href,
                "source_url": row.source_url,
                "raw_data_text": row.data_text,
                "raw_fee_price": row.fee_price,
                "raw_fee_fixed_price": row.fee_fixed_price,
            }

            record = PlanRecord(
                vendor="egmobile",
                plan_id=plan_id,
                name=name,
                monthly_fee=float(monthly_fee),
                data_allowance_mb=data_allowance_mb,
                voice_minutes=None,
                sms_count=None,
                network_type=None,
                promotion=" | ".join(promotion_bits) if promotion_bits else None,
                metadata=metadata,
            )
            records.append(record)
        return records


registry.register(
    "egmobile",
    EGMobileCollector,
    description="EG모바일 요금제 리스트를 수집하여 PlanRecord로 변환",
)


