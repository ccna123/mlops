"""Loads champion models from the MLflow Registry and keeps them in memory.

Serving ships no model of its own: it asks the Registry for whatever currently
holds the `champion` alias. A model that is not there yet is not an error —
classification has no champion until that branch has been trained, and serving
must still come up and say so.

The loader is injectable so the routes can be tested without MLflow running.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

CHAMPION_ALIAS = "champion"

MODEL_NAMES: dict[str, str] = {
    "regression": "house_price_regressor",
    "classification": "house_needs_renovation_classifier",
}


@dataclass(frozen=True)
class LoadedModel:
    """One model currently in memory, with the version it came from."""

    name: str
    version: str
    model: object


def load_from_mlflow(model_name: str):
    """Fetches the champion of one registered model. Returns (model, version)."""
    import mlflow
    import mlflow.sklearn
    from mlflow import MlflowClient

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    version = MlflowClient().get_model_version_by_alias(model_name, CHAMPION_ALIAS)
    model = mlflow.sklearn.load_model(f"models:/{model_name}@{CHAMPION_ALIAS}")
    return model, str(version.version)


class ModelRegistry:
    """Holds the champion of each task type, and swaps them on reload."""

    def __init__(self, loader=load_from_mlflow):
        self._loader = loader
        self._loaded: dict[str, LoadedModel | None] = dict.fromkeys(MODEL_NAMES)

    def reload(self) -> dict[str, LoadedModel | None]:
        """Reloads every champion. A model that cannot be loaded becomes None.

        Never raises for a missing model: an empty Registry is a normal state
        while the system is being built, not a failure to report.
        """
        for task_type, model_name in MODEL_NAMES.items():
            try:
                model, version = self._loader(model_name)
                self._loaded[task_type] = LoadedModel(model_name, version, model)
            except Exception as err:  # noqa: BLE001 - any failure means "not available"
                print(f"could not load {model_name}: {err}", file=sys.stderr)
                self._loaded[task_type] = None
        return self._loaded

    def get(self, task_type: str) -> LoadedModel | None:
        """The model for a task type, or None when it is not loaded.

        Raises KeyError for a task type that does not exist, so a typo in a
        route surfaces immediately instead of looking like a missing model.
        """
        if task_type not in MODEL_NAMES:
            raise KeyError(f"unknown task type: {task_type!r}")
        return self._loaded[task_type]

    def describe(self) -> dict:
        """The `models` block /health and /reload both return."""
        return {
            task_type: {
                "loaded": loaded is not None,
                "name": MODEL_NAMES[task_type],
                "version": loaded.version if loaded else None,
            }
            for task_type, loaded in self._loaded.items()
        }
