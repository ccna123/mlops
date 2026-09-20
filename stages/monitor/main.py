"""Monitor stage: measure drift for one model and publish the verdict.

This is the only place Evidently is imported, and it is imported inside a
function. ml-base has no Evidently, and a module-level import here would
make every stage that imports ml_common fail.

What it compares:

- Feature drift  - the served records against a sample of the train split
- Prediction drift - predictions served against the champion's predictions
  on that same sample
- Performance drift - accuracy on the rows that have ground truth against
  the metrics the train stage logged

The reference is the train split read back through the fingerprint logged in
MLflow, not the baseline profile. Evidently takes DataFrames; profile.json is
a summary and cannot be fed to it. See section 2.1 of the design doc.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime

import mlflow
import mlflow.sklearn
from mlflow import MlflowClient

from ml_common import drift, schema
from ml_common.cleaning import DateFeatures, OutlierClipper, RawRecordCleaner
from ml_common.features import _numeric_and_categorical_columns
from ml_common.metrics import compute_metrics
from ml_common.stageio import emit_result
from ml_common.storage import (
    Storage,
    drift_latest_key,
    drift_summary_key,
    processed_key,
    report_key,
)

CHAMPION_ALIAS = "champion"
DEFAULT_WINDOW_HOURS = 24
DEFAULT_REFERENCE_ROWS = 10_000
REFERENCE_SEED = 42

DRIFTED_COLUMNS_COUNT_TYPE = "evidently:metric_v2:DriftedColumnsCount"
VALUE_DRIFT_TYPE = "evidently:metric_v2:ValueDrift"


def load_champion_context(model_name: str) -> tuple[object, str, str, str]:
    """Loads the champion together with everything needed to judge it.

    Args:
        model_name: the registered model to look under.

    Returns:
        A tuple of (fitted Pipeline, version string, run_id, fingerprint).
        The fingerprint comes from the run's logged params, which is how the
        train split that produced this model is found again - the same path
        scripts/smoke_round_trip.py uses. The run_id is returned alongside so
        the training metrics can be read without asking MLflow for the same
        version a second time.

    Raises:
        Exception: when no champion exists, or when the run has no
            `fingerprint` param. Both mean there is nothing to compare
            against, and guessing a fingerprint would silently measure drift
            against the wrong data.

    Example:
        model, version, run_id, fingerprint = load_champion_context("house_price_regressor")
        # -> (Pipeline(...), "3", "a1b2c3d4", "3f0a9c1d5e2b7a48")
    """
    client = MlflowClient()
    version = client.get_model_version_by_alias(model_name, CHAMPION_ALIAS)
    fingerprint = client.get_run(version.run_id).data.params["fingerprint"]
    model = mlflow.sklearn.load_model(f"models:/{model_name}@{CHAMPION_ALIAS}")
    return model, str(version.version), version.run_id, fingerprint


def train_metrics_of(run_id: str, task_type: str) -> dict:
    """Reads the metrics the train stage logged for this model version.

    Args:
        run_id: the MLflow run that produced the champion.
        task_type: "regression" or "classification".

    Returns:
        The metrics under their plain names, with the `train_` prefix the
        train stage added stripped back off, e.g. {"rmse": 41203.7, ...}.

    Example:
        train_metrics_of("a1b2c3", "regression")
        # -> {"rmse": 41203.7, "mae": 28104.2, "r2": 0.947}
    """
    logged = MlflowClient().get_run(run_id).data.metrics
    return {
        name[len("train_") :]: value
        for name, value in logged.items()
        if name.startswith("train_")
    }


def _drifted_share(summary: dict) -> float:
    """Pulls the share of drifted columns out of Evidently's result dict.

    `results.dict()` returns `{"metrics": [...], "tests": [...]}` where
    `metrics` is a FLAT list of metric-result dicts (Evidently 0.7.23, not
    the nested 0.4-era shape). The entry wanted is identified by
    `config["type"] == "evidently:metric_v2:DriftedColumnsCount"`, never by
    list position, since preset composition can reorder entries. Its value
    is `{"count": ..., "share": ...}`.

    Args:
        summary: what `results.dict()` returned.

    Returns:
        The fraction of columns flagged as drifted, 0.0 to 1.0.

    Raises:
        KeyError: when no entry has that `config["type"]`. Better to fail
            loudly than to report 0.0 and put a green badge on an unread
            report.

    Example:
        _drifted_share(results.dict())   # -> 0.42
    """
    for metric in summary.get("metrics", []):
        config = metric.get("config") or {}
        if config.get("type") == DRIFTED_COLUMNS_COUNT_TYPE:
            return float(metric["value"]["share"])
    raise KeyError(
        f"no metric with config.type == {DRIFTED_COLUMNS_COUNT_TYPE!r} in the "
        f"Evidently result; metric types seen were "
        f"{[(m.get('config') or {}).get('type') for m in summary.get('metrics', [])]}"
    )


def _feature_margins(summary: dict) -> list[float]:
    """Pulls (observed value - detection threshold) for every per-column drift check.

    `DriftedColumnsCount` (`_drifted_share`) only counts how many columns
    crossed their threshold. `drift.feature_margin_severity` needs to know
    HOW FAR each one sits past (or under) its threshold, to catch drift
    concentrated into a few columns that the share path dilutes into
    invisibility - see the comment above `FEATURE_MAGNITUDE_WARNING` in
    `ml_common/drift.py` for the market_shift measurement that found this.

    Each `evidently:metric_v2:ValueDrift` entry carries `config["column"]`,
    `config["threshold"]` and a bare numeric `value` - the drift score
    itself, whose meaning depends on `config["method"]` (Jensen-Shannon
    distance for categoricals, Wasserstein distance (normed) for most
    numerics, text-content drift for the auto-detected `property_id`).
    Different methods are not on the same scale, which is exactly why this
    subtracts each column's OWN threshold before comparing across columns,
    rather than comparing raw values.

    Args:
        summary: what `results.dict()` returned - the same dict `_drifted_share`
            reads.

    Returns:
        One float per `ValueDrift` entry found, in whatever order Evidently
        listed them. Empty when there are none - `feature_margin_severity`
        treats that as "ok", not an error, since a feature-less comparison
        is not this function's problem to flag.

    Example:
        _feature_margins(results.dict())
        # -> [-0.0409, 0.0193, ..., 0.7250]  # zipcode's ~0.725 excess, last
    """
    margins = []
    for metric in summary.get("metrics", []):
        config = metric.get("config") or {}
        if config.get("type") != VALUE_DRIFT_TYPE:
            continue
        threshold = config.get("threshold")
        value = metric.get("value")
        if threshold is None or value is None:
            continue
        margins.append(float(value) - float(threshold))
    return margins


def clean_for_drift(frame):
    """Runs the model's own column-wise cleaning steps outside the Pipeline.

    Both sides of the feature-drift comparison arrive raw: `current` is
    decoded straight from the inference log's `raw_input` JSON, and
    `reference` is the train split, which `prepare_dataset_for_train` never
    column-cleans - only `RawRecordCleaner` inside the fitted Pipeline does
    that, at fit time. So every "numeric" column here - list_price,
    bedrooms, has_pool - is still an object dtype of strings, and Evidently's
    numeric stats crash on `np.isinf` over that.

    The fix reuses the exact three stateless steps the Pipeline runs before
    the encoder (`RawRecordCleaner`, `OutlierClipper`, `DateFeatures`), the
    same ones `build_pipeline` in features.py wires up. None of them learn
    from data - `fit` is a no-op on all three - so calling them unfitted here
    produces identical output to calling the fitted copies inside the
    champion model. This is not a copy of serving's cleaning logic; monitor
    is not serving, and both import the same `ml_common.cleaning` module.

    Args:
        frame: a raw DataFrame - either the decoded inference log or the
            train split with its target column dropped.

    Returns:
        A new DataFrame with money/numeric columns as real floats, booleans
        cast to 1.0/0.0/NaN the same way the numeric branch of the encoder
        treats them, categorical text normalized, and `listing_date`
        replaced by `listing_year` + `listing_month` - matching the column
        names `_numeric_and_categorical_columns` expects.

    Example:
        clean_for_drift(pd.DataFrame([{"list_price": "$450,000", "has_pool": "Yes"}]))
        # -> list_price 450000.0, has_pool 1.0
    """
    cleaned = RawRecordCleaner().transform(frame)
    cleaned = OutlierClipper().transform(cleaned)
    cleaned = DateFeatures().transform(cleaned)
    # RawRecordCleaner leaves booleans as Python True/False/None (object
    # dtype), which is what the model's ColumnTransformer wants - sklearn
    # coerces that itself. Evidently does not: np.isinf over an object-dtype
    # column raises. Cast explicitly to match "True/False -> 1/0" from
    # features.py's numeric/categorical split.
    for column_name, spec in schema.COLUMNS.items():
        if column_name in cleaned.columns and spec.kind == "boolean":
            cleaned[column_name] = cleaned[column_name].astype("float64")
    return cleaned


def run_drift_report(reference, current, numeric: list[str], categorical: list[str]):
    """Runs Evidently over two frames and returns the report object.

    Args:
        reference: the train-split sample.
        current: the records actually served.
        numeric: numeric column names to compare.
        categorical: categorical column names to compare.

    Returns:
        Evidently's result object, which can `save_html` and `dict`.

    Example:
        results = run_drift_report(ref, cur, numeric, categorical)
        results.save_html("/tmp/evidently.html")

        # NOTE the argument order below: current comes FIRST. Swapping them
        # still runs and still produces a report - it just measures whether
        # the training data drifted away from production, which is backwards
        # and which nothing will warn you about.
    """
    from evidently import DataDefinition, Dataset, Report
    from evidently.presets import DataDriftPreset

    definition = DataDefinition(numerical_columns=numeric, categorical_columns=categorical)
    report = Report([DataDriftPreset()])
    return report.run(
        Dataset.from_pandas(current, data_definition=definition),
        Dataset.from_pandas(reference, data_definition=definition),
    )


def main() -> int:
    """Measures all three drift types for one model and publishes the verdict.

    Args:
        None. Reads TASK_TYPE, MODEL_NAME, MLFLOW_TRACKING_URI, optional
        MONITOR_WINDOW_HOURS (default 24), MONITOR_REFERENCE_ROWS (default
        10000) and MONITOR_RUN_ID, plus the MinIO variables Storage.from_env
        needs.

    Returns:
        0 even when drift is high. A drifting model is a finding to report,
        not a task failure - the same reasoning that makes evaluate exit 0 on
        a blocked model. Returns 1 only when there was no traffic at all,
        since then nothing could be measured.

    Raises:
        Exception: when no champion exists, or the train split for its
            fingerprint is gone from storage. Both mean the comparison cannot
            be made, and a report built on a guess would be worse than none.

    Example:
        # TASK_TYPE=regression MODEL_NAME=house_price_regressor python main.py
        # -> XCOM_RESULT {"severity": "high", "parts": {...}, ...}
    """
    task_type = os.environ["TASK_TYPE"]
    model_name = os.environ["MODEL_NAME"]
    # float, not int: back-to-back scenario runs in a single test session land
    # within the same wall-clock hour, and load_predictions now filters by
    # real timestamp, so isolating one batch from the next needs sub-hour
    # precision (e.g. 0.1 = 6 minutes). Production's hourly Airflow schedule
    # keeps using whole hours by way of DEFAULT_WINDOW_HOURS.
    window_hours = float(os.environ.get("MONITOR_WINDOW_HOURS", DEFAULT_WINDOW_HOURS))
    reference_rows = int(os.environ.get("MONITOR_REFERENCE_ROWS", DEFAULT_REFERENCE_ROWS))
    run_id = os.environ.get("MONITOR_RUN_ID", datetime.now(UTC).strftime("%Y%m%dT%H%M%S"))

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    storage = Storage.from_env()
    now = datetime.now(UTC)

    predictions = drift.load_predictions(storage, model_name, now, window_hours)
    if len(predictions) == 0:
        print(f"no traffic for {model_name} in the last {window_hours}h", file=sys.stderr)
        emit_result(
            {
                "severity": drift.INSUFFICIENT,
                "parts": {},
                "n_predictions": 0,
                "n_ground_truth": 0,
                "report_key": None,
            }
        )
        return 1

    model, version, champion_run_id, fingerprint = load_champion_context(model_name)
    print(f"champion v{version}, fingerprint {fingerprint}", file=sys.stderr)

    train_df = storage.read_parquet(processed_key(fingerprint, task_type, "train"))
    target = schema.target_column(task_type)
    reference = train_df.drop(columns=[target])
    if len(reference) > reference_rows:
        reference = reference.sample(n=reference_rows, random_state=REFERENCE_SEED)

    current = drift.decode_raw_inputs(predictions)
    numeric, categorical = _numeric_and_categorical_columns(task_type)

    # Feature drift. Both sides are raw - clean them the same way the
    # champion's Pipeline does before Evidently ever sees them; see
    # clean_for_drift for why. Only compare columns both sides actually have.
    reference_clean = clean_for_drift(reference)
    current_clean = clean_for_drift(current)
    shared_numeric = [
        c for c in numeric if c in current_clean.columns and c in reference_clean.columns
    ]
    shared_categorical = [
        c for c in categorical if c in current_clean.columns and c in reference_clean.columns
    ]
    feature_report = run_drift_report(
        reference_clean, current_clean, shared_numeric, shared_categorical
    )
    feature_report_summary = feature_report.dict()
    feature_part = drift.feature_severity(
        _drifted_share(feature_report_summary), _feature_margins(feature_report_summary)
    )

    # Prediction drift. The champion has to be run over the reference here:
    # training never logged the distribution of its own output.
    reference_predictions = model.predict(reference)
    prediction_report = run_drift_report(
        reference.assign(prediction=reference_predictions)[["prediction"]],
        predictions[["prediction"]],
        ["prediction"] if task_type == "regression" else [],
        [] if task_type == "regression" else ["prediction"],
    )
    prediction_part = drift.prediction_severity(_drifted_share(prediction_report.dict()) > 0)

    # Performance drift, when there is anything to measure it on.
    outcomes = drift.load_outcomes(storage, model_name, now, window_hours)
    joined = drift.join_outcomes(predictions, outcomes)
    if len(joined) >= drift.MIN_GROUND_TRUTH:
        # Classification is scored on AUC, so it needs the probability serving
        # logged alongside the label. Regression has no probability at all.
        y_proba = None
        if task_type == "classification" and "probability" in joined.columns:
            y_proba = joined["probability"]
        current_metrics = compute_metrics(
            task_type, joined["actual"], joined["prediction"], y_proba
        )
        performance_part = drift.performance_severity(
            task_type,
            current_metrics,
            train_metrics_of(champion_run_id, task_type),
            len(joined),
        )
    else:
        current_metrics = {}
        performance_part = drift.INSUFFICIENT

    parts = {
        "feature": feature_part,
        "prediction": prediction_part,
        "performance": performance_part,
    }
    severity = drift.overall_severity(parts)
    print(f"severity={severity} parts={parts}", file=sys.stderr)

    html_key = report_key(model_name, run_id, "html")
    feature_report.save_html("/tmp/evidently.html")
    with open("/tmp/evidently.html", "rb") as handle:
        storage.write_bytes(handle.read(), html_key, "text/html")

    summary = {
        "model_name": model_name,
        "model_version": version,
        "task_type": task_type,
        "run_id": run_id,
        "computed_at": now.isoformat(),
        "window_hours": window_hours,
        "severity": severity,
        "parts": parts,
        "n_predictions": int(len(predictions)),
        "n_ground_truth": int(len(joined)),
        "current_metrics": current_metrics,
        "report_key": html_key,
    }
    storage.write_json(summary, drift_summary_key(model_name, run_id))
    storage.write_json(summary, drift_latest_key(model_name))
    storage.write_json(feature_report_summary, report_key(model_name, run_id, "json"))

    emit_result(
        {
            "severity": severity,
            "parts": parts,
            "n_predictions": int(len(predictions)),
            "n_ground_truth": int(len(joined)),
            "report_key": html_key,
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
