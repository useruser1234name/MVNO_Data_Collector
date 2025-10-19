"""Shared schema definitions for normalized plan records."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


@dataclass(slots=True)
class PlanRecord:
    """Normalized representation of a MVNO plan."""

    vendor: str
    plan_id: str
    name: str
    monthly_fee: float
    data_allowance_mb: int
    voice_minutes: Optional[int]
    sms_count: Optional[int]
    network_type: Optional[str] = None
    promotion: Optional[str] = None
    effective_date: Optional[date] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.vendor:
            raise ValueError("vendor is required")
        if not self.plan_id:
            raise ValueError("plan_id is required")
        if self.monthly_fee < 0:
            raise ValueError("monthly_fee must be non-negative")
        if self.data_allowance_mb < 0:
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
            "metadata": self.metadata,
        }
        if self.effective_date:
            payload["effective_date"] = self.effective_date.isoformat()
        return payload
