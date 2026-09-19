# Plan 2 — Batch Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng sáu stage `extract`, `validate`, `prepare_dataset_for_train`, `train`, `evaluate`, `register` và DAG `ml_pipeline` chạy được full một lượt cho bài toán regression, từ raw parquet trên MinIO tới model mang alias `champion` trong MLflow Registry.

**Architecture:** Logic thuần nằm trong `common/ml_common/` và được test bằng pytest không cần Docker. Mỗi stage là một image `FROM ml-base:latest` chứa một `main.py` mỏng: đọc biến môi trường, gọi hàm thuần, ghi MinIO, in một dòng JSON cuối cùng ra stdout. Airflow gọi các stage bằng `DockerOperator` qua docker socket; dữ liệu đi qua đường dẫn MinIO, XCom chỉ chở giá trị nhỏ.

**Tech Stack:** Python 3.12 (container) / 3.13 (dev), pandas 2.3, scikit-learn 1.9, MLflow 2.22, Airflow 2.10.3, MinIO (quay.io), Postgres 16, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-19-plan2-batch-pipeline-design.md` — đọc cùng plan này. Plan lập luận từ spec; chỗ nào hai bên lệch nhau thì spec thắng, và phải báo chứ không tự chọn bên.

## Global Constraints

Áp dụng cho mọi task. Sao chép nguyên giá trị, không tự đổi.

- **Python:** container 3.12, dev 3.13. **Không dùng cú pháp chỉ có ở 3.13+.**
- **Pin version:** `pandas>=2.2,<3`, `scikit-learn>=1.5,<2`, `pyarrow>=16`, `boto3>=1.34`, `numpy>=1.26,<3`, `mlflow>=2.14,<3`.
- **Thao tác theo dòng và theo cột phải tách biệt.** Thao tác theo cột nằm trong `sklearn.Pipeline` và đi cùng model. Thao tác theo dòng (`rowops.py`) **chỉ** được gọi từ stage `prepare_dataset_for_train`. **Không bao giờ import `rowops` từ `features.py` hay từ serving.**
- **Đường dẫn object storage:** mọi key phải sinh ra từ hàm `*_key()` / `*_prefix()` trong `common/ml_common/storage.py`. Không nối chuỗi ở bất kỳ file nào khác.
- **Ngôn ngữ trong code:** toàn bộ code, comment, docstring, error message viết **tiếng Anh tự nhiên**. File markdown tiếng Việt có dấu.
- **Giá trị thiếu:** dùng `None` / `np.nan`. Không dùng chuỗi rỗng hay sentinel như `-1`.
- **Encoding file:** UTF-8 không BOM.
- **Ruff:** `line-length = 100`, rule set `["E", "F", "I", "UP", "B"]`.
- **Commit:** mỗi task kết thúc bằng **đúng một** commit. Conventional Commits, mô tả tiếng Việt **không dấu**. Kết thúc message bằng dòng `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`, kiểm lại bằng `git log -1`.
- **Build lại `ml-base` mỗi khi `common/` thay đổi:** `powershell -ExecutionPolicy Bypass -File scripts\build_base_image.ps1`. Không build lại thì stage dùng bản cũ và lỗi sẽ rất khó hiểu.
- **Dung lượng đĩa:** ổ C còn ~16GB. Kiểm tra còn tối thiểu 8GB trước khi build image.
- **Lệnh Python local:** gọi thẳng `.venv\Scripts\python.exe`, không dùng `Activate.ps1`.

## File Structure

| File | Trách nhiệm |
| --- | --- |
| `common/ml_common/storage.py` | **Sửa:** thêm `extracted_key()`, `validation_report_key()`, và method `Storage.object_etag()` |
| `common/ml_common/fingerprint.py` | **Mới.** Tính cache key từ `dataset_version` + ETag + `sample_rows` |
| `common/ml_common/validation.py` | **Mới.** Luật kiểm tra dataset, trả report dict + cờ fatal |
| `common/ml_common/estimators.py` | **Mới.** Dựng estimator theo `task_type` + tên, bọc log-target cho regression |
| `common/ml_common/metrics.py` | **Mới.** Tính metric theo `task_type`, regression trả đơn vị đô la |
| `common/ml_common/gates.py` | **Mới.** Quyết định hai cổng của `evaluate` |
| `scripts/seed_raw_data.py` | **Mới.** Đẩy CSV local lên MinIO thành `raw/v1/data.parquet` |
| `scripts/build_stage_images.ps1` | **Mới.** Build cả sáu image stage |
| `stages/base/Dockerfile` | **Sửa:** thêm `mlflow` vào image nền |
| `stages/{extract,validate,prepare_dataset_for_train,train,evaluate,register}/` | **Mới.** Mỗi thư mục một `Dockerfile` + `main.py` |
| `dags/ml_pipeline_dag.py` | **Mới.** DAG `ml_pipeline` |
| `docker-compose.yml` | **Sửa:** `airflow-scheduler` thêm docker socket + provider |
| `common/tests/test_*.py` | Test cho từng module mới ở trên |

Lý do đặt logic thuần trong `common/` thay vì trong `stages/`: `common/` đã có sẵn bộ test chạy ở cả Python 3.13 local lẫn 3.12 trong container. Đặt logic ở `stages/` thì phải dựng thêm một bộ test thứ hai cho mỗi stage, và stage vốn chỉ nên là vỏ mỏng.

---

## Task 1: Cache addressing — key mới và fingerprint

**Files:**
- Modify: `common/ml_common/storage.py`
- Create: `common/ml_common/fingerprint.py`
- Test: `common/tests/test_storage.py` (thêm), `common/tests/test_fingerprint.py` (mới)

**Interfaces:**
- Consumes: `storage.Storage` (đã có từ Plan 1)
- Produces:
  - `storage.extracted_key(fingerprint: str) -> str`
  - `storage.validation_report_key(fingerprint: str) -> str`
  - `storage.Storage.object_etag(key: str) -> str`
  - `fingerprint.compute_fingerprint(dataset_version: str, etag: str, sample_rows: int | None) -> str`

- [ ] **Step 1: Viết test cho hai hàm key mới**

Thêm vào cuối `common/tests/test_storage.py`:

```python
def test_extracted_key():
    assert storage.extracted_key("abc123") == "extracted/abc123/data.parquet"


def test_validation_report_key():
    assert storage.validation_report_key("abc123") == "reports/validation/abc123.json"
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_storage.py -k "extracted_key or validation_report_key" -v`
Expected: FAIL với `AttributeError: module 'ml_common.storage' has no attribute 'extracted_key'`

- [ ] **Step 3: Thêm hai hàm key vào `storage.py`**

Chèn ngay sau `processed_prefix()`:

```python
def extracted_key(fingerprint: str) -> str:
    """Path to the sampled working copy that `extract` writes.

    Separate from `raw/`: raw holds the full dataset as it arrived, while this
    holds exactly the rows this pipeline run will use, after SAMPLE_ROWS.
    """
    return f"extracted/{fingerprint}/data.parquet"


def validation_report_key(fingerprint: str) -> str:
    """Path to the counts `validate` produces for one fingerprint."""
    return f"reports/validation/{fingerprint}.json"
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_storage.py -k "extracted_key or validation_report_key" -v`
Expected: PASS, 2 test

- [ ] **Step 5: Viết test cho `object_etag`**

Thêm vào `common/tests/test_storage.py`. Bộ test này đã dùng `moto` — tra cách các test khác dựng fixture rồi theo đúng pattern đó:

```python
def test_object_etag_changes_when_content_changes(storage_client):
    first = pd.DataFrame({"a": [1, 2, 3]})
    second = pd.DataFrame({"a": [9, 9, 9]})

    storage_client.write_parquet(first, "raw/v1/data.parquet")
    etag_before = storage_client.object_etag("raw/v1/data.parquet")

    storage_client.write_parquet(second, "raw/v1/data.parquet")
    etag_after = storage_client.object_etag("raw/v1/data.parquet")

    assert etag_before != etag_after
    assert '"' not in etag_before


def test_object_etag_missing_key_raises(storage_client):
    with pytest.raises(FileNotFoundError):
        storage_client.object_etag("raw/nope/data.parquet")
```

- [ ] **Step 6: Chạy test để xác nhận fail**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_storage.py -k object_etag -v`
Expected: FAIL với `AttributeError: 'Storage' object has no attribute 'object_etag'`

- [ ] **Step 7: Thêm method `object_etag` vào class `Storage`**

Chèn ngay trước `def exists`:

```python
    def object_etag(self, key: str) -> str:
        """ETag of an object, used as a cheap content fingerprint.

        S3 quotes the ETag in the response; the quotes are stripped so the
        value can go straight into a path or a hash.
        """
        try:
            response = self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as err:
            if err.response["Error"]["Code"] in ("NoSuchKey", "404", "NoSuchBucket"):
                raise FileNotFoundError(f"Key not found: {key}") from err
            raise
        return response["ETag"].strip('"')
```

- [ ] **Step 8: Chạy test để xác nhận pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_storage.py -k object_etag -v`
Expected: PASS, 2 test

- [ ] **Step 9: Viết test cho `compute_fingerprint`**

Tạo `common/tests/test_fingerprint.py`:

```python
"""Tests for the cache key that ties processed data back to its raw input."""

from ml_common.fingerprint import compute_fingerprint


def test_same_input_gives_same_fingerprint():
    first = compute_fingerprint("v1", "abc", 200000)
    second = compute_fingerprint("v1", "abc", 200000)
    assert first == second


def test_fingerprint_is_short_lowercase_hex():
    result = compute_fingerprint("v1", "abc", None)
    assert len(result) == 16
    assert all(char in "0123456789abcdef" for char in result)


def test_different_sample_rows_gives_different_fingerprint():
    sampled = compute_fingerprint("v1", "abc", 200000)
    full = compute_fingerprint("v1", "abc", None)
    assert sampled != full


def test_different_etag_gives_different_fingerprint():
    before = compute_fingerprint("v1", "abc", 200000)
    after = compute_fingerprint("v1", "xyz", 200000)
    assert before != after


def test_different_dataset_version_gives_different_fingerprint():
    first = compute_fingerprint("v1", "abc", 200000)
    second = compute_fingerprint("v2", "abc", 200000)
    assert first != second


def test_sample_rows_zero_is_not_the_same_as_no_limit():
    """0 rows and 'no limit' are different requests; they must not share a cache."""
    assert compute_fingerprint("v1", "abc", 0) != compute_fingerprint("v1", "abc", None)
```

- [ ] **Step 10: Chạy test để xác nhận fail**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_fingerprint.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.fingerprint'`

- [ ] **Step 11: Viết `common/ml_common/fingerprint.py`**

```python
"""The cache key that ties processed data back to the raw input it came from.

`prepare_dataset_for_train` skips its work when data for a fingerprint already
exists, so anything that changes which rows the pipeline sees MUST be part of
the fingerprint. Leaving SAMPLE_ROWS out would let a 200k-row run silently
reuse the split built from 2 million rows.
"""

from __future__ import annotations

import hashlib

_LENGTH = 16


def compute_fingerprint(dataset_version: str, etag: str, sample_rows: int | None) -> str:
    """Builds the cache key for one combination of raw data and row limit.

    Args:
        dataset_version: the raw dataset version, e.g. "v1".
        etag: ETag of the raw object; it already changes whenever the file does,
            so there is no need to read and hash 2 million rows.
        sample_rows: row limit for this run, or None to use every row.

    Returns:
        16 lowercase hex characters.
    """
    limit = "all" if sample_rows is None else str(sample_rows)
    payload = f"{dataset_version}|{etag}|{limit}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:_LENGTH]
```

- [ ] **Step 12: Chạy test để xác nhận pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_fingerprint.py -v`
Expected: PASS, 6 test

- [ ] **Step 13: Chạy toàn bộ test và lint**

Run:
```powershell
.venv\Scripts\python.exe -m pytest common/ -q
.venv\Scripts\python.exe -m ruff check common/
```
Expected: tất cả PASS (148 test cũ + 10 test mới = 158), `All checks passed!`

- [ ] **Step 14: Build lại image nền và chạy test bên trong**

Run:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_base_image.ps1
docker run --rm ml-base:latest sh -c "pip install --quiet 'pytest>=8.0' 'moto[s3]>=5.0' && python -m pytest /app/common/tests -q"
```
Expected: 158 passed. Con số phải khớp với lần chạy local — lệch là có khác biệt môi trường, dừng lại và báo.

- [ ] **Step 15: Commit**

```bash
git add common/ml_common/storage.py common/ml_common/fingerprint.py common/tests/test_storage.py common/tests/test_fingerprint.py
git commit -m "feat: key cho extracted va validation report, them fingerprint cache key"
```

---

## Task 2: `validation.py` — luật kiểm tra dataset

**Files:**
- Create: `common/ml_common/validation.py`
- Test: `common/tests/test_validation.py`

**Interfaces:**
- Consumes: `schema.COLUMNS`, `schema.target_column()`, `schema.ColumnSpec`
- Produces: `validation.validate_dataframe(df: pd.DataFrame, task_type: str) -> dict`

Report dict có đúng các khoá: `ok` (bool), `fatal` (list[str]), `row_count` (int), `duplicate_rows` (int), `columns` (dict[str, dict]). Mỗi entry trong `columns` có `missing_rate` (float) và `out_of_bounds` (int).

**Quan trọng:** dataset này **cố tình dirty**. `validate` chỉ fail khi dữ liệu vô dụng, không fail vì dữ liệu bẩn. Đúng ba luật fatal:
1. Thiếu cột so với `schema.COLUMNS`.
2. Hơn 50% giá trị target bị thiếu.
3. Số dòng bằng 0.

- [ ] **Step 1: Viết test**

Tạo `common/tests/test_validation.py`:

```python
"""Tests for the validate stage's rules.

The dataset is dirty on purpose, so these tests pin down the line between
"dirty but usable" (must pass) and "unusable" (must fail).
"""

import numpy as np
import pandas as pd
import pytest

from ml_common import schema
from ml_common.validation import validate_dataframe


def _valid_frame(row_count: int = 4) -> pd.DataFrame:
    """A frame with every schema column present and a usable target."""
    data = {}
    for column_name, spec in schema.COLUMNS.items():
        if spec.kind == "numeric":
            data[column_name] = [1] * row_count
        elif spec.kind == "money":
            data[column_name] = ["$100,000"] * row_count
        elif spec.kind == "boolean":
            data[column_name] = ["Y"] * row_count
        elif spec.kind == "date":
            data[column_name] = ["2024-01-15"] * row_count
        else:
            data[column_name] = ["value"] * row_count
    data[schema.target_column("regression")] = [100000.0] * row_count
    return pd.DataFrame(data)


def test_clean_enough_frame_passes():
    report = validate_dataframe(_valid_frame(), "regression")
    assert report["ok"] is True
    assert report["fatal"] == []


def test_dirty_but_usable_frame_still_passes():
    """Dirty values are the exercise, not an incident — they must not fail the run."""
    df = _valid_frame()
    df.loc[0, "city"] = "  NEW_YORK  "
    df.loc[1, "zipcode"] = "1234"
    df.loc[2, "bedrooms"] = -5
    report = validate_dataframe(df, "regression")
    assert report["ok"] is True


def test_missing_column_is_fatal():
    df = _valid_frame().drop(columns=["city"])
    report = validate_dataframe(df, "regression")
    assert report["ok"] is False
    assert any("city" in reason for reason in report["fatal"])


def test_empty_frame_is_fatal():
    report = validate_dataframe(_valid_frame(row_count=0), "regression")
    assert report["ok"] is False
    assert any("no rows" in reason for reason in report["fatal"])


def test_target_mostly_missing_is_fatal():
    df = _valid_frame(row_count=10)
    df.loc[0:5, schema.target_column("regression")] = np.nan
    report = validate_dataframe(df, "regression")
    assert report["ok"] is False
    assert any("target" in reason for reason in report["fatal"])


def test_target_half_missing_is_not_fatal():
    """The rule is 'more than 50%', so exactly half must still pass."""
    df = _valid_frame(row_count=10)
    df.loc[0:4, schema.target_column("regression")] = np.nan
    report = validate_dataframe(df, "regression")
    assert report["ok"] is True


def test_report_counts_missing_rate_per_column():
    df = _valid_frame(row_count=4)
    df.loc[0:1, "city"] = None
    report = validate_dataframe(df, "regression")
    assert report["columns"]["city"]["missing_rate"] == pytest.approx(0.5)


def test_report_counts_duplicate_rows():
    df = _valid_frame(row_count=4)
    df.loc[1, schema.ID_COLUMN] = df.loc[0, schema.ID_COLUMN]
    report = validate_dataframe(df, "regression")
    assert report["duplicate_rows"] == 1


def test_report_counts_out_of_bounds_values():
    df = _valid_frame(row_count=4)
    df.loc[0, "bedrooms"] = -1
    report = validate_dataframe(df, "regression")
    assert report["columns"]["bedrooms"]["out_of_bounds"] == 1


def test_report_is_json_serializable():
    """The report goes to MinIO as JSON, so no numpy types may survive."""
    import json

    report = validate_dataframe(_valid_frame(), "regression")
    json.dumps(report)


def test_invalid_task_type_raises():
    with pytest.raises(ValueError, match="task_type"):
        validate_dataframe(_valid_frame(), "clustering")
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_validation.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.validation'`

- [ ] **Step 3: Viết `common/ml_common/validation.py`**

```python
"""Rules for the validate stage: measure the data, block only what is unusable.

This dataset is dirty on purpose — eight documented kinds of mess are the
exercise, not an incident. So validation counts everything and reports it, but
fails the run only when the data cannot be trained on at all.
"""

from __future__ import annotations

import pandas as pd

from . import schema

MAX_TARGET_MISSING_RATE = 0.5


def _missing_rate(series: pd.Series) -> float:
    if len(series) == 0:
        return 0.0
    return float(series.isna().mean())


def _out_of_bounds_count(series: pd.Series, spec: schema.ColumnSpec) -> int:
    """Counts values outside the schema bounds, ignoring anything non-numeric.

    Values that cannot be read as numbers are not counted here: they are missing
    or mistyped, which the missing rate and the parsers already cover.
    """
    if spec.min_value is None and spec.max_value is None:
        return 0
    numeric = pd.to_numeric(series, errors="coerce")
    outside = pd.Series(False, index=series.index)
    if spec.min_value is not None:
        outside |= numeric < spec.min_value
    if spec.max_value is not None:
        outside |= numeric > spec.max_value
    return int(outside.fillna(False).sum())


def validate_dataframe(df: pd.DataFrame, task_type: str) -> dict:
    """Measures a raw dataset and decides whether the run may continue.

    Args:
        df: the raw DataFrame, straight from `extracted/`.
        task_type: "regression" or "classification".

    Returns:
        A JSON-serializable report. `ok` is False when `fatal` is non-empty.
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}")

    fatal: list[str] = []
    row_count = int(len(df))

    missing_columns = sorted(set(schema.COLUMNS) - set(df.columns))
    if missing_columns:
        fatal.append(f"missing columns required by the schema: {', '.join(missing_columns)}")

    if row_count == 0:
        fatal.append("the dataset has no rows")

    target = schema.target_column(task_type)
    if target in df.columns and row_count > 0:
        target_missing = _missing_rate(df[target])
        if target_missing > MAX_TARGET_MISSING_RATE:
            fatal.append(
                f"target {target!r} is missing in {target_missing:.1%} of rows, "
                f"above the {MAX_TARGET_MISSING_RATE:.0%} limit"
            )

    columns: dict[str, dict] = {}
    for column_name, spec in schema.COLUMNS.items():
        if column_name not in df.columns:
            continue
        series = df[column_name]
        columns[column_name] = {
            "missing_rate": round(_missing_rate(series), 6),
            "out_of_bounds": _out_of_bounds_count(series, spec),
        }

    duplicate_rows = 0
    if schema.ID_COLUMN in df.columns:
        duplicate_rows = int(df[schema.ID_COLUMN].duplicated().sum())

    return {
        "ok": not fatal,
        "fatal": fatal,
        "row_count": row_count,
        "duplicate_rows": duplicate_rows,
        "columns": columns,
    }
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_validation.py -v`
Expected: PASS, 11 test

`ColumnSpec` có các thuộc tính `name`, `kind`, `required`, `min_value`, `max_value`, `allowed` — dùng đúng tên đó, **đừng sửa `schema.py`**, nó đã có test xanh từ Plan 1.

- [ ] **Step 5: Chạy toàn bộ test và lint**

Run:
```powershell
.venv\Scripts\python.exe -m pytest common/ -q
.venv\Scripts\python.exe -m ruff check common/
```
Expected: 169 passed, `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add common/ml_common/validation.py common/tests/test_validation.py
git commit -m "feat: luat kiem tra dataset cho stage validate"
```

---

## Task 3: `estimators.py` — dựng estimator theo task_type

**Files:**
- Create: `common/ml_common/estimators.py`
- Test: `common/tests/test_estimators.py`

**Interfaces:**
- Consumes: `schema.TASK_TYPES`
- Produces: `estimators.build_estimator(task_type: str, name: str) -> BaseEstimator`, và hằng `estimators.ESTIMATOR_NAMES: dict[str, tuple[str, ...]]`

Tên estimator hợp lệ: regression `("ridge", "hist_gradient_boosting", "dummy")`, classification `("logistic", "hist_gradient_boosting", "dummy")`.

`"dummy"` có mặt vì Definition of Done yêu cầu chứng minh cổng `evaluate` **chặn được** một model kém — cần một model chắc chắn trượt ngưỡng.

**Quyết định bắt buộc:** regression bọc estimator trong `TransformedTargetRegressor(func=np.log1p, inverse_func=np.expm1)`. Nhờ vậy `.predict()` trả thẳng đô la và không stage nào ở hạ nguồn — kể cả serving ở Plan 3 — phải tự nghịch đảo log. Classification **không** bọc.

- [ ] **Step 1: Viết test**

Tạo `common/tests/test_estimators.py`:

```python
"""Tests for estimator construction, especially the log-target wrapper."""

import numpy as np
import pandas as pd
import pytest
from sklearn.compose import TransformedTargetRegressor

from ml_common.estimators import ESTIMATOR_NAMES, build_estimator


def test_regression_estimator_is_wrapped_for_log_target():
    estimator = build_estimator("regression", "ridge")
    assert isinstance(estimator, TransformedTargetRegressor)


def test_classification_estimator_is_not_wrapped():
    estimator = build_estimator("classification", "logistic")
    assert not isinstance(estimator, TransformedTargetRegressor)


def test_regression_predicts_in_original_units():
    """The wrapper must undo the log, so predictions come back in dollars."""
    X = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0]})
    y = pd.Series([100000.0, 200000.0, 300000.0, 400000.0])

    estimator = build_estimator("regression", "ridge")
    estimator.fit(X, y)
    predictions = estimator.predict(X)

    assert predictions.min() > 1000, "predictions look like logs, not dollars"


def test_every_declared_regression_name_builds():
    for name in ESTIMATOR_NAMES["regression"]:
        assert build_estimator("regression", name) is not None


def test_every_declared_classification_name_builds():
    for name in ESTIMATOR_NAMES["classification"]:
        assert build_estimator("classification", name) is not None


def test_dummy_regression_predicts_a_constant():
    """The evaluate gate needs a model that reliably fails; dummy is it."""
    X = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0]})
    y = pd.Series([100000.0, 500000.0, 200000.0, 900000.0])

    estimator = build_estimator("regression", "dummy")
    estimator.fit(X, y)
    predictions = estimator.predict(X)

    assert np.allclose(predictions, predictions[0])


def test_invalid_task_type_raises():
    with pytest.raises(ValueError, match="task_type"):
        build_estimator("clustering", "ridge")


def test_unknown_estimator_name_raises():
    with pytest.raises(ValueError, match="estimator"):
        build_estimator("regression", "xgboost")
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_estimators.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.estimators'`

- [ ] **Step 3: Viết `common/ml_common/estimators.py`**

```python
"""Builds the estimator that goes at the end of the Pipeline.

Regression trains on log(price) to tame the skew, but every consumer wants
dollars. TransformedTargetRegressor keeps that conversion INSIDE the model, so
evaluate and serving never have to know it happened — one less piece of logic
that could drift between training and serving.
"""

from __future__ import annotations

import numpy as np
from sklearn.compose import TransformedTargetRegressor
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge

from . import schema

ESTIMATOR_NAMES: dict[str, tuple[str, ...]] = {
    "regression": ("ridge", "hist_gradient_boosting", "dummy"),
    "classification": ("logistic", "hist_gradient_boosting", "dummy"),
}

RANDOM_STATE = 42


def _regression_base(name: str):
    if name == "ridge":
        return Ridge(alpha=1.0)
    if name == "hist_gradient_boosting":
        return HistGradientBoostingRegressor(random_state=RANDOM_STATE)
    return DummyRegressor(strategy="mean")


def _classification_base(name: str):
    if name == "logistic":
        return LogisticRegression(max_iter=1000)
    if name == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(random_state=RANDOM_STATE)
    return DummyClassifier(strategy="prior")


def build_estimator(task_type: str, name: str):
    """Builds an estimator ready to pass to `features.build_pipeline`.

    Args:
        task_type: "regression" or "classification".
        name: one of `ESTIMATOR_NAMES[task_type]`.

    Returns:
        For regression, a TransformedTargetRegressor predicting in the original
        units. For classification, the classifier itself.
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}")
    allowed = ESTIMATOR_NAMES[task_type]
    if name not in allowed:
        raise ValueError(f"estimator for {task_type} must be one of {allowed}, got: {name!r}")

    if task_type == "regression":
        return TransformedTargetRegressor(
            regressor=_regression_base(name),
            func=np.log1p,
            inverse_func=np.expm1,
        )
    return _classification_base(name)
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_estimators.py -v`
Expected: PASS, 8 test

- [ ] **Step 5: Chạy toàn bộ test và lint**

Run:
```powershell
.venv\Scripts\python.exe -m pytest common/ -q
.venv\Scripts\python.exe -m ruff check common/
```
Expected: 177 passed, `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add common/ml_common/estimators.py common/tests/test_estimators.py
git commit -m "feat: dung estimator theo task_type, boc log target cho regression"
```

---

## Task 4: `metrics.py` — tính metric theo task_type

**Files:**
- Create: `common/ml_common/metrics.py`
- Test: `common/tests/test_metrics.py`

**Interfaces:**
- Consumes: `schema.TASK_TYPES`
- Produces: `metrics.compute_metrics(task_type: str, y_true, y_pred, y_proba=None) -> dict[str, float]`

Khoá trả về: regression `{"rmse", "mae", "r2"}`; classification `{"f1", "accuracy", "auc"}`. `auc` chỉ có khi truyền `y_proba`.

Mọi giá trị phải là `float` thuần — chúng đi vào MLflow và vào JSON, numpy type sẽ làm `json.dumps` nổ.

- [ ] **Step 1: Viết test**

Tạo `common/tests/test_metrics.py`:

```python
"""Tests for metric computation shared by train and evaluate."""

import json

import numpy as np
import pytest

from ml_common.metrics import compute_metrics


def test_regression_keys():
    result = compute_metrics("regression", [1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert set(result) == {"rmse", "mae", "r2"}


def test_perfect_regression_prediction():
    result = compute_metrics("regression", [1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert result["rmse"] == pytest.approx(0.0)
    assert result["r2"] == pytest.approx(1.0)


def test_rmse_is_in_the_same_unit_as_the_target():
    """Off by 1000 dollars on every row means RMSE is 1000, not log-of-anything."""
    y_true = [100000.0, 200000.0, 300000.0]
    y_pred = [101000.0, 201000.0, 301000.0]
    result = compute_metrics("regression", y_true, y_pred)
    assert result["rmse"] == pytest.approx(1000.0)


def test_classification_keys_without_proba():
    result = compute_metrics("classification", [0, 1, 1, 0], [0, 1, 1, 0])
    assert set(result) == {"f1", "accuracy"}


def test_classification_keys_with_proba():
    result = compute_metrics(
        "classification", [0, 1, 1, 0], [0, 1, 1, 0], y_proba=[0.1, 0.9, 0.8, 0.2]
    )
    assert set(result) == {"f1", "accuracy", "auc"}


def test_all_values_are_plain_floats():
    """MLflow and json.dumps both choke on numpy scalars."""
    result = compute_metrics("regression", np.array([1.0, 2.0]), np.array([1.1, 2.1]))
    for value in result.values():
        assert type(value) is float
    json.dumps(result)


def test_invalid_task_type_raises():
    with pytest.raises(ValueError, match="task_type"):
        compute_metrics("clustering", [1.0], [1.0])
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_metrics.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.metrics'`

- [ ] **Step 3: Viết `common/ml_common/metrics.py`**

```python
"""Metrics shared by train and evaluate.

Regression metrics come out in the target's own units (dollars), because the
Pipeline already undid the log transform. A number the dashboard cannot read is
a number nobody acts on.
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)

from . import schema


def compute_metrics(task_type: str, y_true, y_pred, y_proba=None) -> dict[str, float]:
    """Computes the metrics that matter for a task type.

    Args:
        task_type: "regression" or "classification".
        y_true: observed values.
        y_pred: predicted values, already in the target's own units.
        y_proba: positive-class probabilities; classification only. AUC is left
            out when this is None, rather than guessed at.

    Returns:
        Plain Python floats — numpy scalars break json.dumps and MLflow logging.
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}")

    if task_type == "regression":
        return {
            "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
            "mae": float(mean_absolute_error(y_true, y_pred)),
            "r2": float(r2_score(y_true, y_pred)),
        }

    result = {
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
    }
    if y_proba is not None:
        result["auc"] = float(roc_auc_score(y_true, y_proba))
    return result
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_metrics.py -v`
Expected: PASS, 7 test

- [ ] **Step 5: Chạy toàn bộ test và lint**

Run:
```powershell
.venv\Scripts\python.exe -m pytest common/ -q
.venv\Scripts\python.exe -m ruff check common/
```
Expected: 184 passed, `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add common/ml_common/metrics.py common/tests/test_metrics.py
git commit -m "feat: tinh metric theo task_type, regression tra don vi goc"
```

---

## Task 5: `gates.py` — hai cổng của evaluate

**Files:**
- Create: `common/ml_common/gates.py`
- Test: `common/tests/test_gates.py`

**Interfaces:**
- Consumes: `schema.TASK_TYPES`
- Produces:
  - `gates.FLOOR: dict[str, tuple[str, float]]` — metric và ngưỡng sàn theo task_type
  - `gates.COMPARISON: dict[str, tuple[str, str]]` — metric so sánh và hướng tốt (`"higher"` / `"lower"`)
  - `gates.evaluate_gates(task_type: str, candidate: dict, champion: dict | None) -> dict`

Kết quả trả về có các khoá: `passed` (bool), `floor_passed` (bool), `beats_champion` (bool | None), `reason` (str).

`beats_champion` là `None` khi chưa có champion — khác hẳn `False`, và ghi lại được vì sao một model được promote.

Ngưỡng theo spec mục 7.5: regression R² ≥ 0.75, classification F1 ≥ 0.70. Metric so sánh: regression RMSE (thấp hơn là tốt), classification F1 (cao hơn là tốt).

- [ ] **Step 1: Viết test**

Tạo `common/tests/test_gates.py`:

```python
"""Tests for the two gates that decide whether a model gets promoted.

These rules are the only thing standing between a bad model and production, so
each branch gets its own test.
"""

import pytest

from ml_common.gates import evaluate_gates


def test_passes_both_gates():
    result = evaluate_gates(
        "regression", candidate={"r2": 0.80, "rmse": 1000.0}, champion={"r2": 0.78, "rmse": 1200.0}
    )
    assert result["passed"] is True
    assert result["floor_passed"] is True
    assert result["beats_champion"] is True


def test_below_floor_is_blocked_even_without_a_champion():
    result = evaluate_gates("regression", candidate={"r2": 0.10, "rmse": 9000.0}, champion=None)
    assert result["passed"] is False
    assert result["floor_passed"] is False


def test_above_floor_with_no_champion_passes():
    """First model ever: only gate one applies."""
    result = evaluate_gates("regression", candidate={"r2": 0.80, "rmse": 1000.0}, champion=None)
    assert result["passed"] is True
    assert result["beats_champion"] is None


def test_above_floor_but_worse_than_champion_is_blocked():
    result = evaluate_gates(
        "regression", candidate={"r2": 0.76, "rmse": 1500.0}, champion={"r2": 0.90, "rmse": 900.0}
    )
    assert result["passed"] is False
    assert result["floor_passed"] is True
    assert result["beats_champion"] is False


def test_exactly_at_the_floor_passes():
    """The spec says R2 >= 0.75, so 0.75 is a pass."""
    result = evaluate_gates("regression", candidate={"r2": 0.75, "rmse": 1000.0}, champion=None)
    assert result["floor_passed"] is True


def test_tying_the_champion_is_not_beating_it():
    result = evaluate_gates(
        "regression", candidate={"r2": 0.80, "rmse": 1000.0}, champion={"r2": 0.80, "rmse": 1000.0}
    )
    assert result["beats_champion"] is False
    assert result["passed"] is False


def test_classification_uses_f1_for_both_gates():
    result = evaluate_gates(
        "classification", candidate={"f1": 0.75}, champion={"f1": 0.70}
    )
    assert result["passed"] is True


def test_classification_below_floor_is_blocked():
    result = evaluate_gates("classification", candidate={"f1": 0.65}, champion=None)
    assert result["passed"] is False


def test_reason_names_the_gate_that_blocked():
    below_floor = evaluate_gates("regression", candidate={"r2": 0.1, "rmse": 9.0}, champion=None)
    assert "floor" in below_floor["reason"].lower()

    worse = evaluate_gates(
        "regression", candidate={"r2": 0.76, "rmse": 1500.0}, champion={"r2": 0.9, "rmse": 900.0}
    )
    assert "champion" in worse["reason"].lower()


def test_missing_metric_raises_rather_than_guessing():
    with pytest.raises(KeyError):
        evaluate_gates("regression", candidate={"mae": 100.0}, champion=None)


def test_invalid_task_type_raises():
    with pytest.raises(ValueError, match="task_type"):
        evaluate_gates("clustering", candidate={"r2": 0.9}, champion=None)
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_gates.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.gates'`

- [ ] **Step 3: Viết `common/ml_common/gates.py`**

```python
"""The two gates that decide whether a trained model may be promoted.

Gate one blocks junk on an absolute threshold. Gate two blocks a model that is
merely adequate from replacing a better one already in production — both
measured on the same test split, which is why that split has a fixed seed.
"""

from __future__ import annotations

from . import schema

FLOOR: dict[str, tuple[str, float]] = {
    "regression": ("r2", 0.75),
    "classification": ("f1", 0.70),
}

COMPARISON: dict[str, tuple[str, str]] = {
    "regression": ("rmse", "lower"),
    "classification": ("f1", "higher"),
}


def _is_better(candidate_value: float, champion_value: float, direction: str) -> bool:
    """A tie is not an improvement: the incumbent keeps its place."""
    if direction == "lower":
        return candidate_value < champion_value
    return candidate_value > champion_value


def evaluate_gates(task_type: str, candidate: dict, champion: dict | None) -> dict:
    """Decides whether a candidate model may take the champion alias.

    Args:
        task_type: "regression" or "classification".
        candidate: metrics of the model just trained.
        champion: metrics of the current champion on the SAME test split, or
            None when no model has been promoted yet.

    Returns:
        A dict with `passed`, `floor_passed`, `beats_champion` (None when there
        is no champion to compare against) and a human-readable `reason`.

    Raises:
        KeyError: when a metric a gate needs is absent. Guessing here would
            silently promote a model nobody measured.
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}")

    floor_metric, floor_value = FLOOR[task_type]
    candidate_floor = candidate[floor_metric]
    floor_passed = candidate_floor >= floor_value

    if not floor_passed:
        return {
            "passed": False,
            "floor_passed": False,
            "beats_champion": None,
            "reason": (
                f"below the floor: {floor_metric}={candidate_floor:.4f} "
                f"< {floor_value} required"
            ),
        }

    if champion is None:
        return {
            "passed": True,
            "floor_passed": True,
            "beats_champion": None,
            "reason": f"passed the floor ({floor_metric}={candidate_floor:.4f}); no champion yet",
        }

    compare_metric, direction = COMPARISON[task_type]
    candidate_value = candidate[compare_metric]
    champion_value = champion[compare_metric]
    beats_champion = _is_better(candidate_value, champion_value, direction)

    if not beats_champion:
        return {
            "passed": False,
            "floor_passed": True,
            "beats_champion": False,
            "reason": (
                f"does not beat the champion: {compare_metric}={candidate_value:.4f} "
                f"vs {champion_value:.4f} ({direction} is better)"
            ),
        }

    return {
        "passed": True,
        "floor_passed": True,
        "beats_champion": True,
        "reason": (
            f"passed the floor and beat the champion: {compare_metric}="
            f"{candidate_value:.4f} vs {champion_value:.4f}"
        ),
    }
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_gates.py -v`
Expected: PASS, 11 test

- [ ] **Step 5: Chạy toàn bộ test, lint, và build lại image nền**

Run:
```powershell
.venv\Scripts\python.exe -m pytest common/ -q
.venv\Scripts\python.exe -m ruff check common/
powershell -ExecutionPolicy Bypass -File scripts\build_base_image.ps1
docker run --rm ml-base:latest sh -c "pip install --quiet 'pytest>=8.0' 'moto[s3]>=5.0' && python -m pytest /app/common/tests -q"
```
Expected: 195 passed ở cả hai môi trường, `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add common/ml_common/gates.py common/tests/test_gates.py
git commit -m "feat: hai cong quyet dinh promote model"
```

---

## Task 6: `targets.py` — parse cột target

**Files:**
- Create: `common/ml_common/targets.py`
- Test: `common/tests/test_targets.py`

**Interfaces:**
- Consumes: `parsers.parse_money`, `parsers.parse_bool`, `schema.COLUMNS`, `schema.target_column()`
- Produces: `targets.parse_target(series: pd.Series, task_type: str) -> pd.Series`

**Vì sao task này tồn tại.** `sklearn.Pipeline` chỉ biến đổi `X`, không đụng `y`. Mà target cũng là cột thô: `sale_price` có `kind="money"` nên giá trị là `"$450,000"`, còn `sold_within_30_days` có `kind="boolean"` nên giá trị là `"Y"` / `"1"` / `"True"`. Không parse thì `pipeline.fit(X, y)` nhận `y` là chuỗi và nổ.

**Vì sao làm ở đây không gây training/serving skew.** Target **không phải feature**. Lúc serve, `/predict` không có target — đó chính là thứ đang được hỏi. Nên không có đường nào để logic này lệch giữa train và serve, khác hẳn với cột feature.

**Nó dùng lại parser có sẵn, không chép logic.** `parse_money` và `parse_bool` là đúng hai hàm mà `RawRecordCleaner` dùng cho hai `kind` đó.

- [ ] **Step 1: Viết test**

Tạo `common/tests/test_targets.py`:

```python
"""Tests for target parsing — the one column the Pipeline never touches."""

import numpy as np
import pandas as pd
import pytest

from ml_common.targets import parse_target


def test_regression_target_parses_money_strings():
    series = pd.Series(["$450,000", "320000", "$1,200,500.50"])
    result = parse_target(series, "regression")
    assert list(result) == [450000.0, 320000.0, 1200500.50]


def test_classification_target_parses_every_boolean_form():
    series = pd.Series(["Y", "no", "1", "True"])
    result = parse_target(series, "classification")
    assert list(result) == [True, False, True, True]


def test_unparseable_value_becomes_null_not_a_guess():
    series = pd.Series(["$450,000", "not a price", None])
    result = parse_target(series, "regression")
    assert result[0] == 450000.0
    assert pd.isna(result[1])
    assert pd.isna(result[2])


def test_already_numeric_target_survives():
    """Running twice must not corrupt the values."""
    series = pd.Series([450000.0, 320000.0])
    result = parse_target(series, "regression")
    assert list(result) == [450000.0, 320000.0]


def test_index_is_preserved():
    """The caller lines this up against the feature rows, so the index must match."""
    series = pd.Series(["$1", "$2"], index=[10, 20])
    result = parse_target(series, "regression")
    assert list(result.index) == [10, 20]


def test_regression_result_is_numeric_dtype():
    result = parse_target(pd.Series(["$450,000", "$1"]), "regression")
    assert np.issubdtype(result.dtype, np.number)


def test_empty_series_does_not_crash():
    result = parse_target(pd.Series([], dtype=object), "regression")
    assert len(result) == 0


def test_invalid_task_type_raises():
    with pytest.raises(ValueError, match="task_type"):
        parse_target(pd.Series(["$1"]), "clustering")
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_targets.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.targets'`

- [ ] **Step 3: Viết `common/ml_common/targets.py`**

```python
"""Parses the target column, which the Pipeline never sees.

sklearn transformers act on X, not y, so the target arrives at fit() exactly as
raw as it was in the file: "$450,000" for regression, "Y" for classification.
This module applies the same parser RawRecordCleaner would have used for that
column kind.

Doing this outside the Pipeline is safe in a way that cleaning a FEATURE would
not be: serving has no target — it is the thing being asked for — so there is no
second code path this could drift from.
"""

from __future__ import annotations

import pandas as pd

from . import parsers, schema

_PARSER_BY_KIND = {
    "money": parsers.parse_money,
    "boolean": parsers.parse_bool,
}


def parse_target(series: pd.Series, task_type: str) -> pd.Series:
    """Converts a raw target column into values a model can be fitted on.

    Args:
        series: the raw target column.
        task_type: "regression" or "classification".

    Returns:
        A Series with the same index. Values that cannot be parsed become null
        rather than a guess, so the caller can count and drop them.
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}")

    target_name = schema.target_column(task_type)
    kind = schema.COLUMNS[target_name].kind
    parser = _PARSER_BY_KIND.get(kind)
    if parser is None:
        raise ValueError(f"no target parser for column {target_name!r} of kind {kind!r}")

    parsed = pd.Series([parser(value) for value in series], index=series.index)
    if kind == "money":
        return pd.to_numeric(parsed, errors="coerce")
    return parsed
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_targets.py -v`
Expected: PASS, 8 test

- [ ] **Step 5: Chạy toàn bộ test và lint**

Run:
```powershell
.venv\Scripts\python.exe -m pytest common/ -q
.venv\Scripts\python.exe -m ruff check common/
```
Expected: 203 passed, `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add common/ml_common/targets.py common/tests/test_targets.py
git commit -m "feat: parse cot target, thu Pipeline khong bao gio dung toi"
```

---

## Task 7: Image nền có MLflow, và seed raw data lên MinIO

**Files:**
- Modify: `stages/base/Dockerfile`
- Modify: `common/ml_common/storage.py` (thêm `Storage.upload_file`)
- Create: `scripts/seed_raw_data.py`
- Test: `common/tests/test_storage.py` (thêm)

**Interfaces:**
- Consumes: `storage.Storage`, `storage.raw_key()`
- Produces: `raw/v1/data.parquet` tồn tại thật trên MinIO; `ml-base:latest` có `mlflow`; `Storage.upload_file(local_path: str, key: str) -> None`

**Vì sao `mlflow` vào image nền chứ không cài riêng từng stage:** ba stage `train`, `evaluate`, `register` đều cần nó, và serving ở Plan 3 cũng `FROM ml-base`. Cài một chỗ thì version khoá ở một chỗ — đúng lập luận đã chọn `DockerOperator` ngay từ đầu.

**Vì sao cần `upload_file`:** file CSV 373MB / 2 triệu dòng. Đọc hết vào pandas rồi `write_parquet` sẽ ngốn vài GB RAM trên máy 16GB đang chạy 5 container. Ghi parquet ra đĩa theo từng chunk rồi upload cả file là cách duy nhất không chạm trần.

- [ ] **Step 1: Kiểm tra dung lượng đĩa**

Run: `.venv\Scripts\python.exe -c "import shutil; print(f'{shutil.disk_usage(\"C:/\").free/2**30:.1f} GB free')"`
Expected: ≥ 8 GB. Ít hơn thì dừng và báo.

- [ ] **Step 2: Viết test cho `upload_file`**

Thêm vào `common/tests/test_storage.py`. Bộ test này đã dùng `moto` — tra cách các test khác dựng fixture rồi theo đúng pattern đó:

```python
def test_upload_file_puts_the_bytes_on_storage(storage_client, tmp_path):
    local = tmp_path / "data.parquet"
    pd.DataFrame({"a": [1, 2, 3]}).to_parquet(local, index=False)

    storage_client.upload_file(str(local), "raw/v1/data.parquet")

    assert storage_client.exists("raw/v1/data.parquet")
    restored = storage_client.read_parquet("raw/v1/data.parquet")
    assert list(restored["a"]) == [1, 2, 3]


def test_upload_file_missing_local_path_raises(storage_client, tmp_path):
    with pytest.raises(FileNotFoundError):
        storage_client.upload_file(str(tmp_path / "nope.parquet"), "raw/v1/data.parquet")
```

- [ ] **Step 3: Chạy test để xác nhận fail**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_storage.py -k upload_file -v`
Expected: FAIL với `AttributeError: 'Storage' object has no attribute 'upload_file'`

- [ ] **Step 4: Thêm `upload_file` vào class `Storage`**

Chèn ngay sau `write_bytes`:

```python
    def upload_file(self, local_path: str, key: str) -> None:
        """Uploads a file from disk without reading it into memory first.

        Used for seeding raw data: the source CSV is hundreds of megabytes, and
        materializing it as a DataFrame just to upload it would not fit.
        """
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"Local file not found: {local_path}")
        self._client.upload_file(local_path, self.bucket, key)
```

- [ ] **Step 5: Chạy test để xác nhận pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_storage.py -k upload_file -v`
Expected: PASS, 2 test

- [ ] **Step 6: Thêm `mlflow` vào `stages/base/Dockerfile`**

Sửa khối `RUN pip install` đang có thành:

```dockerfile
# Install dependencies first, copy code after: code changes don't bust this layer's cache.
COPY common/pyproject.toml /app/common/pyproject.toml
RUN mkdir -p /app/common/ml_common \
    && touch /app/common/ml_common/__init__.py \
    && pip install --no-cache-dir -e /app/common \
    && pip install --no-cache-dir "mlflow>=2.14,<3"
```

`mlflow` cài ở đây chứ không nằm trong `common/pyproject.toml` vì package `ml_common` không import `mlflow` — chỉ stage mới import. Đưa vào dependency của package sẽ bắt mọi người dùng `ml_common` kéo theo cả MLflow.

- [ ] **Step 7: Build lại image nền và xác nhận mlflow có mặt**

Run:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_base_image.ps1
docker run --rm ml-base:latest python -c "import mlflow, sklearn; print('mlflow', mlflow.__version__, '| sklearn', sklearn.__version__)"
```
Expected: in ra mlflow 2.x và sklearn 1.x.

- [ ] **Step 8: Viết `scripts/seed_raw_data.py`**

```python
"""Seeds the raw dataset into MinIO. Run once, by hand, from the repo root.

The pipeline's `extract` stage reads only from object storage, the way a real
system does: raw data is delivered by something upstream, not produced by the
pipeline itself. This script is that upstream delivery, done by hand.
"""

from __future__ import annotations

import argparse
import os
import tempfile

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ml_common.storage import Storage, raw_key

CHUNK_ROWS = 200_000
DEFAULT_SOURCE = "house_pricing_dirty.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload the raw CSV to object storage.")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="local CSV to upload")
    parser.add_argument("--version", default="v1", help="dataset version to write under")
    parser.add_argument("--limit", type=int, default=None, help="stop after this many rows")
    return parser.parse_args()


def csv_to_parquet(source: str, destination: str, limit: int | None) -> int:
    """Streams the CSV into a parquet file, a chunk at a time.

    Every column is read as text on purpose: this is the RAW copy, and parsing
    belongs to the Pipeline. Letting pandas infer types here would quietly fix
    some of the dirt the pipeline exists to handle.
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
            print(f"  ... {written:,} rows")
            if limit is not None and written >= limit:
                break
    finally:
        if writer is not None:
            writer.close()
    return written


def main() -> int:
    args = parse_args()
    if not os.path.isfile(args.source):
        raise SystemExit(f"Source CSV not found: {args.source}. Run this from the repo root.")

    storage = Storage.from_env()
    key = raw_key(args.version)

    with tempfile.TemporaryDirectory() as workdir:
        local_parquet = os.path.join(workdir, "data.parquet")
        print(f"Converting {args.source} -> parquet")
        row_count = csv_to_parquet(args.source, local_parquet, args.limit)
        size_mb = os.path.getsize(local_parquet) / 2**20
        print(f"Uploading {size_mb:.1f} MB to {key}")
        storage.upload_file(local_parquet, key)

    print(f"Seeded {row_count:,} rows to {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 9: Seed thử một bản nhỏ trước**

Chạy bản nhỏ trước để bắt lỗi nhanh, đừng chờ 2 triệu dòng mới biết sai:

```powershell
.venv\Scripts\python.exe scripts\seed_raw_data.py --limit 5000 --version v-smoke
```
Expected: in tiến độ rồi `Seeded 5,000 rows to raw/v-smoke/data.parquet`

- [ ] **Step 10: Xác nhận object có thật trên MinIO và dữ liệu vẫn còn bẩn**

Run:
```powershell
.venv\Scripts\python.exe -c "from ml_common.storage import Storage, raw_key; s=Storage.from_env(); df=s.read_parquet(raw_key('v-smoke')); print(df.shape); print(df.dtypes.unique()); print(df['list_price'].head(3).tolist())"
```
Expected: `(5000, 24)`, dtype toàn `object`, và `list_price` còn giá trị dạng chuỗi.

Nếu dtype đã là số thì `dtype=str` chưa có tác dụng — dừng lại và sửa, vì raw phải giữ nguyên độ bẩn.

- [ ] **Step 11: Seed bản đầy đủ**

Run: `.venv\Scripts\python.exe scripts\seed_raw_data.py`
Expected: `Seeded 2,0xx,xxx rows to raw/v1/data.parquet`. Mất vài phút.

- [ ] **Step 12: Xác nhận bản đầy đủ**

Run:
```powershell
.venv\Scripts\python.exe -c "from ml_common.storage import Storage, raw_key; s=Storage.from_env(); print(s.exists(raw_key('v1'))); print(s.object_etag(raw_key('v1')))"
```
Expected: `True` và một chuỗi ETag.

- [ ] **Step 13: Chạy toàn bộ test và lint**

Run:
```powershell
.venv\Scripts\python.exe -m pytest common/ -q
.venv\Scripts\python.exe -m ruff check common/ scripts/
```
Expected: 205 passed, `All checks passed!`

- [ ] **Step 14: Commit**

```bash
git add common/ml_common/storage.py common/tests/test_storage.py stages/base/Dockerfile scripts/seed_raw_data.py
git commit -m "feat: mlflow vao image nen va script seed raw data len MinIO"
```

---

## Task 8: Stage `extract`

**Files:**
- Create: `stages/extract/Dockerfile`, `stages/extract/main.py`

**Interfaces:**
- Consumes: `storage.raw_key()`, `storage.extracted_key()`, `storage.Storage.object_etag()`, `fingerprint.compute_fingerprint()`
- Produces: `extracted/{fingerprint}/data.parquet`; XCom `{"fingerprint": str, "row_count": int}`

**Biến môi trường đọc vào:** `DATASET_VERSION` (mặc định `v1`), `SAMPLE_ROWS` (rỗng = lấy hết), cộng `MINIO_*` và `ML_BUCKET` mà `Storage.from_env()` cần.

**Quy ước chung cho mọi stage, áp dụng từ task này trở đi:**
- Log cho người đọc đi ra **stderr**.
- **Dòng cuối cùng trên stdout là một dòng JSON duy nhất** — `DockerOperator` lấy đúng dòng đó làm XCom.
- Exit code 0 là thành công, khác 0 là fail task.

- [ ] **Step 1: Viết `stages/extract/main.py`**

```python
"""Extract stage: pick the rows this run will use and park them under a fingerprint.

Reads the raw dataset from object storage, applies SAMPLE_ROWS, and writes the
result to a fingerprint-addressed prefix. The fingerprint computed here is what
every later stage uses to find its input.
"""

from __future__ import annotations

import json
import os
import sys

from ml_common.fingerprint import compute_fingerprint
from ml_common.storage import Storage, extracted_key, raw_key


def read_sample_rows() -> int | None:
    """Reads SAMPLE_ROWS, treating empty or unset as 'use every row'."""
    raw_value = os.environ.get("SAMPLE_ROWS", "").strip()
    if not raw_value:
        return None
    return int(raw_value)


def main() -> int:
    dataset_version = os.environ.get("DATASET_VERSION", "v1")
    sample_rows = read_sample_rows()
    storage = Storage.from_env()

    source = raw_key(dataset_version)
    etag = storage.object_etag(source)
    fingerprint = compute_fingerprint(dataset_version, etag, sample_rows)
    destination = extracted_key(fingerprint)

    print(f"raw={source} etag={etag} sample_rows={sample_rows}", file=sys.stderr)

    if storage.exists(destination):
        row_count = len(storage.read_parquet(destination))
        print(f"reusing existing {destination}", file=sys.stderr)
    else:
        df = storage.read_parquet(source)
        if sample_rows is not None:
            df = df.head(sample_rows)
        storage.write_parquet(df, destination)
        row_count = len(df)
        print(f"wrote {row_count} rows to {destination}", file=sys.stderr)

    print(json.dumps({"fingerprint": fingerprint, "row_count": int(row_count)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Viết `stages/extract/Dockerfile`**

```dockerfile
# Extract stage. Build from the repo root:
#   docker build -f stages/extract/Dockerfile -t ml-extract:latest .
FROM ml-base:latest

COPY stages/extract/main.py /app/main.py

ENTRYPOINT ["python", "/app/main.py"]
```

- [ ] **Step 3: Build image**

Run: `docker build -f stages/extract/Dockerfile -t ml-extract:latest .`
Expected: build thành công, dòng cuối `naming to docker.io/library/ml-extract:latest`

- [ ] **Step 4: Chạy tay với bản nhỏ và xác nhận output**

```powershell
docker run --rm --network mlops_default --env-file .env -e MINIO_ENDPOINT_INTERNAL=http://minio:9000 -e DATASET_VERSION=v-smoke -e SAMPLE_ROWS=1000 ml-extract:latest
```
Expected: stderr có `wrote 1000 rows to extracted/...`, và **dòng cuối trên stdout** là JSON dạng `{"fingerprint": "....", "row_count": 1000}`

Ghi lại giá trị `fingerprint` — các step sau dùng nó.

- [ ] **Step 5: Xác nhận fingerprint đổi khi SAMPLE_ROWS đổi**

Chạy lại lệnh Step 4 nhưng `-e SAMPLE_ROWS=500`.
Expected: `fingerprint` khác hẳn lần trước. Nếu giống nhau thì cache sẽ bị dùng nhầm — dừng lại và sửa.

- [ ] **Step 6: Xác nhận chạy lại cùng tham số thì dùng lại file cũ**

Chạy lại đúng lệnh Step 4.
Expected: stderr in `reusing existing extracted/...`, `fingerprint` y hệt Step 4.

- [ ] **Step 7: Xác nhận object nằm thật trên MinIO**

Run: `docker compose exec minio mc ls --recursive local/ml-pipeline/extracted/`
Expected: liệt kê `data.parquet` dưới các prefix fingerprint vừa tạo.

Nếu `mc` báo Access Denied, chạy `docker compose exec minio mc alias set local http://localhost:9000 minioadmin minioadmin` trước — alias mặc định trong container `minio` không có credential.

- [ ] **Step 8: Commit**

```bash
git add stages/extract/
git commit -m "feat: stage extract, tinh fingerprint va ghi ban lam viec"
```

---

## Task 9: Stage `validate`

**Files:**
- Create: `stages/validate/Dockerfile`, `stages/validate/main.py`

**Interfaces:**
- Consumes: `storage.extracted_key()`, `storage.validation_report_key()`, `validation.validate_dataframe()`
- Produces: `reports/validation/{fingerprint}.json`; XCom `{"ok": bool, "row_count": int}`

**Biến môi trường:** `FINGERPRINT` (bắt buộc), `TASK_TYPE` (bắt buộc).

Exit code 1 khi `ok` là false — đó là cách task fail và chặn DAG.

- [ ] **Step 1: Viết `stages/validate/main.py`**

```python
"""Validate stage: measure the dataset, block only what cannot be trained on.

The dataset is dirty by design, so this stage counts the mess and reports it
rather than refusing to work with it. It fails the run for exactly three
reasons, all of them "there is nothing here to train on".
"""

from __future__ import annotations

import json
import os
import sys

from ml_common.storage import Storage, extracted_key, validation_report_key
from ml_common.validation import validate_dataframe


def main() -> int:
    fingerprint = os.environ["FINGERPRINT"]
    task_type = os.environ["TASK_TYPE"]
    storage = Storage.from_env()

    df = storage.read_parquet(extracted_key(fingerprint))
    report = validate_dataframe(df, task_type)

    report_destination = validation_report_key(fingerprint)
    storage.write_json(report, report_destination)
    print(f"report written to {report_destination}", file=sys.stderr)
    print(f"rows={report['row_count']} duplicates={report['duplicate_rows']}", file=sys.stderr)

    for column_name, counts in sorted(report["columns"].items()):
        if counts["missing_rate"] > 0 or counts["out_of_bounds"] > 0:
            print(
                f"  {column_name}: missing={counts['missing_rate']:.1%} "
                f"out_of_bounds={counts['out_of_bounds']}",
                file=sys.stderr,
            )

    for reason in report["fatal"]:
        print(f"FATAL: {reason}", file=sys.stderr)

    print(json.dumps({"ok": report["ok"], "row_count": report["row_count"]}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Viết `stages/validate/Dockerfile`**

```dockerfile
# Validate stage. Build from the repo root:
#   docker build -f stages/validate/Dockerfile -t ml-validate:latest .
FROM ml-base:latest

COPY stages/validate/main.py /app/main.py

ENTRYPOINT ["python", "/app/main.py"]
```

- [ ] **Step 3: Build image**

Run: `docker build -f stages/validate/Dockerfile -t ml-validate:latest .`
Expected: build thành công

- [ ] **Step 4: Chạy tay trên fingerprint đã tạo ở Task 8**

Thay `<FP>` bằng fingerprint ghi lại ở Task 8 Step 4:

```powershell
docker run --rm --network mlops_default --env-file .env -e MINIO_ENDPOINT_INTERNAL=http://minio:9000 -e FINGERPRINT=<FP> -e TASK_TYPE=regression ml-validate:latest
echo $LASTEXITCODE
```
Expected: stderr in thống kê từng cột bẩn, stdout dòng cuối `{"ok": true, "row_count": 1000}`, exit code `0`.

- [ ] **Step 5: Xác nhận report nằm trên MinIO và đọc được**

```powershell
.venv\Scripts\python.exe -c "from ml_common.storage import Storage, validation_report_key; s=Storage.from_env(); r=s.read_json(validation_report_key('<FP>')); print(r['ok'], r['row_count'], r['duplicate_rows'])"
```
Expected: in ra `True`, số dòng, số bản trùng.

- [ ] **Step 6: Xác nhận stage thật sự fail được**

Dữ liệu bẩn phải pass, nhưng dữ liệu vô dụng phải fail:

```powershell
.venv\Scripts\python.exe -c "import pandas as pd; from ml_common.storage import Storage, extracted_key; s=Storage.from_env(); s.write_parquet(pd.DataFrame({'property_id':['1','2']}), extracted_key('broken'))"
docker run --rm --network mlops_default --env-file .env -e MINIO_ENDPOINT_INTERNAL=http://minio:9000 -e FINGERPRINT=broken -e TASK_TYPE=regression ml-validate:latest
echo $LASTEXITCODE
```
Expected: stderr in `FATAL: missing columns ...`, stdout `{"ok": false, ...}`, **exit code 1**.

Nếu exit code là 0 thì cổng này vô dụng — dừng lại và sửa.

- [ ] **Step 7: Commit**

```bash
git add stages/validate/
git commit -m "feat: stage validate, dem du lieu ban va chan du lieu vo dung"
```

---

## Task 10: Stage `prepare_dataset_for_train`

**Files:**
- Create: `stages/prepare_dataset_for_train/Dockerfile`, `stages/prepare_dataset_for_train/main.py`

**Interfaces:**
- Consumes: `storage.extracted_key()`, `storage.processed_key()`, `rowops.drop_duplicates()`, `rowops.drop_rows_missing_target()`, `targets.parse_target()`, `schema.target_column()`
- Produces: `processed/{fp}/train.parquet` và `processed/{fp}/test.parquet`; XCom `{"skipped": bool, "train_rows": int, "test_rows": int}`

**Biến môi trường:** `FINGERPRINT`, `TASK_TYPE`, `FORCE_REPROCESS` (chuỗi `"true"`/`"false"`).

**Stage này KHÔNG làm sạch theo cột.** Nó chỉ làm ba việc theo dòng rồi chia tập. Cột feature trong file nó ghi ra **vẫn còn thô** — `"$450,000"`, `"NEW YORK"`, zipcode 4 số. Việc làm sạch cột nằm trong `Pipeline` và được fit ở stage `train`, để model tự chứa logic đó và serving không phải chép lại. Xem mục 2.2 của spec.

**Ngoại lệ duy nhất là cột target.** Target không phải feature — serving không bao giờ có nó — nên parse nó ở đây là an toàn, và bắt buộc: parse trước rồi mới drop, để những target không parse nổi cũng bị loại thay vì trôi xuống `train` rồi làm `fit()` nổ vì `y` có NaN.

**Seed `42` là bắt buộc, không phải tuỳ chọn.** Cổng thứ hai của `evaluate` so ứng viên với champion **trên cùng `test.parquet`**. Test set đổi giữa hai lần train thì phép so sánh đó vô nghĩa.

- [ ] **Step 1: Viết `stages/prepare_dataset_for_train/main.py`**

```python
"""Prepare stage: row-level work and the train/test split. Nothing column-level.

Column cleaning deliberately does NOT happen here. It lives inside the sklearn
Pipeline so it ships with the model and runs identically at serving time. The
files this stage writes still hold raw column values.

The target is the one exception: it is not a feature, serving never sends one,
so parsing it here cannot drift from anything.
"""

from __future__ import annotations

import json
import os
import sys

from sklearn.model_selection import train_test_split

from ml_common import schema
from ml_common.rowops import drop_duplicates, drop_rows_missing_target
from ml_common.storage import Storage, extracted_key, processed_key
from ml_common.targets import parse_target

TEST_SIZE = 0.2
RANDOM_STATE = 42


def main() -> int:
    fingerprint = os.environ["FINGERPRINT"]
    task_type = os.environ["TASK_TYPE"]
    force = os.environ.get("FORCE_REPROCESS", "false").strip().lower() == "true"
    storage = Storage.from_env()

    train_destination = processed_key(fingerprint, "train")
    test_destination = processed_key(fingerprint, "test")

    already_there = storage.exists(train_destination) and storage.exists(test_destination)
    if already_there and not force:
        train_rows = len(storage.read_parquet(train_destination))
        test_rows = len(storage.read_parquet(test_destination))
        print(f"cache hit for {fingerprint}, skipping", file=sys.stderr)
        print(
            json.dumps({"skipped": True, "train_rows": train_rows, "test_rows": test_rows})
        )
        return 0

    if already_there:
        print("cache present but FORCE_REPROCESS is set, rebuilding", file=sys.stderr)

    df = storage.read_parquet(extracted_key(fingerprint))
    print(f"read {len(df)} rows", file=sys.stderr)

    df, duplicate_count = drop_duplicates(df)
    print(f"dropped {duplicate_count} duplicate rows", file=sys.stderr)

    target = schema.target_column(task_type)
    df[target] = parse_target(df[target], task_type)

    df, missing_target_count = drop_rows_missing_target(df, task_type)
    print(f"dropped {missing_target_count} rows with an unusable target", file=sys.stderr)

    if len(df) < 2:
        print("FATAL: not enough usable rows to split", file=sys.stderr)
        return 1

    train_df, test_df = train_test_split(df, test_size=TEST_SIZE, random_state=RANDOM_STATE)
    storage.write_parquet(train_df, train_destination)
    storage.write_parquet(test_df, test_destination)
    print(f"wrote {len(train_df)} train / {len(test_df)} test rows", file=sys.stderr)

    print(
        json.dumps(
            {
                "skipped": False,
                "train_rows": int(len(train_df)),
                "test_rows": int(len(test_df)),
                "dropped_duplicates": int(duplicate_count),
                "dropped_missing_target": int(missing_target_count),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Viết `stages/prepare_dataset_for_train/Dockerfile`**

```dockerfile
# Prepare-dataset stage. Build from the repo root:
#   docker build -f stages/prepare_dataset_for_train/Dockerfile -t ml-prepare-dataset:latest .
FROM ml-base:latest

COPY stages/prepare_dataset_for_train/main.py /app/main.py

ENTRYPOINT ["python", "/app/main.py"]
```

- [ ] **Step 3: Build image**

Run: `docker build -f stages/prepare_dataset_for_train/Dockerfile -t ml-prepare-dataset:latest .`
Expected: build thành công

- [ ] **Step 4: Chạy tay lần đầu**

Thay `<FP>` bằng fingerprint từ Task 8:

```powershell
docker run --rm --network mlops_default --env-file .env -e MINIO_ENDPOINT_INTERNAL=http://minio:9000 -e FINGERPRINT=<FP> -e TASK_TYPE=regression -e FORCE_REPROCESS=false ml-prepare-dataset:latest
```
Expected: stderr in số dòng trùng và số dòng target hỏng đã bỏ; stdout dòng cuối `{"skipped": false, "train_rows": ..., "test_rows": ...}` với tỉ lệ khoảng 80/20.

- [ ] **Step 5: Chạy lại và xác nhận cache hoạt động**

Chạy lại đúng lệnh trên.
Expected: stderr in `cache hit`, stdout `{"skipped": true, ...}`.

- [ ] **Step 6: Xác nhận `FORCE_REPROCESS` phá được cache**

Chạy lại với `-e FORCE_REPROCESS=true`.
Expected: stderr in `cache present but FORCE_REPROCESS is set, rebuilding`, stdout `{"skipped": false, ...}`.

- [ ] **Step 7: Xác nhận file ghi ra vẫn thô ở mức cột, nhưng target đã parse**

Đây là bước quan trọng nhất của task — nó chứng minh ranh giới kiến trúc ở mục 2.2 được tôn trọng:

```powershell
.venv\Scripts\python.exe -c "from ml_common.storage import Storage, processed_key; s=Storage.from_env(); df=s.read_parquet(processed_key('<FP>','train')); print('list_price:', df['list_price'].head(3).tolist()); print('city:', df['city'].head(3).tolist()); print('sale_price dtype:', df['sale_price'].dtype)"
```
Expected:
- `list_price` vẫn là chuỗi kiểu `"$..."` hoặc chuỗi số — **chưa parse**
- `city` vẫn còn hoa/thường/gạch dưới lẫn lộn — **chưa chuẩn hoá**
- `sale_price dtype` là kiểu số — **đã parse**, vì nó là target

Nếu `list_price` hoặc `city` đã sạch thì có ai đó đã đưa logic cột vào stage này — dừng lại, đó là bug kiến trúc chứ không phải chuyện style.

- [ ] **Step 8: Commit**

```bash
git add stages/prepare_dataset_for_train/
git commit -m "feat: stage prepare_dataset_for_train, thao tac theo dong va chia tap"
```

---

## Task 11: Stage `train`

**Files:**
- Create: `stages/train/Dockerfile`, `stages/train/main.py`

**Interfaces:**
- Consumes: `storage.processed_key()`, `estimators.build_estimator()`, `features.build_pipeline()`, `metrics.compute_metrics()`, `schema.target_column()`
- Produces: một MLflow run chứa params, metrics train, và `Pipeline` đã fit ở artifact path `model`; XCom `{"run_id": str, "experiment": str, "metrics": {...}}`

**Biến môi trường:** `FINGERPRINT`, `TASK_TYPE`, `MODEL_NAME`, `ESTIMATOR_NAME` (mặc định `ridge`), `MLFLOW_TRACKING_URI`.

**Log nguyên `Pipeline`, không log riêng estimator.** `mlflow.sklearn.log_model(pipeline, ...)` đóng gói cả chuỗi làm sạch cùng model, nên model trong Registry tự chứa logic clean và `/predict` ở Plan 3 nhận record thô. Log riêng estimator là tạo ra training/serving skew ngay tại chỗ này.

- [ ] **Step 1: Viết `stages/train/main.py`**

```python
"""Train stage: fit the whole Pipeline and log it to MLflow.

What gets logged is the Pipeline, not the bare estimator. The Pipeline carries
its own cleaning steps, so the model in the Registry knows how to handle a raw
record and serving never needs a second copy of that logic.
"""

from __future__ import annotations

import json
import os
import sys

import mlflow
import mlflow.sklearn

from ml_common import schema
from ml_common.estimators import build_estimator
from ml_common.features import build_pipeline
from ml_common.metrics import compute_metrics
from ml_common.storage import Storage, processed_key


def main() -> int:
    fingerprint = os.environ["FINGERPRINT"]
    task_type = os.environ["TASK_TYPE"]
    model_name = os.environ["MODEL_NAME"]
    estimator_name = os.environ.get("ESTIMATOR_NAME", "ridge")

    storage = Storage.from_env()
    train_df = storage.read_parquet(processed_key(fingerprint, "train"))
    target = schema.target_column(task_type)

    # Drop the target so X looks exactly like a serving record does: no target.
    features = train_df.drop(columns=[target])
    y = train_df[target]
    print(f"training on {len(train_df)} rows, estimator={estimator_name}", file=sys.stderr)

    estimator = build_estimator(task_type, estimator_name)
    pipeline = build_pipeline(task_type, estimator)

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    mlflow.set_experiment(model_name)

    with mlflow.start_run() as run:
        pipeline.fit(features, y)

        mlflow.log_params(
            {
                "task_type": task_type,
                "estimator": estimator_name,
                "fingerprint": fingerprint,
                "train_rows": len(train_df),
            }
        )
        train_metrics = compute_metrics(task_type, y, pipeline.predict(features))
        mlflow.log_metrics({f"train_{name}": value for name, value in train_metrics.items()})
        # MLflow 2.x uses `artifact_path`; the `name` parameter only exists from MLflow 3.
        mlflow.sklearn.log_model(pipeline, artifact_path="model")

        run_id = run.info.run_id

    print(f"run_id={run_id} train_metrics={train_metrics}", file=sys.stderr)
    print(json.dumps({"run_id": run_id, "experiment": model_name, "metrics": train_metrics}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Viết `stages/train/Dockerfile`**

```dockerfile
# Train stage. Build from the repo root:
#   docker build -f stages/train/Dockerfile -t ml-train:latest .
FROM ml-base:latest

COPY stages/train/main.py /app/main.py

ENTRYPOINT ["python", "/app/main.py"]
```

- [ ] **Step 3: Build image**

Run: `docker build -f stages/train/Dockerfile -t ml-train:latest .`
Expected: build thành công

- [ ] **Step 4: Chạy tay với Ridge**

```powershell
docker run --rm --network mlops_default --env-file .env -e MINIO_ENDPOINT_INTERNAL=http://minio:9000 -e MLFLOW_TRACKING_URI=http://mlflow:5000 -e FINGERPRINT=<FP> -e TASK_TYPE=regression -e MODEL_NAME=house_price_regressor -e ESTIMATOR_NAME=ridge ml-train:latest
```
Expected: stdout dòng cuối `{"run_id": "...", "experiment": "house_price_regressor", "metrics": {"rmse": ..., "mae": ..., "r2": ...}}`

Ghi lại `run_id`.

**`rmse` phải là con số cỡ hàng chục nghìn đến hàng trăm nghìn (đô la).** Nếu nó nhỏ hơn 10 thì model đang dự đoán ở thang log — `TransformedTargetRegressor` chưa nghịch đảo, dừng lại và sửa Task 3.

- [ ] **Step 5: Xác nhận model nằm thật trên MinIO, không chỉ có run trong Postgres**

```powershell
docker compose exec minio mc ls --recursive local/ml-pipeline/artifacts/ | Select-String "<RUN_ID>"
```
Expected: thấy `model/MLmodel` và `model/model.pkl` dưới run đó.

- [ ] **Step 6: Xác nhận model load lại được và ăn record THÔ**

Đây là bước chứng minh cả thiết kế hoạt động:

```powershell
docker run --rm --network mlops_default --env-file .env -e MINIO_ENDPOINT_INTERNAL=http://minio:9000 -e MLFLOW_TRACKING_URI=http://mlflow:5000 --entrypoint python ml-train:latest -c "import os, mlflow, mlflow.sklearn; from ml_common.storage import Storage, processed_key; mlflow.set_tracking_uri(os.environ['MLFLOW_TRACKING_URI']); m = mlflow.sklearn.load_model('runs:/<RUN_ID>/model'); df = Storage.from_env().read_parquet(processed_key('<FP>','test')).drop(columns=['sale_price']).head(3); print(df['list_price'].tolist()); print(m.predict(df))"
```
Expected: in ra `list_price` **vẫn ở dạng thô** rồi in ba con số dự đoán hợp lý (hàng trăm nghìn đô). Model tự làm sạch record thô — không có bước clean nào ở ngoài.

- [ ] **Step 7: Commit**

```bash
git add stages/train/
git commit -m "feat: stage train, log nguyen Pipeline vao MLflow"
```

---

## Task 12: Stage `evaluate`

**Files:**
- Create: `stages/evaluate/Dockerfile`, `stages/evaluate/main.py`

**Interfaces:**
- Consumes: `storage.processed_key()`, `metrics.compute_metrics()`, `gates.evaluate_gates()`, `schema.target_column()`
- Produces: metric của cả ứng viên lẫn champion ghi vào **chính run của ứng viên**; XCom `{"passed": bool, "reason": str, "metrics": {...}, "champion_metrics": {...} | None}`

**Biến môi trường:** `FINGERPRINT`, `TASK_TYPE`, `MODEL_NAME`, `RUN_ID`, `MLFLOW_TRACKING_URI`.

**Stage này luôn exit 0, kể cả khi model trượt cổng.** Trượt cổng không phải lỗi hệ thống — đó là một kết quả hợp lệ mà pipeline phải ghi lại. Việc rẽ nhánh do `BranchPythonOperator` ở Task 15 làm, đọc `passed` từ XCom. Nếu stage này exit 1 khi trượt thì DAG sẽ báo failed thay vì báo "đã đánh giá và quyết định không promote".

**Champion phải được chấm trên cùng `test.parquet` với ứng viên** — đó là lý do test set có seed cố định.

- [ ] **Step 1: Viết `stages/evaluate/main.py`**

```python
"""Evaluate stage: score the candidate and decide whether it may be promoted.

Two gates, both required. The first blocks junk on an absolute threshold. The
second blocks a merely-adequate model from displacing a better one, scored on
the SAME test split — which is why that split has a fixed seed.

A failed gate is a result, not an error: this stage always exits 0 and lets the
DAG branch on what it reports.
"""

from __future__ import annotations

import json
import os
import sys

import mlflow
import mlflow.sklearn
from mlflow.exceptions import MlflowException

from ml_common import schema
from ml_common.gates import evaluate_gates
from ml_common.metrics import compute_metrics
from ml_common.storage import Storage, processed_key

CHAMPION_ALIAS = "champion"


def score_model(model, features, y_true, task_type: str) -> dict:
    """Runs a model over the test split and returns its metrics."""
    y_pred = model.predict(features)
    y_proba = None
    if task_type == "classification" and hasattr(model, "predict_proba"):
        y_proba = model.predict_proba(features)[:, 1]
    return compute_metrics(task_type, y_true, y_pred, y_proba)


def load_champion(model_name: str):
    """Loads the current champion, or None when nothing has been promoted yet."""
    try:
        return mlflow.sklearn.load_model(f"models:/{model_name}@{CHAMPION_ALIAS}")
    except MlflowException as err:
        print(f"no champion to compare against: {err}", file=sys.stderr)
        return None


def main() -> int:
    fingerprint = os.environ["FINGERPRINT"]
    task_type = os.environ["TASK_TYPE"]
    model_name = os.environ["MODEL_NAME"]
    run_id = os.environ["RUN_ID"]

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])

    storage = Storage.from_env()
    test_df = storage.read_parquet(processed_key(fingerprint, "test"))
    target = schema.target_column(task_type)
    features = test_df.drop(columns=[target])
    y_true = test_df[target]
    print(f"scoring on {len(test_df)} test rows", file=sys.stderr)

    candidate = mlflow.sklearn.load_model(f"runs:/{run_id}/model")
    candidate_metrics = score_model(candidate, features, y_true, task_type)
    print(f"candidate: {candidate_metrics}", file=sys.stderr)

    champion = load_champion(model_name)
    champion_metrics = None
    if champion is not None:
        champion_metrics = score_model(champion, features, y_true, task_type)
        print(f"champion:  {champion_metrics}", file=sys.stderr)

    decision = evaluate_gates(task_type, candidate_metrics, champion_metrics)
    print(f"decision: {decision['reason']}", file=sys.stderr)

    # Write the numbers back onto the candidate's own run, so a blocked model
    # still leaves a record of why it was blocked.
    with mlflow.start_run(run_id=run_id):
        mlflow.log_metrics({f"test_{name}": value for name, value in candidate_metrics.items()})
        if champion_metrics is not None:
            mlflow.log_metrics(
                {f"champion_test_{name}": value for name, value in champion_metrics.items()}
            )
        mlflow.set_tags(
            {
                "gate_passed": str(decision["passed"]),
                "gate_reason": decision["reason"],
            }
        )

    print(
        json.dumps(
            {
                "passed": decision["passed"],
                "reason": decision["reason"],
                "metrics": candidate_metrics,
                "champion_metrics": champion_metrics,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Viết `stages/evaluate/Dockerfile`**

```dockerfile
# Evaluate stage. Build from the repo root:
#   docker build -f stages/evaluate/Dockerfile -t ml-evaluate:latest .
FROM ml-base:latest

COPY stages/evaluate/main.py /app/main.py

ENTRYPOINT ["python", "/app/main.py"]
```

- [ ] **Step 3: Build image**

Run: `docker build -f stages/evaluate/Dockerfile -t ml-evaluate:latest .`
Expected: build thành công

- [ ] **Step 4: Chạy tay — chưa có champion nào**

```powershell
docker run --rm --network mlops_default --env-file .env -e MINIO_ENDPOINT_INTERNAL=http://minio:9000 -e MLFLOW_TRACKING_URI=http://mlflow:5000 -e FINGERPRINT=<FP> -e TASK_TYPE=regression -e MODEL_NAME=house_price_regressor -e RUN_ID=<RUN_ID> ml-evaluate:latest
echo $LASTEXITCODE
```
Expected: stderr in `no champion to compare against`, stdout dòng cuối có `"passed": true` hoặc `false` tuỳ R² thật, `"champion_metrics": null`, exit code `0`.

Ghi lại giá trị `r2` thật — spec mục 7.5 nói ngưỡng 0.75 là điểm khởi đầu và **sẽ hiệu chỉnh sau lần train đầu tiên**. Nếu Ridge ra R² thấp hơn nhiều so với 0.75, báo lại chứ đừng tự hạ ngưỡng.

- [ ] **Step 5: Xác nhận metric đã ghi vào run**

```powershell
.venv\Scripts\python.exe -c "import mlflow; mlflow.set_tracking_uri('http://localhost:5000'); r=mlflow.get_run('<RUN_ID>'); print({k:v for k,v in r.data.metrics.items()}); print(r.data.tags.get('gate_reason'))"
```
Expected: thấy cả `train_*` lẫn `test_*` metrics, và `gate_reason` là câu giải thích.

- [ ] **Step 6: Commit**

```bash
git add stages/evaluate/
git commit -m "feat: stage evaluate voi hai cong, luon exit 0 de DAG tu re nhanh"
```

---

## Task 13: Stage `register`

**Files:**
- Create: `stages/register/Dockerfile`, `stages/register/main.py`

**Interfaces:**
- Consumes: `storage.processed_key()`, `storage.baseline_key()`, `profiling.compute_profile()`, `schema.feature_columns()`
- Produces: một model version mới mang alias `champion`; `monitoring-baseline/{model_name}/{version}/profile.json`; XCom `{"version": str, "baseline_key": str}`

**Biến môi trường:** `FINGERPRINT`, `TASK_TYPE`, `MODEL_NAME`, `RUN_ID`, `MLFLOW_TRACKING_URI`.

**Dùng alias, không dùng stage.** `set_registered_model_alias(model_name, "champion", version)`. Model stage đã deprecate ở MLflow 2.22 và bỏ hẳn ở MLflow 3 — xem mục 2.3 của spec.

**Baseline sinh từ `train.parquet`, không phải `test.parquet`.** Plan 4 so phân phối traffic production với phân phối dữ liệu **model đã học**, nên baseline phải là tập train.

- [ ] **Step 1: Viết `stages/register/main.py`**

```python
"""Register stage: promote the model and snapshot what it learned from.

Promotion moves an alias, not a stage: MLflow deprecated model stages in 2.x and
removes them in 3.x. Moving the `champion` alias to a new version leaves every
older version intact and untouched — nothing is archived, it simply stops being
pointed at.
"""

from __future__ import annotations

import json
import os
import sys

import mlflow
from mlflow import MlflowClient

from ml_common import schema
from ml_common.profiling import compute_profile
from ml_common.storage import Storage, baseline_key, processed_key

CHAMPION_ALIAS = "champion"


def main() -> int:
    fingerprint = os.environ["FINGERPRINT"]
    task_type = os.environ["TASK_TYPE"]
    model_name = os.environ["MODEL_NAME"]
    run_id = os.environ["RUN_ID"]

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    client = MlflowClient()

    registered = mlflow.register_model(f"runs:/{run_id}/model", model_name)
    version = registered.version
    print(f"registered {model_name} version {version}", file=sys.stderr)

    client.set_registered_model_alias(model_name, CHAMPION_ALIAS, version)
    print(f"alias {CHAMPION_ALIAS} now points at version {version}", file=sys.stderr)

    # Baseline comes from the TRAIN split: Plan 4 compares production traffic
    # against the distribution the model actually learned from.
    storage = Storage.from_env()
    train_df = storage.read_parquet(processed_key(fingerprint, "train"))
    profile = compute_profile(train_df, schema.feature_columns(task_type))

    destination = baseline_key(model_name, version)
    storage.write_json(profile, destination)
    print(f"baseline profile written to {destination}", file=sys.stderr)

    print(json.dumps({"version": str(version), "baseline_key": destination}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Viết `stages/register/Dockerfile`**

```dockerfile
# Register stage. Build from the repo root:
#   docker build -f stages/register/Dockerfile -t ml-register:latest .
FROM ml-base:latest

COPY stages/register/main.py /app/main.py

ENTRYPOINT ["python", "/app/main.py"]
```

- [ ] **Step 3: Build image**

Run: `docker build -f stages/register/Dockerfile -t ml-register:latest .`
Expected: build thành công

- [ ] **Step 4: Chạy tay**

```powershell
docker run --rm --network mlops_default --env-file .env -e MINIO_ENDPOINT_INTERNAL=http://minio:9000 -e MLFLOW_TRACKING_URI=http://mlflow:5000 -e FINGERPRINT=<FP> -e TASK_TYPE=regression -e MODEL_NAME=house_price_regressor -e RUN_ID=<RUN_ID> ml-register:latest
```
Expected: stdout dòng cuối `{"version": "1", "baseline_key": "monitoring-baseline/house_price_regressor/1/profile.json"}`

- [ ] **Step 5: Xác nhận alias trỏ đúng và load được bằng alias**

```powershell
.venv\Scripts\python.exe -c "import mlflow; from mlflow import MlflowClient; mlflow.set_tracking_uri('http://localhost:5000'); c=MlflowClient(); v=c.get_model_version_by_alias('house_price_regressor','champion'); print('version', v.version, 'run', v.run_id)"
```
Expected: in ra version và `run_id` khớp với `<RUN_ID>`.

- [ ] **Step 6: Xác nhận baseline profile nằm thật trên MinIO và đọc được**

```powershell
.venv\Scripts\python.exe -c "from ml_common.storage import Storage, baseline_key; s=Storage.from_env(); p=s.read_json(baseline_key('house_price_regressor', 1)); print(len(p), 'columns profiled'); print(list(p)[:5])"
```
Expected: in ra số cột đã profile và vài tên cột. Số cột phải khớp `len(schema.feature_columns("regression"))`.

- [ ] **Step 7: Commit**

```bash
git add stages/register/
git commit -m "feat: stage register, gan alias champion va sinh baseline profile"
```

---

## Task 14: Airflow gọi được Docker

**Files:**
- Modify: `docker-compose.yml` (chỉ service `airflow-scheduler` và khối `&airflow-env`)
- Create: `scripts/build_stage_images.ps1`

**Interfaces:**
- Consumes: sáu image stage từ Task 8-13
- Produces: `airflow-scheduler` có `apache-airflow-providers-docker` và truy cập được docker socket; một lệnh build cả sáu image

**Công thức dưới đây đã được spike xác nhận trên chính máy này** (2026-09-19, branch `spike/docker-operator`). Đừng thay đổi chi tiết nào trong đó nếu chưa thử lại:

- `//var/run/docker.sock` — **hai gạch đầu là bắt buộc** trên Windows, nếu không MSYS mangle đường dẫn thành `C:/Program Files/...`.
- `user: "50000:0"` đã có sẵn từ Plan 1 chính là thứ làm nó chạy: socket là `root:root` mode `660`, container thuộc group `0` nên đọc ghi được.
- Chỉ `airflow-scheduler` cần socket. `LocalExecutor` chạy task ngay trong scheduler, nên webserver không cần và không nên được cấp.

- [ ] **Step 1: Thêm `SAMPLE_ROWS` vào khối `&airflow-env`**

Stage `extract` cần biến này nhưng khối env hiện tại chưa truyền. Thêm vào cuối khối `environment: &airflow-env` của service `airflow-init`:

```yaml
      SAMPLE_ROWS: ${SAMPLE_ROWS}
```

- [ ] **Step 2: Sửa service `airflow-scheduler`**

Service này đang dùng `environment: *airflow-env` và `volumes: *airflow-volumes`. Nó cần thêm hai thứ, mà YAML không merge được list, nên phần `volumes` phải viết đầy đủ:

```yaml
  airflow-scheduler:
    image: apache/airflow:2.10.3-python3.12
    container_name: mlops-airflow-scheduler
    depends_on:
      airflow-init:
        condition: service_completed_successfully
    environment:
      <<: *airflow-env
      _PIP_ADDITIONAL_REQUIREMENTS: apache-airflow-providers-docker==3.14.0
    # LocalExecutor runs tasks inside the scheduler, so this is the only service
    # that needs the Docker socket. The leading double slash is required on
    # Windows: without it the path is rewritten to a Windows path and the mount
    # silently points at nothing.
    volumes:
      - ./dags:/opt/airflow/dags
      - ./logs:/opt/airflow/logs
      - ./plugins:/opt/airflow/plugins
      - //var/run/docker.sock:/var/run/docker.sock
    user: "${AIRFLOW_UID:-50000}:0"
    command: scheduler
    restart: unless-stopped
```

- [ ] **Step 3: Khởi động lại scheduler và chờ cài provider**

Run:
```powershell
docker compose up -d airflow-scheduler
Start-Sleep -Seconds 45
docker compose ps
```
Expected: `mlops-airflow-scheduler` ở trạng thái `Up`.

- [ ] **Step 4: Xác nhận socket và provider dùng được từ trong container**

Run:
```powershell
docker compose exec -T airflow-scheduler ls -la /var/run/docker.sock
docker compose exec -T airflow-scheduler python -c "import docker; c=docker.from_env(); print('ping:', c.ping()); print('containers:', len(c.containers.list()))"
docker compose exec -T airflow-scheduler python -c "from airflow.providers.docker.operators.docker import DockerOperator; print('provider ok')"
```
Expected: socket là `srw-rw---- 1 root root`, `ping: True`, số container > 0, và `provider ok`.

Nếu `ls` báo không tìm thấy file, mount sai — kiểm lại hai gạch đầu ở Step 2.

- [ ] **Step 5: Viết `scripts/build_stage_images.ps1`**

```powershell
# Build every stage image. Run from the repo root.
# ml-base must be current first: build_base_image.ps1 rebuilds it from common/.
$ErrorActionPreference = "Stop"

$stages = @(
    @{ Dir = "extract";                   Tag = "ml-extract:latest" },
    @{ Dir = "validate";                  Tag = "ml-validate:latest" },
    @{ Dir = "prepare_dataset_for_train"; Tag = "ml-prepare-dataset:latest" },
    @{ Dir = "train";                     Tag = "ml-train:latest" },
    @{ Dir = "evaluate";                  Tag = "ml-evaluate:latest" },
    @{ Dir = "register";                  Tag = "ml-register:latest" }
)

foreach ($stage in $stages) {
    Write-Host "== Building $($stage.Tag) ==" -ForegroundColor Cyan
    docker build -f "stages/$($stage.Dir)/Dockerfile" -t $stage.Tag .
}

Write-Host "`nAll stage images built." -ForegroundColor Green
```

- [ ] **Step 6: Build lại cả sáu image từ đầu**

Run: `powershell -ExecutionPolicy Bypass -File scripts\build_stage_images.ps1`
Expected: sáu lần build thành công, dòng cuối `All stage images built.`

- [ ] **Step 7: Xác nhận cả sáu image tồn tại**

Run: `docker images --format "{{.Repository}}:{{.Tag}}" | Select-String "^ml-"`
Expected: liệt kê đủ `ml-base`, `ml-extract`, `ml-validate`, `ml-prepare-dataset`, `ml-train`, `ml-evaluate`, `ml-register`.

- [ ] **Step 8: Commit**

```bash
git add docker-compose.yml scripts/build_stage_images.ps1
git commit -m "feat: airflow goi duoc docker socket va script build sau image stage"
```

---

## Task 15: DAG `ml_pipeline`

**Files:**
- Create: `dags/ml_pipeline_dag.py`
- Delete: `dags/smoke_dag.py`

**Interfaces:**
- Consumes: sáu image stage, và XCom mà chúng in ra
- Produces: DAG `ml_pipeline` chạy được từ UI hoặc CLI với `dag_run.conf`

**Tham số `dag_run.conf`:** `task_type` (bắt buộc), `force_reprocess` (mặc định `false`), `dataset_version` (mặc định `"v1"`).

**Về XCom:** `DockerOperator` với `do_xcom_push=True` đẩy **dòng cuối stdout dưới dạng chuỗi**, không tự parse JSON. Airflow 2.10 không có filter `fromjson` sẵn, nên DAG tự đăng ký nó qua `user_defined_filters`. Đây là chỗ dễ sai nhất của task này.

**`smoke_dag.py` bị xoá ở đây** — nó đã làm xong việc của mình ở Plan 1 (chứng minh Airflow đọc được `dags/`), và spec Plan 1 đã ghi rõ nó sẽ bị xoá ở Plan 2.

- [ ] **Step 1: Viết `dags/ml_pipeline_dag.py`**

```python
"""ml_pipeline — train a model and promote it if it earns the champion alias.

Triggered by hand, never scheduled: retraining is a decision, not a cron job.

Airflow does not run any of the ML code itself. Each task asks the Docker daemon
to run a stage image and reports its exit code. Data moves between stages
through object storage; XCom carries only small values.
"""

from __future__ import annotations

import json
import os

import pendulum
from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import BranchPythonOperator
from airflow.providers.docker.operators.docker import DockerOperator

DOCKER_URL = "unix://var/run/docker.sock"
NETWORK = "mlops_default"

MODEL_NAME_BY_TASK_TYPE = {
    "regression": "house_price_regressor",
    "classification": "house_sold_fast_classifier",
}

# Passed into every stage container. Read from the scheduler's own environment,
# which docker-compose fills from .env.
BASE_ENV = {
    "MINIO_ENDPOINT_INTERNAL": os.environ.get("MINIO_ENDPOINT_INTERNAL", "http://minio:9000"),
    "MINIO_ACCESS_KEY": os.environ.get("MINIO_ACCESS_KEY", ""),
    "MINIO_SECRET_KEY": os.environ.get("MINIO_SECRET_KEY", ""),
    "ML_BUCKET": os.environ.get("ML_BUCKET", "ml-pipeline"),
    "MLFLOW_TRACKING_URI": os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"),
}

FINGERPRINT = "{{ (ti.xcom_pull(task_ids='extract') | fromjson)['fingerprint'] }}"
RUN_ID = "{{ (ti.xcom_pull(task_ids='train') | fromjson)['run_id'] }}"
TASK_TYPE = "{{ params.task_type }}"
MODEL_NAME = "{{ params.model_name }}"


def stage(task_id: str, image: str, extra_env: dict) -> DockerOperator:
    """One stage: run an image, stream its logs, take its last stdout line as XCom."""
    return DockerOperator(
        task_id=task_id,
        image=image,
        docker_url=DOCKER_URL,
        network_mode=NETWORK,
        environment={**BASE_ENV, **extra_env},
        auto_remove="success",
        mount_tmp_dir=False,
        do_xcom_push=True,
    )


def choose_branch(ti) -> str:
    """Reads the evaluate verdict and picks which way the DAG goes."""
    verdict = json.loads(ti.xcom_pull(task_ids="evaluate"))
    print(f"evaluate said: {verdict['reason']}")
    return "register" if verdict["passed"] else "stop_no_deploy"


with DAG(
    dag_id="ml_pipeline",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ml", "training"],
    params={
        "task_type": "regression",
        "force_reprocess": False,
        "dataset_version": "v1",
        "estimator_name": "ridge",
        "model_name": MODEL_NAME_BY_TASK_TYPE["regression"],
    },
    # DockerOperator pushes the container's last stdout line as a plain string.
    # Airflow 2.10 has no built-in JSON filter, so register one here.
    user_defined_filters={"fromjson": json.loads},
) as dag:
    extract = stage(
        "extract",
        "ml-extract:latest",
        {
            "DATASET_VERSION": "{{ params.dataset_version }}",
            "SAMPLE_ROWS": os.environ.get("SAMPLE_ROWS", ""),
        },
    )

    validate = stage(
        "validate",
        "ml-validate:latest",
        {"FINGERPRINT": FINGERPRINT, "TASK_TYPE": TASK_TYPE},
    )

    prepare_dataset = stage(
        "prepare_dataset_for_train",
        "ml-prepare-dataset:latest",
        {
            "FINGERPRINT": FINGERPRINT,
            "TASK_TYPE": TASK_TYPE,
            "FORCE_REPROCESS": "{{ params.force_reprocess | lower }}",
        },
    )

    train = stage(
        "train",
        "ml-train:latest",
        {
            "FINGERPRINT": FINGERPRINT,
            "TASK_TYPE": TASK_TYPE,
            "MODEL_NAME": MODEL_NAME,
            "ESTIMATOR_NAME": "{{ params.estimator_name }}",
        },
    )

    evaluate = stage(
        "evaluate",
        "ml-evaluate:latest",
        {
            "FINGERPRINT": FINGERPRINT,
            "TASK_TYPE": TASK_TYPE,
            "MODEL_NAME": MODEL_NAME,
            "RUN_ID": RUN_ID,
        },
    )

    branch = BranchPythonOperator(task_id="branch_on_gates", python_callable=choose_branch)

    register = stage(
        "register",
        "ml-register:latest",
        {
            "FINGERPRINT": FINGERPRINT,
            "TASK_TYPE": TASK_TYPE,
            "MODEL_NAME": MODEL_NAME,
            "RUN_ID": RUN_ID,
        },
    )

    stop_no_deploy = EmptyOperator(task_id="stop_no_deploy")

    extract >> validate >> prepare_dataset >> train >> evaluate >> branch
    branch >> [register, stop_no_deploy]
```

- [ ] **Step 2: Xoá DAG smoke test của Plan 1**

Run: `git rm dags/smoke_dag.py`
Nó đã chứng minh xong việc Airflow đọc được `dags/`; Plan 1 ghi rõ nó bị xoá ở Plan 2.

- [ ] **Step 3: Xác nhận DAG parse được, không có lỗi import**

Run:
```powershell
docker compose exec -T airflow-scheduler airflow dags list-import-errors
docker compose exec -T airflow-scheduler airflow dags list
```
Expected: `list-import-errors` rỗng; `list` có `ml_pipeline` và **không còn** `smoke_test`.

Nếu có import error về `airflow.providers.docker`, provider chưa cài xong — chờ thêm rồi thử lại.

- [ ] **Step 4: Chạy full DAG lần đầu với bản dữ liệu nhỏ**

Đặt `SAMPLE_ROWS=20000` trong `.env` rồi `docker compose up -d airflow-scheduler` để nạp lại biến. Sau đó:

```powershell
docker compose exec -T airflow-scheduler airflow dags test ml_pipeline 2026-09-19
```
Expected: sáu task chạy tuần tự. Nhánh đi vào `register` hoặc `stop_no_deploy` tuỳ R² thật của Ridge. **Không task nào được fail.**

Nếu `validate` fail vì `FINGERPRINT` rỗng, thì filter `fromjson` chưa chạy — kiểm lại `user_defined_filters`.

- [ ] **Step 5: Chạy lần hai và xác nhận cache**

Chạy lại đúng lệnh trên.
Expected: task `prepare_dataset_for_train` in `{"skipped": true, ...}`.

- [ ] **Step 6: Chạy lần ba với `force_reprocess`**

```powershell
docker compose exec -T airflow-scheduler airflow dags test ml_pipeline 2026-09-19 --conf '{\"force_reprocess\": true}'
```
Expected: `prepare_dataset_for_train` in `{"skipped": false, ...}`.

- [ ] **Step 7: Commit**

```bash
git add dags/ml_pipeline_dag.py
git rm --cached dags/smoke_dag.py 2>$null
git commit -m "feat: DAG ml_pipeline goi sau stage qua DockerOperator"
```

---

## Task 16: Round-trip test và xác nhận hai cổng chặn được thật

**Files:**
- Create: `scripts/smoke_round_trip.py`
- Create: `scripts/verify_pipeline.ps1`
- Modify: `README.md`

**Interfaces:**
- Consumes: mọi thứ từ Task 1-15
- Produces: một lệnh xác nhận toàn bộ Plan 2

Đây là task chứng minh pipeline **làm đúng việc của nó**, không chỉ chạy tới cuối mà không nổ. Hai mục quan trọng nhất là chứng minh cổng `evaluate` **chặn được** — một cổng lúc nào cũng cho qua thì không phải cổng.

- [ ] **Step 1: Viết `scripts/smoke_round_trip.py`**

```python
"""Round-trip check: a model reloaded from MLflow must behave identically.

Spec section 7.11 asks for this. It is the cheapest way to catch training and
serving drifting apart: if the Pipeline that comes back out of the Registry
predicts differently from the one that went in, something in the packaging is
lossy, and Plan 3's /predict would inherit that silently.

Run from the host, with the stack up.
"""

from __future__ import annotations

import os

import mlflow
import mlflow.sklearn
import numpy as np
from mlflow import MlflowClient

from ml_common import schema
from ml_common.storage import Storage, processed_key

os.environ.setdefault("MLFLOW_S3_ENDPOINT_URL", "http://localhost:9000")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "minioadmin")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "minioadmin")

MODEL_NAME = "house_price_regressor"
TASK_TYPE = "regression"
SAMPLE_SIZE = 20


def main() -> int:
    mlflow.set_tracking_uri("http://localhost:5000")
    client = MlflowClient()

    version = client.get_model_version_by_alias(MODEL_NAME, "champion")
    print(f"champion is version {version.version} from run {version.run_id}")

    fingerprint = client.get_run(version.run_id).data.params["fingerprint"]
    test_df = Storage.from_env().read_parquet(processed_key(fingerprint, "test"))
    raw_records = test_df.drop(columns=[schema.target_column(TASK_TYPE)]).head(SAMPLE_SIZE)

    print("feeding RAW records straight in — no cleaning on this side:")
    print(f"  list_price[0] = {raw_records['list_price'].iloc[0]!r}")
    print(f"  city[0]       = {raw_records['city'].iloc[0]!r}")

    from_run = mlflow.sklearn.load_model(f"runs:/{version.run_id}/model")
    from_alias = mlflow.sklearn.load_model(f"models:/{MODEL_NAME}@champion")

    predictions_from_run = from_run.predict(raw_records)
    predictions_from_alias = from_alias.predict(raw_records)

    if not np.allclose(predictions_from_run, predictions_from_alias):
        raise SystemExit("FAIL: the same model predicts differently via run vs alias")

    if not np.all(predictions_from_run > 0):
        raise SystemExit("FAIL: predictions are not positive dollar amounts")

    print(f"OK: {SAMPLE_SIZE} raw records, identical predictions both ways")
    print(f"  first three: {predictions_from_run[:3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Chạy round-trip test**

Run: `.venv\Scripts\python.exe scripts\smoke_round_trip.py`
Expected: in `OK: 20 raw records, identical predictions both ways` và ba con số dự đoán hàng trăm nghìn.

Nếu hai bên lệch nhau, **dừng lại** — đó là training/serving skew, và Plan 3 sẽ thừa hưởng nó.

- [ ] **Step 3: Train GBM và xác nhận nó phải THẮNG Ridge mới được promote**

Champion hiện tại là Ridge. Chạy DAG với GBM:

```powershell
docker compose exec -T airflow-scheduler airflow dags test ml_pipeline 2026-09-19 --conf '{\"estimator_name\": \"hist_gradient_boosting\"}'
```
Expected: task `evaluate` in `"champion_metrics"` khác `null` (đã so với Ridge), và nhánh đi vào `register` nếu GBM thắng.

Ghi lại RMSE của cả hai. **Đây là lần đầu cổng thứ hai được chạy thật** — trước đó chưa có champion nào để so.

- [ ] **Step 4: Xác nhận alias đã chuyển sang version mới**

```powershell
.venv\Scripts\python.exe -c "import mlflow; from mlflow import MlflowClient; mlflow.set_tracking_uri('http://localhost:5000'); c=MlflowClient(); v=c.get_model_version_by_alias('house_price_regressor','champion'); r=c.get_run(v.run_id); print('version', v.version, '| estimator', r.data.params['estimator'], '| test_rmse', r.data.metrics.get('test_rmse'))"
```
Expected: version 2, estimator `hist_gradient_boosting`.

Nếu GBM **không** thắng Ridge thì alias vẫn ở version 1 — đó cũng là kết quả hợp lệ, cổng đang làm đúng việc. Ghi lại con số và báo, đừng ép nó thắng.

- [ ] **Step 5: Chứng minh cổng chặn được model rác**

Đây là mục quan trọng nhất của cả plan. Train một `DummyRegressor` — nó chắc chắn có R² quanh 0:

```powershell
docker compose exec -T airflow-scheduler airflow dags test ml_pipeline 2026-09-19 --conf '{\"estimator_name\": \"dummy\"}'
```
Expected:
- `evaluate` in `"passed": false` và `reason` nhắc tới `floor`
- nhánh đi vào **`stop_no_deploy`**, task `register` bị skip
- **không task nào fail** — trượt cổng là kết quả, không phải lỗi

- [ ] **Step 6: Xác nhận champion KHÔNG đổi sau lần chạy model rác**

```powershell
.venv\Scripts\python.exe -c "import mlflow; from mlflow import MlflowClient; mlflow.set_tracking_uri('http://localhost:5000'); c=MlflowClient(); v=c.get_model_version_by_alias('house_price_regressor','champion'); r=c.get_run(v.run_id); print('champion version', v.version, '| estimator', r.data.params['estimator'])"
```
Expected: vẫn là version và estimator của Step 4, **không phải `dummy`**.

Nếu champion đã thành `dummy` thì cổng vô dụng — dừng lại và sửa.

- [ ] **Step 7: Viết `scripts/verify_pipeline.ps1`**

```powershell
# Verifies Plan 2: the batch pipeline runs and its gates actually gate.
$ErrorActionPreference = "Stop"

Write-Host "== 1/5 Unit tests ==" -ForegroundColor Cyan
.venv\Scripts\python.exe -m pytest common/ -q

Write-Host "== 2/5 Lint ==" -ForegroundColor Cyan
.venv\Scripts\python.exe -m ruff check common/ scripts/

Write-Host "== 3/5 Stage images present ==" -ForegroundColor Cyan
foreach ($tag in @("ml-base", "ml-extract", "ml-validate", "ml-prepare-dataset", "ml-train", "ml-evaluate", "ml-register")) {
    $found = docker images --format "{{.Repository}}" | Select-String -Pattern "^$tag$" -Quiet
    if (-not $found) { throw "Missing image: $tag" }
    Write-Host "  $tag ok"
}

Write-Host "== 4/5 DAG parses with no import errors ==" -ForegroundColor Cyan
docker compose exec -T airflow-scheduler airflow dags list-import-errors

Write-Host "== 5/5 Round-trip: model reloaded from MLflow behaves identically ==" -ForegroundColor Cyan
.venv\Scripts\python.exe scripts\smoke_round_trip.py

Write-Host "`nBatch pipeline ready for Plan 3." -ForegroundColor Green
```

- [ ] **Step 8: Chạy script xác nhận**

Run: `powershell -ExecutionPolicy Bypass -File scripts\verify_pipeline.ps1`
Expected: cả 5 mục pass, dòng cuối `Batch pipeline ready for Plan 3.`

- [ ] **Step 9: Cập nhật `README.md`**

Thêm vào mục **Khởi động**, ngay sau dòng build image nền:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_stage_images.ps1
.venv\Scripts\python.exe scripts\seed_raw_data.py
```

Thêm một mục mới sau mục **Kiểm tra**:

```markdown
## Chạy pipeline

Trên Airflow UI, bật DAG `ml_pipeline` rồi Trigger DAG w/ config:

    {"task_type": "regression", "estimator_name": "hist_gradient_boosting"}

Tham số: `task_type` (bắt buộc), `estimator_name`, `force_reprocess`,
`dataset_version`.

Xác nhận pipeline:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_pipeline.ps1
```
```

Sửa mục **Trạng thái** thành: `Plan 2/5 — batch pipeline chạy được cho regression.`

- [ ] **Step 10: Commit**

```bash
git add scripts/smoke_round_trip.py scripts/verify_pipeline.ps1 README.md
git commit -m "test: round-trip model va xac nhan hai cong chan duoc"
```

---

## Definition of Done

Plan 2 hoàn thành khi:

- [ ] `powershell -ExecutionPolicy Bypass -File scripts\verify_pipeline.ps1` xanh toàn bộ
- [ ] `scripts/seed_raw_data.py` đẩy được raw parquet lên MinIO, dữ liệu vẫn thô
- [ ] Sáu image stage build được và chạy tay được bằng `docker run`
- [ ] DAG `ml_pipeline` chạy full một lượt `task_type=regression`, không task nào fail
- [ ] Chạy lần hai cùng tham số: `prepare_dataset_for_train` báo `skipped: true`
- [ ] Chạy với `force_reprocess=true`: `prepare_dataset_for_train` chạy lại thật
- [ ] `processed/{fp}/train.parquet` **vẫn thô ở mức cột** (`list_price` chưa parse, `city` chưa chuẩn hoá) nhưng **target đã parse thành số**
- [ ] MLflow có registered model `house_price_regressor` với alias `champion`
- [ ] `monitoring-baseline/house_price_regressor/{v}/profile.json` tồn tại trên MinIO
- [ ] Train Ridge rồi GBM: cổng thứ hai được chạy thật, alias chỉ đổi khi ứng viên thắng
- [ ] Train `dummy`: bị chặn ở `evaluate`, DAG đi nhánh `stop_no_deploy`, **alias champion không đổi**, không task nào fail
- [ ] Round-trip test pass: model load lại từ MLflow dự đoán y hệt, và ăn record thô
- [ ] Toàn bộ unit test pass ở cả Python 3.13 local lẫn 3.12 trong `ml-base`

Hai mục áp chót là quan trọng nhất. Chúng là thứ duy nhất chứng minh cổng
`evaluate` thật sự gác cửa chứ không phải lúc nào cũng cho qua, và chứng minh
model tự chứa logic làm sạch của chính nó.

---

## Những gì Plan 2 cố tình KHÔNG làm

- **Không có task `deploy`, không có serving.** Plan 3.
- **Không chạy nhánh classification.** Code phải hỗ trợ `task_type` đầy đủ, nhưng chỉ regression được chạy và xác nhận ở plan này. Plan 3 bật nhánh còn lại.
- **Không có monitoring, không có Evidently, không có `monitoring_dag`.** Plan 4.
- **Không tinh chỉnh hyperparameter.** Ridge và GBM chạy với tham số mặc định. Mục tiêu của plan là đường ống chạy đúng, không phải model tốt nhất.
- **Không hiệu chỉnh ngưỡng 0.75.** Nếu số thật lệch nhiều so với ngưỡng, ghi lại và báo — việc đổi ngưỡng là quyết định của con người sau khi nhìn số, đúng như spec mục 7.5 nói.

---

## Self-review

Rà soát plan này với spec, ngày 2026-09-19.

**Spec coverage** — từng mục của spec ánh xạ sang task nào:

| Mục spec | Task |
| --- | --- |
| 2.1 DockerOperator | 14, 15 |
| 2.2 `prepare_dataset_for_train` không làm sạch cột | 10 (Step 7 xác nhận bằng dữ liệu thật) |
| 2.3 Alias thay vì stage | 13 |
| 2.4 Seed ngoài DAG | 7 |
| 2.5 `SAMPLE_ROWS` trong fingerprint | 1 (test), 8 (Step 5 xác nhận) |
| 2.6 Log target trong Pipeline | 3 (test), 11 (Step 4 xác nhận RMSE ra đô la) |
| 4.1 `extract` | 8 |
| 4.2 `validate`, ba luật fatal | 2, 9 |
| 4.3 `prepare_dataset_for_train`, cache, seed 42 | 10 |
| 4.4 `train`, Ridge trước GBM sau | 3, 11, 16 |
| 4.5 `evaluate`, hai cổng | 5, 12 |
| 4.6 `register`, alias + baseline từ train | 13 |
| 5.1 Hai hàm key mới | 1 |
| 5.2 `docker-compose.yml` | 14 |
| 5.3 `seed_raw_data.py` | 7 |
| 7 Test round-trip | 16 |

**Lỗ hổng phát hiện khi rà soát, đã bổ sung vào plan:**

- Spec không nói ai parse cột target. `Pipeline` chỉ biến đổi `X`, nên `y` sẽ tới `fit()` ở dạng `"$450,000"` và làm nổ. Đã thêm **Task 6 (`targets.py`)**, và `prepare_dataset_for_train` parse target trước khi drop để loại luôn những target không parse nổi.
- Spec không nói `mlflow` vào image nền bằng cách nào. `ml-base` hiện chưa có nó, mà ba stage cuối đều cần. Đã đưa vào **Task 7**, kèm lý do không nhét vào `common/pyproject.toml`.
- Spec không nói làm sao upload file 373MB. Đọc hết vào pandas sẽ chạm trần RAM. Đã thêm `Storage.upload_file` ở **Task 7**.
- Khối `&airflow-env` chưa truyền `SAMPLE_ROWS`, trong khi `extract` cần. Đã thêm ở **Task 14 Step 1**.
- `DockerOperator` đẩy XCom dưới dạng **chuỗi**, không phải dict, và Airflow 2.10 không có filter `fromjson`. Đã xử lý bằng `user_defined_filters` ở **Task 15**, và ghi rõ đây là chỗ dễ sai nhất.
- Spec không nói `evaluate` nên exit code mấy khi trượt cổng. Đã chốt: **luôn exit 0**, để `BranchPythonOperator` quyết định — nếu không, trượt cổng sẽ hiện thành DAG failed thay vì một quyết định được ghi lại.

**Type consistency:** `fingerprint` là `str` xuyên suốt; `version` trả về từ `register` ép sang `str` trước khi vào XCom; `compute_metrics` luôn trả `dict[str, float]` thuần Python; `evaluate_gates` trả `beats_champion` là `bool | None` và mọi chỗ đọc nó đều xử lý `None`.

**Placeholder:** không còn "TBD"/"TODO"; mọi step có code đều có code thật.

