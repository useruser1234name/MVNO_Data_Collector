"""Collector for 스마텔 plan pages."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable, List

from collectors.base import BaseCollector
from collectors.registry import registry
from collectors.vendors.html_plan_common import absolute_url, build_record, fetch_html, normalize_text, parse_money, strip_tags
from schemas.plan_record import PlanRecord

LIST_URL = "https://www.smartel.kr/phoneplan"


def _entry_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def parse_entries_from_html(html: str, source_url: str = LIST_URL) -> list[dict[str, str]]:
    """Parse Smartel plan cards from static/SSR HTML."""
    entries: list[dict[str, str]] = []
    anchor_pattern = re.compile(r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>", flags=re.IGNORECASE | re.DOTALL)
    for match in anchor_pattern.finditer(html):
        attrs = match.group("attrs")
        href_match = re.search(r"href=[\"'](?P<href>[^\"']+)[\"']", attrs, flags=re.IGNORECASE)
        href = href_match.group("href") if href_match else ""
        if "phoneplan" not in href:
            continue
        text = strip_tags(match.group("body"))
        if "월" not in text or "원" not in text:
            continue
        price_match = re.search(r"월\s*([\d,]+)\s*원", text)
        data_match = re.search(r"(\d+(?:\.\d+)?\s*(?:GB|MB|TB)\+?[^\s]*)", text, flags=re.IGNORECASE)
        heading_match = re.search(
            r"<h[1-6][^>]*>(?P<heading>.*?)</h[1-6]>",
            match.group("body"),
            flags=re.IGNORECASE | re.DOTALL,
        )
        name_match = re.search(r"(?:SKT|KT|LGU\+)?\s*([가-힣A-Za-z0-9][가-힣A-Za-z0-9\s+()/._-]{2,80})\s+(?:총\s*)?\d", text)
        raw = normalize_text(text)
        name = strip_tags(heading_match.group("heading")) if heading_match else None
        entries.append(
            {
                "plan_id": f"smartel-{_entry_id(href or raw)}",
                "name": name or (normalize_text(name_match.group(1)) if name_match else raw[:50]),
                "data": normalize_text(data_match.group(1)) if data_match else raw,
                "price": price_match.group(1) if price_match else "0",
                "detail_url": absolute_url(source_url, href) or source_url,
                "raw_text": raw,
            }
        )
    if entries:
        return entries

    # Fallback for search-index text where card anchors are flattened.
    text = strip_tags(html)
    fallback_pattern = re.compile(
        r"(?P<network>SKT|KT|LGU\+)\s+(?P<discount>\d+\s*개월\s*할인)?\s*[^월]{0,30}?"
        r"(?P<name>[가-힣A-Za-z0-9][가-힣A-Za-z0-9\s+()/._-]{2,80})\s+"
        r"(?P<data>\d+(?:\.\d+)?\s*(?:GB|MB|TB)\+?[^월]{0,80}?)\s+월\s*(?P<price>[\d,]+)\s*원",
        flags=re.IGNORECASE,
    )
    for match in fallback_pattern.finditer(text):
        raw = normalize_text(match.group(0))
        entries.append(
            {
                "plan_id": f"smartel-{_entry_id(raw)}",
                "name": normalize_text(match.group("name")),
                "data": normalize_text(match.group("data")),
                "price": match.group("price"),
                "network_type": normalize_text(match.group("network")),
                "detail_url": source_url,
                "raw_text": raw,
            }
        )
    return entries


def row_to_record(row: dict[str, str]) -> PlanRecord:
    raw_text = row.get("raw_text") or ""
    network_type = row.get("network_type")
    if not network_type:
        network_match = re.search(r"\b(SKT|KT|LGU\+)\b", raw_text)
        network_type = network_match.group(1) if network_match else None
    return build_record(
        vendor="smartel",
        plan_id=row["plan_id"],
        name=row["name"],
        monthly_fee=parse_money(row.get("price")),
        data_text=row.get("data") or raw_text,
        voice_text=raw_text,
        sms_text=raw_text,
        network_type=network_type,
        promotion=raw_text if raw_text else None,
        metadata={
            "detail_url": row.get("detail_url"),
            "crawled_source": "official_html",
            "raw_text": raw_text,
        },
    )


class SmartelCollector(BaseCollector):
    """Collector that parses 스마텔 official plan listing HTML."""

    async def fetch_entries(self) -> Iterable[dict[str, str]]:
        source_path = self.config.metadata.get("smartel_html_path")
        html = Path(source_path).read_text(encoding="utf-8") if source_path else fetch_html(LIST_URL)
        await self.save_raw_payload(html, "smartel_plan_list.html")
        return parse_entries_from_html(html, LIST_URL)

    async def parse_entries(self, entries: Iterable[dict[str, str]]) -> List[PlanRecord]:
        return [row_to_record(row) for row in entries]


registry.register(
    "smartel",
    SmartelCollector,
    description="스마텔 공식 요금제 페이지를 PlanRecord로 변환",
)
