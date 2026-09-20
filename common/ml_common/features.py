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

    Example:
        step = SelectColumns(["bedrooms", "city"])
        step.transform(pd.DataFrame([{"city": "boston", "sale_price": 1}]))
        # -> one row, columns exactly ["bedrooms", "city"]:
        #    bedrooms is None (the caller omitted it),
        #    sale_price is gone (leakage, even though it was sent).
    """

    def __init__(self, columns: list[str]):
        """Records which columns to keep.

        Args:
            columns: the exact column names to emit, in the order wanted. Stored
                unchanged so sklearn's `get_params` can round-trip the step.
        """
        self.columns = columns

    def fit(self, X, y=None):  # noqa: N803
        """Learns nothing — the column list was fixed at construction.

        Args:
            X: ignored; present because sklearn requires the signature.
            y: ignored, same reason.

        Returns:
            self, so the step can be chained inside a Pipeline.
        """
        return self

    def transform(self, X):  # noqa: N803
        """Emits exactly the configured columns, in the configured order.

        Args:
            X: a DataFrame that may be missing wanted columns or carrying extra ones.

        Returns:
            A new DataFrame with the same index and exactly `self.columns`.
            Wanted columns absent from X are added holding None; columns not
            wanted are dropped, which is what strips leakage at serving time.
        """
        result = X.copy()
        for column_name in self.columns:
            if column_name not in result.columns:
                result[column_name] = None
        return result[self.columns]


def _numeric_and_categorical_columns(task_type: str) -> tuple[list[str], list[str]]:
    """Splits features into numeric and categorical groups, AFTER DateFeatures has run.

    Args:
        task_type: "regression" or "classification"; decides which columns count
            as features at all.

    Returns:
        A tuple of (numeric column names, categorical column names). Booleans go
        with the numerics because One-Hot would waste two columns on True/False.
        `listing_date` appears in neither: by the time this list is used, it has
        become `listing_year` and `listing_month`, which are in the numeric group.

    Example:
        numeric, categorical = _numeric_and_categorical_columns("regression")
        # numeric     -> [..., "bedrooms", "has_pool", "listing_year", "listing_month"]
        # categorical -> ["city", "state", "zipcode", "property_type", "condition"]
        # zipcode is categorical on purpose: 94107 is a place, not a quantity.
    """
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
        An unfitted Pipeline whose `fit` and `predict` both accept a RAW
        DataFrame — money still written "$450,000", city still "  NEW YORK ".
        That is what makes the object logged to MLflow safe to serve directly.

    Raises:
        ValueError: when task_type is not one of `schema.TASK_TYPES`.

    Example:
        # Train — fit on raw columns, then log the WHOLE pipeline:
        pipeline = build_pipeline("regression", build_estimator("regression", "ridge"))
        pipeline.fit(train_df.drop(columns=["sale_price"]), train_df["sale_price"])
        mlflow.sklearn.log_model(pipeline, artifact_path="model")

        # Serving — the same object, handed a raw record and nothing else:
        pipeline.predict(pd.DataFrame([{
            "list_price": "$450,000",   # still a currency string
            "city": "  NEW YORK ",      # still unnormalized
            "listing_date": "09/20/2026",
        }]))
        # -> array([487312.5])
        # No cleaning happens on the serving side. That is the whole design.
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
