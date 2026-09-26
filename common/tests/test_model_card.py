import json

from ml_common.model_card import build_model_card, excluded_columns


def test_excluded_columns_match_the_leakage_rules():
    assert "list_price" in excluded_columns("regression")
    assert "list_price" not in excluded_columns("classification")
    assert "condition" in excluded_columns("classification")


def test_card_holds_threshold_data_and_limitations():
    card = build_model_card(
        model_name="house_needs_renovation_classifier",
        version="3",
        task_type="classification",
        params={"estimator": "xgboost", "decision_threshold": "0.27",
                "dataset_version": "v2", "fingerprint": "abc"},
        test_metrics={"auc": 0.71},
        group_metrics={"city": {}},
    )
    assert card["algorithm"]["decision_threshold"] == 0.27
    assert card["data"]["data_id"] == "abc"
    assert card["data"]["seed"] is None  # not logged, not guessed
    assert card["known_limitations"]
    json.dumps(card)


def test_regression_card_has_no_threshold():
    card = build_model_card(model_name="m", version="1", task_type="regression",
                            params={}, test_metrics={}, group_metrics=None)
    assert card["algorithm"]["decision_threshold"] is None
