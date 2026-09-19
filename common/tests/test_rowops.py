import numpy as np
import pandas as pd
import pytest

from ml_common import rowops


def test_drop_duplicates_removes_rows_with_duplicate_property_id():
    df = pd.DataFrame(
        {
            "property_id": [1, 2, 2, 3],
            "city": ["a", "b", "b", "c"],
        }
    )
    result, dropped_count = rowops.drop_duplicates(df)
    assert len(result) == 3
    assert dropped_count == 1
    assert result["property_id"].tolist() == [1, 2, 3]


def test_drop_duplicates_keeps_the_first_row():
    df = pd.DataFrame({"property_id": [1, 1], "city": ["first", "second"]})
    result, _ = rowops.drop_duplicates(df)
    assert result["city"].tolist() == ["first"]


def test_drop_duplicates_with_no_duplicates_keeps_all_rows():
    df = pd.DataFrame({"property_id": [1, 2, 3]})
    result, dropped_count = rowops.drop_duplicates(df)
    assert len(result) == 3
    assert dropped_count == 0


def test_drop_duplicates_reindexes_the_result():
    df = pd.DataFrame({"property_id": [1, 1, 2]})
    result, _ = rowops.drop_duplicates(df)
    assert result.index.tolist() == [0, 1]


def test_drop_rows_missing_target_regression():
    df = pd.DataFrame({"sale_price": [100.0, np.nan, 300.0], "city": ["a", "b", "c"]})
    result, dropped_count = rowops.drop_rows_missing_target(df, "regression")
    assert len(result) == 2
    assert dropped_count == 1


def test_drop_rows_missing_target_classification():
    df = pd.DataFrame({"needs_renovation": [True, None, False]})
    result, dropped_count = rowops.drop_rows_missing_target(df, "classification")
    assert len(result) == 2
    assert dropped_count == 1


def test_drop_rows_missing_target_missing_target_column_raises():
    df = pd.DataFrame({"city": ["a"]})
    with pytest.raises(KeyError, match="sale_price"):
        rowops.drop_rows_missing_target(df, "regression")


def test_drop_rows_missing_target_invalid_task_type_raises():
    df = pd.DataFrame({"sale_price": [1.0]})
    with pytest.raises(ValueError, match="task_type"):
        rowops.drop_rows_missing_target(df, "clustering")
