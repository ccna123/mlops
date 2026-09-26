"""feedback_data_pipeline - build a dataset version from served traffic (CN-42).

Triggered by hand from the dashboard's Data screen, never scheduled. One task,
one container: the rules are in ml_common.feedback.

Unpaused at creation like traffic_agent: a run of a paused DAG sits in
`queued` forever with no sign anywhere of why (the incident of 2026-09-21).
"""

from __future__ import annotations

import os

import pendulum
from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator
from run_outcome import report as report_run_outcome

DOCKER_URL = "unix://var/run/docker.sock"
NETWORK = "mlops_default"

MODEL_NAME_BY_TASK_TYPE = {
    "regression": "house_price_regressor",
    "classification": "house_needs_renovation_classifier",
}

_MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT_INTERNAL", "http://minio:9000")
_MINIO_KEY = os.environ.get("MINIO_ACCESS_KEY", "")
_MINIO_SECRET = os.environ.get("MINIO_SECRET_KEY", "")

BASE_ENV = {
    "MINIO_ENDPOINT_INTERNAL": _MINIO_ENDPOINT,
    "MINIO_ACCESS_KEY": _MINIO_KEY,
    "MINIO_SECRET_KEY": _MINIO_SECRET,
    "ML_BUCKET": os.environ.get("ML_BUCKET", "ml-pipeline"),
    "MLFLOW_TRACKING_URI": os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"),
}

with DAG(
    dag_id="feedback_data_pipeline",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    # One at a time: two runs could both pass the "name not taken" check.
    max_active_runs=1,
    is_paused_upon_creation=False,
    tags=["ml", "data"],
    # How each run ended goes to the Pushgateway, where the "pipeline failed"
    # alert rule reads it (CN-46).
    on_success_callback=report_run_outcome,
    on_failure_callback=report_run_outcome,
    params={
        "task_type": "regression",
        "new_version": "",
        # Empty = the dataset version the champion learned from.
        "source_version": "",
        # Empty = the last 30 days. ISO timestamps with an offset.
        "period_start": "",
        "period_end": "",
    },
    user_defined_macros={"model_name_for": MODEL_NAME_BY_TASK_TYPE.__getitem__},
) as dag:
    DockerOperator(
        task_id="build_feedback_dataset",
        image="ml-build-feedback:latest",
        docker_url=DOCKER_URL,
        network_mode=NETWORK,
        environment={
            **BASE_ENV,
            "TASK_TYPE": "{{ params.task_type }}",
            "MODEL_NAME": "{{ model_name_for(params.task_type) }}",
            "NEW_VERSION": "{{ params.new_version }}",
            "SOURCE_VERSION": "{{ params.source_version or '' }}",
            "PERIOD_START": "{{ params.period_start or '' }}",
            "PERIOD_END": "{{ params.period_end or '' }}",
        },
        auto_remove="success",
        mount_tmp_dir=False,
        do_xcom_push=True,
        xcom_all=True,
    )
