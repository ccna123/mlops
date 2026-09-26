"""Tests for estimator construction."""

import numpy as np
import pandas as pd
import pytest
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import GridSearchCV
from sklearn.svm import SVC

from ml_common.estimators import CV_FOLDS, ESTIMATOR_NAMES, PARAM_GRIDS, SCORING, build_estimator


def test_regression_estimator_is_not_target_transformed():
    """Regression predicts dollars directly; no target transform is applied.

    An earlier design wrapped this in a TransformedTargetRegressor to train on
    log(price). Measured on the real dataset, expm1 amplified the tail errors:
    Ridge predicted up to $20.8M against a true maximum of $2.39M and scored
    R2 = -0.4 on held-out data, while gradient boosting scored 0.947 with or
    without it. The wrapper broke one estimator and helped none.
    """
    estimator = build_estimator("regression", "ridge")
    assert not isinstance(estimator, TransformedTargetRegressor)


def test_classification_estimator_is_not_target_transformed():
    estimator = build_estimator("classification", "xgboost")
    assert not isinstance(estimator, TransformedTargetRegressor)


def test_regression_predicts_in_original_units():
    """Predictions come back in dollars, the same unit the target was fitted on."""
    X = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0]})
    y = pd.Series([100000.0, 200000.0, 300000.0, 400000.0])

    estimator = build_estimator("regression", "ridge")
    estimator.fit(X, y)
    predictions = estimator.predict(X)

    assert predictions.min() > 1000, "predictions are not on the dollar scale"


def test_regression_does_not_explode_on_skewed_targets():
    """A skewed target must not produce predictions far outside its own range.

    This is the regression that the log-target wrapper caused: exponentiating
    log-space errors pushed predictions an order of magnitude past the real
    maximum. Guard it so the wrapper cannot quietly come back.
    """
    X = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]})
    y = pd.Series([50_000.0, 80_000.0, 120_000.0, 300_000.0, 900_000.0, 2_400_000.0])

    estimator = build_estimator("regression", "ridge")
    estimator.fit(X, y)

    assert estimator.predict(X).max() < y.max() * 3


def test_every_declared_regression_name_builds():
    for name in ESTIMATOR_NAMES["regression"]:
        assert build_estimator("regression", name) is not None


def test_every_declared_classification_name_builds():
    for name in ESTIMATOR_NAMES["classification"]:
        assert build_estimator("classification", name) is not None


def test_invalid_task_type_raises():
    with pytest.raises(ValueError, match="task_type"):
        build_estimator("clustering", "ridge")


def test_unknown_estimator_name_raises():
    with pytest.raises(ValueError, match="estimator"):
        build_estimator("regression", "catboost")


def test_regression_offers_xgboost():
    assert type(build_estimator("regression", "xgboost")).__name__ == "XGBRegressor"


def test_regression_offers_random_forest():
    # Added 2026-09-23: random_forest used to be classification-only.
    assert isinstance(build_estimator("regression", "random_forest"), RandomForestRegressor)


def test_classification_offers_xgboost():
    assert type(build_estimator("classification", "xgboost")).__name__ == "XGBClassifier"


def test_classification_offers_random_forest():
    assert isinstance(build_estimator("classification", "random_forest"), RandomForestClassifier)


def test_classification_offers_svm_with_calibrated_probabilities():
    # gates.evaluate_gates and drift.performance_severity both read AUC, and
    # compute_metrics only computes it when the estimator exposes
    # predict_proba (see its own docstring: "the gates read auc, so a
    # candidate scored without probabilities fails with KeyError instead of
    # sneaking past"). A bare SVC has no predict_proba at all unless built
    # with probability=True, which scikit-learn deprecated in favor of this
    # wrapper - without it every SVM-trained classifier would silently drop
    # out of the gates.
    estimator = build_estimator("classification", "svm")
    assert isinstance(estimator, CalibratedClassifierCV)
    assert isinstance(estimator.estimator, SVC)
    assert hasattr(estimator, "predict_proba")


def test_svm_is_offered_for_classification_only():
    with pytest.raises(ValueError, match="estimator"):
        build_estimator("regression", "svm")


def test_ridge_is_offered_for_regression_only():
    with pytest.raises(ValueError, match="estimator"):
        build_estimator("classification", "ridge")


def test_xgboost_regression_predicts_in_original_units():
    X = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0]})
    y = pd.Series([100000.0, 200000.0, 300000.0, 400000.0])

    estimator = build_estimator("regression", "xgboost")
    estimator.fit(X, y)

    assert estimator.predict(X).min() > 1000, "predictions are not on the dollar scale"


def test_xgboost_classification_predicts_the_labels_it_was_fitted_on():
    X = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0]})
    y = pd.Series([0, 1, 0, 1])

    estimator = build_estimator("classification", "xgboost")
    estimator.fit(X, y)

    assert set(estimator.predict(X)).issubset({0, 1})


# --- tune=True: default hyperparameters vs GridSearchCV --------------------


def test_tune_defaults_to_false_and_returns_the_bare_estimator():
    estimator = build_estimator("regression", "ridge")
    assert not isinstance(estimator, GridSearchCV)


def test_tune_true_wraps_the_estimator_in_grid_search_cv():
    estimator = build_estimator("regression", "ridge", tune=True)
    assert isinstance(estimator, GridSearchCV)
    assert estimator.param_grid == PARAM_GRIDS["regression"]["ridge"]
    assert estimator.cv.n_splits == CV_FOLDS


def test_tune_true_uses_the_metric_this_project_already_grades_models_on():
    # Tuning "best" has to mean the same thing gates and drift already use -
    # rmse (ml_common.metrics, drift.performance_severity) for regression,
    # auc for classification - or a "tuned" model could win a search on one
    # yardstick and still fail the gate that judges it by another.
    regression = build_estimator("regression", "ridge", tune=True)
    classification = build_estimator("classification", "xgboost", tune=True)

    assert regression.scoring == SCORING["regression"] == "neg_root_mean_squared_error"
    assert classification.scoring == SCORING["classification"] == "roc_auc"


def test_tune_true_fits_every_declared_regression_estimator():
    X = pd.DataFrame({"a": np.arange(20, dtype=float), "b": np.arange(20, dtype=float) % 3})
    y = pd.Series(np.arange(20, dtype=float) * 1000 + 50_000)

    for name in ESTIMATOR_NAMES["regression"]:
        estimator = build_estimator("regression", name, tune=True)
        estimator.fit(X, y)
        assert set(estimator.best_params_) == set(PARAM_GRIDS["regression"][name])


def test_tune_true_fits_every_declared_classification_estimator():
    X = pd.DataFrame({"a": np.arange(20, dtype=float), "b": np.arange(20, dtype=float) % 3})
    y = pd.Series(np.arange(20) % 2)

    for name in ESTIMATOR_NAMES["classification"]:
        estimator = build_estimator("classification", name, tune=True)
        estimator.fit(X, y)
        assert set(estimator.best_params_) == set(PARAM_GRIDS["classification"][name])


# --- time-ordered CV, decision threshold, defaults --------------------------

from ml_common.estimators import (  # noqa: E402
    DEFAULT_ESTIMATOR,
    TARGET_RECALL,
    ThresholdedClassifier,
    TimeOrderedSplit,
    build_model,
    choose_threshold,
    decision_threshold,
    fitted_search,
)


def test_time_ordered_split_scores_only_rows_after_the_learned_dated_rows():
    rows = np.zeros((100, 1))
    for learn, score in TimeOrderedSplit(n_splits=5, undated_rows=10).split(rows):
        assert set(range(10)) <= set(learn)
        assert learn[learn >= 10].max() < score.min()
        assert score.min() >= 10


def test_tuning_uses_time_ordered_folds():
    assert isinstance(build_estimator("regression", "ridge", tune=True).cv, TimeOrderedSplit)


def test_regression_default_is_xgboost_because_ridge_fails_gate_one():
    assert DEFAULT_ESTIMATOR == {"regression": "xgboost", "classification": "xgboost"}


def test_dag_default_estimators_match_the_common_ones():
    from pathlib import Path

    dag = (Path(__file__).resolve().parents[2] / "dags" / "ml_pipeline_dag.py").read_text()
    for task_type, name in DEFAULT_ESTIMATOR.items():
        assert f'"{task_type}": "{name}"' in dag


def test_choose_threshold_is_the_highest_reaching_the_recall():
    assert choose_threshold([1, 1, 1, 0], [0.9, 0.6, 0.2, 0.1], 0.66) == 0.6
    assert choose_threshold([0, 0], [0.9, 0.1]) == 0.5


def _classification_data(n=400, seed=0):
    rng = np.random.default_rng(seed)
    X = pd.DataFrame({"a": rng.normal(size=n), "b": rng.normal(size=n)})
    y = pd.Series((X["a"] + rng.normal(scale=1.0, size=n)) > 1.0)
    return X, y


def test_thresholded_classifier_reaches_the_recall_on_its_holdout():
    X, y = _classification_data()
    model = build_model("classification", "random_forest").fit(X, y)
    cut = int(len(y) * 0.8)
    assert isinstance(model, ThresholdedClassifier)
    assert 0 < decision_threshold(model) < 1
    temp = RandomForestClassifier(random_state=42).fit(X.iloc[:cut], y.iloc[:cut])
    holdout_proba = temp.predict_proba(X.iloc[cut:])[:, 1]
    caught = (holdout_proba >= model.threshold_)[y.iloc[cut:].to_numpy()]
    assert caught.mean() >= TARGET_RECALL


def test_thresholded_classifier_predicts_at_its_threshold():
    X, y = _classification_data()
    model = build_model("classification", "xgboost").fit(X, y)
    proba = model.predict_proba(X)[:, 1]
    assert (model.predict(X) == (proba >= model.threshold_)).all()


def test_thresholded_classifier_survives_a_pickle_round_trip():
    import pickle

    X, y = _classification_data()
    model = build_model("classification", "xgboost").fit(X, y)
    again = pickle.loads(pickle.dumps(model))
    assert again.threshold_ == model.threshold_
    assert (again.predict(X) == model.predict(X)).all()


def test_tuned_classifier_exposes_its_search_and_threshold():
    X, y = _classification_data(200)
    model = build_model("classification", "random_forest", tune=True).fit(X, y)
    assert fitted_search(model) is not None
    assert decision_threshold(model) is not None


def test_regression_model_has_no_threshold():
    model = build_model("regression", "ridge")
    assert not isinstance(model, ThresholdedClassifier)
    assert fitted_search(model) is None
