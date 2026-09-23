"""Builds the estimator that goes at the end of the Pipeline.

Regression predicts in dollars directly. An earlier design wrapped it in a
TransformedTargetRegressor to train on log(price) and undo the log on the way
out, on the theory that it would tame the target's skew. Measured on this
dataset, it did the opposite: a linear model fits log space well, but expm1
amplifies the tail errors, so Ridge produced predictions up to $20.8M against a
true maximum of $2.39M and scored R2 = -0.4 on held-out data. Gradient boosting
scored 0.947 either way, so the wrapper bought nothing and broke one estimator.

Narrowed to three names per task type on 2026-09-23 (previously six, including
`logistic`, `hist_gradient_boosting`, its deliberately-weak variant and
`dummy`): the project settled on ridge/xgboost/random_forest for regression and
xgboost/svm/random_forest for classification, and stopped offering the rest.
That also retired the `hist_gradient_boosting_weak`/`dummy` "diagnostic"
pair - the two names that existed only to exercise the promotion gates
end to end (a model tuned to land between the gates, and one built to fail
them). Exercising the gates now needs a real run with real data instead.
"""

from __future__ import annotations

from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.model_selection import GridSearchCV
from sklearn.svm import SVC
from xgboost import XGBClassifier, XGBRegressor

from . import schema

ESTIMATOR_NAMES: dict[str, tuple[str, ...]] = {
    "regression": ("ridge", "xgboost", "random_forest"),
    "classification": ("xgboost", "svm", "random_forest"),
}

RANDOM_STATE = 42

# GridSearchCV's own k-fold split, run on the Pipeline's already-preprocessed
# feature matrix. Kept the same for every estimator so "tuned" means the same
# amount of search everywhere, and small (5) because it multiplies training
# time by len(param_grid) * CV_FOLDS fits - this runs on a 16GB dev box (see
# CLAUDE.md) already tight on RAM with Airflow, MLflow and Evidently running
# alongside it.
CV_FOLDS = 5

# Each grid is deliberately small (<=8 combinations) for the same RAM/time
# reason as CV_FOLDS. Values are plausible ranges around this project's
# defaults below, not the result of a search for the best possible model -
# the point of `tune` is to pick from a few reasonable candidates instead of
# guessing one, not to run an exhaustive search on a laptop.
PARAM_GRIDS: dict[str, dict[str, dict[str, list]]] = {
    "regression": {
        "ridge": {"alpha": [0.1, 1.0, 10.0]},
        "xgboost": {
            "n_estimators": [100, 300],
            "max_depth": [3, 6],
            "learning_rate": [0.05, 0.1],
        },
        "random_forest": {"n_estimators": [100, 300], "max_depth": [None, 10, 20]},
    },
    "classification": {
        "xgboost": {
            "n_estimators": [100, 300],
            "max_depth": [3, 6],
            "learning_rate": [0.05, 0.1],
        },
        # Prefixed "estimator__": `svm` is CalibratedClassifierCV wrapping
        # SVC (see _classification_base), so GridSearchCV must route these
        # through to the wrapped SVC rather than to the calibrator itself.
        "svm": {"estimator__C": [0.1, 1.0, 10.0], "estimator__kernel": ["rbf", "linear"]},
        "random_forest": {"n_estimators": [100, 300], "max_depth": [None, 10, 20]},
    },
}

# GridSearchCV needs a scorer to rank candidates by. Picked to match what
# this project already grades trained models on elsewhere - rmse
# (ml_common.metrics.compute_metrics, ml_common.drift.performance_severity)
# for regression, auc for classification - so "the tuned model" and "the
# model the gates and drift judge favorably" are the same yardstick, not two
# different opinions of what "better" means.
SCORING: dict[str, str] = {
    "regression": "neg_root_mean_squared_error",
    "classification": "roc_auc",
}


def _regression_base(name: str):
    """Builds one regression estimator by name, with this project's defaults.

    Args:
        name: a name already checked against `ESTIMATOR_NAMES["regression"]`.

    Returns:
        The estimator, unfitted.

    Example:
        _regression_base("xgboost")         # -> XGBRegressor(random_state=42)
        _regression_base("random_forest")   # -> RandomForestRegressor(random_state=42)
    """
    if name == "xgboost":
        return XGBRegressor(random_state=RANDOM_STATE)
    if name == "random_forest":
        return RandomForestRegressor(random_state=RANDOM_STATE)
    return Ridge(alpha=1.0)


def _classification_base(name: str):
    """Builds one classification estimator by name, with this project's defaults.

    Args:
        name: a name already checked against `ESTIMATOR_NAMES["classification"]`.

    Returns:
        The estimator, unfitted. `svm` comes back as an SVC wrapped in
        `CalibratedClassifierCV(ensemble=False)` rather than a bare SVC:
        plain SVC has no `predict_proba` unless built with
        `probability=True`, which scikit-learn 1.9 deprecated in favor of
        this exact wrapper (removed in 1.11). `compute_metrics` only
        computes auc when the estimator exposes `predict_proba` - the gates
        read auc, so an SVM with no calibrated probabilities would fail them
        with a KeyError instead of being judged on its actual performance.

    Example:
        _classification_base("xgboost")         # -> XGBClassifier
        _classification_base("svm")             # -> CalibratedClassifierCV(SVC(...))
        _classification_base("random_forest")   # -> RandomForestClassifier
    """
    if name == "xgboost":
        return XGBClassifier(random_state=RANDOM_STATE)
    if name == "random_forest":
        return RandomForestClassifier(random_state=RANDOM_STATE)
    return CalibratedClassifierCV(SVC(random_state=RANDOM_STATE), ensemble=False)


def build_estimator(task_type: str, name: str, tune: bool = False):
    """Builds an estimator ready to pass to `features.build_pipeline`.

    Args:
        task_type: "regression" or "classification".
        name: one of `ESTIMATOR_NAMES[task_type]`.
        tune: False (default) returns the estimator with this project's fixed
            hyperparameters - the fast, reproducible choice every run gets
            unless asked otherwise. True wraps it in
            `GridSearchCV(cv=CV_FOLDS, scoring=SCORING[task_type])` searching
            `PARAM_GRIDS[task_type][name]`: slower (`len(param_grid) *
            CV_FOLDS` extra fits, all inside the Pipeline's own `fit` call)
            but picks hyperparameters instead of guessing them.

    Returns:
        The unfitted estimator, or an unfitted `GridSearchCV` wrapping it when
        `tune` is True. Regression estimators predict in dollars, so no
        caller downstream - evaluate, register, or serving - has to undo a
        transform. Once fitted, a `GridSearchCV`'s `predict`/`predict_proba`
        delegate to its `best_estimator_`, so nothing downstream has to know
        tuning happened at all - including `features.build_pipeline`, which
        takes either shape as its final step exactly the same way.

    Raises:
        ValueError: when task_type is unknown, or when the name is not one
            this task offers. Falling back to a default would train
            something nobody asked for and log it under the requested name.

    Example:
        # The pair of calls the train stage always makes:
        estimator = build_estimator("regression", "xgboost")
        pipeline = build_pipeline("regression", estimator)

        build_estimator("regression", "svm")
        # -> ValueError: svm belongs to classification, not regression

        build_estimator("regression", "ridge", tune=True)
        # -> GridSearchCV(Ridge(alpha=1.0), param_grid={"alpha": [0.1, 1.0, 10.0]},
        #                  cv=5, scoring="neg_root_mean_squared_error")
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}")
    allowed = ESTIMATOR_NAMES[task_type]
    if name not in allowed:
        raise ValueError(f"estimator for {task_type} must be one of {allowed}, got: {name!r}")

    base = _regression_base(name) if task_type == "regression" else _classification_base(name)
    if not tune:
        return base
    return GridSearchCV(
        base,
        param_grid=PARAM_GRIDS[task_type][name],
        cv=CV_FOLDS,
        scoring=SCORING[task_type],
    )
