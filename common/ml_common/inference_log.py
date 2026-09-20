"""Holds prediction records until there are enough to write as one batch.

Writing one object per request would leave MinIO full of tiny files and make
the monitoring DAG open thousands of them to read a single day. So records
accumulate here and leave in batches.

Three rules, in priority order:

1. Serving a request never waits on this and never fails because of it.
2. A failed flush keeps its records and retries; MinIO restarting for a few
   seconds must not lose monitoring data.
3. The buffer has a hard cap. Rule 2 without a cap means a long MinIO outage
   plus live traffic ends in an out-of-memory kill, so past the cap the oldest
   records are dropped and counted — loss stays bounded and visible at /health.

This module decides WHEN to flush and WHAT to drop. It never touches object
storage: the caller supplies the write. That keeps it testable with a list.

Every method takes a lock: serving adds from request threads while the flusher
takes from another, and take() is a copy followed by a clear — a record added
between the two would otherwise be cleared without ever being handed out.
"""

from __future__ import annotations

import threading
import time
from collections import deque

DEFAULT_FLUSH_SIZE = 500
DEFAULT_FLUSH_SECONDS = 30.0
DEFAULT_MAX_SIZE = 5000


class InferenceLogBuffer:
    """A bounded FIFO of prediction records with a size-or-age flush trigger."""

    def __init__(
        self,
        flush_size: int = DEFAULT_FLUSH_SIZE,
        flush_seconds: float = DEFAULT_FLUSH_SECONDS,
        max_size: int = DEFAULT_MAX_SIZE,
        clock=time.monotonic,
    ):
        if flush_size > max_size:
            raise ValueError(
                f"flush_size ({flush_size}) cannot exceed max_size ({max_size}): "
                "the buffer would drop records before it ever flushed"
            )
        self._flush_size = flush_size
        self._flush_seconds = flush_seconds
        self._max_size = max_size
        self._clock = clock
        self._records: deque[dict] = deque()
        self._dropped = 0
        self._last_taken_at = clock()
        self._lock = threading.Lock()

    def _trim(self) -> None:
        """Caller must hold the lock."""
        while len(self._records) > self._max_size:
            self._records.popleft()
            self._dropped += 1

    def add(self, record: dict) -> None:
        """Appends one record, dropping the oldest if that puts us over the cap."""
        with self._lock:
            self._records.append(record)
            self._trim()

    def give_back(self, records: list[dict]) -> None:
        """Returns records a failed flush could not write, keeping their order.

        They go to the FRONT: they arrived before anything still buffered, and
        reordering them would scramble the timeline the monitoring DAG reads.
        """
        with self._lock:
            self._records.extendleft(reversed(records))
            self._trim()

    def should_flush(self, now: float | None = None) -> bool:
        """True when the batch is full enough, or has waited long enough.

        An empty buffer never flushes, however old — otherwise serving would
        write an empty file every flush interval for as long as it idles.
        """
        with self._lock:
            if not self._records:
                return False
            if len(self._records) >= self._flush_size:
                return True
            current = self._clock() if now is None else now
            return (current - self._last_taken_at) >= self._flush_seconds

    def take(self) -> list[dict]:
        """Removes and returns every buffered record, and restarts the age timer."""
        with self._lock:
            taken = list(self._records)
            self._records.clear()
            self._last_taken_at = self._clock()
            return taken

    def stats(self) -> dict:
        """Counts for /health. `dropped` is cumulative and never resets."""
        with self._lock:
            return {"buffered": len(self._records), "dropped": self._dropped}
