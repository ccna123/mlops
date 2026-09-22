"""traffic_agent - sends simulated traffic to serving, on demand.

Drift can only be measured against predictions serving has actually logged.
On a dev box no real caller exists, so every drift verdict reads
`insufficient_data` until somebody produces traffic. This DAG is the button
behind that: one container, one bounded batch of requests, then it exits.

The container is `ml-agent:latest`, the same image the compose `agent`
profile loops over. Nothing in `services/agent/` knows this DAG exists - the
scenario, the model and the request count arrive as command line arguments,
exactly as they would from a shell.

Left unpaused deliberately (`is_paused_upon_creation=False`, which overrides
AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION for this DAG alone). A triggered
run of a paused DAG sits in `queued` forever and no signal anywhere says
why - half a day went into learning that on 2026-09-21, and a dashboard
button that silently does nothing is worse than no button.
"""

from __future__ import annotations

import os

import pendulum
from airflow import DAG
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.providers.docker.operators.docker import DockerOperator

DOCKER_URL = "unix://var/run/docker.sock"
NETWORK = "mlops_default"

_MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT_INTERNAL", "http://minio:9000")
_MINIO_KEY = os.environ.get("MINIO_ACCESS_KEY", "")
_MINIO_SECRET = os.environ.get("MINIO_SECRET_KEY", "")

BASE_ENV = {
    "MINIO_ENDPOINT_INTERNAL": _MINIO_ENDPOINT,
    "MINIO_ACCESS_KEY": _MINIO_KEY,
    "MINIO_SECRET_KEY": _MINIO_SECRET,
    "ML_BUCKET": os.environ.get("ML_BUCKET", "ml-pipeline"),
    "SERVING_URL": "http://serving:8000",
    "DATASET_VERSION": os.environ.get("DATASET_VERSION", "v1"),
}

with DAG(
    dag_id="traffic_agent",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    # One batch at a time. Two agents against one serving container would
    # interleave their requests in the inference log, and the drift report
    # would then describe a mixture of two scenarios as though it were one.
    max_active_runs=1,
    is_paused_upon_creation=False,
    tags=["ml", "monitoring"],
    params={
        "scenario": "none",
        "task_type": "regression",
        "count": 300,
    },
) as dag:
    send_traffic = DockerOperator(
        task_id="send_traffic",
        image="ml-agent:latest",
        docker_url=DOCKER_URL,
        network_mode=NETWORK,
        environment=BASE_ENV,
        command=[
            "python",
            "-m",
            "services.agent",
            "--scenario",
            "{{ params.scenario }}",
            "--task-type",
            "{{ params.task_type }}",
            "--count",
            "{{ params.count }}",
            # A fixed seed would send the same houses every time, so repeated
            # runs of one scenario would pile up duplicate rows rather than
            # widening the sample. The run's own timestamp varies per run and
            # still records which sample was used.
            "--seed",
            "{{ data_interval_start.int_timestamp }}",
        ],
        auto_remove="success",
        mount_tmp_dir=False,
        do_xcom_push=True,
        xcom_all=True,
    )

    # Traffic that nobody measures answers nothing, and until 2026-09-22 the
    # measuring was a second button the user had to press at the right moment -
    # which meant opening Airflow to find out when the traffic had landed.
    # Chained here rather than in the dashboard so the drift still gets
    # computed if the browser is closed halfway through.
    compute_drift = TriggerDagRunOperator(
        task_id="compute_drift",
        trigger_dag_id="monitoring_dag",
        # Waits, so this run's own state answers "is the whole thing done?".
        # It holds a worker slot for the minute or so monitoring takes; that is
        # the price of having one run to poll instead of two to correlate.
        wait_for_completion=True,
        poke_interval=10,
        # A monitoring run that fails must fail this task too. Left at the
        # defaults, a failed monitoring run would wait forever.
        allowed_states=["success"],
        failed_states=["failed"],
    )

    send_traffic >> compute_drift
