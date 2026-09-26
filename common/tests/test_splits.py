from datetime import date, timedelta

import pandas as pd
import pytest

from ml_common import splits


def _listing_frame(days: list[str | None], ids: list[str] | None = None) -> pd.DataFrame:
    ids = ids or [f"p{i}" for i in range(len(days))]
    return pd.DataFrame({"property_id": ids, "listing_date": days})


def _daily_dates(count: int, start: str = "2020-01-01") -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(start, periods=count, freq="D")]


class TestEventDates:
    def test_parses_all_three_listing_formats(self):
        frame = _listing_frame(["2023-07-15", "07/16/2023", "17-Jul-2023", "garbage", None])
        result = splits.event_dates(frame)
        assert list(result[:3]) == [date(2023, 7, 15), date(2023, 7, 16), date(2023, 7, 17)]
        assert result[3] is None and result[4] is None

    def test_feedback_records_use_prediction_time_not_listing_date(self):
        frame = pd.DataFrame(
            {
                "property_id": ["p1", "p2"],
                "listing_date": ["2020-01-01", "2020-01-01"],
                splits.SOURCE_COLUMN: [splits.SOURCE_ORIGINAL, splits.SOURCE_FEEDBACK],
                splits.PREDICTED_AT_COLUMN: [None, "2026-09-20T10:00:00+00:00"],
            }
        )
        result = splits.event_dates(frame)
        assert list(result) == [date(2020, 1, 1), date(2026, 9, 20)]

    def test_frame_without_source_column_is_all_original(self):
        result = splits.record_sources(_listing_frame(["2020-01-01"]))
        assert list(result) == [splits.SOURCE_ORIGINAL]


class TestComputeSplitPoints:
    def test_simulation_is_capped_at_ten_percent(self):
        dates = pd.Series(_daily_dates(1000))
        rule = splits.compute_split_points(pd.Series(splits.parse_dates(dates)))
        frame = _listing_frame(list(dates))
        assigned = splits.assign_split(frame, {splits.SOURCE_ORIGINAL: rule})
        assert (assigned == "simulation").sum() == 100
        # test is ~20% of what lies before T2
        assert (assigned == "test").sum() == 180
        assert (assigned == "train").sum() == 720

    def test_simulation_targets_twenty_thousand_on_large_data(self):
        dates = pd.Series([date(1200, 1, 1) + timedelta(days=i) for i in range(300_000)])
        rule = splits.compute_split_points(dates)
        sim = (dates >= date.fromisoformat(rule["t2"])).sum()
        assert sim == splits.SIMULATION_TARGET_ROWS

    def test_ignores_undated_records(self):
        dates = pd.Series(splits.parse_dates(pd.Series(_daily_dates(100) + [None] * 50)))
        rule = splits.compute_split_points(dates)
        assert rule["t1"] < rule["t2"]

    def test_no_dated_record_raises(self):
        with pytest.raises(ValueError, match="listing date"):
            splits.compute_split_points(pd.Series([None, None], dtype=object))

    def test_rule_is_json_friendly(self):
        dates = pd.Series(splits.parse_dates(pd.Series(_daily_dates(50))))
        rule = splits.compute_split_points(dates)
        assert isinstance(rule["t1"], str) and isinstance(rule["t2"], str)
        assert rule["undated_test_share"] == splits.UNDATED_TEST_SHARE


class TestAssignSplit:
    def _rule(self) -> dict:
        return {
            splits.SOURCE_ORIGINAL: {
                "t1": "2021-01-01",
                "t2": "2022-01-01",
                "undated_test_share": 0.2,
            }
        }

    def test_every_dated_test_record_is_after_every_dated_train_record(self):
        frame = _listing_frame(_daily_dates(1200, "2019-06-01"))
        assigned = splits.assign_split(frame, self._rule())
        dates = splits.event_dates(frame)
        train_max = max(d for d, s in zip(dates, assigned, strict=True) if s == "train")
        test_min = min(d for d, s in zip(dates, assigned, strict=True) if s == "test")
        test_max = max(d for d, s in zip(dates, assigned, strict=True) if s == "test")
        sim_min = min(d for d, s in zip(dates, assigned, strict=True) if s == "simulation")
        assert train_max < test_min
        assert test_max < sim_min

    def test_undated_records_never_go_to_simulation(self):
        frame = _listing_frame([None] * 2000)
        assigned = splits.assign_split(frame, self._rule())
        assert set(assigned) <= {"train", "test"}
        share = (assigned == "test").mean()
        assert 0.15 < share < 0.25

    def test_undated_assignment_depends_only_on_property_id(self):
        frame = _listing_frame([None] * 200)
        first = splits.assign_split(frame, self._rule())
        shuffled = frame.sample(frac=1, random_state=3)
        second = splits.assign_split(shuffled, self._rule())
        assert (first.loc[shuffled.index] == second).all()

    def test_zero_undated_share_sends_every_undated_record_to_train(self):
        rule = {splits.SOURCE_ORIGINAL: {"t1": "2021-01-01", "t2": "2021-01-01",
                                         "undated_test_share": 0.0}}
        assigned = splits.assign_split(_listing_frame([None] * 100), rule)
        assert set(assigned) == {"train"}

    def test_null_t2_means_no_simulation_set(self):
        rule = {splits.SOURCE_ORIGINAL: {"t1": "2021-01-01", "t2": None,
                                         "undated_test_share": 0.2}}
        assigned = splits.assign_split(_listing_frame(["2030-01-01"]), rule)
        assert list(assigned) == ["test"]

    def test_source_without_a_rule_raises(self):
        frame = pd.DataFrame(
            {
                "property_id": ["p1"],
                "listing_date": ["2020-01-01"],
                splits.SOURCE_COLUMN: [splits.SOURCE_FEEDBACK],
                splits.PREDICTED_AT_COLUMN: ["2026-01-01T00:00:00+00:00"],
            }
        )
        with pytest.raises(ValueError, match="feedback"):
            splits.assign_split(frame, self._rule())

    def test_keeps_the_input_index(self):
        frame = _listing_frame(["2020-01-01", "2021-06-01"]).set_index(pd.Index([7, 3]))
        assigned = splits.assign_split(frame, self._rule())
        assert list(assigned.index) == [7, 3]


class TestBuildManifest:
    def test_manifest_holds_split_points_for_original_records(self):
        frame = _listing_frame(_daily_dates(100))
        manifest = splits.build_manifest("v2", frame["listing_date"], row_count=100)
        assert manifest["dataset_version"] == "v2"
        assert manifest["row_count"] == 100
        assert set(manifest["split_points"]) == {splits.SOURCE_ORIGINAL}
        assert manifest["lineage"] is None
