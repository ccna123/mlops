"""Parses the target column, which the Pipeline never sees.

sklearn transformers act on X, not y, so the target arrives at fit() exactly as
raw as it was in the file: "$450,000" for regression, "Y" for classification.
This module applies the same parser RawRecordCleaner would have used for that
column kind.

Doing this outside the Pipeline is safe in a way that cleaning a FEATURE would
not be: serving has no target — it is the thing being asked for — so there is no
second code path this could drift from.
"""

from __future__ import annotations

import pandas as pd

from . import parsers, schema

_PARSER_BY_KIND = {
    "money": parsers.parse_money,
    "boolean": parsers.parse_bool,
}


def parse_target(series: pd.Series, task_type: str) -> pd.Series:
    """Converts a raw target column into values a model can be fitted on.

    Args:
        series: the raw target column.
        task_type: "regression" or "classification".

    Returns:
        A Series with the same index. Values that cannot be parsed become null
        rather than a guess, so the caller can count and drop them.
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}")

    target_name = schema.target_column(task_type)
    kind = schema.COLUMNS[target_name].kind
    parser = _PARSER_BY_KIND.get(kind)
    if parser is None:
        raise ValueError(f"no target parser for column {target_name!r} of kind {kind!r}")

    parsed = pd.Series([parser(value) for value in series], index=series.index)
    if kind == "money":
        return pd.to_numeric(parsed, errors="coerce")
    return parsed
