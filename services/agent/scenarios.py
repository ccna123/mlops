"""The five market scenarios the agent can simulate.

Every scenario starts from a REAL row of the dataset and distorts it. That
keeps the relationships between columns believable - a generated house with
twenty bedrooms and thirty square metres would produce drift that means
nothing.

The interesting pair is `price_inflation` and `market_rally`. Both multiply
the asking price by the same factor; they differ only in whether the true
sale price moves with it, and that design is still right. But
`schema.feature_columns("regression")` excludes `list_price` as leakage, so
neither scenario's perturbation ever reaches the regression model's input -
`SelectColumns` strips it before the model or the drift comparison sees it.
`price_inflation` therefore changes nothing the model can see: a useful
negative result, since drift in a column the model never reads is not drift
that matters. `market_rally` moves the true sale price without moving the
prediction, so it fires performance drift with zero feature drift.
`market_shift` is the scenario that actually exercises feature drift,
because `city` - unlike `list_price` - IS a regression feature.

Pure functions on dicts: no HTTP, no pandas, no config.
"""

from __future__ import annotations

from ml_common.parsers import parse_money

SCENARIOS = (
    "none",
    "price_inflation",
    "market_rally",
    "market_shift",
    "new_segment",
)

PRICE_FACTOR = 1.2

# Somewhere the training data barely covers, so concentrating traffic here
# genuinely shifts the city distribution.
SHIFT_CITIES = ("phoenix",)

# Deliberately absent from schema.COLUMNS["property_type"].allowed. Serving
# must survive it: the OneHotEncoder was built with
# handle_unknown="infrequent_if_exist" for exactly this.
NEW_PROPERTY_TYPE = "floating home"

# Scenarios that move the true outcome along with the features. Only these
# simulate a market that really rose, as opposed to sellers merely asking
# for more.
_TRUTH_SCALED = {"market_rally": PRICE_FACTOR}


def _check_scenario(scenario: str) -> None:
    """Rejects a scenario name that does not exist.

    Args:
        scenario: the name to check.

    Returns:
        Nothing when the name is valid.

    Raises:
        ValueError: otherwise. A typo must not silently become "no distortion
            at all", which would look like a clean run rather than a mistake.

    Example:
        _check_scenario("market_rally")  # -> None
        _check_scenario("market_raly")   # -> ValueError
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}, got: {scenario!r}")


def apply_scenario(record: dict, scenario: str) -> dict:
    """Distorts one raw record the way a scenario says the market has moved.

    Args:
        record: a raw record as it would be POSTed to /predict. Not modified;
            a new dict is returned.
        scenario: one of SCENARIOS.

    Returns:
        A new record. A column the scenario targets but the record does not
        have is left absent rather than invented, and a price that cannot be
        read as a number is left exactly as it was - the same refusal to
        guess that the parsers make.

    Raises:
        ValueError: when the scenario name is unknown.

    Example:
        apply_scenario({"list_price": "$400,000"}, "price_inflation")
        # -> {"list_price": 480000.0}

        apply_scenario({"city": "boston"}, "market_shift")
        # -> {"city": "phoenix"}

        apply_scenario({"property_type": "condo"}, "new_segment")
        # -> {"property_type": "floating home"}, a value never trained on
    """
    _check_scenario(scenario)
    result = dict(record)

    if scenario in ("price_inflation", "market_rally") and "list_price" in result:
        amount = parse_money(result["list_price"])
        if amount is not None:
            result["list_price"] = amount * PRICE_FACTOR

    if scenario == "market_shift" and "city" in result:
        result["city"] = SHIFT_CITIES[0]

    if scenario == "new_segment" and "property_type" in result:
        result["property_type"] = NEW_PROPERTY_TYPE

    return result


def adjust_truth(actual, scenario: str, task_type: str):
    """Moves the true outcome to stay consistent with a scenario, if it should.

    Args:
        actual: the real outcome from the dataset row - a sale price for
            regression, a bool for classification.
        scenario: one of SCENARIOS.
        task_type: "regression" or "classification".

    Returns:
        For `market_rally` on regression, the price scaled by PRICE_FACTOR:
        the market really did rise, but `list_price` (the only column either
        scenario perturbs) is excluded from the regression model's features,
        so the prediction never follows it - performance drift fires because
        the truth moved and the model did not. For everything else the value
        is unchanged - under `price_inflation` this makes no difference to
        the model either way, since it never sees the inflated `list_price`
        at all. Classification truth is never scaled, because a bool has
        nothing to scale.

    Raises:
        ValueError: when the scenario name is unknown.

    Example:
        adjust_truth(420000.0, "price_inflation", "regression")  # -> 420000.0
        adjust_truth(420000.0, "market_rally", "regression")     # -> 504000.0
        adjust_truth(True, "market_rally", "classification")     # -> True
    """
    _check_scenario(scenario)
    if task_type != "regression":
        return actual
    factor = _TRUTH_SCALED.get(scenario)
    if factor is None:
        return actual
    return actual * factor
