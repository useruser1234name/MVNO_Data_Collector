"""Collector implementation for 인스모바일 (insmobile).

탭 페이지에서 카드 상세 URL을 수집한 후, 상세 페이지의 텍스트에서
월요금/데이터/음성/문자 정보를 휴리스틱으로 추출하여 PlanRecord를 생성합니다.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from collectors.base import BaseCollector
from collectors.registry import registry
from schemas.plan_record import PlanRecord


logger = logging.getLogger(__name__)


SITE_ROOT = "https://www.insmobile.co.kr"
START_URL = "https://www.insmobile.co.kr/rate_plan.do?type=T007"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _strip_jsessionid(url: str) -> str:
    return re.sub(r";jsessionid=[^?]*", "", url)


def _fetch_soup(session: requests.Session, url: str, referer: str | None = None, timeout: int = 15) -> BeautifulSoup:
    headers = dict(HEADERS)
    headers["Referer"] = referer or f"{SITE_ROOT}/"
    response = session.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding
    return BeautifulSoup(response.text, "lxml")


@dataclass(slots=True)
class DetailLink:
    url: str


def _extract_tab_links(soup: BeautifulSoup) -> list[str]:
    urls: list[str] = []
    ul = soup.select_one("ul.tab_box_list_t3")
    if not ul:
        return urls
    for a in ul.select("a.tab_box_link"):
        href = a.get("href")
        if not href:
            continue
        full = _strip_jsessionid(urljoin(SITE_ROOT, href))
        urls.append(full)
    # de-dup while preserving order
    return list(dict.fromkeys(urls))


def _maybe_add(urls: list[str], raw: str | None) -> None:
    if not raw:
        return
    urls.append(_strip_jsessionid(urljoin(SITE_ROOT, raw)))


def _extract_card_links(soup: BeautifulSoup) -> list[str]:
    out: list[str] = []
    wrap = soup.select_one("div.rate_list_wrap")
    if not wrap:
        return out
    scope = wrap.select_one("div.card_list.rate_list") or wrap
    for a in scope.select("a.card_list_item[href]"):
        _maybe_add(out, a.get("href"))
    for a in scope.select(".card_list_item a[href]"):
        _maybe_add(out, a.get("href"))
    for el in scope.select(".card_list_item"):
        onclick = el.get("onclick")
        if onclick:
            m = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", onclick)
            if m:
                _maybe_add(out, m.group(1))
        data_url = el.get("data-url")
        if data_url:
            _maybe_add(out, data_url)
    return list(dict.fromkeys(out))


def _parse_money(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.findall(r"\d[\d,]{2,}", text)
    if not digits:
        return None
    return int(digits[0].replace(",", ""))


def _parse_data_allowance(text: str | None) -> int:
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


def _parse_voice_minutes(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"(\d+)\s*분", text)
    return int(m.group(1)) if m else None


def _parse_sms_count(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"(\d+)\s*건", text)
    return int(m.group(1)) if m else None


def _extract_name(soup: BeautifulSoup, fallback_url: str) -> str:
    for sel in ("h1", "h2", "h3", ".plan_tit", ".tit"):
        node = soup.select_one(sel)
        if node:
            text = node.get_text(strip=True)
            if text:
                return text
    # fallback: last path component
    return fallback_url.rstrip("/").split("/")[-1]


def _parse_detail_to_record(url: str, soup: BeautifulSoup) -> PlanRecord:
    page_text = soup.get_text(" ", strip=True)
    name = _extract_name(soup, url)
    monthly_fee = _parse_money(page_text) or 0
    data_allowance_mb = _parse_data_allowance(page_text)
    voice_minutes = _parse_voice_minutes(page_text)
    sms_count = _parse_sms_count(page_text)
    return PlanRecord(
        vendor="insmobile",
        plan_id=name,  # 상세에 고유 코드가 명시되지 않는 경우가 많아 이름으로 대체
        name=name,
        monthly_fee=float(monthly_fee),
        data_allowance_mb=data_allowance_mb,
        voice_minutes=voice_minutes,
        sms_count=sms_count,
        network_type=None,
        promotion=None,
        metadata={
            "detail_url": url,
        },
    )


class InsmobileCollector(BaseCollector):
    """Collector for 인스모바일 요금제 상세."""

    async def fetch_entries(self) -> Iterable[DetailLink]:
        return await asyncio.to_thread(self._fetch_entries_sync)

    def _fetch_entries_sync(self) -> list[DetailLink]:
        session = requests.Session()
        session.headers.update(HEADERS)
        try:
            start_url = _strip_jsessionid(START_URL)
            soup = _fetch_soup(session, start_url)
            tab_urls = _extract_tab_links(soup)
            detail_urls: list[str] = []
            for tab_url in tab_urls or [start_url]:
                tab_soup = _fetch_soup(session, tab_url, referer=start_url)
                detail_urls.extend(_extract_card_links(tab_soup))
            detail_urls = list(dict.fromkeys(detail_urls))
            logger.info("Collected %s detail URLs", len(detail_urls))
            return [DetailLink(url=u) for u in detail_urls]
        finally:
            session.close()

    async def parse_entries(self, entries: Iterable[DetailLink]) -> List[PlanRecord]:
        return await asyncio.to_thread(self._parse_entries_sync, list(entries))

    def _parse_entries_sync(self, entries: list[DetailLink]) -> List[PlanRecord]:
        session = requests.Session()
        session.headers.update(HEADERS)
        records: list[PlanRecord] = []
        try:
            for entry in entries:
                try:
                    soup = _fetch_soup(session, entry.url)
                    record = _parse_detail_to_record(entry.url, soup)
                    records.append(record)
                except Exception as exc:
                    logger.warning("Failed to parse %s: %s", entry.url, exc, exc_info=True)
            return records
        finally:
            session.close()


registry.register(
    "insmobile",
    InsmobileCollector,
    description="인스모바일 상세 페이지를 수집하여 PlanRecord로 반환",
)



