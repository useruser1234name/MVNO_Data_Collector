from collectors.vendors.chancemobile import parse_entries_from_html as parse_chance_entries
from collectors.vendors.chancemobile import row_to_record as chance_row_to_record
from collectors.vendors.smartel import parse_entries_from_html as parse_smartel_entries
from collectors.vendors.smartel import row_to_record as smartel_row_to_record
from collectors.vendors.theonemobile import parse_entries_from_html as parse_theone_entries
from collectors.vendors.theonemobile import row_to_record as theone_row_to_record


def test_theonemobile_parser_extracts_plan_record() -> None:
    html = """
    <div>ONE 5G 30GB 기본 월 30GB 통화 무제한 문자 무제한 KT망 5G 월 4,400원 12개월 이후 29,700원</div>
    """

    rows = parse_theone_entries(html)
    record = theone_row_to_record(rows[0])

    assert record.vendor == "theonemobile"
    assert record.name.startswith("ONE 5G")
    assert record.monthly_fee == 4400.0
    assert record.data_allowance_mb == 30 * 1024
    assert record.metadata["voice_unlimited"] is True
    assert record.metadata["sms_unlimited"] is True


def test_chancemobile_parser_extracts_onclick_plan_record() -> None:
    html = """
    <div onclick="fnMovePlanDetail('GD001','POS01')">
      <p class="data_name">찬스 데이터 7GB+</p>
      <strong>7GB+1Mbps</strong><span>통화 무제한 문자 무제한</span><strong>월 11,000원</strong>
    </div>
    """

    rows = parse_chance_entries(html)
    record = chance_row_to_record(rows[0])

    assert record.vendor == "chancemobile"
    assert record.plan_id == "chancemobile-GD001-POS01"
    assert record.name == "찬스 데이터 7GB+"
    assert record.monthly_fee == 11000.0
    assert record.data_allowance_mb == 7 * 1024
    assert record.metadata["detail_url"].endswith("gdcd=GD001&poscd=POS01")


def test_smartel_parser_extracts_anchor_plan_record() -> None:
    html = """
    <a href="/phoneplan/55"><span>SKT</span><h1>스마일 7GB+</h1>
      <p>총 7GB</p><p>소진 후 최대 1Mbps 속도 무제한</p>
      <p>기본 제공</p><p>기본제공</p><p>월</p><p>7,000</p><p>원</p>
      <p>7개월 이후 월 24,200원</p>
    </a>
    """

    rows = parse_smartel_entries(html)
    record = smartel_row_to_record(rows[0])

    assert record.vendor == "smartel"
    assert record.name == "스마일 7GB+"
    assert record.monthly_fee == 7000.0
    assert record.data_allowance_mb == 7 * 1024
    assert record.network_type == "SKT"
    assert record.metadata["detail_url"] == "https://www.smartel.kr/phoneplan/55"
