"""Computes the statistical profile of a DataFrame — used as a drift baseline.

The `register` stage calls this on the train set of a newly promoted model,
then writes the result to monitoring-baseline/{model}/{version}/profile.json.
This keeps the baseline tied to the exact model version that used it.

The result must be serializable by plain `json.dumps`, so every numpy type
is converted back to a native Python type.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from ml_common import schema

_NUMERIC_KINDS = {"numeric", "money", "boolean"}


def _to_float(value) -> float | None:
    """Converts a numpy scalar to something json.dumps can write.

    Args:
        value: a numpy or Python number, possibly NaN or None.

    Returns:
        A plain Python float, or None for a missing value — JSON has no NaN.

    Example:
        _to_float(np.float64(3.5))  # -> 3.5, a plain float json.dumps accepts
        _to_float(np.nan)           # -> None
        _to_float(None)             # -> None
    """
    if value is None or pd.isna(value):
        return None
    return float(value)


def _profile_numeric_column(series: pd.Series, n_bins: int) -> dict:
    """Summarizes one numeric column as a drift baseline.

    Args:
        series: the column. Values that cannot be read as numbers are treated
            as missing rather than dropped silently — they raise missing_rate.
        n_bins: number of histogram bins.

    Returns:
        A JSON-serializable dict with kind, missing_rate, mean, std, min, max,
        the p25/p50/p75 quantiles and a histogram. An all-missing column comes
        back with None statistics and an empty histogram, not an exception.

    Example:
        _profile_numeric_column(pd.Series([1.0, 2.0, 3.0, None]), n_bins=2)
        # -> {"kind": "numeric", "missing_rate": 0.25, "mean": 2.0, "std": 1.0,
        #     "min": 1.0, "max": 3.0,
        #     "quantiles": {"p25": 1.5, "p50": 2.0, "p75": 2.5},
        #     "histogram": {"bin_edges": [1.0, 2.0, 3.0], "counts": [1, 2]}}
    """
    valid = pd.to_numeric(series, errors="coerce").dropna()
    result: dict = {
        "kind": "numeric",
        "missing_rate": float(1 - len(valid) / len(series)) if len(series) else 1.0,
        "mean": _to_float(valid.mean()) if len(valid) else None,
        "std": _to_float(valid.std()) if len(valid) else None,
        "min": _to_float(valid.min()) if len(valid) else None,
        "max": _to_float(valid.max()) if len(valid) else None,
        "quantiles": {
            "p25": _to_float(valid.quantile(0.25)) if len(valid) else None,
            "p50": _to_float(valid.quantile(0.50)) if len(valid) else None,
            "p75": _to_float(valid.quantile(0.75)) if len(valid) else None,
        },
        "histogram": {"bin_edges": [], "counts": []},
    }
    if len(valid):
        counts, bin_edges = np.histogram(valid, bins=n_bins)
        result["histogram"] = {
            "bin_edges": [float(x) for x in bin_edges],
            "counts": [int(x) for x in counts],
        }
    return result


def _profile_categorical_column(series: pd.Series) -> dict:
    """Summarizes one categorical column as a drift baseline.

    Args:
        series: the column, already normalized by the cleaning transformers.

    Returns:
        A JSON-serializable dict with kind, missing_rate, n_unique and
        `distribution` — the share of each value, as fractions summing to 1.
        An all-missing column comes back with an empty distribution.

    Example:
        _profile_categorical_column(pd.Series(["boston", "boston", "miami", None]))
        # -> {"kind": "categorical", "missing_rate": 0.25, "n_unique": 2,
        #     "distribution": {"boston": 0.666..., "miami": 0.333...}}
        # Shares are of the NON-missing values, which is why they sum to 1
        # even though a quarter of the column is missing.
    """
    valid = series.dropna()
    distribution = (
        {str(k): float(v) for k, v in valid.value_counts(normalize=True).items()}
        if len(valid)
        else {}
    )
    return {
        "kind": "categorical",
        "missing_rate": float(1 - len(valid) / len(series)) if len(series) else 1.0,
        "n_unique": int(valid.nunique()),
        "distribution": distribution,
    }


def compute_profile(df: pd.DataFrame, columns: list[str], n_bins: int = 20) -> dict:
    """Computes the statistical profile for the given columns.

    Args:
        df: cleaned DataFrame.
        columns: list of columns to profile. Columns missing from df are skipped.
        n_bins: number of histogram bins for numeric columns.

    Returns:
        A dict serializable by json.dumps, holding `n_rows`, `computed_at` (UTC
        ISO-8601) and `columns` — one entry per profiled column, numeric or
        categorical depending on its schema kind. See the Interfaces section of
        the design doc for the full shape.

    Example:
        # What the register stage does after promoting a model — profile the
        # TRAIN split, so Plan 4 compares live traffic against what the model
        # actually learned from:
        profile = compute_profile(train_df, schema.feature_columns("regression"))
        storage.write_json(profile, baseline_key(model_name, version))
        # profile -> {"n_rows": 160000, "computed_at": "2026-09-20T09:14:22+00:00",
        #             "columns": {"bedrooms": {...}, "city": {...}}}
    """
    column_profiles: dict[str, dict] = {}
    for column_name in columns:
        if column_name not in df.columns:
            continue
        spec = schema.COLUMNS.get(column_name)
        is_numeric = (
            spec.kind in _NUMERIC_KINDS if spec else pd.api.types.is_numeric_dtype(df[column_name])
        )
        if is_numeric:
            column_profiles[column_name] = _profile_numeric_column(df[column_name], n_bins)
        else:
            column_profiles[column_name] = _profile_categorical_column(df[column_name])

    return {
        "n_rows": int(len(df)),
        "computed_at": datetime.now(UTC).isoformat(),
        "columns": column_profiles,
    }
