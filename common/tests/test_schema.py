import pytest

from ml_common import schema


def test_has_24_columns():
    assert len(schema.COLUMNS) == 24


def test_every_column_has_valid_kind():
    valid_kinds = {"id", "numeric", "categorical", "boolean", "date", "money", "zipcode"}
    for name, spec in schema.COLUMNS.items():
        assert spec.kind in valid_kinds, f"{name} has invalid kind: {spec.kind}"


def test_regression_excludes_leakage_columns_and_list_price():
    cols = schema.feature_columns("regression")
    assert "sale_price" not in cols, "target must not be a feature"
    assert "price_category" not in cols, "price_category is derived from sale_price"
    assert "list_price" not in cols, "list_price would make the task trivial"
    assert "days_on_market" in cols, "days_on_market is valid for the regression task"


def test_classification_excludes_leakage_columns_but_keeps_list_price():
    cols = schema.feature_columns("classification")
    assert "sold_within_30_days" not in cols
    assert "days_on_market" not in cols, "sold_within_30_days is derived directly from this"
    assert "sale_price" not in cols, "only known after the sale"
    assert "price_category" not in cols
    assert "list_price" in cols, "asking price is known before the sale, a valid signal"


def test_id_column_never_in_features():
    for task in ("regression", "classification"):
        assert schema.ID_COLUMN not in schema.feature_columns(task)


def test_invalid_task_type_raises():
    with pytest.raises(ValueError, match="task_type"):
        schema.feature_columns("clustering")


def test_columns_of_kind_returns_correct_columns():
    assert set(schema.columns_of_kind("money")) == {"list_price", "sale_price"}
    assert set(schema.columns_of_kind("boolean")) == {"has_pool", "sold_within_30_days"}
    assert schema.columns_of_kind("date") == ["listing_date"]


def test_numeric_bounds_are_sensible():
    assert schema.COLUMNS["bedrooms"].min_value == 0
    assert schema.COLUMNS["bedrooms"].max_value == 20
    assert schema.COLUMNS["school_rating"].min_value == 1
    assert schema.COLUMNS["school_rating"].max_value == 10
    assert schema.COLUMNS["distance_to_city_center_km"].min_value == 0


def test_year_built_max_is_current_year():
    from datetime import date

    assert schema.COLUMNS["year_built"].max_value == date.today().year


def test_allowed_values_are_already_normalized():
    for name, spec in schema.COLUMNS.items():
        if spec.allowed is None:
            continue
        for value in spec.allowed:
            assert value == value.strip().lower(), f"{name}: {value!r} not normalized"
            assert "_" not in value and "-" not in value, f"{name}: {value!r} still has a separator"
