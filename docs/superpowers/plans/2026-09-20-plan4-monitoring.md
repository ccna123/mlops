# Plan 4 — Monitoring & Drift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng `services/agent/` sinh traffic theo 5 kịch bản thị trường, thêm `POST /feedback/{task_type}` vào serving, viết `common/ml_common/drift.py` cùng image `ml-monitor` chạy Evidently, và nối `monitoring_dag` để hệ thống tự phát hiện khi model đang hỏng dần.

**Architecture:** Luật quy ra mức độ drift nằm ở `common/ml_common/drift.py` — thuần pandas, test được ở máy dev không cần Evidently. Evidently chỉ sống trong image `ml-monitor` và được import lazy trong `stages/monitor/main.py`, để `ml-base` (gốc của 6 stage và serving) không phải cõng thêm ~500MB. Baseline cho Evidently là tập train đọc lại qua `fingerprint` đã log trong MLflow, không phải `profile.json` — Evidently chỉ nhận DataFrame.

**Tech Stack:** Python 3.12 (container) / 3.13 (dev), Evidently 0.7.x, FastAPI, MLflow 2.22, pandas 2.3, scikit-learn 1.9, MinIO, Airflow 2.10.3.

**Spec:** `docs/superpowers/specs/2026-09-20-plan4-monitoring-design.md` — đọc cùng plan này. Plan lập luận từ spec; hai bên lệch nhau thì spec thắng, và **phải báo chứ không tự chọn bên**.

## Global Constraints

- **Python:** container 3.12, dev 3.13. **Không dùng cú pháp chỉ có ở 3.13+.**
- **Pin version:** `pandas>=2.2,<3`, `scikit-learn>=1.5,<2`, `pyarrow>=16`, `boto3>=1.34`, `numpy>=1.26,<3`, `mlflow>=2.14,<3`, `fastapi>=0.115`, `uvicorn[standard]>=0.30`, **`evidently>=0.7,<0.8`**, `httpx>=0.27`.
- **Evidently chỉ được cài trong `ml-monitor`.** Không thêm vào `ml-base`, không thêm vào `common/pyproject.toml` phần `dependencies`.
- **`common/ml_common/drift.py` không được import Evidently ở mức module.** `ml-base` không có Evidently; import ở mức module sẽ làm mọi stage sập khi import `ml_common`.
- **Serving không được import `ml_common.cleaning` hay `ml_common.rowops`.** Ràng buộc này vẫn giữ nguyên ở Plan 4 và `scripts/verify_serving.ps1` vẫn kiểm.
- **Mọi key object storage** phải sinh từ hàm `*_key()` / `*_prefix()` trong `common/ml_common/storage.py`. Không nối chuỗi ở nơi khác.
- **Stage phát kết quả qua `stageio.emit_result()`**, không `print(json.dumps(...))`.
- **Docstring:** mọi function/method/class trong code production phải có docstring Google style với `Args:`, `Returns:`, thêm `Raises:` khi có ném exception, và `Example:` dạng minh hoạ dùng `# ->` (**không dùng `>>>`**). Thư mục `tests/` được miễn. Ruff rule `D` sẽ chặn nếu thiếu.
- **Ruff:** cấu hình ở `ruff.toml` **tại gốc repo**. `line-length = 100`, rules `["E", "F", "I", "UP", "B", "D"]`, `convention = "google"`. Chạy `.venv\Scripts\python.exe -m ruff check . --fix`.
- **Ngôn ngữ trong code:** tiếng Anh tự nhiên. File markdown tiếng Việt có dấu.
- **Giá trị thiếu:** `None` / `np.nan`. Không dùng chuỗi rỗng hay `-1`.
- **Commit:** mỗi task **đúng một** commit, Conventional Commits, mô tả **tiếng Anh**, kết thúc bằng `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. Kiểm lại bằng `git log -1`.
- **Build lại ba tầng mỗi khi `common/` thay đổi**, đúng thứ tự: `scripts\build_base_image.ps1`, rồi `scripts\build_stage_images.ps1`, rồi `docker build -f services/serving/Dockerfile -t ml-serving:latest .`. Chỉ build `ml-base` là chưa đủ — 6 stage image và `ml-serving` đều `FROM ml-base:latest`.
- **Lệnh Python local:** gọi thẳng `.venv\Scripts\python.exe`, không dùng `Activate.ps1`.
- **Chạy Python từ host** cần override `MINIO_ENDPOINT_INTERNAL` bỏ trống, `MINIO_ENDPOINT=http://localhost:9000`, `MLFLOW_TRACKING_URI=http://localhost:5000`.

## File Structure

| File | Trách nhiệm |
| --- | --- |
| `common/ml_common/storage.py` | **Sửa:** thêm `drift_summary_key()`, `drift_latest_key()` |
| `common/ml_common/drift.py` | **Mới.** Gom cửa sổ, join `request_id`, luật quy mức độ. Thuần pandas |
| `services/agent/scenarios.py` | **Mới.** 5 kịch bản bóp méo — hàm thuần trên dict |
| `services/agent/runner.py` | **Mới.** Lõi agent: dựng request, gọi HTTP, gom feedback |
| `services/agent/__main__.py` | **Mới.** CLI |
| `services/agent/Dockerfile` | **Mới.** `FROM ml-base:latest` + httpx |
| `services/serving/app.py` | **Sửa:** thêm `POST /feedback/{task_type}` và `write_ground_truth` |
| `stages/monitor/main.py` | **Mới.** Gọi Evidently, ghi report + summary |
| `stages/monitor/Dockerfile` | **Mới.** `FROM ml-base:latest` + Evidently |
| `dags/monitoring_dag.py` | **Mới.** DAG theo lịch, một task mỗi `task_type` |
| `scripts/build_stage_images.ps1` | **Sửa:** thêm `ml-monitor` |
| `scripts/verify_monitoring.ps1` | **Mới.** Một lệnh xác nhận Plan 4 |

**Vì sao `drift.py` nằm ở `common/` chứ không ở `stages/monitor/`:** luật quy mức độ là phần dễ sai nhất và đáng test nhất của plan này. Ở `common/` thì nó chạy trong bộ test đã có, ở máy dev, không cần Evidently và không cần container. Ranh giới: `drift.py` **quyết định mức độ**, `monitor/main.py` **gọi Evidently và ghi file**.

**Vì sao `scenarios.py` tách khỏi `runner.py`:** `scenarios.py` là hàm thuần trên dict — test được bằng bảng tham số, không cần HTTP. `runner.py` lo IO. Tách ra thì test được từng kịch bản mà không dựng server giả.

---

## Task 1: Xác minh API Evidently và dựng image `ml-monitor`

Spec mục 2.3 yêu cầu task đầu tiên là xác minh API thật trên đúng version được pin, **không viết chay theo trí nhớ**. Evidently đổi API giữa 0.4 và 0.7; code chép từ blog cũ sẽ hỏng.

**Files:**
- Create: `stages/monitor/Dockerfile`
- Modify: `scripts/build_stage_images.ps1`

**Interfaces:**
- Produces: image `ml-monitor:latest` có Evidently 0.7.x; xác nhận được chữ ký `Report.run(current, reference)`

- [ ] **Step 1: Viết Dockerfile cho `ml-monitor`**

Tạo `stages/monitor/Dockerfile`:

```dockerfile
# Monitoring stage. Build from the repo root:
#   docker build -f stages/monitor/Dockerfile -t ml-monitor:latest .
#
# Evidently lives ONLY here. It pulls in plotly and around 500MB, and
# ml-base is the parent of six stage images plus serving - none of which
# ever compute drift. Putting it in the base would make every one of them
# carry the weight.
FROM ml-base:latest

RUN pip install --no-cache-dir "evidently>=0.7,<0.8"

COPY stages/monitor/main.py /app/main.py

WORKDIR /app
CMD ["python", "main.py"]
```

- [ ] **Step 2: Build image**

```powershell
docker build -f stages/monitor/Dockerfile -t ml-monitor:latest .
```

Expected: build xong, không lỗi. Nếu `ml-base:latest` chưa có thì chạy `scripts\build_base_image.ps1` trước.

- [ ] **Step 3: Xác minh API thật bên trong image**

Đây là bước then chốt của task này. Chạy:

```powershell
docker run --rm ml-monitor:latest python -c "import evidently, inspect; from evidently import Report; print('version:', evidently.__version__); print('run signature:', inspect.signature(Report.run))"
```

Expected: in ra version `0.7.x`, và chữ ký của `Report.run` cho thấy tham số **current đứng trước reference**.

**Ghi lại kết quả thật vào commit message.** Nếu chữ ký khác những gì spec mục 2.3 mô tả thì **dừng lại và báo** — đừng tự sửa spec, đừng tự đoán.

- [ ] **Step 4: Chạy thử một report tối thiểu**

```powershell
docker run --rm ml-monitor:latest python -c @'
import pandas as pd
from evidently import DataDefinition, Dataset, Report
from evidently.presets import DataDriftPreset

ref = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0] * 25, "b": ["x", "y"] * 50})
cur = pd.DataFrame({"a": [9.0, 9.5, 10.0, 10.5] * 25, "b": ["z"] * 100})

schema = DataDefinition(numerical_columns=["a"], categorical_columns=["b"])
report = Report([DataDriftPreset()])
results = report.run(Dataset.from_pandas(cur, data_definition=schema),
                     Dataset.from_pandas(ref, data_definition=schema))
d = results.dict()
print("keys:", list(d.keys()))
print(d)
'@
```

Expected: chạy được, in ra dict. **Ghi lại hình dạng dict này** — Task 9 cần biết chính xác lấy tỉ lệ cột drift ra từ đường dẫn nào trong dict.

Hai tập dữ liệu trên cố tình khác hẳn nhau (`a` nhảy từ 1–4 sang 9–10.5, `b` đổi hoàn toàn giá trị), nên drift **phải** được phát hiện. Nếu nó báo không drift thì có gì đó sai với cách gọi, không phải với dữ liệu.

- [ ] **Step 5: Thêm `ml-monitor` vào script build**

Sửa `scripts/build_stage_images.ps1`, thêm vào mảng `$stages`:

```powershell
    @{ Dir = "register";                  Tag = "ml-register:latest" },
    @{ Dir = "monitor";                   Tag = "ml-monitor:latest" }
```

(chú ý dấu phẩy sau dòng `register`)

- [ ] **Step 6: Chạy lại script build để chắc không hỏng gì**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_stage_images.ps1
```

Expected: 7 image build xong, dòng cuối `All stage images built.`

- [ ] **Step 7: Commit**

```bash
git add stages/monitor/Dockerfile scripts/build_stage_images.ps1
git commit -m "$(cat <<'EOF'
build: ml-monitor image carrying Evidently

Evidently is installed only here. It pulls in plotly and about 500MB, and
ml-base is the parent of six stage images plus serving, none of which ever
compute drift.

Verified inside the image rather than from memory: Evidently <FILL IN THE
VERSION PRINTED IN STEP 3>, and Report.run takes current before reference.
A minimal report over two deliberately different frames reports drift, so
the call shape is right.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

Thay `<FILL IN...>` bằng version thật in ra ở Step 3.

---

## Task 2: Hai hàm key mới trong `storage.py`

**Files:**
- Modify: `common/ml_common/storage.py`
- Test: `common/tests/test_storage.py`

**Interfaces:**
- Produces: `storage.drift_summary_key(model_name, run_id) -> str`, `storage.drift_latest_key(model_name) -> str`

- [ ] **Step 1: Viết test fail trước**

Thêm vào `common/tests/test_storage.py`:

```python
def test_drift_summary_key_sits_beside_the_evidently_report():
    from ml_common.storage import drift_summary_key, report_key

    summary = drift_summary_key("house_price_regressor", "abc123")
    assert summary == "reports/house_price_regressor/abc123/summary.json"
    # Same run prefix as the full report, so one listing finds both.
    assert summary.rsplit("/", 1)[0] == report_key(
        "house_price_regressor", "abc123", "html"
    ).rsplit("/", 1)[0]


def test_drift_latest_key_is_one_object_per_model():
    from ml_common.storage import drift_latest_key

    assert drift_latest_key("house_price_regressor") == "reports/house_price_regressor/latest.json"
```

- [ ] **Step 2: Chạy test cho fail**

```powershell
.venv\Scripts\python.exe -m pytest common/tests/test_storage.py -k drift -v
```

Expected: FAIL với `ImportError: cannot import name 'drift_summary_key'`

- [ ] **Step 3: Implement**

Thêm vào `common/ml_common/storage.py`, ngay sau hàm `report_key`:

```python
def drift_summary_key(model_name: str, run_id: str) -> str:
    """Builds the path to the short drift verdict of one monitoring run.

    Args:
        model_name: the registered model that was monitored.
        run_id: the monitoring run's identifier.

    Returns:
        The key, e.g. "reports/house_price_regressor/a1b2c3/summary.json".
        It sits in the same prefix as the full Evidently report, so one
        listing finds both, but it stays small enough to read in bulk when
        drawing a history.

    Example:
        drift_summary_key("house_price_regressor", "a1b2c3")
        # -> "reports/house_price_regressor/a1b2c3/summary.json"
    """
    return f"reports/{model_name}/{run_id}/summary.json"


def drift_latest_key(model_name: str) -> str:
    """Builds the path to the most recent drift verdict for a model.

    Args:
        model_name: the registered model.

    Returns:
        The key, e.g. "reports/house_price_regressor/latest.json". One object
        per model, overwritten every run.

    Example:
        drift_latest_key("house_price_regressor")
        # -> "reports/house_price_regressor/latest.json"

        # Plan 5 answers /api/drift/latest with a single read of this key,
        # rather than listing the whole prefix and comparing timestamps.
    """
    return f"reports/{model_name}/latest.json"
```

- [ ] **Step 4: Chạy test cho pass**

```powershell
.venv\Scripts\python.exe -m pytest common/tests/test_storage.py -k drift -v
.venv\Scripts\python.exe -m ruff check . --fix
```

Expected: 2 passed, ruff sạch.

- [ ] **Step 5: Commit**

```bash
git add common/ml_common/storage.py common/tests/test_storage.py
git commit -m "$(cat <<'EOF'
feat: storage keys for the drift verdict

summary.json sits in the same run prefix as the Evidently report but stays
small, so a history can read many of them. latest.json is one object per
model, overwritten each run, so plan 5 answers /api/drift/latest with a
single read instead of listing the prefix and sorting by time.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `drift.py` — gom cửa sổ và join ground truth

**Files:**
- Create: `common/ml_common/drift.py`
- Test: `common/tests/test_drift.py`

**Interfaces:**
- Consumes: `storage.Storage`, `storage.inference_log_prefix`, `storage.ground_truth_prefix`
- Produces:
  - `drift.days_in_window(end: datetime, window_hours: int) -> list[date]`
  - `drift.load_predictions(storage, model_name, end, window_hours) -> pd.DataFrame`
  - `drift.load_outcomes(storage, model_name, end, window_hours) -> pd.DataFrame`
  - `drift.decode_raw_inputs(frame: pd.DataFrame) -> pd.DataFrame`
  - `drift.join_outcomes(predictions, outcomes) -> pd.DataFrame`

- [ ] **Step 1: Viết test fail trước**

Tạo `common/tests/test_drift.py`:

```python
"""Tests for the pure-pandas half of monitoring.

Nothing here imports Evidently: that is the whole reason the severity rules
and the window handling live in common/ instead of in the monitor stage.
"""

import json
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from ml_common import drift


def test_days_in_window_covers_a_single_day():
    end = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)
    assert drift.days_in_window(end, 6) == [date(2026, 9, 20)]


def test_days_in_window_spans_midnight():
    # 24 hours back from 09:00 reaches into the previous day.
    end = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)
    assert drift.days_in_window(end, 24) == [date(2026, 9, 19), date(2026, 9, 20)]


def test_days_in_window_spans_three_days():
    end = datetime(2026, 9, 20, 1, 0, tzinfo=UTC)
    assert drift.days_in_window(end, 48) == [
        date(2026, 9, 18),
        date(2026, 9, 19),
        date(2026, 9, 20),
    ]


def test_decode_raw_inputs_turns_json_strings_back_into_columns():
    frame = pd.DataFrame(
        {
            "request_id": ["r1", "r2"],
            "raw_input": [
                json.dumps({"city": "boston", "bedrooms": 3}),
                json.dumps({"city": "miami", "bedrooms": 4}),
            ],
        }
    )
    result = drift.decode_raw_inputs(frame)
    assert list(result.columns) == ["city", "bedrooms"]
    assert result["city"].tolist() == ["boston", "miami"]
    assert result["bedrooms"].tolist() == [3, 4]


def test_decode_raw_inputs_fills_missing_keys_with_none():
    # Serving accepts a record that omits an optional column, so two rows in
    # the same log can carry different keys.
    frame = pd.DataFrame(
        {
            "request_id": ["r1", "r2"],
            "raw_input": [
                json.dumps({"city": "boston", "bedrooms": 3}),
                json.dumps({"city": "miami"}),
            ],
        }
    )
    result = drift.decode_raw_inputs(frame)
    assert result["bedrooms"].tolist()[0] == 3
    assert pd.isna(result["bedrooms"].tolist()[1])


def test_decode_raw_inputs_on_empty_frame_returns_empty():
    frame = pd.DataFrame({"request_id": [], "raw_input": []})
    assert len(drift.decode_raw_inputs(frame)) == 0


def test_join_outcomes_keeps_only_rows_with_ground_truth():
    predictions = pd.DataFrame(
        {"request_id": ["r1", "r2", "r3"], "prediction": [100.0, 200.0, 300.0]}
    )
    outcomes = pd.DataFrame({"request_id": ["r1", "r3"], "actual": [110.0, 280.0]})

    joined = drift.join_outcomes(predictions, outcomes)

    assert joined["request_id"].tolist() == ["r1", "r3"]
    assert joined["prediction"].tolist() == [100.0, 300.0]
    assert joined["actual"].tolist() == [110.0, 280.0]


def test_join_outcomes_ignores_feedback_for_unknown_requests():
    # Feedback can arrive for a prediction served before the window started.
    predictions = pd.DataFrame({"request_id": ["r1"], "prediction": [100.0]})
    outcomes = pd.DataFrame({"request_id": ["r1", "older"], "actual": [110.0, 999.0]})

    joined = drift.join_outcomes(predictions, outcomes)

    assert len(joined) == 1
    assert joined["request_id"].tolist() == ["r1"]


def test_join_outcomes_with_no_feedback_returns_empty_not_error():
    predictions = pd.DataFrame({"request_id": ["r1"], "prediction": [100.0]})
    outcomes = pd.DataFrame({"request_id": [], "actual": []})

    joined = drift.join_outcomes(predictions, outcomes)

    assert len(joined) == 0
    assert "prediction" in joined.columns


class FakeStorage:
    """Stands in for Storage: keys to DataFrames, no boto3 and no MinIO."""

    def __init__(self, frames: dict):
        self._frames = frames

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self._frames if k.startswith(prefix))

    def read_parquet(self, key: str) -> pd.DataFrame:
        return self._frames[key]


def test_load_predictions_concatenates_every_part_in_the_window():
    frames = {
        "inference-log/m/dt=2026-09-20/part-a.parquet": pd.DataFrame(
            {"request_id": ["r1"], "prediction": [1.0]}
        ),
        "inference-log/m/dt=2026-09-20/part-b.parquet": pd.DataFrame(
            {"request_id": ["r2"], "prediction": [2.0]}
        ),
    }
    end = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)

    result = drift.load_predictions(FakeStorage(frames), "m", end, 6)

    assert sorted(result["request_id"].tolist()) == ["r1", "r2"]


def test_load_predictions_reads_both_days_when_the_window_spans_midnight():
    frames = {
        "inference-log/m/dt=2026-09-19/part-a.parquet": pd.DataFrame(
            {"request_id": ["yesterday"], "prediction": [1.0]}
        ),
        "inference-log/m/dt=2026-09-20/part-b.parquet": pd.DataFrame(
            {"request_id": ["today"], "prediction": [2.0]}
        ),
    }
    end = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)

    result = drift.load_predictions(FakeStorage(frames), "m", end, 24)

    assert sorted(result["request_id"].tolist()) == ["today", "yesterday"]


def test_load_predictions_with_no_traffic_returns_empty_frame():
    end = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)
    result = drift.load_predictions(FakeStorage({}), "m", end, 6)
    assert len(result) == 0


def test_load_outcomes_reads_the_ground_truth_prefix():
    frames = {
        "ground-truth/m/dt=2026-09-20/part-a.parquet": pd.DataFrame(
            {"request_id": ["r1"], "actual": [110.0]}
        ),
    }
    end = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)

    result = drift.load_outcomes(FakeStorage(frames), "m", end, 6)

    assert result["actual"].tolist() == [110.0]


def test_load_predictions_skips_a_day_that_has_no_files():
    frames = {
        "inference-log/m/dt=2026-09-20/part-a.parquet": pd.DataFrame(
            {"request_id": ["r1"], "prediction": [1.0]}
        ),
    }
    end = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)

    # 2026-09-19 has no traffic at all; that is silence, not an error.
    result = drift.load_predictions(FakeStorage(frames), "m", end, 24)

    assert result["request_id"].tolist() == ["r1"]
```

- [ ] **Step 2: Chạy test cho fail**

```powershell
.venv\Scripts\python.exe -m pytest common/tests/test_drift.py -v
```

Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.drift'`

- [ ] **Step 3: Implement**

Tạo `common/ml_common/drift.py`:

```python
"""The half of monitoring that does not need Evidently.

Reading the window, rebuilding the raw records, joining ground truth, and
deciding what counts as `ok`, `warning` or `high` are all plain pandas. They
live here rather than in the monitor stage for one reason: the severity
rules are the part most likely to be wrong, and here they run in the test
suite on a dev machine with no container and no Evidently.

The split is: this module DECIDES, and `stages/monitor/main.py` calls
Evidently and writes the files.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd

from .storage import ground_truth_prefix, inference_log_prefix


def days_in_window(end: datetime, window_hours: int) -> list[date]:
    """Lists the day partitions a time window touches.

    Args:
        end: the end of the window, timezone-aware and in UTC.
        window_hours: how many hours back the window reaches.

    Returns:
        Every date from the start of the window to `end`, in order. A window
        that reaches back across midnight returns more than one date, which
        is why this exists at all: the logs are partitioned by day, so a
        24-hour window almost always has to read two prefixes.

    Example:
        days_in_window(datetime(2026, 9, 20, 18, tzinfo=UTC), 6)
        # -> [date(2026, 9, 20)]

        days_in_window(datetime(2026, 9, 20, 9, tzinfo=UTC), 24)
        # -> [date(2026, 9, 19), date(2026, 9, 20)]
    """
    start = end - timedelta(hours=window_hours)
    days: list[date] = []
    cursor = start.date()
    while cursor <= end.date():
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _read_prefix_days(storage, prefix_builder, model_name: str, days: list[date]) -> pd.DataFrame:
    """Reads and concatenates every parquet part under one prefix per day.

    Args:
        storage: anything with `list_keys` and `read_parquet`.
        prefix_builder: a function taking (model_name, day) and returning a prefix.
        model_name: the registered model whose data is wanted.
        days: the day partitions to read.

    Returns:
        One DataFrame holding every part found, with a fresh index. A day
        with no files contributes nothing; no files at all returns an empty
        DataFrame rather than raising, because "nobody sent traffic" is a
        normal state, not a failure.
    """
    frames: list[pd.DataFrame] = []
    for day in days:
        for key in storage.list_keys(prefix_builder(model_name, day)):
            frames.append(storage.read_parquet(key))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def load_predictions(storage, model_name: str, end: datetime, window_hours: int) -> pd.DataFrame:
    """Reads every prediction served inside the window.

    Args:
        storage: a `Storage`, or anything with `list_keys` and `read_parquet`.
        model_name: the registered model that served them.
        end: the end of the window, timezone-aware UTC.
        window_hours: how far back to read.

    Returns:
        The inference log rows - request_id, timestamp, raw_input, prediction,
        model_name, model_version - concatenated across every part file of
        every day the window touches. Empty when there was no traffic.

    Example:
        predictions = load_predictions(storage, "house_price_regressor", now, 24)
        # -> 1,432 rows gathered from part files across two day partitions
    """
    return _read_prefix_days(storage, inference_log_prefix, model_name, days_in_window(end, window_hours))


def load_outcomes(storage, model_name: str, end: datetime, window_hours: int) -> pd.DataFrame:
    """Reads every ground-truth outcome reported for the window.

    Args:
        storage: a `Storage`, or anything with `list_keys` and `read_parquet`.
        model_name: the registered model the outcomes belong to.
        end: the end of the window, timezone-aware UTC.
        window_hours: how far back to read.

    Returns:
        The ground-truth rows - request_id, actual, received_at - or an empty
        DataFrame. Empty is the normal state early on: ground truth always
        arrives later than the prediction it describes.

    Example:
        outcomes = load_outcomes(storage, "house_price_regressor", now, 24)
        # -> often empty on the first run, which is not an error
    """
    return _read_prefix_days(storage, ground_truth_prefix, model_name, days_in_window(end, window_hours))


def decode_raw_inputs(frame: pd.DataFrame) -> pd.DataFrame:
    """Rebuilds the served records from the JSON text in the inference log.

    Serving stores each record as `json.dumps(record)` in a single
    `raw_input` column, because a record's shape varies from call to call and
    parquet wants a fixed schema. Evidently needs real columns back.

    Args:
        frame: inference log rows carrying a `raw_input` column.

    Returns:
        A DataFrame of the decoded records, one row per input row, indexed
        positionally. Keys absent from a record become NaN, so two rows that
        carried different optional columns still line up. An empty input
        returns an empty DataFrame.

    Example:
        decode_raw_inputs(log)
        # -> columns city, bedrooms, list_price, ... exactly as callers sent
        #    them, still raw: "$450,000" is still a string here.
    """
    if len(frame) == 0:
        return pd.DataFrame()
    records = [json.loads(text) for text in frame["raw_input"]]
    return pd.DataFrame(records)


def join_outcomes(predictions: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    """Matches predictions to the outcomes that were later reported for them.

    Args:
        predictions: inference log rows, carrying `request_id` and `prediction`.
        outcomes: ground-truth rows, carrying `request_id` and `actual`.

    Returns:
        Only the rows where both sides exist - an inner join on `request_id`.
        Feedback for a prediction served before the window is dropped, and so
        is a prediction nobody has reported on yet. That second group is the
        normal case, and its size is what decides whether performance drift
        can be measured at all.

    Example:
        joined = join_outcomes(predictions, outcomes)
        # -> 137 rows out of 1,432 predictions; the other 1,295 have no
        #    outcome yet, which is why performance drift always lags.
    """
    if len(predictions) == 0 or len(outcomes) == 0:
        empty = predictions.iloc[0:0].copy()
        empty["actual"] = pd.Series(dtype="object")
        return empty
    return predictions.merge(outcomes[["request_id", "actual"]], on="request_id", how="inner")
```

- [ ] **Step 4: Chạy test cho pass**

```powershell
.venv\Scripts\python.exe -m pytest common/tests/test_drift.py -v
.venv\Scripts\python.exe -m ruff check . --fix
```

Expected: 13 passed, ruff sạch.

- [ ] **Step 5: Commit**

```bash
git add common/ml_common/drift.py common/tests/test_drift.py
git commit -m "$(cat <<'EOF'
feat: read the monitoring window and join ground truth

A window is expressed in hours but the logs are partitioned by day, so a
24-hour window normally has to read two prefixes; days_in_window works that
out and the readers follow it. A day with no files contributes nothing
rather than raising, because no traffic is a normal state.

decode_raw_inputs rebuilds real columns from the JSON text serving stores,
which is what Evidently will need. join_outcomes is an inner join, so its
row count is also the answer to whether performance drift can be measured
at all.

Nothing here imports Evidently, so it all runs in the dev test suite.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `drift.py` — luật quy ra mức độ

**Files:**
- Modify: `common/ml_common/drift.py`
- Test: `common/tests/test_drift.py`

**Interfaces:**
- Consumes: `metrics.compute_metrics`
- Produces:
  - `drift.SEVERITIES = ("ok", "warning", "high")`, `drift.INSUFFICIENT = "insufficient_data"`
  - `drift.MIN_GROUND_TRUTH = 50`
  - `drift.feature_severity(drifted_share: float) -> str`
  - `drift.prediction_severity(drifted: bool) -> str`
  - `drift.performance_severity(task_type, current: dict, train: dict, n_joined: int) -> str`
  - `drift.overall_severity(parts: dict) -> str`

- [ ] **Step 1: Viết test fail trước**

Thêm vào `common/tests/test_drift.py`:

```python
@pytest.mark.parametrize(
    ("share", "expected"),
    [
        (0.0, "ok"),
        (0.29, "ok"),
        (0.3, "warning"),
        (0.5, "warning"),
        (0.51, "high"),
        (1.0, "high"),
    ],
)
def test_feature_severity_thresholds(share, expected):
    assert drift.feature_severity(share) == expected


def test_prediction_severity_is_binary():
    assert drift.prediction_severity(False) == "ok"
    assert drift.prediction_severity(True) == "high"


def test_performance_severity_says_insufficient_below_the_floor():
    # Not "ok". A green badge when nobody has checked is the dangerous lie.
    result = drift.performance_severity(
        "regression", {"rmse": 41_000.0}, {"rmse": 41_000.0}, n_joined=10
    )
    assert result == "insufficient_data"


def test_performance_severity_at_exactly_the_floor_is_measured():
    result = drift.performance_severity(
        "regression", {"rmse": 41_000.0}, {"rmse": 41_000.0}, n_joined=drift.MIN_GROUND_TRUTH
    )
    assert result == "ok"


@pytest.mark.parametrize(
    ("current_rmse", "expected"),
    [
        (41_000.0, "ok"),
        (49_199.0, "ok"),
        (49_200.0, "warning"),
        (61_500.0, "warning"),
        (61_501.0, "high"),
    ],
)
def test_performance_severity_regression_uses_the_rmse_ratio(current_rmse, expected):
    # Train rmse 41_000: warning at 1.2x = 49_200, high above 1.5x = 61_500.
    result = drift.performance_severity(
        "regression", {"rmse": current_rmse}, {"rmse": 41_000.0}, n_joined=500
    )
    assert result == expected


@pytest.mark.parametrize(
    ("current_auc", "expected"),
    [
        (0.72, "ok"),
        (0.71, "ok"),
        (0.66, "warning"),
        (0.61, "warning"),
        (0.60, "high"),
    ],
)
def test_performance_severity_classification_uses_the_auc_drop(current_auc, expected):
    # Train auc 0.71: warning once it drops 0.05, high once it drops 0.10.
    result = drift.performance_severity(
        "classification", {"auc": current_auc}, {"auc": 0.71}, n_joined=500
    )
    assert result == expected


def test_performance_severity_improving_is_never_worse_than_ok():
    result = drift.performance_severity(
        "regression", {"rmse": 20_000.0}, {"rmse": 41_000.0}, n_joined=500
    )
    assert result == "ok"


def test_overall_severity_takes_the_worst():
    assert drift.overall_severity({"feature": "ok", "prediction": "ok", "performance": "ok"}) == "ok"
    assert (
        drift.overall_severity({"feature": "warning", "prediction": "ok", "performance": "ok"})
        == "warning"
    )
    assert (
        drift.overall_severity({"feature": "warning", "prediction": "high", "performance": "ok"})
        == "high"
    )


def test_overall_severity_ignores_insufficient_data():
    # Unmeasured must not drag the verdict up OR down.
    result = drift.overall_severity(
        {"feature": "ok", "prediction": "ok", "performance": "insufficient_data"}
    )
    assert result == "ok"

    result = drift.overall_severity(
        {"feature": "high", "prediction": "ok", "performance": "insufficient_data"}
    )
    assert result == "high"


def test_overall_severity_with_nothing_measured_is_insufficient():
    result = drift.overall_severity(
        {
            "feature": "insufficient_data",
            "prediction": "insufficient_data",
            "performance": "insufficient_data",
        }
    )
    assert result == "insufficient_data"
```

- [ ] **Step 2: Chạy test cho fail**

```powershell
.venv\Scripts\python.exe -m pytest common/tests/test_drift.py -k severity -v
```

Expected: FAIL với `AttributeError: module 'ml_common.drift' has no attribute 'feature_severity'`

- [ ] **Step 3: Implement**

Thêm vào cuối `common/ml_common/drift.py`:

```python
SEVERITIES = ("ok", "warning", "high")

# Performance drift has a third state the other two do not. Ground truth
# always arrives later than the prediction it describes, so early on there is
# simply nothing to measure. Reporting "ok" then would put a green badge on a
# dashboard when the truthful answer is "nobody has checked yet".
INSUFFICIENT = "insufficient_data"

MIN_GROUND_TRUTH = 50

FEATURE_WARNING_SHARE = 0.3
FEATURE_HIGH_SHARE = 0.5

RMSE_WARNING_RATIO = 1.2
RMSE_HIGH_RATIO = 1.5

AUC_WARNING_DROP = 0.05
AUC_HIGH_DROP = 0.10


def feature_severity(drifted_share: float) -> str:
    """Grades feature drift from the share of columns Evidently flagged.

    Args:
        drifted_share: fraction of columns reported as drifted, 0.0 to 1.0.

    Returns:
        "ok" below 0.3, "warning" from 0.3 through 0.5, "high" above 0.5.

    Example:
        feature_severity(0.1)   # -> "ok", a column or two moving is normal
        feature_severity(0.4)   # -> "warning"
        feature_severity(0.8)   # -> "high"

        # These numbers are a starting point, not a conclusion. Calibrate
        # them against a scenario=none run: if no-drift traffic already
        # scores 0.25, the 0.3 line is far too close.
    """
    if drifted_share > FEATURE_HIGH_SHARE:
        return "high"
    if drifted_share >= FEATURE_WARNING_SHARE:
        return "warning"
    return "ok"


def prediction_severity(drifted: bool) -> str:
    """Grades prediction drift, which is a single column and so a yes or no.

    Args:
        drifted: whether Evidently flagged the prediction column.

    Returns:
        "high" when it drifted, "ok" otherwise. There is no middle grade:
        one column cannot be partly drifted, and the model's own output
        shifting is worth looking at whenever it happens.

    Example:
        prediction_severity(True)   # -> "high"
        prediction_severity(False)  # -> "ok"
    """
    return "high" if drifted else "ok"


def performance_severity(task_type: str, current: dict, train: dict, n_joined: int) -> str:
    """Grades how far real accuracy has fallen from what training measured.

    Args:
        task_type: "regression" or "classification".
        current: metrics computed over the rows that have ground truth.
        train: the metrics logged by the train stage for this model version.
        n_joined: how many rows had ground truth. Below MIN_GROUND_TRUTH the
            metric is too noisy to act on.

    Returns:
        "insufficient_data" when n_joined is below the floor. Otherwise for
        regression, the rmse ratio: "ok" below 1.2x, "warning" to 1.5x,
        "high" above. For classification, the auc drop: "ok" under 0.05,
        "warning" to 0.10, "high" beyond. A model doing BETTER than at
        training is "ok", never worse.

    Raises:
        KeyError: when the metric a task needs is missing from either dict.
            Guessing would report a verdict nobody measured.

    Example:
        performance_severity("regression", {"rmse": 41000}, {"rmse": 41000}, 500)
        # -> "ok"

        performance_severity("regression", {"rmse": 70000}, {"rmse": 41000}, 500)
        # -> "high", predictions are off by 70% more than they were

        performance_severity("regression", {"rmse": 41000}, {"rmse": 41000}, 10)
        # -> "insufficient_data", NOT "ok" - 10 rows decides nothing
    """
    if n_joined < MIN_GROUND_TRUTH:
        return INSUFFICIENT

    if task_type == "regression":
        ratio = current["rmse"] / train["rmse"]
        if ratio > RMSE_HIGH_RATIO:
            return "high"
        if ratio >= RMSE_WARNING_RATIO:
            return "warning"
        return "ok"

    drop = train["auc"] - current["auc"]
    if drop >= AUC_HIGH_DROP:
        return "high"
    if drop >= AUC_WARNING_DROP:
        return "warning"
    return "ok"


def overall_severity(parts: dict) -> str:
    """Reduces the three drift verdicts to the one a dashboard shows.

    Args:
        parts: the per-type verdicts, e.g.
            {"feature": "ok", "prediction": "ok", "performance": "high"}.

    Returns:
        The worst of the measured verdicts. `insufficient_data` is skipped
        rather than counted: something unmeasured must not drag the badge up,
        and must not hold it down either. When nothing at all was measured,
        the answer is `insufficient_data`, because "ok" would claim a check
        that never happened.

    Example:
        overall_severity({"feature": "warning", "prediction": "high", "performance": "ok"})
        # -> "high"

        overall_severity({"feature": "ok", "prediction": "ok",
                          "performance": "insufficient_data"})
        # -> "ok", feature and prediction really were measured and were fine

        overall_severity({"feature": "insufficient_data",
                          "prediction": "insufficient_data",
                          "performance": "insufficient_data"})
        # -> "insufficient_data"
    """
    measured = [value for value in parts.values() if value in SEVERITIES]
    if not measured:
        return INSUFFICIENT
    return max(measured, key=SEVERITIES.index)
```

- [ ] **Step 4: Chạy test cho pass**

```powershell
.venv\Scripts\python.exe -m pytest common/tests/test_drift.py -v
.venv\Scripts\python.exe -m ruff check . --fix
```

Expected: toàn bộ test trong file pass, ruff sạch.

- [ ] **Step 5: Commit**

```bash
git add common/ml_common/drift.py common/tests/test_drift.py
git commit -m "$(cat <<'EOF'
feat: severity rules for the three drift types

Performance drift gets a third state the others do not have. Ground truth
arrives after the prediction it describes, so early on there is nothing to
measure, and reporting ok there would put a green badge on a dashboard when
the honest answer is that nobody has checked. overall_severity skips that
state rather than counting it, so unmeasured neither raises nor lowers the
verdict, and returns it when nothing at all was measured.

The thresholds are a starting point. They need calibrating against a
scenario=none run: if traffic with no drift already scores 0.25 drifted
columns, the 0.3 warning line is far too close.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `scenarios.py` — 5 kịch bản thị trường

**Files:**
- Create: `services/agent/__init__.py`, `services/agent/scenarios.py`
- Test: `services/agent/tests/__init__.py`, `services/agent/tests/test_scenarios.py`

**Interfaces:**
- Consumes: không gì (hàm thuần trên dict)
- Produces:
  - `scenarios.SCENARIOS = ("none", "price_inflation", "market_rally", "market_shift", "new_segment")`
  - `scenarios.PRICE_FACTOR = 1.2`
  - `scenarios.apply_scenario(record: dict, scenario: str) -> dict`
  - `scenarios.adjust_truth(actual, scenario: str, task_type: str)`

- [ ] **Step 1: Viết test fail trước**

Tạo `services/agent/tests/__init__.py` (rỗng) và `services/agent/tests/test_scenarios.py`:

```python
import pytest

from services.agent import scenarios


def base_record() -> dict:
    return {
        "property_id": "p1",
        "city": "boston",
        "property_type": "condo",
        "list_price": 400000.0,
        "bedrooms": 3,
    }


def test_none_changes_nothing():
    record = base_record()
    assert scenarios.apply_scenario(record, "none") == record


def test_apply_scenario_does_not_mutate_the_caller_s_record():
    record = base_record()
    scenarios.apply_scenario(record, "price_inflation")
    assert record["list_price"] == 400000.0


def test_price_inflation_raises_the_asking_price():
    result = scenarios.apply_scenario(base_record(), "price_inflation")
    assert result["list_price"] == pytest.approx(480000.0)


def test_market_rally_raises_the_asking_price_the_same_way():
    result = scenarios.apply_scenario(base_record(), "market_rally")
    assert result["list_price"] == pytest.approx(480000.0)


def test_market_shift_moves_the_city():
    result = scenarios.apply_scenario(base_record(), "market_shift")
    assert result["city"] in scenarios.SHIFT_CITIES
    assert result["city"] != "boston"


def test_new_segment_uses_a_property_type_the_model_never_saw():
    from ml_common import schema

    result = scenarios.apply_scenario(base_record(), "new_segment")
    allowed = schema.COLUMNS["property_type"].allowed
    assert result["property_type"] not in allowed


def test_unknown_scenario_is_rejected():
    with pytest.raises(ValueError, match="scenario"):
        scenarios.apply_scenario(base_record(), "nonsense")


def test_price_inflation_leaves_the_true_sale_price_alone():
    # The whole point: asking prices are inflated but houses still sell for
    # what they were always worth, so the model is misled.
    assert scenarios.adjust_truth(420000.0, "price_inflation", "regression") == 420000.0


def test_market_rally_lifts_the_true_sale_price_too():
    # The market really did move, so the model stays roughly right.
    assert scenarios.adjust_truth(420000.0, "market_rally", "regression") == pytest.approx(504000.0)


def test_none_leaves_the_truth_alone():
    assert scenarios.adjust_truth(420000.0, "none", "regression") == 420000.0


def test_truth_is_never_scaled_for_classification():
    # needs_renovation is a bool. Multiplying it by 1.2 is meaningless.
    assert scenarios.adjust_truth(True, "market_rally", "classification") is True
    assert scenarios.adjust_truth(False, "price_inflation", "classification") is False


def test_record_missing_the_distorted_column_is_left_alone():
    # Serving accepts records with optional columns missing; the agent must
    # not invent a list_price that was never there.
    record = {"property_id": "p1", "city": "boston"}
    result = scenarios.apply_scenario(record, "price_inflation")
    assert "list_price" not in result


def test_unparseable_price_is_left_alone_rather_than_guessed():
    record = {"property_id": "p1", "list_price": "call for price"}
    result = scenarios.apply_scenario(record, "price_inflation")
    assert result["list_price"] == "call for price"


def test_currency_string_price_is_still_inflated():
    # The raw data mixes plain numbers with currency strings; both must drift.
    record = {"property_id": "p1", "list_price": "$400,000"}
    result = scenarios.apply_scenario(record, "price_inflation")
    assert result["list_price"] == pytest.approx(480000.0)
```

- [ ] **Step 2: Chạy test cho fail**

```powershell
.venv\Scripts\python.exe -m pytest services/agent/tests/test_scenarios.py -v
```

Expected: FAIL với `ModuleNotFoundError: No module named 'services.agent'`

- [ ] **Step 3: Implement**

Tạo `services/agent/__init__.py` (rỗng) và `services/agent/scenarios.py`:

```python
"""The five market scenarios the agent can simulate.

Every scenario starts from a REAL row of the dataset and distorts it. That
keeps the relationships between columns believable - a generated house with
twenty bedrooms and thirty square metres would produce drift that means
nothing.

The interesting pair is `price_inflation` and `market_rally`. Both multiply
the asking price by the same factor; they differ only in whether the true
sale price moves with it. That one difference is what separates drift that
hurts the model from drift that does not, and it is the reason the three
drift types are reported separately at all.

Pure functions on dicts: no HTTP, no pandas, no config.
"""

from __future__ import annotations

from ml_common.parsers import parse_money

SCENARIOS = (
    "none",
    "price_inflation",
    "market_rally",
    "market_shift",
    "new_segment",
)

PRICE_FACTOR = 1.2

# Somewhere the training data barely covers, so concentrating traffic here
# genuinely shifts the city distribution.
SHIFT_CITIES = ("phoenix",)

# Deliberately absent from schema.COLUMNS["property_type"].allowed. Serving
# must survive it: the OneHotEncoder was built with
# handle_unknown="infrequent_if_exist" for exactly this.
NEW_PROPERTY_TYPE = "floating home"

# Scenarios that move the true outcome along with the features. Only these
# simulate a market that really rose, as opposed to sellers merely asking
# for more.
_TRUTH_SCALED = {"market_rally": PRICE_FACTOR}


def _check_scenario(scenario: str) -> None:
    """Rejects a scenario name that does not exist.

    Args:
        scenario: the name to check.

    Returns:
        Nothing when the name is valid.

    Raises:
        ValueError: otherwise. A typo must not silently become "no distortion
            at all", which would look like a clean run rather than a mistake.

    Example:
        _check_scenario("market_rally")  # -> None
        _check_scenario("market_raly")   # -> ValueError
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {SCENARIOS}, got: {scenario!r}")


def apply_scenario(record: dict, scenario: str) -> dict:
    """Distorts one raw record the way a scenario says the market has moved.

    Args:
        record: a raw record as it would be POSTed to /predict. Not modified;
            a new dict is returned.
        scenario: one of SCENARIOS.

    Returns:
        A new record. A column the scenario targets but the record does not
        have is left absent rather than invented, and a price that cannot be
        read as a number is left exactly as it was - the same refusal to
        guess that the parsers make.

    Raises:
        ValueError: when the scenario name is unknown.

    Example:
        apply_scenario({"list_price": "$400,000"}, "price_inflation")
        # -> {"list_price": 480000.0}

        apply_scenario({"city": "boston"}, "market_shift")
        # -> {"city": "phoenix"}

        apply_scenario({"property_type": "condo"}, "new_segment")
        # -> {"property_type": "floating home"}, a value never trained on
    """
    _check_scenario(scenario)
    result = dict(record)

    if scenario in ("price_inflation", "market_rally") and "list_price" in result:
        amount = parse_money(result["list_price"])
        if amount is not None:
            result["list_price"] = amount * PRICE_FACTOR

    if scenario == "market_shift" and "city" in result:
        result["city"] = SHIFT_CITIES[0]

    if scenario == "new_segment" and "property_type" in result:
        result["property_type"] = NEW_PROPERTY_TYPE

    return result


def adjust_truth(actual, scenario: str, task_type: str):
    """Moves the true outcome to stay consistent with a scenario, if it should.

    Args:
        actual: the real outcome from the dataset row - a sale price for
            regression, a bool for classification.
        scenario: one of SCENARIOS.
        task_type: "regression" or "classification".

    Returns:
        For `market_rally` on regression, the price scaled by PRICE_FACTOR:
        the market really did rise, so the model stays roughly right and
        performance drift should NOT fire. For everything else the value
        unchanged - under `price_inflation` houses still sell for what they
        were always worth, which is what makes the model wrong. Classification
        truth is never scaled, because a bool has nothing to scale.

    Raises:
        ValueError: when the scenario name is unknown.

    Example:
        adjust_truth(420000.0, "price_inflation", "regression")  # -> 420000.0
        adjust_truth(420000.0, "market_rally", "regression")     # -> 504000.0
        adjust_truth(True, "market_rally", "classification")     # -> True
    """
    _check_scenario(scenario)
    if task_type != "regression":
        return actual
    factor = _TRUTH_SCALED.get(scenario)
    if factor is None:
        return actual
    return actual * factor
```

- [ ] **Step 4: Chạy test cho pass**

```powershell
.venv\Scripts\python.exe -m pytest services/agent/tests/test_scenarios.py -v
.venv\Scripts\python.exe -m ruff check . --fix
```

Expected: 14 passed, ruff sạch.

- [ ] **Step 5: Commit**

```bash
git add services/agent/ 
git commit -m "$(cat <<'EOF'
feat: five market scenarios for the traffic agent

Each one distorts a real row rather than generating a house from scratch, so
the relationships between columns stay believable.

price_inflation and market_rally multiply the asking price identically and
differ only in whether the true sale price moves with it. Under inflation
houses still sell for what they were worth, so the model is misled and every
drift type fires. Under a rally the market really moved, so the model stays
roughly right and performance drift should stay quiet. Without that second
case every scenario would teach "drift means retrain", which is the wrong
reflex and the reason the drift types are separated at all.

A targeted column that is absent stays absent, and a price that cannot be
read stays as it is, matching what the parsers already refuse to guess.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `runner.py` — lõi agent

**Files:**
- Create: `services/agent/runner.py`
- Test: `services/agent/tests/test_runner.py`

**Interfaces:**
- Consumes: `scenarios.apply_scenario`, `scenarios.adjust_truth`, `ml_common.schema`, `ml_common.targets.derive_target`
- Produces:
  - `runner.build_requests(pool: pd.DataFrame, scenario, task_type, count, seed) -> list[dict]`
  - `runner.send_predictions(post, base_url, task_type, requests) -> list[dict]`
  - `runner.send_feedback(post, base_url, task_type, outcomes) -> dict`

Mỗi phần tử `build_requests` trả về là dict `{"record": dict, "truth": object}`.

- [ ] **Step 1: Viết test fail trước**

Tạo `services/agent/tests/test_runner.py`:

```python
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
```

- [ ] **Step 2: Chạy test cho fail**

```powershell
.venv\Scripts\python.exe -m pytest services/agent/tests/test_runner.py -v
```

Expected: FAIL với `ImportError: cannot import name 'runner'`

- [ ] **Step 3: Implement**

Tạo `services/agent/runner.py`:

```python
"""The agent's core: turn real rows into traffic, then report what happened.

Kept free of HTTP clients and of argument parsing so the whole thing can be
tested by passing in a function that records calls. The CLI in __main__.py
supplies a real one.

Predictions and feedback are two separate calls on purpose. In production
nobody knows what a house sold for at the moment they ask what it is worth,
and splitting the two here keeps that delay visible instead of pretending
the answer arrives with the question.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from ml_common import schema
from ml_common.targets import derive_target

from .scenarios import adjust_truth, apply_scenario


def build_requests(
    pool: pd.DataFrame,
    scenario: str,
    task_type: str,
    count: int,
    seed: int,
) -> list[dict]:
    """Samples real rows and turns them into requests with known outcomes.

    Args:
        pool: rows from the raw dataset, still unparsed.
        scenario: one of `scenarios.SCENARIOS`.
        task_type: "regression" or "classification".
        count: how many requests to build. A pool smaller than this is
            sampled with replacement, so a small pool still produces traffic.
        seed: makes the sample reproducible, so a scenario can be re-run.

    Returns:
        A list of {"record": dict, "truth": value}. The record is what gets
        POSTed - raw, with the target column removed but leakage columns left
        in, because a real caller would send those and the Pipeline's
        SelectColumns is what strips them. Rows whose true outcome cannot be
        read are dropped rather than guessed, so the list may be shorter than
        `count`.

    Example:
        build_requests(pool, "price_inflation", "regression", count=500, seed=42)
        # -> 500 records with list_price multiplied by 1.2, each paired with
        #    the price the house really sold for - unchanged, which is what
        #    makes the model wrong under this scenario.
    """
    if len(pool) == 0:
        return []

    target = schema.target_column(task_type)
    sample = pool.sample(n=count, replace=len(pool) < count, random_state=seed)
    truths = derive_target(sample, task_type)

    requests: list[dict] = []
    for (_, row), truth in zip(sample.iterrows(), truths, strict=True):
        if truth is None or pd.isna(truth):
            continue
        record = {k: v for k, v in row.to_dict().items() if k != target}
        requests.append(
            {
                "record": apply_scenario(record, scenario),
                "truth": adjust_truth(truth, scenario, task_type),
            }
        )
    return requests


def send_predictions(
    post,
    base_url: str,
    task_type: str,
    requests: list[dict],
    now: datetime | None = None,
) -> list[dict]:
    """POSTs each record to /predict and keeps the outcome aside for later.

    Args:
        post: a callable taking (url, json=...) and returning the decoded
            response body. Injected so tests need no server.
        base_url: serving's root, e.g. "http://serving:8000".
        task_type: "regression" or "classification".
        requests: what `build_requests` produced.
        now: the moment to stamp as the prediction day. None reads the clock.

    Returns:
        One dict per served request, carrying `request_id`, `predicted_on`
        and `actual`. `predicted_on` is recorded HERE rather than read back
        from serving: the ground-truth files are partitioned by the day of
        the prediction so they line up with the inference log, and the agent
        is the only party that already knows that day.

    Example:
        served = send_predictions(post, "http://serving:8000", "regression", reqs)
        # -> [{"request_id": "3f0a...", "predicted_on": "2026-09-20",
        #      "actual": 420000.0}, ...]
    """
    moment = datetime.now(UTC) if now is None else now
    day = moment.date().isoformat()

    served: list[dict] = []
    for item in requests:
        body = post(f"{base_url}/predict/{task_type}", json=item["record"])
        served.append(
            {
                "request_id": body["request_id"],
                "predicted_on": day,
                "actual": item["truth"],
            }
        )
    return served


def send_feedback(post, base_url: str, task_type: str, outcomes: list[dict]) -> dict:
    """Reports the real outcomes back to serving as one batch.

    Args:
        post: a callable taking (url, json=...) and returning the decoded body.
        base_url: serving's root.
        task_type: "regression" or "classification".
        outcomes: what `send_predictions` returned, or a subset of it.

    Returns:
        Serving's response. An empty list makes no call at all and returns
        {"accepted": 0}, so "there is nothing to report" costs nothing and
        does not write an empty file.

    Example:
        send_feedback(post, "http://serving:8000", "regression", served)
        # -> {"accepted": 500, "key": "ground-truth/.../part-1a2b3c4d.parquet"}
        # One request, one parquet file - not 500 tiny ones.
    """
    if not outcomes:
        return {"accepted": 0}

    payload = {
        "outcomes": [
            {
                "request_id": item["request_id"],
                "predicted_on": item["predicted_on"],
                "actual": item["actual"],
            }
            for item in outcomes
        ]
    }
    return post(f"{base_url}/feedback/{task_type}", json=payload)
```

- [ ] **Step 4: Chạy test cho pass**

```powershell
.venv\Scripts\python.exe -m pytest services/agent/tests/test_runner.py -v
.venv\Scripts\python.exe -m ruff check . --fix
```

Expected: 15 passed, ruff sạch.

- [ ] **Step 5: Commit**

```bash
git add services/agent/runner.py services/agent/tests/test_runner.py
git commit -m "$(cat <<'EOF'
feat: agent core that turns real rows into traffic

build_requests samples real rows, strips the target, and keeps the true
outcome aside. Leakage columns stay in the record on purpose: a real caller
would send them, and SelectColumns inside the Pipeline is what strips them,
so sending them exercises that guard.

predicted_on is stamped by the agent rather than read back from serving.
Ground-truth files are partitioned by the day of the prediction so they line
up with the inference log, and the agent is the only party that already
knows that day - having serving work it out would mean keeping an index of
request ids, which is state it does not otherwise need.

Predictions and feedback stay two separate calls, because in production
nobody knows what a house sold for at the moment they ask what it is worth.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: CLI, Dockerfile, và service trong compose

**Files:**
- Create: `services/agent/__main__.py`, `services/agent/Dockerfile`
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: `runner.build_requests`, `runner.send_predictions`, `runner.send_feedback`, `storage.Storage`, `storage.raw_key`
- Produces: `python -m services.agent --scenario X --task-type Y --count N`, image `ml-agent:latest`, service `agent` có `profiles: ["agent"]`

- [ ] **Step 1: Viết CLI**

Tạo `services/agent/__main__.py`:

```python
"""Command line for the traffic agent.

Runs one bounded batch and exits. That boundary is the point: a scenario is
only measurable if you can say "exactly these 500 requests were
price_inflation", and a process that runs forever cannot say that without
growing a control API of its own.

The always-on mode is the compose service, which loops over this same code.
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx
import pandas as pd

from ml_common import schema
from ml_common.storage import Storage, raw_key

from .runner import build_requests, send_feedback, send_predictions
from .scenarios import SCENARIOS

DEFAULT_POOL_ROWS = 20_000


def parse_args() -> argparse.Namespace:
    """Reads the command line.

    Args:
        None. Parses sys.argv.

    Returns:
        A namespace with `scenario`, `task_type`, `count`, `seed`,
        `pool_rows`, `feedback_ratio` and `dataset_version`.

    Example:
        # python -m services.agent --scenario price_inflation --count 500
        # -> scenario="price_inflation", count=500, feedback_ratio=1.0
    """
    parser = argparse.ArgumentParser(description="Send simulated traffic to serving.")
    parser.add_argument("--scenario", choices=SCENARIOS, default="none")
    parser.add_argument("--task-type", choices=schema.TASK_TYPES, default="regression")
    parser.add_argument("--count", type=int, default=200, help="requests to send")
    parser.add_argument("--seed", type=int, default=42, help="makes the sample reproducible")
    parser.add_argument(
        "--pool-rows",
        type=int,
        default=DEFAULT_POOL_ROWS,
        help="how many of the most recent raw rows to sample from",
    )
    parser.add_argument(
        "--feedback-ratio",
        type=float,
        default=1.0,
        help="fraction of served requests to report outcomes for; 0 sends none",
    )
    parser.add_argument("--dataset-version", default=os.environ.get("DATASET_VERSION", "v1"))
    return parser.parse_args()


def load_pool(storage: Storage, dataset_version: str, pool_rows: int) -> pd.DataFrame:
    """Reads the most recent raw rows to draw traffic from.

    Args:
        storage: where the raw dataset lives.
        dataset_version: which raw version to read, e.g. "v1".
        pool_rows: how many of the most recent rows, by listing_date, to keep.

    Returns:
        The tail of the dataset ordered by `listing_date`. Whether these rows
        are ones the model has seen depends on SAMPLE_ROWS: `extract` takes
        head(SAMPLE_ROWS), so with the dev setting of 200k the tail really is
        unseen, and on a full 2-million-row run nothing is. Either way the
        drift comes from the scenario, not from the choice of rows.

    Example:
        pool = load_pool(storage, "v1", 20_000)
        # -> the 20,000 most recently listed houses
    """
    frame = storage.read_parquet(raw_key(dataset_version))
    if "listing_date" in frame.columns:
        frame = frame.sort_values("listing_date", na_position="first")
    return frame.tail(pool_rows).reset_index(drop=True)


def main() -> int:
    """Sends one batch of traffic and reports the outcomes.

    Args:
        None. Takes settings from the command line, SERVING_URL (default
        http://serving:8000), and the MinIO variables Storage.from_env needs.

    Returns:
        0 on success, 1 when the pool yielded no usable rows.

    Example:
        # python -m services.agent --scenario price_inflation --count 500
        # -> pool 20000 rows
        #    sent 500 predictions to http://serving:8000
        #    reported 500 outcomes, accepted 500
    """
    args = parse_args()
    base_url = os.environ.get("SERVING_URL", "http://serving:8000").rstrip("/")

    pool = load_pool(Storage.from_env(), args.dataset_version, args.pool_rows)
    print(f"pool {len(pool)} rows", file=sys.stderr)

    requests = build_requests(pool, args.scenario, args.task_type, args.count, args.seed)
    if not requests:
        print("FATAL: no usable rows in the pool", file=sys.stderr)
        return 1

    with httpx.Client(timeout=30.0) as client:

        def post(url: str, json: dict) -> dict:
            response = client.post(url, json=json)
            response.raise_for_status()
            return response.json()

        served = send_predictions(post, base_url, args.task_type, requests)
        print(f"sent {len(served)} predictions to {base_url}", file=sys.stderr)

        reported = served[: int(len(served) * args.feedback_ratio)]
        result = send_feedback(post, base_url, args.task_type, reported)
        print(f"reported {len(reported)} outcomes, accepted {result['accepted']}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Viết Dockerfile**

Tạo `services/agent/Dockerfile`:

```dockerfile
# Traffic agent. Build from the repo root:
#   docker build -f services/agent/Dockerfile -t ml-agent:latest .
#
# FROM ml-base because the agent derives the true label with
# ml_common.targets.derive_target - the same function the prepare stage uses.
# Reimplementing "poor or fair means needs renovation" here would be a second
# copy of a rule that must not drift.
FROM ml-base:latest

RUN pip install --no-cache-dir "httpx>=0.27"

COPY services/__init__.py /app/services/__init__.py
COPY services/agent/ /app/services/agent/

WORKDIR /app
ENV PYTHONPATH=/app
CMD ["python", "-m", "services.agent", "--help"]
```

- [ ] **Step 3: Build image và chạy thử `--help`**

```powershell
docker build -f services/agent/Dockerfile -t ml-agent:latest .
docker run --rm ml-agent:latest
```

Expected: in ra usage của argparse, có đủ `--scenario`, `--task-type`, `--count`, `--feedback-ratio`.

- [ ] **Step 4: Thêm service vào compose**

Sửa `docker-compose.yml`, thêm vào phần `services:` (đặt cạnh `serving`):

```yaml
  agent:
    build:
      context: .
      dockerfile: services/agent/Dockerfile
    image: ml-agent:latest
    # profiles keeps this OFF by default. `docker compose up` does not start
    # it; only `docker compose --profile agent up -d` does. A 16GB machine is
    # already running Airflow, Postgres, MinIO, MLflow and serving.
    profiles: ["agent"]
    depends_on:
      - serving
    environment:
      MINIO_ENDPOINT_INTERNAL: ${MINIO_ENDPOINT_INTERNAL:-http://minio:9000}
      MINIO_ACCESS_KEY: ${MINIO_ACCESS_KEY}
      MINIO_SECRET_KEY: ${MINIO_SECRET_KEY}
      ML_BUCKET: ${ML_BUCKET:-ml-pipeline}
      SERVING_URL: http://serving:8000
      DATASET_VERSION: ${DATASET_VERSION:-v1}
      AGENT_SCENARIO: ${AGENT_SCENARIO:-none}
      AGENT_TASK_TYPE: ${AGENT_TASK_TYPE:-regression}
      AGENT_COUNT: ${AGENT_COUNT:-200}
      AGENT_INTERVAL_SECONDS: ${AGENT_INTERVAL_SECONDS:-300}
    command:
      - sh
      - -c
      - |
        while true; do
          python -m services.agent \
            --scenario "$$AGENT_SCENARIO" \
            --task-type "$$AGENT_TASK_TYPE" \
            --count "$$AGENT_COUNT" \
            --seed $$RANDOM || true
          sleep "$$AGENT_INTERVAL_SECONDS"
        done
```

- [ ] **Step 5: Xác nhận service KHÔNG tự chạy**

```powershell
docker compose config --services
docker compose up -d
docker compose ps
```

Expected: `agent` **có** trong `config --services`, nhưng **không** có trong `docker compose ps` sau khi `up -d`. Đó là điều `profiles` phải làm.

Rồi kiểm chế độ bật:

```powershell
docker compose --profile agent config --services
```

Expected: có `agent`.

- [ ] **Step 6: Commit**

```bash
git add services/agent/__main__.py services/agent/Dockerfile docker-compose.yml
git commit -m "$(cat <<'EOF'
feat: agent CLI, image, and a compose service that stays off

The CLI runs one bounded batch and exits. That boundary is what makes a
scenario measurable: you can say exactly these 500 requests were
price_inflation, which a process running forever cannot say without growing
a control API of its own.

The compose service loops over the same CLI but declares profiles: [agent],
so docker compose up does not start it. The machine is already running
Airflow, Postgres, MinIO, MLflow and serving on 16GB.

The image is FROM ml-base because the agent derives the true label with
ml_common.targets.derive_target. Reimplementing "poor or fair means needs
renovation" in the agent would be a second copy of a rule that must not
drift from the one training uses.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `POST /feedback/{task_type}` trên serving

**Files:**
- Modify: `services/serving/app.py`
- Test: `services/serving/tests/test_app.py`

**Interfaces:**
- Consumes: `storage.Storage`, `storage.ground_truth_key`, `model_registry.ModelRegistry`
- Produces: route `POST /feedback/{task_type}`, hàm `app.write_ground_truth(records: list[dict]) -> str`

- [ ] **Step 1: Viết test fail trước**

Thêm vào `services/serving/tests/test_app.py`:

```python
def test_feedback_writes_one_batch_and_reports_the_key():
    written = []

    def fake_ground_truth(records):
        written.append(records)
        return "ground-truth/house_price_regressor/dt=2026-09-20/part-abc.parquet"

    app = create_app(
        registry=ModelRegistry(loader=lambda name: (ConstantModel(1.0), "1")),
        start_flusher=False,
        write_truth=fake_ground_truth,
    )
    with TestClient(app) as client:
        response = client.post(
            "/feedback/regression",
            json={
                "outcomes": [
                    {"request_id": "r1", "predicted_on": "2026-09-20", "actual": 420000.0},
                    {"request_id": "r2", "predicted_on": "2026-09-20", "actual": 380000.0},
                ]
            },
        )

    assert response.status_code == 200
    assert response.json()["accepted"] == 2
    assert "ground-truth/" in response.json()["key"]
    assert len(written) == 1
    assert len(written[0]) == 2
    assert written[0][0]["model_name"] == "house_price_regressor"


def test_feedback_rejects_an_empty_batch():
    app = create_app(
        registry=ModelRegistry(loader=lambda name: (ConstantModel(1.0), "1")),
        start_flusher=False,
        write_truth=lambda records: "k",
    )
    with TestClient(app) as client:
        response = client.post("/feedback/regression", json={"outcomes": []})

    assert response.status_code == 422


def test_feedback_without_a_champion_is_503():
    # Without a champion there is no model name to file the outcomes under.
    app = create_app(
        registry=ModelRegistry(loader=_loader_that_fails),
        start_flusher=False,
        write_truth=lambda records: "k",
    )
    with TestClient(app) as client:
        response = client.post(
            "/feedback/regression",
            json={"outcomes": [{"request_id": "r1", "predicted_on": "2026-09-20", "actual": 1.0}]},
        )

    assert response.status_code == 503


def test_feedback_rejects_an_outcome_missing_a_field():
    app = create_app(
        registry=ModelRegistry(loader=lambda name: (ConstantModel(1.0), "1")),
        start_flusher=False,
        write_truth=lambda records: "k",
    )
    with TestClient(app) as client:
        response = client.post(
            "/feedback/regression",
            json={"outcomes": [{"request_id": "r1", "actual": 1.0}]},
        )

    assert response.status_code == 422
```

Nếu `_loader_that_fails` và `ConstantModel` chưa có trong file test, thêm:

```python
def _loader_that_fails(name):
    raise RuntimeError("no champion")
```

- [ ] **Step 2: Chạy test cho fail**

```powershell
.venv\Scripts\python.exe -m pytest services/serving/tests/test_app.py -k feedback -v
```

Expected: FAIL — `create_app() got an unexpected keyword argument 'write_truth'`

- [ ] **Step 3: Implement**

Sửa `services/serving/app.py`.

Thêm import và hàm ghi, ngay sau `write_batch`:

```python
def write_ground_truth(records: list[dict]) -> str:
    """Writes one batch of reported outcomes, one file per model and per day.

    Args:
        records: outcomes carrying `model_name` and `predicted_on`. Grouping
            uses `predicted_on`, the day the PREDICTION was served, not the
            day the feedback arrived - that is what puts these rows in the
            same partition as the inference log they will be joined to.

    Returns:
        The key of the last file written, for the response body.

    Raises:
        Exception: anything object storage raises. Unlike the inference log,
            this one surfaces to the caller: the agent is reporting a batch
            it can retry, so a silent drop would lose data nobody knows about.

    Example:
        write_ground_truth([
            {"request_id": "r1", "predicted_on": "2026-09-20",
             "actual": 420000.0, "model_name": "house_price_regressor"},
        ])
        # -> "ground-truth/house_price_regressor/dt=2026-09-20/part-1a2b3c4d.parquet"
    """
    storage = Storage.from_env()
    frame = pd.DataFrame(records)
    key = ""
    for (model_name, day), group in frame.groupby(["model_name", "predicted_on"], sort=False):
        key = ground_truth_key(model_name, date.fromisoformat(day), uuid4().hex[:8])
        storage.write_parquet(group.reset_index(drop=True), key)
    return key
```

Sửa import ở đầu file:

```python
from ml_common.storage import Storage, ground_truth_key, inference_log_key
```

Sửa chữ ký `create_app`, thêm tham số:

```python
def create_app(
    registry: ModelRegistry | None = None,
    buffer: InferenceLogBuffer | None = None,
    flush=write_batch,
    start_flusher: bool = True,
    write_truth=write_ground_truth,
) -> FastAPI:
```

Bổ sung vào docstring của `create_app`, trong mục `Args:`:

```
        write_truth: what writes a feedback batch. Takes a list of outcome
            dicts and returns the key written; tests pass a recorder.
```

Thêm route, sau route `predict`:

```python
    @app.post("/feedback/{task_type}")
    def feedback(
        task_type: Literal["regression", "classification"],
        payload: Annotated[dict, Body()],
    ) -> dict:
        """Records what actually happened to predictions served earlier.

        Args:
            task_type: "regression" or "classification", from the path.
            payload: {"outcomes": [...]}, each outcome carrying `request_id`,
                `predicted_on` (the ISO date the prediction was served) and
                `actual` - a number for regression, a bool for classification.

        Returns:
            `accepted`, how many outcomes were stored, and `key`, the last
            object written.

        Raises:
            HTTPException: 422 when `outcomes` is empty or an entry is missing
                a field. 503 when no champion is loaded, since there is then
                no model name to file the outcomes under.

        Example:
            # POST /feedback/regression
            # {"outcomes": [
            #    {"request_id": "3f0a...", "predicted_on": "2026-09-20",
            #     "actual": 420000.0}]}
            # -> {"accepted": 1, "key": "ground-truth/.../part-1a2b3c4d.parquet"}
            #
            # A whole batch in one call, so one file is written rather than
            # one per house - the same reason the inference log batches.
        """
        outcomes = payload.get("outcomes") or []
        if not outcomes:
            raise HTTPException(status_code=422, detail="outcomes must not be empty")

        loaded = registry.get(task_type)
        if loaded is None:
            raise HTTPException(
                status_code=503,
                detail=f"no champion loaded for {task_type}; nothing to file outcomes under",
            )

        required = ("request_id", "predicted_on", "actual")
        records = []
        for outcome in outcomes:
            missing = [field for field in required if field not in outcome]
            if missing:
                raise HTTPException(
                    status_code=422,
                    detail=f"outcome is missing {', '.join(missing)}",
                )
            records.append({**{f: outcome[f] for f in required}, "model_name": loaded.name})

        key = write_truth(records)
        return {"accepted": len(records), "key": key}
```

- [ ] **Step 4: Chạy test cho pass**

```powershell
.venv\Scripts\python.exe -m pytest services/serving/tests/test_app.py -v
.venv\Scripts\python.exe -m ruff check . --fix
```

Expected: toàn bộ test trong file pass.

- [ ] **Step 5: Ghi `probability` vào inference log**

Không có bước này thì **performance drift của classification không tính được**. Spec mục 4 chốt classification chấm bằng AUC — cùng metric mà cổng promote dùng — nhưng AUC cần xác suất, mà inference log của Plan 3 chỉ ghi `prediction` (bool). `/predict` đã tính sẵn `probability` rồi, chỉ là chưa ghi xuống.

Viết test trước, thêm vào `services/serving/tests/test_app.py`:

```python
def test_inference_log_records_the_probability_for_classification():
    # Performance drift scores classification on AUC, the same metric the
    # promotion gate uses. AUC needs probabilities, so the log must carry them.
    buffered = []

    app = create_app(
        registry=ModelRegistry(loader=lambda name: (ProbaModel(), "1")),
        buffer=InferenceLogBuffer(flush_size=1),
        flush=buffered.append,
        start_flusher=False,
    )
    with TestClient(app) as client:
        client.post("/predict/classification", json={"city": "boston"})

    record = buffered[0][0]
    assert record["probability"] == pytest.approx(0.83)


def test_inference_log_probability_is_none_for_regression():
    buffered = []

    app = create_app(
        registry=ModelRegistry(loader=lambda name: (ConstantModel(450000.0), "1")),
        buffer=InferenceLogBuffer(flush_size=1),
        flush=buffered.append,
        start_flusher=False,
    )
    with TestClient(app) as client:
        client.post("/predict/regression", json={"city": "boston"})

    assert buffered[0][0]["probability"] is None
```

Nếu chưa có `ProbaModel` trong file test thì thêm:

```python
class ProbaModel:
    """A classifier stand-in that also exposes probabilities."""

    def predict(self, frame):
        return [True] * len(frame)

    def predict_proba(self, frame):
        return [[0.17, 0.83]] * len(frame)
```

Chạy cho fail:

```powershell
.venv\Scripts\python.exe -m pytest services/serving/tests/test_app.py -k probability -v
```

Expected: FAIL với `KeyError: 'probability'`.

Rồi sửa `buffer.add(...)` trong route `predict` của `services/serving/app.py`, thêm một khoá:

```python
        buffer.add(
            {
                "request_id": request_id,
                "timestamp": now.isoformat(),
                "day": now.date().isoformat(),
                "raw_input": json.dumps(record, default=str),
                "prediction": prediction,
                # Needed by performance drift: classification is scored on AUC,
                # the same metric the promotion gate uses, and AUC cannot be
                # computed from a bool. None for regression.
                "probability": probability,
                "model_name": loaded.name,
                "model_version": loaded.version,
            }
        )
```

Chạy lại cho pass:

```powershell
.venv\Scripts\python.exe -m pytest services/serving/tests/test_app.py -v
```

- [ ] **Step 6: Kiểm ràng buộc serving vẫn giữ**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_serving.ps1
```

Expected: xanh. Đặc biệt bước "Serving must not import cleaning logic" phải vẫn qua.

- [ ] **Step 7: Commit**

```bash
git add services/serving/app.py services/serving/tests/test_app.py
git commit -m "$(cat <<'EOF'
feat: POST /feedback accepts a batch of real outcomes, and log probability

A whole batch per call, so one parquet file is written rather than one per
house - the same reason the inference log batches, and the same problem it
was avoiding.

Files are partitioned by predicted_on, the day the prediction was served,
not the day the feedback arrived. That is what puts these rows in the same
partition as the inference log they get joined to. The caller supplies that
date because it already knows it; having serving work it out would mean
keeping an index of request ids, which is state it does not otherwise need.

Unlike the inference log, a failed write here surfaces to the caller. The
agent is reporting a batch it can retry, so dropping it silently would lose
data nobody knows is missing.

The inference log now also records probability. Performance drift scores
classification on AUC, the same metric the promotion gate uses, and AUC
cannot be computed from a bool. /predict already worked the probability out
and was throwing it away.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `stages/monitor/main.py` — gọi Evidently

**Files:**
- Create: `stages/monitor/main.py`
- Modify: `stages/monitor/Dockerfile` (không đổi, đã có từ Task 1)

**Interfaces:**
- Consumes: `drift.*` (Task 3, 4), `storage.drift_summary_key`, `storage.drift_latest_key`, `storage.report_key`, `features._numeric_and_categorical_columns`, `metrics.compute_metrics`
- Produces: stage result `{"severity": str, "parts": dict, "n_predictions": int, "n_ground_truth": int, "report_key": str}`

**Trước khi viết:** mở lại kết quả Step 4 của Task 1 để biết chính xác đường dẫn trong dict của Evidently. Đoạn `_drifted_share` dưới đây dò nhiều khoá vì hình dạng dict thay đổi giữa các bản 0.7.x — **thay bằng đường dẫn thật đã thấy**, đừng để nguyên phần dò nếu đã biết chắc.

- [ ] **Step 1: Viết `main.py`**

Tạo `stages/monitor/main.py`:

```python
"""Monitor stage: measure drift for one model and publish the verdict.

This is the only place Evidently is imported, and it is imported inside a
function. ml-base has no Evidently, and a module-level import here would
make every stage that imports ml_common fail.

What it compares:

- Feature drift  - the served records against a sample of the train split
- Prediction drift - predictions served against the champion's predictions
  on that same sample
- Performance drift - accuracy on the rows that have ground truth against
  the metrics the train stage logged

The reference is the train split read back through the fingerprint logged in
MLflow, not the baseline profile. Evidently takes DataFrames; profile.json is
a summary and cannot be fed to it. See section 2.1 of the design doc.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime

import mlflow
import mlflow.sklearn
from mlflow import MlflowClient

from ml_common import drift, schema
from ml_common.features import _numeric_and_categorical_columns
from ml_common.metrics import compute_metrics
from ml_common.stageio import emit_result
from ml_common.storage import (
    Storage,
    drift_latest_key,
    drift_summary_key,
    processed_key,
    report_key,
)

CHAMPION_ALIAS = "champion"
DEFAULT_WINDOW_HOURS = 24
DEFAULT_REFERENCE_ROWS = 10_000
REFERENCE_SEED = 42


def load_champion_context(model_name: str) -> tuple[object, str, str, str]:
    """Loads the champion together with everything needed to judge it.

    Args:
        model_name: the registered model to look under.

    Returns:
        A tuple of (fitted Pipeline, version string, run_id, fingerprint).
        The fingerprint comes from the run's logged params, which is how the
        train split that produced this model is found again - the same path
        scripts/smoke_round_trip.py uses. The run_id is returned alongside so
        the training metrics can be read without asking MLflow for the same
        version a second time.

    Raises:
        Exception: when no champion exists, or when the run has no
            `fingerprint` param. Both mean there is nothing to compare
            against, and guessing a fingerprint would silently measure drift
            against the wrong data.

    Example:
        model, version, run_id, fingerprint = load_champion_context("house_price_regressor")
        # -> (Pipeline(...), "3", "a1b2c3d4", "3f0a9c1d5e2b7a48")
    """
    client = MlflowClient()
    version = client.get_model_version_by_alias(model_name, CHAMPION_ALIAS)
    fingerprint = client.get_run(version.run_id).data.params["fingerprint"]
    model = mlflow.sklearn.load_model(f"models:/{model_name}@{CHAMPION_ALIAS}")
    return model, str(version.version), version.run_id, fingerprint


def train_metrics_of(run_id: str, task_type: str) -> dict:
    """Reads the metrics the train stage logged for this model version.

    Args:
        run_id: the MLflow run that produced the champion.
        task_type: "regression" or "classification".

    Returns:
        The metrics under their plain names, with the `train_` prefix the
        train stage added stripped back off, e.g. {"rmse": 41203.7, ...}.

    Example:
        train_metrics_of("a1b2c3", "regression")
        # -> {"rmse": 41203.7, "mae": 28104.2, "r2": 0.947}
    """
    logged = MlflowClient().get_run(run_id).data.metrics
    return {
        name[len("train_") :]: value
        for name, value in logged.items()
        if name.startswith("train_")
    }


def _drifted_share(summary: dict) -> float:
    """Pulls the share of drifted columns out of Evidently's result dict.

    Args:
        summary: what `results.dict()` returned.

    Returns:
        The fraction of columns flagged as drifted, 0.0 to 1.0.

    Raises:
        KeyError: when no known key holds the share. Better to fail loudly
            than to report 0.0 and put a green badge on an unread report.

    Example:
        _drifted_share(results.dict())   # -> 0.42
    """
    for metric in summary.get("metrics", []):
        value = metric.get("value")
        if isinstance(value, dict) and "share_of_drifted_columns" in value:
            return float(value["share_of_drifted_columns"])
        if metric.get("metric_id", "").startswith("DriftedColumnsCount") and isinstance(
            value, dict
        ):
            return float(value.get("share", 0.0))
    raise KeyError(
        "no drifted-column share in the Evidently result; "
        f"top-level keys were {list(summary)}"
    )


def run_drift_report(reference, current, numeric: list[str], categorical: list[str]):
    """Runs Evidently over two frames and returns the report object.

    Args:
        reference: the train-split sample.
        current: the records actually served.
        numeric: numeric column names to compare.
        categorical: categorical column names to compare.

    Returns:
        Evidently's result object, which can `save_html` and `dict`.

    Example:
        results = run_drift_report(ref, cur, numeric, categorical)
        results.save_html("/tmp/evidently.html")

        # NOTE the argument order below: current comes FIRST. Swapping them
        # still runs and still produces a report - it just measures whether
        # the training data drifted away from production, which is backwards
        # and which nothing will warn you about.
    """
    from evidently import DataDefinition, Dataset, Report
    from evidently.presets import DataDriftPreset

    definition = DataDefinition(numerical_columns=numeric, categorical_columns=categorical)
    report = Report([DataDriftPreset()])
    return report.run(
        Dataset.from_pandas(current, data_definition=definition),
        Dataset.from_pandas(reference, data_definition=definition),
    )


def main() -> int:
    """Measures all three drift types for one model and publishes the verdict.

    Args:
        None. Reads TASK_TYPE, MODEL_NAME, MLFLOW_TRACKING_URI, optional
        MONITOR_WINDOW_HOURS (default 24), MONITOR_REFERENCE_ROWS (default
        10000) and MONITOR_RUN_ID, plus the MinIO variables Storage.from_env
        needs.

    Returns:
        0 even when drift is high. A drifting model is a finding to report,
        not a task failure - the same reasoning that makes evaluate exit 0 on
        a blocked model. Returns 1 only when there was no traffic at all,
        since then nothing could be measured.

    Raises:
        Exception: when no champion exists, or the train split for its
            fingerprint is gone from storage. Both mean the comparison cannot
            be made, and a report built on a guess would be worse than none.

    Example:
        # TASK_TYPE=regression MODEL_NAME=house_price_regressor python main.py
        # -> XCOM_RESULT {"severity": "high", "parts": {...}, ...}
    """
    task_type = os.environ["TASK_TYPE"]
    model_name = os.environ["MODEL_NAME"]
    window_hours = int(os.environ.get("MONITOR_WINDOW_HOURS", DEFAULT_WINDOW_HOURS))
    reference_rows = int(os.environ.get("MONITOR_REFERENCE_ROWS", DEFAULT_REFERENCE_ROWS))
    run_id = os.environ.get("MONITOR_RUN_ID", datetime.now(UTC).strftime("%Y%m%dT%H%M%S"))

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    storage = Storage.from_env()
    now = datetime.now(UTC)

    predictions = drift.load_predictions(storage, model_name, now, window_hours)
    if len(predictions) == 0:
        print(f"no traffic for {model_name} in the last {window_hours}h", file=sys.stderr)
        emit_result(
            {
                "severity": drift.INSUFFICIENT,
                "parts": {},
                "n_predictions": 0,
                "n_ground_truth": 0,
                "report_key": None,
            }
        )
        return 1

    model, version, champion_run_id, fingerprint = load_champion_context(model_name)
    print(f"champion v{version}, fingerprint {fingerprint}", file=sys.stderr)

    train_df = storage.read_parquet(processed_key(fingerprint, task_type, "train"))
    target = schema.target_column(task_type)
    reference = train_df.drop(columns=[target])
    if len(reference) > reference_rows:
        reference = reference.sample(n=reference_rows, random_state=REFERENCE_SEED)

    current = drift.decode_raw_inputs(predictions)
    numeric, categorical = _numeric_and_categorical_columns(task_type)

    # Feature drift. Only compare columns both sides actually have.
    shared_numeric = [c for c in numeric if c in current.columns and c in reference.columns]
    shared_categorical = [
        c for c in categorical if c in current.columns and c in reference.columns
    ]
    feature_report = run_drift_report(reference, current, shared_numeric, shared_categorical)
    feature_part = drift.feature_severity(_drifted_share(feature_report.dict()))

    # Prediction drift. The champion has to be run over the reference here:
    # training never logged the distribution of its own output.
    reference_predictions = model.predict(reference)
    prediction_report = run_drift_report(
        reference.assign(prediction=reference_predictions)[["prediction"]],
        predictions[["prediction"]],
        ["prediction"] if task_type == "regression" else [],
        [] if task_type == "regression" else ["prediction"],
    )
    prediction_part = drift.prediction_severity(_drifted_share(prediction_report.dict()) > 0)

    # Performance drift, when there is anything to measure it on.
    outcomes = drift.load_outcomes(storage, model_name, now, window_hours)
    joined = drift.join_outcomes(predictions, outcomes)
    if len(joined) >= drift.MIN_GROUND_TRUTH:
        # Classification is scored on AUC, so it needs the probability serving
        # logged alongside the label. Regression has no probability at all.
        y_proba = None
        if task_type == "classification" and "probability" in joined.columns:
            y_proba = joined["probability"]
        current_metrics = compute_metrics(
            task_type, joined["actual"], joined["prediction"], y_proba
        )
        performance_part = drift.performance_severity(
            task_type,
            current_metrics,
            train_metrics_of(champion_run_id, task_type),
            len(joined),
        )
    else:
        current_metrics = {}
        performance_part = drift.INSUFFICIENT

    parts = {
        "feature": feature_part,
        "prediction": prediction_part,
        "performance": performance_part,
    }
    severity = drift.overall_severity(parts)
    print(f"severity={severity} parts={parts}", file=sys.stderr)

    html_key = report_key(model_name, run_id, "html")
    feature_report.save_html("/tmp/evidently.html")
    with open("/tmp/evidently.html", "rb") as handle:
        storage.write_bytes(handle.read(), html_key, "text/html")

    summary = {
        "model_name": model_name,
        "model_version": version,
        "task_type": task_type,
        "run_id": run_id,
        "computed_at": now.isoformat(),
        "window_hours": window_hours,
        "severity": severity,
        "parts": parts,
        "n_predictions": int(len(predictions)),
        "n_ground_truth": int(len(joined)),
        "current_metrics": current_metrics,
        "report_key": html_key,
    }
    storage.write_json(summary, drift_summary_key(model_name, run_id))
    storage.write_json(summary, drift_latest_key(model_name))
    storage.write_json(feature_report.dict(), report_key(model_name, run_id, "json"))

    emit_result(
        {
            "severity": severity,
            "parts": parts,
            "n_predictions": int(len(predictions)),
            "n_ground_truth": int(len(joined)),
            "report_key": html_key,
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Build lại image**

```powershell
docker build -f stages/monitor/Dockerfile -t ml-monitor:latest .
```

- [ ] **Step 3: Kiểm import không kéo Evidently vào `ml-base`**

```powershell
docker run --rm ml-base:latest python -c "from ml_common import drift; print('drift imports without evidently:', drift.MIN_GROUND_TRUTH)"
```

Expected: in ra `drift imports without evidently: 50`. Nếu nó `ModuleNotFoundError: evidently` thì có import ở mức module — sửa lại.

- [ ] **Step 4: Chạy thử stage thật**

Cần có champion và có traffic. Bắn traffic trước:

```powershell
docker compose --profile agent run --rm agent python -m services.agent --scenario none --task-type regression --count 200
```

Rồi chạy monitor:

```powershell
docker run --rm --network mlops_default `
  -e TASK_TYPE=regression -e MODEL_NAME=house_price_regressor `
  -e MLFLOW_TRACKING_URI=http://mlflow:5000 `
  -e MINIO_ENDPOINT_INTERNAL=http://minio:9000 `
  -e MINIO_ACCESS_KEY=minioadmin -e MINIO_SECRET_KEY=minioadmin `
  -e MLFLOW_S3_ENDPOINT_URL=http://minio:9000 `
  -e AWS_ACCESS_KEY_ID=minioadmin -e AWS_SECRET_ACCESS_KEY=minioadmin `
  ml-monitor:latest
```

Expected: dòng cuối là `XCOM_RESULT {...}` với `"severity"` và `"parts"`. Với `scenario=none` thì feature phải ra `ok`; nếu không, **ghi lại con số `share` thật** — Task 11 sẽ dùng để hiệu chỉnh ngưỡng.

- [ ] **Step 5: Commit**

```bash
git add stages/monitor/main.py
git commit -m "$(cat <<'EOF'
feat: monitor stage measuring all three drift types

Evidently is imported inside a function, not at module level: ml-base has no
Evidently, and a module-level import would break every stage that imports
ml_common.

The reference is the train split read back through the fingerprint logged in
MLflow, because Evidently takes DataFrames and profile.json is a summary.
Prediction drift needs the champion run over that reference at monitoring
time, since training never logged the distribution of its own output.

Exits 0 even when drift is high. A drifting model is a finding to report, the
same way a blocked model is at the evaluate gate. It exits 1 only when there
was no traffic at all, because then nothing could be measured.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `monitoring_dag`

**Files:**
- Create: `dags/monitoring_dag.py`

**Interfaces:**
- Consumes: image `ml-monitor:latest`, `stage_result` (chép lại, DAG không import được `ml_common`)
- Produces: DAG `monitoring_dag` với 2 task song song

**Lệch khỏi spec, có chủ ý và phải ghi ra:** §6.2 vẽ ba task `collect_window` → `run_evidently` → `publish_report`. Plan này gộp thành **một task mỗi `task_type`**. Lý do: XCom chỉ chuyển được giá trị nhỏ, nên ba task riêng sẽ phải **đọc lại cửa sổ dữ liệu ba lần** từ MinIO, hoặc ghi trạng thái trung gian chỉ để chuyền tay nhau. Đổi lại, hai model được monitor song song — thứ bản ba-task không có.

- [ ] **Step 1: Viết DAG**

Tạo `dags/monitoring_dag.py`:

```python
"""monitoring_dag - the only DAG that runs on a schedule.

It measures drift for each model independently, so a missing classification
champion never blocks the regression verdict.

Created paused on purpose. The schedule stays hourly as the design says, but
a 16GB dev box is already running Airflow, Postgres, MinIO, MLflow and
serving; a job that quietly fires every hour and pulls Evidently plus 10,000
reference rows is the kind of thing people forget about and then wonder why
the machine crawls. Drop the flag when this moves to MWAA.

One container per model rather than the three tasks section 6.2 sketches.
XCom carries only small values, so collect/report/publish as separate tasks
would each have to re-read the window from object storage.
"""

from __future__ import annotations

import json
import os

import pendulum
from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator

DOCKER_URL = "unix://var/run/docker.sock"
NETWORK = "mlops_default"

MODEL_NAME_BY_TASK_TYPE = {
    "regression": "house_price_regressor",
    "classification": "house_needs_renovation_classifier",
}

_MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT_INTERNAL", "http://minio:9000")
_MINIO_KEY = os.environ.get("MINIO_ACCESS_KEY", "")
_MINIO_SECRET = os.environ.get("MINIO_SECRET_KEY", "")

BASE_ENV = {
    "MINIO_ENDPOINT_INTERNAL": _MINIO_ENDPOINT,
    "MINIO_ACCESS_KEY": _MINIO_KEY,
    "MINIO_SECRET_KEY": _MINIO_SECRET,
    "ML_BUCKET": os.environ.get("ML_BUCKET", "ml-pipeline"),
    "MLFLOW_TRACKING_URI": os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"),
    "MLFLOW_S3_ENDPOINT_URL": _MINIO_ENDPOINT,
    "AWS_ACCESS_KEY_ID": _MINIO_KEY,
    "AWS_SECRET_ACCESS_KEY": _MINIO_SECRET,
    "MONITOR_WINDOW_HOURS": os.environ.get("MONITOR_WINDOW_HOURS", "24"),
}

# Kept in sync with ml_common.stageio.RESULT_PREFIX by a test in common/tests.
# The DAG runs in the Airflow image, which has no ml_common installed.
RESULT_PREFIX = "XCOM_RESULT "


def stage_result(lines: list[str]) -> dict:
    """Finds the line a stage marked as its result, wherever it landed.

    Args:
        lines: every log line the container produced.

    Returns:
        The payload the stage emitted, decoded from JSON.

    Raises:
        ValueError: when no marked line is present.

    Example:
        stage_result(ti.xcom_pull(task_ids="monitor_regression"))["severity"]
        # -> "high"
    """
    for line in reversed(lines):
        if isinstance(line, str) and line.strip().startswith(RESULT_PREFIX):
            return json.loads(line.strip()[len(RESULT_PREFIX) :])
    raise ValueError(f"no {RESULT_PREFIX.strip()} line in stage output: {lines!r}")


with DAG(
    dag_id="monitoring_dag",
    schedule="@hourly",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    is_paused_upon_creation=True,
    tags=["ml", "monitoring"],
    user_defined_filters={"stage_result": stage_result},
) as dag:
    for task_type, model_name in MODEL_NAME_BY_TASK_TYPE.items():
        DockerOperator(
            task_id=f"monitor_{task_type}",
            image="ml-monitor:latest",
            docker_url=DOCKER_URL,
            network_mode=NETWORK,
            environment={
                **BASE_ENV,
                "TASK_TYPE": task_type,
                "MODEL_NAME": model_name,
                "MONITOR_RUN_ID": "{{ run_id | replace(':', '-') | replace('+', '-') }}",
            },
            auto_remove="success",
            mount_tmp_dir=False,
            do_xcom_push=True,
            xcom_all=True,
            # A model with no champion yet must not fail the whole run.
            trigger_rule="all_done",
        )
```

- [ ] **Step 2: Kiểm DAG parse được**

```powershell
docker compose exec airflow-scheduler airflow dags list-import-errors
docker compose exec airflow-scheduler airflow dags list | Select-String monitoring
```

Expected: không có import error; `monitoring_dag` xuất hiện và ở trạng thái `True` cho cột paused.

- [ ] **Step 3: Chạy tay một lần**

```powershell
docker compose exec airflow-scheduler airflow dags unpause monitoring_dag
docker compose exec airflow-scheduler airflow dags trigger monitoring_dag
```

Đợi rồi xem ở http://localhost:8080. Expected: `monitor_regression` xanh và có `XCOM_RESULT`; `monitor_classification` có thể fail nếu chưa có champion — đó là lý do có `trigger_rule="all_done"`.

Pause lại sau khi xong:

```powershell
docker compose exec airflow-scheduler airflow dags pause monitoring_dag
```

- [ ] **Step 4: Commit**

```bash
git add dags/monitoring_dag.py
git commit -m "$(cat <<'EOF'
feat: monitoring_dag, one container per model

Created paused. The hourly schedule stays as designed, but a 16GB dev box
already runs Airflow, Postgres, MinIO, MLflow and serving, and a job that
quietly fires every hour pulling Evidently and 10,000 reference rows is the
kind of thing people forget about and then blame the machine for.

One task per model rather than the three tasks section 6.2 sketches. XCom
carries only small values, so collect, report and publish as separate tasks
would each have to re-read the window from object storage. Splitting by model
instead buys something real: the two are measured in parallel, and a missing
classification champion does not block the regression verdict.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Chạy thật 4 kịch bản và hiệu chỉnh ngưỡng

Đây là task chứng minh plan này có giá trị. Ngưỡng ở Task 4 là **số khởi điểm chưa ai đo**; task này đo rồi chỉnh.

**Files:**
- Create: `scripts/verify_monitoring.ps1`
- Modify: `common/ml_common/drift.py` (chỉ nếu số đo đòi)

**Interfaces:**
- Consumes: mọi thứ từ Task 1–10

- [ ] **Step 1: Đảm bảo có champion cho regression**

```powershell
docker compose exec airflow-scheduler airflow dags trigger ml_pipeline -c '{\"task_type\": \"regression\"}'
```

Đợi DAG xanh tới `register`. Kiểm: http://localhost:5000 → Models → `house_price_regressor` có alias `champion`.

- [ ] **Step 2: Chạy `scenario=none` và ghi lại số thật**

```powershell
docker compose --profile agent run --rm agent python -m services.agent --scenario none --task-type regression --count 500
```

Rồi chạy monitor (lệnh đầy đủ ở Task 9 Step 4) và **ghi lại `share` thật của feature drift**.

Expected: `severity` ra `ok`.

**Nếu `none` đã ra `warning` hoặc `high`** thì ngưỡng 0.3 quá sát — đó chính là thứ task này tồn tại để phát hiện. Nâng `FEATURE_WARNING_SHARE` lên trên con số đo được một khoảng rõ ràng, ghi con số thật vào comment, và ghi lý do vào commit.

- [ ] **Step 3: Chạy `price_inflation`**

```powershell
docker compose --profile agent run --rm agent python -m services.agent --scenario price_inflation --task-type regression --count 500
```

Chạy monitor. Expected: `severity` ra `high`, `parts.performance` ra `high` (vì feedback đã gửi cùng lúc, đủ 500 > 50 dòng).

- [ ] **Step 4: Chạy `market_rally` — bài kiểm tra khó nhất**

```powershell
docker compose --profile agent run --rm agent python -m services.agent --scenario market_rally --task-type regression --count 500
```

Chạy monitor. Expected: `parts.feature` kêu (`warning` hoặc `high`), nhưng **`parts.performance` ra `ok`**.

Đây là dòng dễ hỏng nhất trong cả plan. Nếu `performance` cũng ra `high` thì `adjust_truth` không có tác dụng — kiểm lại Task 5 rằng `market_rally` thật sự nhân giá bán, và kiểm `build_requests` truyền đúng `task_type`.

- [ ] **Step 5: Chạy `new_segment` — serving không được sập**

```powershell
docker compose --profile agent run --rm agent python -m services.agent --scenario new_segment --task-type regression --count 200
```

Expected: **không có lỗi HTTP 500 nào**. `handle_unknown="infrequent_if_exist"` từ Plan 2 phải đỡ được giá trị `property_type` chưa từng thấy.

- [ ] **Step 6: Kiểm `insufficient_data`**

```powershell
docker compose --profile agent run --rm agent python -m services.agent --scenario none --task-type regression --count 100 --feedback-ratio 0
```

Chạy monitor với cửa sổ ngắn để chỉ thấy lô này:

```powershell
# them -e MONITOR_WINDOW_HOURS=1 vao lenh o Task 9 Step 4
```

Expected: `parts.performance` ra `insufficient_data`, **không phải `ok`**.

- [ ] **Step 7: Viết script xác nhận**

Tạo `scripts/verify_monitoring.ps1`:

```powershell
# Xac nhan Plan 4. Chay tu goc repo, voi stack dang chay va da co champion.
$ErrorActionPreference = "Stop"

Write-Host "== 1/5 Test o may dev ==" -ForegroundColor Cyan
.venv\Scripts\python.exe -m pytest common/ services/ -q
if ($LASTEXITCODE -ne 0) { throw "test that bai" }

Write-Host "== 2/5 Ruff ==" -ForegroundColor Cyan
.venv\Scripts\python.exe -m ruff check .
if ($LASTEXITCODE -ne 0) { throw "ruff that bai" }

Write-Host "== 3/5 drift.py khong keo Evidently vao ml-base ==" -ForegroundColor Cyan
docker run --rm ml-base:latest python -c "from ml_common import drift; print(drift.MIN_GROUND_TRUTH)"
if ($LASTEXITCODE -ne 0) { throw "drift.py import Evidently o muc module - phai import lazy" }

Write-Host "== 4/5 Agent service phai TAT mac dinh ==" -ForegroundColor Cyan
$running = docker compose ps --services
if ($running -contains "agent") { throw "service agent dang chay - profiles khong co tac dung" }

Write-Host "== 5/5 Image ml-monitor ton tai ==" -ForegroundColor Cyan
docker image inspect ml-monitor:latest | Out-Null
if ($LASTEXITCODE -ne 0) { throw "chua build ml-monitor" }

Write-Host "`nPlan 4 xanh." -ForegroundColor Green
Write-Host "Bang kich ban phai kiem bang tay - xem Task 11 cua plan." -ForegroundColor Yellow
```

- [ ] **Step 8: Chạy script**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_monitoring.ps1
```

Expected: xanh cả 5 bước.

- [ ] **Step 9: Commit**

```bash
git add scripts/verify_monitoring.ps1 common/ml_common/drift.py
git commit -m "$(cat <<'EOF'
test: calibrate the drift thresholds against real runs

Ran all four scenarios end to end. Recorded numbers in the comments beside
the constants, replacing the guesses.

<FILL IN: what scenario=none actually scored, and whether the thresholds had
to move. If they did, say what they moved to and why.>

The market_rally run is the one worth keeping: feature drift fires while
performance stays ok, which is the evidence that separating the three drift
types earns its keep. Without it the system would only ever teach "drift
means retrain".

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Cập nhật tài liệu

**Files:**
- Modify: `CLAUDE.md`, `mlops-pipeline-design.md`, `docs/superpowers/specs/2026-09-20-plan4-monitoring-design.md`

- [ ] **Step 1: Cập nhật `CLAUDE.md`**

Trong mục "Lệnh", thêm vào khối build:

```powershell
docker build -f services/agent/Dockerfile -t ml-agent:latest .
```

Thêm vào danh sách verify script:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_monitoring.ps1
```

Trong mục "Trạng thái", thêm dòng vào bảng:

```markdown
| 4/5 | Monitoring — agent 5 kịch bản, `/feedback`, Evidently 3 loại drift, `monitoring_dag` | `scripts\verify_monitoring.ps1` |
```

Và sửa câu cuối thành: `Một plan còn lại: **5/5 dashboard**.`

- [ ] **Step 2: Vá ngược 5 chỗ vào `mlops-pipeline-design.md`**

Theo đúng bảng ở mục 9 của spec Plan 4:

1. §7.8 — ghi rõ baseline có **hai dạng**: `profile.json` cho dashboard, và tập train đọc lại cho Evidently.
2. §7.7 — thêm `market_rally` vào bảng scenario.
3. §6.2 — thêm ghi chú DAG tạo ra ở trạng thái paused, và một task mỗi model thay vì ba task.
4. §7.8 — thêm `insufficient_data` vào danh sách mức độ.
5. §7.7 — ghi rõ agent gửi feedback theo lệnh, mang theo `predicted_on`.

- [ ] **Step 3: Thêm dòng lệch thứ 6 vào spec Plan 4**

Mục 9 của spec hiện có 5 dòng. Thêm dòng về `monitoring_dag` gộp task (xem Task 10):

```markdown
| §6.2 | 3 task `collect_window`/`run_evidently`/`publish_report` | 1 task mỗi `task_type`, chạy song song | XCom chỉ chuyền được giá trị nhỏ; 3 task sẽ phải đọc lại cửa sổ 3 lần |
```

Và sửa "Cả năm dòng" thành "Cả sáu dòng".

Sửa luôn mục 6 của spec: dòng `services/serving/app.py` hiện ghi "Thêm route `POST /feedback/{task_type}`", phải thành "Thêm route `POST /feedback/{task_type}`; ghi thêm `probability` vào inference log". Lý do ghi kèm: performance drift của classification chấm bằng AUC, mà AUC không tính được từ một bool.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md mlops-pipeline-design.md docs/superpowers/specs/2026-09-20-plan4-monitoring-design.md
git commit -m "$(cat <<'EOF'
docs: record what plan 4 changed about the design

Patches the five divergences the spec listed back into the design doc, now
that the real thresholds and window sizes are known, plus a sixth found
while writing the DAG: monitoring runs one container per model rather than
the three tasks section 6.2 sketched, because XCom carries only small values
and three tasks would each re-read the window.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Definition of Done

1. `.venv\Scripts\python.exe -m pytest common/ services/ -q` xanh.
2. Test trong container xanh: `docker run --rm ml-base:latest sh -c "pip install --quiet 'pytest>=8.0' 'moto[s3]>=5.0' && python -m pytest /app/common/tests -q"`
3. `.venv\Scripts\python.exe -m ruff check .` sạch.
4. `ml-monitor:latest` và `ml-agent:latest` build được.
5. `docker run --rm ml-base:latest python -c "from ml_common import drift"` chạy được — Evidently không rò vào `ml-base`.
6. `docker compose up -d` **không** khởi động `agent`.
7. `monitoring_dag` parse được và tạo ra ở trạng thái paused.
8. **Bảng kịch bản đúng hết:**

| Chạy | Feature | Prediction | Performance | Tổng hợp |
| --- | --- | --- | --- | --- |
| `none` | `ok` | `ok` | `ok` | **`ok`** |
| `price_inflation` | `high` | `high` | `high` | **`high`** |
| `market_rally` | `warning`/`high` | `warning`/`high` | **`ok`** | warning/high |
| `new_segment` | drift ở `property_type` | — | — | serving **không sập** |

9. Chạy khi chưa có ground truth ra `insufficient_data`, không ra `ok`.
10. `scripts\verify_monitoring.ps1` xanh.

Điểm 8 là điều kiện thật. Một hệ thống drift luôn báo `high` vô dụng ngang một hệ thống luôn báo `ok`.

---

## Những gì Plan 4 cố tình KHÔNG làm

- **Auto-retrain.** §6.2 chốt: cảnh báo, người quyết định. Nút bấm thuộc Plan 5.
- **`services/api/` và dashboard.** Plan 5.
- **Sửa 6 stage của Plan 2.** Quyết định 2.1 của spec chọn đọc lại tập train chính vì nó không bắt sửa `register`.
- **Text/LLM drift của Evidently.** Dataset này thuần bảng.
- **Cảnh báo qua email/Slack.** Chưa có nơi để gửi tới.

---

## Self-review

**Spec coverage** — đối chiếu từng mục của spec:

| Mục spec | Task |
| --- | --- |
| 2.1 baseline đọc lại train split | Task 9 (`load_champion_context`) |
| 2.2 Evidently không vào `ml-base` | Task 1 (Dockerfile), Task 9 (lazy import), Task 11 Step 7 (script kiểm) |
| 2.3 API Evidently 0.7 | Task 1 (xác minh), Task 9 (`run_drift_report`) |
| 2.4 agent lõi + CLI + profile | Task 6, Task 7 |
| 2.5 `price_inflation` vs `market_rally` | Task 5, Task 11 Step 3–4 |
| 2.6 `insufficient_data` | Task 4, Task 11 Step 6 |
| 2.7 DAG paused | Task 10 |
| 2.8 `/feedback` theo lô, ngày do agent cấp | Task 6, Task 8 |
| 3 API endpoint | Task 8 |
| 4 ba loại drift + ngưỡng | Task 4, Task 9, Task 11 |
| 5 cấu trúc thư mục + 2 hàm key | Task 2, Task 5–10 |
| 6 thay đổi code đã có | Task 2, 7, 8; `register` không đụng ✔ |
| 7 test | Task 3–6, 8, 11 |
| 8 Definition of Done | Task 11 |
| 9 chỗ lệch spec | Task 12 |

Không có mục nào thiếu task.

**Placeholder scan** — hai chỗ `<FILL IN...>` trong commit message của Task 1 và Task 11 là **cố ý**: chúng chờ số đo thật, không thể biết trước khi chạy. Mọi chỗ khác đều có code thật.

**Type consistency** — đã đối chiếu:

- `drift.load_predictions/load_outcomes` nhận `(storage, model_name, end, window_hours)` ở cả Task 3 lẫn Task 9 ✔
- `scenarios.apply_scenario(record, scenario)` và `adjust_truth(actual, scenario, task_type)` khớp giữa Task 5 và Task 6 ✔
- `runner.build_requests(pool, scenario, task_type, count, seed)` khớp Task 6 và Task 7 ✔
- `create_app(..., write_truth=...)` khớp Task 8 ✔
- `drift.INSUFFICIENT` dùng ở Task 4, 9, 10 cùng một tên ✔
- `load_champion_context` trả 4 giá trị ở Task 9, và cả 4 đều được dùng ✔

**Ba lỗi self-review bắt được và đã sửa trong plan này:**

1. **Classification không tính được AUC.** Spec mục 4 chốt performance drift của classification chấm bằng AUC — cùng metric cổng promote dùng — nhưng inference log của Plan 3 chỉ ghi `prediction` (bool). Không có xác suất thì `compute_metrics` không trả khoá `auc`, và `performance_severity` sẽ nổ `KeyError`. Đã thêm Task 8 Step 5: ghi `probability` xuống log. `/predict` vốn đã tính sẵn rồi vứt đi.
2. **Gọi MLflow thừa một lần.** `load_champion_context` không trả `run_id`, nên phần performance phải hỏi lại MLflow đúng version đó lần nữa. Đã cho nó trả `run_id`.
3. **Một import sai** trong bản nháp Task 6 (`adjust_scenario_error` không tồn tại). Đã sửa.

Lỗi 1 là lỗi thiết kế chứ không phải lỗi gõ: nó nằm ở chỗ nối giữa spec Plan 4 và code Plan 3, và chỉ lộ ra khi đối chiếu hai bên. Nếu không bắt ở đây thì nó sẽ nổ lúc chạy Task 11 với `classification`.
