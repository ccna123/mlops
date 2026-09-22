"""Tests for estimator construction."""

import numpy as np
import pandas as pd
import pytest
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import RandomForestClassifier

from ml_common.estimators import ESTIMATOR_NAMES, build_estimator


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
    estimator = build_estimator("classification", "logistic")
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


def test_dummy_regression_predicts_a_constant():
    """The evaluate gate needs a model that reliably fails; dummy is it."""
    X = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0]})
    y = pd.Series([100000.0, 500000.0, 200000.0, 900000.0])

    estimator = build_estimator("regression", "dummy")
    estimator.fit(X, y)
    predictions = estimator.predict(X)

    assert np.allclose(predictions, predictions[0])


def test_invalid_task_type_raises():
    with pytest.raises(ValueError, match="task_type"):
        build_estimator("clustering", "ridge")


def test_unknown_estimator_name_raises():
    # "xgboost" used to stand in for an unknown name here. It is a real
    # estimator now, so this needs a name that genuinely is not offered.
    with pytest.raises(ValueError, match="estimator"):
        build_estimator("regression", "catboost")


def test_regression_offers_xgboost():
    assert type(build_estimator("regression", "xgboost")).__name__ == "XGBRegressor"


def test_classification_offers_xgboost():
    assert type(build_estimator("classification", "xgboost")).__name__ == "XGBClassifier"


def test_classification_offers_random_forest():
    assert isinstance(build_estimator("classification", "random_forest"), RandomForestClassifier)


def test_random_forest_is_offered_for_classification_only():
    # Asked for on classification only. Regression must refuse it loudly
    # rather than quietly hand back a DummyRegressor under that name.
    with pytest.raises(ValueError, match="estimator"):
        build_estimator("regression", "random_forest")


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
