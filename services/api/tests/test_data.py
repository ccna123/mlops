import asyncio
import io
import tempfile
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from ml_common.storage import raw_key
from services.api.app import create_app
from services.api.routes import data as data_routes
from services.api.routes.data import (
    DEFAULT_PREVIEW_ROWS,
    MAX_PREVIEW_ROWS,
    PREVIEW_STATS_ROWS,
)

CSV = b"property_id,city,sale_price\np1,boston,450000\np2,miami,380000\n"


def _on_the_event_loop_thread() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class FakeStorage:
    """Reads the file at call time: the route deletes its temp files afterwards."""

    def __init__(self, error=None):
        self.uploaded = []
        self.on_loop_thread = []
        self.error = error

    def upload_file(self, local_path, key):
        self.on_loop_thread.append(_on_the_event_loop_thread())
        if self.error is not None:
            raise self.error
        with open(local_path, "rb") as handle:
            self.uploaded.append((key, handle.read()))


def _client(storage, max_bytes=None):
    app = create_app(storage=storage)
    if max_bytes is not None:
        app.state.max_upload_bytes = max_bytes
    return TestClient(app)


def _post(client, content=CSV, filename="data.csv", version="v2"):
    return client.post(
        "/api/data/upload",
        files={"file": (filename, io.BytesIO(content), "text/csv")},
        data={"dataset_version": version},
    )


@pytest.fixture
def scratch(tmp_path, monkeypatch):
    """Points tempfile at an empty directory so leftovers are visible."""
    directory = tmp_path / "scratch"
    directory.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(directory))
    return directory


def _stored_table(storage) -> pa.Table:
    _, content = storage.uploaded[0]
    return pq.read_table(pa.BufferReader(content))


def test_upload_stores_the_file_under_the_dataset_version():
    storage = FakeStorage()
    response = _post(_client(storage))

    assert response.status_code == 200
    assert response.json()["dataset_version"] == "v2"
    assert storage.uploaded[0][0] == "raw/v2/data.parquet"


def test_the_stored_parquet_is_all_text_with_the_original_values():
    storage = FakeStorage()
    _post(_client(storage))

    table = _stored_table(storage)

    assert table.num_rows == 2
    assert all(pa.types.is_string(field.type) for field in table.schema)
    assert table.column("sale_price").to_pylist() == ["450000", "380000"]
    assert table.column("property_id").to_pylist() == ["p1", "p2"]


def test_a_currency_value_is_not_repaired_on_the_way_in():
    storage = FakeStorage()
    _post(_client(storage), content=b'id,price\np1,"$450,000"\n')

    assert _stored_table(storage).column("price").to_pylist() == ["$450,000"]


def test_upload_reports_the_row_count_and_size():
    body = _post(_client(FakeStorage())).json()
    assert body["rows"] == 2
    assert body["size_mb"] >= 0


def test_upload_over_the_cap_is_413_not_an_out_of_memory_kill():
    big = b"a,b\n" + b"1,2\n" * 10_000
    response = _post(_client(FakeStorage(), max_bytes=100), content=big)

    assert response.status_code == 413
    assert "100" in response.json()["detail"]
    assert "limit" in response.json()["detail"]


def test_a_rejected_upload_stores_nothing():
    storage = FakeStorage()
    big = b"a,b\n" + b"1,2\n" * 10_000
    _post(_client(storage, max_bytes=100), content=big)
    assert storage.uploaded == []


def test_upload_rejects_a_file_that_is_not_csv():
    response = _post(_client(FakeStorage()), content=b"not csv", filename="data.txt")
    assert response.status_code == 422


def test_a_header_only_csv_is_422_because_there_is_nothing_to_store():
    storage = FakeStorage()
    response = _post(_client(storage), content=b"a,b\n")

    assert response.status_code == 422
    assert "no data rows" in response.json()["detail"]
    assert storage.uploaded == []


@pytest.mark.parametrize("version", ["v2", "v1.1", "2026-09_a", "a" * 64])
def test_a_plain_dataset_version_is_accepted(version):
    storage = FakeStorage()
    response = _post(_client(storage), version=version)

    assert response.status_code == 200
    assert storage.uploaded[0][0] == f"raw/{version}/data.parquet"


@pytest.mark.parametrize(
    "version", ["a/b", "../x", "", "a" * 65, "..", ".", "v 2", "v2\n", "v2/", "\\x"]
)
def test_a_dataset_version_that_is_not_a_plain_name_is_422_and_stores_nothing(version):
    storage = FakeStorage()
    response = _post(_client(storage), version=version)

    assert response.status_code == 422
    assert storage.uploaded == []


def test_conversion_and_upload_run_off_the_event_loop_thread(monkeypatch):
    conversion_on_loop_thread = []
    real_convert = data_routes.csv_to_parquet

    def recording_convert(*args, **kwargs):
        conversion_on_loop_thread.append(_on_the_event_loop_thread())
        return real_convert(*args, **kwargs)

    monkeypatch.setattr(data_routes, "csv_to_parquet", recording_convert)
    storage = FakeStorage()

    assert _post(_client(storage)).status_code == 200

    # Blocking work on the loop would freeze /health for the length of a
    # multi-hundred-megabyte upload.
    assert conversion_on_loop_thread == [False]
    assert storage.on_loop_thread == [False]


def test_temp_files_are_removed_after_a_successful_upload(scratch):
    assert _post(_client(FakeStorage())).status_code == 200
    assert list(scratch.iterdir()) == []


def test_temp_files_are_removed_after_a_413(scratch):
    big = b"a,b\n" + b"1,2\n" * 10_000
    assert _post(_client(FakeStorage(), max_bytes=100), content=big).status_code == 413
    assert list(scratch.iterdir()) == []


def test_a_csv_pandas_cannot_parse_is_422_with_the_reason_and_cleans_up(scratch):
    storage = FakeStorage()
    response = _post(_client(storage), content=b'a,b\n1,"2\n3,4\n')

    assert response.status_code == 422
    assert "could not parse" in response.json()["detail"]
    assert storage.uploaded == []
    assert list(scratch.iterdir()) == []


def test_bytes_that_are_not_text_are_422_not_a_500(scratch):
    response = _post(_client(FakeStorage()), content=b"a,b\n1,\xff\xfe\n")

    assert response.status_code == 422
    assert list(scratch.iterdir()) == []


def test_a_storage_failure_is_not_hidden_and_still_cleans_up(scratch):
    client = _client(FakeStorage(error=RuntimeError("minio is down")))

    with pytest.raises(RuntimeError, match="minio is down"):
        _post(client)

    assert list(scratch.iterdir()) == []


class FakeHeadStorage:
    """Serves one frame for exactly one key, and records what it was asked."""

    def __init__(self, frame, total_rows=None, key=None, error=None):
        self._frame = frame
        self._total_rows = len(frame) if total_rows is None else total_rows
        self._key = raw_key("v1") if key is None else key
        self._error = error
        self.head_calls = []

    def read_parquet_head(self, key, rows):
        self.head_calls.append((key, rows))
        if self._error is not None:
            raise self._error
        if key != self._key:
            raise FileNotFoundError(f"Key not found: {key}")
        return self._frame.head(rows), self._total_rows


def _preview_client(frame, **kwargs):
    storage = FakeHeadStorage(frame, **kwargs)
    return TestClient(create_app(storage=storage)), storage


PREVIEW_FRAME = pd.DataFrame(
    {
        "property_id": ["p1", "p2", "p3"],
        "city": ["boston", "miami", None],
        "bedrooms": ["3", "4", "999"],
        "sale_price": ["$450,000", "$380,000", "$1"],
    }
)

BIG_FRAME = pd.DataFrame({"property_id": [f"p{i}" for i in range(250)], "bedrooms": ["3"] * 250})


def test_preview_returns_sample_rows_and_column_stats():
    client, _ = _preview_client(PREVIEW_FRAME)
    body = client.get("/api/data/v1/preview?rows=2").json()

    assert body["total_rows"] == 3
    assert [row["property_id"] for row in body["sample"]] == ["p1", "p2"]
    assert [column["name"] for column in body["columns"]] == sorted(
        ["property_id", "city", "bedrooms", "sale_price"]
    )
    bedrooms = next(c for c in body["columns"] if c["name"] == "bedrooms")
    assert bedrooms["kind"] == "numeric"


def test_preview_reads_the_raw_key_of_the_version_with_the_stats_row_limit():
    client, storage = _preview_client(PREVIEW_FRAME)
    client.get("/api/data/v1/preview")

    assert storage.head_calls == [(raw_key("v1"), PREVIEW_STATS_ROWS)]


def test_preview_reports_missing_rate_from_ml_common_not_its_own_count():
    client, _ = _preview_client(PREVIEW_FRAME)
    body = client.get("/api/data/v1/preview").json()
    city = next(c for c in body["columns"] if c["name"] == "city")
    assert city["missing_rate"] > 0


def test_preview_reports_out_of_bounds_counts():
    # bedrooms is declared max_value=20 in the schema; "999" is outside it.
    client, _ = _preview_client(PREVIEW_FRAME)
    body = client.get("/api/data/v1/preview").json()
    bedrooms = next(c for c in body["columns"] if c["name"] == "bedrooms")
    assert bedrooms["out_of_bounds"] == 1


def test_total_rows_is_the_file_total_and_stats_rows_is_what_the_stats_saw():
    # The file has 2,000,000 rows; the fake hands back only the 3-row head.
    client, _ = _preview_client(PREVIEW_FRAME, total_rows=2_000_000)
    body = client.get("/api/data/v1/preview").json()

    assert body["total_rows"] == 2_000_000
    assert body["stats_rows"] == 3


def test_preview_of_a_version_that_does_not_exist_is_404():
    client, storage = _preview_client(PREVIEW_FRAME)
    response = client.get("/api/data/v9/preview")

    assert response.status_code == 404
    assert "v9" in response.json()["detail"]
    assert storage.head_calls == [(raw_key("v9"), PREVIEW_STATS_ROWS)]


def test_a_storage_failure_that_is_not_a_missing_key_is_a_500_not_a_404():
    storage = FakeHeadStorage(PREVIEW_FRAME, error=RuntimeError("minio is down"))
    client = TestClient(create_app(storage=storage), raise_server_exceptions=False)

    assert client.get("/api/data/v1/preview").status_code == 500


def test_preview_rows_above_the_cap_is_silently_clamped():
    client, _ = _preview_client(BIG_FRAME)
    response = client.get("/api/data/v1/preview?rows=10000")

    assert response.status_code == 200
    assert len(response.json()["sample"]) == MAX_PREVIEW_ROWS


def test_preview_rows_below_the_cap_returns_exactly_that_many():
    client, _ = _preview_client(BIG_FRAME)
    assert len(client.get("/api/data/v1/preview?rows=50").json()["sample"]) == 50


def test_preview_defaults_to_the_default_row_count():
    client, _ = _preview_client(BIG_FRAME)
    assert len(client.get("/api/data/v1/preview").json()["sample"]) == DEFAULT_PREVIEW_ROWS


@pytest.mark.parametrize("rows", [0, -1])
def test_preview_rows_that_is_not_positive_is_422(rows):
    client, storage = _preview_client(BIG_FRAME)

    assert client.get(f"/api/data/v1/preview?rows={rows}").status_code == 422
    assert storage.head_calls == []


def test_a_float_nan_in_the_sample_becomes_json_null():
    frame = pd.DataFrame(
        {"property_id": ["p1", "p2"], "bedrooms": [3.0, float("nan")], "city": ["a", None]}
    )
    client, _ = _preview_client(frame)
    response = client.get("/api/data/v1/preview")

    assert response.status_code == 200
    sample = response.json()["sample"]
    assert sample[0]["bedrooms"] == 3.0
    assert sample[1]["bedrooms"] is None
    assert sample[1]["city"] is None


def test_the_returned_sample_holds_no_nan_whatever_the_response_encoder_does():
    # FastAPI's own serializer maps NaN to null today, so the HTTP test above
    # cannot tell whether the handler converted. Call it directly: the dict it
    # returns must already be JSON-safe, not rely on a framework detail.
    frame = pd.DataFrame({"property_id": ["p1", "p2"], "bedrooms": [3.0, float("nan")]})
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(storage=FakeHeadStorage(frame)))
    )

    body = data_routes.preview(request, "v1", DEFAULT_PREVIEW_ROWS)

    assert body["sample"][1]["bedrooms"] is None


@pytest.mark.parametrize("version", ["%2E%2E", "a%20b", "a" * 65])
def test_preview_dataset_version_that_is_not_a_plain_name_is_422_and_reads_nothing(version):
    # Percent-encoded because the HTTP client would collapse a literal ".."
    # segment before the request left the process. "%2E%2E" is "..", "a%20b" is "a b".
    client, storage = _preview_client(PREVIEW_FRAME)

    assert client.get(f"/api/data/{version}/preview").status_code == 422
    assert storage.head_calls == []


def test_a_version_the_upload_accepts_is_previewable():
    client, storage = _preview_client(PREVIEW_FRAME)
    client.get("/api/data/v1.1/preview")

    assert storage.head_calls == [(raw_key("v1.1"), PREVIEW_STATS_ROWS)]
