"""Airflow DAG definition for the MVNO ETL pipeline."""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from pipeline.run_collectors import main as run_collectors_main


def run_collectors_task(**context):
    run_collectors_main()


def transform_task(**context):
    # Placeholder for transform step integration
    pass


def load_task(**context):
    # Placeholder for load step integration
    pass


def create_dag() -> DAG:
    with DAG(
        dag_id="mvno_etl_pipeline",
        start_date=datetime(2024, 1, 1),
        schedule_interval=timedelta(days=1),
        catchup=False,
        default_args={"retries": 1, "retry_delay": timedelta(minutes=10)},
        tags=["mvno", "etl"],
    ) as dag:
        extract = PythonOperator(task_id="run_collectors", python_callable=run_collectors_task)
        transform = PythonOperator(task_id="transform", python_callable=transform_task)
        load = PythonOperator(task_id="load", python_callable=load_task)

        extract >> transform >> load

    return dag


globals()["dag"] = create_dag()
