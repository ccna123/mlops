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

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin, clone
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.svm import SVC
from xgboost import XGBClassifier, XGBRegressor

from . import schema

ESTIMATOR_NAMES: dict[str, tuple[str, ...]] = {
    "regression": ("ridge", "xgboost", "random_forest"),
    "classification": ("xgboost", "svm", "random_forest"),
}

RANDOM_STATE = 42

# Used when the operator leaves the algorithm blank. Ridge was the regression
# default until 2026-09-25, but it reached R2 0.68 on 48,000 rows, below the
# 0.75 of gate 1, so a run with the default choice always failed. Ridge stays
# on offer as the baseline to beat (02 3.5). The DAG keeps its own copy of this
# map (it cannot import ml_common); a test keeps the two equal.
DEFAULT_ESTIMATOR: dict[str, str] = {"regression": "xgboost", "classification": "xgboost"}

# The decision threshold of the classifier is chosen for this recall (CN-43):
# catch at least 70% of the houses that need renovation. At the default 0.5 a
# model with AUC 0.71 flagged almost nothing (F1 0.16).
TARGET_RECALL = 0.70
# Share of the train set, the latest by time, held out to choose the threshold.
THRESHOLD_HOLDOUT_SHARE = 0.20

# Number of time-ordered folds GridSearchCV scores each candidate on. Kept the
# same for every estimator so "tuned" means the same amount of search
# everywhere, and small (5) because it multiplies training time by
# len(param_grid) * CV_FOLDS fits - this runs on a 16GB dev box (see
# CLAUDE.md) already tight on RAM with Airflow, MLflow and Evidently running
# alongside it.
CV_FOLDS = 5


class TimeOrderedSplit:
    """Cross-validation folds in which the scored rows always come after the learned ones.

    The rows must already be in time order (see `splits.training_order`), with
    the undated rows first. The first `undated_rows` rows are always on the
    learning side: an undated record cannot be placed after anything. The dated
    rows are cut like `TimeSeriesSplit`: each fold learns from everything before
    a point and is scored on the block right after it (NV-08). A random k-fold
    would let a candidate learn the price level of the very months it is scored
    on, and favour exactly the settings that fail on a new month.

    Example:
        cv = TimeOrderedSplit(n_splits=5, undated_rows=80)
        for learn, score in cv.split(X):
            assert learn.max() < score.min() or learn[:80].tolist() == list(range(80))
        GridSearchCV(estimator, grid, cv=cv)
    """

    def __init__(self, n_splits: int = CV_FOLDS, undated_rows: int = 0):
        """Stores the fold count and how many leading rows are undated.

        Args:
            n_splits: how many folds.
            undated_rows: how many rows at the start have no date.
        """
        self.n_splits = n_splits
        self.undated_rows = undated_rows

    def get_n_splits(self, X=None, y=None, groups=None) -> int:  # noqa: N803
        """Tells scikit-learn how many folds there are.

        Args:
            X: ignored.
            y: ignored.
            groups: ignored.

        Returns:
            `n_splits`.
        """
        return self.n_splits

    def split(self, X, y=None, groups=None):  # noqa: N803
        """Yields (learn positions, score positions) for each fold.

        Args:
            X: the rows, in time order with the undated rows first.
            y: ignored.
            groups: ignored.

        Returns:
            A generator of pairs of integer position arrays.
        """
        count = len(X)
        undated = min(self.undated_rows, count)
        leading = np.arange(undated)
        dated = np.arange(undated, count)
        for learn, score in TimeSeriesSplit(n_splits=self.n_splits).split(dated):
            yield np.concatenate([leading, dated[learn]]), dated[score]


def choose_threshold(y_true, probability, target_recall: float = TARGET_RECALL) -> float:
    """Picks the highest decision threshold that still reaches a recall target.

    Args:
        y_true: the observed classes, True/1 for "needs renovation".
        probability: the positive-class probability for the same rows.
        target_recall: the share of positives that must be caught.

    Returns:
        The threshold, a probability actually observed on a positive row, so
        "probability >= threshold" catches at least `target_recall` of the
        positives. 0.5 when there is no positive row to aim at.

    Example:
        choose_threshold([1, 1, 1, 0], [0.9, 0.6, 0.2, 0.1], 0.66)
        # -> 0.6: at 0.6 two of three positives are caught (recall 0.67)
    """
    truth = np.asarray(y_true).astype(bool)
    scores = np.asarray(probability, dtype=float)[truth]
    if scores.size == 0:
        return 0.5
    ranked = np.sort(scores)[::-1]
    needed = int(np.ceil(target_recall * scores.size))
    return float(ranked[max(needed, 1) - 1])


class ThresholdedClassifier(ClassifierMixin, BaseEstimator):
    """A classifier that answers yes/no at its own decision threshold (CN-43).

    Fitting does three things, in the order 02 3.5 lays down, on rows already
    in time order:

    1. fit the wrapped estimator (a plain classifier, or a GridSearchCV that
       picks the hyperparameters) on every row - this is the final model;
    2. fit a copy with the chosen hyperparameters on the earliest
       (1 - holdout_share) of the rows, and score the latest holdout_share;
    3. keep the highest threshold that still reaches `target_recall` there.

    The threshold travels inside the model, like the cleaning steps: serving
    calls `predict` and gets the thresholded answer without knowing the number.
    The test set is never used to choose it.

    Example:
        model = ThresholdedClassifier(XGBClassifier())
        model.fit(X_sorted_by_time, y)
        model.threshold_          # -> 0.27
        model.predict(X_new)      # -> probability >= 0.27
    """

    def __init__(
        self,
        estimator=None,
        target_recall: float = TARGET_RECALL,
        holdout_share: float = THRESHOLD_HOLDOUT_SHARE,
    ):
        """Stores the settings; nothing is fitted here.

        Args:
            estimator: the classifier to wrap, possibly a GridSearchCV.
            target_recall: recall the threshold must reach on the holdout.
            holdout_share: latest share of the rows used to choose it.
        """
        self.estimator = estimator
        self.target_recall = target_recall
        self.holdout_share = holdout_share

    def fit(self, X, y):  # noqa: N803
        """Fits the final model and chooses its threshold.

        Args:
            X: feature rows in time order (undated first).
            y: the classes.

        Returns:
            self.
        """
        labels = np.asarray(y)
        self.estimator_ = clone(self.estimator).fit(X, labels)
        self.classes_ = self.estimator_.classes_
        chosen = getattr(self.estimator_, "best_estimator_", self.estimator_)
        cut = int(len(labels) * (1 - self.holdout_share))
        learn_labels, holdout_labels = labels[:cut], labels[cut:]
        if len(set(learn_labels.tolist())) < 2 or not np.asarray(holdout_labels).astype(bool).any():
            # Not enough of both classes to learn and aim at: keep the usual cut.
            self.threshold_ = 0.5
            return self
        temporary = clone(chosen).fit(_rows(X, slice(0, cut)), learn_labels)
        positive = list(temporary.classes_).index(self.classes_[-1])
        holdout_probability = temporary.predict_proba(_rows(X, slice(cut, None)))[:, positive]
        self.threshold_ = choose_threshold(holdout_labels, holdout_probability, self.target_recall)
        return self

    def predict_proba(self, X):  # noqa: N803
        """Returns the wrapped model's class probabilities.

        Args:
            X: feature rows.

        Returns:
            An array of shape (rows, 2).
        """
        return self.estimator_.predict_proba(X)

    def predict(self, X):  # noqa: N803
        """Answers yes/no at the stored threshold.

        Args:
            X: feature rows.

        Returns:
            The positive class where its probability reaches `threshold_`,
            the other class elsewhere.
        """
        positive = self.predict_proba(X)[:, -1] >= self.threshold_
        return np.where(positive, self.classes_[-1], self.classes_[0])


def _rows(X, which):  # noqa: N803
    """Slices rows of an array or a DataFrame by position.

    Args:
        X: a numpy array or a DataFrame.
        which: a slice.

    Returns:
        The selected rows, same type as X.
    """
    return X.iloc[which] if hasattr(X, "iloc") else X[which]

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


def build_estimator(task_type: str, name: str, tune: bool = False, cv=None):
    """Builds an estimator ready to pass to `features.build_pipeline`.

    Args:
        task_type: "regression" or "classification".
        name: one of `ESTIMATOR_NAMES[task_type]`.
        tune: False (default) returns the estimator with this project's fixed
            hyperparameters - the fast, reproducible choice every run gets
            unless asked otherwise. True wraps it in
            `GridSearchCV(cv=cv, scoring=SCORING[task_type])` searching
            `PARAM_GRIDS[task_type][name]`: slower (`len(param_grid) *
            CV_FOLDS` extra fits, all inside the Pipeline's own `fit` call)
            but picks hyperparameters instead of guessing them.
        cv: the fold generator for tuning; None means
            `TimeOrderedSplit(CV_FOLDS)` with no undated rows. The train stage
            passes one that knows how many undated rows lead the data.

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
        #                  cv=TimeOrderedSplit(5), scoring="neg_root_mean_squared_error")
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
        cv=cv if cv is not None else TimeOrderedSplit(CV_FOLDS),
        scoring=SCORING[task_type],
    )


def build_model(task_type: str, name: str, tune: bool = False, cv=None):
    """Builds the final step of the Pipeline the train stage fits.

    Args:
        task_type: "regression" or "classification".
        name: one of `ESTIMATOR_NAMES[task_type]`.
        tune: whether to search hyperparameters (see `build_estimator`).
        cv: the fold generator for tuning (see `build_estimator`).

    Returns:
        `build_estimator(...)` for regression. For classification, that same
        estimator wrapped in `ThresholdedClassifier`, so the model answers
        yes/no at a threshold chosen for `TARGET_RECALL`.

    Raises:
        ValueError: as `build_estimator`.

    Example:
        build_model("classification", "xgboost")
        # -> ThresholdedClassifier(estimator=XGBClassifier(...))
    """
    estimator = build_estimator(task_type, name, tune=tune, cv=cv)
    if task_type == "classification":
        return ThresholdedClassifier(estimator)
    return estimator


def fitted_search(model):
    """Finds the fitted GridSearchCV inside a model, if tuning happened.

    Args:
        model: the fitted final step of the Pipeline.

    Returns:
        The GridSearchCV, or None when the model was not tuned.

    Example:
        search = fitted_search(pipeline.named_steps["model"])
        search.best_params_ if search else {}
    """
    inner = getattr(model, "estimator_", model)
    return inner if isinstance(inner, GridSearchCV) else None


def decision_threshold(model) -> float | None:
    """Reads the decision threshold a fitted model answers at.

    Args:
        model: the fitted final step of the Pipeline.

    Returns:
        The threshold for a `ThresholdedClassifier`, None otherwise (a
        regressor, or a classifier trained before thresholds existed).

    Example:
        decision_threshold(pipeline.named_steps["model"])  # -> 0.27
    """
    return getattr(model, "threshold_", None)
