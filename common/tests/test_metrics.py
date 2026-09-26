"""Tests for metric computation shared by train and evaluate."""

import json

import numpy as np
import pytest

from ml_common.metrics import compute_metrics


def test_regression_keys():
    result = compute_metrics("regression", [1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert set(result) == {"rmse", "mae", "r2"}


def test_perfect_regression_prediction():
    result = compute_metrics("regression", [1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert result["rmse"] == pytest.approx(0.0)
    assert result["r2"] == pytest.approx(1.0)


def test_rmse_is_in_the_same_unit_as_the_target():
    """Off by 1000 dollars on every row means RMSE is 1000, not log-of-anything."""
    y_true = [100000.0, 200000.0, 300000.0]
    y_pred = [101000.0, 201000.0, 301000.0]
    result = compute_metrics("regression", y_true, y_pred)
    assert result["rmse"] == pytest.approx(1000.0)


def test_classification_keys_without_proba():
    result = compute_metrics("classification", [0, 1, 1, 0], [0, 1, 1, 0])
    assert set(result) == {"f1", "precision", "recall", "accuracy"}


def test_classification_keys_with_proba():
    result = compute_metrics(
        "classification", [0, 1, 1, 0], [0, 1, 1, 0], y_proba=[0.1, 0.9, 0.8, 0.2]
    )
    assert set(result) == {"f1", "precision", "recall", "accuracy", "auc"}


def test_all_values_are_plain_floats():
    """MLflow and json.dumps both choke on numpy scalars."""
    result = compute_metrics("regression", np.array([1.0, 2.0]), np.array([1.1, 2.1]))
    for value in result.values():
        assert type(value) is float
    json.dumps(result)


def test_invalid_task_type_raises():
    with pytest.raises(ValueError, match="task_type"):
        compute_metrics("clustering", [1.0], [1.0])
