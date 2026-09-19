"""Smoke test DAG — proves Airflow can read dags/ and run a task.

This DAG is deleted in Plan 2 once ml_pipeline_dag.py exists.
"""

from __future__ import annotations

import pendulum
from airflow.decorators import dag, task


@dag(
    dag_id="smoke_test",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["smoke"],
)
def smoke_test():
    @task
    def hello():
        print("Airflow can read dags/ and run a task.")
        return "ok"

    @task
    def check_env_vars():
        import os

        for name in ("MLFLOW_TRACKING_URI", "MINIO_ENDPOINT_INTERNAL", "ML_BUCKET"):
            value = os.environ.get(name)
            print(f"{name} = {value}")
            assert value, f"Missing environment variable {name}"
        return "ok"

    hello() >> check_env_vars()


smoke_test()
