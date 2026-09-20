from datetime import UTC, datetime

import pandas as pd
import pytest

from services.agent import runner


def pool_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "property_id": ["p1", "p2", "p3"],
            "city": ["boston", "miami", "denver"],
            "property_type": ["condo", "condo", "condo"],
            "list_price": ["$400,000", "$500,000", "$300,000"],
            "sale_price": ["$420,000", "$520,000", "$310,000"],
            "condition": ["poor", "excellent", "good"],
            "bedrooms": [3, 4, 2],
        }
    )


def test_build_requests_returns_the_requested_count():
    result = runner.build_requests(pool_frame(), "none", "regression", count=2, seed=42)
    assert len(result) == 2


def test_build_requests_is_reproducible_for_a_seed():
    first = runner.build_requests(pool_frame(), "none", "regression", count=3, seed=7)
    second = runner.build_requests(pool_frame(), "none", "regression", count=3, seed=7)
    assert [r["record"]["property_id"] for r in first] == [
        r["record"]["property_id"] for r in second
    ]


def test_build_requests_strips_the_target_from_the_record():
    # A caller asking for a price obviously does not know the price.
    result = runner.build_requests(pool_frame(), "none", "regression", count=3, seed=1)
    for item in result:
        assert "sale_price" not in item["record"]


def test_build_requests_keeps_leakage_columns_in_the_record():
    # condition IS leakage for classification, but a real caller would send
    # it, and SelectColumns inside the Pipeline is what strips it. Sending it
    # exercises that guard.
    result = runner.build_requests(pool_frame(), "none", "classification", count=3, seed=1)
    assert any("condition" in item["record"] for item in result)


def test_build_requests_carries_the_true_sale_price_for_regression():
    result = runner.build_requests(pool_frame(), "none", "regression", count=3, seed=1)
    truths = sorted(item["truth"] for item in result)
    assert truths == pytest.approx([310000.0, 420000.0, 520000.0])


def test_build_requests_derives_the_true_label_for_classification():
    result = runner.build_requests(pool_frame(), "none", "classification", count=3, seed=1)
    by_id = {item["record"]["property_id"]: item["truth"] for item in result}
    assert by_id["p1"] is True      # condition poor -> needs renovation
    assert by_id["p2"] is False     # excellent
    assert by_id["p3"] is False     # good


def test_build_requests_inflation_moves_the_price_but_not_the_truth():
    result = runner.build_requests(
        pool_frame(), "price_inflation", "regression", count=3, seed=1
    )
    by_id = {item["record"]["property_id"]: item for item in result}
    assert by_id["p1"]["record"]["list_price"] == pytest.approx(480000.0)
    assert by_id["p1"]["truth"] == pytest.approx(420000.0)


def test_build_requests_rally_moves_both():
    result = runner.build_requests(pool_frame(), "market_rally", "regression", count=3, seed=1)
    by_id = {item["record"]["property_id"]: item for item in result}
    assert by_id["p1"]["record"]["list_price"] == pytest.approx(480000.0)
    assert by_id["p1"]["truth"] == pytest.approx(504000.0)


def test_build_requests_drops_rows_whose_truth_cannot_be_read():
    pool = pool_frame()
    pool.loc[0, "sale_price"] = "call for price"
    result = runner.build_requests(pool, "none", "regression", count=3, seed=1)
    assert all(item["record"]["property_id"] != "p1" for item in result)


def test_build_requests_on_empty_pool_returns_empty():
    empty = pool_frame().iloc[0:0]
    assert runner.build_requests(empty, "none", "regression", count=5, seed=1) == []


class FakePost:
    """Records calls instead of making them."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, json):
        self.calls.append((url, json))
        return self.responses.pop(0)


def test_send_predictions_posts_one_record_at_a_time():
    post = FakePost(
        [
            {"request_id": "r1", "prediction": 1.0},
            {"request_id": "r2", "prediction": 2.0},
        ]
    )
    requests = [{"record": {"a": 1}, "truth": 10.0}, {"record": {"a": 2}, "truth": 20.0}]

    result = runner.send_predictions(post, "http://serving:8000", "regression", requests)

    assert [url for url, _ in post.calls] == ["http://serving:8000/predict/regression"] * 2
    assert [item["request_id"] for item in result] == ["r1", "r2"]


def test_send_predictions_pairs_each_response_with_its_truth():
    post = FakePost([{"request_id": "r1", "prediction": 1.0}])
    requests = [{"record": {"a": 1}, "truth": 99.0}]

    result = runner.send_predictions(post, "http://serving:8000", "regression", requests)

    assert result[0]["actual"] == 99.0


def test_send_predictions_stamps_the_day_it_called():
    post = FakePost([{"request_id": "r1", "prediction": 1.0}])
    requests = [{"record": {"a": 1}, "truth": 99.0}]

    result = runner.send_predictions(
        post, "http://serving:8000", "regression", requests, now=datetime(2026, 9, 20, tzinfo=UTC)
    )

    assert result[0]["predicted_on"] == "2026-09-20"


def test_send_feedback_sends_one_batch_with_only_the_needed_fields():
    post = FakePost([{"accepted": 2}])
    outcomes = [
        {"request_id": "r1", "predicted_on": "2026-09-20", "actual": 1.0, "extra": "drop me"},
        {"request_id": "r2", "predicted_on": "2026-09-20", "actual": 2.0, "extra": "drop me"},
    ]

    runner.send_feedback(post, "http://serving:8000", "regression", outcomes)

    assert len(post.calls) == 1
    url, body = post.calls[0]
    assert url == "http://serving:8000/feedback/regression"
    assert body["outcomes"] == [
        {"request_id": "r1", "predicted_on": "2026-09-20", "actual": 1.0},
        {"request_id": "r2", "predicted_on": "2026-09-20", "actual": 2.0},
    ]


def test_send_feedback_with_nothing_to_report_makes_no_call():
    post = FakePost([])
    result = runner.send_feedback(post, "http://serving:8000", "regression", [])
    assert post.calls == []
    assert result == {"accepted": 0}
