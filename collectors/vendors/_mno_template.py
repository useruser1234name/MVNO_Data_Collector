"""이통3사(MNO) 수집기 템플릿 — 복사해 vendor별 구현 시작점으로 사용.

언더스코어 프리픽스(_)로 시작하므로 discover_collectors가 import하지만 registry.register는
실제 구현 완료 후 주석을 해제한다. MVNO와 분리된 전용 트랙:
  - 스텔스 Playwright 컨텍스트(collectors.utils.playwright.stealth_context)
  - 내부 JSON API 우선 역설계(ApiFetcher) → 실패 시 HTML 폴백
  - 약정/선택약정/결합할인 다단계 가격 → PlanRecord.price_components
  - 보수적 스케줄/저빈도/robots 준수(collectors.utils.robots)

주의: 이통3사는 ToS·안티봇·법적 고려가 크다. docs/LEGAL_GUARDRAILS.md 준수.
"""
from __future__ import annotations

import logging
from typing import Iterable, List

from collectors.base import BaseCollector
from schemas.plan_record import PlanRecord, PriceComponent

logger = logging.getLogger(__name__)


class MnoCollectorTemplate(BaseCollector):
    """이통3사 수집기 골격. fetch_entries/parse_entries를 vendor별로 구현."""

    VENDOR = "mno_template"

    async def fetch_entries(self) -> Iterable[dict]:
        # 1순위: 내부 JSON API 역설계(ApiFetcher). 2순위: stealth_context로 렌더링 후 HTML.
        raise NotImplementedError("이통3사 수집기 구현 필요 (API 우선 탐색 → HTML 폴백)")

    async def parse_entries(self, entries: Iterable[dict]) -> List[PlanRecord]:
        records: List[PlanRecord] = []
        for entry in entries:
            # 약정/선택약정/프로모션 가격을 price_components로 다단계 표현하는 예시 골격:
            components = [
                PriceComponent(price_type="정상가", monthly_fee=entry["fee_normal"]),
            ]
            if entry.get("fee_select_agreement") is not None:
                components.append(
                    PriceComponent(
                        price_type="선택약정",
                        monthly_fee=entry["fee_select_agreement"],
                        commitment_months=entry.get("commitment_months", 24),
                    )
                )
            records.append(
                PlanRecord(
                    vendor=self.VENDOR,
                    plan_id=entry["plan_id"],
                    name=entry["name"],
                    monthly_fee=float(entry["fee_normal"]),
                    data_allowance_mb=entry.get("data_allowance_mb"),
                    voice_minutes=entry.get("voice_minutes"),
                    sms_count=entry.get("sms_count"),
                    network_type=entry.get("network_type", "5G"),
                    price_components=components,
                    metadata={"source": "mno_template"},
                )
            )
        return records


# 구현 완료 후 등록:
# from collectors.registry import registry
# registry.register("skt", SktCollector, description="SKT 다이렉트 요금제 수집기")
