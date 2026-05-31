"""가격 컴포넌트 SCD Type 2 적재 — 가격 변동·요금제 단종 이력을 보존한다.

in-place UPSERT(과거값 덮어쓰기)를 대체. 변경감지는 row_hash로 수행한다.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, Sequence

from sqlalchemy import and_, select
from sqlalchemy.engine import Engine

from etl.schema import fct_plan, fct_plan_price, metadata

logger = logging.getLogger(__name__)

# row_hash 계산에 포함하는 가격 속성(이 값들이 바뀌면 새 버전으로 본다)
_HASH_FIELDS = ("price_type", "monthly_fee", "commitment_months")
_NATURAL_KEY = ("vendor", "plan_id", "price_type")


def compute_row_hash(record: Mapping) -> str:
    parts = [f"{k}={record.get(k)}" for k in _HASH_FIELDS]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class Scd2Stats:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    expired: int = 0


class Scd2PriceLoader:
    """fct_plan_price를 SCD2로 적재한다."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def ensure_schema(self) -> None:
        metadata.create_all(self.engine)

    def load(self, records: Sequence[Mapping], collected_at: datetime) -> Scd2Stats:
        """가격 레코드 목록을 SCD2로 병합.

        각 record: {vendor, plan_id, price_type, monthly_fee, commitment_months?}
        """
        stats = Scd2Stats()
        with self.engine.begin() as conn:
            for record in records:
                new_hash = compute_row_hash(record)
                current = conn.execute(
                    select(fct_plan_price).where(
                        and_(
                            fct_plan_price.c.vendor == record["vendor"],
                            fct_plan_price.c.plan_id == record["plan_id"],
                            fct_plan_price.c.price_type == record["price_type"],
                            fct_plan_price.c.is_current.is_(True),
                        )
                    )
                ).fetchone()

                if current is None:
                    self._insert(conn, record, new_hash, collected_at)
                    stats.inserted += 1
                elif current.row_hash == new_hash:
                    stats.unchanged += 1
                else:
                    self._close(conn, current.id, collected_at)
                    self._insert(conn, record, new_hash, collected_at)
                    stats.updated += 1
        logger.info("SCD2 load: %s", stats)
        return stats

    def expire_missing(
        self, present_keys: Iterable[tuple], collected_at: datetime
    ) -> int:
        """이번 수집에 없는(=단종 의심) 현재 행을 만료 처리.

        주의: 수집 정상 확인(완주율 게이트) 후에만 호출해야 멀쩡한 요금제를
        단종으로 오기록하지 않는다.
        """
        present = set(present_keys)
        expired = 0
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(fct_plan_price).where(fct_plan_price.c.is_current.is_(True))
            ).fetchall()
            for row in rows:
                key = (row.vendor, row.plan_id, row.price_type)
                if key not in present:
                    self._close(conn, row.id, collected_at)
                    expired += 1
        return expired

    def _insert(self, conn, record: Mapping, row_hash: str, collected_at: datetime) -> None:
        conn.execute(
            fct_plan_price.insert().values(
                vendor=record["vendor"],
                plan_id=record["plan_id"],
                price_type=record["price_type"],
                monthly_fee=float(record["monthly_fee"]),
                commitment_months=record.get("commitment_months"),
                row_hash=row_hash,
                valid_from=collected_at,
                valid_to=None,
                is_current=True,
                collected_at=collected_at,
            )
        )

    def _close(self, conn, row_id: int, collected_at: datetime) -> None:
        conn.execute(
            fct_plan_price.update()
            .where(fct_plan_price.c.id == row_id)
            .values(valid_to=collected_at, is_current=False)
        )


def explode_price_components(plan_record: Mapping) -> list[dict]:
    """PlanRecord(dict)를 가격 컴포넌트 행 목록으로 전개.

    price_components가 있으면 각 컴포넌트를, 없으면 monthly_fee를 '정상가'로 사용.
    """
    vendor = plan_record["vendor"]
    plan_id = plan_record["plan_id"]
    components = plan_record.get("price_components") or []
    if components:
        return [
            {
                "vendor": vendor,
                "plan_id": plan_id,
                "price_type": c.get("price_type", "정상가"),
                "monthly_fee": c.get("monthly_fee", 0.0),
                "commitment_months": c.get("commitment_months"),
            }
            for c in components
        ]
    return [
        {
            "vendor": vendor,
            "plan_id": plan_id,
            "price_type": "정상가",
            "monthly_fee": plan_record.get("monthly_fee", 0.0),
            "commitment_months": None,
        }
    ]
