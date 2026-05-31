"""CLI entrypoint for running one or more collectors."""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import pkgutil
from pathlib import Path
from typing import Iterable

from collectors.base import CollectorConfig
from collectors.policy import FieldPolicySet, load_policy_file
from collectors.registry import registry


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def discover_collectors() -> None:
    """Import collector modules so that registration side-effects run."""
    import collectors.vendors  # noqa: F401

    package = collectors.vendors
    prefix = package.__name__ + "."
    for module in pkgutil.walk_packages(package.__path__, prefix):
        importlib.import_module(module.name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MVNO collectors")
    parser.add_argument("collectors", nargs="*", help="Collectors to run. Leave empty to run all.")
    parser.add_argument("--output-dir", default="output/raw", help="Base directory for collector outputs")
    parser.add_argument("--concurrency", type=int, default=3, help="Maximum concurrent collectors")
    parser.add_argument("--metadata", help="JSON string with run metadata", default="{}")
    parser.add_argument("--summary", help="Path to write run summary JSON", default=None)
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="레코드 0건인 수집기가 하나라도 있으면 비정상 종료(코드 2). 무음 실패 차단용.",
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
    return {"collector": name, "records": len(records)}


async def run_all(
    selected: Iterable[str],
    output_dir: Path,
    concurrency: int,
    metadata: dict,
    policies: dict[str, FieldPolicySet],
) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    results: list[dict] = []

    async def run_with_semaphore(name: str) -> None:
        async with sem:
            logger.info("Running collector %s", name)
            policy = policies.get(name)
            result = await run_collector(name, output_dir, concurrency, metadata, policy)
            results.append(result)

    await asyncio.gather(*(run_with_semaphore(name) for name in selected))
    return results


def main() -> int:
    discover_collectors()
    args = parse_args()
    available = list(registry.available())
    selected = args.collectors or available

    missing = set(selected) - set(available)
    if missing:
        logger.error("Unknown collectors requested: %s", ", ".join(sorted(missing)))
        return 1

    try:
        metadata = json.loads(args.metadata)
    except json.JSONDecodeError as exc:
        logger.error("Invalid metadata JSON: %s", exc)
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
    results = asyncio.run(
        run_all(selected, output_dir, args.concurrency, metadata, policies)
    )

    empty_collectors = sorted(result["collector"] for result in results if result["records"] == 0)
    summary = {
        "collectors": sorted(results, key=lambda entry: entry["collector"]),
        "total_records": sum(result["records"] for result in results),
        "empty_collectors": empty_collectors,
    }
    logger.info("Run summary: %s", summary)

    if empty_collectors:
        # 수집 0건은 사이트 구조 변경/차단의 1차 신호 — 무음 실패로 흘려보내지 않도록 경고한다.
        logger.warning(
            "Collectors returned 0 records: %s", ", ".join(empty_collectors)
        )

    if args.summary:
        Path(args.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if empty_collectors and args.fail_on_empty:
        logger.error(
            "Failing run because --fail-on-empty is set and %d collector(s) returned 0 records",
            len(empty_collectors),
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
