import numpy as np
import pandas as pd

from ml_common import profiling


def sample_df():
    rng = np.random.default_rng(7)
    return pd.DataFrame(
        {
            "living_area_sqft": rng.uniform(800, 4000, 500),
            "bedrooms": rng.integers(1, 6, 500).astype(float),
            "city": rng.choice(["new york", "boston", "austin"], 500),
            "condition": rng.choice(["good", "fair"], 500),
        }
    )


def test_has_common_metadata():
    profile = profiling.compute_profile(sample_df(), ["living_area_sqft", "city"])
    assert profile["n_rows"] == 500
    assert isinstance(profile["computed_at"], str)
    assert set(profile["columns"]) == {"living_area_sqft", "city"}


def test_numeric_column_has_full_stats():
    profile = profiling.compute_profile(sample_df(), ["living_area_sqft"])
    column = profile["columns"]["living_area_sqft"]
    assert column["kind"] == "numeric"
    assert 800 <= column["mean"] <= 4000
    assert column["std"] > 0
    assert column["min"] >= 800
    assert column["max"] <= 4000
    assert column["quantiles"]["p25"] < column["quantiles"]["p50"] < column["quantiles"]["p75"]


def test_histogram_has_the_requested_bin_count():
    profile = profiling.compute_profile(sample_df(), ["living_area_sqft"], n_bins=20)
    hist = profile["columns"]["living_area_sqft"]["histogram"]
    assert len(hist["counts"]) == 20
    assert len(hist["bin_edges"]) == 21
    assert sum(hist["counts"]) == 500


def test_categorical_column_distribution_sums_to_one():
    profile = profiling.compute_profile(sample_df(), ["city"])
    column = profile["columns"]["city"]
    assert column["kind"] == "categorical"
    assert column["n_unique"] == 3
    assert abs(sum(column["distribution"].values()) - 1.0) < 1e-9


def test_missing_rate_is_computed_correctly():
    df = pd.DataFrame({"bedrooms": [1.0, 2.0, np.nan, np.nan]})
    profile = profiling.compute_profile(df, ["bedrooms"])
    assert profile["columns"]["bedrooms"]["missing_rate"] == 0.5


def test_column_entirely_missing_does_not_crash():
    df = pd.DataFrame({"bedrooms": [np.nan, np.nan]})
    profile = profiling.compute_profile(df, ["bedrooms"])
    column = profile["columns"]["bedrooms"]
    assert column["missing_rate"] == 1.0
    assert column["mean"] is None


def test_column_not_in_df_is_skipped():
    profile = profiling.compute_profile(sample_df(), ["city", "nonexistent_column"])
    assert set(profile["columns"]) == {"city"}


def test_profile_is_json_serializable():
    import json

    profile = profiling.compute_profile(sample_df(), ["living_area_sqft", "city"])
    text = json.dumps(profile)
    assert json.loads(text)["n_rows"] == 500


def test_no_numpy_types_remain_in_the_result():
    """numpy types are not serializable by plain json."""
    profile = profiling.compute_profile(sample_df(), ["living_area_sqft", "city"])
    column = profile["columns"]["living_area_sqft"]
    assert type(column["mean"]) is float
    assert all(type(c) is int for c in column["histogram"]["counts"])
