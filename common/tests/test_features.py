import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.pipeline import Pipeline

from ml_common import features


@pytest.fixture
def raw_df():
    """RAW data — mirrors real data before cleaning."""
    row_count = 40
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "property_id": range(row_count),
            "listing_date": ["2023-07-15", "07/15/2023"] * (row_count // 2),
            "city": ["NEW YORK", "new_york", "  Boston ", "BOSTON"] * (row_count // 4),
            "state": ["NY", "ny", "MA", "ma"] * (row_count // 4),
            "zipcode": ["10001", "1000"] * (row_count // 2),
            "property_type": ["Single_Family", "MULTI FAMILY"] * (row_count // 2),
            "lot_size_sqft": rng.uniform(1000, 9000, row_count),
            "living_area_sqft": rng.uniform(800, 4000, row_count),
            "bedrooms": rng.integers(1, 6, row_count).astype(float),
            "bathrooms": rng.choice([1.0, 1.5, 2.0, 2.5], row_count),
            "year_built": rng.integers(1950, 2020, row_count).astype(float),
            "stories": rng.integers(1, 4, row_count).astype(float),
            "garage_spaces": rng.integers(0, 3, row_count).astype(float),
            "has_pool": ["Yes", "N", "1", "False"] * (row_count // 4),
            "hoa_fee_monthly": rng.uniform(0, 400, row_count),
            "school_rating": rng.uniform(1, 10, row_count),
            "crime_index": rng.uniform(0, 100, row_count),
            "distance_to_city_center_km": rng.uniform(0, 40, row_count),
            "condition": ["Good", "EXCELLENT", "poor", "Fair"] * (row_count // 4),
            "days_on_market": rng.integers(1, 200, row_count),
            "list_price": ["$450,000", 500000] * (row_count // 2),
            "sale_price": [440000, "$490,000"] * (row_count // 2),
            "price_category": ["Medium", "High"] * (row_count // 2),
            "sold_within_30_days": ["Yes", "No"] * (row_count // 2),
        }
    )


def test_returns_a_sklearn_pipeline():
    result = features.build_pipeline("regression", DummyRegressor())
    assert isinstance(result, Pipeline)


def test_invalid_task_type_raises():
    with pytest.raises(ValueError, match="task_type"):
        features.build_pipeline("clustering", DummyRegressor())


def test_regression_fit_and_predict_on_RAW_data(raw_df):
    """This is the most important guarantee: the Pipeline accepts raw data,
    no cleaning needed beforehand. If this test passes, serving calling
    /predict with a raw record will work correctly."""
    pipeline = features.build_pipeline("regression", DummyRegressor())
    X = raw_df.drop(columns=["sale_price"])
    y = pd.to_numeric(raw_df["sale_price"].astype(str).str.replace(r"[$,]", "", regex=True))
    pipeline.fit(X, y)
    predictions = pipeline.predict(X)
    assert len(predictions) == len(raw_df)


def test_classification_fit_and_predict_on_RAW_data(raw_df):
    pipeline = features.build_pipeline("classification", DummyClassifier())
    X = raw_df.drop(columns=["sold_within_30_days"])
    y = raw_df["sold_within_30_days"].map({"Yes": 1, "No": 0})
    pipeline.fit(X, y)
    predictions = pipeline.predict(X)
    assert len(predictions) == len(raw_df)


def test_can_predict_a_SINGLE_record(raw_df):
    """Serving receives a single record."""
    pipeline = features.build_pipeline("regression", DummyRegressor())
    X = raw_df.drop(columns=["sale_price"])
    y = pd.to_numeric(raw_df["sale_price"].astype(str).str.replace(r"[$,]", "", regex=True))
    pipeline.fit(X, y)
    predictions = pipeline.predict(X.head(1))
    assert len(predictions) == 1


def test_leakage_columns_do_not_affect_the_pipeline(raw_df):
    """price_category and list_price must not influence the regression model.

    Uses DecisionTreeRegressor, NOT DummyRegressor: Dummy ignores every
    feature, so it would pass even with a buggy Pipeline, giving false
    confidence.
    """
    from sklearn.tree import DecisionTreeRegressor

    pipeline = features.build_pipeline("regression", DecisionTreeRegressor(random_state=0))
    X = raw_df.drop(columns=["sale_price"])
    y = pd.to_numeric(raw_df["sale_price"].astype(str).str.replace(r"[$,]", "", regex=True))
    pipeline.fit(X, y)

    X_altered = X.copy()
    X_altered["price_category"] = "Luxury"
    X_altered["list_price"] = "$9,999,999"
    np.testing.assert_array_equal(pipeline.predict(X), pipeline.predict(X_altered))


def test_selectcolumns_actually_excludes_leakage_columns():
    """Checks the column list directly, without going through predict results."""
    from sklearn.dummy import DummyRegressor as _Dummy

    pipeline = features.build_pipeline("regression", _Dummy())
    selected_columns = pipeline.named_steps["select_columns"].columns
    assert "price_category" not in selected_columns
    assert "list_price" not in selected_columns
    assert "sale_price" not in selected_columns
    assert "property_id" not in selected_columns
    assert "living_area_sqft" in selected_columns


def test_unseen_categorical_value_does_not_crash(raw_df):
    """The Plan 4 agent will send a new property_type (drift_scenario=new_segment)."""
    pipeline = features.build_pipeline("regression", DummyRegressor())
    X = raw_df.drop(columns=["sale_price"])
    y = pd.to_numeric(raw_df["sale_price"].astype(str).str.replace(r"[$,]", "", regex=True))
    pipeline.fit(X, y)

    X_new = X.head(1).copy()
    X_new["property_type"] = "Houseboat"
    X_new["city"] = "Atlantis"
    predictions = pipeline.predict(X_new)
    assert len(predictions) == 1


def test_missing_values_do_not_crash(raw_df):
    pipeline = features.build_pipeline("regression", DummyRegressor())
    X = raw_df.drop(columns=["sale_price"])
    y = pd.to_numeric(raw_df["sale_price"].astype(str).str.replace(r"[$,]", "", regex=True))
    pipeline.fit(X, y)

    X_missing = X.head(1).copy()
    for column in ["bedrooms", "bathrooms", "year_built", "school_rating", "hoa_fee_monthly"]:
        X_missing[column] = np.nan
    predictions = pipeline.predict(X_missing)
    assert len(predictions) == 1


def test_thresholded_classifier_pipeline_answers_a_single_raw_record(raw_df):
    from ml_common.estimators import build_model

    pipeline = features.build_pipeline("classification", build_model("classification", "xgboost"))
    X = raw_df.drop(columns=["condition"])
    y = raw_df["condition"].str.lower().isin(["poor", "fair"])
    pipeline.fit(X, y)
    record = X.head(1)
    probability = pipeline.predict_proba(record)[:, 1]
    threshold = pipeline.named_steps["model"].threshold_
    assert list(pipeline.predict(record)) == [bool(probability[0] >= threshold)]
