"""Tests for model lifecycle inside serving, with a fake loader instead of MLflow."""

import pytest

from services.serving.model_registry import MODEL_NAMES, ModelRegistry


class FakeLoader:
    """Stands in for MLflow. Raises for names it was not given."""

    def __init__(self, available: dict):
        self.available = available
        self.calls = 0

    def __call__(self, model_name: str):
        self.calls += 1
        if model_name not in self.available:
            raise RuntimeError(f"no champion for {model_name}")
        return self.available[model_name]


def test_model_names_cover_both_task_types():
    assert set(MODEL_NAMES) == {"regression", "classification"}
    assert MODEL_NAMES["classification"] == "house_needs_renovation_classifier"


def test_reload_loads_every_available_model():
    loader = FakeLoader({name: ("model", "7") for name in MODEL_NAMES.values()})
    registry = ModelRegistry(loader=loader)
    registry.reload()
    assert registry.get("regression").version == "7"
    assert registry.get("classification").version == "7"


def test_a_missing_model_does_not_stop_the_others():
    """Serving must come up before the second model has ever been trained."""
    loader = FakeLoader({MODEL_NAMES["regression"]: ("model", "3")})
    registry = ModelRegistry(loader=loader)
    registry.reload()
    assert registry.get("regression") is not None
    assert registry.get("classification") is None


def test_reload_never_raises_when_nothing_is_available():
    registry = ModelRegistry(loader=FakeLoader({}))
    registry.reload()
    assert registry.get("regression") is None


def test_reload_replaces_the_previous_version():
    loader = FakeLoader({MODEL_NAMES["regression"]: ("old", "1")})
    registry = ModelRegistry(loader=loader)
    registry.reload()
    loader.available[MODEL_NAMES["regression"]] = ("new", "2")
    registry.reload()
    assert registry.get("regression").version == "2"
    assert registry.get("regression").model == "new"


def test_describe_reports_loaded_state_for_both():
    loader = FakeLoader({MODEL_NAMES["regression"]: ("model", "3")})
    registry = ModelRegistry(loader=loader)
    registry.reload()
    described = registry.describe()
    assert described["regression"] == {
        "loaded": True,
        "name": "house_price_regressor",
        "version": "3",
    }
    assert described["classification"] == {
        "loaded": False,
        "name": "house_needs_renovation_classifier",
        "version": None,
    }


def test_describe_is_json_serializable():
    import json

    registry = ModelRegistry(loader=FakeLoader({}))
    registry.reload()
    json.dumps(registry.describe())


def test_get_rejects_an_unknown_task_type():
    registry = ModelRegistry(loader=FakeLoader({}))
    with pytest.raises(KeyError):
        registry.get("clustering")
