"""동적 통합 테스트(E2E): 수집 → JSONL → transform → SCD2 마트 적재 전 구간.

실제 등록된 amobile 수집기를 run_all 경로로 실행하고, 산출 JSONL을 transform으로
검증한 뒤 SCD2 로더로 sqlite 마트에 적재한다.
"""
import asyncio
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, select

from etl.schema import fct_plan_price
from etl.scd2 import Scd2PriceLoader, explode_price_components
from etl.transform import TransformConfig, transform
from pipeline.run_collectors import discover_collectors, run_all

FIX = Path(__file__).parent / "fixtures"
REF = Path(__file__).resolve().parents[1] / "etl" / "reference"


def test_e2e_amobile_to_scd2_mart(tmp_path, monkeypatch):
    # 1) 수집: 실제 amobile 수집기를 로컬 픽스처 HTML로 실행
    monkeypatch.setenv("AMOBILE_HTML_DIR", str(FIX / "amobile"))
    discover_collectors()
    out_dir = tmp_path / "raw"
    results = asyncio.run(run_all(["amobile"], out_dir, 1, {}, {}))
    assert results[0]["records"] == 1

    # 2) 산출물 위치 확인 + transform(규칙기반 quarantine)
    jsonl = next((out_dir / "amobile").rglob("records.jsonl"))
    valid, invalid = transform(jsonl, TransformConfig(reference_dir=REF))
    assert len(valid) == 1 and len(invalid) == 0
    assert valid.iloc[0]["vendor"] == "amobile"  # vendor_mapping 적용 확인

    # 3) 가격 컴포넌트 전개 → SCD2 마트 적재
    engine = create_engine("sqlite://")
    loader = Scd2PriceLoader(engine)
    loader.ensure_schema()
    price_rows = []
    for rec in valid.to_dict(orient="records"):
        price_rows += explode_price_components(rec)

    stats = loader.load(price_rows, collected_at=datetime(2026, 6, 1))
    assert stats.inserted == 1

    with engine.connect() as conn:
        rows = conn.execute(
            select(fct_plan_price).where(fct_plan_price.c.is_current.is_(True))
        ).fetchall()
    assert len(rows) == 1
    assert rows[0].monthly_fee == 3300.0
    assert rows[0].plan_id == "70944"

    # 4) 재적재 멱등성: 동일 데이터 재실행 시 변경 없음
    stats2 = loader.load(price_rows, collected_at=datetime(2026, 6, 2))
    assert stats2.unchanged == 1 and stats2.inserted == 0
