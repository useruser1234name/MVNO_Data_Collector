"""Integration tests for the rule-based quarantine in etl/transform.py."""
import json
from pathlib import Path

import pandas as pd

from etl.transform import TransformConfig, quarantine_invalid, transform


def _cfg(tmp_path):
    return TransformConfig(reference_dir=tmp_path)


def _rec(**kw):
    base = dict(
        vendor="amobile", plan_id="70944", name="plan", monthly_fee=3300,
        data_allowance_mb=11264, voice_minutes=100, sms_count=100,
        data_unlimited=False, parse_status={"fee": "ok", "data": "ok"},
    )
    base.update(kw)
    return base


def test_valid_passes(tmp_path):
    frame = pd.DataFrame([_rec()])
    valid, invalid = quarantine_invalid(frame, _cfg(tmp_path))
    assert len(valid) == 1 and len(invalid) == 0


def test_fee_parse_failure_quarantined(tmp_path):
    # 요금 파싱 실패가 0원으로 둔갑한 케이스
    frame = pd.DataFrame([_rec(monthly_fee=0, parse_status={"fee": "unparsed"})])
    valid, invalid = quarantine_invalid(frame, _cfg(tmp_path))
    assert len(valid) == 0 and len(invalid) == 1
    assert "fee_parse_failed" in invalid.iloc[0]["quarantine_reasons"]


def test_placeholder_plan_id_quarantined(tmp_path):
    frame = pd.DataFrame([_rec(plan_id="unknown")])
    valid, invalid = quarantine_invalid(frame, _cfg(tmp_path))
    assert len(invalid) == 1
    assert "placeholder_plan_id" in invalid.iloc[0]["quarantine_reasons"]


def test_duplicate_natural_key(tmp_path):
    frame = pd.DataFrame([_rec(), _rec()])
    valid, invalid = quarantine_invalid(frame, _cfg(tmp_path))
    assert len(valid) == 1 and len(invalid) == 1
    assert "duplicate_natural_key" in invalid.iloc[0]["quarantine_reasons"]


def test_unlimited_logic_conflict(tmp_path):
    frame = pd.DataFrame([_rec(data_unlimited=True, data_allowance_mb=11264)])
    _, invalid = quarantine_invalid(frame, _cfg(tmp_path))
    assert "unlimited_with_value" in invalid.iloc[0]["quarantine_reasons"]


def test_unlimited_valid_when_value_none(tmp_path):
    frame = pd.DataFrame([_rec(data_unlimited=True, data_allowance_mb=None,
                               parse_status={"fee": "ok", "data": "unlimited"})])
    valid, invalid = quarantine_invalid(frame, _cfg(tmp_path))
    assert len(valid) == 1 and len(invalid) == 0


def test_fee_too_high(tmp_path):
    frame = pd.DataFrame([_rec(monthly_fee=999999)])
    _, invalid = quarantine_invalid(frame, _cfg(tmp_path))
    assert "fee_too_high" in invalid.iloc[0]["quarantine_reasons"]


def test_transform_end_to_end(tmp_path):
    path = tmp_path / "records.jsonl"
    rows = [_rec(plan_id="a"), _rec(plan_id="b", monthly_fee=0, parse_status={"fee": "unparsed"})]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    valid, invalid = transform(path, _cfg(tmp_path))
    assert len(valid) == 1 and len(invalid) == 1
