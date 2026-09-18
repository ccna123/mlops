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
    """Converts a numpy value to a Python float, NaN to None."""
    if value is None or pd.isna(value):
        return None
    return float(value)


def _profile_numeric_column(series: pd.Series, n_bins: int) -> dict:
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
        A dict serializable by json.dumps — see the Interfaces section for its shape.
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
