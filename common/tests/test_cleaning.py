import numpy as np
import pandas as pd
import pytest

from ml_common import cleaning


@pytest.fixture
def dirty_df():
    """A small DataFrame covering every dirty type."""
    return pd.DataFrame(
        {
            "property_id": [1, 2, 3],
            "listing_date": ["2023-07-15", "07/15/2023", "15-Jul-2023"],
            "city": ["NEW YORK", "new_york", "  New York  "],
            "state": ["NY", "ny", "Ny"],
            "zipcode": ["10001", "1000", None],
            "property_type": ["Single_Family", "MULTI FAMILY", "Multi-Family"],
            "living_area_sqft": [1500.0, 2000.0, 45000.0],
            "bedrooms": [3.0, -1.0, 25.0],
            "bathrooms": [2.0, 1.5, 50.0],
            "year_built": [1990.0, 2055.0, 1750.0],
            "has_pool": ["Yes", "N", "1"],
            "condition": ["Good", "EXCELLENT", "poor"],
            "distance_to_city_center_km": [5.0, -3.0, 10.0],
            "list_price": ["$450,000", 500000, "$1,250,000"],
            "sale_price": [440000, "$490,000", 1200000],
        }
    )


class TestRawRecordCleaner:
    def test_never_drops_rows(self, dirty_df):
        result = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        assert len(result) == len(dirty_df)

    def test_works_with_a_single_row(self, dirty_df):
        """Serving calls /predict with one record — this must work."""
        one_row = dirty_df.head(1)
        result = cleaning.RawRecordCleaner().fit_transform(one_row)
        assert len(result) == 1

    def test_parses_money_columns(self, dirty_df):
        result = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        assert result["list_price"].tolist() == [450000.0, 500000.0, 1250000.0]
        assert result["sale_price"].tolist() == [440000.0, 490000.0, 1200000.0]

    def test_normalizes_categorical_columns(self, dirty_df):
        result = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        assert result["city"].tolist() == ["new york", "new york", "new york"]
        assert result["state"].tolist() == ["ny", "ny", "ny"]
        assert result["property_type"].tolist() == [
            "single family",
            "multi family",
            "multi family",
        ]

    def test_parses_boolean_columns(self, dirty_df):
        result = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        assert result["has_pool"].tolist() == [True, False, True]

    def test_invalid_zipcode_becomes_none(self, dirty_df):
        result = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        assert result["zipcode"].tolist() == ["10001", None, None]

    def test_three_date_formats_parse_to_the_same_date(self, dirty_df):
        result = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        parsed = pd.to_datetime(result["listing_date"])
        assert parsed.nunique() == 1

    def test_does_not_mutate_the_input_dataframe(self, dirty_df):
        original_copy = dirty_df.copy(deep=True)
        cleaning.RawRecordCleaner().fit_transform(dirty_df)
        pd.testing.assert_frame_equal(dirty_df, original_copy)

    def test_missing_column_is_skipped_without_raising(self):
        """Serving may receive a record missing an optional column."""
        df = pd.DataFrame({"city": ["NEW YORK"], "list_price": ["$100,000"]})
        result = cleaning.RawRecordCleaner().fit_transform(df)
        assert result["city"].tolist() == ["new york"]
        assert result["list_price"].tolist() == [100000.0]

    def test_column_outside_schema_is_left_untouched(self):
        df = pd.DataFrame({"city": ["NEW YORK"], "extra_column": [42]})
        result = cleaning.RawRecordCleaner().fit_transform(df)
        assert result["extra_column"].tolist() == [42]


class TestOutlierClipper:
    def test_clips_to_schema_bounds(self, dirty_df):
        cleaned = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        result = cleaning.OutlierClipper().fit_transform(cleaned)
        # bedrooms: -1 -> 0, 25 -> 20
        assert result["bedrooms"].tolist() == [3.0, 0.0, 20.0]
        # bathrooms: 50 -> 15
        assert result["bathrooms"].tolist() == [2.0, 1.5, 15.0]
        # distance: -3 -> 0
        assert result["distance_to_city_center_km"].tolist() == [5.0, 0.0, 10.0]

    def test_future_build_year_is_clipped(self, dirty_df):
        from datetime import date

        cleaned = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        result = cleaning.OutlierClipper().fit_transform(cleaned)
        assert result["year_built"].max() <= date.today().year
        assert result["year_built"].min() >= 1800

    def test_abnormal_area_is_clipped(self, dirty_df):
        cleaned = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        result = cleaning.OutlierClipper().fit_transform(cleaned)
        assert result["living_area_sqft"].max() <= 50_000

    def test_does_not_drop_rows(self, dirty_df):
        cleaned = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        result = cleaning.OutlierClipper().fit_transform(cleaned)
        assert len(result) == len(dirty_df)

    def test_missing_value_stays_missing_after_clip(self):
        df = pd.DataFrame({"bedrooms": [np.nan, 3.0]})
        result = cleaning.OutlierClipper().fit_transform(df)
        assert pd.isna(result["bedrooms"].iloc[0])


class TestDateFeatures:
    def test_splits_year_and_month(self, dirty_df):
        cleaned = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        result = cleaning.DateFeatures().fit_transform(cleaned)
        assert result["listing_year"].tolist() == [2023, 2023, 2023]
        assert result["listing_month"].tolist() == [7, 7, 7]

    def test_drops_the_original_date_column(self, dirty_df):
        cleaned = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        result = cleaning.DateFeatures().fit_transform(cleaned)
        assert "listing_date" not in result.columns

    def test_missing_date_becomes_nan_without_raising(self):
        df = pd.DataFrame({"listing_date": [None, pd.Timestamp("2023-07-15")]})
        result = cleaning.DateFeatures().fit_transform(df)
        assert pd.isna(result["listing_year"].iloc[0])
        assert result["listing_year"].iloc[1] == 2023
