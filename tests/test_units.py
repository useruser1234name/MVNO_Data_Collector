"""Unit tests for the unified normalizer (schemas/units.py)."""
from schemas import units


class TestParseData:
    def test_gb(self):
        q = units.parse_data_to_mb("11GB")
        assert q.value == 11 * 1024 and not q.unlimited and q.status == units.STATUS_OK

    def test_tb(self):
        assert units.parse_data_to_mb("1TB").value == 1024 * 1024

    def test_short_m_suffix_regression(self):
        # 과거 '500M'이 0으로 반환되던 버그 회귀 방지
        q = units.parse_data_to_mb("500M")
        assert q.value == 500 and q.status == units.STATUS_OK

    def test_decimal(self):
        assert units.parse_data_to_mb("1.5GB").value == round(1.5 * 1024)

    def test_unlimited(self):
        q = units.parse_data_to_mb("데이터 무제한")
        assert q.unlimited and q.value is None and q.status == units.STATUS_UNLIMITED

    def test_missing(self):
        q = units.parse_data_to_mb(None)
        assert q.value is None and q.status == units.STATUS_MISSING

    def test_unparsed(self):
        q = units.parse_data_to_mb("상담원 문의")
        assert q.value is None and q.status == units.STATUS_UNPARSED and not q.unlimited


class TestParseVoiceSms:
    def test_voice_minutes(self):
        assert units.parse_voice("100분").value == 100

    def test_voice_unlimited(self):
        q = units.parse_voice("집/이동전화 무제한")
        assert q.unlimited and q.value is None

    def test_sms_count(self):
        assert units.parse_sms("100건").value == 100

    def test_sms_thousands(self):
        assert units.parse_sms("1,000건").value == 1000


class TestParseMoney:
    def test_with_won_and_two_values(self):
        # 첫 번째 값(부가세 포함) 사용
        assert units.parse_money("3,300원 3,000원") == 3300

    def test_plain(self):
        assert units.parse_money("19800") == 19800

    def test_none(self):
        assert units.parse_money(None) is None

    def test_no_digits(self):
        assert units.parse_money("문의") is None


class TestParseSpeed:
    def test_mbps(self):
        assert units.parse_speed_to_kbps("최대 3Mbps") == 3000

    def test_kbps(self):
        assert units.parse_speed_to_kbps("400Kbps") == 400

    def test_none(self):
        assert units.parse_speed_to_kbps("무제한") is None
