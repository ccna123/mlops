"""Tests for the validate stage's rules.

The dataset is dirty on purpose, so these tests pin down the line between
"dirty but usable" (must pass) and "unusable" (must fail).
"""

import numpy as np
import pandas as pd
import pytest

from ml_common import schema
from ml_common.validation import validate_dataframe


def _valid_frame(row_count: int = 4) -> pd.DataFrame:
    """A frame with every schema column present, in bounds, and a usable target.

    The id column gets distinct values on purpose: giving every row the same id
    would make the duplicate count equal row_count - 1 and quietly break the
    tests that assert on it.
    """
    data = {}
    for column_name, spec in schema.COLUMNS.items():
        if spec.kind == "id":
            data[column_name] = [f"P{index}" for index in range(row_count)]
        elif spec.kind == "numeric":
            # Start at the column's own lower bound so nothing is out of bounds
            # before a test deliberately puts it there.
            base = spec.min_value if spec.min_value is not None else 1
            data[column_name] = [base] * row_count
        elif spec.kind == "money":
            data[column_name] = ["$100,000"] * row_count
        elif spec.kind == "boolean":
            data[column_name] = ["Y"] * row_count
        elif spec.kind == "date":
            data[column_name] = ["2024-01-15"] * row_count
        else:
            data[column_name] = ["value"] * row_count
    data[schema.target_column("regression")] = [100000.0] * row_count
    return pd.DataFrame(data)


def test_clean_enough_frame_passes():
    report = validate_dataframe(_valid_frame(), "regression")
    assert report["ok"] is True
    assert report["fatal"] == []


def test_dirty_but_usable_frame_still_passes():
    """Dirty values are the exercise, not an incident — they must not fail the run."""
    df = _valid_frame()
    df.loc[0, "city"] = "  NEW_YORK  "
    df.loc[1, "zipcode"] = "1234"
    df.loc[2, "bedrooms"] = -5
    report = validate_dataframe(df, "regression")
    assert report["ok"] is True


def test_missing_column_is_fatal():
    df = _valid_frame().drop(columns=["city"])
    report = validate_dataframe(df, "regression")
    assert report["ok"] is False
    assert any("city" in reason for reason in report["fatal"])


def test_empty_frame_is_fatal():
    report = validate_dataframe(_valid_frame(row_count=0), "regression")
    assert report["ok"] is False
    assert any("no rows" in reason for reason in report["fatal"])


def test_target_mostly_missing_is_fatal():
    df = _valid_frame(row_count=10)
    df.loc[0:5, schema.target_column("regression")] = np.nan
    report = validate_dataframe(df, "regression")
    assert report["ok"] is False
    assert any("target" in reason for reason in report["fatal"])


def test_target_half_missing_is_not_fatal():
    """The rule is 'more than 50%', so exactly half must still pass."""
    df = _valid_frame(row_count=10)
    df.loc[0:4, schema.target_column("regression")] = np.nan
    report = validate_dataframe(df, "regression")
    assert report["ok"] is True


def test_report_counts_missing_rate_per_column():
    df = _valid_frame(row_count=4)
    df.loc[0:1, "city"] = None
    report = validate_dataframe(df, "regression")
    assert report["columns"]["city"]["missing_rate"] == pytest.approx(0.5)


def test_report_counts_duplicate_rows():
    df = _valid_frame(row_count=4)
    df.loc[1, schema.ID_COLUMN] = df.loc[0, schema.ID_COLUMN]
    report = validate_dataframe(df, "regression")
    assert report["duplicate_rows"] == 1


def test_report_counts_out_of_bounds_values():
    df = _valid_frame(row_count=4)
    df.loc[0, "bedrooms"] = -1
    report = validate_dataframe(df, "regression")
    assert report["columns"]["bedrooms"]["out_of_bounds"] == 1


def test_report_is_json_serializable():
    """The report goes to MinIO as JSON, so no numpy types may survive."""
    import json

    report = validate_dataframe(_valid_frame(), "regression")
    json.dumps(report)


def test_invalid_task_type_raises():
    with pytest.raises(ValueError, match="task_type"):
        validate_dataframe(_valid_frame(), "clustering")
