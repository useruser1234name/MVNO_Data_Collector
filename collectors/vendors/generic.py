"""설정주도(config-driven) 범용 수집기.

단순 표/리스트형 MVNO 다수를 코드 작성 없이 policy.json(셀렉터 매핑)만으로 수집한다.
그동안 데드코드였던 collectors/policy.py(FieldPolicySet)를 실제 추출에 연결한다.

CollectorConfig.metadata 스펙:
  row_selector : 요금제 1건에 해당하는 행 컨테이너 CSS 셀렉터(필수)
  vendor       : PlanRecord.vendor (기본: config.name)
  html_paths   : 로컬 HTML 파일 경로 목록(오프라인/테스트)
  list_urls    : 수집 대상 목록 URL(HttpFetcher 사용)
field_policy   : 컬럼(NAME/PRICE/DATA/VOICE/SMS/PLAN_ID) → 셀렉터 정책
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Iterable, List, Optional

from bs4 import BeautifulSoup

from collectors.base import BaseCollector, CollectorConfig
from collectors.fetchers import HttpFetcher
from collectors.policy import FieldPolicySet, load_policy_file
from schemas import units
from schemas.plan_record import PlanRecord

logger = logging.getLogger(__name__)

COL_NAME = "NAME"
COL_PRICE = "PRICE"
COL_DATA = "DATA"
COL_VOICE = "VOICE"
COL_SMS = "SMS"
COL_PLAN_ID = "PLAN_ID"
COL_NETWORK = "NETWORK"


class GenericCollector(BaseCollector):
    """policy.json 기반 범용 HTML 리스트/테이블 수집기."""

    async def fetch_entries(self) -> Iterable[str]:
        return await asyncio.to_thread(self._fetch_sync)

    def _fetch_sync(self) -> List[str]:
        meta = self.config.metadata
        htmls: List[str] = []
        for path in meta.get("html_paths", []) or []:
            htmls.append(Path(path).read_text(encoding="utf-8", errors="ignore"))
        urls = meta.get("list_urls") or []
        if urls:
            fetcher = HttpFetcher()
            try:
                for url in urls:
                    htmls.append(fetcher.fetch_text(url))
            finally:
                fetcher.close()
        return htmls

    async def parse_entries(self, entries: Iterable[str]) -> List[PlanRecord]:
        return await asyncio.to_thread(self._parse_sync, list(entries))

    def _parse_sync(self, htmls: List[str]) -> List[PlanRecord]:
        policy = self.field_policy
        if policy is None:
            raise ValueError("GenericCollector requires a field_policy")
        row_selector = self.config.metadata.get("row_selector")
        if not row_selector:
            raise ValueError("GenericCollector requires metadata['row_selector']")
        vendor = self.config.metadata.get("vendor", self.config.name)

        records: List[PlanRecord] = []
        for html in htmls:
            soup = BeautifulSoup(html, "lxml")
            for index, row in enumerate(soup.select(row_selector)):
                record = self._row_to_record(row, policy, vendor, index)
                if record is not None:
                    records.append(record)
        logger.info("GenericCollector(%s) parsed %d records", vendor, len(records))
        return records

    @staticmethod
    def _extract(row, column: str, policy: FieldPolicySet) -> Optional[str]:
        for option in policy.selectors_for(column):
            node = row.select_one(option.selector)
            if not node:
                continue
            if option.attribute:
                value = node.get(option.attribute)
            else:
                value = node.get_text(strip=True)
            if value:
                return value.strip() if isinstance(value, str) else value
        return None

    def _row_to_record(self, row, policy: FieldPolicySet, vendor: str, index: int) -> Optional[PlanRecord]:
        name = self._extract(row, COL_NAME, policy)
        if not name:
            return None  # 이름 없는 행은 헤더/장식으로 간주

        data_q = units.parse_data_to_mb(self._extract(row, COL_DATA, policy))
        voice_q = units.parse_voice(self._extract(row, COL_VOICE, policy))
        sms_q = units.parse_sms(self._extract(row, COL_SMS, policy))
        price_text = self._extract(row, COL_PRICE, policy)
        monthly_fee = units.parse_money(price_text)

        plan_id = self._extract(row, COL_PLAN_ID, policy) or f"{name}#{index}"
        network_type = self._extract(row, COL_NETWORK, policy)

        if monthly_fee is not None:
            fee_status = units.STATUS_OK
        else:
            fee_status = units.STATUS_MISSING if not price_text else units.STATUS_UNPARSED
            monthly_fee = 0

        parse_status = {
            "data": data_q.status,
            "voice": voice_q.status,
            "sms": sms_q.status,
            "fee": fee_status,
        }

        return PlanRecord(
            vendor=vendor,
            plan_id=plan_id,
            name=name,
            monthly_fee=float(monthly_fee),
            data_allowance_mb=data_q.value,
            voice_minutes=voice_q.value,
            sms_count=sms_q.value,
            network_type=network_type,
            data_unlimited=data_q.unlimited,
            voice_unlimited=voice_q.unlimited,
            sms_unlimited=sms_q.unlimited,
            parse_status=parse_status,
            metadata={"raw_price": price_text},
        )


def build_generic_collector(
    name: str,
    output_dir: Path,
    policy_file: Path,
    row_selector: str,
    vendor: Optional[str] = None,
    html_paths: Optional[List[str]] = None,
    list_urls: Optional[List[str]] = None,
) -> GenericCollector:
    """카탈로그 generic 항목으로부터 GenericCollector를 구성하는 팩토리."""
    policies = load_policy_file(policy_file)
    vendor_key = vendor or name
    policy = policies.get(vendor_key) or next(iter(policies.values()), None)
    config = CollectorConfig(
        name=name,
        output_dir=output_dir,
        metadata={
            "row_selector": row_selector,
            "vendor": vendor_key,
            "html_paths": html_paths or [],
            "list_urls": list_urls or [],
        },
        field_policy=policy,
    )
    return GenericCollector(config)
