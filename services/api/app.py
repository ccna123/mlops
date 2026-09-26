"""HTTP surface the dashboard talks to, and nothing else talks to.

Every collaborator is injected, the same way `services/serving/app.py`
injects its registry and its flush function. That is what lets the routes
be tested without Airflow, MLflow or MinIO running - serving's suite proves
the pattern works, at 20 tests in four seconds.

The dashboard reaches Airflow, MLflow and object storage ONLY through here.
Section 8.2 of the design doc gives the reason: credentials would otherwise
live in the browser, CORS would have to open for several services, and
every backend swap would become a frontend change.
"""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import FastAPI

from ml_common.storage import Storage

from .clients.airflow import AirflowClient
from .clients.registry import RegistryClient
from .clients.reports import ReportsClient
from .clients.serving import ServingClient
from .routes import data, drift, feedback, health, models, pipeline, simulate

logger = logging.getLogger(__name__)


def create_app(
    airflow=None,
    registry=None,
    reports=None,
    probes: dict | None = None,
    storage=None,
    serving=None,
) -> FastAPI:
    """Builds the API application.

    Args:
        airflow: client for Airflow's REST API. None builds the real one from
            the environment, or stays None when the environment lacks it.
        registry: client for the MLflow Model Registry. Same rule as `airflow`.
        reports: reader for drift summaries in object storage. None builds the
            real one on top of `storage`, and stays None when there is no
            storage - a reader wrapped around None would only fail later with
            an AttributeError.
        probes: health probes, name to a zero-argument callable. None builds
            one probe per real dependency.
        storage: `ml_common.storage.Storage` that uploaded datasets are
            written to. Same rule as `airflow`.
        serving: client asked to reload after a manual champion change or a
            model deletion. None builds the real one from SERVING_URL.

    Returns:
        A FastAPI app serving everything under `/api`. A dependency that could
        not be built is left as None and `/health` reports it as down, so the
        app still starts and says what is missing.

    Example:
        # Production - module level, everything real:
        app = create_app()

        # A test - no infrastructure at all:
        app = create_app(probes={"airflow": lambda: True})
    """
    app = FastAPI(title="mlops control room api")
    app.state.airflow = airflow if airflow is not None else _real_airflow()
    app.state.registry = registry if registry is not None else _real_registry()
    app.state.storage = storage if storage is not None else _real_storage()
    app.state.serving = serving if serving is not None else ServingClient()
    if reports is not None:
        app.state.reports = reports
    elif app.state.storage is not None:
        app.state.reports = ReportsClient(app.state.storage)
    else:
        app.state.reports = None
    app.state.probes = probes if probes is not None else _real_probes(app.state)
    app.state.max_upload_bytes = 500 * 1024 * 1024

    app.include_router(health.router, prefix="/api")
    app.include_router(pipeline.router, prefix="/api")
    app.include_router(models.router, prefix="/api")
    app.include_router(drift.router, prefix="/api")
    app.include_router(data.router, prefix="/api")
    app.include_router(simulate.router, prefix="/api")
    app.include_router(feedback.router, prefix="/api")
    return app


def _real_airflow() -> AirflowClient | None:
    """Builds the Airflow client from the environment, or None if it cannot.

    Args:
        None. Reads AIRFLOW_API_URL, AIRFLOW_USERNAME and AIRFLOW_PASSWORD.

    Returns:
        An `AirflowClient`, or None when a variable is absent. None means
        /health reports airflow as down instead of the container dying at
        startup and restarting forever - a dashboard that loads and says what
        is broken beats one that never loads. The None is never silent: a
        WARNING names the missing variable, since a typo'd variable would
        otherwise look like an Airflow outage. Building the client makes no
        request.

    Example:
        _real_airflow()  # -> AirflowClient(...) or None
    """
    try:
        return AirflowClient(
            os.environ["AIRFLOW_API_URL"],
            os.environ["AIRFLOW_USERNAME"],
            os.environ["AIRFLOW_PASSWORD"],
        )
    except KeyError as err:
        logger.warning(
            "airflow client not configured, /health will report it down: "
            "missing environment variable %s",
            err,
            exc_info=True,
        )
        return None


def _real_registry() -> RegistryClient | None:
    """Builds the Model Registry client from the environment, or None if it cannot.

    Args:
        None. Reads MLFLOW_TRACKING_URI.

    Returns:
        A `RegistryClient`, or None when MLFLOW_TRACKING_URI is absent, with a
        WARNING naming it. Same reasoning as `_real_airflow`. Building the
        client makes no request.

    Example:
        _real_registry()  # -> RegistryClient(...) or None
    """
    try:
        return RegistryClient()
    except KeyError as err:
        logger.warning(
            "mlflow client not configured, /health will report it down: "
            "missing environment variable %s",
            err,
            exc_info=True,
        )
        return None


def _real_storage() -> Storage | None:
    """Builds the object storage client from the environment, or None if it cannot.

    Args:
        None. Reads MINIO_ENDPOINT_INTERNAL or MINIO_ENDPOINT, MINIO_ACCESS_KEY,
        MINIO_SECRET_KEY and ML_BUCKET (see `Storage.from_env`).

    Returns:
        A `Storage`, or None when a required variable is absent, with a
        WARNING naming it. Same reasoning as `_real_airflow`. Building the
        client makes no request.

    Example:
        _real_storage()  # -> Storage(...) or None
    """
    try:
        return Storage.from_env()
    except KeyError as err:
        logger.warning(
            "minio client not configured, /health will report it down: "
            "missing environment variable %s",
            err,
            exc_info=True,
        )
        return None


def _real_probes(state) -> dict:
    """Builds one health probe per dependency.

    Args:
        state: the app state holding the already-built clients. A client that
            is None makes its probe answer False.

    Returns:
        Name to a zero-argument callable. Each probe makes the cheapest call
        that proves the dependency answers - one run listed, one registered
        model asked for, one bucket header - never a scan, because /health is
        polled.

    Example:
        _real_probes(app.state)
        # -> {"airflow": <callable>, "mlflow": <callable>, "minio": <callable>,
        #     "serving": <callable>, "postgres": <callable>}
    """

    # Each probe returns True when the call COMPLETED. The value it returns is
    # irrelevant - an empty run list is a healthy Airflow with nothing to show.
    # build_health() turns any raised exception into "down", so these only have
    # to make the call and not defend against failure themselves.
    def airflow_up() -> bool:
        if state.airflow is None:
            return False
        state.airflow.list_runs("ml_pipeline", 1)
        return True

    def mlflow_up() -> bool:
        if state.registry is None:
            return False
        state.registry.ping()
        return True

    def minio_up() -> bool:
        if state.storage is None:
            return False
        state.storage.check_reachable()
        return True

    def serving_up() -> bool:
        url = os.environ.get("SERVING_URL", "http://serving:8000")
        return httpx.get(f"{url}/health", timeout=5.0).status_code == 200

    def postgres_up() -> bool:
        # Airflow answering at all means its metadata database is reachable;
        # there is no separate probe worth the extra dependency. It therefore
        # reads "down" whenever Airflow itself is down, and cannot tell the
        # two apart.
        return airflow_up()

    return {
        "airflow": airflow_up,
        "mlflow": mlflow_up,
        "minio": minio_up,
        "serving": serving_up,
        "postgres": postgres_up,
    }


app = create_app()
