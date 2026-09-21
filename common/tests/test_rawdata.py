import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ml_common import rawdata
from ml_common.rawdata import csv_to_parquet

CSV = (
    "property_id,city,sale_price,notes\n"
    'p1,boston,450000,"two, commas, here"\n'
    'p2,miami,"$450,000",\n'
    "p3,,380000,plain\n"
)


def _write_csv(tmp_path, text=CSV):
    path = tmp_path / "source.csv"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _convert(tmp_path, limit=None, on_chunk=None, text=CSV):
    destination = str(tmp_path / "out.parquet")
    written = csv_to_parquet(_write_csv(tmp_path, text), destination, limit, on_chunk=on_chunk)
    return written, pq.read_table(destination)


def test_every_column_comes_back_as_a_string(tmp_path):
    _, table = _convert(tmp_path)
    assert all(pa.types.is_string(field.type) for field in table.schema)


def test_numeric_looking_and_currency_values_stay_text(tmp_path):
    _, table = _convert(tmp_path)
    assert table.column("sale_price").to_pylist() == ["450000", "$450,000", "380000"]


def test_an_empty_field_stays_an_empty_string_not_null(tmp_path):
    _, table = _convert(tmp_path)
    assert table.column("city").to_pylist() == ["boston", "miami", ""]
    assert table.column("notes").to_pylist() == ["two, commas, here", "", "plain"]


def test_returns_the_number_of_rows_written(tmp_path):
    written, table = _convert(tmp_path)
    assert written == 3
    assert table.num_rows == 3


def test_limit_stops_early(tmp_path):
    written, table = _convert(tmp_path, limit=2)
    assert written == 2
    assert table.column("property_id").to_pylist() == ["p1", "p2"]


def test_limit_larger_than_the_file_writes_everything(tmp_path):
    written, _ = _convert(tmp_path, limit=1000)
    assert written == 3


def test_on_chunk_receives_the_running_total_after_each_chunk(tmp_path, monkeypatch):
    monkeypatch.setattr(rawdata, "CHUNK_ROWS", 2)
    totals = []

    written, _ = _convert(tmp_path, on_chunk=totals.append)

    assert totals == [2, 3]
    assert written == 3


def test_on_chunk_stops_at_the_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(rawdata, "CHUNK_ROWS", 2)
    totals = []

    _convert(tmp_path, limit=3, on_chunk=totals.append)

    assert totals == [2, 3]


def test_a_limit_that_cuts_mid_chunk_still_leaves_a_readable_file(tmp_path, monkeypatch):
    monkeypatch.setattr(rawdata, "CHUNK_ROWS", 10)

    written, table = _convert(tmp_path, limit=2)

    assert written == 2
    assert table.num_rows == 2


def test_chunked_and_unchunked_reads_produce_the_same_table(tmp_path, monkeypatch):
    _, whole = _convert(tmp_path)
    monkeypatch.setattr(rawdata, "CHUNK_ROWS", 1)

    _, chunked = _convert(tmp_path)

    assert chunked.equals(whole)


def test_progress_is_optional(tmp_path):
    written, _ = _convert(tmp_path, on_chunk=None)
    assert written == 3


def test_a_header_only_file_writes_zero_rows(tmp_path):
    destination = tmp_path / "out.parquet"

    written = csv_to_parquet(_write_csv(tmp_path, "a,b\n"), str(destination), None)

    assert written == 0
    assert not destination.exists()


def test_an_unparseable_csv_raises_value_error(tmp_path):
    with pytest.raises(ValueError):
        csv_to_parquet(_write_csv(tmp_path, 'a,b\n1,"2\n3,4\n'), str(tmp_path / "out.parquet"))


def test_a_failure_between_chunks_still_closes_the_writer(tmp_path, monkeypatch):
    monkeypatch.setattr(rawdata, "CHUNK_ROWS", 1)
    destination = tmp_path / "out.parquet"

    def fail_on_the_second_chunk(written):
        if written == 2:
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        csv_to_parquet(_write_csv(tmp_path), str(destination), None, fail_on_the_second_chunk)

    # The writer is closed in `finally`, so what is left is a valid parquet
    # file with the rows written so far rather than a truncated one.
    assert pq.read_table(destination).num_rows == 2
