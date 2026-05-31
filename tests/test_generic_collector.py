"""GenericCollector(설정주도) 픽스처 테스트 + 스텔스/robots 유틸 테스트."""
import asyncio
from pathlib import Path

from collectors.utils.playwright import STEALTH_INIT_SCRIPT, stealth_context_options
from collectors.utils.robots import CrawlBudget
from collectors.vendors.generic import build_generic_collector
from schemas import units

FIX = Path(__file__).parent / "fixtures" / "generic"


def _run_collector(tmp_path):
    collector = build_generic_collector(
        name="simplemvno",
        output_dir=tmp_path,
        policy_file=FIX / "policy.json",
        row_selector="li.plan",
        vendor="simplemvno",
        html_paths=[str(FIX / "list.html")],
    )

    async def _go():
        entries = await collector.fetch_entries()
        return await collector.parse_entries(entries)

    return asyncio.run(_go())


def test_generic_extracts_records(tmp_path):
    records = _run_collector(tmp_path)
    # 헤더 행(이름 없음)은 제외되어 2건
    assert len(records) == 2
    names = {r.name for r in records}
    assert names == {"심플 LTE 11GB", "심플 5G 무제한"}


def test_generic_normalizes_via_units(tmp_path):
    records = _run_collector(tmp_path)
    by_name = {r.name: r for r in records}

    lte = by_name["심플 LTE 11GB"]
    assert lte.monthly_fee == 19800
    assert lte.data_allowance_mb == 11 * 1024
    assert lte.voice_unlimited is True  # '음성 무제한'
    assert lte.sms_count == 100

    g5 = by_name["심플 5G 무제한"]
    assert g5.monthly_fee == 55000  # '월 55,000원'
    assert g5.data_unlimited is True and g5.data_allowance_mb is None
    assert g5.parse_status["data"] == units.STATUS_UNLIMITED


def test_stealth_context_options():
    opts = stealth_context_options(user_agent="UA")
    assert opts["locale"] == "ko-KR"
    assert opts["timezone_id"] == "Asia/Seoul"
    assert opts["viewport"] == {"width": 1366, "height": 768}
    assert opts["user_agent"] == "UA"
    assert "webdriver" in STEALTH_INIT_SCRIPT


def test_crawl_budget_limit():
    budget = CrawlBudget(max_requests_per_domain=2)
    url = "https://x.com/a"
    assert budget.allow(url) and budget.allow(url)
    assert budget.allow(url) is False  # 3번째 초과
