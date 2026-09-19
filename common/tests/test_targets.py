"""Tests for target parsing — the one column the Pipeline never touches."""

import numpy as np
import pandas as pd
import pytest

from ml_common.targets import parse_target


def test_regression_target_parses_money_strings():
    series = pd.Series(["$450,000", "320000", "$1,200,500.50"])
    result = parse_target(series, "regression")
    assert list(result) == [450000.0, 320000.0, 1200500.50]


def test_classification_target_parses_every_boolean_form():
    series = pd.Series(["Y", "no", "1", "True"])
    result = parse_target(series, "classification")
    assert list(result) == [True, False, True, True]


def test_unparseable_value_becomes_null_not_a_guess():
    series = pd.Series(["$450,000", "not a price", None])
    result = parse_target(series, "regression")
    assert result[0] == 450000.0
    assert pd.isna(result[1])
    assert pd.isna(result[2])


def test_already_numeric_target_survives():
    """Running twice must not corrupt the values."""
    series = pd.Series([450000.0, 320000.0])
    result = parse_target(series, "regression")
    assert list(result) == [450000.0, 320000.0]


def test_index_is_preserved():
    """The caller lines this up against the feature rows, so the index must match."""
    series = pd.Series(["$1", "$2"], index=[10, 20])
    result = parse_target(series, "regression")
    assert list(result.index) == [10, 20]


def test_regression_result_is_numeric_dtype():
    result = parse_target(pd.Series(["$450,000", "$1"]), "regression")
    assert np.issubdtype(result.dtype, np.number)


def test_empty_series_does_not_crash():
    result = parse_target(pd.Series([], dtype=object), "regression")
    assert len(result) == 0


def test_invalid_task_type_raises():
    with pytest.raises(ValueError, match="task_type"):
        parse_target(pd.Series(["$1"]), "clustering")
