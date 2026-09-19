"""Builds the estimator that goes at the end of the Pipeline.

Regression trains on log(price) to tame the skew, but every consumer wants
dollars. TransformedTargetRegressor keeps that conversion INSIDE the model, so
evaluate and serving never have to know it happened — one less piece of logic
that could drift between training and serving.
"""

from __future__ import annotations

import numpy as np
from sklearn.compose import TransformedTargetRegressor
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge

from . import schema

ESTIMATOR_NAMES: dict[str, tuple[str, ...]] = {
    "regression": ("ridge", "hist_gradient_boosting", "dummy"),
    "classification": ("logistic", "hist_gradient_boosting", "dummy"),
}

RANDOM_STATE = 42


def _regression_base(name: str):
    if name == "ridge":
        return Ridge(alpha=1.0)
    if name == "hist_gradient_boosting":
        return HistGradientBoostingRegressor(random_state=RANDOM_STATE)
    return DummyRegressor(strategy="mean")


def _classification_base(name: str):
    if name == "logistic":
        return LogisticRegression(max_iter=1000)
    if name == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(random_state=RANDOM_STATE)
    return DummyClassifier(strategy="prior")


def build_estimator(task_type: str, name: str):
    """Builds an estimator ready to pass to `features.build_pipeline`.

    Args:
        task_type: "regression" or "classification".
        name: one of `ESTIMATOR_NAMES[task_type]`.

    Returns:
        For regression, a TransformedTargetRegressor predicting in the original
        units. For classification, the classifier itself.
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}")
    allowed = ESTIMATOR_NAMES[task_type]
    if name not in allowed:
        raise ValueError(f"estimator for {task_type} must be one of {allowed}, got: {name!r}")

    if task_type == "regression":
        return TransformedTargetRegressor(
            regressor=_regression_base(name),
            func=np.log1p,
            inverse_func=np.expm1,
        )
    return _classification_base(name)
