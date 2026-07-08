from collectors.vendors.ktmmobile import row_to_record as kt_row_to_record
from collectors.vendors.sk7mobile import row_to_record as sk7_row_to_record


def test_ktmmobile_row_to_record_normalizes_modal_csv_row() -> None:
    record = kt_row_to_record(
        {
            "card_index": "1",
            "modal_title": "모두다 맘껏 7GB+",
            "list_title": "아무나 SOLO 결합 시 매월 평생 데이터 5GB 제공",
            "modal_price": "35200",
            "modal_price_text": "월 기본료(VAT 포함) 35,200 원",
            "tab_name": "유심/eSIM 요금제",
            "modal_html_path": "ktmm_out/html/example.html",
            "modal_png_path": "ktmm_out/modals/example.png",
        }
    )

    assert record.vendor == "ktmmobile"
    assert record.plan_id == "ktmmobile-1"
    assert record.monthly_fee == 35200.0
    assert record.data_allowance_mb == 7 * 1024
    assert record.metadata["crawled_source"] == "local_modal_csv"


def test_sk7mobile_row_to_record_normalizes_detail_csv_row() -> None:
    record = sk7_row_to_record(
        {
            "prodCd": "PD00000130",
            "refCode": "PHONE",
            "searchCallPlanType": "PROD_LTE_TYPE_ALL",
            "title": "데이터중심1.2GB_3G",
            "badges": "3G|통화편의",
            "data": "1.2GB",
            "voice": "기본제공",
            "sms": "50건",
            "price_base": "36300",
            "price_promo": "",
            "url": "https://www.sk7mobile.com/prod/data/callingPlanView.do?prodCd=PD00000130",
        }
    )

    assert record.vendor == "sk7mobile"
    assert record.plan_id == "PD00000130"
    assert record.monthly_fee == 36300.0
    assert record.data_allowance_mb == int(1.2 * 1024)
    assert record.voice_minutes is None
    assert record.metadata["voice_unlimited"] is True
    assert record.sms_count == 50
    assert record.network_type == "3G"
