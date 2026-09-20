"""Builds the estimator that goes at the end of the Pipeline.

Regression predicts in dollars directly. An earlier design wrapped it in a
TransformedTargetRegressor to train on log(price) and undo the log on the way
out, on the theory that it would tame the target's skew. Measured on this
dataset, it did the opposite: a linear model fits log space well, but expm1
amplifies the tail errors, so Ridge produced predictions up to $20.8M against a
true maximum of $2.39M and scored R2 = -0.4 on held-out data. Gradient boosting
scored 0.947 either way, so the wrapper bought nothing and broke one estimator.
"""

from __future__ import annotations

from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge

from . import schema

ESTIMATOR_NAMES: dict[str, tuple[str, ...]] = {
    "regression": ("ridge", "hist_gradient_boosting", "hist_gradient_boosting_weak", "dummy"),
    "classification": (
        "logistic",
        "hist_gradient_boosting",
        "hist_gradient_boosting_weak",
        "dummy",
    ),
}

RANDOM_STATE = 42

# The deliberately under-trained variant exists so the promotion gates can be
# exercised end to end on real data. Measured on 48k rows it scores R2 = 0.769:
# above the 0.75 floor, below the full model's 0.947. That makes it a champion
# the full model can then beat, and a challenger the full model can then reject.
WEAK_MAX_ITER = 10


def _regression_base(name: str):
    """Builds one regression estimator by name.

    Args:
        name: a name already checked against `ESTIMATOR_NAMES["regression"]`.

    Returns:
        The estimator. An unrecognized name falls through to DummyRegressor, so
        the caller is the one that must validate — `build_estimator` does.

    Example:
        _regression_base("hist_gradient_boosting")       # -> scores R2 0.947
        _regression_base("hist_gradient_boosting_weak")  # -> max_iter=10, R2 0.769
        _regression_base("anything else")                # -> DummyRegressor
    """
    if name == "ridge":
        return Ridge(alpha=1.0)
    if name == "hist_gradient_boosting":
        return HistGradientBoostingRegressor(random_state=RANDOM_STATE)
    if name == "hist_gradient_boosting_weak":
        return HistGradientBoostingRegressor(random_state=RANDOM_STATE, max_iter=WEAK_MAX_ITER)
    return DummyRegressor(strategy="mean")


def _classification_base(name: str):
    """Builds one classification estimator by name.

    Args:
        name: a name already checked against `ESTIMATOR_NAMES["classification"]`.

    Returns:
        The estimator. An unrecognized name falls through to DummyClassifier, so
        the caller is the one that must validate — `build_estimator` does.

    Example:
        _classification_base("logistic")           # -> LogisticRegression(max_iter=1000)
        _classification_base("anything else")      # -> DummyClassifier(strategy="prior")
    """
    if name == "logistic":
        return LogisticRegression(max_iter=1000)
    if name == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(random_state=RANDOM_STATE)
    if name == "hist_gradient_boosting_weak":
        return HistGradientBoostingClassifier(random_state=RANDOM_STATE, max_iter=WEAK_MAX_ITER)
    return DummyClassifier(strategy="prior")


def build_estimator(task_type: str, name: str):
    """Builds an estimator ready to pass to `features.build_pipeline`.

    Args:
        task_type: "regression" or "classification".
        name: one of `ESTIMATOR_NAMES[task_type]`.

    Returns:
        The unfitted estimator itself. Regression estimators predict in dollars,
        so no caller downstream — evaluate, register, or serving — has to undo a
        transform.

    Raises:
        ValueError: when task_type is unknown, or when the name is not one this
            task offers. Falling back to a default would train something nobody
            asked for and log it under the requested name.

    Example:
        # The pair of calls the train stage always makes:
        estimator = build_estimator("regression", "hist_gradient_boosting")
        pipeline = build_pipeline("regression", estimator)

        build_estimator("regression", "logistic")
        # -> ValueError: logistic belongs to classification, not regression
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}")
    allowed = ESTIMATOR_NAMES[task_type]
    if name not in allowed:
        raise ValueError(f"estimator for {task_type} must be one of {allowed}, got: {name!r}")

    if task_type == "regression":
        return _regression_base(name)
    return _classification_base(name)
