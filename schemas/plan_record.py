"""Shared schema definitions for normalized plan records."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, List, Optional


@dataclass(slots=True)
class PriceComponent:
    """요금제의 단일 가격 변형(정상가/약정할인/선택약정/프로모션 등).

    이통3사·결합할인처럼 한 요금제가 조건별로 여러 가격을 갖는 경우를 표현한다.
    """

    price_type: str  # 정상가 | 약정할인 | 선택약정 | 결합할인 | 프로모션
    monthly_fee: float
    commitment_months: Optional[int] = None
    promo_period_months: Optional[int] = None
    post_promo_fee: Optional[float] = None
    discount_kind: Optional[str] = None
    note: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.price_type:
            raise ValueError("price_type is required")
        if self.monthly_fee < 0:
            raise ValueError("monthly_fee must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "price_type": self.price_type,
            "monthly_fee": self.monthly_fee,
            "commitment_months": self.commitment_months,
            "promo_period_months": self.promo_period_months,
            "post_promo_fee": self.post_promo_fee,
            "discount_kind": self.discount_kind,
            "note": self.note,
        }


@dataclass(slots=True)
class PlanRecord:
    """Normalized representation of a MVNO/MNO plan.

    무제한/결측/실패를 0·None으로 뭉개지 않도록 ``*_unlimited`` 플래그와
    ``parse_status`` 를 1급 필드로 둔다. ``data_allowance_mb`` 등 수치 필드는
    하위호환을 위해 유지하되, 무제한/실패 시 None을 허용한다.
    """

    vendor: str
    plan_id: str
    name: str
    monthly_fee: float
    data_allowance_mb: Optional[int]
    voice_minutes: Optional[int]
    sms_count: Optional[int]
    network_type: Optional[str] = None
    promotion: Optional[str] = None
    effective_date: Optional[date] = None
    # 1급 무제한/결측 구분 플래그
    data_unlimited: bool = False
    voice_unlimited: bool = False
    sms_unlimited: bool = False
    # 필드별 파싱 상태(units.STATUS_*). 하류 품질 게이트에서 격리 판단에 사용.
    parse_status: dict[str, str] = field(default_factory=dict)
    # 가격 다단계(이통3사·결합/약정). 비어있으면 monthly_fee 단일 가격으로 해석.
    price_components: List[PriceComponent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.vendor:
            raise ValueError("vendor is required")
        if not self.plan_id:
            raise ValueError("plan_id is required")
        if self.monthly_fee < 0:
            raise ValueError("monthly_fee must be non-negative")
        if self.data_allowance_mb is not None and self.data_allowance_mb < 0:
            raise ValueError("data_allowance_mb must be non-negative")
        if self.voice_minutes is not None and self.voice_minutes < 0:
            raise ValueError("voice_minutes must be non-negative")
        if self.sms_count is not None and self.sms_count < 0:
            raise ValueError("sms_count must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "vendor": self.vendor,
            "plan_id": self.plan_id,
            "name": self.name,
            "monthly_fee": self.monthly_fee,
            "data_allowance_mb": self.data_allowance_mb,
            "voice_minutes": self.voice_minutes,
            "sms_count": self.sms_count,
            "network_type": self.network_type,
            "promotion": self.promotion,
            "data_unlimited": self.data_unlimited,
            "voice_unlimited": self.voice_unlimited,
            "sms_unlimited": self.sms_unlimited,
            "parse_status": self.parse_status,
            "price_components": [pc.to_dict() for pc in self.price_components],
            "metadata": self.metadata,
        }
        if self.effective_date:
            payload["effective_date"] = self.effective_date.isoformat()
        return payload
