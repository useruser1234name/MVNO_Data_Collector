import argparse
import sys
from pathlib import Path

import pytest

from pipeline import run_collectors


def test_select_collectors_prefers_comma_separated_option() -> None:
    args = argparse.Namespace(
        collector_option="example, uplusumobile,",
        positional_collectors=["ignored"],
    )

    assert run_collectors.select_collectors(args, ["example"]) == ["example", "uplusumobile"]


def test_select_collectors_defaults_to_available_when_no_selection() -> None:
    args = argparse.Namespace(collector_option=None, positional_collectors=[])

    assert run_collectors.select_collectors(args, ["example"]) == ["example"]


def test_discover_collectors_skips_missing_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vendors_dir = tmp_path / "collectors" / "vendors"
    vendors_dir.mkdir(parents=True)
    (tmp_path / "collectors" / "__init__.py").write_text("", encoding="utf-8")
    (vendors_dir / "__init__.py").write_text("", encoding="utf-8")
    (vendors_dir / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
    (vendors_dir / "needs_extra.py").write_text(
        "import definitely_missing_mvno_dep\n",
        encoding="utf-8",
    )

    original_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "collectors" or name.startswith("collectors.")
    }
    for name in list(original_modules):
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.syspath_prepend(str(tmp_path))

    try:
        unavailable = run_collectors.discover_collectors()
    finally:
        collector_modules = [
            name
            for name in list(sys.modules)
            if name == "collectors" or name.startswith("collectors.")
        ]
        for name in collector_modules:
            monkeypatch.delitem(sys.modules, name, raising=False)
        sys.modules.update(original_modules)

    assert unavailable == {"needs_extra": "definitely_missing_mvno_dep"}


def test_load_vendor_registry_reads_site_urls(tmp_path: Path) -> None:
    registry_path = tmp_path / "vendor_registry.csv"
    registry_path.write_text(
        "collector_name,operator_name,brand_name,site_url,priority,crawl_status\n"
        "example,예시사업자,예시모바일,https://example.test,P0,implemented\n",
        encoding="utf-8",
    )

    vendors = run_collectors.load_vendor_registry(registry_path)

    assert vendors["example"]["brand_name"] == "예시모바일"
    assert vendors["example"]["site_url"] == "https://example.test"


def test_write_failure_report_includes_vendor_site_url(tmp_path: Path) -> None:
    report_path = tmp_path / "failures.md"
    vendor_registry = {
        "example": {
            "brand_name": "예시모바일",
            "operator_name": "예시사업자",
            "site_url": "https://example.test",
        }
    }

    run_collectors.write_failure_report(
        report_path,
        [
            run_collectors.make_failure_entry(
                "example",
                "RuntimeError",
                stage="run",
                details="boom",
            )
        ],
        vendor_registry,
    )

    report = report_path.read_text(encoding="utf-8")
    assert "예시모바일" in report
    assert "https://example.test" in report
    assert "RuntimeError" in report


def test_run_all_continues_and_records_collector_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import asyncio

    async def fake_run_collector(name, output_dir, concurrency, metadata, policy):
        if name == "bad":
            raise RuntimeError("boom")
        return {"collector": name, "records": 2, "status": "success"}

    monkeypatch.setattr(run_collectors, "run_collector", fake_run_collector)

    results, failures = asyncio.run(
        run_collectors.run_all(
            ["good", "bad"],
            tmp_path,
            2,
            {},
            {},
        )
    )

    assert results == [{"collector": "good", "records": 2, "status": "success"}]
    assert failures == [
        {
            "collector": "bad",
            "stage": "run",
            "reason": "RuntimeError",
            "details": "boom",
        }
    ]
