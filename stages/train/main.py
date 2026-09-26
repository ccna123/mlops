"""Train stage: fit the whole Pipeline and log it to MLflow.

What gets logged is the Pipeline, not the bare estimator. The Pipeline carries
its own cleaning steps, and for classification its decision threshold, so the
model in the Registry knows how to handle a raw record and serving never needs
a second copy of that logic.

The train set is put in time order before fitting (undated records first), so
hyperparameter tuning and the choice of the decision threshold always score on
records that come after the ones they learned from (NV-08).
"""

from __future__ import annotations

import json
import os
import sys

import mlflow
import mlflow.sklearn

from ml_common import schema, splits
from ml_common.estimators import (
    CV_FOLDS,
    DEFAULT_ESTIMATOR,
    TimeOrderedSplit,
    build_model,
    decision_threshold,
    fitted_search,
)
from ml_common.features import build_pipeline
from ml_common.metrics import compute_metrics
from ml_common.stageio import emit_result
from ml_common.storage import Storage, processed_key


def traceability_params(threshold: float | None) -> dict:
    """Collects what a model version must trace back to (NV-09, PCN-26).

    Args:
        threshold: the classifier's decision threshold, or None.

    Returns:
        The params to log: data ID (under `fingerprint` and `data_id`),
        dataset version, split points, sample size, random seed, source commit
        and image digest, plus `decision_threshold` when there is one.
        Missing environment values are logged as "unknown" rather than left
        out, so their absence is visible.

    Example:
        traceability_params(0.27)
        # -> {"fingerprint": "3f0a...", "data_id": "3f0a...",
        #     "dataset_version": "v2", "split_points": "{...}", "seed": 42,
        #     "sample_rows": "200000", "git_commit": "a1b2c3d",
        #     "image_digest": "sha256:...", "decision_threshold": 0.27}
    """
    data_id = os.environ["FINGERPRINT"]
    params = {
        "fingerprint": data_id,
        "data_id": data_id,
        "dataset_version": os.environ.get("DATASET_VERSION", "unknown"),
        "split_points": os.environ.get("SPLIT_POINTS", "unknown"),
        "seed": splits.RANDOM_SEED,
        "sample_rows": os.environ.get("SAMPLE_ROWS") or "all",
        "git_commit": os.environ.get("GIT_COMMIT") or "unknown",
        "image_digest": os.environ.get("IMAGE_DIGEST") or "unknown",
    }
    if threshold is not None:
        params["decision_threshold"] = threshold
    return params


def main() -> int:
    """Fits the whole Pipeline on the train set and logs it to MLflow.

    Args:
        None. Reads FINGERPRINT (the data ID), TASK_TYPE, MODEL_NAME,
        ESTIMATOR_NAME (default: `DEFAULT_ESTIMATOR` of the task),
        TUNE_HYPERPARAMETERS ("true" runs a time-ordered grid search),
        DATASET_VERSION, SPLIT_POINTS, SAMPLE_ROWS, GIT_COMMIT (baked into the
        image at build time), IMAGE_DIGEST (passed by the DAG) and
        MLFLOW_TRACKING_URI, plus the MinIO variables `Storage.from_env` needs.

    Returns:
        0. The stage result carries `run_id`, `experiment`, the training
        `metrics` and `decision_threshold` (None for regression). Nothing is
        registered or promoted here — `evaluate` decides that.

    Raises:
        KeyError: when a required variable is unset.
        FileNotFoundError: when the train set for that data ID and task is not
            in storage.
        ValueError: when ESTIMATOR_NAME is not one this task offers.
    """
    data_id = os.environ["FINGERPRINT"]
    task_type = os.environ["TASK_TYPE"]
    model_name = os.environ["MODEL_NAME"]
    estimator_name = os.environ.get("ESTIMATOR_NAME") or DEFAULT_ESTIMATOR[task_type]
    tune_hyperparameters = os.environ.get("TUNE_HYPERPARAMETERS", "false").strip().lower() == "true"

    storage = Storage.from_env()
    train_df = storage.read_parquet(processed_key(data_id, task_type, "train"))
    order, undated_rows = splits.training_order(train_df)
    train_df = train_df.loc[order].reset_index(drop=True)

    target = schema.target_column(task_type)
    # Drop the target so X looks exactly like a serving record does: no target.
    features = train_df.drop(columns=[target])
    y = train_df[target]

    print(
        f"training on {len(train_df)} rows ({undated_rows} undated), "
        f"estimator={estimator_name}, tune_hyperparameters={tune_hyperparameters}",
        file=sys.stderr,
    )
    model = build_model(
        task_type,
        estimator_name,
        tune=tune_hyperparameters,
        cv=TimeOrderedSplit(CV_FOLDS, undated_rows=undated_rows),
    )
    pipeline = build_pipeline(task_type, model)

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    mlflow.set_experiment(model_name)
    with mlflow.start_run() as run:
        pipeline.fit(features, y)
        fitted = pipeline.named_steps["model"]
        threshold = decision_threshold(fitted)
        mlflow.log_params(
            {
                "task_type": task_type,
                "estimator": estimator_name,
                "tune_hyperparameters": tune_hyperparameters,
                "train_rows": len(train_df),
                **traceability_params(threshold),
            }
        )
        search = fitted_search(fitted)
        if search is not None:
            # Logged under their own names, not folded into "estimator", so a
            # run trained with defaults and one trained tuned stay
            # distinguishable by more than the one boolean flag.
            mlflow.log_params({f"best_{k}": v for k, v in search.best_params_.items()})
        probability = (
            pipeline.predict_proba(features)[:, 1] if task_type == "classification" else None
        )
        train_metrics = compute_metrics(task_type, y, pipeline.predict(features), probability)
        mlflow.log_metrics({f"train_{name}": value for name, value in train_metrics.items()})
        # MLflow 2.x uses `artifact_path`; the `name` parameter only exists from MLflow 3.
        mlflow.sklearn.log_model(pipeline, artifact_path="model")
        run_id = run.info.run_id

    print(f"run_id={run_id} train_metrics={train_metrics}", file=sys.stderr)
    emit_result(
        {
            "run_id": run_id,
            "experiment": model_name,
            "metrics": train_metrics,
            "decision_threshold": threshold,
            "split_points": json.loads(os.environ.get("SPLIT_POINTS") or "null"),
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
