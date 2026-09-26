"""Metrics shared by train and evaluate.

Regression metrics come out in the target's own units (dollars), because the
Pipeline already undid the log transform. A number the dashboard cannot read is
a number nobody acts on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)

from . import parsers, schema


def compute_metrics(task_type: str, y_true, y_pred, y_proba=None) -> dict[str, float]:
    """Computes the metrics that matter for a task type.

    Args:
        task_type: "regression" or "classification".
        y_true: observed values.
        y_pred: predicted values, already in the target's own units.
        y_proba: positive-class probabilities; classification only. AUC is left
            out when this is None, rather than guessed at.

    Returns:
        For regression: rmse, mae and r2. For classification: f1, precision,
        recall and accuracy of `y_pred` (so at whatever decision threshold
        produced it), plus auc when y_proba was given. Values are plain Python floats — numpy
        scalars break json.dumps and MLflow logging.

    Raises:
        ValueError: when task_type is not one of `schema.TASK_TYPES`.

    Example:
        compute_metrics("regression", y_true, y_pred)
        # -> {"rmse": 41203.7, "mae": 28104.2, "r2": 0.947}
        #    rmse and mae are in dollars, readable straight off a dashboard

        compute_metrics("classification", y_true, y_pred, y_proba)
        # -> {"f1": 0.51, "precision": 0.39, "recall": 0.72, "accuracy": 0.64,
        #     "auc": 0.71}

        compute_metrics("classification", y_true, y_pred)
        # -> no "auc" key at all. The gates read auc, so a candidate scored
        #    without probabilities fails with KeyError instead of sneaking past.
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}")

    if task_type == "regression":
        return {
            "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
            "mae": float(mean_absolute_error(y_true, y_pred)),
            "r2": float(r2_score(y_true, y_pred)),
        }

    result = {
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
    }
    if y_proba is not None:
        result["auc"] = float(roc_auc_score(y_true, y_proba))
    return result


GROUP_COLUMNS = ("city", "property_type")
EVALUATION_GROUP_MIN_ROWS = 200
MONITORING_GROUP_MIN_ROWS = 50


def group_metrics(
    task_type: str,
    raw_groups: pd.DataFrame,
    y_true,
    y_pred,
    y_proba=None,
    min_rows: int = EVALUATION_GROUP_MIN_ROWS,
) -> dict:
    """Computes the task's metrics per city and per property type (CN-45).

    Group names are normalized the way the cleaning code normalizes text, so
    "NEW YORK" and "new_york" are one group. Records whose group is missing are
    left out. These numbers are for reading only: no gate and no drift level is
    decided on them.

    Args:
        task_type: "regression" or "classification".
        raw_groups: the raw rows holding the `GROUP_COLUMNS` that exist.
        y_true: observed values, same rows in the same order.
        y_pred: predictions for those rows.
        y_proba: positive-class probabilities (classification), or None.
        min_rows: a group with fewer rows gets no metrics, only its count and
            `insufficient_data: True`.

    Returns:
        `{column: {group: {"n": rows, **metrics} | {"n": rows,
        "insufficient_data": True}}}`. A group holding one class only gets no
        `auc` (it is undefined there).

    Example:
        group_metrics("regression", test_df, y, pred, min_rows=200)
        # -> {"city": {"boston": {"n": 812, "rmse": 51000.0, ...},
        #              "tulsa": {"n": 41, "insufficient_data": True}},
        #     "property_type": {...}}
    """
    truth = np.asarray(y_true)
    predicted = np.asarray(y_pred)
    probability = None if y_proba is None else np.asarray(y_proba)
    result: dict[str, dict] = {}
    for column in GROUP_COLUMNS:
        if column not in raw_groups.columns:
            continue
        names = np.array(
            [parsers.normalize_text(v) for v in raw_groups[column]], dtype=object
        )
        by_group: dict[str, dict] = {}
        for name in sorted({n for n in names if n is not None}):
            mask = names == name
            count = int(mask.sum())
            if count < min_rows:
                by_group[name] = {"n": count, "insufficient_data": True}
                continue
            group_probability = None
            if probability is not None and len(set(truth[mask].tolist())) > 1:
                group_probability = probability[mask]
            by_group[name] = {
                "n": count,
                **compute_metrics(task_type, truth[mask], predicted[mask], group_probability),
            }
        result[column] = by_group
    return result
