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
    """One model currently in memory, with the version it came from.

    Example:
        loaded = registry.get("regression")
        loaded.name      # -> "house_price_regressor"
        loaded.version   # -> "3", carried so every prediction can say which
                         #    model produced it in the inference log
        loaded.model.predict(pd.DataFrame([raw_record]))
    """

    name: str
    version: str
    model: object


def load_from_mlflow(model_name: str):
    """Fetches the champion of one registered model from MLflow.

    Imported lazily inside the function: mlflow is a heavy import, and the
    tests that inject their own loader must not pay for it.

    Args:
        model_name: the registered model name, e.g. "house_price_regressor".

    Returns:
        A tuple of (the sklearn Pipeline, its registry version as a string).
        The Pipeline carries its own cleaning steps, so it takes raw records.

    Raises:
        Exception: whatever MLflow raises when the model, the alias or the
            server is not there. `ModelRegistry.reload` treats any of it as
            "not available" rather than a failure to report.

    Example:
        model, version = load_from_mlflow("house_price_regressor")
        # -> (Pipeline(steps=[("clean", RawRecordCleaner()), ...]), "3")

        # Whatever holds the champion alias right now — serving pins no
        # version of its own, which is what lets /reload swap models live.
    """
    import mlflow
    import mlflow.sklearn
    from mlflow import MlflowClient

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    version = MlflowClient().get_model_version_by_alias(model_name, CHAMPION_ALIAS)
    model = mlflow.sklearn.load_model(f"models:/{model_name}@{CHAMPION_ALIAS}")
    return model, str(version.version)


class ModelRegistry:
    """Holds the champion of each task type, and swaps them on reload.

    Example:
        registry = ModelRegistry()
        registry.reload()               # on startup, and again on POST /reload
        registry.get("regression")      # -> LoadedModel(...) or None
        registry.describe()             # -> the block /health returns

        # In tests, with no MLflow anywhere:
        registry = ModelRegistry(loader=lambda name: (FakeModel(), "1"))
    """

    def __init__(self, loader=load_from_mlflow):
        """Starts empty — nothing is loaded until `reload` is called.

        Args:
            loader: takes a model name and returns (model, version). Injectable
                so the routes can be tested with MLflow nowhere in sight.
        """
        self._loader = loader
        self._loaded: dict[str, LoadedModel | None] = dict.fromkeys(MODEL_NAMES)

    def reload(self) -> dict[str, LoadedModel | None]:
        """Reloads every champion. A model that cannot be loaded becomes None.

        Args:
            None. Every name in MODEL_NAMES is attempted, so one task's
            failure never keeps the other from being refreshed.

        Returns:
            The internal map from task type to LoadedModel or None, now
            current. Never raises for a missing model: an empty Registry is a
            normal state while the system is being built, not a failure to
            report. Each failure is logged to stderr with its reason.

        Example:
            registry.reload()
            # -> {"regression": LoadedModel("house_price_regressor", "3", ...),
            #     "classification": None}
            # The classifier has no champion yet. Serving still starts, /health
            # reports "degraded", and /predict/regression works normally.
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
        """Looks up the champion currently held for one task type.

        Args:
            task_type: "regression" or "classification".

        Returns:
            The LoadedModel, or None when nothing is loaded for that task —
            which /predict turns into a 503.

        Raises:
            KeyError: for a task type that does not exist, so a typo in a route
                surfaces immediately instead of looking like a missing model.

        Example:
            loaded = registry.get("regression")
            if loaded is None:
                raise HTTPException(503, "no champion loaded; train it, then /reload")
            loaded.model.predict(frame)

            registry.get("regresion")   # -> KeyError, not None
        """
        if task_type not in MODEL_NAMES:
            raise KeyError(f"unknown task type: {task_type!r}")
        return self._loaded[task_type]

    def describe(self) -> dict:
        """Builds the `models` block /health and /reload both return.

        Args:
            None.

        Returns:
            One entry per task type, each holding `loaded`, the registered
            `name`, and `version` — the live version, or None when that task
            has no champion. The model object itself is left out: it does not
            serialize, and no caller of an HTTP endpoint needs it.

        Example:
            registry.describe()
            # -> {"regression": {"loaded": True, "name": "house_price_regressor",
            #                    "version": "3"},
            #     "classification": {"loaded": False,
            #                        "name": "house_needs_renovation_classifier",
            #                        "version": None}}
            # `name` is reported even when nothing is loaded, so /health says
            # WHICH model is missing rather than just that one is.
        """
        return {
            task_type: {
                "loaded": loaded is not None,
                "name": MODEL_NAMES[task_type],
                "version": loaded.version if loaded else None,
            }
            for task_type, loaded in self._loaded.items()
        }
