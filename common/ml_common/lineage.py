"""Tracing a model version back to the data it learned from (NV-09).

model version -> the run that produced it -> the data ID it logged (param
`fingerprint`) -> its train set in `processed/`. Evaluation, monitoring and the
simulation agent all walk this path, so it lives in one place.

MLflow is not a dependency of ml_common, so the client is passed in and only
used through the few calls below (`MlflowClient` fits).
"""

from __future__ import annotations

from .storage import processed_key

CHAMPION_ALIAS = "champion"

# MLflow answers a missing registered model with RESOURCE_DOES_NOT_EXIST, but a
# missing alias on an existing model with INVALID_PARAMETER_VALUE.
_NOT_FOUND_CODES = frozenset({"RESOURCE_DOES_NOT_EXIST", "INVALID_PARAMETER_VALUE"})


def champion_version(client, model_name: str):
    """Finds the model version holding the champion alias.

    Args:
        client: an `MlflowClient`.
        model_name: the registered model.

    Returns:
        The ModelVersion, or None when the model or the alias does not exist.
        Only a missing resource becomes None; a failure to reach MLflow still
        raises, so an outage is not mistaken for "no champion yet".

    Example:
        version = champion_version(MlflowClient(), "house_price_regressor")
        version.version, version.run_id  # -> ("4", "a1b2c3...")
    """
    try:
        return client.get_model_version_by_alias(model_name, CHAMPION_ALIAS)
    except Exception as error:
        if getattr(error, "error_code", "") in _NOT_FOUND_CODES:
            return None
        raise


def run_params(client, run_id: str) -> dict:
    """Reads the params a run logged.

    Args:
        client: an `MlflowClient`.
        run_id: the run.

    Returns:
        The params, as strings.

    Example:
        run_params(client, run_id)["dataset_version"]  # -> "v2"
    """
    return dict(client.get_run(run_id).data.params)


def train_set_key(client, run_id: str, task_type: str) -> str:
    """Finds the train set a run learned from.

    Args:
        client: an `MlflowClient`.
        run_id: the training run.
        task_type: "regression" or "classification".

    Returns:
        The `processed/` key of that run's train set.

    Raises:
        KeyError: when the run logged no `fingerprint` (it was not trained by
            the pipeline). Guessing would compare against the wrong data.

    Example:
        train_set_key(client, run_id, "regression")
        # -> "processed/3f0a9c1d5e2b7a48/regression/train.parquet"
    """
    data_id = run_params(client, run_id)["fingerprint"]
    return processed_key(data_id, task_type, "train")
