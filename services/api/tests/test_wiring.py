"""Tests for what `create_app()` builds when nothing is injected, and the probes.

Every fake here RECORDS what it was called with. A fake that answers whatever
it is asked would pass with the wrong method or the wrong arguments, and this
file exists to catch exactly that.

No test may touch the network. The autouse guard below turns any outbound
connection or DNS lookup into a recorded attempt, and the tests that build
real clients assert none was made.
"""

import logging
import socket

import httpx
import mlflow.tracking._tracking_service.utils as mlflow_utils
import pytest
from fastapi.testclient import TestClient
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

import services.api.app as app_module
from ml_common.storage import Storage
from services.api.app import create_app
from services.api.clients.airflow import AirflowClient
from services.api.clients.registry import RegistryClient
from services.api.clients.reports import ReportsClient

ENV_VARS = (
    "AIRFLOW_API_URL",
    "AIRFLOW_USERNAME",
    "AIRFLOW_PASSWORD",
    "MLFLOW_TRACKING_URI",
    "MINIO_ENDPOINT_INTERNAL",
    "MINIO_ENDPOINT",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
    "SERVING_URL",
    "ML_BUCKET",
)

FIVE_SERVICES = {"airflow", "mlflow", "minio", "serving", "postgres"}
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def no_environment(monkeypatch):
    """Starts every test with none of the variables the wiring reads."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def network_attempts(monkeypatch):
    """Records every non-loopback connection or DNS lookup instead of making it.

    Loopback stays open because asyncio (which TestClient runs on) connects a
    socket pair to itself on Windows.
    """
    attempts: list[str] = []
    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in LOOPBACK:
            attempts.append(f"connect {address}")
            raise OSError("network is off in test_wiring")
        return real_connect(self, address)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host not in LOOPBACK and host is not None:
            attempts.append(f"resolve {host}")
            raise OSError("network is off in test_wiring")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    return attempts


@pytest.fixture
def get_calls(monkeypatch):
    """Replaces httpx.get with a recorder and returns the list it records to.

    Set `get_calls.status` (an int) or `get_calls.error` (an exception) to
    choose what the next calls do.
    """

    class Recorder(list):
        status = 200
        error = None

    recorded = Recorder()

    def fake_get(url, **kwargs):
        recorded.append((url, kwargs))
        if recorded.error is not None:
            raise recorded.error
        return httpx.Response(recorded.status, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    return recorded


class RecordingAirflow:
    """Has only `list_runs`, so calling anything else fails loudly."""

    def __init__(self, error=None):
        self.calls = []
        self._error = error

    def list_runs(self, dag_id, limit):
        self.calls.append(("list_runs", dag_id, limit))
        if self._error is not None:
            raise self._error
        return []


class RecordingRegistry:
    """`ping` records; `list_models` raises so a probe that still uses it fails."""

    def __init__(self, error=None):
        self.calls = []
        self._error = error

    def ping(self):
        self.calls.append(("ping",))
        if self._error is not None:
            raise self._error

    def list_models(self):
        raise AssertionError("the mlflow probe must not call list_models - too expensive to poll")


class RecordingStorage:
    """`check_reachable` records; the scanning and swallowing methods raise."""

    def __init__(self, error=None):
        self.calls = []
        self._error = error

    def check_reachable(self):
        self.calls.append(("check_reachable",))
        if self._error is not None:
            raise self._error

    def list_keys(self, prefix):
        raise AssertionError("the minio probe must not list keys - a full scan on every poll")

    def exists(self, key):
        raise AssertionError("exists() swallows every error, so it cannot prove reachability")


class State:
    """Stands in for `app.state`: just the three clients the probes read."""

    def __init__(self, airflow=None, registry=None, storage=None):
        self.airflow = airflow
        self.registry = registry
        self.storage = storage


def _set_dummy_environment(monkeypatch):
    monkeypatch.setenv("AIRFLOW_API_URL", "http://airflow.invalid:8080/api/v1")
    monkeypatch.setenv("AIRFLOW_USERNAME", "dash-user")
    monkeypatch.setenv("AIRFLOW_PASSWORD", "dash-pass")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow.invalid:5000")
    monkeypatch.setenv("MINIO_ENDPOINT_INTERNAL", "http://minio.invalid:9000")
    monkeypatch.setenv("MINIO_ENDPOINT", "http://not-this-one.invalid:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "dummy-access")
    monkeypatch.setenv("MINIO_SECRET_KEY", "dummy-secret")
    monkeypatch.setenv("ML_BUCKET", "wiring-bucket")
    # set_tracking_uri writes module-level state; monkeypatch puts it back.
    monkeypatch.setattr(mlflow_utils, "_tracking_uri", None)


# --- 1. nothing configured -------------------------------------------------


def test_with_no_environment_the_app_starts_and_health_reports_all_five_down(
    get_calls, network_attempts
):
    get_calls.error = httpx.ConnectError("serving is not there")

    client = TestClient(create_app())
    body = client.get("/api/health").json()

    assert body["status"] == "degraded"
    assert body["services"] == {name: "down" for name in FIVE_SERVICES}
    # The serving probe is the only one that can be "down" for a reason other
    # than a None client - prove it really tried, and only once.
    assert [url for url, _ in get_calls] == ["http://serving:8000/health"]
    assert network_attempts == []


def test_with_no_environment_every_client_is_none_and_so_are_reports():
    app = create_app()

    assert app.state.airflow is None
    assert app.state.registry is None
    assert app.state.storage is None
    assert app.state.reports is None


# --- 2. the builders -------------------------------------------------------


def test_builders_return_the_real_clients_configured_from_the_environment(
    monkeypatch, network_attempts
):
    _set_dummy_environment(monkeypatch)

    airflow = app_module._real_airflow()
    registry = app_module._real_registry()
    storage = app_module._real_storage()

    assert isinstance(airflow, AirflowClient)
    assert airflow._base == "http://airflow.invalid:8080/api/v1"
    assert airflow._auth == ("dash-user", "dash-pass")

    assert isinstance(registry, RegistryClient)
    assert isinstance(registry._client, MlflowClient)
    assert mlflow_utils._tracking_uri == "http://mlflow.invalid:5000"

    assert isinstance(storage, Storage)
    assert storage.bucket == "wiring-bucket"
    # MINIO_ENDPOINT_INTERNAL wins over MINIO_ENDPOINT inside a container.
    assert storage._client.meta.endpoint_url == "http://minio.invalid:9000"

    assert network_attempts == []


def test_create_app_from_the_environment_builds_every_client_and_reports(
    monkeypatch, network_attempts
):
    _set_dummy_environment(monkeypatch)

    app = create_app()

    assert isinstance(app.state.airflow, AirflowClient)
    assert isinstance(app.state.registry, RegistryClient)
    assert isinstance(app.state.storage, Storage)
    assert isinstance(app.state.reports, ReportsClient)
    assert app.state.reports._storage is app.state.storage
    assert set(app.state.probes) == FIVE_SERVICES
    assert network_attempts == []


@pytest.mark.parametrize("missing", ["AIRFLOW_API_URL", "AIRFLOW_USERNAME", "AIRFLOW_PASSWORD"])
def test_airflow_builder_returns_none_when_any_of_its_variables_is_missing(monkeypatch, missing):
    _set_dummy_environment(monkeypatch)
    monkeypatch.delenv(missing)

    assert app_module._real_airflow() is None


def test_registry_builder_returns_none_without_a_tracking_uri(monkeypatch):
    _set_dummy_environment(monkeypatch)
    monkeypatch.delenv("MLFLOW_TRACKING_URI")

    assert app_module._real_registry() is None


@pytest.mark.parametrize("missing", ["MINIO_ACCESS_KEY", "MINIO_SECRET_KEY"])
def test_storage_builder_returns_none_when_a_credential_is_missing(monkeypatch, missing):
    _set_dummy_environment(monkeypatch)
    monkeypatch.delenv(missing)

    assert app_module._real_storage() is None


def test_storage_builder_returns_none_when_neither_endpoint_is_set(monkeypatch):
    _set_dummy_environment(monkeypatch)
    monkeypatch.delenv("MINIO_ENDPOINT_INTERNAL")
    monkeypatch.delenv("MINIO_ENDPOINT")

    assert app_module._real_storage() is None


def test_storage_builder_falls_back_to_the_host_endpoint(monkeypatch):
    _set_dummy_environment(monkeypatch)
    monkeypatch.delenv("MINIO_ENDPOINT_INTERNAL")

    storage = app_module._real_storage()

    assert storage._client.meta.endpoint_url == "http://not-this-one.invalid:9000"


# --- 3. the probes ---------------------------------------------------------


def test_airflow_probe_lists_one_run_of_ml_pipeline():
    airflow = RecordingAirflow()

    probes = app_module._real_probes(State(airflow=airflow))

    assert probes["airflow"]() is True
    assert airflow.calls == [("list_runs", "ml_pipeline", 1)]


def test_postgres_probe_is_the_airflow_probe():
    airflow = RecordingAirflow()

    probes = app_module._real_probes(State(airflow=airflow))

    assert probes["postgres"]() is True
    assert airflow.calls == [("list_runs", "ml_pipeline", 1)]


def test_mlflow_probe_pings_and_never_lists_models():
    registry = RecordingRegistry()

    probes = app_module._real_probes(State(registry=registry))

    assert probes["mlflow"]() is True
    assert registry.calls == [("ping",)]


def test_minio_probe_checks_the_bucket_and_never_lists_or_uses_exists():
    storage = RecordingStorage()

    probes = app_module._real_probes(State(storage=storage))

    assert probes["minio"]() is True
    assert storage.calls == [("check_reachable",)]


@pytest.mark.parametrize("name", ["airflow", "mlflow", "minio", "postgres"])
def test_a_probe_is_false_when_its_client_is_none(name):
    probes = app_module._real_probes(State())

    assert probes[name]() is False


@pytest.mark.parametrize(
    ("name", "state_kwarg", "fake"),
    [
        ("airflow", "airflow", RecordingAirflow),
        ("postgres", "airflow", RecordingAirflow),
        ("mlflow", "registry", RecordingRegistry),
        ("minio", "storage", RecordingStorage),
    ],
)
def test_a_probe_lets_the_exception_propagate_instead_of_answering(name, state_kwarg, fake):
    failing = fake(error=ConnectionError("refused"))

    probes = app_module._real_probes(State(**{state_kwarg: failing}))

    with pytest.raises(ConnectionError, match="refused"):
        probes[name]()


def test_health_reports_down_for_the_probe_whose_call_raised_and_ok_for_the_rest(get_calls):
    airflow = RecordingAirflow(error=RuntimeError("airflow exploded"))
    registry = RecordingRegistry()
    storage = RecordingStorage()

    client = TestClient(create_app(airflow=airflow, registry=registry, storage=storage))
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["services"] == {
        "airflow": "down",
        "mlflow": "ok",
        "minio": "ok",
        "serving": "ok",
        "postgres": "down",
    }
    assert registry.calls == [("ping",)]
    assert storage.calls == [("check_reachable",)]


def test_health_reports_a_failing_mlflow_and_minio_down_too(get_calls):
    registry = RecordingRegistry(error=MlflowException("mlflow is down"))
    storage = RecordingStorage(error=OSError("minio is down"))

    client = TestClient(create_app(airflow=RecordingAirflow(), registry=registry, storage=storage))
    services = client.get("/api/health").json()["services"]

    assert services["mlflow"] == "down"
    assert services["minio"] == "down"
    assert services["airflow"] == "ok"


# --- 4. the serving probe --------------------------------------------------


def test_serving_probe_is_true_on_http_200(get_calls):
    get_calls.status = 200

    assert app_module._real_probes(State())["serving"]() is True


@pytest.mark.parametrize("status", [201, 204, 301, 404, 500, 503])
def test_serving_probe_is_false_on_any_other_status(get_calls, status):
    get_calls.status = status

    assert app_module._real_probes(State())["serving"]() is False


def test_serving_probe_requests_health_on_the_default_serving_url(get_calls):
    app_module._real_probes(State())["serving"]()

    ((url, kwargs),) = get_calls
    assert url == "http://serving:8000/health"
    assert kwargs.get("timeout"), "a hung serving must not hang /health"


def test_serving_probe_requests_health_on_serving_url_when_it_is_set(monkeypatch, get_calls):
    monkeypatch.setenv("SERVING_URL", "http://serving.example:9100")

    app_module._real_probes(State())["serving"]()

    assert [url for url, _ in get_calls] == ["http://serving.example:9100/health"]


def test_serving_probe_lets_a_connection_error_propagate(get_calls):
    get_calls.error = httpx.ConnectError("refused")

    with pytest.raises(httpx.ConnectError):
        app_module._real_probes(State())["serving"]()


# --- 5. reports ------------------------------------------------------------


def test_reports_wraps_the_injected_storage():
    storage = RecordingStorage()

    app = create_app(storage=storage)

    assert isinstance(app.state.reports, ReportsClient)
    assert app.state.reports._storage is storage


def test_reports_is_none_when_storage_is_none():
    app = create_app(storage=None)

    assert app.state.storage is None
    assert app.state.reports is None


def test_an_injected_reports_client_is_kept_even_without_storage():
    injected = object()

    app = create_app(reports=injected)

    assert app.state.reports is injected


def test_injected_clients_and_probes_are_used_as_given():
    airflow, registry, storage = RecordingAirflow(), RecordingRegistry(), RecordingStorage()
    probes = {"only": lambda: True}

    app = create_app(airflow=airflow, registry=registry, storage=storage, probes=probes)

    assert app.state.airflow is airflow
    assert app.state.registry is registry
    assert app.state.storage is storage
    assert app.state.probes is probes


# --- 6. a dependency that is not configured is logged, not silently None ----

APP_LOGGER = "services.api.app"


def _warnings(caplog):
    return [r for r in caplog.records if r.name == APP_LOGGER and r.levelno >= logging.WARNING]


@pytest.mark.parametrize(
    ("builder", "dependency", "missing"),
    [
        ("_real_airflow", "airflow", "AIRFLOW_API_URL"),
        ("_real_airflow", "airflow", "AIRFLOW_USERNAME"),
        ("_real_airflow", "airflow", "AIRFLOW_PASSWORD"),
        ("_real_registry", "mlflow", "MLFLOW_TRACKING_URI"),
        ("_real_storage", "minio", "MINIO_ACCESS_KEY"),
        ("_real_storage", "minio", "MINIO_SECRET_KEY"),
        ("_real_storage", "minio", "MINIO_ENDPOINT"),
    ],
)
def test_a_builder_warns_naming_the_dependency_and_the_missing_variable(
    monkeypatch, caplog, builder, dependency, missing
):
    _set_dummy_environment(monkeypatch)
    monkeypatch.delenv(missing)
    if missing == "MINIO_ENDPOINT":
        monkeypatch.delenv("MINIO_ENDPOINT_INTERNAL")

    with caplog.at_level(logging.WARNING, logger=APP_LOGGER):
        result = getattr(app_module, builder)()

    assert result is None
    (record,) = _warnings(caplog)
    assert dependency in record.getMessage()
    assert missing in record.getMessage()
    # The traceback rides along, so a KeyError from deeper than the env read
    # can still be traced to where it came from.
    assert record.exc_info is not None
    assert isinstance(record.exc_info[1], KeyError)


def test_create_app_with_no_environment_logs_one_warning_per_unbuilt_client(caplog):
    with caplog.at_level(logging.WARNING, logger=APP_LOGGER):
        create_app()

    messages = [r.getMessage() for r in _warnings(caplog)]
    assert len(messages) == 3
    assert any("airflow" in m and "AIRFLOW_API_URL" in m for m in messages)
    assert any("mlflow" in m and "MLFLOW_TRACKING_URI" in m for m in messages)
    assert any("minio" in m and "MINIO_ENDPOINT" in m for m in messages)


def test_a_fully_configured_environment_logs_no_warning(monkeypatch, caplog):
    _set_dummy_environment(monkeypatch)

    with caplog.at_level(logging.WARNING, logger=APP_LOGGER):
        create_app()

    assert _warnings(caplog) == []
