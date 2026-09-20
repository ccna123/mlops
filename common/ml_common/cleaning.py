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

    Example:
        RawRecordCleaner().transform(pd.DataFrame([{
            "list_price": "$450,000",
            "city": "NEW_YORK",
            "has_pool": "Yes",
            "listing_date": "09/20/2026",
            "note": "kept as-is",       # not in the schema
        }]))
        # -> list_price   450000.0
        #    city         "new york"
        #    has_pool     True
        #    listing_date date(2026, 9, 20)
        #    note         "kept as-is"
    """

    def fit(self, X: pd.DataFrame, y=None) -> RawRecordCleaner:  # noqa: N803
        """Learns nothing — the parsers are fixed by the schema.

        Args:
            X: ignored; present because sklearn requires the signature.
            y: ignored, same reason.

        Returns:
            self, so the step can be chained inside a Pipeline.
        """
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        """Parses every column the schema knows a parser for.

        Args:
            X: a DataFrame of raw values — 2 million rows at train time, one row
                at serving time.

        Returns:
            A new DataFrame with the same index and the same columns. Values
            that could not be parsed become None; columns outside the schema and
            columns absent from X are left exactly as they are.
        """
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

    Example:
        # bedrooms is declared min_value=0, max_value=20:
        OutlierClipper().transform(pd.DataFrame({"bedrooms": [-1, 3, 999, None]}))
        # -> [0.0, 3.0, 20.0, NaN]
        # The -1 row is NOT dropped. Its other columns still carry signal, and
        # serving could never drop a row anyway.
    """

    def fit(self, X: pd.DataFrame, y=None) -> OutlierClipper:  # noqa: N803
        """Learns nothing — the bounds come from the schema, not from the data.

        Args:
            X: ignored; present because sklearn requires the signature.
            y: ignored, same reason.

        Returns:
            self, so the step can be chained inside a Pipeline.
        """
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        """Clips every bounded numeric column into its schema range.

        Args:
            X: a DataFrame, usually already parsed by `RawRecordCleaner`.

        Returns:
            A new DataFrame with the same index and columns. Bounded columns
            come back numeric with out-of-range values pulled to the nearest
            bound; anything unreadable as a number becomes NaN. Columns with no
            bounds in the schema are left as they are.
        """
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

    Example:
        DateFeatures().transform(pd.DataFrame({"listing_date": ["2026-09-20", None]}))
        # -> listing_date is GONE; listing_year [2026, NaN], listing_month [9, NaN]

        # A frame with no listing_date at all comes back untouched, so the step
        # is safe on a serving record that omitted the field.
    """

    def fit(self, X: pd.DataFrame, y=None) -> DateFeatures:  # noqa: N803
        """Learns nothing — the two features are derived per row.

        Args:
            X: ignored; present because sklearn requires the signature.
            y: ignored, same reason.

        Returns:
            self, so the step can be chained inside a Pipeline.
        """
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        """Replaces `listing_date` with `listing_year` and `listing_month`.

        Args:
            X: a DataFrame that may or may not carry a `listing_date` column.

        Returns:
            A new DataFrame with the same index. When `listing_date` is present
            it is dropped and the two integer columns take its place, holding
            NaN for a date that could not be read. When it is absent, X comes
            back unchanged.
        """
        result = X.copy()
        if "listing_date" not in result.columns:
            return result
        parsed = pd.to_datetime(result["listing_date"], errors="coerce")
        result["listing_year"] = parsed.dt.year
        result["listing_month"] = parsed.dt.month
        return result.drop(columns=["listing_date"])
