"""Collector for KT M모바일 records captured from modal crawl CSV exports."""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Iterable, List

from collectors.base import BaseCollector
from collectors.registry import registry
from schemas.plan_record import PlanRecord

DEFAULT_MODAL_CSV = Path("ktmm_out/ktmmobile_modal_data.csv")


def parse_money(value: str | int | float | None) -> float:
    """Parse a Korean won amount from a text or numeric CSV value."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    digits = re.findall(r"\d+", value.replace(",", ""))
    return float("".join(digits)) if digits else 0.0


def parse_data_allowance_mb(*values: str | None) -> tuple[int, dict[str, Any]]:
    """Infer the first advertised data allowance from plan text values."""
    source = " ".join(value or "" for value in values)
    normalized = re.sub(r"\s+", " ", source).strip()
    metadata: dict[str, Any] = {"data_allowance_source": normalized} if normalized else {}
    if "무제한" in normalized:
        metadata["unlimited_data"] = True
        return 0, metadata

    match = re.search(r"(\d+(?:\.\d+)?)\s*(TB|GB|MB)", normalized, flags=re.IGNORECASE)
    if not match:
        return 0, metadata

    amount = float(match.group(1))
    unit = match.group(2).upper()
    if unit == "TB":
        amount *= 1024 * 1024
    elif unit == "GB":
        amount *= 1024
    return int(amount), metadata


def row_to_record(row: dict[str, str]) -> PlanRecord:
    """Convert a KT M모바일 modal CSV row into a normalized plan record."""
    card_index = (row.get("card_index") or "").strip()
    title = (row.get("modal_title") or row.get("list_title") or "").strip()
    plan_id = f"ktmmobile-{card_index or re.sub(r'[^0-9A-Za-z가-힣]+', '-', title).strip('-')}"
    data_allowance_mb, data_meta = parse_data_allowance_mb(row.get("modal_title"), row.get("list_title"))

    metadata: dict[str, Any] = {
        "source_csv": str(DEFAULT_MODAL_CSV),
        "tab_name": row.get("tab_name"),
        "card_index": card_index,
        "list_title": row.get("list_title"),
        "modal_price_text": row.get("modal_price_text"),
        "modal_html_path": row.get("modal_html_path"),
        "modal_png_path": row.get("modal_png_path"),
        "crawled_source": "local_modal_csv",
    }
    metadata.update(data_meta)

    return PlanRecord(
        vendor="ktmmobile",
        plan_id=plan_id,
        name=title or plan_id,
        monthly_fee=parse_money(row.get("modal_price") or row.get("modal_price_text")),
        data_allowance_mb=data_allowance_mb,
        voice_minutes=None,
        sms_count=None,
        network_type="LTE/5G",
        promotion=row.get("speed_toplist_modal") or row.get("speed_dataguide_modal") or None,
        metadata=metadata,
    )


class KTMmobileCollector(BaseCollector):
    """Collector that normalizes existing KT M모바일 modal crawl CSV data."""

    @property
    def csv_path(self) -> Path:
        configured = self.config.metadata.get("ktmmobile_csv_path")
        return Path(configured) if configured else DEFAULT_MODAL_CSV

    async def fetch_entries(self) -> Iterable[dict[str, str]]:
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
            return [row for row in csv.DictReader(fh) if any(row.values())]

    async def parse_entries(self, entries: Iterable[dict[str, str]]) -> List[PlanRecord]:
        return [row_to_record(row) for row in entries]


registry.register(
    "ktmmobile",
    KTMmobileCollector,
    description="KT M모바일 모달 크롤링 CSV를 PlanRecord로 변환",
)
