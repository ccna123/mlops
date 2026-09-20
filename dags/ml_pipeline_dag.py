"""ml_pipeline — train a model and promote it if it earns the champion alias.

Triggered by hand, never scheduled: retraining is a decision, not a cron job.

Airflow does not run any of the ML code itself. Each task asks the Docker daemon
to run a stage image and reports its exit code. Data moves between stages
through object storage; XCom carries only small values.
"""

from __future__ import annotations

import json
import os
import urllib.request

import pendulum
from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import BranchPythonOperator, PythonOperator
from airflow.providers.docker.operators.docker import DockerOperator

DOCKER_URL = "unix://var/run/docker.sock"
NETWORK = "mlops_default"

MODEL_NAME_BY_TASK_TYPE = {
    "regression": "house_price_regressor",
    "classification": "house_needs_renovation_classifier",
}

DEFAULT_ESTIMATOR_BY_TASK_TYPE = {
    "regression": "ridge",
    "classification": "logistic",
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


# Kept in sync with ml_common.stageio.RESULT_PREFIX by a test in common/tests.
# The DAG cannot import ml_common: it runs in the Airflow image, which has no
# ml_common installed, only the stage images do.
RESULT_PREFIX = "XCOM_RESULT "


def stage_result(lines: list[str]) -> dict:
    """Finds the line a stage marked as its result, wherever it landed.

    DockerOperator merges stdout and stderr, and the daemon does not guarantee
    the order of two writes microseconds apart on different pipes. The result
    marks itself rather than relying on position; see ml_common.stageio.

    Args:
        lines: every log line the stage container produced, as xcom_all=True
            pushes them. Non-string entries are skipped rather than crashing.

    Returns:
        The payload the stage emitted, decoded from JSON.

    Raises:
        ValueError: when no marked line is present — the stage died before
            emitting one, and letting the DAG carry on with nothing would fail
            further downstream with a much less obvious message.

    Example:
        stage_result(ti.xcom_pull(task_ids="extract"))["fingerprint"]
        # -> "3f0a9c1d5e2b7a48"

        # Also registered as a Jinja filter, which is how templates reach it —
        # Airflow 2.10 has no built-in JSON filter:
        # "{{ (ti.xcom_pull(task_ids='extract') | stage_result)['fingerprint'] }}"
    """
    for line in reversed(lines):
        if isinstance(line, str) and line.strip().startswith(RESULT_PREFIX):
            return json.loads(line.strip()[len(RESULT_PREFIX) :])
    raise ValueError(f"no {RESULT_PREFIX.strip()} line in stage output: {lines!r}")


FINGERPRINT = "{{ (ti.xcom_pull(task_ids='extract') | stage_result)['fingerprint'] }}"
RUN_ID = "{{ (ti.xcom_pull(task_ids='train') | stage_result)['run_id'] }}"
TASK_TYPE = "{{ params.task_type }}"
MODEL_NAME = "{{ model_name_for(params.task_type) }}"
ESTIMATOR_NAME = "{{ params.estimator_name or default_estimator_for(params.task_type) }}"


def stage(task_id: str, image: str, extra_env: dict) -> DockerOperator:
    """One stage: run an image, stream its logs, take every log line as XCom.

    Args:
        task_id: the Airflow task id, which is also what XCom is pulled by.
        image: the stage image tag, e.g. "ml-extract:latest".
        extra_env: variables specific to this stage, merged over BASE_ENV.
            Values may be Jinja templates; DockerOperator renders them.

    Returns:
        A configured DockerOperator. xcom_all=True (rather than the default
        last-line-only) is required so stage_result() above has the full set of
        lines to scan — see its docstring. auto_remove="success" keeps a failed
        container around to inspect, and removes the rest.

    Example:
        validate = stage(
            "validate",
            "ml-validate:latest",
            {"FINGERPRINT": FINGERPRINT, "TASK_TYPE": TASK_TYPE},
        )
        # FINGERPRINT is a Jinja string pulling extract's XCom, so the value is
        # resolved at run time, not when the DAG file is parsed. BASE_ENV (MinIO
        # and MLflow credentials) is merged in for every stage automatically.
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
    """Reads the evaluate verdict and picks which way the DAG goes.

    Args:
        ti: the task instance Airflow passes in, used to pull evaluate's XCom.

    Returns:
        The task id to run next: "register" when both gates passed,
        "stop_no_deploy" when they did not. The branch that is not chosen is
        skipped, not failed — a model that did not earn promotion is a normal
        outcome of a training run.

    Example:
        # evaluate emitted {"passed": false, "reason": "does not beat the
        # champion: rmse=45000.0000 vs 41000.0000 (lower is better)", ...}
        choose_branch(ti)   # -> "stop_no_deploy"
        # register and deploy are skipped; the DAG run still succeeds.
    """
    verdict = stage_result(ti.xcom_pull(task_ids="evaluate"))
    print(f"evaluate said: {verdict['reason']}")
    return "register" if verdict["passed"] else "stop_no_deploy"


SERVING_RELOAD_URL = os.environ.get("SERVING_URL", "http://serving:8000").rstrip("/") + "/reload"


def reload_serving() -> str:
    """Tells serving to pick up the version that was just registered.

    One HTTP call, so no image and no Airflow Connection: a PythonOperator with
    the standard library is the whole task.

    Args:
        None. Posts to SERVING_URL (default http://serving:8000) + "/reload".

    Returns:
        Serving's response body, which lists the versions now live. It is
        returned rather than only printed so it lands in XCom and the run keeps
        a record of what was deployed.

    Raises:
        urllib.error.URLError: when serving is unreachable or answers an error.
            The task fails, which is the point: the alias moved but nothing is
            serving the new version, and that should be visible in the DAG.

    Example:
        reload_serving()
        # -> '{"models": {"regression": {"loaded": true, "version": "4"}, ...}}'

        # Runs only on the register branch, so serving is asked to reload
        # exactly when there is something new to load.
    """
    request = urllib.request.Request(SERVING_RELOAD_URL, data=b"", method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    print(f"serving reloaded: {body}")
    return body


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
        "estimator_name": None,
        # None = use every row, same as the old default. A triggered run's
        # conf overrides this, which is how the dashboard picks a row count.
        "sample_rows": None,
    },
    # model_name is derived, never passed: a run that names the wrong registered
    # model does not fail, it quietly registers a classifier under the regressor.
    user_defined_macros={
        "model_name_for": MODEL_NAME_BY_TASK_TYPE.__getitem__,
        "default_estimator_for": DEFAULT_ESTIMATOR_BY_TASK_TYPE.__getitem__,
    },
    # Airflow 2.10 has no built-in JSON filter, so register the scan-for-result
    # helper (see stage_result() above) as a Jinja filter for use in templates.
    user_defined_filters={"stage_result": stage_result},
) as dag:
    extract = stage(
        "extract",
        "ml-extract:latest",
        {
            "DATASET_VERSION": "{{ params.dataset_version }}",
            # Airflow merges a triggered run's conf into params, so this covers
            # both the API path and a hand-triggered run.
            "SAMPLE_ROWS": "{{ params.sample_rows or '' }}",
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
            "ESTIMATOR_NAME": ESTIMATOR_NAME,
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

    deploy = PythonOperator(task_id="deploy", python_callable=reload_serving)

    extract >> validate >> prepare_dataset >> train >> evaluate >> branch
    branch >> [register, stop_no_deploy]
    register >> deploy
