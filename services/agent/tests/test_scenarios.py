import pytest

from services.agent import scenarios


def base_record() -> dict:
    return {
        "property_id": "p1",
        "city": "boston",
        "property_type": "condo",
        "list_price": 400000.0,
        "bedrooms": 3,
    }


def test_none_changes_nothing():
    record = base_record()
    assert scenarios.apply_scenario(record, "none") == record


def test_apply_scenario_does_not_mutate_the_caller_s_record():
    record = base_record()
    scenarios.apply_scenario(record, "price_inflation")
    assert record["list_price"] == 400000.0


def test_price_inflation_raises_the_asking_price():
    result = scenarios.apply_scenario(base_record(), "price_inflation")
    assert result["list_price"] == pytest.approx(480000.0)


def test_market_rally_raises_the_asking_price_the_same_way():
    result = scenarios.apply_scenario(base_record(), "market_rally")
    assert result["list_price"] == pytest.approx(480000.0)


def test_market_shift_moves_the_city():
    result = scenarios.apply_scenario(base_record(), "market_shift")
    assert result["city"] in scenarios.SHIFT_CITIES
    assert result["city"] != "boston"


def test_new_segment_uses_a_property_type_the_model_never_saw():
    from ml_common import schema

    result = scenarios.apply_scenario(base_record(), "new_segment")
    allowed = schema.COLUMNS["property_type"].allowed
    assert result["property_type"] not in allowed


def test_unknown_scenario_is_rejected():
    with pytest.raises(ValueError, match="scenario"):
        scenarios.apply_scenario(base_record(), "nonsense")


def test_price_inflation_leaves_the_true_sale_price_alone():
    # The whole point: asking prices are inflated but houses still sell for
    # what they were always worth, so the model is misled.
    assert scenarios.adjust_truth(420000.0, "price_inflation", "regression") == 420000.0


def test_market_rally_lifts_the_true_sale_price_too():
    # The market really did move, so the model stays roughly right.
    assert scenarios.adjust_truth(420000.0, "market_rally", "regression") == pytest.approx(504000.0)


def test_none_leaves_the_truth_alone():
    assert scenarios.adjust_truth(420000.0, "none", "regression") == 420000.0


def test_truth_is_never_scaled_for_classification():
    # needs_renovation is a bool. Multiplying it by 1.2 is meaningless.
    assert scenarios.adjust_truth(True, "market_rally", "classification") is True
    assert scenarios.adjust_truth(False, "price_inflation", "classification") is False


def test_record_missing_the_distorted_column_is_left_alone():
    # Serving accepts records with optional columns missing; the agent must
    # not invent a list_price that was never there.
    record = {"property_id": "p1", "city": "boston"}
    result = scenarios.apply_scenario(record, "price_inflation")
    assert "list_price" not in result


def test_unparseable_price_is_left_alone_rather_than_guessed():
    record = {"property_id": "p1", "list_price": "call for price"}
    result = scenarios.apply_scenario(record, "price_inflation")
    assert result["list_price"] == "call for price"


def test_currency_string_price_is_still_inflated():
    # The raw data mixes plain numbers with currency strings; both must drift.
    record = {"property_id": "p1", "list_price": "$400,000"}
    result = scenarios.apply_scenario(record, "price_inflation")
    assert result["list_price"] == pytest.approx(480000.0)
