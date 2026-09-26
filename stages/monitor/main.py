"""Monitor stage: measure one model's four monitoring sections and publish the verdict.

This is the only place Evidently is imported, and it is imported inside
functions: ml-base has no Evidently.

The division of labour (02 7.2): Evidently COUNTS - per-column drift tests,
performance metrics, missing values, values outside a known list.
`ml_common.evidently_adapter` reads those results into a fixed shape, and
`ml_common.drift` DECIDES the level of each section. No threshold lives here.

The four sections:

- Data drift - the served records against a sample of the train set
- Prediction drift - predictions served against the champion's predictions on
  that same sample
- Performance drift - metrics on the rows that have ground truth against the
  champion's metrics on the test set
- Data quality of the input - missing rates and never-seen categories after
  the model's own cleaning, against the train set

The reference is the train set traced back through MLflow
(`ml_common.lineage`), not the baseline profile: Evidently takes DataFrames.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime

import mlflow
import mlflow.artifacts
import mlflow.sklearn
from mlflow import MlflowClient

from ml_common import drift, pushgateway, schema
from ml_common import evidently_adapter as adapter
from ml_common.cleaning import DateFeatures, OutlierClipper, RawRecordCleaner
from ml_common.estimators import decision_threshold
from ml_common.features import _numeric_and_categorical_columns
from ml_common.metrics import MONITORING_GROUP_MIN_ROWS, group_metrics
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


def test_metrics_of(run_id: str, task_type: str) -> dict:
    """Reads what this model version scored on the held-out test split.

    The `test_` metrics, not the `train_` ones, and the difference decides
    whether a drift alarm means anything. Until 2026-09-22 this read
    `train_`, which is measured on the very rows the model was fitted on, so
    an overfit model brought its own tiny denominator: the xgboost champion
    scored train rmse 14321 against test rmse 152620, and live traffic at rmse
    203809 came out as 14.2x - "high" - when against the test score it is
    1.33x, a warning. The more a model overfits, the louder and less
    informative its performance drift becomes. The test split is the only
    baseline measured on data the model had not seen, which is exactly what
    live traffic is.

    These are the same numbers the Models screen shows, so the dashboard now
    compares against a figure the user can see rather than one kept private
    to this stage.

    Args:
        run_id: the MLflow run that produced the champion.
        task_type: "regression" or "classification".

    Returns:
        The metrics under their plain names, with the `test_` prefix the
        evaluate stage added stripped back off, e.g. {"rmse": 152620.4, ...}.
        Empty when the run has none - a model registered outside the pipeline
        never went through evaluate. `champion_test_*`, logged on the same run
        for the model this one was compared against, is NOT picked up: it does
        not start with `test_`.

    Example:
        test_metrics_of("a1b2c3", "regression")
        # -> {"rmse": 152620.2, "mae": 86713.0, "r2": 0.8577}
    """
    logged = MlflowClient().get_run(run_id).data.metrics
    return {
        name[len("test_") :]: value
        for name, value in logged.items()
        if name.startswith("test_")
    }


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

    # Subset both frames to exactly the columns being compared before handing
    # them to Evidently. Dataset.from_pandas auto-detects and compares every
    # column present in the frame, not just the ones named in `definition` -
    # a frame carrying extra columns (e.g. the full cleaned dataset, which
    # still has `property_id`) would silently pull those into the drift
    # count too. Applied identically to both sides so neither is compared
    # against a different column set than the other.
    compared_columns = [*numeric, *categorical]
    report = Report([DataDriftPreset()])
    definition = DataDefinition(numerical_columns=numeric, categorical_columns=categorical)
    return report.run(
        Dataset.from_pandas(current[compared_columns], data_definition=definition),
        Dataset.from_pandas(reference[compared_columns], data_definition=definition),
    )


def performance_report(joined, task_type: str, threshold: float):
    """Has Evidently compute the performance metrics on the rows with ground truth.

    Args:
        joined: predictions joined to outcomes: `actual`, `prediction`, and
            for classification `probability`.
        task_type: "regression" or "classification".
        threshold: the champion's decision threshold (classification), so
            F1, precision and recall are measured where the model answers.

    Returns:
        Evidently's result object; `evidently_adapter.performance_metrics`
        reads it. Its numbers equal what the evaluate stage computes on the
        same rows (common/tests/test_evidently_adapter.py).

    Example:
        summary = performance_report(joined, "regression", 0.5).dict()
        adapter.performance_metrics(summary, "regression")  # -> {"rmse": ...}
    """
    import evidently.metrics as em
    from evidently import BinaryClassification, DataDefinition, Dataset, Regression, Report

    if task_type == "regression":
        frame = joined[["actual", "prediction"]].astype(float)
        definition = DataDefinition(
            numerical_columns=["actual", "prediction"],
            regression=[Regression(target="actual", prediction="prediction")],
        )
        metrics = [em.RMSE(), em.MAE(), em.R2Score()]
    else:
        frame = joined[["actual", "probability"]].copy()
        frame["actual"] = frame["actual"].astype(bool).astype(int)
        frame["probability"] = frame["probability"].astype(float)
        definition = DataDefinition(
            numerical_columns=["probability"],
            categorical_columns=["actual"],
            classification=[
                BinaryClassification(
                    target="actual", prediction_probas="probability", pos_label=1
                )
            ],
        )
        metrics = [
            em.RocAuc(),
            em.F1Score(probas_threshold=threshold),
            em.Precision(probas_threshold=threshold),
            em.Recall(probas_threshold=threshold),
            em.Accuracy(probas_threshold=threshold),
        ]
    return Report(metrics).run(Dataset.from_pandas(frame, data_definition=definition), None)


def known_categories(train_df, columns: list[str]) -> dict[str, list]:
    """Lists every category the train set holds, after the model's cleaning.

    The full train set, not the 10,000-row sample: a value the sample happens
    to miss is not "never seen". Only distinct raw values are cleaned, so this
    is cheap even on two million rows.

    Args:
        train_df: the champion's raw train set.
        columns: the categorical feature columns.

    Returns:
        `{column: sorted cleaned values}`.

    Example:
        known_categories(train_df, ["city"])  # -> {"city": ["boston", "miami", ...]}
    """
    result = {}
    for column in columns:
        if column not in train_df.columns:
            continue
        distinct = train_df[[column]].drop_duplicates()
        cleaned = clean_for_drift(distinct)[column].dropna().unique()
        result[column] = sorted(str(value) for value in cleaned)
    return result


def quality_report(frame, numeric: list[str], categorical: list[str], categories: dict):
    """Has Evidently count missing values and never-seen categories on one frame.

    Evidently's result holds only the "current" side, so the monitor runs this
    once on the traffic and once on the reference.

    Args:
        frame: cleaned records (`clean_for_drift`).
        numeric: numeric columns to count missing values in.
        categorical: categorical columns to count missing and unseen values in.
        categories: `known_categories` of the train set.

    Returns:
        Evidently's result object; `evidently_adapter.quality_numbers` reads it.

    Example:
        numbers = adapter.quality_numbers(quality_report(cur, num, cat, known).dict())
    """
    import evidently.metrics as em
    from evidently import DataDefinition, Dataset, Report

    columns = [*numeric, *categorical]
    metrics = [em.MissingValueCount(column=column) for column in columns]
    metrics += [
        em.OutListValueCount(column=column, values=categories.get(column, []))
        for column in categorical
    ]
    definition = DataDefinition(numerical_columns=numeric, categorical_columns=categorical)
    subset = frame[columns].copy()
    for column in categorical:
        subset[column] = subset[column].astype(object).where(subset[column].notna(), None)
    return Report(metrics).run(Dataset.from_pandas(subset, data_definition=definition), None)


def flush_result() -> dict | None:
    """Reads what the DAG's flush step reported, if it ran.

    Args:
        None. Reads FLUSH_RESULT, the JSON the flush task returned.

    Returns:
        `{"ok", "written", "error"}`, or None when the variable is absent or
        unreadable (a run started outside the DAG).

    Example:
        # FLUSH_RESULT='{"ok": false, "error": "minio down"}'
        flush_result()  # -> {"ok": False, "error": "minio down"}
    """
    try:
        return json.loads(os.environ.get("FLUSH_RESULT") or "null")
    except ValueError:
        return None


def reference_group_metrics(run_id: str) -> dict | None:
    """Reads the per-group test metrics evaluate logged for the champion.

    Args:
        run_id: the champion's training run.

    Returns:
        The dict `metrics.group_metrics` produced, or None for a champion
        evaluated before group metrics existed.

    Example:
        reference_group_metrics(run_id)["city"]["boston"]["rmse"]  # -> 51000.0
    """
    try:
        return mlflow.artifacts.load_dict(f"runs:/{run_id}/group_metrics.json")
    except Exception as error:  # noqa: BLE001 - absent on older runs
        print(f"no group metrics on the champion run: {error}", file=sys.stderr)
        return None


def previous_summary(storage: Storage, model_name: str) -> dict | None:
    """Reads the last monitoring summary of a model, to continue warning streaks.

    Args:
        storage: where summaries live.
        model_name: the model.

    Returns:
        The summary, or None when the model was never monitored.

    Example:
        previous_summary(storage, "house_price_regressor")["consecutive_warnings"]
    """
    try:
        return storage.read_json(drift_latest_key(model_name))
    except FileNotFoundError:
        return None


def main() -> int:
    """Measures all four sections for one model and publishes the verdict.

    Args:
        None. Reads TASK_TYPE, MODEL_NAME, MLFLOW_TRACKING_URI, optional
        MONITOR_WINDOW_HOURS (default 24), MONITOR_REFERENCE_ROWS (default
        10000), MONITOR_RUN_ID, FLUSH_RESULT and PUSHGATEWAY_URL (optional:
        where the levels are pushed for alerting), plus the MinIO variables
        `Storage.from_env` needs.

    Returns:
        0 in every case that completes, including when there was no traffic or
        no champion to measure: those are emitted as `insufficient_data`, not
        failures, because `traffic_agent` waits on this DAG's run state and a
        model not trained yet must not fail the other model's verdict.
        DockerOperator does not push XCom for a container exiting non-zero.

    Raises:
        Exception: when the champion's train set is gone from storage. A
            report built on a guess would be worse than none.

    Example:
        # TASK_TYPE=regression MODEL_NAME=house_price_regressor python main.py
        # -> XCOM_RESULT {"severity": "high", "parts": {...}, ...}
    """
    task_type = os.environ["TASK_TYPE"]
    model_name = os.environ["MODEL_NAME"]
    # float, not int: back-to-back scenario runs need sub-hour windows.
    window_hours = float(os.environ.get("MONITOR_WINDOW_HOURS", DEFAULT_WINDOW_HOURS))
    reference_rows = int(os.environ.get("MONITOR_REFERENCE_ROWS", DEFAULT_REFERENCE_ROWS))
    run_id = os.environ.get("MONITOR_RUN_ID", datetime.now(UTC).strftime("%Y%m%dT%H%M%S"))
    flushed = flush_result()
    if flushed is not None and not flushed.get("ok", False):
        print(f"WARNING: the log flush before this run failed: {flushed}", file=sys.stderr)

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    storage = Storage.from_env()
    now = datetime.now(UTC)

    predictions = drift.load_predictions(storage, model_name, now, window_hours)
    n_predictions = int(len(predictions))
    if n_predictions == 0:
        print(f"no traffic for {model_name} in the last {window_hours}h", file=sys.stderr)
        emit_result({"severity": drift.INSUFFICIENT, "parts": {}, "n_predictions": 0,
                     "n_ground_truth": 0, "report_key": None})
        return 0

    try:
        model, version, champion_run_id, data_id = load_champion_context(model_name)
    except mlflow.exceptions.MlflowException as error:
        print(f"no champion for {model_name} yet: {error}", file=sys.stderr)
        emit_result({"severity": drift.INSUFFICIENT, "parts": {},
                     "n_predictions": n_predictions, "n_ground_truth": 0,
                     "report_key": None})
        return 0
    print(f"champion v{version}, data ID {data_id}", file=sys.stderr)

    reference_metrics = test_metrics_of(champion_run_id, task_type)
    threshold = decision_threshold(model.named_steps.get("model")) if hasattr(
        model, "named_steps") else None
    outcomes = drift.load_outcomes(storage, model_name, now, window_hours)
    joined = drift.join_outcomes(predictions, outcomes)

    summary = {
        "model_name": model_name,
        "model_version": version,
        "task_type": task_type,
        "run_id": run_id,
        "computed_at": now.isoformat(),
        "window_hours": window_hours,
        "n_predictions": n_predictions,
        "n_ground_truth": int(len(joined)),
        # What the champion scored on the test set: the yardstick for
        # performance drift (see test_metrics_of). Absent before 2026-09-22.
        "reference_metrics": reference_metrics,
        "reference_source": "test_metrics",
        "decision_threshold": threshold,
        "flush": flushed,
    }

    if not drift.enough_predictions(n_predictions):
        print(f"only {n_predictions} predictions, below {drift.MIN_PREDICTIONS}", file=sys.stderr)
        parts = {name: drift.INSUFFICIENT for name in drift.PART_NAMES}
        summary.update({"parts": parts, "current_metrics": {},
                        "input_quality": {"level": drift.INSUFFICIENT, "columns": []},
                        "group_metrics": None, "report_key": None})
        return _publish(storage, summary, parts, feature_summary=None, html=None)

    train_df = storage.read_parquet(processed_key(data_id, task_type, "train"))
    target = schema.target_column(task_type)
    reference = train_df.drop(columns=[target])
    if len(reference) > reference_rows:
        reference = reference.sample(n=reference_rows, random_state=REFERENCE_SEED)

    current = drift.decode_raw_inputs(predictions)
    numeric, categorical = _numeric_and_categorical_columns(task_type)
    reference_clean = clean_for_drift(reference)
    current_clean = clean_for_drift(current)
    shared_numeric = [
        c for c in numeric if c in current_clean.columns and c in reference_clean.columns
    ]
    shared_categorical = [
        c for c in categorical if c in current_clean.columns and c in reference_clean.columns
    ]

    # Data drift.
    feature_report = run_drift_report(
        reference_clean, current_clean, shared_numeric, shared_categorical
    )
    feature_summary = feature_report.dict()
    feature_part = drift.feature_severity(
        adapter.drifted_share(feature_summary), adapter.feature_margins(feature_summary)
    )

    # Prediction drift: training never logged the distribution of its own
    # output, so the champion is run over the reference sample here.
    reference_predictions = model.predict(reference)
    prediction_report = run_drift_report(
        reference.assign(prediction=reference_predictions)[["prediction"]],
        predictions[["prediction"]],
        ["prediction"] if task_type == "regression" else [],
        [] if task_type == "regression" else ["prediction"],
    )
    prediction_part = drift.prediction_severity(
        adapter.drifted_share(prediction_report.dict()) > 0
    )

    # Performance drift.
    current_metrics: dict = {}
    groups = None
    if not reference_metrics:
        print(f"no test_ metrics on run {champion_run_id}, performance cannot be graded",
              file=sys.stderr)
        performance_part = drift.INSUFFICIENT
    elif len(joined) >= drift.MIN_GROUND_TRUTH:
        current_metrics = adapter.performance_metrics(
            performance_report(joined, task_type, threshold or 0.5).dict(), task_type
        )
        performance_part = drift.performance_severity(
            task_type, current_metrics, reference_metrics, len(joined)
        )
        probability = joined["probability"] if task_type == "classification" else None
        groups = group_metrics(
            task_type, drift.decode_raw_inputs(joined), joined["actual"],
            joined["prediction"], probability, min_rows=MONITORING_GROUP_MIN_ROWS,
        )
    else:
        performance_part = drift.INSUFFICIENT

    # Data quality of the input, on data cleaned the way the model cleans it.
    categories = known_categories(train_df, shared_categorical)
    quality_current = adapter.quality_numbers(
        quality_report(current_clean, shared_numeric, shared_categorical, categories).dict()
    )
    quality_reference = adapter.quality_numbers(
        quality_report(reference_clean, shared_numeric, shared_categorical, categories).dict()
    )
    quality = drift.input_quality(quality_reference, quality_current, n_predictions)

    parts = {
        "feature": feature_part,
        "prediction": prediction_part,
        "performance": performance_part,
        "input_quality": quality["level"],
    }
    summary.update({
        "parts": parts,
        "current_metrics": current_metrics,
        "input_quality": quality,
        "group_metrics": {"current": groups,
                          "reference": reference_group_metrics(champion_run_id)},
        "report_key": report_key(model_name, run_id, "html"),
    })
    feature_report.save_html("/tmp/evidently.html")
    with open("/tmp/evidently.html", "rb") as handle:
        html = handle.read()
    return _publish(storage, summary, parts, feature_summary=feature_summary, html=html)


def _publish(storage: Storage, summary: dict, parts: dict, feature_summary, html) -> int:
    """Finishes the summary, writes it and the report, and emits the result.

    Args:
        storage: where reports live.
        summary: everything measured so far.
        parts: the level of each section.
        feature_summary: Evidently's data drift result dict, or None.
        html: the Evidently report page, or None.

    Returns:
        0.

    Example:
        return _publish(storage, summary, parts, feature_summary=None, html=None)
    """
    model_name, run_id = summary["model_name"], summary["run_id"]
    summary["severity"] = drift.overall_severity(parts)
    summary["consecutive_warnings"] = drift.consecutive_warnings(
        previous_summary(storage, model_name), parts, summary["model_version"]
    )
    print(f"severity={summary['severity']} parts={parts}", file=sys.stderr)
    if html is not None:
        storage.write_bytes(html, report_key(model_name, run_id, "html"), "text/html")
    if feature_summary is not None:
        storage.write_json(feature_summary, report_key(model_name, run_id, "json"))
    storage.write_json(summary, drift_summary_key(model_name, run_id))
    storage.write_json(summary, drift_latest_key(model_name))
    # After the summary is safely written: the alert rules read these (02 7.5).
    pushgateway.push(
        pushgateway.monitoring_samples(summary), "monitoring", {"model_name": model_name}
    )
    emit_result({
        "severity": summary["severity"],
        "parts": parts,
        "n_predictions": summary["n_predictions"],
        "n_ground_truth": summary["n_ground_truth"],
        "report_key": summary.get("report_key"),
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
