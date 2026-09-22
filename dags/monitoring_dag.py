"""monitoring_dag - recomputes drift for every model, on demand.

It measures drift for each model independently, so a missing classification
champion never blocks the regression verdict.

Trigger-only, and left unpaused. The design (section 6.2) asked for an hourly
schedule and Plan 4 shipped it paused to protect a 16GB dev box already
running Airflow, Postgres, MinIO, MLflow and serving: a job that quietly
fires every hour and pulls Evidently plus 10,000 reference rows is the kind
of thing people forget about and then wonder why the machine crawls.

Since the dashboard now has a button that triggers this DAG, `schedule=None`
protects that same box while leaving the button useful. Staying paused would
not: a triggered run of a paused DAG sits in `queued` forever with no signal
anywhere that says why. Restore `schedule="@hourly"` when this moves to MWAA,
where the hourly cost is not a problem.

One container per model rather than the three tasks section 6.2 sketches.
XCom carries only small values, so collect/report/publish as separate tasks
would each have to re-read the window from object storage.

The two tasks share no dependency edge, so a model with no champion yet
fails its own task and leaves the other's verdict untouched. That
independence is the whole mechanism - there is no trigger rule doing it.
"""

from __future__ import annotations

import json
import os

import pendulum
from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator

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
    "MLFLOW_S3_ENDPOINT_URL": _MINIO_ENDPOINT,
    "AWS_ACCESS_KEY_ID": _MINIO_KEY,
    "AWS_SECRET_ACCESS_KEY": _MINIO_SECRET,
    "MONITOR_WINDOW_HOURS": os.environ.get("MONITOR_WINDOW_HOURS", "24"),
}

# Kept in sync with ml_common.stageio.RESULT_PREFIX by a test in common/tests.
# The DAG runs in the Airflow image, which has no ml_common installed.
RESULT_PREFIX = "Data drift "


def stage_result(lines: list[str]) -> dict:
    """Finds the line a stage marked as its result, wherever it landed.

    Args:
        lines: every log line the container produced.

    Returns:
        The payload the stage emitted, decoded from JSON.

    Raises:
        ValueError: when no marked line is present.

    Example:
        stage_result(ti.xcom_pull(task_ids="monitor_regression"))["severity"]
        # -> "high"
    """
    for line in reversed(lines):
        if isinstance(line, str) and line.strip().startswith(RESULT_PREFIX):
            return json.loads(line.strip()[len(RESULT_PREFIX) :])
    raise ValueError(f"no {RESULT_PREFIX.strip()} line in stage output: {lines!r}")


with DAG(
    dag_id="monitoring_dag",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    # One monitoring run at a time: two runs would recompute the same window
    # and race each other writing the same drift summary keys.
    max_active_runs=1,
    tags=["ml", "monitoring"],
    user_defined_filters={"stage_result": stage_result},
) as dag:
    for task_type, model_name in MODEL_NAME_BY_TASK_TYPE.items():
        DockerOperator(
            task_id=f"monitor_{task_type}",
            image="ml-monitor:latest",
            docker_url=DOCKER_URL,
            network_mode=NETWORK,
            environment={
                **BASE_ENV,
                "TASK_TYPE": task_type,
                "MODEL_NAME": model_name,
                "MONITOR_RUN_ID": "{{ run_id | replace(':', '-') | replace('+', '-') }}",
            },
            auto_remove="success",
            mount_tmp_dir=False,
            do_xcom_push=True,
            xcom_all=True,
        )
