"""Collector for 찬스모바일 plan pages."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List
from urllib.parse import urlencode, urlunparse

from collectors.base import BaseCollector
from collectors.registry import registry
from collectors.vendors.html_plan_common import build_record, fetch_html, normalize_text, parse_money, strip_tags
from schemas.plan_record import PlanRecord

LIST_URL = "https://chancemobile.co.kr/view/plan/phone_plan.aspx"


def build_detail_url(gdcd: str, poscd: str) -> str:
    query = urlencode({"gdcd": gdcd, "poscd": poscd})
    return urlunparse(("https", "chancemobile.co.kr", "/view/plan/phone_plan_detail.aspx", "", query, ""))


def parse_entries_from_html(html: str, source_url: str = LIST_URL) -> list[dict[str, str]]:
    """Extract ChanceMobile rows from onclick-driven listing markup."""
    entries: list[dict[str, str]] = []
    pattern = re.compile(
        r"(?P<fragment><(?P<tag>\w+)[^>]*onclick=[\"'][^\"']*fnMovePlanDetail\s*\(\s*[\"']?(?P<gdcd>[^,'\")\s]+)"
        r"[\"']?\s*,\s*[\"']?(?P<poscd>[^,'\")\s]+)[^>]*>.*?</(?P=tag)>)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(html):
        fragment_text = strip_tags(match.group("fragment"))
        detail_url = build_detail_url(match.group("gdcd"), match.group("poscd"))
        name_html_match = re.search(
            r"class=[\"'][^\"']*(?:data_name|plan|title|name)[^\"']*[\"'][^>]*>(?P<name>.*?)</",
            match.group("fragment"),
            flags=re.IGNORECASE | re.DOTALL,
        )
        name_match = re.search(r"([가-힣A-Za-z0-9][가-힣A-Za-z0-9\s+()/._-]{2,60})", fragment_text)
        data_match = re.search(r"(\d+(?:\.\d+)?\s*(?:GB|MB|TB)[^\s]*)", fragment_text, re.IGNORECASE)
        price_match = re.search(r"월\s*([\d,]+)\s*원|([\d,]+)\s*원", fragment_text)
        entries.append(
            {
                "plan_id": f"chancemobile-{match.group('gdcd')}-{match.group('poscd')}",
                "name": (
                    strip_tags(name_html_match.group("name"))
                    if name_html_match
                    else normalize_text(name_match.group(1)) if name_match else f"찬스모바일 {match.group('gdcd')}"
                ),
                "data": normalize_text(data_match.group(1)) if data_match else "",
                "price": next(group for group in price_match.groups() if group) if price_match else "0",
                "detail_url": detail_url,
                "source_url": source_url,
                "raw_text": fragment_text,
            }
        )
    return entries


def row_to_record(row: dict[str, str]) -> PlanRecord:
    raw_text = row.get("raw_text") or ""
    return build_record(
        vendor="chancemobile",
        plan_id=row["plan_id"],
        name=row["name"],
        monthly_fee=parse_money(row.get("price")),
        data_text=row.get("data") or raw_text,
        voice_text=raw_text,
        sms_text=raw_text,
        promotion=raw_text if raw_text else None,
        metadata={
            "detail_url": row.get("detail_url"),
            "source_url": row.get("source_url"),
            "crawled_source": "official_html",
            "raw_text": raw_text,
        },
    )


class ChanceMobileCollector(BaseCollector):
    """Collector that parses 찬스모바일 official plan listing HTML."""

    async def fetch_entries(self) -> Iterable[dict[str, str]]:
        source_path = self.config.metadata.get("chancemobile_html_path")
        html = Path(source_path).read_text(encoding="utf-8") if source_path else fetch_html(LIST_URL)
        await self.save_raw_payload(html, "chancemobile_plan_list.html")
        return parse_entries_from_html(html, LIST_URL)

    async def parse_entries(self, entries: Iterable[dict[str, str]]) -> List[PlanRecord]:
        return [row_to_record(row) for row in entries]


registry.register(
    "chancemobile",
    ChanceMobileCollector,
    description="찬스모바일 공식 요금제 페이지를 PlanRecord로 변환",
)
