"""Builds the target column, which the Pipeline never sees.

sklearn transformers act on X, not y, so the target arrives at fit() exactly as
raw as it was in the file. Regression reads "$450,000" from `sale_price` and
applies the same parser RawRecordCleaner would have used for that column kind.
Classification has no target column in the raw data: `needs_renovation` is
derived from `condition`.

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
        A Series with the same index — float for regression, object holding
        True/False/None for classification. Values that cannot be parsed become
        null rather than a guess, so the caller can count and drop them.

    Raises:
        ValueError: when task_type is unknown, or when the target column's kind
            has no parser registered here.

    Example:
        parse_target(pd.Series(["$450,000", "380000", "call us"]), "regression")
        # -> [450000.0, 380000.0, NaN]
        # The third row is not guessed at; rowops drops it, and the count of
        # dropped rows is logged by the prepare stage.
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


TARGET_SOURCE: dict[str, str] = {
    "regression": schema.TARGET_REGRESSION,
    "classification": "condition",
}

NEEDS_RENOVATION_CONDITIONS = frozenset({"poor", "fair"})


def derive_target(df: pd.DataFrame, task_type: str) -> pd.Series:
    """Produces the target column a model is fitted on.

    Regression reads `sale_price` straight from the data. Classification has no
    target column in the raw data at all: `needs_renovation` is derived from
    `condition`, which is why `condition` is leakage for that task. A feedback
    record (see `feedback.py`) already holds the observed `needs_renovation`;
    where that value is readable it is used as it is.

    Args:
        df: the raw DataFrame, with the source column present.
        task_type: "regression" or "classification".

    Returns:
        A Series with the same index. Values that cannot be read become null
        rather than a guess, so the caller can count and drop them.

    Raises:
        ValueError: when task_type is not one of `schema.TASK_TYPES`.
        KeyError: when the source column is absent. Silently returning nulls
            would drop every row and look like empty data instead of a bug.

    Example:
        # Classification — built from `condition`, which does not look like a
        # target at all until you see this:
        df = pd.DataFrame({"condition": ["Poor", "GOOD", "fair", "unknown"]})
        derive_target(df, "classification")
        # -> [True, False, True, None]
        #    poor and fair need renovation; "unknown" is not in the allowed set
        #    so it becomes None rather than a guess.

        # Regression — just reads and parses sale_price:
        derive_target(pd.DataFrame({"sale_price": ["$450,000"]}), "regression")
        # -> [450000.0]
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}")

    source = TARGET_SOURCE[task_type]
    if source not in df.columns:
        raise KeyError(f"missing source column {source!r} needed to build the target")

    if task_type == "regression":
        return parse_target(df[source], task_type)

    values = []
    for raw_value in df[source]:
        normalized = parsers.normalize_text(raw_value)
        if normalized is None or normalized not in schema.COLUMNS["condition"].allowed:
            values.append(None)
        else:
            values.append(normalized in NEEDS_RENOVATION_CONDITIONS)
    result = pd.Series(values, index=df.index, dtype="object")
    # Feedback records carry the observed answer itself, not a condition to
    # derive it from; where one is readable it wins.
    if schema.TARGET_CLASSIFICATION in df.columns:
        given = pd.Series(
            [parsers.parse_bool(v) for v in df[schema.TARGET_CLASSIFICATION]],
            index=df.index,
            dtype="object",
        )
        result = given.where(given.notna(), result)
    return result
