"""통합 데이터 모델(SQLAlchemy Core) — sqlite/postgres 양쪽에서 동작.

헤더-가격 분리:
  dim_operator      : 사업자 마스터(정규명/그룹/망)
  fct_plan          : 요금제 헤더(자연키 vendor+plan_id, 회선/데이터/음성/문자)
  fct_plan_price    : 가격 컴포넌트 SCD2 이력(약정/선택약정/프로모션별, 변동 추적)

DDL을 코드(Core MetaData)로 보유해 데이터 계약·마이그레이션·테스트를 일원화한다.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()

dim_operator = Table(
    "dim_operator",
    metadata,
    Column("operator_key", String(64), primary_key=True),
    Column("display_name", String(128), nullable=False),
    Column("group", String(16), nullable=False),  # mvno | mno
    Column("network", String(32)),
    Column("is_mvno", Boolean, nullable=False, default=True),
)

fct_plan = Table(
    "fct_plan",
    metadata,
    Column("plan_sk", Integer, primary_key=True, autoincrement=True),
    Column("vendor", String(64), nullable=False),
    Column("plan_id", String(128), nullable=False),
    Column("name", Text, nullable=False),
    Column("network_type", String(32)),
    Column("data_allowance_mb", Integer),
    Column("voice_minutes", Integer),
    Column("sms_count", Integer),
    Column("data_unlimited", Boolean, default=False),
    Column("voice_unlimited", Boolean, default=False),
    Column("sms_unlimited", Boolean, default=False),
    UniqueConstraint("vendor", "plan_id", name="uq_fct_plan_natural_key"),
)

fct_plan_price = Table(
    "fct_plan_price",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("vendor", String(64), nullable=False),
    Column("plan_id", String(128), nullable=False),
    Column("price_type", String(32), nullable=False),  # 정상가/약정할인/선택약정/프로모션
    Column("monthly_fee", Float, nullable=False),
    Column("commitment_months", Integer),
    Column("row_hash", String(64), nullable=False),
    Column("valid_from", DateTime, nullable=False),
    Column("valid_to", DateTime),  # NULL = 현재 유효
    Column("is_current", Boolean, nullable=False, default=True),
    Column("collected_at", DateTime, nullable=False),
)


def create_all(engine) -> None:
    metadata.create_all(engine)
