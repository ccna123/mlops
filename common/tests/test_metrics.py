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


def test_group_metrics_normalizes_names_and_marks_small_groups():
    import pandas as pd

    from ml_common.metrics import group_metrics

    raw = pd.DataFrame({"city": ["NEW YORK", "new_york"] * 3 + ["Tulsa"],
                        "property_type": ["condo"] * 7})
    y = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 90.0]
    pred = [101.0, 111.0, 119.0, 131.0, 139.0, 151.0, 50.0]
    result = group_metrics("regression", raw, y, pred, min_rows=5)
    assert result["city"]["new york"]["n"] == 6
    assert "rmse" in result["city"]["new york"]
    assert result["city"]["tulsa"] == {"n": 1, "insufficient_data": True}
    assert result["property_type"]["condo"]["n"] == 7


def test_group_metrics_leaves_auc_out_of_a_one_class_group():
    import pandas as pd

    from ml_common.metrics import group_metrics

    raw = pd.DataFrame({"city": ["a"] * 4 + ["b"] * 4})
    y = [True, True, True, True, True, False, True, False]
    pred = y
    proba = [0.9, 0.8, 0.7, 0.6, 0.9, 0.1, 0.8, 0.2]
    result = group_metrics("classification", raw, y, pred, proba, min_rows=2)
    assert "auc" not in result["city"]["a"]
    assert "auc" in result["city"]["b"]
