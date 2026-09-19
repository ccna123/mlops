# MLOps Foundation Implementation Plan (Plan 1/5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng hạ tầng Docker Compose (Postgres / MinIO / MLflow / Airflow) và package `common/` đã test đủ 8 loại dirty của dataset, làm nền cho 4 plan sau.

**Architecture:** `common/` là một Python package thuần, không phụ thuộc Airflow hay MLflow, được cài bằng `pip install -e` vào cả môi trường test local lẫn mọi image stage. Nó chứa toàn bộ logic hiểu biết về dataset: schema, parser, transformer, wrapper storage, profiling. Các stage ở Plan 2 chỉ là lớp vỏ mỏng gọi vào package này. Hạ tầng dựng bằng một `docker-compose.yml` duy nhất, xây dần qua 4 task cuối, mỗi task thêm một service và có smoke test riêng.

**Tech Stack:** Python 3.11+, pandas, scikit-learn, pyarrow, boto3, pytest, ruff, Docker Compose, PostgreSQL 16, MinIO, MLflow 2.x, Apache Airflow 2.10 (LocalExecutor).

**Spec:** `mlops-pipeline-design.md` (phiên bản 2, commit `6fd7845`)

## Global Constraints

Áp dụng cho mọi task trong plan này.

- **Python:** `common/` khai báo `requires-python = ">=3.11"`. Máy dev chạy Python 3.13, container chạy Python 3.12 (Airflow 2.10 chưa hỗ trợ 3.13). **Không dùng cú pháp chỉ có ở 3.13+.**
- **Không bao giờ train ở môi trường này rồi serve ở môi trường khác.** Model pickle bởi scikit-learn phải được load bởi cùng minor version Python và cùng version scikit-learn. Train và serve đều diễn ra trong container Python 3.12. Môi trường local Python 3.13 chỉ dùng để chạy test logic thuần.
- **Phân biệt thao tác theo dòng và thao tác theo cột.** Đây là ràng buộc kiến trúc quan trọng nhất của plan:
  - *Thao tác theo cột* (parse, normalize, clip, impute, encode) → nằm trong sklearn `Pipeline`, được đóng gói cùng model, dùng chung giữa `preprocess` và serving.
  - *Thao tác theo dòng* (drop duplicate, loại bỏ dòng không hợp lệ) → **chỉ** nằm ở stage `preprocess`, tuyệt đối không đưa vào `Pipeline`. Lý do: `/predict` nhận một record đơn lẻ, một transformer xoá dòng sẽ trả về DataFrame rỗng và làm serving sập.
- **Pin version:** `pandas>=2.2,<3`, `scikit-learn>=1.5,<2`, `pyarrow>=16`, `boto3>=1.34`, `numpy>=1.26,<3`.
- **Chuẩn hoá text:** mọi giá trị categorical được chuẩn hoá về **chữ thường, dấu cách đơn, không khoảng trắng đầu/cuối**, gạch dưới và gạch nối đổi thành dấu cách. `"Multi-Family"`, `"MULTI FAMILY"`, `"multi_family"` đều ra `"multi family"`.
- **Giá trị thiếu:** dùng `None` / `np.nan`, không dùng chuỗi rỗng hay sentinel như `-1`.
- **Đường dẫn MinIO:** chỉ được tạo qua hàm trong `ml_common/storage.py`, không nối chuỗi thủ công ở bất kỳ đâu.
- **Encoding file:** mọi file text ghi bằng UTF-8, không BOM.
- **Commit:** mỗi task kết thúc bằng đúng một commit. Message tiếng Việt, theo Conventional Commits (`feat:`, `test:`, `chore:`, `docs:`).
- **Dung lượng đĩa:** ổ C còn ~16GB (đo ngày 2026-09-19, sau khi Plan 1 pull hết image). Trước mỗi task pull image, kiểm tra còn tối thiểu 8GB trống.

---

## Ánh xạ Task → Agent → Skill

13 task chỉ có 3 quy trình thật sự khác nhau, nên chúng dùng chung 2 agent và
3 skill thay vì mỗi task một bộ.

| Task | Nội dung                 | Agent                  | Skill                   |
| ---- | ------------------------- | ---------------------- | ----------------------- |
| 1    | Scaffolding và tooling   | — (chạy trực tiếp) | —                      |
| 2    | `schema.py`             | `mlops-tdd`          | `mlops-tdd-module`    |
| 3    | `parsers.py`            | `mlops-tdd`          | `mlops-tdd-module`    |
| 4    | `cleaning.py`           | `mlops-tdd`          | `mlops-tdd-module`    |
| 5    | `rowops.py`             | `mlops-tdd`          | `mlops-tdd-module`    |
| 6    | `features.py`           | `mlops-tdd`          | `mlops-tdd-module`    |
| 7    | Postgres + MinIO          | `mlops-infra`        | `mlops-infra-service` |
| 8    | `storage.py`            | `mlops-tdd`          | `mlops-tdd-module`    |
| 9    | `profiling.py`          | `mlops-tdd`          | `mlops-tdd-module`    |
| 10   | MLflow                    | `mlops-infra`        | `mlops-infra-service` |
| 11   | Airflow                   | `mlops-infra`        | `mlops-infra-service` |
| 12   | Image nền`ml-base`     | `mlops-infra`        | `mlops-infra-service` |
| 13   | Tài liệu và xác nhận | — (chạy trực tiếp) | `mlops-verify`        |

Task 1 và 13 chạy trực tiếp, không qua subagent: Task 1 dựng chính cái môi
trường mà mọi subagent sau đó cần, còn Task 13 cần nhìn toàn cảnh cả 12 task
trước nên context trống không giúp được gì.

Prompt dispatch cho subagent phải nêu rõ số task, ví dụ:

> Thực thi Task 3 của Plan 1 (`parsers.py`). Đọc `CLAUDE.md` và mục `## Task 3`
> trong `docs/superpowers/plans/2026-09-17-foundation.md` trước khi viết code.

Định nghĩa agent nằm ở `.claude/agents/`, skill ở `.claude/skills/`. Chúng được
commit cùng repo nên ai clone về cũng có.

---

## File Structure

| File                                   | Trách nhiệm                                                                                                                 |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `common/pyproject.toml`              | Khai báo package`ml_common`, dependency, cấu hình pytest + ruff                                                          |
| `common/ml_common/schema.py`         | Nguồn sự thật duy nhất về cột, kiểu, ràng buộc, cột leakage. Không import pandas ở mức module.                   |
| `common/ml_common/parsers.py`        | Hàm parse thuần cho từng giá trị đơn lẻ (tiền, bool, ngày, zipcode, text). Không biết gì về pandas hay sklearn. |
| `common/ml_common/cleaning.py`       | Các sklearn transformer áp parser lên DataFrame theo cột. Chỉ thao tác theo cột.                                       |
| `common/ml_common/rowops.py`         | Thao tác theo dòng (dedup, loại dòng hỏng). Tách riêng để không ai vô tình đưa vào Pipeline.                   |
| `common/ml_common/features.py`       | Dựng`Pipeline` hoàn chỉnh theo `task_type`                                                                             |
| `common/ml_common/storage.py`        | Wrapper boto3 + toàn bộ convention đường dẫn MinIO/S3                                                                   |
| `common/ml_common/profiling.py`      | Tính baseline profile từ DataFrame                                                                                          |
| `common/tests/`                      | Test cho từng module trên                                                                                                   |
| `docker-compose.yml`                 | Postgres, MinIO, MLflow, Airflow                                                                                              |
| `docker/postgres/init-databases.sql` | Tạo database`mlflow` bên cạnh `airflow`                                                                                |
| `docker/mlflow/Dockerfile`           | MLflow + psycopg2 + boto3                                                                                                     |
| `stages/base/Dockerfile`             | Image nền cho mọi stage: Python 3.12 + ml_common                                                                            |
| `.env.example`                       | Mẫu biến môi trường                                                                                                      |

Lý do tách `parsers.py` khỏi `cleaning.py`: parser là hàm thuần trên giá trị đơn lẻ, test được bằng bảng tham số, không cần dựng DataFrame. Transformer là lớp bọc pandas/sklearn quanh chúng. Gộp hai thứ vào một file sẽ tạo ra một file vừa lớn vừa khó test.

Lý do tách `rowops.py`: làm cho ràng buộc "không thao tác dòng trong Pipeline" trở thành ranh giới file, không chỉ là một quy ước trong đầu.

---

## Task 1: Scaffolding và tooling

**Files:**

- Create: `common/pyproject.toml`
- Create: `common/ml_common/__init__.py`
- Create: `common/tests/__init__.py`
- Create: `.env.example`
- Create: `.pre-commit-config.yaml`
- Modify: `.gitignore`

**Interfaces:**

- Consumes: không có (task đầu tiên)
- Produces: package `ml_common` cài được bằng `pip install -e common[dev]`; lệnh `pytest` và `ruff` chạy được từ thư mục gốc.

- [ ] **Step 1: Tạo `common/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "ml-common"
version = "0.1.0"
description = "Shared logic for the MLOps house pricing pipeline"
requires-python = ">=3.11"
dependencies = [
    "pandas>=2.2,<3",
    "numpy>=1.26,<3",
    "scikit-learn>=1.5,<2",
    "pyarrow>=16",
    "boto3>=1.34",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "ruff>=0.6",
    "moto[s3]>=5.0",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["ml_common*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --strict-markers"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 2: Tạo package rỗng và thư mục test**

```bash
mkdir -p common/ml_common common/tests
printf '"""Shared logic for the MLOps house pricing pipeline."""\n\n__version__ = "0.1.0"\n' > common/ml_common/__init__.py
touch common/tests/__init__.py
```

- [ ] **Step 3: Tạo virtualenv và cài package**

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e "common[dev]"
```

Không cần `Activate.ps1` — gọi thẳng `.venv\Scripts\python.exe` để tránh vướng execution policy của PowerShell.

- [ ] **Step 4: Xác nhận cài đặt thành công**

Run: `.venv\Scripts\python.exe -c "import ml_common; print(ml_common.__version__)"`
Expected: in ra `0.1.0`

- [ ] **Step 5: Tạo `.env.example`**

```bash
# MinIO / S3
MINIO_ENDPOINT=http://localhost:9000
MINIO_ENDPOINT_INTERNAL=http://minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
ML_BUCKET=ml-pipeline

# PostgreSQL
POSTGRES_USER=mlops
POSTGRES_PASSWORD=mlops
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# MLflow
MLFLOW_TRACKING_URI=http://mlflow:5000
MLFLOW_TRACKING_URI_LOCAL=http://localhost:5000

# Airflow
AIRFLOW_UID=50000
AIRFLOW_ADMIN_USER=admin
AIRFLOW_ADMIN_PASSWORD=admin

# Serving (used from Plan 3)
SERVING_URL=http://serving:8000

# Dev: limits how many rows are read from raw data. Empty = read all ~2M rows.
# On a 16GB RAM machine, set 200000 while developing; remove it for real runs.
SAMPLE_ROWS=200000
```

- [ ] **Step 6: Cập nhật `.gitignore`**

```bash
cat >> .gitignore <<'EOF'
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
.env
logs/
EOF
```

- [ ] **Step 7: Tạo `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: [--maxkb=5000]
```

- [ ] **Step 8: Commit**

```bash
git add common/ .env.example .pre-commit-config.yaml .gitignore
git commit -m "chore: scaffolding package ml_common va tooling"
```

---

## Task 2: `schema.py` — định nghĩa dataset

**Files:**

- Create: `common/ml_common/schema.py`
- Test: `common/tests/test_schema.py`

**Interfaces:**

- Consumes: không có
- Produces:
  - `ColumnSpec` dataclass với thuộc tính `name: str`, `kind: str`, `required: bool`, `min_value: float | None`, `max_value: float | None`, `allowed: tuple[str, ...] | None`
  - `COLUMNS: dict[str, ColumnSpec]` — 24 cột
  - `TARGET_REGRESSION: str = "sale_price"`, `TARGET_CLASSIFICATION: str = "sold_within_30_days"`, `ID_COLUMN: str = "property_id"`
  - `feature_columns(task_type: str) -> list[str]`
  - `columns_of_kind(kind: str) -> list[str]`
  - `target_column(task_type: str) -> str`
  - `TASK_TYPES: tuple[str, str] = ("regression", "classification")`

- [ ] **Step 1: Viết test thất bại**

Tạo `common/tests/test_schema.py`:

```python
import pytest

from ml_common import schema


def test_has_24_columns():
    assert len(schema.COLUMNS) == 24


def test_every_column_has_valid_kind():
    valid_kinds = {"id", "numeric", "categorical", "boolean", "date", "money", "zipcode"}
    for name, spec in schema.COLUMNS.items():
        assert spec.kind in valid_kinds, f"{name} has invalid kind: {spec.kind}"


def test_regression_excludes_leakage_columns_and_list_price():
    cols = schema.feature_columns("regression")
    assert "sale_price" not in cols, "target must not be a feature"
    assert "price_category" not in cols, "price_category is derived from sale_price"
    assert "list_price" not in cols, "list_price would make the task trivial"
    assert "days_on_market" in cols, "days_on_market is valid for the regression task"


def test_classification_excludes_leakage_columns_but_keeps_list_price():
    cols = schema.feature_columns("classification")
    assert "sold_within_30_days" not in cols
    assert "days_on_market" not in cols, "sold_within_30_days is derived directly from this"
    assert "sale_price" not in cols, "only known after the sale"
    assert "price_category" not in cols
    assert "list_price" in cols, "asking price is known before the sale, a valid signal"


def test_id_column_never_in_features():
    for task in ("regression", "classification"):
        assert schema.ID_COLUMN not in schema.feature_columns(task)


def test_invalid_task_type_raises():
    with pytest.raises(ValueError, match="task_type"):
        schema.feature_columns("clustering")


def test_columns_of_kind_returns_correct_columns():
    assert set(schema.columns_of_kind("money")) == {"list_price", "sale_price"}
    assert set(schema.columns_of_kind("boolean")) == {"has_pool", "sold_within_30_days"}
    assert schema.columns_of_kind("date") == ["listing_date"]


def test_numeric_bounds_are_sensible():
    assert schema.COLUMNS["bedrooms"].min_value == 0
    assert schema.COLUMNS["bedrooms"].max_value == 20
    assert schema.COLUMNS["school_rating"].min_value == 1
    assert schema.COLUMNS["school_rating"].max_value == 10
    assert schema.COLUMNS["distance_to_city_center_km"].min_value == 0


def test_year_built_max_is_current_year():
    from datetime import date

    assert schema.COLUMNS["year_built"].max_value == date.today().year


def test_allowed_values_are_already_normalized():
    for name, spec in schema.COLUMNS.items():
        if spec.allowed is None:
            continue
        for value in spec.allowed:
            assert value == value.strip().lower(), f"{name}: {value!r} not normalized"
            assert "_" not in value and "-" not in value, f"{name}: {value!r} still has a separator"
```

- [ ] **Step 2: Chạy test để xác nhận nó thất bại**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_schema.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.schema'`

- [ ] **Step 3: Viết `common/ml_common/schema.py`**

```python
"""Single source of truth for the house pricing dataset schema.

Used by the `validate` stage (checking raw data) and by serving (checking
records sent to /predict). Does not import pandas at module level, so this
file stays lightweight and importable from anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

TARGET_REGRESSION = "sale_price"
TARGET_CLASSIFICATION = "sold_within_30_days"
ID_COLUMN = "property_id"

TASK_TYPES = ("regression", "classification")


@dataclass(frozen=True)
class ColumnSpec:
    """Describes one column: its logical data kind and valid-value constraints."""

    name: str
    kind: str
    required: bool = False
    min_value: float | None = None
    max_value: float | None = None
    allowed: tuple[str, ...] | None = None


_CURRENT_YEAR = date.today().year

_SPECS = [
    ColumnSpec("property_id", "id", required=True),
    ColumnSpec("listing_date", "date"),
    ColumnSpec("city", "categorical"),
    ColumnSpec("state", "categorical"),
    ColumnSpec("zipcode", "zipcode"),
    ColumnSpec(
        "property_type",
        "categorical",
        allowed=("single family", "condo", "townhouse", "multi family", "land"),
    ),
    ColumnSpec("lot_size_sqft", "numeric", min_value=0, max_value=1_000_000),
    ColumnSpec("living_area_sqft", "numeric", min_value=0, max_value=50_000),
    ColumnSpec("bedrooms", "numeric", min_value=0, max_value=20),
    ColumnSpec("bathrooms", "numeric", min_value=0, max_value=15),
    ColumnSpec("year_built", "numeric", min_value=1800, max_value=_CURRENT_YEAR),
    ColumnSpec("stories", "numeric", min_value=0, max_value=5),
    ColumnSpec("garage_spaces", "numeric", min_value=0, max_value=6),
    ColumnSpec("has_pool", "boolean"),
    ColumnSpec("hoa_fee_monthly", "numeric", min_value=0, max_value=5_000),
    ColumnSpec("school_rating", "numeric", min_value=1, max_value=10),
    ColumnSpec("crime_index", "numeric", min_value=0, max_value=100),
    ColumnSpec("distance_to_city_center_km", "numeric", min_value=0, max_value=200),
    ColumnSpec(
        "condition",
        "categorical",
        allowed=("poor", "fair", "good", "excellent"),
    ),
    ColumnSpec("days_on_market", "numeric", min_value=0, max_value=3_650),
    ColumnSpec("list_price", "money", min_value=0),
    ColumnSpec("sale_price", "money", min_value=0),
    ColumnSpec(
        "price_category",
        "categorical",
        allowed=("low", "medium", "high", "luxury"),
    ),
    ColumnSpec("sold_within_30_days", "boolean"),
]

COLUMNS: dict[str, ColumnSpec] = {spec.name: spec for spec in _SPECS}

# Columns excluded from features, per task. See section 5 of the design doc
# for the reasoning behind each one.
_EXCLUDED: dict[str, frozenset[str]] = {
    "regression": frozenset(
        {
            ID_COLUMN,
            TARGET_REGRESSION,
            "price_category",  # derived directly from sale_price
            "list_price",  # temporally valid but makes the task trivial
        }
    ),
    "classification": frozenset(
        {
            ID_COLUMN,
            TARGET_CLASSIFICATION,
            "days_on_market",  # sold_within_30_days is derived directly from this
            "sale_price",  # only known after the sale
            "price_category",  # derived from sale_price
        }
    ),
}


def feature_columns(task_type: str) -> list[str]:
    """List of columns usable as features for a task, leakage already excluded."""
    if task_type not in TASK_TYPES:
        raise ValueError(f"task_type must be one of {TASK_TYPES}, got: {task_type!r}")
    excluded = _EXCLUDED[task_type]
    return [name for name in COLUMNS if name not in excluded]


def columns_of_kind(kind: str) -> list[str]:
    """List of columns of a given logical kind, in declaration order."""
    return [name for name, spec in COLUMNS.items() if spec.kind == kind]


def target_column(task_type: str) -> str:
    """Name of the target column for a task."""
    if task_type not in TASK_TYPES:
        raise ValueError(f"task_type must be one of {TASK_TYPES}, got: {task_type!r}")
    return TARGET_REGRESSION if task_type == "regression" else TARGET_CLASSIFICATION
```

- [ ] **Step 4: Chạy test để xác nhận nó pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_schema.py -v`
Expected: PASS toàn bộ 10 test

- [ ] **Step 5: Commit**

```bash
git add common/ml_common/schema.py common/tests/test_schema.py
git commit -m "feat: dinh nghia schema dataset house pricing"
```

---

## Task 3: `parsers.py` — hàm parse giá trị đơn lẻ

Đây là task quan trọng nhất của plan. Mọi loại dirty trong dataset đều được xử lý ở đây, và mọi bug ở đây sẽ âm thầm làm hỏng cả model lẫn serving.

**Files:**

- Create: `common/ml_common/parsers.py`
- Test: `common/tests/test_parsers.py`

**Interfaces:**

- Consumes: không có
- Produces:
  - `parse_money(value: object) -> float | None`
  - `parse_bool(value: object) -> bool | None`
  - `parse_date(value: object) -> datetime.date | None`
  - `parse_zipcode(value: object) -> str | None`
  - `normalize_text(value: object) -> str | None`

- [ ] **Step 1: Viết test thất bại**

Tạo `common/tests/test_parsers.py`:

```python
from datetime import date

import numpy as np
import pytest

from ml_common import parsers


# --- Dirty type 6: mixed plain numbers and "$xxx,xxx" strings ---

@pytest.mark.parametrize(
    "input,expected",
    [
        ("$450,000", 450000.0),
        ("$1,250,000", 1250000.0),
        ("$999", 999.0),
        ("450000", 450000.0),
        (450000, 450000.0),
        (450000.75, 450000.75),
        ("  $450,000  ", 450000.0),
        ("$450,000.50", 450000.50),
    ],
)
def test_parse_money_with_multiple_input_format(input, expected):
    assert parsers.parse_money(input) == expected


@pytest.mark.parametrize("input", [None, "", "   ", np.nan, "Not number", "$"])
def test_parse_money_invalid_input_expect_return_none(input):
    assert parsers.parse_money(input) is None


# --- Dirty type 4: has_pool has 8 different representations ---

@pytest.mark.parametrize(
    "input,expected",
    [
        ("Yes", True), ("No", False),
        ("Y", True), ("N", False),
        ("1", True), ("0", False),
        ("True", True), ("False", False),
        ("yes", True), ("NO", False),
        ("  Y  ", True),
        (1, True), (0, False),
        (True, True), (False, False),
        (1.0, True), (0.0, False),
    ],
)
def test_parse_bool_every_representation(input, expected):
    assert parsers.parse_bool(input) is expected


@pytest.mark.parametrize("input", [None, "", "   ", np.nan, "maybe", "2"])
def test_parse_bool_invalid_input_expect_return_none(input):
    assert parsers.parse_bool(input) is None


# --- Dirty type 5: listing_date has 3 formats ---

@pytest.mark.parametrize(
    "input,expected",
    [
        ("2023-07-15", date(2023, 7, 15)),
        ("07/15/2023", date(2023, 7, 15)),
        ("15-Jul-2023", date(2023, 7, 15)),
        ("  2023-07-15  ", date(2023, 7, 15)),
        ("01/02/2023", date(2023, 1, 2)),  # MM/DD, not DD/MM
        ("03-Mar-2020", date(2020, 3, 3)),
    ],
)
def test_parse_date_three_formats(input, expected):
    assert parsers.parse_date(input) == expected


@pytest.mark.parametrize("input", [None, "", "   ", np.nan, "not a date", "2023-13-45"])
def test_parse_date_invalid_input_expect_return_none(input):
    assert parsers.parse_date(input) is None


def test_parse_date_accepts_existing_date_object():
    assert parsers.parse_date(date(2023, 7, 15)) == date(2023, 7, 15)


# --- Dirty type 8: zipcode missing or truncated to 4 digits ---

@pytest.mark.parametrize(
    "input,expected",
    [
        ("90210", "90210"),
        ("  90210  ", "90210"),
        (90210, "90210"),
        ("02134", "02134"),  # leading 0 must not be lost
    ],
)
def test_parse_zipcode_valid_input(input, expected):
    assert parsers.parse_zipcode(input) == expected


@pytest.mark.parametrize("input", [None, "", "9021", "902101", "abcde", np.nan, 9021])
def test_parse_zipcode_invalid_format_expect_return_none(input):
    assert parsers.parse_zipcode(input) is None


def test_parse_zipcode_integer_with_lost_leading_zero_is_not_recovered():
    # 2134 in the CSV is very likely 02134 with its leading zero stripped by Excel.
    # We do NOT guess: return None so validate can count and report it.
    assert parsers.parse_zipcode(2134) is None


# --- Dirty type 3: categorical mixing upper/lower case and separators ---

@pytest.mark.parametrize(
    "input,expected",
    [
        ("NEW YORK", "new york"),
        ("new york", "new york"),
        ("New_York", "new york"),
        ("  New York  ", "new york"),
        ("New-York", "new york"),
        ("SINGLE FAMILY", "single family"),
        ("Single_Family", "single family"),
        ("Multi-Family", "multi family"),
        ("MULTI FAMILY", "multi family"),
        ("multi_family", "multi family"),
        ("New   York", "new york"),  # multiple spaces -> one
        ("CA", "ca"),
    ],
)
def test_normalize_text(input, expected):
    assert parsers.normalize_text(input) == expected


@pytest.mark.parametrize("input", [None, "", "   ", np.nan])
def test_normalize_text_empty_input_expect_return_none(input):
    assert parsers.normalize_text(input) is None


def test_every_multi_family_variant_normalizes_to_the_same_value():
    variants = ["Multi-Family", "MULTI FAMILY", "multi_family", "  Multi Family  "]
    result = {parsers.normalize_text(v) for v in variants}
    assert result == {"multi family"}
```

- [ ] **Step 2: Chạy test để xác nhận nó thất bại**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_parsers.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.parsers'`

- [ ] **Step 3: Viết `common/ml_common/parsers.py`**

```python
"""Parse functions for individual raw values.

Each function takes an arbitrary value (string, number, None, NaN) and
returns a normalized value, or None if it could not be parsed. Never raises
an exception and never guesses: an ambiguous value returns None so the
`validate` stage can count and report it.

This module does not import pandas or sklearn — just pure functions, tested
with parametrized tables.
"""

from __future__ import annotations

import re
from datetime import date, datetime

_MONEY_NOISE_CHARS = re.compile(r"[$,\s]")
_ONLY_DIGITS = re.compile(r"^-?\d+(\.\d+)?$")
_VALID_ZIPCODE = re.compile(r"^\d{5}$")
_EXTRA_SPACES = re.compile(r"\s+")

_BOOL_TRUE = {"yes", "y", "1", "true", "t"}
_BOOL_FALSE = {"no", "n", "0", "false", "f"}

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y")


def _is_empty(value: object) -> bool:
    """True if the value counts as missing: None, NaN, empty or whitespace-only string."""
    if value is None:
        return True
    # NaN is the only float that doesn't equal itself.
    if isinstance(value, float) and value != value:
        return True
    return isinstance(value, str) and not value.strip()


def parse_money(value: object) -> float | None:
    """Parse a money amount: '$450,000' -> 450000.0. Returns None if unparseable.

    Handles dirty type 6: the same column mixes plain numbers with
    currency-formatted strings.
    """
    if _is_empty(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _MONEY_NOISE_CHARS.sub("", str(value))
    if not _ONLY_DIGITS.match(text):
        return None
    return float(text)


def parse_bool(value: object) -> bool | None:
    """Parse a boolean from 8 possible representations. Returns None if unparseable.

    Handles dirty type 4: has_pool has Yes/No/Y/N/1/0/True/False.
    """
    if _is_empty(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    text = str(value).strip().lower()
    if text in _BOOL_TRUE:
        return True
    if text in _BOOL_FALSE:
        return False
    return None


def parse_date(value: object) -> date | None:
    """Parse a date from 3 mixed formats. Returns None if unparseable.

    Handles dirty type 5: YYYY-MM-DD, MM/DD/YYYY, DD-Mon-YYYY.
    Tries each format in turn instead of using dateutil: much faster over
    2 million rows, and never mistakes DD/MM for MM/DD.
    """
    if _is_empty(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_zipcode(value: object) -> str | None:
    """Parse a 5-digit zipcode. Returns None if missing or badly formatted.

    Handles dirty type 8. A 4-digit zipcode returns None instead of guessing
    a leading zero: guessing would silently produce wrong data, while None
    lets the `validate` stage count and report it.
    """
    if _is_empty(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if value != int(value):
            return None
        value = int(value)
    text = str(value).strip()
    if not _VALID_ZIPCODE.match(text):
        return None
    return text


def normalize_text(value: object) -> str | None:
    """Normalize a categorical value to lowercase, single spaces.

    Handles dirty type 3: 'NEW YORK', 'new_york', 'New-York', '  New York  '
    all normalize to 'new york'. Underscores and hyphens become spaces so
    every variant of 'Multi-Family' converges to the same value.
    """
    if _is_empty(value):
        return None
    text = str(value).strip().lower()
    text = text.replace("_", " ").replace("-", " ")
    text = _EXTRA_SPACES.sub(" ", text).strip()
    return text or None
```

- [ ] **Step 4: Chạy test để xác nhận nó pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_parsers.py -v`
Expected: PASS toàn bộ (khoảng 70 test case nhờ `parametrize`)

- [ ] **Step 5: Chạy ruff**

Run: `.venv\Scripts\python.exe -m ruff check common/ --fix`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add common/ml_common/parsers.py common/tests/test_parsers.py
git commit -m "feat: parser cho 5 loai dirty o muc gia tri don le"
```

---

## Task 4: `cleaning.py` — transformer theo cột

**Files:**

- Create: `common/ml_common/cleaning.py`
- Test: `common/tests/test_cleaning.py`

**Interfaces:**

- Consumes: `ml_common.parsers` (Task 3), `ml_common.schema` (Task 2)
- Produces:
  - `RawRecordCleaner(BaseEstimator, TransformerMixin)` — `.fit(X, y=None) -> self`, `.transform(X: pd.DataFrame) -> pd.DataFrame`
  - `OutlierClipper(BaseEstimator, TransformerMixin)` — `.fit(X, y=None) -> self`, `.transform(X: pd.DataFrame) -> pd.DataFrame`
  - `DateFeatures(BaseEstimator, TransformerMixin)` — `.fit(X, y=None) -> self`, `.transform(X: pd.DataFrame) -> pd.DataFrame`

Cả ba đều **chỉ thao tác theo cột**, không bao giờ xoá dòng. Xem Global Constraints.

- [ ] **Step 1: Viết test thất bại**

Tạo `common/tests/test_cleaning.py`:

```python
import numpy as np
import pandas as pd
import pytest

from ml_common import cleaning


@pytest.fixture
def dirty_df():
    """A small DataFrame covering every dirty type."""
    return pd.DataFrame(
        {
            "property_id": [1, 2, 3],
            "listing_date": ["2023-07-15", "07/15/2023", "15-Jul-2023"],
            "city": ["NEW YORK", "new_york", "  New York  "],
            "state": ["NY", "ny", "Ny"],
            "zipcode": ["10001", "1000", None],
            "property_type": ["Single_Family", "MULTI FAMILY", "Multi-Family"],
            "living_area_sqft": [1500.0, 2000.0, 45000.0],
            "bedrooms": [3.0, -1.0, 25.0],
            "bathrooms": [2.0, 1.5, 50.0],
            "year_built": [1990.0, 2055.0, 1750.0],
            "has_pool": ["Yes", "N", "1"],
            "condition": ["Good", "EXCELLENT", "poor"],
            "distance_to_city_center_km": [5.0, -3.0, 10.0],
            "list_price": ["$450,000", 500000, "$1,250,000"],
            "sale_price": [440000, "$490,000", 1200000],
        }
    )


class TestRawRecordCleaner:
    def test_never_drops_rows(self, dirty_df):
        result = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        assert len(result) == len(dirty_df)

    def test_works_with_a_single_row(self, dirty_df):
        """Serving calls /predict with one record — this must work."""
        one_row = dirty_df.head(1)
        result = cleaning.RawRecordCleaner().fit_transform(one_row)
        assert len(result) == 1

    def test_parses_money_columns(self, dirty_df):
        result = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        assert result["list_price"].tolist() == [450000.0, 500000.0, 1250000.0]
        assert result["sale_price"].tolist() == [440000.0, 490000.0, 1200000.0]

    def test_normalizes_categorical_columns(self, dirty_df):
        result = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        assert result["city"].tolist() == ["new york", "new york", "new york"]
        assert result["state"].tolist() == ["ny", "ny", "ny"]
        assert result["property_type"].tolist() == [
            "single family",
            "multi family",
            "multi family",
        ]

    def test_parses_boolean_columns(self, dirty_df):
        result = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        assert result["has_pool"].tolist() == [True, False, True]

    def test_invalid_zipcode_becomes_none(self, dirty_df):
        result = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        assert result["zipcode"].tolist() == ["10001", None, None]

    def test_three_date_formats_parse_to_the_same_date(self, dirty_df):
        result = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        parsed = pd.to_datetime(result["listing_date"])
        assert parsed.nunique() == 1

    def test_does_not_mutate_the_input_dataframe(self, dirty_df):
        original_copy = dirty_df.copy(deep=True)
        cleaning.RawRecordCleaner().fit_transform(dirty_df)
        pd.testing.assert_frame_equal(dirty_df, original_copy)

    def test_missing_column_is_skipped_without_raising(self):
        """Serving may receive a record missing an optional column."""
        df = pd.DataFrame({"city": ["NEW YORK"], "list_price": ["$100,000"]})
        result = cleaning.RawRecordCleaner().fit_transform(df)
        assert result["city"].tolist() == ["new york"]
        assert result["list_price"].tolist() == [100000.0]

    def test_column_outside_schema_is_left_untouched(self):
        df = pd.DataFrame({"city": ["NEW YORK"], "extra_column": [42]})
        result = cleaning.RawRecordCleaner().fit_transform(df)
        assert result["extra_column"].tolist() == [42]


class TestOutlierClipper:
    def test_clips_to_schema_bounds(self, dirty_df):
        cleaned = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        result = cleaning.OutlierClipper().fit_transform(cleaned)
        # bedrooms: -1 -> 0, 25 -> 20
        assert result["bedrooms"].tolist() == [3.0, 0.0, 20.0]
        # bathrooms: 50 -> 15
        assert result["bathrooms"].tolist() == [2.0, 1.5, 15.0]
        # distance: -3 -> 0
        assert result["distance_to_city_center_km"].tolist() == [5.0, 0.0, 10.0]

    def test_future_build_year_is_clipped(self, dirty_df):
        from datetime import date

        cleaned = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        result = cleaning.OutlierClipper().fit_transform(cleaned)
        assert result["year_built"].max() <= date.today().year
        assert result["year_built"].min() >= 1800

    def test_abnormal_area_is_clipped(self, dirty_df):
        cleaned = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        result = cleaning.OutlierClipper().fit_transform(cleaned)
        assert result["living_area_sqft"].max() <= 50_000

    def test_does_not_drop_rows(self, dirty_df):
        cleaned = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        result = cleaning.OutlierClipper().fit_transform(cleaned)
        assert len(result) == len(dirty_df)

    def test_missing_value_stays_missing_after_clip(self):
        df = pd.DataFrame({"bedrooms": [np.nan, 3.0]})
        result = cleaning.OutlierClipper().fit_transform(df)
        assert pd.isna(result["bedrooms"].iloc[0])


class TestDateFeatures:
    def test_splits_year_and_month(self, dirty_df):
        cleaned = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        result = cleaning.DateFeatures().fit_transform(cleaned)
        assert result["listing_year"].tolist() == [2023, 2023, 2023]
        assert result["listing_month"].tolist() == [7, 7, 7]

    def test_drops_the_original_date_column(self, dirty_df):
        cleaned = cleaning.RawRecordCleaner().fit_transform(dirty_df)
        result = cleaning.DateFeatures().fit_transform(cleaned)
        assert "listing_date" not in result.columns

    def test_missing_date_becomes_nan_without_raising(self):
        df = pd.DataFrame({"listing_date": [None, pd.Timestamp("2023-07-15")]})
        result = cleaning.DateFeatures().fit_transform(df)
        assert pd.isna(result["listing_year"].iloc[0])
        assert result["listing_year"].iloc[1] == 2023
```

- [ ] **Step 2: Chạy test để xác nhận nó thất bại**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_cleaning.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.cleaning'`

- [ ] **Step 3: Viết `common/ml_common/cleaning.py`**

```python
"""Data-cleaning transformers — column-wise ONLY.

The transformers here live inside a sklearn Pipeline and get packaged with
the model into MLflow, so they run in BOTH places: the `preprocess` stage
(over 2 million rows) and serving (over a single record).

That means they must NEVER drop rows. Row-wise operations live in
`rowops.py`. See the plan's Global Constraints.
"""

from __future__ import annotations

import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

from ml_common import parsers, schema

_PARSER_BY_KIND = {
    "money": parsers.parse_money,
    "boolean": parsers.parse_bool,
    "date": parsers.parse_date,
    "zipcode": parsers.parse_zipcode,
    "categorical": parsers.normalize_text,
}


class RawRecordCleaner(BaseEstimator, TransformerMixin):
    """Applies the matching parser to each column, based on its `kind` in the schema.

    Columns not in the schema are left untouched. Columns in the schema but
    absent from the DataFrame are skipped — serving may receive a record
    missing an optional column.
    """

    def fit(self, X: pd.DataFrame, y=None) -> RawRecordCleaner:  # noqa: N803
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        result = X.copy()
        for column_name, spec in schema.COLUMNS.items():
            if column_name not in result.columns:
                continue
            parser = _PARSER_BY_KIND.get(spec.kind)
            if parser is None:
                continue
            result[column_name] = [parser(value) for value in result[column_name]]
        return result


class OutlierClipper(BaseEstimator, TransformerMixin):
    """Clips numeric values into the schema's [min_value, max_value] range.

    Clipping is chosen over dropping rows for two reasons: serving can't
    drop rows, and a house with `bedrooms = -1` still has useful information
    in its other columns. Missing values stay missing.
    """

    def fit(self, X: pd.DataFrame, y=None) -> OutlierClipper:  # noqa: N803
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        result = X.copy()
        for column_name, spec in schema.COLUMNS.items():
            if column_name not in result.columns:
                continue
            if spec.min_value is None and spec.max_value is None:
                continue
            numeric = pd.to_numeric(result[column_name], errors="coerce")
            result[column_name] = numeric.clip(lower=spec.min_value, upper=spec.max_value)
        return result


class DateFeatures(BaseEstimator, TransformerMixin):
    """Turns `listing_date` into `listing_year` + `listing_month`.

    Tree models can't use a datetime dtype directly, and year/month are two
    signals with real-world meaning (market cycles, peak season).
    """

    def fit(self, X: pd.DataFrame, y=None) -> DateFeatures:  # noqa: N803
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        result = X.copy()
        if "listing_date" not in result.columns:
            return result
        parsed = pd.to_datetime(result["listing_date"], errors="coerce")
        result["listing_year"] = parsed.dt.year
        result["listing_month"] = parsed.dt.month
        return result.drop(columns=["listing_date"])
```

- [ ] **Step 4: Chạy test để xác nhận nó pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_cleaning.py -v`
Expected: PASS toàn bộ

- [ ] **Step 5: Commit**

```bash
git add common/ml_common/cleaning.py common/tests/test_cleaning.py
git commit -m "feat: transformer lam sach theo cot, dung chung train va serve"
```

---

## Task 5: `rowops.py` — thao tác theo dòng

**Files:**

- Create: `common/ml_common/rowops.py`
- Test: `common/tests/test_rowops.py`

**Interfaces:**

- Consumes: `ml_common.schema` (Task 2)
- Produces:
  - `drop_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, int]` — trả (df đã khử trùng, số dòng đã xoá)
  - `drop_rows_missing_target(df: pd.DataFrame, task_type: str) -> tuple[pd.DataFrame, int]`

- [ ] **Step 1: Viết test thất bại**

Tạo `common/tests/test_rowops.py`:

```python
import numpy as np
import pandas as pd
import pytest

from ml_common import rowops


def test_drop_duplicates_removes_rows_with_duplicate_property_id():
    df = pd.DataFrame(
        {
            "property_id": [1, 2, 2, 3],
            "city": ["a", "b", "b", "c"],
        }
    )
    result, dropped_count = rowops.drop_duplicates(df)
    assert len(result) == 3
    assert dropped_count == 1
    assert result["property_id"].tolist() == [1, 2, 3]


def test_drop_duplicates_keeps_the_first_row():
    df = pd.DataFrame({"property_id": [1, 1], "city": ["first", "second"]})
    result, _ = rowops.drop_duplicates(df)
    assert result["city"].tolist() == ["first"]


def test_drop_duplicates_with_no_duplicates_keeps_all_rows():
    df = pd.DataFrame({"property_id": [1, 2, 3]})
    result, dropped_count = rowops.drop_duplicates(df)
    assert len(result) == 3
    assert dropped_count == 0


def test_drop_duplicates_reindexes_the_result():
    df = pd.DataFrame({"property_id": [1, 1, 2]})
    result, _ = rowops.drop_duplicates(df)
    assert result.index.tolist() == [0, 1]


def test_drop_rows_missing_target_regression():
    df = pd.DataFrame({"sale_price": [100.0, np.nan, 300.0], "city": ["a", "b", "c"]})
    result, dropped_count = rowops.drop_rows_missing_target(df, "regression")
    assert len(result) == 2
    assert dropped_count == 1


def test_drop_rows_missing_target_classification():
    df = pd.DataFrame({"sold_within_30_days": [True, None, False]})
    result, dropped_count = rowops.drop_rows_missing_target(df, "classification")
    assert len(result) == 2
    assert dropped_count == 1


def test_drop_rows_missing_target_missing_target_column_raises():
    df = pd.DataFrame({"city": ["a"]})
    with pytest.raises(KeyError, match="sale_price"):
        rowops.drop_rows_missing_target(df, "regression")


def test_drop_rows_missing_target_invalid_task_type_raises():
    df = pd.DataFrame({"sale_price": [1.0]})
    with pytest.raises(ValueError, match="task_type"):
        rowops.drop_rows_missing_target(df, "clustering")
```

- [ ] **Step 2: Chạy test để xác nhận nó thất bại**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_rowops.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.rowops'`

- [ ] **Step 3: Viết `common/ml_common/rowops.py`**

```python
"""ROW-wise operations — only ever called from the `preprocess` stage.

This file is deliberately kept separate from `cleaning.py`: the functions
here drop rows, so they must NEVER be placed in a sklearn Pipeline. Serving
calls /predict with a single record; a row-dropping step would return an
empty DataFrame and crash serving.

The file boundary itself is the safeguard — nobody imports this by mistake.
"""

from __future__ import annotations

import pandas as pd

from ml_common import schema


def drop_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drops rows with a duplicate `property_id`, keeping the first one.

    Handles dirty type 2 (~0.6% of rows are duplicated). Returns
    (new df, dropped row count) so the `preprocess` stage can log the count.
    """
    row_count_before = len(df)
    result = df.drop_duplicates(subset=[schema.ID_COLUMN], keep="first").reset_index(drop=True)
    return result, row_count_before - len(result)


def drop_rows_missing_target(df: pd.DataFrame, task_type: str) -> tuple[pd.DataFrame, int]:
    """Drops rows with no target value — they can't be trained on.

    Returns (new df, dropped row count).
    """
    target_column = schema.target_column(task_type)
    if target_column not in df.columns:
        raise KeyError(f"Missing target column {target_column!r} in DataFrame")
    row_count_before = len(df)
    result = df[df[target_column].notna()].reset_index(drop=True)
    return result, row_count_before - len(result)
```

- [ ] **Step 4: Chạy test để xác nhận nó pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_rowops.py -v`
Expected: PASS toàn bộ 8 test

- [ ] **Step 5: Commit**

```bash
git add common/ml_common/rowops.py common/tests/test_rowops.py
git commit -m "feat: thao tac theo dong, tach rieng khoi Pipeline"
```

---

## Task 6: `features.py` — dựng Pipeline

**Files:**

- Create: `common/ml_common/features.py`
- Test: `common/tests/test_features.py`

**Interfaces:**

- Consumes: `ml_common.cleaning` (Task 4), `ml_common.schema` (Task 2)
- Produces:
  - `build_pipeline(task_type: str, estimator) -> sklearn.pipeline.Pipeline`

- [ ] **Step 1: Viết test thất bại**

Tạo `common/tests/test_features.py`:

```python
import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.pipeline import Pipeline

from ml_common import features


@pytest.fixture
def raw_df():
    """RAW data — mirrors real data before cleaning."""
    row_count = 40
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "property_id": range(row_count),
            "listing_date": ["2023-07-15", "07/15/2023"] * (row_count // 2),
            "city": ["NEW YORK", "new_york", "  Boston ", "BOSTON"] * (row_count // 4),
            "state": ["NY", "ny", "MA", "ma"] * (row_count // 4),
            "zipcode": ["10001", "1000"] * (row_count // 2),
            "property_type": ["Single_Family", "MULTI FAMILY"] * (row_count // 2),
            "lot_size_sqft": rng.uniform(1000, 9000, row_count),
            "living_area_sqft": rng.uniform(800, 4000, row_count),
            "bedrooms": rng.integers(1, 6, row_count).astype(float),
            "bathrooms": rng.choice([1.0, 1.5, 2.0, 2.5], row_count),
            "year_built": rng.integers(1950, 2020, row_count).astype(float),
            "stories": rng.integers(1, 4, row_count).astype(float),
            "garage_spaces": rng.integers(0, 3, row_count).astype(float),
            "has_pool": ["Yes", "N", "1", "False"] * (row_count // 4),
            "hoa_fee_monthly": rng.uniform(0, 400, row_count),
            "school_rating": rng.uniform(1, 10, row_count),
            "crime_index": rng.uniform(0, 100, row_count),
            "distance_to_city_center_km": rng.uniform(0, 40, row_count),
            "condition": ["Good", "EXCELLENT", "poor", "Fair"] * (row_count // 4),
            "days_on_market": rng.integers(1, 200, row_count),
            "list_price": ["$450,000", 500000] * (row_count // 2),
            "sale_price": [440000, "$490,000"] * (row_count // 2),
            "price_category": ["Medium", "High"] * (row_count // 2),
            "sold_within_30_days": ["Yes", "No"] * (row_count // 2),
        }
    )


def test_returns_a_sklearn_pipeline():
    result = features.build_pipeline("regression", DummyRegressor())
    assert isinstance(result, Pipeline)


def test_invalid_task_type_raises():
    with pytest.raises(ValueError, match="task_type"):
        features.build_pipeline("clustering", DummyRegressor())


def test_regression_fit_and_predict_on_RAW_data(raw_df):
    """This is the most important guarantee: the Pipeline accepts raw data,
    no cleaning needed beforehand. If this test passes, serving calling
    /predict with a raw record will work correctly."""
    pipeline = features.build_pipeline("regression", DummyRegressor())
    X = raw_df.drop(columns=["sale_price"])
    y = pd.to_numeric(raw_df["sale_price"].astype(str).str.replace(r"[$,]", "", regex=True))
    pipeline.fit(X, y)
    predictions = pipeline.predict(X)
    assert len(predictions) == len(raw_df)


def test_classification_fit_and_predict_on_RAW_data(raw_df):
    pipeline = features.build_pipeline("classification", DummyClassifier())
    X = raw_df.drop(columns=["sold_within_30_days"])
    y = raw_df["sold_within_30_days"].map({"Yes": 1, "No": 0})
    pipeline.fit(X, y)
    predictions = pipeline.predict(X)
    assert len(predictions) == len(raw_df)


def test_can_predict_a_SINGLE_record(raw_df):
    """Serving receives a single record."""
    pipeline = features.build_pipeline("regression", DummyRegressor())
    X = raw_df.drop(columns=["sale_price"])
    y = pd.to_numeric(raw_df["sale_price"].astype(str).str.replace(r"[$,]", "", regex=True))
    pipeline.fit(X, y)
    predictions = pipeline.predict(X.head(1))
    assert len(predictions) == 1


def test_leakage_columns_do_not_affect_the_pipeline(raw_df):
    """price_category and list_price must not influence the regression model.

    Uses DecisionTreeRegressor, NOT DummyRegressor: Dummy ignores every
    feature, so it would pass even with a buggy Pipeline, giving false
    confidence.
    """
    from sklearn.tree import DecisionTreeRegressor

    pipeline = features.build_pipeline("regression", DecisionTreeRegressor(random_state=0))
    X = raw_df.drop(columns=["sale_price"])
    y = pd.to_numeric(raw_df["sale_price"].astype(str).str.replace(r"[$,]", "", regex=True))
    pipeline.fit(X, y)

    X_altered = X.copy()
    X_altered["price_category"] = "Luxury"
    X_altered["list_price"] = "$9,999,999"
    np.testing.assert_array_equal(pipeline.predict(X), pipeline.predict(X_altered))


def test_selectcolumns_actually_excludes_leakage_columns():
    """Checks the column list directly, without going through predict results."""
    from sklearn.dummy import DummyRegressor as _Dummy

    pipeline = features.build_pipeline("regression", _Dummy())
    selected_columns = pipeline.named_steps["select_columns"].columns
    assert "price_category" not in selected_columns
    assert "list_price" not in selected_columns
    assert "sale_price" not in selected_columns
    assert "property_id" not in selected_columns
    assert "living_area_sqft" in selected_columns


def test_unseen_categorical_value_does_not_crash(raw_df):
    """The Plan 4 agent will send a new property_type (drift_scenario=new_segment)."""
    pipeline = features.build_pipeline("regression", DummyRegressor())
    X = raw_df.drop(columns=["sale_price"])
    y = pd.to_numeric(raw_df["sale_price"].astype(str).str.replace(r"[$,]", "", regex=True))
    pipeline.fit(X, y)

    X_new = X.head(1).copy()
    X_new["property_type"] = "Houseboat"
    X_new["city"] = "Atlantis"
    predictions = pipeline.predict(X_new)
    assert len(predictions) == 1


def test_missing_values_do_not_crash(raw_df):
    pipeline = features.build_pipeline("regression", DummyRegressor())
    X = raw_df.drop(columns=["sale_price"])
    y = pd.to_numeric(raw_df["sale_price"].astype(str).str.replace(r"[$,]", "", regex=True))
    pipeline.fit(X, y)

    X_missing = X.head(1).copy()
    for column in ["bedrooms", "bathrooms", "year_built", "school_rating", "hoa_fee_monthly"]:
        X_missing[column] = np.nan
    predictions = pipeline.predict(X_missing)
    assert len(predictions) == 1
```

- [ ] **Step 2: Chạy test để xác nhận nó thất bại**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_features.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.features'`

- [ ] **Step 3: Viết `common/ml_common/features.py`**

```python
"""Builds the complete sklearn Pipeline for each task.

The Pipeline returned here gets logged whole into MLflow at the `train`
stage, so it must SELF-CONTAIN all cleaning logic: the model in the
Registry receives a RAW record and handles it itself. This is the guard
against training/serving skew — see section 7.1 of the design doc.
"""

from __future__ import annotations

from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml_common import schema
from ml_common.cleaning import DateFeatures, OutlierClipper, RawRecordCleaner


class SelectColumns(BaseEstimator, TransformerMixin):
    """Keeps exactly the given list of columns, in that order.

    Missing columns are added with value None. This keeps serving from
    crashing when a caller omits an optional column, and strips leakage
    columns even if a caller sends them.
    """

    def __init__(self, columns: list[str]):
        self.columns = columns

    def fit(self, X, y=None):  # noqa: N803
        return self

    def transform(self, X):  # noqa: N803
        result = X.copy()
        for column_name in self.columns:
            if column_name not in result.columns:
                result[column_name] = None
        return result[self.columns]


def _numeric_and_categorical_columns(task_type: str) -> tuple[list[str], list[str]]:
    """Splits features into numeric and categorical groups, AFTER DateFeatures has run."""
    feature = schema.feature_columns(task_type)
    numeric_columns: list[str] = []
    categorical_columns: list[str] = []
    for column_name in feature:
        if column_name == "listing_date":
            continue  # already turned into listing_year / listing_month
        spec = schema.COLUMNS[column_name]
        if spec.kind in ("numeric", "money"):
            numeric_columns.append(column_name)
        elif spec.kind == "boolean":
            numeric_columns.append(column_name)  # True/False -> 1/0
        else:  # categorical, zipcode
            categorical_columns.append(column_name)
    if "listing_date" in feature:
        numeric_columns.extend(["listing_year", "listing_month"])
    return numeric_columns, categorical_columns


def build_pipeline(task_type: str, estimator) -> Pipeline:
    """Builds the full Pipeline: clean -> select columns -> encode -> model.

    Args:
        task_type: "regression" or "classification".
        estimator: an already-initialized sklearn estimator.

    Returns:
        A Pipeline that accepts a RAW DataFrame as input.
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(
            f"task_type must be one of {schema.TASK_TYPES}, got: {task_type!r}"
        )

    numeric_columns, categorical_columns = _numeric_and_categorical_columns(task_type)

    numeric_branch = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]
    )
    categorical_branch = Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            # handle_unknown="infrequent_if_exist" keeps serving from crashing
            # on a value it has never seen (agent drift_scenario=new_segment).
            (
                "encode",
                OneHotEncoder(
                    handle_unknown="infrequent_if_exist",
                    min_frequency=0.01,
                    sparse_output=False,
                ),
            ),
        ]
    )

    encoder = ColumnTransformer(
        [
            ("numeric", numeric_branch, numeric_columns),
            ("categorical", categorical_branch, categorical_columns),
        ],
        remainder="drop",
    )

    return Pipeline(
        [
            ("clean", RawRecordCleaner()),
            ("clip_outlier", OutlierClipper()),
            ("date_features", DateFeatures()),
            ("select_columns", SelectColumns(numeric_columns + categorical_columns)),
            ("encode", encoder),
            ("model", estimator),
        ]
    )
```

- [ ] **Step 4: Chạy test để xác nhận nó pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_features.py -v`
Expected: PASS toàn bộ 9 test

Nếu `test_unseen_categorical_value_does_not_crash` thất bại với `Found unknown categories`, kiểm tra lại `handle_unknown` của `OneHotEncoder` — đây chính là lỗi sẽ làm serving sập ở Plan 4.

**Một hạn chế đã biết, cố ý để lại:** `zipcode` được xếp vào nhóm categorical, mà nó có hàng chục nghìn giá trị khác nhau. Với `min_frequency=0.01` trên 2 triệu dòng, gần như mọi zipcode sẽ rơi vào nhóm "infrequent" và cột này gần như không đóng góp gì. Vô hại nhưng lãng phí. Không sửa ở Plan 1 vì chưa có dữ liệu thật để biết nên thay bằng gì (target encoding? gộp theo 3 số đầu?) — Plan 2 sẽ quyết sau khi nhìn kết quả train đầu tiên.

- [ ] **Step 5: Commit**

```bash
git add common/ml_common/features.py common/tests/test_features.py
git commit -m "feat: dung Pipeline tu chua logic lam sach cho ca 2 bai toan"
```

---

## Task 7: Hạ tầng — Postgres và MinIO

**Files:**

- Create: `docker-compose.yml`
- Create: `docker/postgres/init-databases.sql`

**Interfaces:**

- Consumes: `.env.example` (Task 1)
- Produces: Postgres nghe ở `localhost:5432` với hai database `airflow` và `mlflow`; MinIO ở `localhost:9000` (API) và `localhost:9001` (console), bucket `ml-pipeline` đã tạo sẵn.

- [ ] **Step 1: Kiểm tra dung lượng đĩa trước khi pull image**

Run: `.venv\Scripts\python.exe -c "import shutil; print(f'{shutil.disk_usage(\"C:/\").free/2**30:.1f} GB free')"`
Expected: ≥ 8 GB. Nếu ít hơn, dọn đĩa trước — `docker system prune -a` nếu có image cũ không dùng.

- [ ] **Step 2: Tạo `docker/postgres/init-databases.sql`**

Script này chỉ chạy đúng một lần, lúc volume Postgres được khởi tạo lần đầu.

```sql
-- Database `airflow` is already created by the POSTGRES_DB variable.
-- Create a separate database for MLflow: keeping them apart means Airflow's
-- and MLflow's metadata don't affect each other on backup or reset.
CREATE DATABASE mlflow;
```

- [ ] **Step 3: Tạo `docker-compose.yml`**

```yaml
name: mlops

services:
  postgres:
    image: postgres:16-alpine
    container_name: mlops-postgres
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: airflow
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./docker/postgres/init-databases.sql:/docker-entrypoint-initdb.d/init-databases.sql:ro
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 5s
      timeout: 5s
      retries: 10
    restart: unless-stopped

  minio:
    # MinIO da go image khoi Docker Hub; quay.io la registry chinh thuc hien nay.
    image: quay.io/minio/minio:latest
    container_name: mlops-minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY}
    volumes:
      - minio-data:/data
    ports:
      - "9000:9000"
      - "9001:9001"
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 5s
      timeout: 5s
      retries: 10
    restart: unless-stopped

  minio-init:
    image: quay.io/minio/mc:latest
    container_name: mlops-minio-init
    depends_on:
      minio:
        condition: service_healthy
    entrypoint: >
      /bin/sh -c "
      mc alias set local http://minio:9000 ${MINIO_ACCESS_KEY} ${MINIO_SECRET_KEY} &&
      mc mb --ignore-existing local/${ML_BUCKET} &&
      echo 'Bucket ${ML_BUCKET} ready'
      "

volumes:
  postgres-data:
  minio-data:
```

- [ ] **Step 4: Tạo `.env` từ mẫu và khởi động**

```powershell
Copy-Item .env.example .env
docker compose up -d postgres minio minio-init
```

- [ ] **Step 5: Xác nhận Postgres có đúng hai database**

Run: `docker compose exec postgres psql -U mlops -d airflow -c "\l"`
Expected: bảng liệt kê có cả `airflow` và `mlflow`

- [ ] **Step 6: Xác nhận MinIO có bucket**

Run: `docker compose logs minio-init`
Expected: dòng `Bucket ml-pipeline ready`

Mở `http://localhost:9001` bằng trình duyệt, đăng nhập `minioadmin` / `minioadmin`, thấy bucket `ml-pipeline`.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml docker/postgres/init-databases.sql
git commit -m "feat: ha tang Postgres hai database va MinIO"
```

---

## Task 8: `storage.py` — wrapper MinIO/S3

**Files:**

- Create: `common/ml_common/storage.py`
- Test: `common/tests/test_storage.py`

**Interfaces:**

- Consumes: Task 7 (MinIO đang chạy — nhưng test dùng `moto`, không cần MinIO thật)
- Produces:
  - Hàm đường dẫn key: `raw_key(dataset_version) -> str`, `processed_key(fingerprint, split) -> str`, `baseline_key(model_name, version) -> str`, `inference_log_key(model_name, day, part_id) -> str`, `ground_truth_key(model_name, day, part_id) -> str`, `report_key(model_name, run_id, ext) -> str`
  - Hàm đường dẫn prefix (Plan 2 và Plan 4 dùng): `processed_prefix(fingerprint) -> str`, `inference_log_prefix(model_name, day) -> str`, `ground_truth_prefix(model_name, day) -> str`
  - `Storage` class: `.write_parquet(df, key)`, `.read_parquet(key) -> pd.DataFrame`, `.write_json(obj, key)`, `.read_json(key) -> dict`, `.write_bytes(data, key, content_type)`, `.exists(key) -> bool`, `.list_keys(prefix) -> list[str]`, `.from_env() -> Storage` (classmethod)

- [ ] **Step 1: Viết test thất bại**

Tạo `common/tests/test_storage.py`:

```python
from datetime import date

import pandas as pd
import pytest
from moto import mock_aws

from ml_common import storage

BUCKET = "test-bucket"


@pytest.fixture
def store():
    with mock_aws():
        import boto3

        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        yield storage.Storage(
            endpoint_url=None,
            access_key="test",
            secret_key="test",
            bucket=BUCKET,
        )


class TestKeyHelpers:
    def test_raw_key(self):
        assert storage.raw_key("v1") == "raw/v1/data.parquet"

    def test_processed_key(self):
        assert storage.processed_key("abc123", "train") == "processed/abc123/train.parquet"
        assert storage.processed_key("abc123", "test") == "processed/abc123/test.parquet"

    def test_processed_key_invalid_split_raises(self):
        with pytest.raises(ValueError, match="split"):
            storage.processed_key("abc123", "validation")

    def test_baseline_key(self):
        result = storage.baseline_key("house_price_regressor", 3)
        assert result == "monitoring-baseline/house_price_regressor/3/profile.json"

    def test_inference_log_key_partitions_by_day(self):
        result = storage.inference_log_key("house_price_regressor", date(2026, 9, 17), "0001")
        assert result == "inference-log/house_price_regressor/dt=2026-09-17/part-0001.parquet"

    def test_ground_truth_key_partitions_by_day(self):
        result = storage.ground_truth_key("house_price_regressor", date(2026, 9, 17), "0001")
        assert result == "ground-truth/house_price_regressor/dt=2026-09-17/part-0001.parquet"

    def test_report_key(self):
        result = storage.report_key("house_price_regressor", "run-42", "html")
        assert result == "reports/house_price_regressor/run-42/evidently.html"

    def test_no_key_starts_with_a_slash(self):
        keys = [
            storage.raw_key("v1"),
            storage.processed_key("a", "train"),
            storage.baseline_key("m", 1),
            storage.inference_log_key("m", date(2026, 1, 1), "0001"),
            storage.ground_truth_key("m", date(2026, 1, 1), "0001"),
            storage.report_key("m", "r", "json"),
        ]
        for key in keys:
            assert not key.startswith("/"), f"{key} starts with a slash"


class TestStorage:
    def test_write_and_read_parquet_preserves_data(self, store):
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        store.write_parquet(df, "some/folder/file.parquet")
        result = store.read_parquet("some/folder/file.parquet")
        pd.testing.assert_frame_equal(df, result)

    def test_write_and_read_json(self, store):
        data = {"name": "test", "count": 42, "items": [1, 2, 3]}
        store.write_json(data, "some/folder/file.json")
        assert store.read_json("some/folder/file.json") == data

    def test_exists_is_correct_for_present_and_absent_keys(self, store):
        store.write_json({"a": 1}, "present/file.json")
        assert store.exists("present/file.json") is True
        assert store.exists("absent/file.json") is False

    def test_list_keys_by_prefix(self, store):
        store.write_json({}, "prefix-a/one.json")
        store.write_json({}, "prefix-a/two.json")
        store.write_json({}, "prefix-b/three.json")
        result = store.list_keys("prefix-a/")
        assert sorted(result) == ["prefix-a/one.json", "prefix-a/two.json"]

    def test_list_keys_missing_prefix_returns_empty_list(self, store):
        assert store.list_keys("does-not-exist/") == []

    def test_reading_a_missing_key_raises(self, store):
        with pytest.raises(FileNotFoundError, match="missing/file.parquet"):
            store.read_parquet("missing/file.parquet")

    def test_overwriting_an_existing_key(self, store):
        store.write_json({"version": 1}, "file.json")
        store.write_json({"version": 2}, "file.json")
        assert store.read_json("file.json") == {"version": 2}
```

- [ ] **Step 2: Chạy test để xác nhận nó thất bại**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_storage.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.storage'`

- [ ] **Step 3: Viết `common/ml_common/storage.py`**

```python
"""boto3 wrapper and the ENTIRE path convention for MinIO/S3.

This is the single place in the system that knows about object storage.
When migrating to real S3, only `endpoint_url` needs to go away — no other
file needs to change.

Never concatenate paths by hand anywhere else: use the *_key() functions
here. See the plan's Global Constraints.
"""

from __future__ import annotations

import io
import json
import os
from datetime import date

import boto3
import pandas as pd
from botocore.exceptions import ClientError

_SPLITS = ("train", "test")


def raw_key(dataset_version: str) -> str:
    """Path to the raw data of a dataset version."""
    return f"raw/{dataset_version}/data.parquet"


def processed_key(fingerprint: str, split: str) -> str:
    """Path to processed data, named after the raw data's fingerprint.

    The fingerprint acts as a cache key: `preprocess` skips work if this
    prefix already exists.
    """
    if split not in _SPLITS:
        raise ValueError(f"split must be one of {_SPLITS}, got: {split!r}")
    return f"processed/{fingerprint}/{split}.parquet"


def processed_prefix(fingerprint: str) -> str:
    """Prefix covering both train and test for a fingerprint."""
    return f"processed/{fingerprint}/"


def baseline_key(model_name: str, version: int | str) -> str:
    """Statistical profile of the train set, tied to a specific model version."""
    return f"monitoring-baseline/{model_name}/{version}/profile.json"


def inference_log_key(model_name: str, day: date, part_id: str) -> str:
    """One inference log file, partitioned by day."""
    return f"inference-log/{model_name}/dt={day.isoformat()}/part-{part_id}.parquet"


def inference_log_prefix(model_name: str, day: date) -> str:
    """Prefix covering all inference logs for a day."""
    return f"inference-log/{model_name}/dt={day.isoformat()}/"


def ground_truth_key(model_name: str, day: date, part_id: str) -> str:
    """One ground-truth file from /feedback, partitioned by day."""
    return f"ground-truth/{model_name}/dt={day.isoformat()}/part-{part_id}.parquet"


def ground_truth_prefix(model_name: str, day: date) -> str:
    """Prefix covering all ground truth for a day."""
    return f"ground-truth/{model_name}/dt={day.isoformat()}/"


def report_key(model_name: str, run_id: str, ext: str) -> str:
    """Evidently report for one monitoring run."""
    return f"reports/{model_name}/{run_id}/evidently.{ext}"


class Storage:
    """Reads/writes parquet and json on S3-compatible object storage."""

    def __init__(
        self,
        endpoint_url: str | None,
        access_key: str,
        secret_key: str,
        bucket: str,
    ):
        self.bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
        )

    @classmethod
    def from_env(cls) -> Storage:
        """Builds a Storage from environment variables.

        Inside a container, use MINIO_ENDPOINT_INTERNAL (http://minio:9000);
        running from the host, use MINIO_ENDPOINT (http://localhost:9000).
        """
        endpoint = os.environ.get("MINIO_ENDPOINT_INTERNAL") or os.environ["MINIO_ENDPOINT"]
        return cls(
            endpoint_url=endpoint,
            access_key=os.environ["MINIO_ACCESS_KEY"],
            secret_key=os.environ["MINIO_SECRET_KEY"],
            bucket=os.environ.get("ML_BUCKET", "ml-pipeline"),
        )

    def write_parquet(self, df: pd.DataFrame, key: str) -> None:
        """Writes a DataFrame as parquet (snappy compression)."""
        buffer = io.BytesIO()
        df.to_parquet(buffer, index=False, compression="snappy")
        buffer.seek(0)
        self._client.put_object(Bucket=self.bucket, Key=key, Body=buffer.getvalue())

    def read_parquet(self, key: str) -> pd.DataFrame:
        """Reads a parquet file into a DataFrame."""
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as err:
            if err.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"Key not found: {key}") from err
            raise
        return pd.read_parquet(io.BytesIO(response["Body"].read()))

    def write_json(self, obj: dict, key: str) -> None:
        """Writes a dict as UTF-8 JSON."""
        content = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="application/json",
        )

    def read_json(self, key: str) -> dict:
        """Reads a JSON file into a dict."""
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as err:
            if err.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"Key not found: {key}") from err
            raise
        return json.loads(response["Body"].read().decode("utf-8"))

    def write_bytes(self, data: bytes, key: str, content_type: str) -> None:
        """Writes raw bytes — used for Evidently's HTML report in Plan 4."""
        self._client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    def exists(self, key: str) -> bool:
        """True if the key exists."""
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def list_keys(self, prefix: str) -> list[str]:
        """List of keys under a prefix, with pagination."""
        result: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                result.append(obj["Key"])
        return result
```

- [ ] **Step 4: Chạy test để xác nhận nó pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_storage.py -v`
Expected: PASS toàn bộ 15 test

- [ ] **Step 5: Kiểm tra thủ công với MinIO thật**

Test ở Step 4 dùng `moto` (S3 giả lập trong bộ nhớ). Bước này xác nhận nó nói chuyện được với MinIO thật.

Tạo `scripts/smoke_storage.py`:

```python
"""Smoke test: write and read a parquet file on real MinIO."""

import os

import pandas as pd

os.environ["MINIO_ENDPOINT"] = "http://localhost:9000"
os.environ.pop("MINIO_ENDPOINT_INTERNAL", None)  # running from host, not inside a container
os.environ["MINIO_ACCESS_KEY"] = "minioadmin"
os.environ["MINIO_SECRET_KEY"] = "minioadmin"
os.environ["ML_BUCKET"] = "ml-pipeline"

from ml_common.storage import Storage  # noqa: E402

store = Storage.from_env()
store.write_parquet(pd.DataFrame({"a": [1, 2, 3]}), "smoke-test/sample.parquet")
print(store.read_parquet("smoke-test/sample.parquet"))
print("keys:", store.list_keys("smoke-test/"))
print("exists:", store.exists("smoke-test/sample.parquet"))
```

Run: `.venv\Scripts\python.exe scripts\smoke_storage.py`
Expected: in ra DataFrame 3 dòng, danh sách key có `smoke-test/sample.parquet`, và `exists: True`

- [ ] **Step 6: Commit**

```bash
git add common/ml_common/storage.py common/tests/test_storage.py scripts/smoke_storage.py
git commit -m "feat: wrapper storage va convention duong dan MinIO"
```

---

## Task 9: `profiling.py` — baseline profile

**Files:**

- Create: `common/ml_common/profiling.py`
- Test: `common/tests/test_profiling.py`

**Interfaces:**

- Consumes: `ml_common.schema` (Task 2)
- Produces:
  - `compute_profile(df: pd.DataFrame, columns: list[str], n_bins: int = 20) -> dict`

Cấu trúc dict trả về — Plan 4 đọc đúng cấu trúc này, nên nó là hợp đồng:

```python
{
    "n_rows": int,
    "computed_at": str,          # ISO 8601
    "columns": {
        "<column_name>": {
            "kind": "numeric",
            "missing_rate": float,
            "mean": float, "std": float, "min": float, "max": float,
            "quantiles": {"p25": float, "p50": float, "p75": float},
            "histogram": {"bin_edges": [float, ...], "counts": [int, ...]},
        },
        "<other_column_name>": {
            "kind": "categorical",
            "missing_rate": float,
            "n_unique": int,
            "distribution": {"<value>": float, ...},   # proportion, sums to 1.0
        },
    },
}
```

- [ ] **Step 1: Viết test thất bại**

Tạo `common/tests/test_profiling.py`:

```python
import numpy as np
import pandas as pd

from ml_common import profiling


def sample_df():
    rng = np.random.default_rng(7)
    return pd.DataFrame(
        {
            "living_area_sqft": rng.uniform(800, 4000, 500),
            "bedrooms": rng.integers(1, 6, 500).astype(float),
            "city": rng.choice(["new york", "boston", "austin"], 500),
            "condition": rng.choice(["good", "fair"], 500),
        }
    )


def test_has_common_metadata():
    profile = profiling.compute_profile(sample_df(), ["living_area_sqft", "city"])
    assert profile["n_rows"] == 500
    assert isinstance(profile["computed_at"], str)
    assert set(profile["columns"]) == {"living_area_sqft", "city"}


def test_numeric_column_has_full_stats():
    profile = profiling.compute_profile(sample_df(), ["living_area_sqft"])
    column = profile["columns"]["living_area_sqft"]
    assert column["kind"] == "numeric"
    assert 800 <= column["mean"] <= 4000
    assert column["std"] > 0
    assert column["min"] >= 800
    assert column["max"] <= 4000
    assert column["quantiles"]["p25"] < column["quantiles"]["p50"] < column["quantiles"]["p75"]


def test_histogram_has_the_requested_bin_count():
    profile = profiling.compute_profile(sample_df(), ["living_area_sqft"], n_bins=20)
    hist = profile["columns"]["living_area_sqft"]["histogram"]
    assert len(hist["counts"]) == 20
    assert len(hist["bin_edges"]) == 21
    assert sum(hist["counts"]) == 500


def test_categorical_column_distribution_sums_to_one():
    profile = profiling.compute_profile(sample_df(), ["city"])
    column = profile["columns"]["city"]
    assert column["kind"] == "categorical"
    assert column["n_unique"] == 3
    assert abs(sum(column["distribution"].values()) - 1.0) < 1e-9


def test_missing_rate_is_computed_correctly():
    df = pd.DataFrame({"bedrooms": [1.0, 2.0, np.nan, np.nan]})
    profile = profiling.compute_profile(df, ["bedrooms"])
    assert profile["columns"]["bedrooms"]["missing_rate"] == 0.5


def test_column_entirely_missing_does_not_crash():
    df = pd.DataFrame({"bedrooms": [np.nan, np.nan]})
    profile = profiling.compute_profile(df, ["bedrooms"])
    column = profile["columns"]["bedrooms"]
    assert column["missing_rate"] == 1.0
    assert column["mean"] is None


def test_column_not_in_df_is_skipped():
    profile = profiling.compute_profile(sample_df(), ["city", "nonexistent_column"])
    assert set(profile["columns"]) == {"city"}


def test_profile_is_json_serializable():
    import json

    profile = profiling.compute_profile(sample_df(), ["living_area_sqft", "city"])
    text = json.dumps(profile)
    assert json.loads(text)["n_rows"] == 500


def test_no_numpy_types_remain_in_the_result():
    """numpy types are not serializable by plain json."""
    profile = profiling.compute_profile(sample_df(), ["living_area_sqft", "city"])
    column = profile["columns"]["living_area_sqft"]
    assert type(column["mean"]) is float
    assert all(type(c) is int for c in column["histogram"]["counts"])
```

- [ ] **Step 2: Chạy test để xác nhận nó thất bại**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_profiling.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.profiling'`

- [ ] **Step 3: Viết `common/ml_common/profiling.py`**

```python
"""Computes the statistical profile of a DataFrame — used as a drift baseline.

The `register` stage calls this on the train set of a newly promoted model,
then writes the result to monitoring-baseline/{model}/{version}/profile.json.
This keeps the baseline tied to the exact model version that used it.

The result must be serializable by plain `json.dumps`, so every numpy type
is converted back to a native Python type.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ml_common import schema

_NUMERIC_KINDS = {"numeric", "money", "boolean"}


def _to_float(value) -> float | None:
    """Converts a numpy value to a Python float, NaN to None."""
    if value is None or pd.isna(value):
        return None
    return float(value)


def _profile_numeric_column(series: pd.Series, n_bins: int) -> dict:
    valid = pd.to_numeric(series, errors="coerce").dropna()
    result: dict = {
        "kind": "numeric",
        "missing_rate": float(1 - len(valid) / len(series)) if len(series) else 1.0,
        "mean": _to_float(valid.mean()) if len(valid) else None,
        "std": _to_float(valid.std()) if len(valid) else None,
        "min": _to_float(valid.min()) if len(valid) else None,
        "max": _to_float(valid.max()) if len(valid) else None,
        "quantiles": {
            "p25": _to_float(valid.quantile(0.25)) if len(valid) else None,
            "p50": _to_float(valid.quantile(0.50)) if len(valid) else None,
            "p75": _to_float(valid.quantile(0.75)) if len(valid) else None,
        },
        "histogram": {"bin_edges": [], "counts": []},
    }
    if len(valid):
        counts, bin_edges = np.histogram(valid, bins=n_bins)
        result["histogram"] = {
            "bin_edges": [float(x) for x in bin_edges],
            "counts": [int(x) for x in counts],
        }
    return result


def _profile_categorical_column(series: pd.Series) -> dict:
    valid = series.dropna()
    distribution = (
        {str(k): float(v) for k, v in valid.value_counts(normalize=True).items()}
        if len(valid)
        else {}
    )
    return {
        "kind": "categorical",
        "missing_rate": float(1 - len(valid) / len(series)) if len(series) else 1.0,
        "n_unique": int(valid.nunique()),
        "distribution": distribution,
    }


def compute_profile(df: pd.DataFrame, columns: list[str], n_bins: int = 20) -> dict:
    """Computes the statistical profile for the given columns.

    Args:
        df: cleaned DataFrame.
        columns: list of columns to profile. Columns missing from df are skipped.
        n_bins: number of histogram bins for numeric columns.

    Returns:
        A dict serializable by json.dumps — see the Interfaces section for its shape.
    """
    column_profiles: dict[str, dict] = {}
    for column_name in columns:
        if column_name not in df.columns:
            continue
        spec = schema.COLUMNS.get(column_name)
        is_numeric = (
            spec.kind in _NUMERIC_KINDS if spec else pd.api.types.is_numeric_dtype(df[column_name])
        )
        if is_numeric:
            column_profiles[column_name] = _profile_numeric_column(df[column_name], n_bins)
        else:
            column_profiles[column_name] = _profile_categorical_column(df[column_name])

    return {
        "n_rows": int(len(df)),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "columns": column_profiles,
    }
```

- [ ] **Step 4: Chạy test để xác nhận nó pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_profiling.py -v`
Expected: PASS toàn bộ 9 test

- [ ] **Step 5: Chạy toàn bộ test suite**

Run: `.venv\Scripts\python.exe -m pytest common/ -v`
Expected: PASS toàn bộ. Đây là lần đầu chạy tất cả với nhau — nếu có test nào hỏng thì là do import vòng giữa các module.

- [ ] **Step 6: Commit**

```bash
git add common/ml_common/profiling.py common/tests/test_profiling.py
git commit -m "feat: tinh baseline profile cho drift detection"
```

---

## Task 10: Hạ tầng — MLflow

**Files:**

- Create: `docker/mlflow/Dockerfile`
- Modify: `docker-compose.yml` (thêm service `mlflow`)

**Interfaces:**

- Consumes: Task 7 (Postgres và MinIO đang chạy)
- Produces: MLflow Tracking Server ở `http://localhost:5000`, backend store là Postgres database `mlflow`, artifact store là `s3://ml-pipeline/artifacts/`.

- [ ] **Step 1: Tạo `docker/mlflow/Dockerfile`**

Image chính thức của MLflow không kèm driver Postgres và boto3, nên phải build thêm.

```dockerfile
FROM python:3.12-slim

RUN pip install --no-cache-dir \
    "mlflow>=2.14,<3" \
    "psycopg2-binary>=2.9" \
    "boto3>=1.34"

EXPOSE 5000

ENTRYPOINT ["mlflow", "server"]
```

- [ ] **Step 2: Thêm service `mlflow` vào `docker-compose.yml`**

Chèn vào dưới service `minio-init`, trước khối `volumes:`:

```yaml
  mlflow:
    build: ./docker/mlflow
    container_name: mlops-mlflow
    depends_on:
      postgres:
        condition: service_healthy
      minio:
        condition: service_healthy
    environment:
      MLFLOW_S3_ENDPOINT_URL: ${MINIO_ENDPOINT_INTERNAL}
      AWS_ACCESS_KEY_ID: ${MINIO_ACCESS_KEY}
      AWS_SECRET_ACCESS_KEY: ${MINIO_SECRET_KEY}
    command:
      - --host=0.0.0.0
      - --port=5000
      - --backend-store-uri=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/mlflow
      - --default-artifact-root=s3://${ML_BUCKET}/artifacts/
    ports:
      - "5000:5000"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s
    restart: unless-stopped
```

- [ ] **Step 3: Build và khởi động**

```powershell
docker compose up -d --build mlflow
docker compose ps
```

Expected: `mlops-mlflow` ở trạng thái `running (healthy)`. Lần đầu build mất vài phút.

- [ ] **Step 4: Xác nhận MLflow ghi được vào Postgres và MinIO**

Tạo `scripts/smoke_mlflow.py`:

```python
"""Smoke test: log a run and a model to real MLflow."""

import mlflow
import mlflow.sklearn
import pandas as pd
from sklearn.dummy import DummyRegressor

mlflow.set_tracking_uri("http://localhost:5000")
mlflow.set_experiment("smoke-test")

X = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
y = pd.Series([10.0, 20.0, 30.0])
model = DummyRegressor().fit(X, y)

with mlflow.start_run() as run:
    mlflow.log_param("trial", "smoke")
    mlflow.log_metric("rmse", 1.23)
    # MLflow 2.x uses `artifact_path`; the `name` param only exists from MLflow 3.
    mlflow.sklearn.log_model(model, artifact_path="model")
    print("run_id:", run.info.run_id)
    print("artifact_uri:", mlflow.get_artifact_uri())
```

Run:

```powershell
.venv\Scripts\python.exe -m pip install "mlflow>=2.14,<3"
.venv\Scripts\python.exe scripts\smoke_mlflow.py
```

Expected: in ra `run_id` và một `artifact_uri` bắt đầu bằng `s3://ml-pipeline/artifacts/`.

- [ ] **Step 5: Xác nhận artifact thật sự nằm trên MinIO**

Mở `http://localhost:5000` — thấy experiment `smoke-test` với một run có param và metric.
Mở `http://localhost:9001` — trong bucket `ml-pipeline`, prefix `artifacts/` có thư mục của run đó.

Nếu MLflow UI hiện run nhưng MinIO không có file, thì `MLFLOW_S3_ENDPOINT_URL` đang sai.

- [ ] **Step 6: Commit**

```bash
git add docker/mlflow/Dockerfile docker-compose.yml scripts/smoke_mlflow.py
git commit -m "feat: MLflow tracking server voi backend Postgres va artifact MinIO"
```

---

## Task 11: Hạ tầng — Airflow

**Files:**

- Modify: `docker-compose.yml` (thêm `airflow-init`, `airflow-scheduler`, `airflow-webserver`)
- Create: `dags/smoke_dag.py`

**Interfaces:**

- Consumes: Task 7 (Postgres đang chạy)
- Produces: Airflow Webserver ở `http://localhost:8080`, LocalExecutor, metadata trong Postgres database `airflow`, thư mục `dags/` được mount vào container.

- [ ] **Step 1: Kiểm tra dung lượng đĩa**

Run: `.venv\Scripts\python.exe -c "import shutil; print(f'{shutil.disk_usage(\"C:/\").free/2**30:.1f} GB free')"`
Expected: ≥ 5 GB. Image Airflow khoảng 2GB.

- [ ] **Step 2: Tạo thư mục và đặt quyền**

```powershell
New-Item -ItemType Directory -Force dags, logs, plugins | Out-Null
```

- [ ] **Step 3: Thêm ba service Airflow vào `docker-compose.yml`**

Chèn vào dưới service `mlflow`, trước khối `volumes:`:

```yaml
  airflow-init:
    image: apache/airflow:2.10.3-python3.12
    container_name: mlops-airflow-init
    depends_on:
      postgres:
        condition: service_healthy
    environment: &airflow-env
      AIRFLOW__CORE__EXECUTOR: LocalExecutor
      AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/airflow
      AIRFLOW__CORE__LOAD_EXAMPLES: "false"
      AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION: "true"
      AIRFLOW__WEBSERVER__EXPOSE_CONFIG: "true"
      MLFLOW_TRACKING_URI: ${MLFLOW_TRACKING_URI}
      MINIO_ENDPOINT_INTERNAL: ${MINIO_ENDPOINT_INTERNAL}
      MINIO_ACCESS_KEY: ${MINIO_ACCESS_KEY}
      MINIO_SECRET_KEY: ${MINIO_SECRET_KEY}
      ML_BUCKET: ${ML_BUCKET}
    volumes: &airflow-volumes
      - ./dags:/opt/airflow/dags
      - ./logs:/opt/airflow/logs
      - ./plugins:/opt/airflow/plugins
    user: "${AIRFLOW_UID:-50000}:0"
    # Giữ nguyên MỘT dòng. YAML folded scalar (`>`) không gộp các dòng được thụt
    # sâu hơn — bash sẽ nhận newline thật và tách `airflow users create` khỏi
    # tham số của nó, container thoát với mã 2 ("--username: command not found").
    entrypoint: >
      /bin/bash -c "airflow db migrate && airflow users create --username ${AIRFLOW_ADMIN_USER} --password ${AIRFLOW_ADMIN_PASSWORD} --firstname Admin --lastname User --role Admin --email admin@example.com || true"

  airflow-scheduler:
    image: apache/airflow:2.10.3-python3.12
    container_name: mlops-airflow-scheduler
    depends_on:
      airflow-init:
        condition: service_completed_successfully
    environment: *airflow-env
    volumes: *airflow-volumes
    user: "${AIRFLOW_UID:-50000}:0"
    command: scheduler
    restart: unless-stopped

  airflow-webserver:
    image: apache/airflow:2.10.3-python3.12
    container_name: mlops-airflow-webserver
    depends_on:
      airflow-init:
        condition: service_completed_successfully
    environment: *airflow-env
    volumes: *airflow-volumes
    user: "${AIRFLOW_UID:-50000}:0"
    command: webserver
    ports:
      - "8080:8080"
    healthcheck:
      test: ["CMD", "curl", "--fail", "http://localhost:8080/health"]
      interval: 15s
      timeout: 10s
      retries: 10
      start_period: 60s
    restart: unless-stopped
```

- [ ] **Step 4: Tạo `dags/smoke_dag.py`**

DAG này chứng minh Airflow đọc được thư mục `dags/` và chạy được task. Nó bị xoá ở Plan 2.

```python
"""Smoke test DAG — proves Airflow can read dags/ and run a task.

This DAG is deleted in Plan 2 once ml_pipeline_dag.py exists.
"""

from __future__ import annotations

import pendulum
from airflow.decorators import dag, task


@dag(
    dag_id="smoke_test",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["smoke"],
)
def smoke_test():
    @task
    def hello():
        print("Airflow can read dags/ and run a task.")
        return "ok"

    @task
    def check_env_vars():
        import os

        for name in ("MLFLOW_TRACKING_URI", "MINIO_ENDPOINT_INTERNAL", "ML_BUCKET"):
            value = os.environ.get(name)
            print(f"{name} = {value}")
            assert value, f"Missing environment variable {name}"
        return "ok"

    hello() >> check_env_vars()


smoke_test()
```

- [ ] **Step 5: Khởi động Airflow**

```powershell
docker compose up -d airflow-init
docker compose logs -f airflow-init
```

Chờ tới khi container thoát với mã 0, rồi:

```powershell
docker compose up -d airflow-scheduler airflow-webserver
docker compose ps
```

Expected: `mlops-airflow-webserver` ở trạng thái `running (healthy)` sau khoảng 60 giây.

- [ ] **Step 6: Chạy DAG smoke test**

Mở `http://localhost:8080`, đăng nhập `admin` / `admin`. DAG `smoke_test` phải xuất hiện trong danh sách.

Hoặc chạy bằng CLI:

```powershell
docker compose exec airflow-scheduler airflow dags list
docker compose exec airflow-scheduler airflow dags test smoke_test 2026-09-17
```

Expected: cả hai task `hello` và `check_env_vars` đều `success`, log in ra ba biến môi trường có giá trị.

Nếu `check_env_vars` thất bại, biến môi trường chưa truyền được vào container — kiểm tra lại khối `&airflow-env` và file `.env`.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml dags/smoke_dag.py
git commit -m "feat: Airflow LocalExecutor va DAG smoke test"
```

---

## Task 12: Image nền cho các stage

**Files:**

- Create: `stages/base/Dockerfile`
- Create: `stages/base/README.md`
- Create: `scripts/build_base_image.ps1`

**Interfaces:**

- Consumes: `common/` (Task 1-9)
- Produces: image local tên `ml-base:latest` chứa Python 3.12 + `ml_common` đã cài. Mọi stage ở Plan 2 dùng `FROM ml-base:latest`.

- [ ] **Step 1: Tạo `stages/base/Dockerfile`**

```dockerfile
# Base image for every stage of the pipeline.
#
# Why this exists: if each stage installed its own pandas/scikit-learn, the
# build would be slow and versions would drift between stages. A
# scikit-learn version mismatch between train time and serve time is the
# hardest kind of bug to find — the model unpickles wrong or not at all.
#
# Python 3.12 (not 3.13): matches the Airflow image and serving.
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first, copy code after: code changes don't bust this layer's cache.
COPY common/pyproject.toml /app/common/pyproject.toml
RUN mkdir -p /app/common/ml_common \
    && touch /app/common/ml_common/__init__.py \
    && pip install --no-cache-dir -e /app/common

# Now copy the actual code
COPY common/ /app/common/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-c", "import ml_common; print('ml-base ready, ml_common', ml_common.__version__)"]
```

- [ ] **Step 2: Tạo `scripts/build_base_image.ps1`**

Build phải chạy từ thư mục gốc của repo vì Dockerfile tham chiếu `common/`.

```powershell
# Build the base image. Run from the repo root.
docker build -f stages/base/Dockerfile -t ml-base:latest .
```

- [ ] **Step 3: Build image**

Run: `powershell -ExecutionPolicy Bypass -File scripts\build_base_image.ps1`
Expected: build thành công, dòng cuối `naming to docker.io/library/ml-base:latest`

- [ ] **Step 4: Xác nhận `ml_common` import được trong image**

Run: `docker run --rm ml-base:latest`
Expected: `ml-base ready, ml_common 0.1.0`

- [ ] **Step 5: Xác nhận test suite chạy được bên trong image**

Đây là bước quan trọng: nó chứng minh `common/` hoạt động trên Python 3.12 (môi trường thật) chứ không chỉ trên Python 3.13 của máy dev.

Run:

```powershell
docker run --rm ml-base:latest sh -c "pip install --quiet 'pytest>=8.0' 'moto[s3]>=5.0' && python -m pytest /app/common/tests -q"
```

Expected: toàn bộ test PASS.

Nếu có test nào pass ở local mà fail trong container, dừng lại và sửa — đó chính là loại khác biệt môi trường sẽ gây lỗi khó hiểu ở Plan 2 và Plan 3.

- [ ] **Step 6: Tạo `stages/base/README.md`**

```markdown
# Image nền cho các stage

`ml-base:latest` chứa Python 3.12 và package `ml_common` đã cài ở chế độ editable.

## Build

Chạy từ thư mục gốc của repo:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_base_image.ps1
```

## Khi nào phải build lại

Bất cứ khi nào `common/` thay đổi. Các stage `FROM ml-base:latest` sẽ không
tự thấy thay đổi cho tới khi image nền được build lại.

## Ràng buộc

Python phải là 3.12, khớp với image Airflow và với serving. Model pickle
bởi scikit-learn chỉ load lại được bởi cùng minor version Python và cùng
version scikit-learn.

```

- [ ] **Step 7: Commit**

```bash
git add stages/base/ scripts/build_base_image.ps1
git commit -m "feat: image nen ml-base cho cac stage"
```

---

## Task 13: Tài liệu và xác nhận toàn bộ

**Files:**

- Create: `README.md` (ghi đè file rỗng nếu đã có)
- Create: `scripts/verify_foundation.ps1`

**Interfaces:**

- Consumes: mọi task trước
- Produces: một lệnh duy nhất xác nhận toàn bộ nền tảng hoạt động.

- [ ] **Step 1: Tạo `scripts/verify_foundation.ps1`**

```powershell
# Verifies the entire Plan 1 foundation works.
$ErrorActionPreference = "Stop"

Write-Host "== 1/5 Local test suite ==" -ForegroundColor Cyan
.venv\Scripts\python.exe -m pytest common/ -q

Write-Host "== 2/5 Lint ==" -ForegroundColor Cyan
.venv\Scripts\python.exe -m ruff check common/

Write-Host "== 3/5 Containers running ==" -ForegroundColor Cyan
docker compose ps

Write-Host "== 4/5 Storage can reach real MinIO ==" -ForegroundColor Cyan
.venv\Scripts\python.exe scripts\smoke_storage.py

Write-Host "== 5/5 Test suite inside the Python 3.12 image ==" -ForegroundColor Cyan
docker run --rm ml-base:latest sh -c "pip install --quiet 'pytest>=8.0' 'moto[s3]>=5.0' && python -m pytest /app/common/tests -q"

Write-Host "`nFoundation ready for Plan 2." -ForegroundColor Green
```

- [ ] **Step 2: Chạy script xác nhận**

Run: `powershell -ExecutionPolicy Bypass -File scripts\verify_foundation.ps1`
Expected: cả 5 mục đều pass, dòng cuối `Foundation ready for Plan 2.`

- [ ] **Step 3: Viết `README.md`**

```markdown
# MLOps House Pricing Pipeline

Pipeline MLOps đầy đủ chạy offline, thiết kế để migrate lên AWS với thay đổi
code tối thiểu. Xem `mlops-pipeline-design.md` để biết thiết kế đầy đủ.

## Trạng thái

Plan 1/5 (Foundation) — hạ tầng và package `common/`.

## Yêu cầu

- Docker Desktop
- Python 3.11+ (dev trên 3.13, container chạy 3.12)
- Ổ đĩa còn tối thiểu 15GB

## Khởi động

```powershell
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e "common[dev]"
docker compose up -d
powershell -ExecutionPolicy Bypass -File scripts\build_base_image.ps1
```

## Giao diện

| Service       | URL                   | Đăng nhập            |
| ------------- | --------------------- | ----------------------- |
| Airflow       | http://localhost:8080 | admin / admin           |
| MLflow        | http://localhost:5000 | —                      |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin |

## Kiểm tra

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_foundation.ps1
```

## Cấu trúc

| Thư mục             | Nội dung                                                               |
| --------------------- | ----------------------------------------------------------------------- |
| `common/`           | Package`ml_common` — schema, parser, transformer, storage, profiling |
| `dags/`             | DAG của Airflow                                                        |
| `docker/`           | Dockerfile cho hạ tầng                                                |
| `stages/base/`      | Image nền cho các stage                                               |
| `scripts/`          | Script smoke test và tiện ích                                        |
| `docs/superpowers/` | Spec và implementation plan                                            |

## Lưu ý về RAM

Máy 16GB chạy đồng thời Airflow + Postgres + MinIO + MLflow. Khi phát triển,
đặt `SAMPLE_ROWS=200000` trong `.env` để không load toàn bộ 2 triệu dòng.
Xoá biến đó khi chạy thật.

```

- [ ] **Step 4: Commit**

```bash
git add README.md scripts/verify_foundation.ps1
git commit -m "docs: README va script xac nhan nen tang"
```

---

## Definition of Done

Plan 1 hoàn thành khi:

- [ ] `powershell -ExecutionPolicy Bypass -File scripts\verify_foundation.ps1` chạy xanh toàn bộ
- [ ] `http://localhost:8080` đăng nhập được, DAG `smoke_test` chạy thành công
- [ ] `http://localhost:5000` hiện experiment `smoke-test` với artifact nằm trên MinIO
- [ ] `http://localhost:9001` có bucket `ml-pipeline`
- [ ] `docker run --rm ml-base:latest` in ra `ml-base ready, ml_common 0.1.0`
- [ ] Test suite pass ở cả Python 3.13 (local) lẫn Python 3.12 (container)
- [ ] Toàn bộ 8 loại dirty của dataset đều có test tương ứng trong `common/tests/`

---

## Những gì Plan 1 cố tình KHÔNG làm

Để tránh nhầm lẫn khi thực thi:

- **Không đọc file CSV thật.** `house_pricing_dirty.csv` chỉ được đụng tới ở Plan 2, stage `extract`. Plan 1 test bằng DataFrame nhỏ tạo trong bộ nhớ — nhanh hơn nhiều và đủ để bắt mọi lỗi logic.
- **Không train model nào.** `features.build_pipeline` chỉ được test bằng `DummyRegressor`/`DummyClassifier`. Model thật ở Plan 2.
- **Không viết stage nào.** `stages/` chỉ có `base/`.
- **Không có serving, agent, monitoring, dashboard.** Plan 3, 4, 5.

---

## Bản đồ các plan tiếp theo

| Plan                | Nội dung                                                                                                                                                       | Phụ thuộc |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| 2 — Batch pipeline | `stages/` extract, validate, preprocess (có cache fingerprint), train, evaluate (2 cổng), register (+ baseline profile); `ml_pipeline` DAG cho regression | Plan 1      |
| 3 — Serving        | `services/serving/` với `/predict` `/reload` `/health`, ghi inference log theo batch; task `deploy`; nhánh classification                           | Plan 2      |
| 4 — Monitoring     | `services/agent/` với `drift_scenario`; `/feedback` + ground truth; `stages/monitor/` với Evidently; `monitoring_dag`                               | Plan 3      |
| 5 — Dashboard      | `services/api/` theo contract mục 8.3; nối `dashboard/` bỏ mock JS                                                                                       | Plan 4      |

Mỗi plan được viết sau khi plan trước chạy xong, vì mỗi lần chạy sẽ lộ ra thứ cần điều chỉnh cho plan kế tiếp.
