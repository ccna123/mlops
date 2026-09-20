"""Metrics shared by train and evaluate.

Regression metrics come out in the target's own units (dollars), because the
Pipeline already undid the log transform. A number the dashboard cannot read is
a number nobody acts on.
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)

from . import schema


def compute_metrics(task_type: str, y_true, y_pred, y_proba=None) -> dict[str, float]:
    """Computes the metrics that matter for a task type.

    Args:
        task_type: "regression" or "classification".
        y_true: observed values.
        y_pred: predicted values, already in the target's own units.
        y_proba: positive-class probabilities; classification only. AUC is left
            out when this is None, rather than guessed at.

    Returns:
        For regression: rmse, mae and r2. For classification: f1 and accuracy,
        plus auc when y_proba was given. Values are plain Python floats — numpy
        scalars break json.dumps and MLflow logging.

    Raises:
        ValueError: when task_type is not one of `schema.TASK_TYPES`.

    Example:
        compute_metrics("regression", y_true, y_pred)
        # -> {"rmse": 41203.7, "mae": 28104.2, "r2": 0.947}
        #    rmse and mae are in dollars, readable straight off a dashboard

        compute_metrics("classification", y_true, y_pred, y_proba)
        # -> {"f1": 0.81, "accuracy": 0.86, "auc": 0.91}

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
        "accuracy": float(accuracy_score(y_true, y_pred)),
    }
    if y_proba is not None:
        result["auc"] = float(roc_auc_score(y_true, y_proba))
    return result
