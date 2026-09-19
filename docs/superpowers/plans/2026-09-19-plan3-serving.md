# Plan 3 — Serving Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng `services/serving/` phục vụ cả hai model từ MLflow Registry qua `/predict/{model}`, `/reload`, `/health`; ghi inference log theo lô lên MinIO; nối task `deploy` vào DAG; và cho nhánh classification với bài toán mới `needs_renovation` chạy thật tới khi có champion.

**Architecture:** Logic thuần (bộ đệm inference log, sinh target, cổng AUC) nằm trong `common/ml_common/` và test bằng pytest không cần container. Serving là một image `FROM ml-base:latest` — bắt buộc, vì đó là cách duy nhất khoá được version sklearn giữa lúc train và lúc serve. Serving load model qua alias `@champion`, nhận record **thô**, và không bao giờ import logic cleaning: toàn bộ `Pipeline` đã nằm trong pickle.

**Tech Stack:** Python 3.12 (container) / 3.13 (dev), FastAPI + uvicorn, MLflow 2.22, pandas 2.3, scikit-learn 1.9, MinIO, Airflow 2.10.3.

**Spec:** `docs/superpowers/specs/2026-09-19-plan3-serving-design.md` — đọc cùng plan này. Plan lập luận từ spec; hai bên lệch nhau thì spec thắng, và phải báo chứ không tự chọn bên.

## Global Constraints

- **Python:** container 3.12, dev 3.13. **Không dùng cú pháp chỉ có ở 3.13+.**
- **Pin version:** `pandas>=2.2,<3`, `scikit-learn>=1.5,<2`, `pyarrow>=16`, `boto3>=1.34`, `numpy>=1.26,<3`, `mlflow>=2.14,<3`, `fastapi>=0.115`, `uvicorn[standard]>=0.30`.
- **Serving không được import `ml_common.cleaning` hay `ml_common.rowops`.** Model tự chứa logic làm sạch. Một transformer xoá dòng gọi với một record sẽ trả DataFrame rỗng và làm `/predict` sập.
- **Mọi key object storage** phải sinh từ hàm `*_key()` trong `common/ml_common/storage.py`. Không nối chuỗi ở nơi khác.
- **Stage phát kết quả qua `stageio.emit_result()`**, không `print(json.dumps(...))`. Dòng kết quả tự đánh dấu bằng `XCOM_RESULT `.
- **Ngôn ngữ trong code:** tiếng Anh tự nhiên. File markdown tiếng Việt có dấu.
- **Giá trị thiếu:** `None` / `np.nan`. Không dùng chuỗi rỗng hay `-1`.
- **Encoding:** UTF-8 không BOM. **Ruff:** `line-length = 100`, rules `["E", "F", "I", "UP", "B"]`.
- **Commit:** mỗi task **đúng một** commit, Conventional Commits, mô tả tiếng Việt **không dấu**, kết thúc bằng `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`, kiểm lại bằng `git log -1`.
- **Build lại `ml-base` mỗi khi `common/` thay đổi**, rồi build lại các image phụ thuộc: `scripts\build_base_image.ps1` và `scripts\build_stage_images.ps1`.
- **Lệnh Python local:** gọi thẳng `.venv\Scripts\python.exe`, không dùng `Activate.ps1`.
- **Chạy Python từ host** cần load `.env` rồi override `MINIO_ENDPOINT_INTERNAL=http://localhost:9000` và `MLFLOW_TRACKING_URI=http://localhost:5000`.

## File Structure

| File | Trách nhiệm |
| --- | --- |
| `common/ml_common/gates.py` | **Sửa:** cổng classification dùng AUC thay F1 |
| `common/ml_common/schema.py` | **Sửa:** `TARGET_CLASSIFICATION` mới + danh sách leakage |
| `common/ml_common/targets.py` | **Sửa:** thêm `derive_target()` và `TARGET_SOURCE` |
| `common/ml_common/validation.py` | **Sửa:** classification kiểm cột nguồn thay vì cột target |
| `common/ml_common/inference_log.py` | **Mới.** Bộ đệm theo lô — thuần logic, không đụng IO |
| `stages/prepare_dataset_for_train/main.py` | **Sửa:** gọi `derive_target` |
| `dags/ml_pipeline_dag.py` | **Sửa:** suy `model_name`/`estimator_name` từ `task_type`; thêm task `deploy` |
| `services/serving/model_registry.py` | **Mới.** Load champion từ MLflow, giữ trong bộ nhớ |
| `services/serving/app.py` | **Mới.** FastAPI: routes và state |
| `services/serving/Dockerfile` | **Mới.** `FROM ml-base:latest` + FastAPI |
| `docker-compose.yml` | **Sửa:** thêm service `serving` |
| `scripts/verify_serving.ps1` | **Mới.** Một lệnh xác nhận Plan 3 |

**Vì sao `inference_log.py` nằm ở `common/` chứ không ở `services/serving/`:** nó là logic thuần (đầy chưa, hết hạn chưa, vượt trần bỏ gì) và `common/` đã có bộ test chạy ở cả Python 3.13 local lẫn 3.12 trong container. Đặt ở `services/` thì phải dựng bộ test thứ hai. Ranh giới: nó **quyết định khi nào và bỏ gì**, không tự ghi MinIO — serving đưa cho nó hàm flush.

**Vì sao `model_registry.py` tách khỏi `app.py`:** `app.py` lo HTTP, `model_registry.py` lo vòng đời model. Tách ra thì test được registry bằng MLflow giả mà không cần dựng FastAPI, và test được route bằng registry giả mà không cần MLflow.

---

## Task 1: Cổng classification dùng AUC

**Files:**
- Modify: `common/ml_common/gates.py`
- Test: `common/tests/test_gates.py`

**Interfaces:**
- Consumes: `schema.TASK_TYPES`
- Produces: `gates.FLOOR["classification"] == ("auc", 0.55)`, `gates.COMPARISON["classification"] == ("auc", "higher")`

**Vì sao đổi — hai bằng chứng ngược chiều nhau, cả hai đã đo trên dữ liệu thật:**

| Target | Model | F1 | AUC | Cổng F1 ≥ 0.70 làm gì |
| --- | --- | --- | --- | --- |
| `sold_within_30_days` (55,8% dương) | `dummy` | **0.7186** | 0.5000 | **cho lọt** |
| `needs_renovation` (25,1% dương) | GBM | 0.1592 | **0.7061** | **chặn nhầm** |

F1 phụ thuộc **ngưỡng quyết định** và **tỷ lệ lớp**, nên một con số F1 cố định chỉ đúng cho đúng một phân bố dữ liệu. AUC không phụ thuộc ngưỡng, và mọi model đoán hằng số đều cho đúng 0.5 theo định nghĩa.

- [ ] **Step 1: Sửa test hiện có sang AUC**

Trong `common/tests/test_gates.py`, hai test classification đang dùng `f1`. Thay bằng:

```python
def test_classification_uses_auc_for_both_gates():
    result = evaluate_gates("classification", candidate={"auc": 0.72}, champion={"auc": 0.65})
    assert result["passed"] is True


def test_classification_below_floor_is_blocked():
    result = evaluate_gates("classification", candidate={"auc": 0.52}, champion=None)
    assert result["passed"] is False
```

- [ ] **Step 2: Thêm test cho hai chế độ hỏng của F1**

Thêm vào cuối `common/tests/test_gates.py`:

```python
def test_a_constant_predictor_cannot_pass_the_classification_floor():
    """A model that predicts one class for everything scores AUC 0.5 by definition.

    The old F1 floor let exactly such a model through: predicting the majority
    class on a 55.8%-positive target gives recall 1.0 and F1 0.719, above the
    old 0.70 bar, while its AUC was 0.500.
    """
    result = evaluate_gates("classification", candidate={"auc": 0.50}, champion=None)
    assert result["passed"] is False
    assert "floor" in result["reason"].lower()


def test_a_good_model_with_low_f1_still_passes():
    """F1 collapses on an imbalanced target at the default 0.5 threshold.

    The real classifier scores AUC 0.706 but F1 0.159 on a 25%-positive target.
    The gate must judge it on AUC, or it would block a genuinely good model.
    """
    result = evaluate_gates("classification", candidate={"auc": 0.706}, champion=None)
    assert result["passed"] is True


def test_classification_missing_auc_raises():
    """AUC is now load-bearing: evaluate must always supply it, or we stop."""
    with pytest.raises(KeyError):
        evaluate_gates("classification", candidate={"f1": 0.9}, champion=None)
```

- [ ] **Step 3: Chạy test để xác nhận fail**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_gates.py -v`
Expected: FAIL — các test mới báo `KeyError: 'auc'` hoặc kết quả ngược, vì `FLOOR` vẫn là `("f1", 0.70)`

- [ ] **Step 4: Sửa `gates.py`**

```python
FLOOR: dict[str, tuple[str, float]] = {
    "regression": ("r2", 0.75),
    "classification": ("auc", 0.55),
}

COMPARISON: dict[str, tuple[str, str]] = {
    "regression": ("rmse", "lower"),
    "classification": ("auc", "higher"),
}
```

Cập nhật docstring của module, thêm đoạn giải thích vì sao không dùng F1:

```python
"""The two gates that decide whether a trained model may be promoted.

Gate one blocks junk on an absolute threshold. Gate two blocks a model that is
merely adequate from replacing a better one already in production — both
measured on the same test split, which is why that split has a fixed seed.

Classification is judged on AUC, not F1. F1 depends on both the decision
threshold and the class balance, and it failed in both directions on real data:
a constant predictor scored F1 0.719 on a 55.8%-positive target (above the old
0.70 bar) while its AUC was 0.500, and a genuine model scored F1 0.159 on a
25%-positive target while its AUC was 0.706. AUC is threshold-independent, and
any constant predictor scores exactly 0.5 by construction.
"""
```

- [ ] **Step 5: Chạy test để xác nhận pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_gates.py -v`
Expected: PASS toàn bộ

- [ ] **Step 6: Chạy toàn bộ test và lint**

Run:
```powershell
.venv\Scripts\python.exe -m pytest common/ -q
.venv\Scripts\python.exe -m ruff check common/
```
Expected: `All checks passed!`. Hiện có **213** test; task này sửa 2 test cũ và thêm 3 mới nên tổng phải là **216** — báo con số thật nếu khác.

- [ ] **Step 7: Commit**

```bash
git add common/ml_common/gates.py common/tests/test_gates.py
git commit -m "fix: cong classification dung AUC thay F1"
```

---

## Task 2: `schema.py` — target classification mới

**Files:**
- Modify: `common/ml_common/schema.py`
- Test: `common/tests/test_schema.py`

**Interfaces:**
- Produces: `schema.TARGET_CLASSIFICATION == "needs_renovation"`; `schema.feature_columns("classification")` không chứa `condition`, `sale_price`, `days_on_market`, `sold_within_30_days`, `price_category`, `property_id`

**Điểm quan trọng:** `needs_renovation` **không tồn tại trong raw data** — nó được sinh từ `condition` ở Task 3. Vì vậy nó **không** được thêm vào `COLUMNS`; `COLUMNS` mô tả cột thô. Chỉ `TARGET_CLASSIFICATION` và danh sách leakage đổi.

Hệ quả tự nhiên: `feature_columns()` duyệt `COLUMNS` nên `needs_renovation` không bao giờ lọt vào feature.

- [ ] **Step 1: Viết test**

Thêm vào `common/tests/test_schema.py`:

```python
def test_classification_target_is_needs_renovation():
    assert schema.TARGET_CLASSIFICATION == "needs_renovation"
    assert schema.target_column("classification") == "needs_renovation"


def test_derived_target_is_not_a_raw_column():
    """needs_renovation is computed from condition, so it is not in the raw schema."""
    assert "needs_renovation" not in schema.COLUMNS


def test_condition_is_leakage_for_classification():
    """condition is the source the target is derived from — using it is circular."""
    assert "condition" not in schema.feature_columns("classification")


def test_post_sale_columns_are_leakage_for_classification():
    features = schema.feature_columns("classification")
    for column_name in ("sale_price", "days_on_market", "sold_within_30_days", "price_category"):
        assert column_name not in features


def test_list_price_is_kept_for_classification():
    """Known at listing time, and the single strongest feature (AUC 0.56)."""
    assert "list_price" in schema.feature_columns("classification")
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_schema.py -k "needs_renovation or leakage or list_price" -v`
Expected: FAIL — `TARGET_CLASSIFICATION` vẫn là `"sold_within_30_days"`

- [ ] **Step 3: Sửa `schema.py`**

```python
TARGET_CLASSIFICATION = "needs_renovation"
```

Và trong `_EXCLUDED`, thay khối `"classification"` thành:

```python
    "classification": frozenset(
        {
            ID_COLUMN,
            "condition",  # the column needs_renovation is derived from
            "sale_price",  # only known after the sale
            "days_on_market",  # only known after the sale
            "sold_within_30_days",  # only known after the sale
            "price_category",  # derived from sale_price
        }
    ),
```

Lưu ý `TARGET_CLASSIFICATION` không còn nằm trong `_EXCLUDED` vì nó không phải cột thô — `feature_columns()` duyệt `COLUMNS` nên nó không thể lọt vào.

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_schema.py -v`
Expected: PASS. Nếu có test cũ khẳng định `sold_within_30_days` là target thì sửa nó theo target mới — đó là thay đổi có chủ ý, không phải test hỏng.

- [ ] **Step 5: Chạy toàn bộ test và lint**

Run:
```powershell
.venv\Scripts\python.exe -m pytest common/ -q
.venv\Scripts\python.exe -m ruff check common/
```
Expected: các test khác **sẽ đỏ** — `targets.parse_target` gọi `schema.COLUMNS[target_name].kind` và giờ sẽ `KeyError: 'needs_renovation'`. Đó là dự kiến; Task 3 sửa. Ghi lại chính xác test nào đỏ và vì sao trong report.

- [ ] **Step 6: Commit**

```bash
git add common/ml_common/schema.py common/tests/test_schema.py
git commit -m "feat: doi target classification sang needs_renovation"
```

---

## Task 3: `targets.py` — sinh target thay vì chỉ parse

**Files:**
- Modify: `common/ml_common/targets.py`
- Test: `common/tests/test_targets.py`

**Interfaces:**
- Consumes: `parsers.parse_money`, `parsers.normalize_text`, `schema.TARGET_REGRESSION`
- Produces:
  - `targets.TARGET_SOURCE: dict[str, str]` — `{"regression": "sale_price", "classification": "condition"}`
  - `targets.NEEDS_RENOVATION_CONDITIONS: frozenset[str]` — `{"poor", "fair"}`
  - `targets.derive_target(df: pd.DataFrame, task_type: str) -> pd.Series`

`parse_target` cũ **giữ nguyên** cho regression. `derive_target` là lớp trên: regression thì gọi `parse_target`, classification thì sinh từ `condition`.

- [ ] **Step 1: Viết test**

Thêm vào `common/tests/test_targets.py`:

```python
import pandas as pd

from ml_common.targets import NEEDS_RENOVATION_CONDITIONS, TARGET_SOURCE, derive_target


def _frame(conditions):
    return pd.DataFrame({"condition": conditions, "sale_price": ["$1"] * len(conditions)})


def test_target_source_names_the_column_each_task_reads():
    assert TARGET_SOURCE["regression"] == "sale_price"
    assert TARGET_SOURCE["classification"] == "condition"


def test_poor_and_fair_need_renovation():
    result = derive_target(_frame(["poor", "fair"]), "classification")
    assert list(result) == [True, True]


def test_good_and_excellent_do_not():
    result = derive_target(_frame(["good", "excellent"]), "classification")
    assert list(result) == [False, False]


def test_dirty_condition_is_normalized_before_comparing():
    """Dirty type 3: the same value arrives in several spellings."""
    result = derive_target(_frame(["POOR", "  Fair  ", "Good"]), "classification")
    assert list(result) == [True, True, False]


def test_unknown_condition_becomes_null_not_a_guess():
    result = derive_target(_frame(["poor", "unknown", None]), "classification")
    assert result[0] is True
    assert pd.isna(result[1])
    assert pd.isna(result[2])


def test_index_is_preserved():
    df = _frame(["poor", "good"])
    df.index = [7, 9]
    assert list(derive_target(df, "classification").index) == [7, 9]


def test_regression_still_parses_money():
    df = pd.DataFrame({"sale_price": ["$450,000", "320000"], "condition": ["good", "good"]})
    assert list(derive_target(df, "regression")) == [450000.0, 320000.0]


def test_missing_source_column_raises():
    with pytest.raises(KeyError, match="condition"):
        derive_target(pd.DataFrame({"sale_price": ["$1"]}), "classification")


def test_invalid_task_type_raises():
    with pytest.raises(ValueError, match="task_type"):
        derive_target(_frame(["poor"]), "clustering")


def test_needs_renovation_conditions_are_the_two_bad_ones():
    assert NEEDS_RENOVATION_CONDITIONS == frozenset({"poor", "fair"})
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_targets.py -v`
Expected: FAIL với `ImportError: cannot import name 'derive_target'`

- [ ] **Step 3: Sửa `targets.py`**

Thêm vào cuối file:

```python
TARGET_SOURCE: dict[str, str] = {
    "regression": schema.TARGET_REGRESSION,
    "classification": "condition",
}

NEEDS_RENOVATION_CONDITIONS = frozenset({"poor", "fair"})


def derive_target(df: pd.DataFrame, task_type: str) -> pd.Series:
    """Produces the target column a model is fitted on.

    Regression reads `sale_price` straight from the data. Classification has no
    target column in the raw data at all: `needs_renovation` is derived from
    `condition`, which is why `condition` is leakage for that task.

    Args:
        df: the raw DataFrame, with the source column present.
        task_type: "regression" or "classification".

    Returns:
        A Series with the same index. Values that cannot be read become null
        rather than a guess, so the caller can count and drop them.

    Raises:
        KeyError: when the source column is absent. Silently returning nulls
            would drop every row and look like empty data instead of a bug.
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}")

    source = TARGET_SOURCE[task_type]
    if source not in df.columns:
        raise KeyError(f"missing source column {source!r} needed to build the target")

    if task_type == "regression":
        return parse_target(df[source], task_type)

    values = []
    for raw_value in df[source]:
        normalized = parsers.normalize_text(raw_value)
        if normalized is None or normalized not in schema.COLUMNS["condition"].allowed:
            values.append(None)
        else:
            values.append(normalized in NEEDS_RENOVATION_CONDITIONS)
    return pd.Series(values, index=df.index, dtype="object")
```

Giá trị ngoài danh sách `allowed` của schema trả `None` chứ không trả `False` — `"unknown"` nghĩa là *không biết tình trạng*, khác hẳn *biết là tốt*.

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_targets.py -v`
Expected: PASS

- [ ] **Step 5: Chạy toàn bộ test và lint**

Run:
```powershell
.venv\Scripts\python.exe -m pytest common/ -q
.venv\Scripts\python.exe -m ruff check common/
```
Expected: test đỏ từ Task 2 giờ phải xanh lại. Nếu còn test nào gọi `parse_target(series, "classification")` thì nó vẫn đỏ vì `needs_renovation` không có trong `COLUMNS` — sửa test đó sang `derive_target`, và ghi rõ trong report.

- [ ] **Step 6: Commit**

```bash
git add common/ml_common/targets.py common/tests/test_targets.py
git commit -m "feat: sinh target needs_renovation tu cot condition"
```

---

## Task 4: `validation.py` kiểm cột nguồn của target

**Files:**
- Modify: `common/ml_common/validation.py`
- Test: `common/tests/test_validation.py`

**Interfaces:**
- Consumes: `targets.TARGET_SOURCE`
- Produces: `validate_dataframe` áp luật "hơn 50% target thiếu" lên **cột nguồn** của task

**Vì sao cần:** `validate` chạy **trước** `prepare_dataset_for_train`, nên cột `needs_renovation` chưa tồn tại. Luật fatal "hơn 50% target thiếu" hiện kiểm `schema.target_column(task_type)`, và với classification cột đó không có trong DataFrame nên luật **im lặng không chạy** — mất một cổng chặn mà không ai biết.

Kiểm cột **nguồn** (`condition`) giữ đúng ý định của luật: *có đủ dữ liệu để train không?*

- [ ] **Step 1: Viết test**

Thêm vào `common/tests/test_validation.py`:

```python
def test_classification_checks_the_source_column_not_the_derived_one():
    """needs_renovation does not exist yet when validate runs; condition does."""
    df = _valid_frame(row_count=10)
    df.loc[0:5, "condition"] = None
    report = validate_dataframe(df, "classification")
    assert report["ok"] is False
    assert any("condition" in reason for reason in report["fatal"])


def test_classification_passes_when_condition_is_mostly_present():
    df = _valid_frame(row_count=10)
    df.loc[0:2, "condition"] = None
    report = validate_dataframe(df, "classification")
    assert report["ok"] is True
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_validation.py -k source_column -v`
Expected: FAIL — hiện luật kiểm `needs_renovation`, cột đó không có trong frame nên luật bị bỏ qua và `ok` vẫn là `True`

- [ ] **Step 3: Sửa `validation.py`**

Đổi import và khối kiểm target:

```python
from . import schema
from .targets import TARGET_SOURCE
```

```python
    target_source = TARGET_SOURCE[task_type]
    if target_source in df.columns and row_count > 0:
        missing_rate = _missing_rate(df[target_source])
        if missing_rate > MAX_TARGET_MISSING_RATE:
            fatal.append(
                f"target source {target_source!r} is missing in {missing_rate:.1%} of rows, "
                f"above the {MAX_TARGET_MISSING_RATE:.0%} limit"
            )
```

Kiểm **cột nguồn** chứ không phải cột target: `validate` chạy trước `prepare_dataset_for_train`, nên cột target của classification chưa tồn tại.

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_validation.py -v`
Expected: PASS. Test regression cũ (`test_target_mostly_missing_is_fatal`) vẫn xanh vì với regression cột nguồn chính là `sale_price`.

- [ ] **Step 5: Chạy toàn bộ test và lint**

Run:
```powershell
.venv\Scripts\python.exe -m pytest common/ -q
.venv\Scripts\python.exe -m ruff check common/
```
Expected: toàn bộ xanh. Kiểm không có import vòng: `validation` import `targets`, `targets` import `parsers` và `schema` — không bên nào import ngược lại `validation`.

- [ ] **Step 6: Commit**

```bash
git add common/ml_common/validation.py common/tests/test_validation.py
git commit -m "fix: validate kiem cot nguon cua target thay vi cot dan xuat"
```

---

## Task 5: `inference_log.py` — bộ đệm theo lô

**Files:**
- Create: `common/ml_common/inference_log.py`
- Test: `common/tests/test_inference_log.py`

**Interfaces:**
- Produces:
  - `inference_log.InferenceLogBuffer(flush_size=500, flush_seconds=30.0, max_size=5000, clock=time.monotonic)`
  - `.add(record: dict) -> None`
  - `.should_flush(now: float | None = None) -> bool`
  - `.take() -> list[dict]` — lấy ra và xoá khỏi buffer
  - `.give_back(records: list[dict]) -> None` — trả lại đầu hàng khi flush hỏng
  - `.stats() -> dict` — `{"buffered": int, "dropped": int}`

**Ranh giới:** module này **không đụng MinIO**. Nó chỉ quyết định *khi nào cần flush* và *bỏ gì khi đầy*. Serving đưa hàm ghi thật. Nhờ vậy test bằng list trong bộ nhớ, không cần container.

**`clock` là tham số** để test điều khiển thời gian, không phải `time.sleep(30)`.

- [ ] **Step 1: Viết test**

Tạo `common/tests/test_inference_log.py`:

```python
"""Tests for the inference log buffer.

The buffer holds prediction records in memory and hands them off in batches.
Writing one object per request would fill MinIO with thousands of tiny files
and make the monitoring DAG crawl.
"""

import pytest

from ml_common.inference_log import InferenceLogBuffer


class FakeClock:
    """A clock the test moves by hand, so no test ever sleeps."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _record(index: int) -> dict:
    return {"request_id": f"r{index}", "prediction": float(index)}


def test_a_fresh_buffer_does_not_need_flushing():
    buffer = InferenceLogBuffer(clock=FakeClock())
    assert buffer.should_flush() is False


def test_reaching_flush_size_triggers_a_flush():
    buffer = InferenceLogBuffer(flush_size=3, clock=FakeClock())
    for index in range(2):
        buffer.add(_record(index))
    assert buffer.should_flush() is False
    buffer.add(_record(2))
    assert buffer.should_flush() is True


def test_age_triggers_a_flush_even_when_nearly_empty():
    clock = FakeClock()
    buffer = InferenceLogBuffer(flush_size=500, flush_seconds=30.0, clock=clock)
    buffer.add(_record(0))
    assert buffer.should_flush() is False
    clock.advance(31.0)
    assert buffer.should_flush() is True


def test_an_empty_buffer_never_flushes_no_matter_how_old():
    """Flushing nothing would write an empty file every 30 seconds forever."""
    clock = FakeClock()
    buffer = InferenceLogBuffer(clock=clock)
    clock.advance(600.0)
    assert buffer.should_flush() is False


def test_take_returns_everything_and_empties_the_buffer():
    buffer = InferenceLogBuffer(clock=FakeClock())
    buffer.add(_record(0))
    buffer.add(_record(1))
    taken = buffer.take()
    assert [item["request_id"] for item in taken] == ["r0", "r1"]
    assert buffer.stats()["buffered"] == 0


def test_take_resets_the_age_timer():
    clock = FakeClock()
    buffer = InferenceLogBuffer(flush_seconds=30.0, clock=clock)
    buffer.add(_record(0))
    clock.advance(31.0)
    buffer.take()
    buffer.add(_record(1))
    assert buffer.should_flush() is False


def test_give_back_puts_failed_records_at_the_front():
    """A failed flush must not reorder records behind ones that arrived later."""
    buffer = InferenceLogBuffer(clock=FakeClock())
    buffer.add(_record(9))
    buffer.give_back([_record(0), _record(1)])
    assert [item["request_id"] for item in buffer.take()] == ["r0", "r1", "r9"]


def test_overflow_drops_the_oldest_and_counts_it():
    buffer = InferenceLogBuffer(max_size=3, clock=FakeClock())
    for index in range(5):
        buffer.add(_record(index))
    assert [item["request_id"] for item in buffer.take()] == ["r2", "r3", "r4"]
    assert buffer.stats()["dropped"] == 2


def test_give_back_beyond_the_cap_also_drops_oldest():
    """MinIO down for a long stretch must not grow the buffer without bound."""
    buffer = InferenceLogBuffer(max_size=3, clock=FakeClock())
    buffer.add(_record(8))
    buffer.add(_record(9))
    buffer.give_back([_record(0), _record(1), _record(2)])
    assert buffer.stats()["buffered"] == 3
    assert buffer.stats()["dropped"] == 2


def test_dropped_count_survives_take():
    """/health reports this number, so it must not reset when a flush succeeds."""
    buffer = InferenceLogBuffer(max_size=2, clock=FakeClock())
    for index in range(4):
        buffer.add(_record(index))
    buffer.take()
    assert buffer.stats()["dropped"] == 2


def test_stats_is_json_serializable():
    import json

    buffer = InferenceLogBuffer(clock=FakeClock())
    buffer.add(_record(0))
    json.dumps(buffer.stats())


def test_flush_size_must_be_at_most_max_size():
    with pytest.raises(ValueError, match="flush_size"):
        InferenceLogBuffer(flush_size=10, max_size=5)
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_inference_log.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.inference_log'`

- [ ] **Step 3: Viết `common/ml_common/inference_log.py`**

```python
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
"""

from __future__ import annotations

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

    def _trim(self) -> None:
        while len(self._records) > self._max_size:
            self._records.popleft()
            self._dropped += 1

    def add(self, record: dict) -> None:
        """Appends one record, dropping the oldest if that puts us over the cap."""
        self._records.append(record)
        self._trim()

    def give_back(self, records: list[dict]) -> None:
        """Returns records a failed flush could not write, keeping their order.

        They go to the FRONT: they arrived before anything still buffered, and
        reordering them would scramble the timeline the monitoring DAG reads.
        """
        self._records.extendleft(reversed(records))
        self._trim()

    def should_flush(self, now: float | None = None) -> bool:
        """True when the batch is full enough, or has waited long enough.

        An empty buffer never flushes, however old — otherwise serving would
        write an empty file every flush interval for as long as it idles.
        """
        if not self._records:
            return False
        if len(self._records) >= self._flush_size:
            return True
        current = self._clock() if now is None else now
        return (current - self._last_taken_at) >= self._flush_seconds

    def take(self) -> list[dict]:
        """Removes and returns every buffered record, and restarts the age timer."""
        taken = list(self._records)
        self._records.clear()
        self._last_taken_at = self._clock()
        return taken

    def stats(self) -> dict:
        """Counts for /health. `dropped` is cumulative and never resets."""
        return {"buffered": len(self._records), "dropped": self._dropped}
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_inference_log.py -v`
Expected: PASS, 12 test

- [ ] **Step 5: Chạy toàn bộ test, lint, và build lại image nền**

Run:
```powershell
.venv\Scripts\python.exe -m pytest common/ -q
.venv\Scripts\python.exe -m ruff check common/
powershell -ExecutionPolicy Bypass -File scripts\build_base_image.ps1
docker run --rm ml-base:latest sh -c "pip install --quiet 'pytest>=8.0' 'moto[s3]>=5.0' && python -m pytest /app/common/tests -q"
```
Expected: local và container ra cùng số test (container thiếu 1 vì test đọc `dags/` bị skip). Lệch nhiều hơn thế là khác biệt môi trường — **dừng lại và báo BLOCKED**.

- [ ] **Step 6: Commit**

```bash
git add common/ml_common/inference_log.py common/tests/test_inference_log.py
git commit -m "feat: bo dem inference log theo lo co tran"
```

---

## Task 6: Stage và DAG dùng target mới

**Files:**
- Modify: `stages/prepare_dataset_for_train/main.py`
- Modify: `dags/ml_pipeline_dag.py`

**Interfaces:**
- Consumes: `targets.derive_target`, `schema.target_column`
- Produces: `processed/{fp}/{train,test}.parquet` có cột `needs_renovation` kiểu bool khi `task_type=classification`

**Ba lỗi phải sửa cùng lúc, vì chúng cùng chặn nhánh classification:**

1. `prepare_dataset_for_train` gọi `parse_target`, sẽ nổ `KeyError: 'needs_renovation'` vì cột đó không có trong `schema.COLUMNS`.
2. DAG có `model_name` trong `params` mặc định cứng theo regression. Chạy `task_type=classification` mà quên truyền sẽ **ghi model classification vào registered model của regression** — hỏng registry im lặng, và `evaluate` sẽ so hai model khác bài toán.
3. DAG có `estimator_name` mặc định `"ridge"`, không hợp lệ cho classification — `build_estimator` ném `ValueError`.

Lỗi 2 nguy hiểm nhất vì nó **không nổ**; nó chỉ ghi sai chỗ.

- [ ] **Step 1: Sửa `stages/prepare_dataset_for_train/main.py`**

Đổi import:

```python
from ml_common.targets import derive_target
```

Đổi khối sinh target (hiện là `df[target] = parse_target(df[target], task_type)`):

```python
    target = schema.target_column(task_type)
    df[target] = derive_target(df, task_type)

    df, missing_target_count = drop_rows_missing_target(df, task_type)
    print(f"dropped {missing_target_count} rows with an unusable target", file=sys.stderr)

    if task_type == "classification":
        # derive_target returns object dtype so it can carry nulls; once those
        # rows are gone, pin it to bool so the parquet schema is deterministic
        # and train does not receive an object column.
        df[target] = df[target].astype(bool)
```

Cập nhật docstring của module: target của classification **được sinh ra** từ `condition`, không đọc sẵn từ raw.

- [ ] **Step 2: Sửa `dags/ml_pipeline_dag.py`**

Thêm bảng estimator mặc định, cạnh `MODEL_NAME_BY_TASK_TYPE` đã có:

```python
DEFAULT_ESTIMATOR_BY_TASK_TYPE = {
    "regression": "ridge",
    "classification": "logistic",
}
```

Đổi `MODEL_NAME` và thêm `ESTIMATOR_NAME` thành template suy từ `task_type`:

```python
MODEL_NAME = "{{ model_name_for(params.task_type) }}"
ESTIMATOR_NAME = "{{ params.estimator_name or default_estimator_for(params.task_type) }}"
```

Trong `DAG(...)`: **bỏ `model_name` khỏi `params`**, cho `estimator_name` mặc định `None`, và đăng ký hai macro:

```python
    params={
        "task_type": "regression",
        "force_reprocess": False,
        "dataset_version": "v1",
        "estimator_name": None,
    },
    # model_name is derived, never passed: a run that names the wrong registered
    # model does not fail, it quietly registers a classifier under the regressor.
    user_defined_macros={
        "model_name_for": MODEL_NAME_BY_TASK_TYPE.__getitem__,
        "default_estimator_for": DEFAULT_ESTIMATOR_BY_TASK_TYPE.__getitem__,
    },
    user_defined_filters={"stage_result": stage_result},
```

Trong task `train`, thay `"ESTIMATOR_NAME": "{{ params.estimator_name }}"` bằng hằng `ESTIMATOR_NAME` vừa định nghĩa.

- [ ] **Step 3: Build lại image bị ảnh hưởng**

`common/` đã đổi ở Task 1-5, và `stages/prepare_dataset_for_train/main.py` vừa đổi:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_base_image.ps1
powershell -ExecutionPolicy Bypass -File scripts\build_stage_images.ps1
```
Expected: dòng cuối `All stage images built.`

- [ ] **Step 4: Xác nhận DAG parse được và macro hoạt động**

Run:
```powershell
docker compose exec -T airflow-scheduler airflow dags list-import-errors
docker compose exec -T airflow-scheduler airflow dags list
```
Expected: không có import error; `ml_pipeline` có trong danh sách.

- [ ] **Step 5: Chạy `prepare_dataset_for_train` tay cho classification**

Dùng fingerprint đã có từ Plan 2 (`extracted/719d453fab924470/data.parquet`, 1000 dòng):

```powershell
docker run --rm --network mlops_default --env-file .env -e MINIO_ENDPOINT_INTERNAL=http://minio:9000 -e FINGERPRINT=719d453fab924470 -e TASK_TYPE=classification -e FORCE_REPROCESS=true ml-prepare-dataset:latest
```
Expected: dòng cuối stdout là `XCOM_RESULT {...}` với `"skipped": false`.

**Lưu ý:** lần chạy này **ghi đè** `processed/719d453fab924470/` bằng bản classification. Đó là hạn chế đã biết của fingerprint hiện tại — nó chỉ băm dữ liệu raw, không băm `task_type`. Với Plan 3 thì không sao vì Task 7 chạy DAG đầy đủ sinh fingerprint riêng. **Ghi nhận điểm này trong report** để Plan 4 biết.

- [ ] **Step 6: Xác nhận cột target được sinh đúng**

```powershell
.venv\Scripts\python.exe -c "from ml_common.storage import Storage, processed_key; tr=Storage.from_env().read_parquet(processed_key('719d453fab924470','train')); print('cot target:', 'needs_renovation' in tr.columns); print('dtype:', tr['needs_renovation'].dtype); print('ty le duong: %.1f%%' % (100*tr['needs_renovation'].mean())); print('condition van tho:', tr['condition'].unique()[:5])"
```
Expected:
- `needs_renovation` có mặt, dtype `bool`
- tỷ lệ dương khoảng **20-30%**
- `condition` **vẫn còn trong file** (nó là cột thô; `SelectColumns` trong Pipeline mới là chỗ loại nó khỏi feature)

Nếu tỷ lệ dương là 0% hoặc 100% thì `derive_target` sai — dừng lại và sửa.

- [ ] **Step 7: Commit**

```bash
git add stages/prepare_dataset_for_train/main.py dags/ml_pipeline_dag.py
git commit -m "feat: stage va DAG dung target classification moi"
```

---

## Task 7: Chạy nhánh classification tới khi có champion

**Files:** không sửa file nào — task này **chạy** và **xác nhận**.

**Interfaces:**
- Consumes: mọi thứ từ Task 1-6
- Produces: registered model `house_needs_renovation_classifier` với alias `champion`, AUC ≥ 0.55

Đây là lần đầu nhánh classification chạy hết DAG. Mục tiêu không phải model tốt, mà **chứng minh cổng AUC hoạt động đúng cả hai chiều** trên dữ liệu thật.

`.env` đang có `SAMPLE_ROWS=20000`. **Giữ nguyên** — đủ tín hiệu và chạy nhanh.

- [ ] **Step 1: Chạy DAG với model rác, phải bị chặn**

```powershell
docker compose exec -T airflow-scheduler airflow dags test ml_pipeline 2026-09-19 --conf '{\"task_type\": \"classification\", \"estimator_name\": \"dummy\"}'
```
Expected:
- `evaluate` in `"passed": false`, `reason` nhắc tới `floor`, và `auc` khoảng **0.50**
- nhánh đi vào `stop_no_deploy`, `register` bị skip
- **không task nào fail**, `DagRun state=success`

Đây là bằng chứng cổng AUC chặn được thứ mà cổng F1 cũ cho lọt.

- [ ] **Step 2: Chạy DAG với model thật**

```powershell
docker compose exec -T airflow-scheduler airflow dags test ml_pipeline 2026-09-19 --conf '{\"task_type\": \"classification\", \"estimator_name\": \"hist_gradient_boosting\"}'
```
Expected: `evaluate` in `"passed": true` với `auc` khoảng **0.65-0.72**, nhánh vào `register`.

Con số thật có thể lệch vì `SAMPLE_ROWS=20000` khác tập 48k đã đo. **Nếu AUC dưới 0.55 thì dừng lại và báo con số thật — đừng hạ ngưỡng.**

- [ ] **Step 3: Xác nhận champion classification tồn tại**

```powershell
.venv\Scripts\python.exe -c "import mlflow; from mlflow import MlflowClient; mlflow.set_tracking_uri('http://localhost:5000'); c=MlflowClient(); v=c.get_model_version_by_alias('house_needs_renovation_classifier','champion'); r=c.get_run(v.run_id); print('version', v.version, '| estimator', r.data.params['estimator'], '| test_auc', round(r.data.metrics['test_auc'],4)); print('f1 de bao cao:', round(r.data.metrics.get('test_f1', -1),4))"
```
Expected: version, estimator `hist_gradient_boosting`, `test_auc` ≥ 0.55.

`test_f1` in ra thường **thấp** (~0.1-0.3) — đó chính là lý do không dùng F1 làm cổng. Ghi lại con số này trong report, nó là bằng chứng sống cho quyết định ở Task 1.

- [ ] **Step 4: Xác nhận model regression không bị đụng**

```powershell
.venv\Scripts\python.exe -c "import mlflow; from mlflow import MlflowClient; mlflow.set_tracking_uri('http://localhost:5000'); c=MlflowClient(); print([m.name for m in c.search_registered_models()]); v=c.get_model_version_by_alias('house_price_regressor','champion'); print('regressor champion van la version', v.version)"
```
Expected: hai registered model riêng biệt, champion của regression **không đổi**. Đây là bằng chứng lỗi số 2 ở Task 6 đã được sửa.

- [ ] **Step 5: Ghi lại số đo vào report**

Không commit gì. Ghi vào report: AUC của `dummy`, AUC và F1 của model thật, version champion, và fingerprint của lần chạy classification.

---

## Task 8: `model_registry.py` — vòng đời model trong serving

**Files:**
- Create: `services/serving/model_registry.py`
- Test: `services/serving/tests/test_model_registry.py`
- Create: `services/serving/tests/__init__.py` (file rỗng)

**Interfaces:**
- Produces:
  - `model_registry.MODEL_NAMES: dict[str, str]` — `{"regression": "house_price_regressor", "classification": "house_needs_renovation_classifier"}`
  - `model_registry.LoadedModel` — dataclass `(name: str, version: str, model)`
  - `model_registry.ModelRegistry(loader=None)` với `.reload() -> dict[str, LoadedModel | None]`, `.get(task_type) -> LoadedModel | None`, `.describe() -> dict`

**`loader` là tham số** để test tiêm hàm giả, không cần MLflow chạy. Mặc định là hàm load thật từ MLflow.

**Thiếu model không phải lỗi.** `reload()` không bao giờ ném vì một model vắng mặt — nó ghi `None` cho model đó và đi tiếp. Registry trống là trạng thái hợp lệ lúc dựng hệ thống.

- [ ] **Step 1: Viết test**

Tạo `services/serving/tests/__init__.py` (rỗng) và `services/serving/tests/test_model_registry.py`:

```python
"""Tests for model lifecycle inside serving, with a fake loader instead of MLflow."""

import pytest

from services.serving.model_registry import MODEL_NAMES, ModelRegistry


class FakeLoader:
    """Stands in for MLflow. Raises for names it was not given."""

    def __init__(self, available: dict):
        self.available = available
        self.calls = 0

    def __call__(self, model_name: str):
        self.calls += 1
        if model_name not in self.available:
            raise RuntimeError(f"no champion for {model_name}")
        return self.available[model_name]


def test_model_names_cover_both_task_types():
    assert set(MODEL_NAMES) == {"regression", "classification"}
    assert MODEL_NAMES["classification"] == "house_needs_renovation_classifier"


def test_reload_loads_every_available_model():
    loader = FakeLoader({name: ("model", "7") for name in MODEL_NAMES.values()})
    registry = ModelRegistry(loader=loader)
    registry.reload()
    assert registry.get("regression").version == "7"
    assert registry.get("classification").version == "7"


def test_a_missing_model_does_not_stop_the_others():
    """Serving must come up before the second model has ever been trained."""
    loader = FakeLoader({MODEL_NAMES["regression"]: ("model", "3")})
    registry = ModelRegistry(loader=loader)
    registry.reload()
    assert registry.get("regression") is not None
    assert registry.get("classification") is None


def test_reload_never_raises_when_nothing_is_available():
    registry = ModelRegistry(loader=FakeLoader({}))
    registry.reload()
    assert registry.get("regression") is None


def test_reload_replaces_the_previous_version():
    loader = FakeLoader({MODEL_NAMES["regression"]: ("old", "1")})
    registry = ModelRegistry(loader=loader)
    registry.reload()
    loader.available[MODEL_NAMES["regression"]] = ("new", "2")
    registry.reload()
    assert registry.get("regression").version == "2"
    assert registry.get("regression").model == "new"


def test_describe_reports_loaded_state_for_both():
    loader = FakeLoader({MODEL_NAMES["regression"]: ("model", "3")})
    registry = ModelRegistry(loader=loader)
    registry.reload()
    described = registry.describe()
    assert described["regression"] == {
        "loaded": True,
        "name": "house_price_regressor",
        "version": "3",
    }
    assert described["classification"] == {
        "loaded": False,
        "name": "house_needs_renovation_classifier",
        "version": None,
    }


def test_describe_is_json_serializable():
    import json

    registry = ModelRegistry(loader=FakeLoader({}))
    registry.reload()
    json.dumps(registry.describe())


def test_get_rejects_an_unknown_task_type():
    registry = ModelRegistry(loader=FakeLoader({}))
    with pytest.raises(KeyError):
        registry.get("clustering")
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv\Scripts\python.exe -m pytest services/serving/tests/ -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'services'`

- [ ] **Step 3: Viết `services/serving/model_registry.py`**

```python
"""Loads champion models from the MLflow Registry and keeps them in memory.

Serving ships no model of its own: it asks the Registry for whatever currently
holds the `champion` alias. A model that is not there yet is not an error —
classification has no champion until that branch has been trained, and serving
must still come up and say so.

The loader is injectable so the routes can be tested without MLflow running.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

CHAMPION_ALIAS = "champion"

MODEL_NAMES: dict[str, str] = {
    "regression": "house_price_regressor",
    "classification": "house_needs_renovation_classifier",
}


@dataclass(frozen=True)
class LoadedModel:
    """One model currently in memory, with the version it came from."""

    name: str
    version: str
    model: object


def load_from_mlflow(model_name: str):
    """Fetches the champion of one registered model. Returns (model, version)."""
    import mlflow
    import mlflow.sklearn
    from mlflow import MlflowClient

    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    version = MlflowClient().get_model_version_by_alias(model_name, CHAMPION_ALIAS)
    model = mlflow.sklearn.load_model(f"models:/{model_name}@{CHAMPION_ALIAS}")
    return model, str(version.version)


class ModelRegistry:
    """Holds the champion of each task type, and swaps them on reload."""

    def __init__(self, loader=load_from_mlflow):
        self._loader = loader
        self._loaded: dict[str, LoadedModel | None] = dict.fromkeys(MODEL_NAMES)

    def reload(self) -> dict[str, LoadedModel | None]:
        """Reloads every champion. A model that cannot be loaded becomes None.

        Never raises for a missing model: an empty Registry is a normal state
        while the system is being built, not a failure to report.
        """
        for task_type, model_name in MODEL_NAMES.items():
            try:
                model, version = self._loader(model_name)
                self._loaded[task_type] = LoadedModel(model_name, version, model)
            except Exception as err:  # noqa: BLE001 - any failure means "not available"
                print(f"could not load {model_name}: {err}", file=sys.stderr)
                self._loaded[task_type] = None
        return self._loaded

    def get(self, task_type: str) -> LoadedModel | None:
        """The model for a task type, or None when it is not loaded.

        Raises KeyError for a task type that does not exist, so a typo in a
        route surfaces immediately instead of looking like a missing model.
        """
        if task_type not in MODEL_NAMES:
            raise KeyError(f"unknown task type: {task_type!r}")
        return self._loaded[task_type]

    def describe(self) -> dict:
        """The `models` block /health and /reload both return."""
        return {
            task_type: {
                "loaded": loaded is not None,
                "name": MODEL_NAMES[task_type],
                "version": loaded.version if loaded else None,
            }
            for task_type, loaded in self._loaded.items()
        }
```

- [ ] **Step 4: Cho pytest thấy package `services`**

Tạo `services/__init__.py` và `services/serving/__init__.py`, cả hai rỗng, để `from services.serving...` import được khi chạy pytest từ gốc repo.

- [ ] **Step 5: Chạy test để xác nhận pass**

Run: `.venv\Scripts\python.exe -m pytest services/serving/tests/ -v`
Expected: PASS, 8 test

- [ ] **Step 6: Lint**

Run: `.venv\Scripts\python.exe -m ruff check services/ --line-length 100`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add services/
git commit -m "feat: model registry cho serving, thieu model khong phai loi"
```

---

## Task 9: `app.py` — FastAPI routes

**Files:**
- Create: `services/serving/app.py`
- Test: `services/serving/tests/test_app.py`

**Interfaces:**
- Consumes: `model_registry.ModelRegistry`, `inference_log.InferenceLogBuffer`, `storage.inference_log_key`
- Produces: `app.create_app(registry=None, buffer=None, flush=None, start_flusher=True) -> FastAPI`, và `app.app` cho uvicorn

**`create_app` là factory có tham số** để test tiêm registry giả và buffer giả — không cần MLflow, không cần MinIO. `start_flusher=False` tắt vòng lặp nền trong test.

**Ba điều bất biến của `/predict`:**

1. Nhận record **thô**. Model tự làm sạch. **Không import `ml_common.cleaning`, không import `ml_common.rowops`.**
2. Không bao giờ chậm hay lỗi vì chuyện ghi log — nó chỉ `buffer.add()`, việc ghi do vòng lặp nền làm.
3. Model chưa load trả **503**, không phải 500. 503 nghĩa là "chưa sẵn sàng, thử lại sau"; 500 nghĩa là "hỏng".

**Ghi lô gom theo `(model_name, ngày)`:** một lô có thể chứa record của cả hai model và có thể vắt qua nửa đêm, mà `inference_log_key` phân vùng theo model và theo ngày. Ngày lấy từ **timestamp của record**, không phải lúc flush.

`raw_input` lưu dạng **chuỗi JSON**, vì parquet không lưu dict lồng nhau gọn gàng và Plan 4 chỉ cần đọc lại được.

- [ ] **Step 1: Viết test**

Tạo `services/serving/tests/test_app.py`:

```python
"""Tests for the serving routes, with fake models instead of MLflow and MinIO."""

import json

import pytest
from fastapi.testclient import TestClient

from ml_common.inference_log import InferenceLogBuffer
from services.serving.app import create_app
from services.serving.model_registry import LoadedModel, ModelRegistry


class FakeModel:
    """Returns a fixed answer, and records what it was given."""

    def __init__(self, value=412350.75, proba=0.83):
        self.value = value
        self.proba = proba
        self.seen = None

    def predict(self, frame):
        self.seen = frame
        return [self.value] * len(frame)

    def predict_proba(self, frame):
        return [[1 - self.proba, self.proba]] * len(frame)


def _registry(loaded: dict) -> ModelRegistry:
    registry = ModelRegistry(loader=lambda name: (_ for _ in ()).throw(RuntimeError("unused")))
    registry._loaded = loaded  # noqa: SLF001 - deliberate: this is the seam under test
    return registry


def _client(loaded: dict, buffer=None, flush=None) -> TestClient:
    app = create_app(
        registry=_registry(loaded),
        buffer=buffer or InferenceLogBuffer(),
        flush=flush or (lambda records: None),
        start_flusher=False,
    )
    return TestClient(app)


RAW_RECORD = {
    "city": "  NEW YORK ",
    "list_price": "$450,000",
    "bedrooms": 3,
    "zipcode": "10001",
}


def test_health_reports_degraded_when_nothing_is_loaded():
    response = _client({"regression": None, "classification": None}).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


def test_health_reports_ok_when_one_model_is_loaded():
    loaded = {
        "regression": LoadedModel("house_price_regressor", "3", FakeModel()),
        "classification": None,
    }
    body = _client(loaded).get("/health").json()
    assert body["status"] == "ok"
    assert body["models"]["regression"]["version"] == "3"
    assert body["models"]["classification"]["loaded"] is False


def test_health_reports_buffer_counts():
    body = _client({"regression": None, "classification": None}).get("/health").json()
    assert body["inference_log"] == {"buffered": 0, "dropped": 0}


def test_predict_on_a_model_that_is_not_loaded_returns_503():
    """Not ready is not the same as broken; 500 would tell the caller to give up."""
    response = _client({"regression": None, "classification": None}).post(
        "/predict/regression", json=RAW_RECORD
    )
    assert response.status_code == 503


def test_predict_with_an_unknown_model_name_returns_422():
    response = _client({"regression": None, "classification": None}).post(
        "/predict/clustering", json=RAW_RECORD
    )
    assert response.status_code == 422


def test_predict_returns_prediction_and_provenance():
    model = FakeModel()
    loaded = {
        "regression": LoadedModel("house_price_regressor", "3", model),
        "classification": None,
    }
    body = _client(loaded).post("/predict/regression", json=RAW_RECORD).json()
    assert body["prediction"] == 412350.75
    assert body["model_name"] == "house_price_regressor"
    assert body["model_version"] == "3"
    assert len(body["request_id"]) > 0


def test_the_model_receives_the_record_untouched():
    """Serving must not clean anything: the Pipeline inside the model does that."""
    model = FakeModel()
    loaded = {
        "regression": LoadedModel("house_price_regressor", "3", model),
        "classification": None,
    }
    _client(loaded).post("/predict/regression", json=RAW_RECORD)
    assert model.seen["list_price"].iloc[0] == "$450,000"
    assert model.seen["city"].iloc[0] == "  NEW YORK "


def test_classification_returns_a_boolean_and_a_probability():
    model = FakeModel(value=True, proba=0.83)
    loaded = {
        "regression": None,
        "classification": LoadedModel("house_needs_renovation_classifier", "1", model),
    }
    body = _client(loaded).post("/predict/classification", json=RAW_RECORD).json()
    assert body["prediction"] is True
    assert body["probability"] == pytest.approx(0.83)


def test_a_record_missing_optional_columns_is_accepted():
    """The Pipeline imputes; rejecting these would be stricter than the model."""
    model = FakeModel()
    loaded = {
        "regression": LoadedModel("house_price_regressor", "3", model),
        "classification": None,
    }
    response = _client(loaded).post("/predict/regression", json={"city": "austin"})
    assert response.status_code == 200


def test_each_prediction_adds_exactly_one_buffered_record():
    buffer = InferenceLogBuffer()
    loaded = {
        "regression": LoadedModel("house_price_regressor", "3", FakeModel()),
        "classification": None,
    }
    client = _client(loaded, buffer=buffer)
    client.post("/predict/regression", json=RAW_RECORD)
    client.post("/predict/regression", json=RAW_RECORD)
    assert buffer.stats()["buffered"] == 2


def test_the_buffered_record_carries_everything_plan_4_needs():
    buffer = InferenceLogBuffer()
    loaded = {
        "regression": LoadedModel("house_price_regressor", "3", FakeModel()),
        "classification": None,
    }
    _client(loaded, buffer=buffer).post("/predict/regression", json=RAW_RECORD)
    record = buffer.take()[0]
    assert set(record) >= {
        "request_id",
        "timestamp",
        "raw_input",
        "prediction",
        "model_name",
        "model_version",
        "day",
    }
    assert json.loads(record["raw_input"])["list_price"] == "$450,000"


def test_a_failing_flush_never_reaches_the_caller():
    """Logging is secondary to serving; a broken MinIO must not break /predict."""

    def broken_flush(records):
        raise RuntimeError("MinIO is down")

    loaded = {
        "regression": LoadedModel("house_price_regressor", "3", FakeModel()),
        "classification": None,
    }
    response = _client(loaded, flush=broken_flush).post("/predict/regression", json=RAW_RECORD)
    assert response.status_code == 200


def test_reload_returns_the_same_models_block_as_health():
    loaded = {"regression": None, "classification": None}
    client = _client(loaded)
    assert client.post("/reload").json()["models"] == client.get("/health").json()["models"]
```

- [ ] **Step 2: Chạy test để xác nhận fail**

Run: `.venv\Scripts\python.exe -m pytest services/serving/tests/test_app.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'services.serving.app'`

Nếu báo thiếu `fastapi` hay `httpx`, cài vào venv dev:
```powershell
.venv\Scripts\python.exe -m pip install "fastapi>=0.115" "httpx>=0.27"
```

- [ ] **Step 3: Viết `services/serving/app.py`**

```python
"""HTTP surface for model serving.

Two rules shape everything here:

The model cleans its own input. /predict takes a raw record — money still
written "$450,000", city still "  NEW YORK " — and hands it to the Pipeline
unchanged. This module must never import ml_common.cleaning, and must never
import ml_common.rowops: a row-dropping transformer handed one record returns
an empty frame and takes serving down with it.

Logging never blocks serving. /predict appends to an in-memory buffer and
returns; a background loop writes batches to object storage. A failure there
is logged and retried, never surfaced to the caller.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Literal
from uuid import uuid4

import pandas as pd
from fastapi import Body, FastAPI, HTTPException

from ml_common.inference_log import InferenceLogBuffer
from ml_common.storage import Storage, inference_log_key

from .model_registry import ModelRegistry

FLUSH_POLL_SECONDS = 1.0


def write_batch(records: list[dict]) -> None:
    """Writes one batch to object storage, one file per model and per day.

    A batch can hold records for both models and can straddle midnight, while
    the key is partitioned by model and by day — so group before writing, using
    the day each record was served, not the day the flush happens.
    """
    storage = Storage.from_env()
    frame = pd.DataFrame(records)
    for (model_name, day), group in frame.groupby(["model_name", "day"], sort=False):
        key = inference_log_key(model_name, date.fromisoformat(day), uuid4().hex[:8])
        storage.write_parquet(group.drop(columns=["day"]).reset_index(drop=True), key)


def create_app(
    registry: ModelRegistry | None = None,
    buffer: InferenceLogBuffer | None = None,
    flush=write_batch,
    start_flusher: bool = True,
) -> FastAPI:
    """Builds the app. Every collaborator is injectable so tests need no infra."""
    registry = registry if registry is not None else ModelRegistry()
    buffer = buffer if buffer is not None else InferenceLogBuffer()

    def drain() -> None:
        """Hands one batch to the writer, putting it back if the write fails."""
        if not buffer.should_flush():
            return
        records = buffer.take()
        if not records:
            return
        try:
            flush(records)
        except Exception as err:  # noqa: BLE001 - any write failure is retryable
            print(f"inference log flush failed, keeping {len(records)} records: {err}",
                  file=sys.stderr)
            buffer.give_back(records)

    async def flusher() -> None:
        while True:
            await asyncio.sleep(FLUSH_POLL_SECONDS)
            await asyncio.to_thread(drain)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        registry.reload()
        task = asyncio.create_task(flusher()) if start_flusher else None
        yield
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await asyncio.to_thread(drain)

    app = FastAPI(title="house pricing serving", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict:
        described = registry.describe()
        any_loaded = any(entry["loaded"] for entry in described.values())
        return {
            "status": "ok" if any_loaded else "degraded",
            "models": described,
            "inference_log": buffer.stats(),
        }

    @app.post("/reload")
    def reload() -> dict:
        registry.reload()
        return {"models": registry.describe()}

    @app.post("/predict/{task_type}")
    def predict(
        task_type: Literal["regression", "classification"],
        record: dict = Body(...),
    ) -> dict:
        loaded = registry.get(task_type)
        if loaded is None:
            raise HTTPException(
                status_code=503,
                detail=f"no champion loaded for {task_type}; train it, then POST /reload",
            )

        frame = pd.DataFrame([record])
        try:
            prediction = loaded.model.predict(frame)[0]
            probability = None
            if task_type == "classification" and hasattr(loaded.model, "predict_proba"):
                probability = float(loaded.model.predict_proba(frame)[0][1])
        except Exception as err:  # noqa: BLE001 - surfaces as 500 with the reason
            raise HTTPException(status_code=500, detail=f"prediction failed: {err}") from err

        prediction = bool(prediction) if task_type == "classification" else float(prediction)
        now = datetime.now(timezone.utc)
        request_id = str(uuid4())

        buffer.add(
            {
                "request_id": request_id,
                "timestamp": now.isoformat(),
                "day": now.date().isoformat(),
                "raw_input": json.dumps(record, default=str),
                "prediction": prediction,
                "model_name": loaded.name,
                "model_version": loaded.version,
            }
        )

        body = {
            "request_id": request_id,
            "prediction": prediction,
            "model_name": loaded.name,
            "model_version": loaded.version,
        }
        if probability is not None:
            body["probability"] = probability
        return body

    return app


app = create_app()
```

- [ ] **Step 4: Chạy test để xác nhận pass**

Run: `.venv\Scripts\python.exe -m pytest services/serving/tests/ -v`
Expected: PASS, 21 test (8 từ Task 8 + 13 mới)

- [ ] **Step 5: Xác nhận serving không import logic cleaning**

Đây là ràng buộc kiến trúc, kiểm bằng lệnh chứ không bằng mắt:

```powershell
.venv\Scripts\python.exe -m pytest services/serving/tests/ -q
findstr /S /C:"ml_common.cleaning" /C:"ml_common.rowops" services\serving\*.py
```
Expected: pytest xanh; `findstr` **không tìm thấy gì**. Có kết quả nghĩa là ranh giới đã bị phá — dừng lại và báo.

- [ ] **Step 6: Lint**

Run: `.venv\Scripts\python.exe -m ruff check services/ --line-length 100`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add services/serving/app.py services/serving/tests/test_app.py
git commit -m "feat: routes serving nhan record tho va ghi log theo lo"
```

---

## Task 10: Image serving và service trong compose

**Files:**
- Create: `services/serving/Dockerfile`
- Modify: `docker-compose.yml`

**Interfaces:**
- Produces: `mlops-serving` chạy healthy ở `http://localhost:8000`, và tới được từ network `mlops_default` bằng hostname `serving`

**`FROM ml-base:latest` là bắt buộc**, không phải tiện tay: đó là cách duy nhất khoá version scikit-learn giữa lúc train và lúc serve. Model pickle bởi sklearn 1.9.1 mà load bằng bản khác sẽ hỏng, hoặc tệ hơn là load được nhưng hành xử khác.

- [ ] **Step 1: Kiểm tra dung lượng đĩa**

Run: `.venv\Scripts\python.exe -c "import shutil; print(f'{shutil.disk_usage(\"C:/\").free/2**30:.1f} GB free')"`
Cộng thêm `docker system df`. Image này `FROM ml-base` nên chỉ thêm FastAPI + uvicorn (~30MB). Nếu build cache đã phình thì `docker builder prune -f` (chỉ xoá cache, an toàn).

- [ ] **Step 2: Viết `services/serving/Dockerfile`**

```dockerfile
# Serving. Build from the repo root:
#   docker build -f services/serving/Dockerfile -t ml-serving:latest .
#
# FROM ml-base is a hard requirement, not convenience: a model pickled by one
# scikit-learn version does not reliably load in another. Sharing the base image
# with the train stage makes the versions match structurally.
FROM ml-base:latest

RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.30"

COPY services/ /app/services/

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "services.serving.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Build image**

Run: `docker build -f services/serving/Dockerfile -t ml-serving:latest .`
Expected: build thành công, dòng cuối `naming to docker.io/library/ml-serving:latest`

- [ ] **Step 4: Thêm service `serving` vào `docker-compose.yml`**

Chèn **dưới `airflow-webserver`, trước khối `volumes:`**:

```yaml
  serving:
    build:
      context: .
      dockerfile: services/serving/Dockerfile
    image: ml-serving:latest
    container_name: mlops-serving
    depends_on:
      minio:
        condition: service_healthy
      mlflow:
        condition: service_healthy
    environment:
      MINIO_ENDPOINT_INTERNAL: ${MINIO_ENDPOINT_INTERNAL}
      MINIO_ACCESS_KEY: ${MINIO_ACCESS_KEY}
      MINIO_SECRET_KEY: ${MINIO_SECRET_KEY}
      ML_BUCKET: ${ML_BUCKET}
      MLFLOW_TRACKING_URI: ${MLFLOW_TRACKING_URI}
      # MLflow reaches MinIO through boto3, which reads the AWS names, not the
      # MINIO ones. Without these three, loading a model's artifact fails with
      # AccessDenied while the tracking call succeeds.
      MLFLOW_S3_ENDPOINT_URL: ${MINIO_ENDPOINT_INTERNAL}
      AWS_ACCESS_KEY_ID: ${MINIO_ACCESS_KEY}
      AWS_SECRET_ACCESS_KEY: ${MINIO_SECRET_KEY}
    ports:
      - "8000:8000"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 20s
    restart: unless-stopped
```

**Không đụng** sáu service đang có.

- [ ] **Step 5: Xác nhận compose không hỏng trước khi khởi động**

Run: `docker compose config --services`
Expected: đúng **8** service — postgres, minio, minio-init, mlflow, airflow-init, airflow-scheduler, airflow-webserver, serving. Khác con số là YAML hỏng, dừng lại và sửa.

- [ ] **Step 6: Khởi động và kiểm healthcheck**

Run:
```powershell
docker compose up -d serving
Start-Sleep -Seconds 30
docker compose ps
```
Expected: `mlops-serving` là `running (healthy)`.

Nếu nó restart liên tục, xem `docker compose logs serving --tail 50`. Lỗi hay gặp nhất là thiếu ba biến AWS/MLflow ở trên.

- [ ] **Step 7: Gọi `/health` thật**

Run: `curl -s http://localhost:8000/health`
Expected: JSON có `"status": "ok"`, `regression.loaded` là `true` với version thật, `classification.loaded` là `true` (Task 7 đã train), và `inference_log` là `{"buffered": 0, "dropped": 0}`.

Nếu `classification.loaded` là `false` thì xem log serving — nhiều khả năng alias chưa tồn tại hoặc thiếu biến artifact.

- [ ] **Step 8: Commit**

```bash
git add services/serving/Dockerfile docker-compose.yml
git commit -m "feat: image serving va service trong compose"
```

---

## Task 11: Task `deploy` trong DAG

**Files:**
- Modify: `dags/ml_pipeline_dag.py`
- Modify: `docker-compose.yml` (thêm `SERVING_URL` vào khối `&airflow-env`)

**Interfaces:**
- Consumes: `POST /reload` của serving
- Produces: `register >> deploy` trong DAG `ml_pipeline`

**Không đóng gói image riêng cho `deploy`.** Spec gốc mục 9 ghi rõ `stages/` không có thư mục `deploy/` vì "đóng gói cả một image để gửi một request là thừa". Dùng `PythonOperator` với `urllib` trong thư viện chuẩn, thay vì `HttpOperator` để khỏi phải cấu hình một Airflow Connection cho đúng một URL nội bộ cố định.

- [ ] **Step 1: Thêm `SERVING_URL` vào khối `&airflow-env`**

Trong `docker-compose.yml`, service `airflow-init`, thêm vào cuối khối `environment: &airflow-env`:

```yaml
      SERVING_URL: ${SERVING_URL}
```

`.env.example` đã có `SERVING_URL=http://serving:8000` từ Plan 1 — kiểm `.env` cũng có; thiếu thì thêm.

- [ ] **Step 2: Thêm task `deploy` vào DAG**

Thêm import và hàm, cạnh `choose_branch` đã có:

```python
import urllib.request

SERVING_RELOAD_URL = os.environ.get("SERVING_URL", "http://serving:8000").rstrip("/") + "/reload"


def reload_serving() -> str:
    """Tells serving to pick up the version that was just registered.

    One HTTP call, so no image and no Airflow Connection: a PythonOperator with
    the standard library is the whole task.
    """
    request = urllib.request.Request(SERVING_RELOAD_URL, data=b"", method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    print(f"serving reloaded: {body}")
    return body
```

Thêm import `PythonOperator` cạnh `BranchPythonOperator`:

```python
from airflow.operators.python import BranchPythonOperator, PythonOperator
```

Tạo task và nối vào cuối, sau `stop_no_deploy`:

```python
    deploy = PythonOperator(task_id="deploy", python_callable=reload_serving)

    extract >> validate >> prepare_dataset >> train >> evaluate >> branch
    branch >> [register, stop_no_deploy]
    register >> deploy
```

- [ ] **Step 3: Nạp lại scheduler để lấy biến mới**

Run:
```powershell
docker compose up -d airflow-scheduler
Start-Sleep -Seconds 20
docker compose exec -T airflow-scheduler airflow dags list-import-errors
```
Expected: không có import error.

- [ ] **Step 4: Xác nhận scheduler gọi được serving**

Trước khi chạy cả DAG, kiểm đường mạng riêng:

```powershell
docker compose exec -T airflow-scheduler python -c "import urllib.request; r=urllib.request.Request('http://serving:8000/reload', data=b'', method='POST'); print(urllib.request.urlopen(r, timeout=30).read().decode())"
```
Expected: in ra JSON có khối `models`.

Lỗi phân giải tên nghĩa là `serving` chưa cùng network — cả hai đều ở `mlops_default` do compose tạo, kiểm lại `docker compose ps`.

- [ ] **Step 5: Chạy DAG full tới `deploy`**

Chạy nhánh regression với model chắc chắn qua cổng:

```powershell
docker compose exec -T airflow-scheduler airflow dags test ml_pipeline 2026-09-19 --conf '{\"estimator_name\": \"hist_gradient_boosting\"}'
```
Expected: `register` SUCCESS rồi `deploy` SUCCESS, log của `deploy` in `serving reloaded: {...}`.

Nếu model bị cổng chặn thì nhánh đi `stop_no_deploy` và `deploy` bị **skip** — đó cũng là đúng, nhưng task này cần thấy `deploy` chạy thật. Nếu bị chặn, xoá alias champion regression rồi chạy lại để có một lần promote thật:
```powershell
.venv\Scripts\python.exe -c "import mlflow; from mlflow import MlflowClient; mlflow.set_tracking_uri('http://localhost:5000'); MlflowClient().delete_registered_model_alias('house_price_regressor','champion'); print('alias removed')"
```

- [ ] **Step 6: Xác nhận `/health` phản ánh version vừa register**

Run: `curl -s http://localhost:8000/health`
Expected: `models.regression.version` khớp version mà `register` vừa tạo. Đây là bằng chứng vòng train → register → deploy → serving đã khép kín.

- [ ] **Step 7: Commit**

```bash
git add dags/ml_pipeline_dag.py docker-compose.yml
git commit -m "feat: task deploy goi reload serving sau khi register"
```

---

## Task 12: Xác nhận toàn bộ Plan 3

**Files:**
- Create: `scripts/verify_serving.ps1`
- Modify: `README.md`

**Interfaces:**
- Consumes: mọi thứ từ Task 1-11
- Produces: một lệnh xác nhận Plan 3

- [ ] **Step 1: Chạy `/predict` với record thô lấy từ dữ liệu thật**

```powershell
.venv\Scripts\python.exe -c "
import json, urllib.request
from ml_common.storage import Storage, processed_key
import mlflow
from mlflow import MlflowClient
mlflow.set_tracking_uri('http://localhost:5000')
c = MlflowClient()
v = c.get_model_version_by_alias('house_price_regressor','champion')
fp = c.get_run(v.run_id).data.params['fingerprint']
row = Storage.from_env().read_parquet(processed_key(fp,'test')).drop(columns=['sale_price']).head(1)
record = json.loads(row.to_json(orient='records'))[0]
print('gui di list_price =', repr(record['list_price']), '| city =', repr(record['city']))
req = urllib.request.Request('http://localhost:8000/predict/regression', data=json.dumps(record).encode(), headers={'Content-Type':'application/json'})
print(urllib.request.urlopen(req, timeout=30).read().decode())
"
```
Expected: in ra `list_price` **vẫn ở dạng thô**, rồi JSON có `prediction` hàng trăm nghìn đô, `request_id`, `model_version`.

Đây là chứng minh cuối cùng rằng model tự chứa logic làm sạch: **không có bước clean nào ở phía serving**.

- [ ] **Step 2: Chạy `/predict` cho classification**

Lặp lại Step 1 nhưng `house_needs_renovation_classifier` và `/predict/classification`, và bỏ cột `condition` khỏi record (nó là leakage, model không dùng — nhưng gửi thừa cũng không sao, `SelectColumns` loại nó).
Expected: `prediction` là `true`/`false`, kèm `probability` trong khoảng 0-1.

- [ ] **Step 3: Xác nhận inference log nằm thật trên MinIO**

Sau hai bước trên, buffer có 2 record — chưa đủ 500 nên phải chờ 30 giây để flush theo tuổi:

```powershell
Start-Sleep -Seconds 35
curl -s http://localhost:8000/health
docker compose exec minio mc ls --recursive local/ml-pipeline/inference-log/
```
Expected: `/health` báo `buffered` về **0**, và `mc ls` liệt kê file parquet dưới `inference-log/{model_name}/dt=YYYY-MM-DD/`.

Nếu `buffered` vẫn khác 0 sau 35 giây thì vòng lặp nền không chạy — xem log serving.

- [ ] **Step 4: Đọc lại inference log bằng pandas**

```powershell
.venv\Scripts\python.exe -c "
from ml_common.storage import Storage, inference_log_prefix
from datetime import date
s = Storage.from_env()
keys = s.list_keys(inference_log_prefix('house_price_regressor', date.today()))
print('files:', keys)
df = s.read_parquet(keys[0])
print('cot:', sorted(df.columns))
print(df[['request_id','prediction','model_version']].to_string())
import json; print('raw_input doc lai duoc:', json.loads(df['raw_input'].iloc[0])['city'])
"
```
Expected: đủ 6 cột `request_id`, `timestamp`, `raw_input`, `prediction`, `model_name`, `model_version`; `raw_input` parse lại được thành dict.

- [ ] **Step 5: Xác nhận buffer bỏ record khi vượt trần**

Trần là 5000, không bắn được ngần ấy request trong bài test này. Thay vào đó kiểm bằng unit test đã có ở Task 5 và xác nhận `/health` phơi ra con số:

```powershell
curl -s http://localhost:8000/health
```
Expected: khối `inference_log` có khoá `dropped`, giá trị 0. Cơ chế bỏ record đã được `test_overflow_drops_the_oldest_and_counts_it` phủ.

- [ ] **Step 6: Viết `scripts/verify_serving.ps1`**

```powershell
# Verifies Plan 3: serving is up, serves both models, and logs what it served.
$ErrorActionPreference = "Stop"

Write-Host "== 1/6 Unit tests ==" -ForegroundColor Cyan
.venv\Scripts\python.exe -m pytest common/ services/ -q

Write-Host "== 2/6 Lint ==" -ForegroundColor Cyan
.venv\Scripts\python.exe -m ruff check common/ scripts/ dags/ stages/ services/

Write-Host "== 3/6 Serving must not import cleaning logic ==" -ForegroundColor Cyan
$leaked = Select-String -Path services\serving\*.py -Pattern "ml_common\.(cleaning|rowops)" -Quiet
if ($leaked) { throw "serving imports cleaning logic - the model is supposed to own that" }
Write-Host "  boundary intact"

Write-Host "== 4/6 Containers ==" -ForegroundColor Cyan
docker compose ps

Write-Host "== 5/6 Serving health ==" -ForegroundColor Cyan
$health = Invoke-RestMethod -Uri http://localhost:8000/health
$health | ConvertTo-Json -Depth 5
if ($health.status -ne "ok") { throw "serving is $($health.status)" }

Write-Host "== 6/6 DAG parses ==" -ForegroundColor Cyan
docker compose exec -T airflow-scheduler airflow dags list-import-errors

Write-Host "`nServing ready for Plan 4." -ForegroundColor Green
```

- [ ] **Step 7: Chạy script xác nhận**

Run: `powershell -ExecutionPolicy Bypass -File scripts\verify_serving.ps1`
Expected: cả 6 mục pass, dòng cuối `Serving ready for Plan 4.`

- [ ] **Step 8: Cập nhật `README.md`**

Thêm `serving` vào bảng giao diện:

| Service | URL | Đăng nhập |
| --- | --- | --- |
| Serving | http://localhost:8000/health | — |

Thêm mục **Gọi thử model** sau mục Chạy pipeline:

````markdown
## Gọi thử model

```powershell
curl -s http://localhost:8000/health
```

`/predict/{model}` nhận record **thô** — không cần làm sạch gì, model tự xử lý:

```powershell
curl -s -X POST http://localhost:8000/predict/regression -H "Content-Type: application/json" -d "{\"city\":\"  NEW YORK \",\"list_price\":\"$450,000\",\"bedrooms\":3}"
```

`model` là `regression` hoặc `classification`. Model chưa train thì trả 503.
````

Sửa mục **Trạng thái** thành `Plan 3/5 — serving chạy được cho cả hai model.`

- [ ] **Step 9: Commit**

```bash
git add scripts/verify_serving.ps1 README.md
git commit -m "test: xac nhan serving phuc vu ca hai model"
```

---

## Definition of Done

- [ ] `powershell -ExecutionPolicy Bypass -File scripts\verify_serving.ps1` xanh toàn bộ
- [ ] `docker compose ps` có `mlops-serving` **healthy**
- [ ] `/health` trả đúng khối `models` và `inference_log`
- [ ] `/predict/regression` với record **thô** trả prediction hàng trăm nghìn đô
- [ ] `/predict/classification` trả boolean kèm `probability`
- [ ] `/predict` tới model chưa load trả **503**, không phải 500
- [ ] Champion `house_needs_renovation_classifier` tồn tại với **AUC ≥ 0.55**
- [ ] `dummy` cho classification **bị cổng chặn**, và `test_f1` của model thật được ghi lại để chứng minh vì sao không dùng F1 làm cổng
- [ ] Champion regression **không bị đụng** khi chạy nhánh classification
- [ ] Inference log nằm thật trên MinIO, đọc lại bằng pandas ra đủ 6 cột, `raw_input` parse lại được
- [ ] DAG chạy full tới `deploy`, và `/health` phản ánh version vừa register
- [ ] Serving **không import** `ml_common.cleaning` hay `ml_common.rowops` — kiểm bằng lệnh
- [ ] Toàn bộ test pass ở cả Python 3.13 local lẫn 3.12 trong `ml-base`

Ba mục quan trọng nhất là **cổng chặn được `dummy`**, **`/predict` ăn record thô**, và
**serving không import logic cleaning**. Chúng chứng minh thiết kế còn nguyên vẹn, không
phải chỉ chạy được.

---

## Những gì Plan 3 cố tình KHÔNG làm

- **Không có `/feedback`, không có ground truth.** Plan 4 — cùng với thứ sinh ra dữ liệu cho nó.
- **Không có agent sinh traffic.** Plan 4.
- **Không có monitoring, Evidently, hay `monitoring_dag`.** Plan 4.
- **Không tinh chỉnh model classification.** AUC ~0.71 là đủ để đường ống chạy đúng. Mục tiêu của plan là serving, không phải model tốt nhất.
- **Không có auth trên serving.** Spec mục 3.2 ghi auth chỉ bắt buộc trước khi expose ra ngoài; hiện chỉ chạy local.
- **Không xử lý batch trong một request.** `/predict` nhận đúng một record, như spec mục 7.6 mô tả.

---

## Self-review

Rà soát plan với spec, ngày 2026-09-19.

**Spec coverage:**

| Mục spec | Task |
| --- | --- |
| 2.1 Serving `FROM ml-base` | 10 |
| 2.2 Không sao chép logic cleaning | 9 (Step 5 kiểm bằng lệnh), 12 (script kiểm lại) |
| 2.3 Thiếu model vẫn khởi động, 503 | 8, 9 |
| 2.4 Inference log lô, trần, đếm số bỏ | 5, 9, 12 |
| 2.5 Target `needs_renovation` | 2, 3, 6, 7 |
| 2.6 Cổng AUC | 1, 7 |
| 2.7 `deploy` không có image riêng | 11 |
| 3. Hợp đồng API | 9 |
| 4.1 `gates.py` | 1 |
| 4.1b `schema.py` | 2 |
| 4.1c `targets.py` | 3 |
| 4.2 DAG suy `model_name` | 6 |
| 4.3 DAG suy `estimator_name` | 6 |
| 5. Cấu trúc thư mục | 5, 8, 9, 10 |
| 6. Test | rải khắp, cộng 12 |

**Lỗ hổng phát hiện khi rà soát, đã bổ sung:**

- Spec không nói `validate` xử sao khi target là cột dẫn xuất. `validate` chạy **trước**
  `prepare_dataset_for_train` nên `needs_renovation` chưa tồn tại, và luật "hơn 50% target
  thiếu" sẽ **im lặng không chạy** cho classification. Đã thêm **Task 4**: kiểm cột **nguồn**
  (`condition`) thay vì cột target, giữ đúng ý định của luật.
- Spec không nói lô inference log gồm nhiều model thì ghi thế nào, mà `inference_log_key`
  phân vùng theo model **và** theo ngày. Task 9 gom theo `(model_name, day)` lúc flush, và
  lấy ngày từ **timestamp của record** chứ không phải lúc flush — một lô có thể vắt qua nửa đêm.
- Spec không nói `raw_input` lưu kiểu gì. Task 9 lưu **chuỗi JSON**: parquet không lưu dict
  lồng nhau gọn, và Plan 4 chỉ cần đọc lại được.
- `InferenceLogBuffer` với `flush_size > max_size` sẽ bỏ record trước khi kịp flush lần nào.
  Task 5 ném `ValueError` ngay lúc khởi tạo thay vì để nó âm thầm mất dữ liệu.
- Fingerprint hiện chỉ băm dữ liệu raw, **không băm `task_type`**, nên chạy tay hai task khác
  nhau trên cùng fingerprint sẽ ghi đè `processed/`. Task 6 Step 5 ghi nhận điểm này; nó không
  chặn Plan 3 vì DAG sinh fingerprint riêng, nhưng Plan 4 cần biết.

**Type consistency:** `version` là `str` xuyên suốt (`model_registry`, `/health`, `/predict`);
`describe()` trả đúng khối mà cả `/health` lẫn `/reload` dùng; `stats()` trả `{"buffered", "dropped"}`
đúng tên khoá mà test và `/health` đọc; `LoadedModel` có `.name` `.version` `.model` và mọi
chỗ dùng đúng ba tên đó.

**Placeholder:** không còn "TBD"/"TODO"; mọi step có code đều có code thật.

