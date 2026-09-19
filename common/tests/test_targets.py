"""Tests for target parsing — the one column the Pipeline never touches."""

import numpy as np
import pandas as pd
import pytest

from ml_common.targets import (
    NEEDS_RENOVATION_CONDITIONS,
    TARGET_SOURCE,
    derive_target,
    parse_target,
)


def test_regression_target_parses_money_strings():
    series = pd.Series(["$450,000", "320000", "$1,200,500.50"])
    result = parse_target(series, "regression")
    assert list(result) == [450000.0, 320000.0, 1200500.50]


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


def _frame(conditions):
    return pd.DataFrame({"condition": conditions, "sale_price": ["$1"] * len(conditions)})


def test_target_source_names_the_column_each_task_reads():
    assert TARGET_SOURCE["regression"] == "sale_price"
    assert TARGET_SOURCE["classification"] == "condition"


def test_poor_and_fair_need_renovation():
    result = derive_target(_frame(["poor", "fair"]), "classification")
    assert list(result) == [True, True]


def test_good_and_excellent_do_not():
    result = derive_target(_frame(["good", "excellent"]), "classification")
    assert list(result) == [False, False]


def test_dirty_condition_is_normalized_before_comparing():
    """Dirty type 3: the same value arrives in several spellings."""
    result = derive_target(_frame(["POOR", "  Fair  ", "Good"]), "classification")
    assert list(result) == [True, True, False]


def test_unknown_condition_becomes_null_not_a_guess():
    result = derive_target(_frame(["poor", "unknown", None]), "classification")
    assert result[0] is True
    assert pd.isna(result[1])
    assert pd.isna(result[2])


def test_derive_target_preserves_index():
    df = _frame(["poor", "good"])
    df.index = [7, 9]
    assert list(derive_target(df, "classification").index) == [7, 9]


def test_regression_still_parses_money():
    df = pd.DataFrame({"sale_price": ["$450,000", "320000"], "condition": ["good", "good"]})
    assert list(derive_target(df, "regression")) == [450000.0, 320000.0]


def test_missing_source_column_raises():
    with pytest.raises(KeyError, match="condition"):
        derive_target(pd.DataFrame({"sale_price": ["$1"]}), "classification")


def test_invalid_task_type_raises_in_derive_target():
    with pytest.raises(ValueError, match="task_type"):
        derive_target(_frame(["poor"]), "clustering")


def test_needs_renovation_conditions_are_the_two_bad_ones():
    assert NEEDS_RENOVATION_CONDITIONS == frozenset({"poor", "fair"})
