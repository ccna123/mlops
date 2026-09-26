import numpy as np
import pandas as pd
import pytest

from ml_common import preparation, splits

RULES = {splits.SOURCE_ORIGINAL: {"t1": "2021-01-01", "t2": "2022-01-01",
                                  "undated_test_share": 0.2}}


def _light(n: int = 1200) -> pd.DataFrame:
    days = pd.date_range("2019-06-01", periods=n, freq="D").strftime("%Y-%m-%d").tolist()
    return pd.DataFrame(
        {
            "property_id": [f"p{i}" for i in range(n)],
            "listing_date": days,
            "sale_price": ["$100,000"] * n,
        }
    )


def _dates(light, positions):
    return [pd.Timestamp(light["listing_date"].iloc[p]) for p in positions]


def test_test_set_is_after_train_set_and_before_simulation():
    light = _light()
    plan = preparation.plan_rows(light, "regression", RULES, None, 42)
    assert max(_dates(light, plan.train_positions)) < min(_dates(light, plan.test_positions))
    assert plan.counts["simulation_rows"] > 0
    assert max(_dates(light, plan.test_positions)) < pd.Timestamp("2022-01-01")


def test_test_set_does_not_change_with_the_row_limit():
    light = _light()
    full = preparation.plan_rows(light, "regression", RULES, None, 42)
    small = preparation.plan_rows(light, "regression", RULES, 50, 42)
    assert np.array_equal(full.test_positions, small.test_positions)
    assert len(small.train_positions) == 50


def test_train_sample_is_random_not_the_first_rows_and_repeatable():
    light = _light()
    first = preparation.plan_rows(light, "regression", RULES, 50, 42)
    again = preparation.plan_rows(light, "regression", RULES, 50, 42)
    other = preparation.plan_rows(light, "regression", RULES, 50, 7)
    assert np.array_equal(first.train_positions, again.train_positions)
    assert not np.array_equal(first.train_positions, other.train_positions)
    assert not np.array_equal(first.train_positions, np.arange(50))


def test_no_property_is_in_both_sets_even_when_duplicated_across_the_split():
    light = _light()
    light.loc[1000, "property_id"] = "p0"  # a test-period duplicate of a train house
    plan = preparation.plan_rows(light, "regression", RULES, None, 42)
    train_ids = set(light["property_id"].iloc[plan.train_positions])
    test_ids = set(light["property_id"].iloc[plan.test_positions])
    assert not train_ids & test_ids
    assert plan.counts["dropped_duplicates"] == 1


def test_records_without_target_are_dropped_and_counted():
    light = _light()
    light.loc[[3, 4], "sale_price"] = "call us"
    plan = preparation.plan_rows(light, "regression", RULES, None, 42)
    assert plan.counts["dropped_missing_target"] == 2
    assert 3 not in plan.train_positions and 4 not in plan.train_positions


def test_simulation_records_are_in_neither_set():
    light = _light()
    plan = preparation.plan_rows(light, "regression", RULES, None, 42)
    kept = len(plan.train_positions) + len(plan.test_positions)
    assert kept + plan.counts["simulation_rows"] == len(light)


def test_classification_plan_uses_condition():
    light = _light(10)
    light["condition"] = ["poor", None] * 5
    plan = preparation.plan_rows(light.drop(columns="sale_price"), "classification",
                                 RULES, None, 42)
    assert plan.counts["dropped_missing_target"] == 5


def test_non_positive_row_limit_is_refused():
    with pytest.raises(ValueError):
        preparation.plan_rows(_light(10), "regression", RULES, 0, 42)


def test_light_columns_keeps_only_what_exists():
    cols = preparation.light_columns("classification", ["property_id", "listing_date",
                                                        "condition", "city"])
    assert cols == ["property_id", "listing_date", "condition"]
