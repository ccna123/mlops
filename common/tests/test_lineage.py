from types import SimpleNamespace

import pytest

from ml_common import lineage


class MissingError(Exception):
    error_code = "RESOURCE_DOES_NOT_EXIST"


class FakeClient:
    def __init__(self, versions=None, params=None, error=None):
        self.versions = versions or {}
        self.params = params or {}
        self.error = error

    def get_model_version_by_alias(self, name, alias):
        if self.error:
            raise self.error
        if name not in self.versions:
            raise MissingError(name)
        return self.versions[name]

    def get_run(self, run_id):
        return SimpleNamespace(data=SimpleNamespace(params=self.params[run_id]))


def test_champion_version_is_none_when_there_is_none():
    assert lineage.champion_version(FakeClient(), "m") is None


def test_an_outage_is_not_mistaken_for_no_champion():
    with pytest.raises(ConnectionError):
        lineage.champion_version(FakeClient(error=ConnectionError("down")), "m")


def test_train_set_key_follows_the_logged_data_id():
    client = FakeClient(params={"r1": {"fingerprint": "abc"}})
    assert lineage.train_set_key(client, "r1", "regression") == (
        "processed/abc/regression/train.parquet"
    )


def test_a_run_without_data_id_raises():
    with pytest.raises(KeyError):
        lineage.train_set_key(FakeClient(params={"r1": {}}), "r1", "regression")


def test_a_missing_alias_on_an_existing_model_is_no_champion():
    class AliasMissing(Exception):
        error_code = "INVALID_PARAMETER_VALUE"

    assert lineage.champion_version(FakeClient(error=AliasMissing("no alias")), "m") is None
