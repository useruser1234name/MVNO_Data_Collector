"""SCD2 가격 적재 통합 테스트 (sqlite in-memory)."""
from datetime import datetime

import pytest
from sqlalchemy import create_engine, select

from etl.schema import fct_plan_price
from etl.scd2 import Scd2PriceLoader, compute_row_hash, explode_price_components


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    Scd2PriceLoader(eng).ensure_schema()
    return eng


def _rec(fee, plan_id="p1", price_type="정상가"):
    return {"vendor": "amobile", "plan_id": plan_id, "price_type": price_type, "monthly_fee": fee}


def _current_rows(engine):
    with engine.connect() as conn:
        return conn.execute(
            select(fct_plan_price).where(fct_plan_price.c.is_current.is_(True))
        ).fetchall()


def test_initial_insert(engine):
    loader = Scd2PriceLoader(engine)
    stats = loader.load([_rec(10000)], collected_at=datetime(2026, 1, 1))
    assert stats.inserted == 1
    rows = _current_rows(engine)
    assert len(rows) == 1 and rows[0].monthly_fee == 10000


def test_unchanged_is_noop(engine):
    loader = Scd2PriceLoader(engine)
    loader.load([_rec(10000)], collected_at=datetime(2026, 1, 1))
    stats = loader.load([_rec(10000)], collected_at=datetime(2026, 1, 2))
    assert stats.unchanged == 1 and stats.updated == 0
    assert len(_current_rows(engine)) == 1


def test_price_change_creates_new_version(engine):
    loader = Scd2PriceLoader(engine)
    loader.load([_rec(10000)], collected_at=datetime(2026, 1, 1))
    stats = loader.load([_rec(9000)], collected_at=datetime(2026, 1, 2))
    assert stats.updated == 1
    # 현재 행은 1개(9000), 과거 행은 닫힘
    current = _current_rows(engine)
    assert len(current) == 1 and current[0].monthly_fee == 9000
    with engine.connect() as conn:
        all_rows = conn.execute(select(fct_plan_price)).fetchall()
    assert len(all_rows) == 2
    closed = [r for r in all_rows if not r.is_current][0]
    assert closed.monthly_fee == 10000 and closed.valid_to == datetime(2026, 1, 2)


def test_expire_missing_marks_discontinued(engine):
    loader = Scd2PriceLoader(engine)
    loader.load([_rec(10000, plan_id="p1"), _rec(20000, plan_id="p2")],
                collected_at=datetime(2026, 1, 1))
    # 다음 수집에 p1만 존재 → p2는 단종 만료
    expired = loader.expire_missing(
        present_keys=[("amobile", "p1", "정상가")], collected_at=datetime(2026, 1, 3)
    )
    assert expired == 1
    current_ids = {(r.plan_id) for r in _current_rows(engine)}
    assert current_ids == {"p1"}


def test_row_hash_changes_with_fee():
    assert compute_row_hash(_rec(10000)) != compute_row_hash(_rec(9000))


def test_explode_uses_normal_price_when_no_components():
    rows = explode_price_components({"vendor": "v", "plan_id": "p", "monthly_fee": 5000})
    assert len(rows) == 1 and rows[0]["price_type"] == "정상가" and rows[0]["monthly_fee"] == 5000


def test_explode_multiple_components():
    plan = {
        "vendor": "skt", "plan_id": "5g-1", "monthly_fee": 55000,
        "price_components": [
            {"price_type": "정상가", "monthly_fee": 55000},
            {"price_type": "선택약정", "monthly_fee": 41250, "commitment_months": 24},
        ],
    }
    rows = explode_price_components(plan)
    assert len(rows) == 2
    assert rows[1]["commitment_months"] == 24
