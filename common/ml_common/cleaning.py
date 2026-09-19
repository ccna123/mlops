"""Data-cleaning transformers — column-wise ONLY.

The transformers here live inside a sklearn Pipeline and get packaged with
the model into MLflow, so they run in BOTH places: the `prepare_dataset_for_train` stage
(over 2 million rows) and serving (over a single record).

That means they must NEVER drop rows. Row-wise operations live in
`rowops.py`. See the plan's Global Constraints.
"""

from __future__ import annotations

import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

from ml_common import parsers, schema

_PARSER_BY_KIND = {
    "money": parsers.parse_money,
    "boolean": parsers.parse_bool,
    "date": parsers.parse_date,
    "zipcode": parsers.parse_zipcode,
    "categorical": parsers.normalize_text,
}


class RawRecordCleaner(BaseEstimator, TransformerMixin):
    """Applies the matching parser to each column, based on its `kind` in the schema.

    Columns not in the schema are left untouched. Columns in the schema but
    absent from the DataFrame are skipped — serving may receive a record
    missing an optional column.
    """

    def fit(self, X: pd.DataFrame, y=None) -> RawRecordCleaner:  # noqa: N803
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        result = X.copy()
        for column_name, spec in schema.COLUMNS.items():
            if column_name not in result.columns:
                continue
            parser = _PARSER_BY_KIND.get(spec.kind)
            if parser is None:
                continue
            result[column_name] = [parser(value) for value in result[column_name]]
        return result


class OutlierClipper(BaseEstimator, TransformerMixin):
    """Clips numeric values into the schema's [min_value, max_value] range.

    Clipping is chosen over dropping rows for two reasons: serving can't
    drop rows, and a house with `bedrooms = -1` still has useful information
    in its other columns. Missing values stay missing.
    """

    def fit(self, X: pd.DataFrame, y=None) -> OutlierClipper:  # noqa: N803
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        result = X.copy()
        for column_name, spec in schema.COLUMNS.items():
            if column_name not in result.columns:
                continue
            if spec.min_value is None and spec.max_value is None:
                continue
            numeric = pd.to_numeric(result[column_name], errors="coerce")
            result[column_name] = numeric.clip(lower=spec.min_value, upper=spec.max_value)
        return result


class DateFeatures(BaseEstimator, TransformerMixin):
    """Turns `listing_date` into `listing_year` + `listing_month`.

    Tree models can't use a datetime dtype directly, and year/month are two
    signals with real-world meaning (market cycles, peak season).
    """

    def fit(self, X: pd.DataFrame, y=None) -> DateFeatures:  # noqa: N803
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        result = X.copy()
        if "listing_date" not in result.columns:
            return result
        parsed = pd.to_datetime(result["listing_date"], errors="coerce")
        result["listing_year"] = parsed.dt.year
        result["listing_month"] = parsed.dt.month
        return result.drop(columns=["listing_date"])
