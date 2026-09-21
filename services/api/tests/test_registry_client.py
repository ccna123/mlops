from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from mlflow.exceptions import MlflowException
from mlflow.protos.databricks_pb2 import (
    INTERNAL_ERROR,
    INVALID_PARAMETER_VALUE,
    RESOURCE_DOES_NOT_EXIST,
)

from services.api.clients.registry import (
    RegistryClient,
    RegistryConflictError,
    RegistryNotFoundError,
)

REGRESSOR = "house_price_regressor"


class FakeMlflowClient:
    """Stands in for MlflowClient at the level RegistryClient actually calls.

    Records what set_registered_model_alias RECEIVED, so a test can assert the
    argument order rather than trusting what came back.
    """

    def __init__(
        self,
        versions=None,
        runs=None,
        champion=None,
        alias_error=None,
        set_alias_error=None,
        model_names=(REGRESSOR,),
        delete_error=None,
    ):
        self.versions = versions if versions is not None else []
        self.runs = runs if runs is not None else {}
        self.champion = champion
        self.alias_error = alias_error
        self.set_alias_error = set_alias_error
        self.model_names = model_names
        self.delete_error = delete_error
        self.alias_calls = []
        self.calls = []
        self.deleted = []
        self.deleted_models = []

    def search_registered_models(self, max_results=None):
        self.calls.append(("search_registered_models", {"max_results": max_results}))
        return [SimpleNamespace(name=name) for name in self.model_names]

    def get_model_version_by_alias(self, name, alias):
        if self.alias_error:
            raise self.alias_error
        if self.champion is None:
            # What MLflow 2.22 really raises for a model whose alias was never set.
            raise MlflowException(
                f"Registered model alias {alias} not found.", error_code=INVALID_PARAMETER_VALUE
            )
        return SimpleNamespace(version=self.champion)

    def search_model_versions(self, filter_string):
        self.calls.append(("search_model_versions", {"filter_string": filter_string}))
        return self.versions

    def get_run(self, run_id):
        self.calls.append(("get_run", {"run_id": run_id}))
        return SimpleNamespace(data=SimpleNamespace(metrics=self.runs.get(run_id, {})))

    def set_registered_model_alias(self, name, alias, version):
        if self.set_alias_error:
            raise self.set_alias_error
        self.alias_calls.append((name, alias, version))

    def delete_model_version(self, name, version):
        if self.delete_error:
            raise self.delete_error
        self.deleted.append((name, version))

    def delete_registered_model(self, name):
        if self.delete_error:
            raise self.delete_error
        self.deleted_models.append(name)


def _version(number, created_ms=1_000):
    return SimpleNamespace(
        version=str(number), run_id=f"run{number}", creation_timestamp=created_ms
    )


def _only_model(mlflow_client):
    (model,) = RegistryClient(client=mlflow_client).list_models()
    return model


def test_creation_timestamp_in_milliseconds_becomes_an_iso_string_in_utc():
    created_ms = 1_789_812_000_000
    fake = FakeMlflowClient(versions=[_version(1, created_ms=created_ms)])

    version = _only_model(fake)["versions"][0]

    assert version["created_at"] == "2026-09-19T10:00:00+00:00"
    assert version["created_at"] == datetime.fromtimestamp(created_ms / 1000, tz=UTC).isoformat()


def test_test_prefix_is_stripped_and_other_metrics_are_excluded():
    logged = {
        "test_rmse": 41203.7,
        "test_r2": 0.947,
        "champion_test_rmse": 39000.0,
        "train_rmse": 30000.0,
        "cv_rmse": 35000.0,
    }
    fake = FakeMlflowClient(versions=[_version(1)], runs={"run1": logged})

    metrics = _only_model(fake)["versions"][0]["metrics"]

    assert metrics == {"rmse": 41203.7, "r2": 0.947}


def test_task_type_comes_from_the_model_name():
    fake = FakeMlflowClient(model_names=("house_needs_renovation_classifier", "something_else"))

    models = RegistryClient(client=fake).list_models()

    assert [m["task_type"] for m in models] == ["classification", None]


def test_champion_is_flagged_through_the_alias():
    fake = FakeMlflowClient(versions=[_version(1), _version(2), _version(3)], champion="2")

    versions = _only_model(fake)["versions"]

    assert {v["version"]: v["is_champion"] for v in versions} == {
        "1": False,
        "2": True,
        "3": False,
    }


def test_no_champion_alias_means_no_version_is_flagged():
    fake = FakeMlflowClient(versions=[_version(1), _version(2)], champion=None)

    versions = _only_model(fake)["versions"]

    assert [v["is_champion"] for v in versions] == [False, False]


def test_missing_alias_reported_as_resource_does_not_exist_also_means_no_champion():
    # A later MLflow may report a missing alias this way instead of INVALID_PARAMETER_VALUE.
    error = MlflowException("gone", error_code=RESOURCE_DOES_NOT_EXIST)
    fake = FakeMlflowClient(versions=[_version(1)], alias_error=error)

    assert _only_model(fake)["versions"][0]["is_champion"] is False


def test_champion_lookup_failing_for_another_reason_is_raised_not_read_as_no_champion():
    error = MlflowException("connection refused", error_code=INTERNAL_ERROR)
    fake = FakeMlflowClient(versions=[_version(1)], alias_error=error)

    with pytest.raises(MlflowException, match="connection refused"):
        RegistryClient(client=fake).list_models()


def test_invalid_parameter_that_is_not_a_missing_alias_is_raised():
    error = MlflowException("alias name is malformed", error_code=INVALID_PARAMETER_VALUE)
    fake = FakeMlflowClient(versions=[_version(1)], alias_error=error)

    with pytest.raises(MlflowException, match="malformed"):
        RegistryClient(client=fake).list_models()


def test_versions_sort_numerically_newest_first():
    # As strings "10" < "9"; the sort must be on the integer.
    fake = FakeMlflowClient(versions=[_version(9), _version(10), _version(2), _version(1)])

    versions = _only_model(fake)["versions"]

    assert [v["version"] for v in versions] == ["10", "9", "2", "1"]


def test_promote_sets_the_champion_alias_with_name_alias_version_in_that_order():
    fake = FakeMlflowClient()

    result = RegistryClient(client=fake).promote(REGRESSOR, "4")

    assert fake.alias_calls == [(REGRESSOR, "champion", "4")]
    assert result == {"name": REGRESSOR, "version": "4", "alias": "champion"}


def test_promote_translates_resource_does_not_exist_into_the_domain_error():
    error = MlflowException("Model Version not found", error_code=RESOURCE_DOES_NOT_EXIST)
    fake = FakeMlflowClient(set_alias_error=error)

    with pytest.raises(RegistryNotFoundError, match="not found"):
        RegistryClient(client=fake).promote(REGRESSOR, "99999")


def test_promote_lets_any_other_mlflow_error_propagate():
    error = MlflowException("server exploded", error_code=INTERNAL_ERROR)
    fake = FakeMlflowClient(set_alias_error=error)

    with pytest.raises(MlflowException, match="server exploded") as caught:
        RegistryClient(client=fake).promote(REGRESSOR, "4")

    assert not isinstance(caught.value, RegistryNotFoundError)


def test_ping_asks_mlflow_for_a_single_registered_model_and_nothing_else():
    # /health polls this: it must not walk every version of every model.
    fake = FakeMlflowClient(versions=[_version(1), _version(2)], runs={"run1": {"test_rmse": 1.0}})

    result = RegistryClient(client=fake).ping()

    assert result is None
    assert fake.calls == [("search_registered_models", {"max_results": 1})]


def test_ping_lets_an_mlflow_failure_propagate():
    class Unreachable(FakeMlflowClient):
        def search_registered_models(self, max_results=None):
            raise MlflowException("connection refused", error_code=INTERNAL_ERROR)

    with pytest.raises(MlflowException, match="connection refused"):
        RegistryClient(client=Unreachable()).ping()


def test_delete_version_removes_a_version_that_is_not_the_champion():
    fake = FakeMlflowClient(champion="3")

    RegistryClient(client=fake).delete_version(REGRESSOR, "2")

    assert fake.deleted == [(REGRESSOR, "2")]


def test_delete_version_refuses_the_champion_and_never_calls_mlflow():
    # serving resolves the champion alias to load its model. Deleting that
    # version would break the next reload, so this has to be refused before
    # MLflow is asked - an "oops" here is not recoverable.
    fake = FakeMlflowClient(champion="3")

    with pytest.raises(RegistryConflictError, match="champion"):
        RegistryClient(client=fake).delete_version(REGRESSOR, "3")

    assert fake.deleted == []


def test_delete_version_works_when_the_model_has_no_champion_at_all():
    fake = FakeMlflowClient(champion=None)

    RegistryClient(client=fake).delete_version(REGRESSOR, "1")

    assert fake.deleted == [(REGRESSOR, "1")]


def test_delete_version_maps_a_missing_version_to_registry_not_found():
    fake = FakeMlflowClient(
        champion="3",
        delete_error=MlflowException("not found", error_code=RESOURCE_DOES_NOT_EXIST),
    )

    with pytest.raises(RegistryNotFoundError):
        RegistryClient(client=fake).delete_version(REGRESSOR, "2")


def test_delete_model_removes_the_registered_model_champion_and_all():
    # No champion check here, unlike delete_version: taking the champion with
    # it is the whole point of deleting a model.
    fake = FakeMlflowClient(champion="3")

    RegistryClient(client=fake).delete_model(REGRESSOR)

    assert fake.deleted_models == [REGRESSOR]


def test_delete_model_maps_a_missing_model_to_registry_not_found():
    fake = FakeMlflowClient(
        delete_error=MlflowException("not found", error_code=RESOURCE_DOES_NOT_EXIST)
    )

    with pytest.raises(RegistryNotFoundError):
        RegistryClient(client=fake).delete_model(REGRESSOR)


def test_delete_version_lets_an_outage_propagate_instead_of_reading_as_missing():
    fake = FakeMlflowClient(
        champion="3", delete_error=MlflowException("mlflow down", error_code=INTERNAL_ERROR)
    )

    with pytest.raises(MlflowException) as caught:
        RegistryClient(client=fake).delete_version(REGRESSOR, "2")

    assert not isinstance(caught.value, RegistryNotFoundError)
