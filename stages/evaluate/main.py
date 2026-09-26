"""Evaluate stage: score the candidate and decide whether it may be promoted.

Two gates, both required. The first blocks junk on an absolute threshold. The
second blocks a model from displacing the champion unless it is better by a
margin, scored on the SAME test set - which is why the test set is fixed by the
dataset version's split points.

It also reports, for reading only: metrics per city and per property type, and
how many test houses the champion learned from (if any, gate 2 leans towards
the champion, and the run is tagged with a warning).

A failed gate is a result, not an error: this stage always exits 0 and lets the
DAG branch on what it reports.
"""

from __future__ import annotations

import os
import sys

import mlflow
import mlflow.sklearn
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from ml_common import lineage, schema
from ml_common.gates import evaluate_gates
from ml_common.metrics import EVALUATION_GROUP_MIN_ROWS, compute_metrics, group_metrics
from ml_common.stageio import emit_result
from ml_common.storage import Storage, processed_key

CHAMPION_ALIAS = "champion"


def predictions(model, features, task_type: str):
    """Runs a model over the test set.

    Args:
        model: a fitted Pipeline.
        features: the test set without its target.
        task_type: "regression" or "classification".

    Returns:
        `(y_pred, y_proba)`; `y_proba` is None for regression or for a
        classifier without probabilities. For a classifier trained with a
        decision threshold, `y_pred` is already at that threshold.

    Example:
        y_pred, y_proba = predictions(candidate, features, "classification")
    """
    y_pred = model.predict(features)
    y_proba = None
    if task_type == "classification" and hasattr(model, "predict_proba"):
        y_proba = model.predict_proba(features)[:, 1]
    return y_pred, y_proba


def champion_overlap(storage: Storage, model_name: str, task_type: str, test_ids) -> int | None:
    """Counts test houses the current champion learned from.

    Args:
        storage: where the champion's train set lives.
        model_name: the registered model.
        task_type: "regression" or "classification".
        test_ids: the property ids of the test set.

    Returns:
        The count; 0 when there is no champion. None when the champion's train
        set cannot be traced (registered outside the pipeline, or deleted).

    Example:
        champion_overlap(storage, "house_price_regressor", "regression", ids)
        # -> 0 when both models used the same dataset version
    """
    client = MlflowClient()
    version = lineage.champion_version(client, model_name)
    if version is None:
        return 0
    try:
        key = lineage.train_set_key(client, version.run_id, task_type)
        champion_ids = storage.read_parquet(key, columns=[schema.ID_COLUMN])[schema.ID_COLUMN]
    except (KeyError, FileNotFoundError) as error:
        print(f"cannot trace the champion's train set: {error}", file=sys.stderr)
        return None
    return int(test_ids.isin(set(champion_ids)).sum())


def score_model(model, features, y_true, task_type: str) -> dict:
    """Runs a model over the test split and measures it.

    Args:
        model: a fitted Pipeline, from a run or from the champion alias.
        features: the test split with the target column already removed, so it
            looks exactly like a serving record does.
        y_true: the observed target for those rows.
        task_type: "regression" or "classification".

    Returns:
        The metrics dict `compute_metrics` produces. Probabilities are passed
        along for a classifier that exposes them, which is what makes AUC —
        the metric both gates judge classification on — available at all.

    Example:
        features = test_df.drop(columns=[target])
        score_model(candidate, features, test_df[target], "regression")
        # -> {"rmse": 41203.7, "mae": 28104.2, "r2": 0.947}

        # Candidate and champion are scored with the SAME three arguments.
        # That is the whole reason the test split has a fixed seed.
    """
    y_pred, y_proba = predictions(model, features, task_type)
    return compute_metrics(task_type, y_true, y_pred, y_proba)


def load_champion(model_name: str):
    """Loads the model currently holding the champion alias.

    Args:
        model_name: the registered model name to look under.

    Returns:
        The fitted Pipeline, or None when nothing has been promoted yet. None
        is an ordinary state on a first run, not a failure: the second gate is
        simply skipped and the candidate is judged on the floor alone.

    Example:
        champion = load_champion("house_price_regressor")
        champion_metrics = None
        if champion is not None:
            champion_metrics = score_model(champion, features, y_true, task_type)
        evaluate_gates(task_type, candidate_metrics, champion_metrics)
        # champion_metrics=None is what tells the gates "nothing to beat yet"
    """
    try:
        return mlflow.sklearn.load_model(f"models:/{model_name}@{CHAMPION_ALIAS}")
    except MlflowException as err:
        print(f"no champion to compare against: {err}", file=sys.stderr)
        return None


def main() -> int:
    """Scores the candidate against both gates and reports the verdict.

    Args:
        None. Reads FINGERPRINT, TASK_TYPE, MODEL_NAME, RUN_ID and
        MLFLOW_TRACKING_URI, plus the MinIO variables `Storage.from_env` needs.

    Returns:
        Always 0, even when the gates block the model. A failed gate is a
        result, not an error: the stage result carries `passed`, `reason`,
        `metrics`, `champion_metrics` and `champion_overlap`, and the DAG
        branches on it. Per-group metrics go to MLflow as
        `group_metrics.json`. The
        numbers are also written back onto the candidate's own MLflow run, so a
        blocked model still leaves a record of why it was blocked.

    Raises:
        KeyError: when a required variable is unset, or when a metric a gate
            needs was not computed.
        FileNotFoundError: when the test split for that fingerprint and task is
            not in storage.
    """
    fingerprint = os.environ["FINGERPRINT"]
    task_type = os.environ["TASK_TYPE"]
    model_name = os.environ["MODEL_NAME"]
    run_id = os.environ["RUN_ID"]

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])

    storage = Storage.from_env()
    test_df = storage.read_parquet(processed_key(fingerprint, task_type, "test"))
    target = schema.target_column(task_type)
    features = test_df.drop(columns=[target])
    y_true = test_df[target]
    print(f"scoring on {len(test_df)} test rows", file=sys.stderr)

    candidate = mlflow.sklearn.load_model(f"runs:/{run_id}/model")
    y_pred, y_proba = predictions(candidate, features, task_type)
    candidate_metrics = compute_metrics(task_type, y_true, y_pred, y_proba)
    groups = group_metrics(
        task_type, test_df, y_true, y_pred, y_proba, min_rows=EVALUATION_GROUP_MIN_ROWS
    )
    print(f"candidate: {candidate_metrics}", file=sys.stderr)

    overlap = champion_overlap(storage, model_name, task_type, test_df[schema.ID_COLUMN])
    if overlap:
        print(f"WARNING: the champion learned {overlap} test houses", file=sys.stderr)

    champion = load_champion(model_name)
    champion_metrics = None
    if champion is not None:
        champion_metrics = score_model(champion, features, y_true, task_type)
        print(f"champion:  {champion_metrics}", file=sys.stderr)

    decision = evaluate_gates(task_type, candidate_metrics, champion_metrics)
    print(f"decision: {decision['reason']}", file=sys.stderr)

    # Write the numbers back onto the candidate's own run, so a blocked model
    # still leaves a record of why it was blocked.
    with mlflow.start_run(run_id=run_id):
        mlflow.log_metrics({f"test_{name}": value for name, value in candidate_metrics.items()})
        if champion_metrics is not None:
            mlflow.log_metrics(
                {f"champion_test_{name}": value for name, value in champion_metrics.items()}
            )
        mlflow.log_dict(groups, "group_metrics.json")
        tags = {
            "gate_passed": str(decision["passed"]),
            "gate_reason": decision["reason"],
            "champion_overlap": "unknown" if overlap is None else str(overlap),
        }
        if overlap:
            tags["warning"] = (
                f"the champion learned {overlap} houses of this test set; "
                "gate 2 leans towards the champion"
            )
        mlflow.set_tags(tags)

    emit_result(
        {
            "passed": decision["passed"],
            "reason": decision["reason"],
            "metrics": candidate_metrics,
            "champion_metrics": champion_metrics,
            "champion_overlap": overlap,
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
