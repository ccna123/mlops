"""Tests for estimator construction, especially the log-target wrapper."""

import numpy as np
import pandas as pd
import pytest
from sklearn.compose import TransformedTargetRegressor

from ml_common.estimators import ESTIMATOR_NAMES, build_estimator


def test_regression_estimator_is_wrapped_for_log_target():
    estimator = build_estimator("regression", "ridge")
    assert isinstance(estimator, TransformedTargetRegressor)


def test_classification_estimator_is_not_wrapped():
    estimator = build_estimator("classification", "logistic")
    assert not isinstance(estimator, TransformedTargetRegressor)


def test_regression_predicts_in_original_units():
    """The wrapper must undo the log, so predictions come back in dollars."""
    X = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0]})
    y = pd.Series([100000.0, 200000.0, 300000.0, 400000.0])

    estimator = build_estimator("regression", "ridge")
    estimator.fit(X, y)
    predictions = estimator.predict(X)

    assert predictions.min() > 1000, "predictions look like logs, not dollars"


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
    with pytest.raises(ValueError, match="estimator"):
        build_estimator("regression", "xgboost")
