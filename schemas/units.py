"""단위·금액·무제한 정규화의 단일 출처(single source of truth).

벤더 수집기마다 제각각 구현하던 데이터량/음성/문자/금액/속도 파싱을 한 곳으로 모은다.
핵심 설계: '진짜 0', '무제한', '파싱 실패'를 단일 0/None으로 뭉개지 않고
:class:`ParsedQuantity` 의 ``status`` 로 명시적으로 구분한다(침묵형 오염 방지).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# 무제한을 의미하는 한국어/영어 표현
_UNLIMITED_PATTERNS = (
    "무제한",
    "무한",
    "unlimited",
    "기본제공",  # 일부 사업자에서 '기본 제공(무제한)' 의미로 사용
)

# 데이터 단위 → MB 배수. 'M', 'MB' 모두 허용(과거 '500M' 미매칭 버그 수정).
_DATA_UNIT_TO_MB = {
    "T": 1024 * 1024,
    "G": 1024,
    "M": 1,
}
_DATA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(T|G|M)B?", re.IGNORECASE)
_VOICE_RE = re.compile(r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*분")
_SMS_RE = re.compile(r"(\d+(?:,\d{3})*)\s*건")
_SPEED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(Mbps|Kbps|Gbps)", re.IGNORECASE)
_MONEY_RE = re.compile(r"\d[\d,]*")

# 파싱 상태 코드
STATUS_OK = "ok"
STATUS_UNLIMITED = "unlimited"
STATUS_MISSING = "missing"
STATUS_UNPARSED = "unparsed"


@dataclass(slots=True)
class ParsedQuantity:
    """수량 파싱 결과. value/unlimited/status로 의미를 명확히 분리한다."""

    value: Optional[int]
    unlimited: bool
    status: str
    raw: Optional[str]

    @property
    def ok(self) -> bool:
        return self.status in (STATUS_OK, STATUS_UNLIMITED)


def _normalize(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed or None


def classify_unlimited(text: Optional[str]) -> bool:
    """텍스트가 무제한을 의미하는지 판별."""
    norm = _normalize(text)
    if not norm:
        return False
    lowered = norm.lower()
    return any(pat.lower() in lowered for pat in _UNLIMITED_PATTERNS)


def parse_data_to_mb(text: Optional[str]) -> ParsedQuantity:
    """데이터 제공량을 MB로 정규화. 'TB/GB/MB' 및 'T/G/M' 약식 모두 지원."""
    norm = _normalize(text)
    if not norm:
        return ParsedQuantity(None, False, STATUS_MISSING, text)
    if classify_unlimited(norm):
        return ParsedQuantity(None, True, STATUS_UNLIMITED, norm)
    match = _DATA_RE.search(norm)
    if not match:
        return ParsedQuantity(None, False, STATUS_UNPARSED, norm)
    value = float(match.group(1))
    unit = match.group(2).upper()
    mb = int(round(value * _DATA_UNIT_TO_MB[unit]))
    return ParsedQuantity(mb, False, STATUS_OK, norm)


def parse_voice(text: Optional[str]) -> ParsedQuantity:
    """음성 제공량(분)을 정규화. '무제한'은 unlimited=True."""
    norm = _normalize(text)
    if not norm:
        return ParsedQuantity(None, False, STATUS_MISSING, text)
    if classify_unlimited(norm):
        return ParsedQuantity(None, True, STATUS_UNLIMITED, norm)
    match = _VOICE_RE.search(norm)
    if not match:
        return ParsedQuantity(None, False, STATUS_UNPARSED, norm)
    minutes = int(float(match.group(1).replace(",", "")))
    return ParsedQuantity(minutes, False, STATUS_OK, norm)


def parse_sms(text: Optional[str]) -> ParsedQuantity:
    """문자 제공량(건)을 정규화. '무제한'은 unlimited=True."""
    norm = _normalize(text)
    if not norm:
        return ParsedQuantity(None, False, STATUS_MISSING, text)
    if classify_unlimited(norm):
        return ParsedQuantity(None, True, STATUS_UNLIMITED, norm)
    match = _SMS_RE.search(norm)
    if not match:
        return ParsedQuantity(None, False, STATUS_UNPARSED, norm)
    count = int(match.group(1).replace(",", ""))
    return ParsedQuantity(count, False, STATUS_OK, norm)


def parse_money(text: Optional[str]) -> Optional[int]:
    """KRW 금액을 정수로 파싱. 첫 번째 숫자 토큰을 사용(부가세 포함값 가정)."""
    norm = _normalize(text)
    if not norm:
        return None
    match = _MONEY_RE.search(norm)
    if not match:
        return None
    return int(match.group(0).replace(",", ""))


def parse_speed_to_kbps(text: Optional[str]) -> Optional[int]:
    """QoS 속도제어 값을 kbps로 정규화(5G 무제한 후 속도제한 비교용)."""
    norm = _normalize(text)
    if not norm:
        return None
    match = _SPEED_RE.search(norm)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "gbps":
        return int(round(value * 1_000_000))
    if unit == "mbps":
        return int(round(value * 1000))
    return int(round(value))  # kbps
