"""CLI entrypoint for running one or more collectors."""
from __future__ import annotations

import argparse
import asyncio
import csv
import importlib
import json
import logging
import pkgutil
import traceback
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from collectors.base import CollectorConfig
from collectors.policy import FieldPolicySet, load_policy_file
from collectors.registry import registry


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

DEFAULT_VENDOR_REGISTRY = Path("etl/reference/vendor_registry.csv")
FailureEntry = dict[str, Any]


def discover_collectors() -> dict[str, str]:
    """Import collector modules so that registration side-effects run.

    Vendor collectors may depend on optional scraping libraries. Missing optional
    third-party dependencies should not prevent unrelated collectors from being
    discovered and executed, so those modules are recorded as unavailable and
    skipped.
    """
    import collectors.vendors  # noqa: F401

    unavailable: dict[str, str] = {}
    package = collectors.vendors
    for module in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
        collector_name = module.name.rsplit(".", maxsplit=1)[-1]
        try:
            importlib.import_module(module.name)
        except ModuleNotFoundError as exc:
            missing_name = exc.name or "unknown"
            if missing_name == module.name or missing_name.startswith(f"{module.name}."):
                raise
            unavailable[collector_name] = missing_name
            logger.warning(
                "Skipping collector module %s because optional dependency '%s' is not installed",
                module.name,
                missing_name,
            )
    return unavailable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MVNO collectors")
    parser.add_argument(
        "positional_collectors",
        nargs="*",
        metavar="collector",
        help="Collectors to run. Leave empty to run all available collectors.",
    )
    parser.add_argument(
        "--collectors",
        dest="collector_option",
        help="Comma-separated collectors to run. Overrides positional collector names.",
    )
    parser.add_argument("--output-dir", default="output/raw", help="Base directory for collector outputs")
    parser.add_argument("--concurrency", type=int, default=3, help="Maximum concurrent collectors")
    parser.add_argument("--metadata", help="JSON string with run metadata", default="{}")
    parser.add_argument("--summary", help="Path to write run summary JSON", default=None)
    parser.add_argument(
        "--failure-report",
        help="Path to write a markdown report for collectors that failed or were unavailable",
        default=None,
    )
    parser.add_argument(
        "--vendor-registry",
        default=str(DEFAULT_VENDOR_REGISTRY),
        help="CSV registry used to resolve collector/vendor names and site URLs for reports",
    )
    parser.add_argument(
        "--policy-file",
        help=(
            "Path to a JSON file describing column selector policies. "
            "Policies are matched by collector name."
        ),
        default=None,
    )
    return parser.parse_args()


def select_collectors(args: argparse.Namespace, available: list[str]) -> list[str]:
    """Resolve CLI collector selection from option or positional arguments."""
    if args.collector_option:
        selected = [name.strip() for name in args.collector_option.split(",") if name.strip()]
        return selected or available
    return args.positional_collectors or available


def load_vendor_registry(path: Path) -> dict[str, dict[str, str]]:
    """Load vendor metadata keyed by collector name for failure reports."""
    if not path.exists():
        return {}

    vendors: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            collector_name = (row.get("collector_name") or "").strip()
            if not collector_name:
                continue
            vendors[collector_name] = {
                "operator_name": (row.get("operator_name") or "").strip(),
                "brand_name": (row.get("brand_name") or "").strip(),
                "site_url": (row.get("site_url") or "").strip(),
                "priority": (row.get("priority") or "").strip(),
                "crawl_status": (row.get("crawl_status") or "").strip(),
            }
    return vendors


def make_failure_entry(
    collector: str,
    reason: str,
    *,
    stage: str,
    details: str | None = None,
) -> FailureEntry:
    """Create a normalized failure entry for summaries and markdown output."""
    return {
        "collector": collector,
        "stage": stage,
        "reason": reason,
        "details": details or "",
    }


def write_failure_report(
    path: Path,
    failures: Iterable[FailureEntry],
    vendor_registry: dict[str, dict[str, str]] | None = None,
) -> None:
    """Write a markdown list of failed/unavailable collectors with site URLs."""
    vendor_registry = vendor_registry or {}
    sorted_failures = sorted(failures, key=lambda entry: entry["collector"])

    lines = [
        "# MVNO 요금 획득 실패 목록",
        "",
        "요금제 획득에 실패했거나 실행 전 단계에서 사용할 수 없었던 업체 목록입니다.",
        "",
        "| 업체/브랜드 | Collector | 사이트 주소 | 단계 | 실패 사유 | 상세 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    if not sorted_failures:
        lines.append("| 없음 | - | - | - | - | - |")
    for failure in sorted_failures:
        collector = str(failure["collector"])
        vendor = vendor_registry.get(collector, {})
        label = vendor.get("brand_name") or vendor.get("operator_name") or collector
        site_url = vendor.get("site_url") or "확인 필요"
        lines.append(
            "| {label} | `{collector}` | {site_url} | {stage} | {reason} | {details} |".format(
                label=label,
                collector=collector,
                site_url=site_url,
                stage=failure.get("stage", ""),
                reason=failure.get("reason", ""),
                details=str(failure.get("details", "")).replace("\n", "<br>"),
            )
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run_collector(
    name: str,
    output_dir: Path,
    concurrency: int,
    metadata: dict,
    policy: FieldPolicySet | None,
) -> dict:
    config = CollectorConfig(
        name=name,
        output_dir=output_dir,
        concurrency=concurrency,
        metadata=metadata,
        field_policy=policy,
    )
    collector = registry.create(name, config)
    records = await collector.run()
    return {"collector": name, "records": len(records), "status": "success"}


async def run_all(
    selected: Iterable[str],
    output_dir: Path,
    concurrency: int,
    metadata: dict,
    policies: dict[str, FieldPolicySet],
) -> tuple[list[dict], list[FailureEntry]]:
    sem = asyncio.Semaphore(concurrency)
    results: list[dict] = []
    failures: list[FailureEntry] = []

    async def run_with_semaphore(name: str) -> None:
        async with sem:
            logger.info("Running collector %s", name)
            policy = policies.get(name)
            try:
                result = await run_collector(name, output_dir, concurrency, metadata, policy)
            except Exception as exc:  # noqa: BLE001 - keep batch execution resilient across vendors.
                logger.exception("Collector %s failed", name)
                failures.append(
                    make_failure_entry(
                        name,
                        type(exc).__name__,
                        stage="run",
                        details=str(exc) or traceback.format_exc(limit=1),
                    )
                )
            else:
                results.append(result)

    await asyncio.gather(*(run_with_semaphore(name) for name in selected))
    return results, failures


def main() -> int:
    unavailable = discover_collectors()
    args = parse_args()
    available = list(registry.available())
    selected = select_collectors(args, available)
    vendor_registry = load_vendor_registry(Path(args.vendor_registry))
    failures: list[FailureEntry] = []

    missing = set(selected) - set(available)
    if missing:
        unavailable_requested = sorted(name for name in missing if name in unavailable)
        unknown_requested = sorted(missing - set(unavailable_requested))
        if unavailable_requested:
            details = ", ".join(
                f"{name} (missing dependency: {unavailable[name]})"
                for name in unavailable_requested
            )
            logger.error("Unavailable collectors requested: %s", details)
            failures.extend(
                make_failure_entry(
                    name,
                    f"missing dependency: {unavailable[name]}",
                    stage="discovery",
                )
                for name in unavailable_requested
            )
        if unknown_requested:
            logger.error("Unknown collectors requested: %s", ", ".join(unknown_requested))
            failures.extend(
                make_failure_entry(name, "unknown collector", stage="selection")
                for name in unknown_requested
            )
        selected = [name for name in selected if name in available]
        if not selected:
            if args.failure_report:
                write_failure_report(Path(args.failure_report), failures, vendor_registry)
            return 1

    if args.concurrency < 1:
        logger.error("--concurrency must be at least 1")
        return 1

    try:
        metadata = json.loads(args.metadata)
    except json.JSONDecodeError as exc:
        logger.error("Invalid metadata JSON: %s", exc)
        return 1
    if not isinstance(metadata, dict):
        logger.error("--metadata must decode to a JSON object")
        return 1

    policies: dict[str, FieldPolicySet] = {}
    if args.policy_file:
        policy_path = Path(args.policy_file)
        try:
            policies = load_policy_file(policy_path)
        except (OSError, ValueError) as exc:
            logger.error("Failed to load policy file %s: %s", policy_path, exc)
            return 1

    output_dir = Path(args.output_dir)
    results, run_failures = asyncio.run(
        run_all(selected, output_dir, args.concurrency, metadata, policies)
    )
    failures.extend(run_failures)

    summary = {
        "collectors": sorted(results, key=lambda entry: entry["collector"]),
        "failures": sorted(failures, key=lambda entry: entry["collector"]),
        "total_records": sum(result["records"] for result in results),
        "total_failures": len(failures),
    }
    logger.info("Run summary: %s", summary)

    if args.summary:
        Path(args.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.failure_report and failures:
        write_failure_report(Path(args.failure_report), failures, vendor_registry)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
