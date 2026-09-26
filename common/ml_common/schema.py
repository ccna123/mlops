"""Single source of truth for the house pricing dataset schema.

Used by the `validate` stage (checking raw data) and by serving (checking
records sent to /predict). Does not import pandas at module level, so this
file stays lightweight and importable from anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

TARGET_REGRESSION = "sale_price"
TARGET_CLASSIFICATION = "needs_renovation"
ID_COLUMN = "property_id"

TASK_TYPES = ("regression", "classification")

# The registered model of each task. The DAGs keep their own copy (the Airflow
# image has no ml_common); everything that can import this reads it from here.
MODEL_NAMES = {
    "regression": "house_price_regressor",
    "classification": "house_needs_renovation_classifier",
}


@dataclass(frozen=True)
class ColumnSpec:
    """Describes one column: its logical data kind and valid-value constraints.

    Frozen, so a spec cannot be edited by accident at runtime — every consumer
    reads the same COLUMNS map.

    Example:
        spec = COLUMNS["bedrooms"]
        # -> ColumnSpec(name="bedrooms", kind="numeric", required=False,
        #               min_value=0, max_value=20, allowed=None)

        # `kind` picks the parser in cleaning.py, min/max drive OutlierClipper
        # and the out-of-bounds count in validation.py, and `allowed` is the
        # value set derive_target checks `condition` against.
    """

    name: str
    kind: str
    required: bool = False
    min_value: float | None = None
    max_value: float | None = None
    allowed: tuple[str, ...] | None = None


_CURRENT_YEAR = date.today().year

_SPECS = [
    ColumnSpec("property_id", "id", required=True),
    ColumnSpec("listing_date", "date"),
    ColumnSpec("city", "categorical"),
    ColumnSpec("state", "categorical"),
    ColumnSpec("zipcode", "zipcode"),
    ColumnSpec(
        "property_type",
        "categorical",
        allowed=("single family", "condo", "townhouse", "multi family", "land"),
    ),
    ColumnSpec("lot_size_sqft", "numeric", min_value=0, max_value=1_000_000),
    ColumnSpec("living_area_sqft", "numeric", min_value=0, max_value=50_000),
    ColumnSpec("bedrooms", "numeric", min_value=0, max_value=20),
    ColumnSpec("bathrooms", "numeric", min_value=0, max_value=15),
    ColumnSpec("year_built", "numeric", min_value=1800, max_value=_CURRENT_YEAR),
    ColumnSpec("stories", "numeric", min_value=0, max_value=5),
    ColumnSpec("garage_spaces", "numeric", min_value=0, max_value=6),
    ColumnSpec("has_pool", "boolean"),
    ColumnSpec("hoa_fee_monthly", "numeric", min_value=0, max_value=5_000),
    ColumnSpec("school_rating", "numeric", min_value=1, max_value=10),
    ColumnSpec("crime_index", "numeric", min_value=0, max_value=100),
    ColumnSpec("distance_to_city_center_km", "numeric", min_value=0, max_value=200),
    ColumnSpec(
        "condition",
        "categorical",
        allowed=("poor", "fair", "good", "excellent"),
    ),
    ColumnSpec("days_on_market", "numeric", min_value=0, max_value=3_650),
    ColumnSpec("list_price", "money", min_value=0),
    ColumnSpec("sale_price", "money", min_value=0),
    ColumnSpec(
        "price_category",
        "categorical",
        allowed=("low", "medium", "high", "luxury"),
    ),
    ColumnSpec("sold_within_30_days", "boolean"),
]

COLUMNS: dict[str, ColumnSpec] = {spec.name: spec for spec in _SPECS}

# Columns excluded from features, per task. See section 5 of the design doc
# for the reasoning behind each one.
_EXCLUDED: dict[str, frozenset[str]] = {
    "regression": frozenset(
        {
            ID_COLUMN,
            TARGET_REGRESSION,
            "price_category",  # derived directly from sale_price
            "list_price",  # temporally valid but makes the task trivial
        }
    ),
    "classification": frozenset(
        {
            ID_COLUMN,
            "condition",  # the column needs_renovation is derived from
            "sale_price",  # only known after the sale
            "days_on_market",  # only known after the sale
            "sold_within_30_days",  # only known after the sale
            "price_category",  # derived from sale_price
        }
    ),
}


def feature_columns(task_type: str) -> list[str]:
    """Lists the columns usable as features for a task.

    Args:
        task_type: "regression" or "classification".

    Returns:
        Column names in declaration order, with the id, the target and every
        leakage column for that task already removed.

    Raises:
        ValueError: when task_type is not one of TASK_TYPES.

    Example:
        feature_columns("regression")
        # -> [..., "condition", "days_on_market", "sold_within_30_days", ...]
        #    but NOT sale_price, list_price, price_category or property_id

        feature_columns("classification")
        # -> condition is gone too: needs_renovation is derived FROM it,
        #    so keeping it would hand the model the answer
    """
    if task_type not in TASK_TYPES:
        raise ValueError(f"task_type must be one of {TASK_TYPES}, got: {task_type!r}")
    excluded = _EXCLUDED[task_type]
    return [name for name in COLUMNS if name not in excluded]


def columns_of_kind(kind: str) -> list[str]:
    """Lists the columns of one logical kind.

    Args:
        kind: a ColumnSpec kind — "id", "date", "categorical", "zipcode",
            "numeric", "money" or "boolean".

    Returns:
        Column names in declaration order. An unknown kind returns an empty
        list rather than raising: asking which columns are of a kind nobody
        declared has a correct answer, and it is "none".

    Example:
        columns_of_kind("money")     # -> ["list_price", "sale_price"]
        columns_of_kind("boolean")   # -> ["has_pool", "sold_within_30_days"]
        columns_of_kind("zipcode")   # -> ["zipcode"]
        columns_of_kind("nonsense")  # -> []
    """
    return [name for name, spec in COLUMNS.items() if spec.kind == kind]


def target_column(task_type: str) -> str:
    """Names the target column for a task.

    Args:
        task_type: "regression" or "classification".

    Returns:
        "sale_price" for regression, "needs_renovation" for classification.
        The classification target does not exist in the raw data — it is built
        by `targets.derive_target`.

    Raises:
        ValueError: when task_type is not one of TASK_TYPES.

    Example:
        target_column("regression")      # -> "sale_price"
        target_column("classification")  # -> "needs_renovation"

        # The usual reason to call it — split X from y without hardcoding a name:
        target = target_column(task_type)
        features, y = train_df.drop(columns=[target]), train_df[target]
    """
    if task_type not in TASK_TYPES:
        raise ValueError(f"task_type must be one of {TASK_TYPES}, got: {task_type!r}")
    return TARGET_REGRESSION if task_type == "regression" else TARGET_CLASSIFICATION
