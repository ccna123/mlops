"""ml_pipeline — train a model and promote it if it earns the champion alias.

Triggered by hand, never scheduled: retraining is a decision, not a cron job.

Airflow does not run any of the ML code itself. Each task asks the Docker daemon
to run a stage image and reports its exit code. Data moves between stages
through object storage; XCom carries only small values.
"""

from __future__ import annotations

import json
import os

import pendulum
from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import BranchPythonOperator
from airflow.providers.docker.operators.docker import DockerOperator

DOCKER_URL = "unix://var/run/docker.sock"
NETWORK = "mlops_default"

MODEL_NAME_BY_TASK_TYPE = {
    "regression": "house_price_regressor",
    "classification": "house_sold_fast_classifier",
}

# Passed into every stage container. Read from the scheduler's own environment,
# which docker-compose fills from .env.
_MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT_INTERNAL", "http://minio:9000")
_MINIO_KEY = os.environ.get("MINIO_ACCESS_KEY", "")
_MINIO_SECRET = os.environ.get("MINIO_SECRET_KEY", "")

BASE_ENV = {
    "MINIO_ENDPOINT_INTERNAL": _MINIO_ENDPOINT,
    "MINIO_ACCESS_KEY": _MINIO_KEY,
    "MINIO_SECRET_KEY": _MINIO_SECRET,
    "ML_BUCKET": os.environ.get("ML_BUCKET", "ml-pipeline"),
    "MLFLOW_TRACKING_URI": os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"),
    # MLflow reaches MinIO through boto3, which reads the AWS names, not the MINIO ones.
    # Without these three, train/evaluate/register fail with AccessDenied the moment they
    # touch an artifact — the tracking call succeeds, so the failure looks unrelated.
    "MLFLOW_S3_ENDPOINT_URL": _MINIO_ENDPOINT,
    "AWS_ACCESS_KEY_ID": _MINIO_KEY,
    "AWS_SECRET_ACCESS_KEY": _MINIO_SECRET,
}


def last_json(lines: list[str]):
    """Pick out the one JSON result line a stage wrote, regardless of position.

    DockerOperator merges a container's stdout and stderr into a single XCom
    value. Every stage writes its human-readable progress to stderr and its
    JSON result to stdout as the final statement in the script — but stdout
    and stderr are separate pipes, and when the last stderr line and the JSON
    print happen microseconds apart (the common case: no I/O between them),
    the Docker daemon can interleave the two streams either way. So the JSON
    line is not reliably the literal last line in the merged list — scan all
    of them instead of trusting position. Confirmed empirically: replaying the
    same extract container five times through DockerOperator's own attach
    call put the JSON line last only 2 times out of 5.
    Scanned from the end, and only a JSON *object* counts. Both matter: every
    stage writes exactly one result and writes it last, so the last match is
    the right one; and json.loads("800") succeeds and returns an int, so a log
    line carrying a bare number would otherwise be mistaken for the result.
    """
    for line in reversed(lines):
        try:
            parsed = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"no JSON object found in stage output: {lines!r}")


FINGERPRINT = "{{ (ti.xcom_pull(task_ids='extract') | last_json)['fingerprint'] }}"
RUN_ID = "{{ (ti.xcom_pull(task_ids='train') | last_json)['run_id'] }}"
TASK_TYPE = "{{ params.task_type }}"
MODEL_NAME = "{{ params.model_name }}"


def stage(task_id: str, image: str, extra_env: dict) -> DockerOperator:
    """One stage: run an image, stream its logs, take every log line as XCom.

    xcom_all=True (rather than the default last-line-only) is required so
    last_json() above has the full set of lines to scan — see its docstring.
    """
    return DockerOperator(
        task_id=task_id,
        image=image,
        docker_url=DOCKER_URL,
        network_mode=NETWORK,
        environment={**BASE_ENV, **extra_env},
        auto_remove="success",
        mount_tmp_dir=False,
        do_xcom_push=True,
        xcom_all=True,
    )


def choose_branch(ti) -> str:
    """Reads the evaluate verdict and picks which way the DAG goes."""
    verdict = last_json(ti.xcom_pull(task_ids="evaluate"))
    print(f"evaluate said: {verdict['reason']}")
    return "register" if verdict["passed"] else "stop_no_deploy"


with DAG(
    dag_id="ml_pipeline",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ml", "training"],
    params={
        "task_type": "regression",
        "force_reprocess": False,
        "dataset_version": "v1",
        "estimator_name": "ridge",
        "model_name": MODEL_NAME_BY_TASK_TYPE["regression"],
    },
    # Airflow 2.10 has no built-in JSON filter, so register the scan-for-JSON
    # helper (see last_json() above) as a Jinja filter for use in templates.
    user_defined_filters={"last_json": last_json},
) as dag:
    extract = stage(
        "extract",
        "ml-extract:latest",
        {
            "DATASET_VERSION": "{{ params.dataset_version }}",
            "SAMPLE_ROWS": os.environ.get("SAMPLE_ROWS", ""),
        },
    )

    validate = stage(
        "validate",
        "ml-validate:latest",
        {"FINGERPRINT": FINGERPRINT, "TASK_TYPE": TASK_TYPE},
    )

    prepare_dataset = stage(
        "prepare_dataset_for_train",
        "ml-prepare-dataset:latest",
        {
            "FINGERPRINT": FINGERPRINT,
            "TASK_TYPE": TASK_TYPE,
            "FORCE_REPROCESS": "{{ params.force_reprocess | lower }}",
        },
    )

    train = stage(
        "train",
        "ml-train:latest",
        {
            "FINGERPRINT": FINGERPRINT,
            "TASK_TYPE": TASK_TYPE,
            "MODEL_NAME": MODEL_NAME,
            "ESTIMATOR_NAME": "{{ params.estimator_name }}",
        },
    )

    evaluate = stage(
        "evaluate",
        "ml-evaluate:latest",
        {
            "FINGERPRINT": FINGERPRINT,
            "TASK_TYPE": TASK_TYPE,
            "MODEL_NAME": MODEL_NAME,
            "RUN_ID": RUN_ID,
        },
    )

    branch = BranchPythonOperator(task_id="branch_on_gates", python_callable=choose_branch)

    register = stage(
        "register",
        "ml-register:latest",
        {
            "FINGERPRINT": FINGERPRINT,
            "TASK_TYPE": TASK_TYPE,
            "MODEL_NAME": MODEL_NAME,
            "RUN_ID": RUN_ID,
        },
    )

    stop_no_deploy = EmptyOperator(task_id="stop_no_deploy")

    extract >> validate >> prepare_dataset >> train >> evaluate >> branch
    branch >> [register, stop_no_deploy]
