import asyncio
import io
import tempfile

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from services.api.app import create_app
from services.api.routes import data as data_routes

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
