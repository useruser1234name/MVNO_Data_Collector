"""Reference 마스터데이터 거버넌스 테스트."""
from collectors.catalog import load_catalog
from etl.reference_data import load_operators, missing_operators
from etl.schema import create_all
from sqlalchemy import create_engine, inspect


def test_operators_loaded():
    ops = load_operators()
    assert "amobile" in ops and ops["amobile"].is_mvno is True
    assert ops["skt"].group == "mno" and ops["skt"].is_mvno is False


def test_all_catalog_vendors_have_operator_row():
    # 거버넌스: 카탈로그 사업자는 모두 dim_operator에 등재돼야 한다
    keys = [e.key for e in load_catalog().all() if e.key != "example"]
    assert missing_operators(keys) == []


def test_schema_create_all_on_sqlite():
    eng = create_engine("sqlite://")
    create_all(eng)
    tables = set(inspect(eng).get_table_names())
    assert {"dim_operator", "fct_plan", "fct_plan_price"}.issubset(tables)
