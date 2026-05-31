"""initial mart: dim_operator, fct_plan, fct_plan_price (SCD2)

Revision ID: 0001
Revises:
Create Date: 2026-05-31

단일 진실원천 etl.schema.metadata 로부터 테이블을 생성한다.
"""
from __future__ import annotations

from alembic import op

from etl.schema import metadata

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata.create_all(bind)


def downgrade() -> None:
    bind = op.get_bind()
    metadata.drop_all(bind)
