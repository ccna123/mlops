"""Reads Evidently's results into this system's own fixed shape (02 7.2).

Evidently does the COUNTING for the four monitoring sections: per-column drift
tests, performance metrics, missing values, values outside a known list. This
system does the DECIDING - which level each section gets - in `drift.py`.

This module is the only place that knows how Evidently lays out its results. It
reads the plain dict `report.run(...).dict()` returns and never imports
Evidently, so it runs (and is tested, against saved real outputs) on a machine
without Evidently. When an Evidently upgrade changes the layout, the tests on
the saved outputs fail first, and only this file has to change.

The layout read here is Evidently 0.7: `{"metrics": [...], "tests": [...]}`,
a FLAT list of metric results, each identified by `config["type"]`, never by
position, since preset composition can reorder them.
"""

from __future__ import annotations

DRIFTED_COLUMNS_COUNT_TYPE = "evidently:metric_v2:DriftedColumnsCount"
VALUE_DRIFT_TYPE = "evidently:metric_v2:ValueDrift"
MISSING_VALUE_COUNT_TYPE = "evidently:metric_v2:MissingValueCount"
OUT_LIST_VALUE_COUNT_TYPE = "evidently:metric_v2:OutListValueCount"

_PERFORMANCE_TYPES: dict[str, dict[str, str]] = {
    "regression": {
        "evidently:metric_v2:RMSE": "rmse",
        "evidently:metric_v2:MAE": "mae",
        "evidently:metric_v2:R2Score": "r2",
    },
    "classification": {
        "evidently:metric_v2:RocAuc": "auc",
        "evidently:metric_v2:F1Score": "f1",
        "evidently:metric_v2:Precision": "precision",
        "evidently:metric_v2:Recall": "recall",
        "evidently:metric_v2:Accuracy": "accuracy",
    },
}


def _entries(summary: dict, metric_type: str) -> list[dict]:
    """Picks the result entries of one metric type.

    Args:
        summary: what `report.run(...).dict()` returned.
        metric_type: the `config["type"]` wanted.

    Returns:
        The matching entries, in Evidently's order.

    Example:
        _entries(summary, VALUE_DRIFT_TYPE)  # -> [{"config": {...}, "value": 0.77}, ...]
    """
    return [
        entry
        for entry in summary.get("metrics", [])
        if (entry.get("config") or {}).get("type") == metric_type
    ]


def _types_seen(summary: dict) -> list:
    """Lists the metric types a result holds, for error messages.

    Args:
        summary: an Evidently result dict.

    Returns:
        The `config["type"]` of every entry.

    Example:
        _types_seen({"metrics": []})  # -> []
    """
    return [(entry.get("config") or {}).get("type") for entry in summary.get("metrics", [])]


def drifted_share(summary: dict) -> float:
    """Reads the share of compared columns Evidently flagged as drifted.

    Args:
        summary: the result of a `DataDriftPreset` report.

    Returns:
        The share, 0.0 to 1.0.

    Raises:
        KeyError: when the result has no `DriftedColumnsCount` entry. Better to
            fail loudly than to report 0.0 and put a green badge on an unread
            report.

    Example:
        drifted_share(results.dict())   # -> 0.42
    """
    found = _entries(summary, DRIFTED_COLUMNS_COUNT_TYPE)
    if not found:
        raise KeyError(
            f"no metric with config.type == {DRIFTED_COLUMNS_COUNT_TYPE!r} in the "
            f"Evidently result; metric types seen were {_types_seen(summary)}"
        )
    return float(found[0]["value"]["share"])


def feature_margins(summary: dict) -> list[float]:
    """Reads (drift score - detection threshold) for every per-column drift check.

    `drifted_share` only counts how many columns crossed their threshold;
    `drift.feature_margin_severity` needs HOW FAR each sits past (or under) its
    own threshold, to catch drift concentrated into a few columns that the
    share dilutes (market_shift: city at 0.78 against 0.1, but only 2 of 22
    columns over). Scores of different methods are not on one scale, which is
    why each column's OWN threshold is subtracted before anything is compared.

    Args:
        summary: the result of a `DataDriftPreset` report.

    Returns:
        One float per usable `ValueDrift` entry, in Evidently's order. An entry
        missing `threshold` or `value` is skipped: one odd column must not take
        the whole run down.

    Raises:
        KeyError: when there are no `ValueDrift` entries at all, or none is
            usable. Both mean extraction is broken, not that nothing drifted;
            returning [] would make the severity "ok" - a green badge produced
            by broken extraction.

    Example:
        feature_margins(results.dict())
        # -> [-0.0409, 0.0193, ..., 0.6754]
    """
    found = _entries(summary, VALUE_DRIFT_TYPE)
    if not found:
        raise KeyError(
            f"no metric with config.type == {VALUE_DRIFT_TYPE!r} in the Evidently "
            f"result; metric types seen were {_types_seen(summary)}"
        )
    margins = []
    for entry in found:
        threshold = (entry.get("config") or {}).get("threshold")
        value = entry.get("value")
        if threshold is None or value is None:
            continue
        margins.append(float(value) - float(threshold))
    if not margins:
        raise KeyError(
            f"found {len(found)} {VALUE_DRIFT_TYPE!r} entries but none had both "
            f"config.threshold and value; configs seen were "
            f"{[entry.get('config') for entry in found]}"
        )
    return margins


def performance_metrics(summary: dict, task_type: str) -> dict[str, float]:
    """Reads the performance metrics of a regression or classification report.

    Args:
        summary: the result of a report holding the metrics
            `monitor` asks for (RMSE, MAE, R2Score; or RocAuc, F1Score,
            Precision, Recall, Accuracy).
        task_type: "regression" or "classification".

    Returns:
        The metrics under this system's names ("rmse", "auc", ...), as floats.
        MAE, which Evidently reports as `{"mean", "std"}`, becomes its mean.
        A metric the report does not hold is left out, so a reader that needs
        it fails with KeyError instead of reading a made-up value.

    Raises:
        ValueError: when task_type is unknown.

    Example:
        performance_metrics(results.dict(), "regression")
        # -> {"rmse": 203809.1, "mae": 141002.7, "r2": 0.71}
    """
    if task_type not in _PERFORMANCE_TYPES:
        raise ValueError(f"unknown task_type: {task_type!r}")
    result: dict[str, float] = {}
    for metric_type, name in _PERFORMANCE_TYPES[task_type].items():
        found = _entries(summary, metric_type)
        if not found:
            continue
        value = found[0].get("value")
        if isinstance(value, dict):
            value = value.get("mean")
        if value is not None:
            result[name] = float(value)
    return result


def quality_numbers(summary: dict) -> dict[str, dict]:
    """Reads missing shares and unseen-category shares per column.

    Args:
        summary: the result of a report holding one `MissingValueCount` per
            column and one `OutListValueCount` per categorical column, where
            the list is every value the reference data holds.

    Returns:
        `{column: {"missing_share": float, "unseen_share": float | None}}`.
        `unseen_share` is the share of PRESENT values outside the known list,
        None for a column no `OutListValueCount` was asked for (numeric ones).

    Example:
        quality_numbers(results.dict())
        # -> {"city": {"missing_share": 0.25, "unseen_share": 0.67},
        #     "bedrooms": {"missing_share": 0.03, "unseen_share": None}}
    """
    result: dict[str, dict] = {}
    for entry in _entries(summary, MISSING_VALUE_COUNT_TYPE):
        column = entry["config"]["column"]
        result.setdefault(column, {"missing_share": 0.0, "unseen_share": None})
        result[column]["missing_share"] = float(entry["value"]["share"])
    for entry in _entries(summary, OUT_LIST_VALUE_COUNT_TYPE):
        column = entry["config"]["column"]
        result.setdefault(column, {"missing_share": 0.0, "unseen_share": None})
        result[column]["unseen_share"] = float(entry["value"]["share"])
    return result
