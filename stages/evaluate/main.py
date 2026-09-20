"""Evaluate stage: score the candidate and decide whether it may be promoted.

Two gates, both required. The first blocks junk on an absolute threshold. The
second blocks a merely-adequate model from displacing a better one, scored on
the SAME test split — which is why that split has a fixed seed.

A failed gate is a result, not an error: this stage always exits 0 and lets the
DAG branch on what it reports.
"""

from __future__ import annotations

import os
import sys

import mlflow
import mlflow.sklearn
from mlflow.exceptions import MlflowException

from ml_common import schema
from ml_common.gates import evaluate_gates
from ml_common.metrics import compute_metrics
from ml_common.stageio import emit_result
from ml_common.storage import Storage, processed_key

CHAMPION_ALIAS = "champion"


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
    y_pred = model.predict(features)
    y_proba = None
    if task_type == "classification" and hasattr(model, "predict_proba"):
        y_proba = model.predict_proba(features)[:, 1]
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
        `metrics` and `champion_metrics`, and the DAG branches on it. The
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
    candidate_metrics = score_model(candidate, features, y_true, task_type)
    print(f"candidate: {candidate_metrics}", file=sys.stderr)

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
        mlflow.set_tags(
            {
                "gate_passed": str(decision["passed"]),
                "gate_reason": decision["reason"],
            }
        )

    emit_result(
        {
            "passed": decision["passed"],
            "reason": decision["reason"],
            "metrics": candidate_metrics,
            "champion_metrics": champion_metrics,
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
