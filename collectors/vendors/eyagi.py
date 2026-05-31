"""Collector implementation for Eyagi 모바일 (eyagi).

목록 페이지(findMyType.php)에서 plan 항목을 수집해 comm_code를 추출하고,
필요한 최소 필드를 충족하도록 표준 PlanRecord를 생성합니다.
상세 페이지 파싱은 추후 확장 가능합니다.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable, List

from bs4 import BeautifulSoup

from collectors.base import BaseCollector
from collectors.registry import registry
from collectors.utils.playwright import browser_context
from schemas.plan_record import PlanRecord


logger = logging.getLogger(__name__)


LIST_PAGE_URL = "https://www.eyagi.co.kr/shop/plan/findMyType.php"


@dataclass(slots=True)
class EyagiListItem:
    comm_code: str
    raw_text: str | None


def _extract_comm_code(onclick_value: str | None) -> str | None:
    if not onclick_value:
        return None
    m = re.search(r"prdcDirect\(\s*['\"]([^'\"]+)['\"]\s*\)", onclick_value)
    return m.group(1) if m else None


def _norm_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


async def _fetch_list_html() -> str:
    async with browser_context() as context:
        page = await context.new_page()
        page.set_default_timeout(15000)
        await page.goto(LIST_PAGE_URL, wait_until="domcontentloaded")
        # 기본 리스트 요소 대기
        await page.wait_for_selector("li.prdc-item", timeout=10000)
        # 더보기/무한스크롤 대응: 몇 차례 스크롤
        for _ in range(8):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            await page.wait_for_timeout(400)
        html = await page.content()
        await page.close()
        return html


def _parse_list(html: str) -> list[EyagiListItem]:
    soup = BeautifulSoup(html, "lxml")
    items: list[EyagiListItem] = []
    for li in soup.select("li.prdc-item"):
        onclick = li.get("onclick") or ""
        if not onclick:
            # 자식에 onclick이 있는 경우도 고려
            child = li.select_one("[onclick]")
            onclick = child.get("onclick") if child else ""
        code = _extract_comm_code(onclick)
        if not code:
            continue
        raw = _norm_text(li.get_text(" ", strip=True))
        items.append(EyagiListItem(comm_code=code, raw_text=raw))
    return items


def _parse_money_anywhere(text: str | None) -> int | None:
    if not text:
        return None
    # 첫 번째 금액 패턴을 월 요금으로 간주
    m = re.search(r"(\d[\d,]{2,})\s*원", text)
    if not m:
        # 숫자만 추출
        m2 = re.search(r"\d[\d,]{2,}", text)
        if not m2:
            return None
        value = m2.group(0)
    else:
        value = m.group(1)
    return int(value.replace(",", ""))


def _parse_data_allowance_anywhere(text: str | None) -> int:
    if not text:
        return 0
    m = re.search(r"(\d+(?:\.\d+)?)\s*(TB|GB|MB)", text, flags=re.IGNORECASE)
    if not m:
        return 0
    value = float(m.group(1))
    unit = m.group(2).upper()
    if unit == "TB":
        return int(value * 1024 * 1024)
    if unit == "GB":
        return int(value * 1024)
    return int(value)


class EyagiCollector(BaseCollector):
    """Collector that builds minimal PlanRecords from Eyagi plan list."""

    async def fetch_entries(self) -> Iterable[EyagiListItem]:
        html = await _fetch_list_html()
        items = _parse_list(html)
        logger.info("Eyagi items: %s", len(items))
        # 과도한 요청 방지를 위해 여기서는 목록만 사용 (상세 파싱은 추후 확장)
        await asyncio.sleep(0.1)
        return items

    async def parse_entries(self, entries: Iterable[EyagiListItem]) -> List[PlanRecord]:
        records: list[PlanRecord] = []
        for item in entries:
            name = item.raw_text or item.comm_code
            monthly_fee = _parse_money_anywhere(item.raw_text) or 0
            data_allowance_mb = _parse_data_allowance_anywhere(item.raw_text)
            # 목록 기준으로는 음성/문자/망 유형을 알기 어려움 → None 처리
            record = PlanRecord(
                vendor="eyagi",
                plan_id=item.comm_code,
                name=name,
                monthly_fee=float(monthly_fee),
                data_allowance_mb=data_allowance_mb,
                voice_minutes=None,
                sms_count=None,
                network_type=None,
                promotion=None,
                metadata={
                    "source": "list",
                    "raw": item.raw_text,
                },
            )
            records.append(record)
        return records


registry.register(
    "eyagi",
    EyagiCollector,
    description="Eyagi 목록에서 comm_code 기반 PlanRecord 최소 필드 생성",
)



