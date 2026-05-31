"""Unit tests for PlanRecord / PriceComponent schema."""
import pytest

from schemas.plan_record import PlanRecord, PriceComponent


def _base(**kw):
    defaults = dict(
        vendor="v", plan_id="p1", name="n", monthly_fee=10000.0,
        data_allowance_mb=11264, voice_minutes=100, sms_count=100,
    )
    defaults.update(kw)
    return PlanRecord(**defaults)


class TestValidation:
    def test_requires_vendor(self):
        with pytest.raises(ValueError):
            _base(vendor="")

    def test_requires_plan_id(self):
        with pytest.raises(ValueError):
            _base(plan_id="")

    def test_negative_fee_rejected(self):
        with pytest.raises(ValueError):
            _base(monthly_fee=-1)

    def test_none_data_allowed_for_unlimited(self):
        # 무제한/실패는 None 허용(0과 구분)
        rec = _base(data_allowance_mb=None, data_unlimited=True)
        assert rec.data_allowance_mb is None and rec.data_unlimited


class TestSerialization:
    def test_to_dict_includes_new_fields(self):
        rec = _base(data_unlimited=True, data_allowance_mb=None,
                    parse_status={"data": "unlimited"})
        d = rec.to_dict()
        assert d["data_unlimited"] is True
        assert d["parse_status"] == {"data": "unlimited"}
        assert d["price_components"] == []

    def test_price_components_serialized(self):
        rec = _base(price_components=[
            PriceComponent(price_type="정상가", monthly_fee=39000),
            PriceComponent(price_type="선택약정", monthly_fee=29250, commitment_months=24),
        ])
        d = rec.to_dict()
        assert len(d["price_components"]) == 2
        assert d["price_components"][1]["commitment_months"] == 24


class TestPriceComponent:
    def test_requires_type(self):
        with pytest.raises(ValueError):
            PriceComponent(price_type="", monthly_fee=1000)

    def test_negative_rejected(self):
        with pytest.raises(ValueError):
            PriceComponent(price_type="정상가", monthly_fee=-5)
