"""Builds the complete sklearn Pipeline for each task.

The Pipeline returned here gets logged whole into MLflow at the `train`
stage, so it must SELF-CONTAIN all cleaning logic: the model in the
Registry receives a RAW record and handles it itself. This is the guard
against training/serving skew — see section 7.1 of the design doc.
"""

from __future__ import annotations

from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml_common import schema
from ml_common.cleaning import DateFeatures, OutlierClipper, RawRecordCleaner


class SelectColumns(BaseEstimator, TransformerMixin):
    """Keeps exactly the given list of columns, in that order.

    Missing columns are added with value None. This keeps serving from
    crashing when a caller omits an optional column, and strips leakage
    columns even if a caller sends them.
    """

    def __init__(self, columns: list[str]):
        self.columns = columns

    def fit(self, X, y=None):  # noqa: N803
        return self

    def transform(self, X):  # noqa: N803
        result = X.copy()
        for column_name in self.columns:
            if column_name not in result.columns:
                result[column_name] = None
        return result[self.columns]


def _numeric_and_categorical_columns(task_type: str) -> tuple[list[str], list[str]]:
    """Splits features into numeric and categorical groups, AFTER DateFeatures has run."""
    feature = schema.feature_columns(task_type)
    numeric_columns: list[str] = []
    categorical_columns: list[str] = []
    for column_name in feature:
        if column_name == "listing_date":
            continue  # already turned into listing_year / listing_month
        spec = schema.COLUMNS[column_name]
        if spec.kind in ("numeric", "money"):
            numeric_columns.append(column_name)
        elif spec.kind == "boolean":
            numeric_columns.append(column_name)  # True/False -> 1/0
        else:  # categorical, zipcode
            categorical_columns.append(column_name)
    if "listing_date" in feature:
        numeric_columns.extend(["listing_year", "listing_month"])
    return numeric_columns, categorical_columns


def build_pipeline(task_type: str, estimator) -> Pipeline:
    """Builds the full Pipeline: clean -> select columns -> encode -> model.

    Args:
        task_type: "regression" or "classification".
        estimator: an already-initialized sklearn estimator.

    Returns:
        A Pipeline that accepts a RAW DataFrame as input.
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(
            f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}"
        )

    numeric_columns, categorical_columns = _numeric_and_categorical_columns(task_type)

    numeric_branch = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]
    )
    categorical_branch = Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            # handle_unknown="infrequent_if_exist" keeps serving from crashing
            # on a value it has never seen (agent drift_scenario=new_segment).
            (
                "encode",
                OneHotEncoder(
                    handle_unknown="infrequent_if_exist",
                    min_frequency=0.01,
                    sparse_output=False,
                ),
            ),
        ]
    )

    encoder = ColumnTransformer(
        [
            ("numeric", numeric_branch, numeric_columns),
            ("categorical", categorical_branch, categorical_columns),
        ],
        remainder="drop",
    )

    return Pipeline(
        [
            ("clean", RawRecordCleaner()),
            ("clip_outlier", OutlierClipper()),
            ("date_features", DateFeatures()),
            ("select_columns", SelectColumns(numeric_columns + categorical_columns)),
            ("encode", encoder),
            ("model", estimator),
        ]
    )
