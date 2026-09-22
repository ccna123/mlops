"""Reads the drift verdicts the monitor stage wrote to object storage.

Plan 4 writes two things per run: a full summary under the run's own prefix,
and a copy at a fixed `latest.json`. Reading the fixed key is one request;
finding the newest by listing and comparing timestamps would be many.

Every key comes from `ml_common.storage`, the one module that knows how the
bucket is laid out. Nothing here builds or parses a path itself.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ml_common.storage import drift_latest_key, drift_prefix, is_drift_summary_key, report_key


class ReportsClient:
    """Reads drift summaries for the dashboard.

    Example:
        client = ReportsClient(Storage.from_env())
        client.latest("house_price_regressor")
        # -> {"severity": "high",
        #     "parts": {"feature": "ok", "prediction": "high",
        #               "performance": "high"}, ...}
    """

    def __init__(self, storage):
        """Records where the reports live.

        Args:
            storage: a `Storage`, or anything with `read_json` and
                `list_keys`. `read_json` must raise `FileNotFoundError` for a
                key that does not exist, as `Storage.read_json` does. Injected
                so the tests need no MinIO.
        """
        self._storage = storage

    def latest(self, model_name: str) -> dict | None:
        """Reads the most recent drift verdict for one model.

        Args:
            model_name: the registered model.

        Returns:
            The summary the monitor stage wrote, or None when monitoring has
            never run for this model. None is a normal early state, not an
            error - the route turns it into a 404 so the UI can show an empty
            state rather than an alarming one.

        Raises:
            Exception: anything the storage raises other than
                `FileNotFoundError` (MinIO unreachable, bad credentials, a
                corrupt object) propagates, so the route answers 500. The key
                is read directly instead of being checked with
                `Storage.exists` first, because `exists` answers False for
                EVERY error and an outage would then read as "monitoring has
                never run".

        Example:
            latest("house_price_regressor")
            # -> {"severity": "high", "parts": {...}, "n_ground_truth": 500,
            #     "report_key": "reports/.../evidently.html"}
        """
        try:
            return self._storage.read_json(drift_latest_key(model_name))
        except FileNotFoundError:
            return None

    def html(self, model_name: str, run_id: str) -> bytes | None:
        """Reads the Evidently HTML report one monitoring run wrote.

        Args:
            model_name: the registered model.
            run_id: the monitoring run whose report is wanted.

        Returns:
            The report's bytes, or None when that run wrote none. None is
            ordinary: a run with no traffic in its window stops before
            Evidently and records `report_key: null`.

        Raises:
            Exception: anything the storage raises other than
                `FileNotFoundError`, so a MinIO outage stays a 500 and never
                reads as "this run has no report".

        Example:
            html("house_price_regressor", "20260920T075645")
            # -> b"<html>..."
        """
        try:
            return self._storage.read_bytes(report_key(model_name, run_id, "html"))
        except FileNotFoundError:
            return None

    def history(self, model_name: str, limit: int) -> list[dict]:
        """Reads recent drift verdicts, newest first.

        Every summary under the model's prefix is read before the list is cut
        to `limit`. The order comes from each summary's own `computed_at`, so
        it cannot be known from the keys, and the newest N cannot be picked
        without seeing them all. That costs one read per monitoring run ever
        made (about 720 a month at hourly monitoring), which is accepted.

        Args:
            model_name: the registered model.
            limit: how many verdicts to return. Must be positive - the route
                enforces that; a zero or negative value here would slice the
                list into something that is not "the newest N".

        Returns:
            Summaries ordered by `computed_at`, newest first. Run ids do not
            sort chronologically: the monitor stage's own default is a
            timestamp, but under `monitoring_dag` it is the Airflow run id,
            where every "scheduled__..." outranks every "manual__..." by
            name whatever time it ran. A summary whose `computed_at` is
            missing, unparseable or lacks a timezone sorts last rather than
            being given a guessed time, and never raises. Only per-run
            summaries are read (see `is_drift_summary_key`) - the same prefix
            also holds `latest.json` and Evidently's own HTML and JSON, and
            folding those in would produce nonsense rather than an error.

        Example:
            history("house_price_regressor", limit=20)
            # -> [{"run_id": "20260920T080000", "computed_at": "2026-09-20T08:00:00+00:00",
            #      "severity": "warning", ...},
            #     {"run_id": "scheduled__2026-09-20T07-00-00-00-00",
            #      "computed_at": "2026-09-20T07:00:00+00:00", "severity": "ok", ...}]
        """
        keys = [
            key
            for key in self._storage.list_keys(drift_prefix(model_name))
            if is_drift_summary_key(key)
        ]
        summaries = [(key, self._storage.read_json(key)) for key in keys]
        # The key breaks ties, so equal or missing timestamps still come out in
        # a stable order instead of whatever the listing happened to return.
        summaries.sort(key=lambda item: (_computed_at(item[1]), item[0]), reverse=True)
        return [summary for _, summary in summaries[:limit]]


def _computed_at(summary: dict) -> datetime:
    """Reads when a summary was computed, as something that sorts.

    Args:
        summary: a drift summary as the monitor stage wrote it.

    Returns:
        The `computed_at` timestamp as an aware datetime. The earliest
        possible time when the field is missing, is not an ISO-8601 string,
        or carries no timezone - naive and aware datetimes cannot be compared,
        and guessing a zone would put the run at a made-up position. Such a
        summary therefore sorts as the oldest.

    Example:
        _computed_at({"computed_at": "2026-09-20T07:56:45+00:00"})
        # -> datetime(2026, 9, 20, 7, 56, 45, tzinfo=UTC)
        _computed_at({"computed_at": "2026-09-20T07:56:45.123456+00:00"})
        # -> datetime(2026, 9, 20, 7, 56, 45, 123456, tzinfo=UTC)
        _computed_at({})                                     # -> datetime.min, UTC
        _computed_at({"computed_at": "2026-09-20T07:56:45"})  # -> datetime.min, UTC
    """
    earliest = datetime.min.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(summary["computed_at"])
    except (KeyError, TypeError, ValueError):
        return earliest
    if parsed.tzinfo is None:
        return earliest
    return parsed
