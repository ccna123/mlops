"""Reads the drift verdicts the monitor stage wrote to object storage.

Plan 4 writes two things per run: a full summary under the run's own prefix,
and a copy at a fixed `latest.json`. Reading the fixed key is one request;
finding the newest by listing and comparing timestamps would be many.

Every key comes from `ml_common.storage`, the one module that knows how the
bucket is laid out. Nothing here builds or parses a path itself.
"""

from __future__ import annotations

from ml_common.storage import drift_latest_key, drift_prefix, is_drift_summary_key


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
            storage: a `Storage`, or anything with `exists`, `read_json` and
                `list_keys`. Injected so the tests need no MinIO.
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

        Example:
            latest("house_price_regressor")
            # -> {"severity": "high", "parts": {...}, "n_ground_truth": 500,
            #     "report_key": "reports/.../evidently.html"}
        """
        key = drift_latest_key(model_name)
        if not self._storage.exists(key):
            return None
        return self._storage.read_json(key)

    def history(self, model_name: str, limit: int) -> list[dict]:
        """Reads recent drift verdicts, newest first.

        Args:
            model_name: the registered model.
            limit: how many verdicts to return. Must be positive - the route
                enforces that; a zero or negative value here would slice the
                list into something that is not "the newest N".

        Returns:
            Summaries ordered newest first. Only per-run summaries are read
            (see `is_drift_summary_key`) - the same prefix also holds
            `latest.json` and Evidently's own HTML and JSON, and folding
            those in would produce nonsense rather than an error.

        Example:
            history("house_price_regressor", limit=20)
            # -> [{"run_id": "20260920T0800", "severity": "warning", ...},
            #     {"run_id": "20260920T0700", "severity": "ok", ...}]
        """
        keys = [
            key
            for key in self._storage.list_keys(drift_prefix(model_name))
            if is_drift_summary_key(key)
        ]
        # Run ids are timestamps, so the key order is the chronological order.
        keys.sort(reverse=True)
        return [self._storage.read_json(key) for key in keys[:limit]]
