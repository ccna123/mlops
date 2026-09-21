"""Turning a raw CSV into the parquet file the pipeline's `extract` stage reads.

Two callers need exactly this conversion: `scripts/seed_raw_data.py`, run once
by hand, and `POST /api/data/upload`, which does it for a dashboard user. It
lives here so both go through the same code. A second copy would drift, and
the raw copy is the one place where "the same" matters: every column is text,
nothing is repaired, and the pipeline gets to see the dirt.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

CHUNK_ROWS = 200_000


def csv_to_parquet(
    source: str,
    destination: str,
    limit: int | None = None,
    on_chunk: Callable[[int], None] | None = None,
) -> int:
    """Streams the CSV into a parquet file, a chunk at a time.

    Every column is read as text on purpose: this is the RAW copy, and parsing
    belongs to the Pipeline. Letting pandas infer types here would quietly fix
    some of the dirt the pipeline exists to handle.

    This function blocks. Callers on an event loop should run it in a thread.

    Args:
        source: path to the CSV. Read `CHUNK_ROWS` (200k) rows at a time, so a
            373 MB file never has to fit in memory whole.
        destination: path of the parquet file to write.
        limit: stop after this many rows, or None for all of them.
        on_chunk: called with the running row total after each chunk is
            written, or None for no progress reporting.

    Returns:
        How many rows were written. The parquet file is closed either way, so
        an interrupted run leaves a readable partial file rather than a corrupt
        one. When the CSV has a header but no rows, nothing is written and
        `destination` is not created.

    Raises:
        ValueError: when pandas cannot parse the CSV (`pandas.errors.ParserError`
            and `EmptyDataError` are both subclasses) or the bytes are not valid
            text (`UnicodeDecodeError`).

    Example:
        csv_to_parquet("house_pricing_dirty.csv", "/tmp/data.parquet", None)
        # -> 2000000

        csv_to_parquet("data.csv", "/tmp/data.parquet", None, on_chunk=print)
        # prints 200000, 400000, ... as each chunk lands

        # Every column lands as a STRING. "$450,000" stays "$450,000" and
        # "09/20/2026" stays text - letting pandas infer types here would
        # quietly repair some of the dirt the pipeline exists to handle.
    """
    written = 0
    writer = None
    try:
        reader = pd.read_csv(source, chunksize=CHUNK_ROWS, dtype=str, keep_default_na=False)
        for chunk in reader:
            if limit is not None and written + len(chunk) > limit:
                chunk = chunk.head(limit - written)
            if chunk.empty:
                break
            table = pa.Table.from_pandas(chunk, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(destination, table.schema, compression="snappy")
            writer.write_table(table)
            written += len(chunk)
            if on_chunk is not None:
                on_chunk(written)
            if limit is not None and written >= limit:
                break
    finally:
        if writer is not None:
            writer.close()
    return written
