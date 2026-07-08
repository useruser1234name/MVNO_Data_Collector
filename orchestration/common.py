"""Common helpers for MVNO Airflow DAGs (standardized storage and envs)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from etl.load import LoadConfig, PlanLoader
from etl.transform import TransformConfig, transform
from pipeline.run_collectors import discover_collectors, run_all

logger = logging.getLogger(__name__)


def notify_failure(context: dict[str, Any]) -> None:
    """Airflow on_failure_callback: 태스크 실패를 웹훅으로 알린다.

    `MVNO_ALERT_WEBHOOK_URL`이 설정되지 않으면 조용히 무시한다(개발 환경 무방).
    httpx/WebhookNotifier import와 전송 실패가 콜백 자체를 깨뜨리지 않도록 방어한다.
    """
    webhook_url = os.environ.get("MVNO_ALERT_WEBHOOK_URL")
    if not webhook_url:
        return

    task_instance = context.get("task_instance")
    exception = context.get("exception")
    payload = {
        "event": "airflow_task_failed",
        "dag_id": getattr(task_instance, "dag_id", None),
        "task_id": getattr(task_instance, "task_id", None),
        "run_id": context.get("run_id"),
        "execution_date": str(context.get("logical_date") or context.get("execution_date") or ""),
        "try_number": getattr(task_instance, "try_number", None),
        "log_url": getattr(task_instance, "log_url", None),
        "exception": str(exception) if exception else None,
    }
    try:
        # 지연 import: httpx 미설치 환경에서도 DAG import가 깨지지 않게 한다.
        from pipeline.notifier import WebhookConfig, WebhookNotifier

        WebhookNotifier(WebhookConfig(url=webhook_url)).send(payload)
        logger.info("Failure notification sent for %s", payload.get("task_id"))
    except Exception as exc:  # noqa: BLE001 - 알림 실패가 태스크 상태를 가리면 안 됨
        logger.warning("Failed to send failure notification: %s", exc)


def mvno_default_args() -> dict[str, Any]:
    """모든 MVNO DAG가 공유하는 default_args (재시도 + 실패 알림 결선)."""
    return {
        "retries": 1,
        "retry_delay": timedelta(minutes=10),
        "on_failure_callback": notify_failure,
    }


def mvno_output_dir() -> Path:
    """Standard output root."""
    return Path(os.environ.get("MVNO_OUTPUT_DIR", "output/raw"))


def mvno_reference_dir() -> Path:
    """Standard reference data dir."""
    return Path(os.environ.get("MVNO_REFERENCE_DIR", "etl/reference"))


def mvno_db_dsn(vendor: str) -> str | None:
    """Prefer global DSN, fallback to vendor-specific env (for backward compat)."""
    return os.environ.get("MVNO_DB_DSN") or os.environ.get(f"{vendor.upper()}_DB_DSN")


def latest_records_path(base_dir: Path, collector: str) -> Path:
    collector_root = base_dir / collector
    if not collector_root.exists():
        raise FileNotFoundError(f"No outputs for collector {collector} under {base_dir}")
    runs = sorted([path for path in collector_root.iterdir() if path.is_dir()])
    if not runs:
        raise FileNotFoundError(f"No completed runs for collector {collector}")
    latest = runs[-1]
    records_path = latest / "records.jsonl"
    if not records_path.exists():
        raise FileNotFoundError(f"records.jsonl not found for collector {collector} in {latest}")
    return records_path


def make_extract_task(vendor: str) -> Callable[..., None]:
    def _task(**context) -> None:
        discover_collectors()
        results = asyncio.run(
            run_all(
                selected=[vendor],
                output_dir=mvno_output_dir(),
                concurrency=int(os.environ.get("MVNO_CONCURRENCY", "1")),
                metadata={},
                policies={},
            )
        )
        logger.info("Collector results: %s", results)
        records_path = latest_records_path(mvno_output_dir(), vendor)
        context["ti"].xcom_push(key="records_path", value=str(records_path))
    return _task


def make_transform_task() -> Callable[..., None]:
    def _task(**context) -> None:
        records_path_value = context["ti"].xcom_pull(key="records_path")
        if not records_path_value:
            raise ValueError("No records_path in XCom")
        records_path = Path(records_path_value)
        valid, invalid = transform(records_path, TransformConfig(reference_dir=mvno_reference_dir()))
        output_dir = records_path.parent / "transformed"
        output_dir.mkdir(parents=True, exist_ok=True)

        valid_path = output_dir / "valid.jsonl"
        valid.to_json(str(valid_path), orient="records", lines=True, force_ascii=False)
        context["ti"].xcom_push(key="valid_path", value=str(valid_path))

        if not invalid.empty:
            invalid_path = output_dir / "invalid.jsonl"
            invalid.to_json(str(invalid_path), orient="records", lines=True, force_ascii=False)
            context["ti"].xcom_push(key="invalid_path", value=str(invalid_path))
        logger.info("Transform completed: valid=%s invalid=%s", len(valid), len(invalid))
    return _task


def make_load_task(vendor: str) -> Callable[..., None]:
    def _task(**context) -> None:
        valid_path_value = context["ti"].xcom_pull(key="valid_path")
        if not valid_path_value:
            raise ValueError("No transformed data available for load step")
        valid_path = Path(valid_path_value)

        records: list[dict] = []
        with valid_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    records.append(json.loads(line))

        dsn = mvno_db_dsn(vendor)
        if not dsn:
            logger.warning("MVNO_DB_DSN (or vendor fallback) is not set. Skipping database load.")
            return

        loader = PlanLoader(LoadConfig(dsn=dsn))
        loader.load_to_staging(records)
        loader.upsert_to_mart(records, conflict_keys=["vendor", "plan_id"])
        logger.info("Loaded %s records into database", len(records))
    return _task


