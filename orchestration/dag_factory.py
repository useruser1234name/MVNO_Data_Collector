"""카탈로그 기반 동적 Airflow DAG 생성기.

벤더당 복붙 DAG 파일을 제거하고 config/vendors.yaml에서 단일 생성한다.
- enabled 이고 수집기 등록이 필요한(stub 외) 벤더만 DAG 생성
- anti_bot_level에 따라 재시도/풀을 차등
- 한 벤더 설정 오류가 전체 DAG 로딩을 깨지 않도록 per-vendor try/except로 격리
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List

from collectors.catalog import VendorCatalog, VendorEntry, load_catalog
from orchestration.common import (
    make_extract_task,
    make_load_task,
    make_transform_task,
    mvno_default_args,
)

logger = logging.getLogger(__name__)

# anti_bot_level → (retries, pool). 이통3사(high)는 보수적.
_ANTI_BOT_POLICY = {
    "low": {"retries": 1, "pool": "default_pool"},
    "medium": {"retries": 2, "pool": "default_pool"},
    "high": {"retries": 3, "pool": "mno_pool"},
}


def dags_to_build(catalog: VendorCatalog) -> List[VendorEntry]:
    """DAG를 생성할 대상(순수 함수, airflow 비의존 — 테스트 가능)."""
    return [e for e in catalog.enabled() if e.requires_registered_collector]


try:  # Airflow는 런타임(docker/airflow)에만 존재 — 로컬/CI import는 가드
    from airflow import DAG
    from airflow.operators.python import PythonOperator

    _AIRFLOW_AVAILABLE = True
except Exception:  # noqa: BLE001
    _AIRFLOW_AVAILABLE = False


def _build_dag(entry: VendorEntry):  # pragma: no cover - airflow 런타임에서만 실행
    policy = _ANTI_BOT_POLICY.get(entry.anti_bot_level, _ANTI_BOT_POLICY["low"])
    default_args = mvno_default_args()
    default_args["retries"] = policy["retries"]

    with DAG(
        dag_id=f"{entry.key}_pipeline",
        start_date=datetime(2024, 1, 1),
        schedule=entry.schedule,
        catchup=False,
        default_args=default_args,
        tags=["mvno", entry.group, entry.collector_type, entry.key],
    ) as dag:
        extract = PythonOperator(
            task_id="extract",
            python_callable=make_extract_task(entry.key),
            pool=policy["pool"],
        )
        transform_op = PythonOperator(task_id="transform", python_callable=make_transform_task())
        load_op = PythonOperator(task_id="load", python_callable=make_load_task(entry.key))
        extract >> transform_op >> load_op
    return dag


def register_dags(namespace: dict) -> None:  # pragma: no cover - airflow 런타임에서만 실행
    """카탈로그를 순회하며 namespace(globals())에 DAG를 등록한다."""
    if not _AIRFLOW_AVAILABLE:
        logger.warning("Airflow not available; skipping DAG registration")
        return
    catalog = load_catalog()
    for entry in dags_to_build(catalog):
        try:
            namespace[f"{entry.key}_dag"] = _build_dag(entry)
        except Exception:  # noqa: BLE001 - 벤더별 격리
            logger.exception("Failed to build DAG for vendor %s", entry.key)


if _AIRFLOW_AVAILABLE:  # pragma: no cover
    register_dags(globals())
