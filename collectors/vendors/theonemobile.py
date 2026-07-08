"""Collector for 더원모바일 plan pages."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable, List

from collectors.base import BaseCollector
from collectors.registry import registry
from collectors.vendors.html_plan_common import build_record, fetch_html, normalize_text, parse_money, strip_tags
from schemas.plan_record import PlanRecord

LIST_URL = "https://www.theonem.co.kr/view/plan/phone_plan.aspx"


def _entry_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def parse_entries_from_html(html: str, source_url: str = LIST_URL) -> list[dict[str, str]]:
    """Parse rendered/static 더원모바일 plan text into raw entries."""
    text = strip_tags(html)
    entries: list[dict[str, str]] = []
    pattern = re.compile(
        r"(?P<name>(?:ONE|TOP|더원|The\s*One)[가-힣A-Za-z0-9\s+()/._-]{2,80}?)\s+"
        r"(?:기본\s*월\s*)?(?P<data>\d+(?:\.\d+)?\s*(?:GB|MB|TB)[^통문월]{0,40}?)\s+"
        r"(?P<voice>(?:통화\s*)?(?:무제한|기본제공|기본 제공|\d+\s*분))\s+"
        r"(?P<sms>(?:문자\s*)?(?:무제한|기본제공|기본 제공|\d+\s*건))[^월]{0,80}?"
        r"월\s*(?P<price>[\d,]+)\s*원",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        raw = normalize_text(match.group(0))
        entries.append(
            {
                "plan_id": f"theonemobile-{_entry_id(raw)}",
                "name": normalize_text(match.group("name")),
                "data": normalize_text(match.group("data")),
                "voice": normalize_text(match.group("voice")).replace("통화", "").strip(),
                "sms": normalize_text(match.group("sms")).replace("문자", "").strip(),
                "price": match.group("price"),
                "source_url": source_url,
                "raw_text": raw,
            }
        )
    return entries


def row_to_record(row: dict[str, str]) -> PlanRecord:
    return build_record(
        vendor="theonemobile",
        plan_id=row["plan_id"],
        name=row["name"],
        monthly_fee=parse_money(row.get("price")),
        data_text=row.get("data"),
        voice_text=row.get("voice"),
        sms_text=row.get("sms"),
        network_type="KT",
        metadata={
            "detail_url": row.get("source_url"),
            "crawled_source": "official_html",
            "raw_text": row.get("raw_text"),
        },
    )


class TheOneMobileCollector(BaseCollector):
    """Collector that parses 더원모바일 official plan listing HTML."""

    async def fetch_entries(self) -> Iterable[dict[str, str]]:
        source_path = self.config.metadata.get("theonemobile_html_path")
        html = Path(source_path).read_text(encoding="utf-8") if source_path else fetch_html(LIST_URL)
        await self.save_raw_payload(html, "theonemobile_plan_list.html")
        return parse_entries_from_html(html, LIST_URL)

    async def parse_entries(self, entries: Iterable[dict[str, str]]) -> List[PlanRecord]:
        return [row_to_record(row) for row in entries]


registry.register(
    "theonemobile",
    TheOneMobileCollector,
    description="더원모바일 공식 요금제 페이지를 PlanRecord로 변환",
)
