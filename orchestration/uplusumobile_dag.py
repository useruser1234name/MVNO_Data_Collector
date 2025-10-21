"""Airflow DAG dedicated to the U+모바일 (uplusumobile) pipeline."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator

from etl.load import LoadConfig, PlanLoader
from etl.transform import TransformConfig, transform
from pipeline.run_collectors import discover_collectors, run_all

logger = logging.getLogger(__name__)

COLLECTOR_NAME = "uplusumobile"
DEFAULT_OUTPUT_DIR = Path(os.environ.get("UPLUS_OUTPUT_DIR", "output/raw"))
REFERENCE_DIR = Path(os.environ.get("UPLUS_REFERENCE_DIR", "etl/reference"))


def _latest_records_path(base_dir: Path, collector: str) -> Path:
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


def run_collector_task(**context) -> None:
    discover_collectors()
    results = asyncio.run(
        run_all(
            selected=[COLLECTOR_NAME],
            output_dir=DEFAULT_OUTPUT_DIR,
            concurrency=1,
            metadata={},
            policies={},
        )
    )
    logger.info("Collector results: %s", results)
    records_path = _latest_records_path(DEFAULT_OUTPUT_DIR, COLLECTOR_NAME)
    context["ti"].xcom_push(key="uplus_records_path", value=str(records_path))


def transform_task(**context) -> None:
    records_path = Path(context["ti"].xcom_pull(key="uplus_records_path"))
    valid, invalid = transform(records_path, TransformConfig(reference_dir=REFERENCE_DIR))
    output_dir = records_path.parent / "transformed"
    output_dir.mkdir(parents=True, exist_ok=True)

    valid_path = output_dir / "valid.jsonl"
    valid.to_json(str(valid_path), orient="records", lines=True, force_ascii=False)
    context["ti"].xcom_push(key="uplus_valid_path", value=str(valid_path))

    if not invalid.empty:
        invalid_path = output_dir / "invalid.jsonl"
        invalid.to_json(str(invalid_path), orient="records", lines=True, force_ascii=False)
        context["ti"].xcom_push(key="uplus_invalid_path", value=str(invalid_path))
    logger.info("Transform completed: valid=%s invalid=%s", len(valid), len(invalid))


def load_task(**context) -> None:
    valid_path_value = context["ti"].xcom_pull(key="uplus_valid_path")
    if not valid_path_value:
        raise ValueError("No transformed data available for load step")
    valid_path = Path(valid_path_value)

    records: list[dict] = []
    with valid_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))

    dsn = os.environ.get("UPLUS_DB_DSN")
    if not dsn:
        logger.warning("UPLUS_DB_DSN is not set. Skipping database load.")
        return

    loader = PlanLoader(LoadConfig(dsn=dsn))
    loader.load_to_staging(records)
    loader.upsert_to_mart(records, conflict_keys=["vendor", "plan_id"])
    logger.info("Loaded %s records into database", len(records))


def create_dag() -> DAG:
    with DAG(
        dag_id="uplusumobile_pipeline",
        start_date=datetime(2024, 1, 1),
        schedule_interval=timedelta(days=1),
        catchup=False,
        default_args={"retries": 1, "retry_delay": timedelta(minutes=10)},
        tags=["mvno", "uplusumobile"],
    ) as dag:
        extract = PythonOperator(task_id="extract", python_callable=run_collector_task)
        transform_op = PythonOperator(task_id="transform", python_callable=transform_task)
        load_op = PythonOperator(task_id="load", python_callable=load_task)

        extract >> transform_op >> load_op

    return dag


globals()["dag"] = create_dag()
