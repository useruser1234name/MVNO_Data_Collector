"""Golden-fixture regression test for the amobile parser."""
from pathlib import Path

from collectors.vendors.amobile import _parse_detail_html
from schemas import units

FIXTURE = Path(__file__).parent / "fixtures" / "amobile" / "KT__70944.html"


def test_amobile_golden():
    rec = _parse_detail_html(FIXTURE)
    assert rec is not None
    assert rec.vendor == "amobile"
    assert rec.plan_id == "70944"
    assert rec.name == "A모바일 LTE 데이터 중심 11GB"
    assert rec.network_type == "LTE"
    assert rec.monthly_fee == 3300.0
    assert rec.data_allowance_mb == 11 * 1024
    assert rec.voice_minutes == 100
    assert rec.sms_count == 100
    assert rec.metadata["carrier_label"] == "KT"
    # 모든 필드가 정상 파싱됐는지 상태 확인
    assert rec.parse_status["fee"] == units.STATUS_OK
    assert rec.parse_status["data"] == units.STATUS_OK
