"""Shared helpers for lightweight MVNO HTML plan collectors."""
from __future__ import annotations

import html
import re
import urllib.request
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from schemas.plan_record import PlanRecord

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class TextExtractor(HTMLParser):
    """Small HTML text extractor that avoids optional BeautifulSoup/lxml deps."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.parts.append(value)

    def text(self) -> str:
        return normalize_text(" ".join(self.parts))


def fetch_html(url: str, timeout: int = 20) -> str:
    """Fetch HTML using the standard library so collectors have no hard deps."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def normalize_text(value: str | None) -> str:
    """Collapse whitespace and unescape entities."""
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def strip_tags(fragment: str) -> str:
    """Return normalized visible text for an HTML fragment."""
    parser = TextExtractor()
    parser.feed(fragment)
    return parser.text()


def parse_money(value: str | int | float | None) -> float:
    """Parse Korean won text into a numeric amount."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    digits = re.findall(r"\d+", value.replace(",", ""))
    return float("".join(digits)) if digits else 0.0


def parse_data_allowance_mb(value: str | None) -> tuple[int, dict[str, Any]]:
    """Parse an advertised data allowance into MB and keep raw/QoS hints."""
    normalized = normalize_text(value)
    metadata: dict[str, Any] = {"data_raw": normalized} if normalized else {}
    if not normalized:
        return 0, metadata
    if "무제한" in normalized and not re.search(r"\d+(?:\.\d+)?\s*(?:TB|GB|MB)", normalized, re.IGNORECASE):
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


def parse_count(value: str | None, unit: str, metadata_key: str) -> tuple[int | None, dict[str, Any]]:
    """Parse voice/SMS limits while preserving unlimited/basic labels."""
    normalized = normalize_text(value)
    metadata: dict[str, Any] = {f"{metadata_key}_raw": normalized} if normalized else {}
    if not normalized:
        return None, metadata
    if any(token in normalized for token in ["무제한", "기본제공", "기본 제공"]):
        metadata[metadata_key] = True
        return None, metadata
    match = re.search(rf"(\d+)\s*{unit}", normalized)
    if match:
        return int(match.group(1)), metadata
    return None, metadata


def absolute_url(base_url: str, url: str | None) -> str | None:
    """Build an absolute URL when a relative href is available."""
    if not url:
        return None
    return urljoin(base_url, html.unescape(url))


def build_record(
    *,
    vendor: str,
    plan_id: str,
    name: str,
    monthly_fee: float,
    data_text: str | None,
    voice_text: str | None = None,
    sms_text: str | None = None,
    network_type: str | None = None,
    promotion: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> PlanRecord:
    """Build a PlanRecord from commonly parsed text fields."""
    data_allowance_mb, data_meta = parse_data_allowance_mb(data_text)
    voice_minutes, voice_meta = parse_count(voice_text, "분", "voice_unlimited")
    sms_count, sms_meta = parse_count(sms_text, "건", "sms_unlimited")
    merged_metadata = metadata.copy() if metadata else {}
    merged_metadata.update(data_meta)
    merged_metadata.update(voice_meta)
    merged_metadata.update(sms_meta)
    return PlanRecord(
        vendor=vendor,
        plan_id=plan_id,
        name=name,
        monthly_fee=monthly_fee,
        data_allowance_mb=data_allowance_mb,
        voice_minutes=voice_minutes,
        sms_count=sms_count,
        network_type=network_type,
        promotion=promotion,
        metadata=merged_metadata,
    )
