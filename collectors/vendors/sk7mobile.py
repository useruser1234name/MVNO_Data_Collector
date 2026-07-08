"""Collector for SK 세븐모바일 records captured from detail crawl CSV exports."""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Iterable, List

from collectors.base import BaseCollector
from collectors.registry import registry
from schemas.plan_record import PlanRecord

DEFAULT_DETAIL_CSV = Path("SK_SevenMobile/sk7_detail_crawl.csv")


def parse_money(value: str | int | float | None) -> float:
    """Parse a numeric price field from SK 7mobile CSV data."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    digits = re.findall(r"\d+", value.replace(",", ""))
    return float("".join(digits)) if digits else 0.0


def parse_data_allowance_mb(value: str | None) -> tuple[int, dict[str, Any]]:
    """Parse data allowance text such as 300MB, 1.2GB, or unlimited labels."""
    normalized = re.sub(r"\s+", " ", value or "").strip()
    metadata: dict[str, Any] = {"data_raw": normalized} if normalized else {}
    if not normalized:
        return 0, metadata
    if any(token in normalized for token in ["무제한", "기본제공"]):
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


def parse_limited_count(value: str | None, unit_pattern: str, unlimited_key: str) -> tuple[int | None, dict[str, Any]]:
    """Parse limited voice/SMS allowances and preserve unlimited/basic labels."""
    normalized = re.sub(r"\s+", " ", value or "").strip()
    metadata: dict[str, Any] = {}
    if not normalized:
        return None, metadata
    metadata[f"{unlimited_key}_raw"] = normalized
    if any(token in normalized for token in ["무제한", "기본제공"]):
        metadata[unlimited_key] = True
        return None, metadata

    match = re.search(rf"(\d+)\s*{unit_pattern}", normalized)
    if match:
        return int(match.group(1)), metadata
    return None, metadata


def row_to_record(row: dict[str, str]) -> PlanRecord:
    """Convert an SK 7mobile detail CSV row into a normalized plan record."""
    data_allowance_mb, data_meta = parse_data_allowance_mb(row.get("data"))
    voice_minutes, voice_meta = parse_limited_count(row.get("voice"), "분", "voice_unlimited")
    sms_count, sms_meta = parse_limited_count(row.get("sms"), "건", "sms_unlimited")
    monthly_fee = parse_money(row.get("price_promo") or row.get("price_base"))

    badges = [badge for badge in (row.get("badges") or "").split("|") if badge]
    network_type = next((badge for badge in badges if badge in {"3G", "LTE", "5G"}), None)
    metadata: dict[str, Any] = {
        "source_csv": str(DEFAULT_DETAIL_CSV),
        "refCode": row.get("refCode"),
        "searchCallPlanType": row.get("searchCallPlanType"),
        "price_base": parse_money(row.get("price_base")),
        "price_promo": parse_money(row.get("price_promo")),
        "badges": badges,
        "detail_url": row.get("url"),
        "crawled_source": "local_detail_csv",
    }
    metadata.update(data_meta)
    metadata.update(voice_meta)
    metadata.update(sms_meta)

    return PlanRecord(
        vendor="sk7mobile",
        plan_id=(row.get("prodCd") or row.get("title") or "unknown").strip(),
        name=(row.get("title") or "").strip() or (row.get("prodCd") or "unknown"),
        monthly_fee=monthly_fee,
        data_allowance_mb=data_allowance_mb,
        voice_minutes=voice_minutes,
        sms_count=sms_count,
        network_type=network_type,
        promotion="|".join(badges) if badges else None,
        metadata=metadata,
    )


class SK7MobileCollector(BaseCollector):
    """Collector that normalizes existing SK 7mobile detail crawl CSV data."""

    @property
    def csv_path(self) -> Path:
        configured = self.config.metadata.get("sk7mobile_csv_path")
        return Path(configured) if configured else DEFAULT_DETAIL_CSV

    async def fetch_entries(self) -> Iterable[dict[str, str]]:
        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
            return [row for row in csv.DictReader(fh) if any(row.values())]

    async def parse_entries(self, entries: Iterable[dict[str, str]]) -> List[PlanRecord]:
        return [row_to_record(row) for row in entries]


registry.register(
    "sk7mobile",
    SK7MobileCollector,
    description="SK 세븐모바일 상세 크롤링 CSV를 PlanRecord로 변환",
)
