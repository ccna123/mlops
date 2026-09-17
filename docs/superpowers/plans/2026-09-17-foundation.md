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
- **Dung lượng đĩa:** ổ C còn ~21GB. Trước mỗi task pull image, kiểm tra còn tối thiểu 8GB trống.

---

## Ánh xạ Task → Agent → Skill

13 task chỉ có 3 quy trình thật sự khác nhau, nên chúng dùng chung 2 agent và
3 skill thay vì mỗi task một bộ.

| Task | Nội dung | Agent | Skill |
| --- | --- | --- | --- |
| 1 | Scaffolding và tooling | — (chạy trực tiếp) | — |
| 2 | `schema.py` | `mlops-tdd` | `mlops-tdd-module` |
| 3 | `parsers.py` | `mlops-tdd` | `mlops-tdd-module` |
| 4 | `cleaning.py` | `mlops-tdd` | `mlops-tdd-module` |
| 5 | `rowops.py` | `mlops-tdd` | `mlops-tdd-module` |
| 6 | `features.py` | `mlops-tdd` | `mlops-tdd-module` |
| 7 | Postgres + MinIO | `mlops-infra` | `mlops-infra-service` |
| 8 | `storage.py` | `mlops-tdd` | `mlops-tdd-module` |
| 9 | `profiling.py` | `mlops-tdd` | `mlops-tdd-module` |
| 10 | MLflow | `mlops-infra` | `mlops-infra-service` |
| 11 | Airflow | `mlops-infra` | `mlops-infra-service` |
| 12 | Image nền `ml-base` | `mlops-infra` | `mlops-infra-service` |
| 13 | Tài liệu và xác nhận | — (chạy trực tiếp) | `mlops-verify` |

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

| File | Trách nhiệm |
| --- | --- |
| `common/pyproject.toml` | Khai báo package `ml_common`, dependency, cấu hình pytest + ruff |
| `common/ml_common/schema.py` | Nguồn sự thật duy nhất về cột, kiểu, ràng buộc, cột leakage. Không import pandas ở mức module. |
| `common/ml_common/parsers.py` | Hàm parse thuần cho từng giá trị đơn lẻ (tiền, bool, ngày, zipcode, text). Không biết gì về pandas hay sklearn. |
| `common/ml_common/cleaning.py` | Các sklearn transformer áp parser lên DataFrame theo cột. Chỉ thao tác theo cột. |
| `common/ml_common/rowops.py` | Thao tác theo dòng (dedup, loại dòng hỏng). Tách riêng để không ai vô tình đưa vào Pipeline. |
| `common/ml_common/features.py` | Dựng `Pipeline` hoàn chỉnh theo `task_type` |
| `common/ml_common/storage.py` | Wrapper boto3 + toàn bộ convention đường dẫn MinIO/S3 |
| `common/ml_common/profiling.py` | Tính baseline profile từ DataFrame |
| `common/tests/` | Test cho từng module trên |
| `docker-compose.yml` | Postgres, MinIO, MLflow, Airflow |
| `docker/postgres/init-databases.sql` | Tạo database `mlflow` bên cạnh `airflow` |
| `docker/mlflow/Dockerfile` | MLflow + psycopg2 + boto3 |
| `stages/base/Dockerfile` | Image nền cho mọi stage: Python 3.12 + ml_common |
| `.env.example` | Mẫu biến môi trường |

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
description = "Logic dùng chung cho MLOps house pricing pipeline"
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
printf '"""Logic dung chung cho MLOps house pricing pipeline."""\n\n__version__ = "0.1.0"\n' > common/ml_common/__init__.py
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

# Serving (dùng từ Plan 3)
SERVING_URL=http://serving:8000

# Dev: giới hạn số dòng đọc từ raw data. Để trống = đọc toàn bộ ~2 triệu dòng.
# Máy 16GB RAM nên để 200000 khi phát triển, xoá đi khi chạy thật.
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


def test_co_du_24_cot():
    assert len(schema.COLUMNS) == 24


def test_moi_cot_co_kind_hop_le():
    hop_le = {"id", "numeric", "categorical", "boolean", "date", "money", "zipcode"}
    for name, spec in schema.COLUMNS.items():
        assert spec.kind in hop_le, f"{name} co kind khong hop le: {spec.kind}"


def test_regression_loai_bo_cot_leakage_va_list_price():
    cols = schema.feature_columns("regression")
    assert "sale_price" not in cols, "target khong duoc la feature"
    assert "price_category" not in cols, "price_category suy ra tu sale_price"
    assert "list_price" not in cols, "list_price lam bai toan tro nen tam thuong"
    assert "days_on_market" in cols, "days_on_market hop le voi bai regression"


def test_classification_loai_bo_cot_leakage_nhung_giu_list_price():
    cols = schema.feature_columns("classification")
    assert "sold_within_30_days" not in cols
    assert "days_on_market" not in cols, "sold_within_30_days suy truc tiep tu day"
    assert "sale_price" not in cols, "chi biet sau khi ban"
    assert "price_category" not in cols
    assert "list_price" in cols, "gia rao biet truoc khi ban, la tin hieu hop le"


def test_khong_co_id_trong_feature():
    for task in ("regression", "classification"):
        assert schema.ID_COLUMN not in schema.feature_columns(task)


def test_task_type_sai_thi_bao_loi():
    with pytest.raises(ValueError, match="task_type"):
        schema.feature_columns("clustering")


def test_columns_of_kind_tra_ve_dung():
    assert set(schema.columns_of_kind("money")) == {"list_price", "sale_price"}
    assert set(schema.columns_of_kind("boolean")) == {"has_pool", "sold_within_30_days"}
    assert schema.columns_of_kind("date") == ["listing_date"]


def test_rang_buoc_so_hoc_hop_ly():
    assert schema.COLUMNS["bedrooms"].min_value == 0
    assert schema.COLUMNS["bedrooms"].max_value == 20
    assert schema.COLUMNS["school_rating"].min_value == 1
    assert schema.COLUMNS["school_rating"].max_value == 10
    assert schema.COLUMNS["distance_to_city_center_km"].min_value == 0


def test_year_built_max_la_nam_hien_tai():
    from datetime import date

    assert schema.COLUMNS["year_built"].max_value == date.today().year


def test_gia_tri_allowed_da_duoc_chuan_hoa():
    for name, spec in schema.COLUMNS.items():
        if spec.allowed is None:
            continue
        for gia_tri in spec.allowed:
            assert gia_tri == gia_tri.strip().lower(), f"{name}: {gia_tri!r} chua chuan hoa"
            assert "_" not in gia_tri and "-" not in gia_tri, f"{name}: {gia_tri!r} con dau noi"
```

- [ ] **Step 2: Chạy test để xác nhận nó thất bại**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_schema.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.schema'`

- [ ] **Step 3: Viết `common/ml_common/schema.py`**

```python
"""Nguon su that duy nhat ve schema cua dataset house pricing.

Duoc dung boi stage `validate` (kiem tra du lieu tho) va boi serving
(kiem tra record gui vao /predict). Khong import pandas o muc module de
file nay nhe va import duoc tu bat ky dau.
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
    """Mo ta mot cot: kieu du lieu logic va rang buoc gia tri hop le."""

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

# Cot phai loai khoi feature, theo tung bai toan.
# Xem muc 5 cua tai lieu thiet ke de biet ly do tung cot.
_EXCLUDED: dict[str, frozenset[str]] = {
    "regression": frozenset(
        {
            ID_COLUMN,
            TARGET_REGRESSION,
            "price_category",  # suy truc tiep tu sale_price
            "list_price",  # hop le ve mat thoi gian nhung lam bai toan tam thuong
        }
    ),
    "classification": frozenset(
        {
            ID_COLUMN,
            TARGET_CLASSIFICATION,
            "days_on_market",  # sold_within_30_days suy truc tiep tu day
            "sale_price",  # chi biet sau khi ban
            "price_category",  # suy ra tu sale_price
        }
    ),
}


def feature_columns(task_type: str) -> list[str]:
    """Danh sach cot dung lam feature cho mot bai toan, da loai leakage."""
    if task_type not in TASK_TYPES:
        raise ValueError(f"task_type phai thuoc {TASK_TYPES}, nhan duoc: {task_type!r}")
    excluded = _EXCLUDED[task_type]
    return [name for name in COLUMNS if name not in excluded]


def columns_of_kind(kind: str) -> list[str]:
    """Danh sach cot theo kieu logic, giu nguyen thu tu khai bao."""
    return [name for name, spec in COLUMNS.items() if spec.kind == kind]


def target_column(task_type: str) -> str:
    """Ten cot target cua mot bai toan."""
    if task_type not in TASK_TYPES:
        raise ValueError(f"task_type phai thuoc {TASK_TYPES}, nhan duoc: {task_type!r}")
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


# --- Dirty type 6: lan lon so va chuoi "$xxx,xxx" ---

@pytest.mark.parametrize(
    "dau_vao,mong_doi",
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
def test_parse_money_cac_dinh_dang(dau_vao, mong_doi):
    assert parsers.parse_money(dau_vao) == mong_doi


@pytest.mark.parametrize("dau_vao", [None, "", "   ", np.nan, "khong phai so", "$"])
def test_parse_money_gia_tri_khong_hop_le_tra_ve_none(dau_vao):
    assert parsers.parse_money(dau_vao) is None


# --- Dirty type 4: has_pool co 8 cach bieu dien ---

@pytest.mark.parametrize(
    "dau_vao,mong_doi",
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
def test_parse_bool_moi_cach_bieu_dien(dau_vao, mong_doi):
    assert parsers.parse_bool(dau_vao) is mong_doi


@pytest.mark.parametrize("dau_vao", [None, "", "   ", np.nan, "maybe", "2"])
def test_parse_bool_gia_tri_khong_hop_le_tra_ve_none(dau_vao):
    assert parsers.parse_bool(dau_vao) is None


# --- Dirty type 5: listing_date co 3 format ---

@pytest.mark.parametrize(
    "dau_vao,mong_doi",
    [
        ("2023-07-15", date(2023, 7, 15)),
        ("07/15/2023", date(2023, 7, 15)),
        ("15-Jul-2023", date(2023, 7, 15)),
        ("  2023-07-15  ", date(2023, 7, 15)),
        ("01/02/2023", date(2023, 1, 2)),  # MM/DD, khong phai DD/MM
        ("03-Mar-2020", date(2020, 3, 3)),
    ],
)
def test_parse_date_ba_format(dau_vao, mong_doi):
    assert parsers.parse_date(dau_vao) == mong_doi


@pytest.mark.parametrize("dau_vao", [None, "", "   ", np.nan, "khong phai ngay", "2023-13-45"])
def test_parse_date_gia_tri_khong_hop_le_tra_ve_none(dau_vao):
    assert parsers.parse_date(dau_vao) is None


def test_parse_date_chap_nhan_doi_tuong_date_san_co():
    assert parsers.parse_date(date(2023, 7, 15)) == date(2023, 7, 15)


# --- Dirty type 8: zipcode thieu hoac bi cat con 4 so ---

@pytest.mark.parametrize(
    "dau_vao,mong_doi",
    [
        ("90210", "90210"),
        ("  90210  ", "90210"),
        (90210, "90210"),
        ("02134", "02134"),  # so 0 dau khong duoc mat
    ],
)
def test_parse_zipcode_hop_le(dau_vao, mong_doi):
    assert parsers.parse_zipcode(dau_vao) == mong_doi


@pytest.mark.parametrize("dau_vao", [None, "", "9021", "902101", "abcde", np.nan, 9021])
def test_parse_zipcode_sai_dinh_dang_tra_ve_none(dau_vao):
    assert parsers.parse_zipcode(dau_vao) is None


def test_parse_zipcode_so_nguyen_mat_so_0_dau_van_duoc_khoi_phuc():
    # 2134 trong CSV rat co the la 02134 bi Excel an mat so 0 dau.
    # Ta KHONG doan: tra ve None de validate dem duoc va bao cao.
    assert parsers.parse_zipcode(2134) is None


# --- Dirty type 3: categorical lan lon hoa/thuong/gach ---

@pytest.mark.parametrize(
    "dau_vao,mong_doi",
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
        ("New   York", "new york"),  # nhieu khoang trang -> mot
        ("CA", "ca"),
    ],
)
def test_normalize_text(dau_vao, mong_doi):
    assert parsers.normalize_text(dau_vao) == mong_doi


@pytest.mark.parametrize("dau_vao", [None, "", "   ", np.nan])
def test_normalize_text_rong_tra_ve_none(dau_vao):
    assert parsers.normalize_text(dau_vao) is None


def test_moi_bien_the_multi_family_deu_ra_cung_mot_gia_tri():
    bien_the = ["Multi-Family", "MULTI FAMILY", "multi_family", "  Multi Family  "]
    ket_qua = {parsers.normalize_text(v) for v in bien_the}
    assert ket_qua == {"multi family"}
```

- [ ] **Step 2: Chạy test để xác nhận nó thất bại**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_parsers.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.parsers'`

- [ ] **Step 3: Viết `common/ml_common/parsers.py`**

```python
"""Ham parse cho tung gia tri don le.

Moi ham nhan mot gia tri bat ky (chuoi, so, None, NaN) va tra ve gia tri
da chuan hoa, hoac None neu khong parse duoc. Khong bao gio nem exception
va khong bao gio doan: gia tri mo ho thi tra None de stage `validate` dem
duoc va bao cao.

Module nay khong import pandas hay sklearn — chi la ham thuan, test bang
bang tham so.
"""

from __future__ import annotations

import re
from datetime import date, datetime

_MONEY_KY_TU_THUA = re.compile(r"[$,\s]")
_CHI_CO_SO = re.compile(r"^-?\d+(\.\d+)?$")
_ZIPCODE_HOP_LE = re.compile(r"^\d{5}$")
_NHIEU_KHOANG_TRANG = re.compile(r"\s+")

_BOOL_THAT = {"yes", "y", "1", "true", "t"}
_BOOL_GIA = {"no", "n", "0", "false", "f"}

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y")


def _la_rong(value: object) -> bool:
    """True neu gia tri coi nhu thieu: None, NaN, chuoi rong hoac toan khoang trang."""
    if value is None:
        return True
    # NaN la so thuc duy nhat khong bang chinh no.
    if isinstance(value, float) and value != value:
        return True
    return isinstance(value, str) and not value.strip()


def parse_money(value: object) -> float | None:
    """Parse gia tien: '$450,000' -> 450000.0. Tra None neu khong parse duoc.

    Xu ly dirty type 6: cung mot cot vua co so thuan vua co chuoi dinh dang tien.
    """
    if _la_rong(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _MONEY_KY_TU_THUA.sub("", str(value))
    if not _CHI_CO_SO.match(text):
        return None
    return float(text)


def parse_bool(value: object) -> bool | None:
    """Parse boolean tu 8 cach bieu dien. Tra None neu khong parse duoc.

    Xu ly dirty type 4: has_pool co Yes/No/Y/N/1/0/True/False.
    """
    if _la_rong(value):
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
    if text in _BOOL_THAT:
        return True
    if text in _BOOL_GIA:
        return False
    return None


def parse_date(value: object) -> date | None:
    """Parse ngay tu 3 format lan lon. Tra None neu khong parse duoc.

    Xu ly dirty type 5: YYYY-MM-DD, MM/DD/YYYY, DD-Mon-YYYY.
    Thu lan luot tung format thay vi dung dateutil: nhanh hon nhieu lan tren
    2 trieu dong, va khong bao gio doan nham DD/MM thanh MM/DD.
    """
    if _la_rong(value):
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
    """Parse zipcode 5 so. Tra None neu thieu hoac sai dinh dang.

    Xu ly dirty type 8. Zipcode 4 so tra ve None thay vi doan them so 0 dau:
    doan se tao ra du lieu sai ma khong ai biet, con None thi stage `validate`
    dem duoc va bao cao.
    """
    if _la_rong(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if value != int(value):
            return None
        value = int(value)
    text = str(value).strip()
    if not _ZIPCODE_HOP_LE.match(text):
        return None
    return text


def normalize_text(value: object) -> str | None:
    """Chuan hoa gia tri categorical ve chu thuong, dau cach don.

    Xu ly dirty type 3: 'NEW YORK', 'new_york', 'New-York', '  New York  '
    deu ra 'new york'. Gach duoi va gach noi doi thanh dau cach de moi bien
    the cua 'Multi-Family' hoi tu ve cung mot gia tri.
    """
    if _la_rong(value):
        return None
    text = str(value).strip().lower()
    text = text.replace("_", " ").replace("-", " ")
    text = _NHIEU_KHOANG_TRANG.sub(" ", text).strip()
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
def df_ban():
    """Mot DataFrame nho chua du cac loai dirty."""
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
    def test_khong_bao_gio_xoa_dong(self, df_ban):
        ket_qua = cleaning.RawRecordCleaner().fit_transform(df_ban)
        assert len(ket_qua) == len(df_ban)

    def test_hoat_dong_voi_mot_dong_duy_nhat(self, df_ban):
        """Serving goi /predict voi mot record — phai chay duoc."""
        mot_dong = df_ban.head(1)
        ket_qua = cleaning.RawRecordCleaner().fit_transform(mot_dong)
        assert len(ket_qua) == 1

    def test_parse_cot_tien(self, df_ban):
        ket_qua = cleaning.RawRecordCleaner().fit_transform(df_ban)
        assert ket_qua["list_price"].tolist() == [450000.0, 500000.0, 1250000.0]
        assert ket_qua["sale_price"].tolist() == [440000.0, 490000.0, 1200000.0]

    def test_chuan_hoa_categorical(self, df_ban):
        ket_qua = cleaning.RawRecordCleaner().fit_transform(df_ban)
        assert ket_qua["city"].tolist() == ["new york", "new york", "new york"]
        assert ket_qua["state"].tolist() == ["ny", "ny", "ny"]
        assert ket_qua["property_type"].tolist() == [
            "single family",
            "multi family",
            "multi family",
        ]

    def test_parse_boolean(self, df_ban):
        ket_qua = cleaning.RawRecordCleaner().fit_transform(df_ban)
        assert ket_qua["has_pool"].tolist() == [True, False, True]

    def test_zipcode_sai_thanh_none(self, df_ban):
        ket_qua = cleaning.RawRecordCleaner().fit_transform(df_ban)
        assert ket_qua["zipcode"].tolist() == ["10001", None, None]

    def test_parse_ngay_ba_format_ra_cung_mot_ngay(self, df_ban):
        ket_qua = cleaning.RawRecordCleaner().fit_transform(df_ban)
        ngay = pd.to_datetime(ket_qua["listing_date"])
        assert ngay.nunique() == 1

    def test_khong_sua_doi_dataframe_dau_vao(self, df_ban):
        ban_sao = df_ban.copy(deep=True)
        cleaning.RawRecordCleaner().fit_transform(df_ban)
        pd.testing.assert_frame_equal(df_ban, ban_sao)

    def test_cot_thieu_thi_bo_qua_khong_nem_loi(self):
        """Serving co the nhan record thieu cot tuy chon."""
        df = pd.DataFrame({"city": ["NEW YORK"], "list_price": ["$100,000"]})
        ket_qua = cleaning.RawRecordCleaner().fit_transform(df)
        assert ket_qua["city"].tolist() == ["new york"]
        assert ket_qua["list_price"].tolist() == [100000.0]

    def test_cot_ngoai_schema_duoc_giu_nguyen(self):
        df = pd.DataFrame({"city": ["NEW YORK"], "cot_la": [42]})
        ket_qua = cleaning.RawRecordCleaner().fit_transform(df)
        assert ket_qua["cot_la"].tolist() == [42]


class TestOutlierClipper:
    def test_clip_ve_bien_cua_schema(self, df_ban):
        da_sach = cleaning.RawRecordCleaner().fit_transform(df_ban)
        ket_qua = cleaning.OutlierClipper().fit_transform(da_sach)
        # bedrooms: -1 -> 0, 25 -> 20
        assert ket_qua["bedrooms"].tolist() == [3.0, 0.0, 20.0]
        # bathrooms: 50 -> 15
        assert ket_qua["bathrooms"].tolist() == [2.0, 1.5, 15.0]
        # distance: -3 -> 0
        assert ket_qua["distance_to_city_center_km"].tolist() == [5.0, 0.0, 10.0]

    def test_nam_xay_tuong_lai_bi_clip(self, df_ban):
        from datetime import date

        da_sach = cleaning.RawRecordCleaner().fit_transform(df_ban)
        ket_qua = cleaning.OutlierClipper().fit_transform(da_sach)
        assert ket_qua["year_built"].max() <= date.today().year
        assert ket_qua["year_built"].min() >= 1800

    def test_dien_tich_bat_thuong_bi_clip(self, df_ban):
        da_sach = cleaning.RawRecordCleaner().fit_transform(df_ban)
        ket_qua = cleaning.OutlierClipper().fit_transform(da_sach)
        assert ket_qua["living_area_sqft"].max() <= 50_000

    def test_khong_xoa_dong(self, df_ban):
        da_sach = cleaning.RawRecordCleaner().fit_transform(df_ban)
        ket_qua = cleaning.OutlierClipper().fit_transform(da_sach)
        assert len(ket_qua) == len(df_ban)

    def test_gia_tri_thieu_van_la_thieu_sau_khi_clip(self):
        df = pd.DataFrame({"bedrooms": [np.nan, 3.0]})
        ket_qua = cleaning.OutlierClipper().fit_transform(df)
        assert pd.isna(ket_qua["bedrooms"].iloc[0])


class TestDateFeatures:
    def test_tach_nam_va_thang(self, df_ban):
        da_sach = cleaning.RawRecordCleaner().fit_transform(df_ban)
        ket_qua = cleaning.DateFeatures().fit_transform(da_sach)
        assert ket_qua["listing_year"].tolist() == [2023, 2023, 2023]
        assert ket_qua["listing_month"].tolist() == [7, 7, 7]

    def test_bo_cot_ngay_goc(self, df_ban):
        da_sach = cleaning.RawRecordCleaner().fit_transform(df_ban)
        ket_qua = cleaning.DateFeatures().fit_transform(da_sach)
        assert "listing_date" not in ket_qua.columns

    def test_ngay_thieu_thanh_nan_khong_nem_loi(self):
        df = pd.DataFrame({"listing_date": [None, pd.Timestamp("2023-07-15")]})
        ket_qua = cleaning.DateFeatures().fit_transform(df)
        assert pd.isna(ket_qua["listing_year"].iloc[0])
        assert ket_qua["listing_year"].iloc[1] == 2023
```

- [ ] **Step 2: Chạy test để xác nhận nó thất bại**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_cleaning.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.cleaning'`

- [ ] **Step 3: Viết `common/ml_common/cleaning.py`**

```python
"""Transformer lam sach du lieu — CHI thao tac theo cot.

Cac transformer o day nam trong sklearn Pipeline va duoc dong goi cung
model vao MLflow, nen chung chay o CA HAI noi: stage `preprocess` (tren 2
trieu dong) va serving (tren mot record don le).

Vi vay chung TUYET DOI khong duoc xoa dong. Thao tac theo dong nam o
`rowops.py`. Xem Global Constraints cua plan.
"""

from __future__ import annotations

import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

from ml_common import parsers, schema

_PARSER_THEO_KIND = {
    "money": parsers.parse_money,
    "boolean": parsers.parse_bool,
    "date": parsers.parse_date,
    "zipcode": parsers.parse_zipcode,
    "categorical": parsers.normalize_text,
}


class RawRecordCleaner(BaseEstimator, TransformerMixin):
    """Ap parser phu hop len tung cot theo `kind` khai bao trong schema.

    Cot khong co trong schema duoc giu nguyen. Cot co trong schema nhung
    vang mat trong DataFrame duoc bo qua — serving co the nhan record
    thieu cot tuy chon.
    """

    def fit(self, X: pd.DataFrame, y=None) -> RawRecordCleaner:  # noqa: N803
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        ket_qua = X.copy()
        for ten_cot, spec in schema.COLUMNS.items():
            if ten_cot not in ket_qua.columns:
                continue
            parser = _PARSER_THEO_KIND.get(spec.kind)
            if parser is None:
                continue
            ket_qua[ten_cot] = [parser(gia_tri) for gia_tri in ket_qua[ten_cot]]
        return ket_qua


class OutlierClipper(BaseEstimator, TransformerMixin):
    """Cat gia tri so ve trong khoang [min_value, max_value] cua schema.

    Chon clip thay vi xoa dong vi hai ly do: serving khong the xoa dong, va
    mot can nha co `bedrooms = -1` van con thong tin huu ich o cac cot khac.
    Gia tri thieu van giu nguyen la thieu.
    """

    def fit(self, X: pd.DataFrame, y=None) -> OutlierClipper:  # noqa: N803
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        ket_qua = X.copy()
        for ten_cot, spec in schema.COLUMNS.items():
            if ten_cot not in ket_qua.columns:
                continue
            if spec.min_value is None and spec.max_value is None:
                continue
            chuoi_so = pd.to_numeric(ket_qua[ten_cot], errors="coerce")
            ket_qua[ten_cot] = chuoi_so.clip(lower=spec.min_value, upper=spec.max_value)
        return ket_qua


class DateFeatures(BaseEstimator, TransformerMixin):
    """Doi `listing_date` thanh `listing_year` + `listing_month`.

    Model cay khong dung truc tiep duoc kieu datetime, va nam/thang la hai
    tin hieu co y nghia thuc te (chu ky thi truong, mua cao diem).
    """

    def fit(self, X: pd.DataFrame, y=None) -> DateFeatures:  # noqa: N803
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:  # noqa: N803
        ket_qua = X.copy()
        if "listing_date" not in ket_qua.columns:
            return ket_qua
        ngay = pd.to_datetime(ket_qua["listing_date"], errors="coerce")
        ket_qua["listing_year"] = ngay.dt.year
        ket_qua["listing_month"] = ngay.dt.month
        return ket_qua.drop(columns=["listing_date"])
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


def test_drop_duplicates_xoa_dong_trung_property_id():
    df = pd.DataFrame(
        {
            "property_id": [1, 2, 2, 3],
            "city": ["a", "b", "b", "c"],
        }
    )
    ket_qua, so_dong_xoa = rowops.drop_duplicates(df)
    assert len(ket_qua) == 3
    assert so_dong_xoa == 1
    assert ket_qua["property_id"].tolist() == [1, 2, 3]


def test_drop_duplicates_giu_dong_dau_tien():
    df = pd.DataFrame({"property_id": [1, 1], "city": ["dau", "sau"]})
    ket_qua, _ = rowops.drop_duplicates(df)
    assert ket_qua["city"].tolist() == ["dau"]


def test_drop_duplicates_khong_co_trung_thi_giu_nguyen():
    df = pd.DataFrame({"property_id": [1, 2, 3]})
    ket_qua, so_dong_xoa = rowops.drop_duplicates(df)
    assert len(ket_qua) == 3
    assert so_dong_xoa == 0


def test_drop_duplicates_index_duoc_danh_lai():
    df = pd.DataFrame({"property_id": [1, 1, 2]})
    ket_qua, _ = rowops.drop_duplicates(df)
    assert ket_qua.index.tolist() == [0, 1]


def test_drop_rows_missing_target_regression():
    df = pd.DataFrame({"sale_price": [100.0, np.nan, 300.0], "city": ["a", "b", "c"]})
    ket_qua, so_dong_xoa = rowops.drop_rows_missing_target(df, "regression")
    assert len(ket_qua) == 2
    assert so_dong_xoa == 1


def test_drop_rows_missing_target_classification():
    df = pd.DataFrame({"sold_within_30_days": [True, None, False]})
    ket_qua, so_dong_xoa = rowops.drop_rows_missing_target(df, "classification")
    assert len(ket_qua) == 2
    assert so_dong_xoa == 1


def test_drop_rows_missing_target_thieu_cot_target_thi_bao_loi():
    df = pd.DataFrame({"city": ["a"]})
    with pytest.raises(KeyError, match="sale_price"):
        rowops.drop_rows_missing_target(df, "regression")


def test_drop_rows_missing_target_task_type_sai_thi_bao_loi():
    df = pd.DataFrame({"sale_price": [1.0]})
    with pytest.raises(ValueError, match="task_type"):
        rowops.drop_rows_missing_target(df, "clustering")
```

- [ ] **Step 2: Chạy test để xác nhận nó thất bại**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_rowops.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.rowops'`

- [ ] **Step 3: Viết `common/ml_common/rowops.py`**

```python
"""Thao tac theo DONG — chi duoc goi tu stage `preprocess`.

File nay tach rieng khoi `cleaning.py` mot cach co chu y: cac ham o day
xoa dong, nen chung KHONG BAO GIO duoc dat vao sklearn Pipeline. Serving
goi /predict voi mot record don le; mot buoc xoa dong se tra ve DataFrame
rong va lam serving sap.

Ranh gioi file chinh la co che bao ve — khong ai vo tinh import nham.
"""

from __future__ import annotations

import pandas as pd

from ml_common import schema


def drop_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Xoa dong trung `property_id`, giu dong dau tien.

    Xu ly dirty type 2 (~0.6% dong bi lap). Tra ve (df moi, so dong da xoa)
    de stage `preprocess` log duoc con so nay.
    """
    so_dong_truoc = len(df)
    ket_qua = df.drop_duplicates(subset=[schema.ID_COLUMN], keep="first").reset_index(drop=True)
    return ket_qua, so_dong_truoc - len(ket_qua)


def drop_rows_missing_target(df: pd.DataFrame, task_type: str) -> tuple[pd.DataFrame, int]:
    """Xoa dong khong co gia tri target — khong train duoc tren chung.

    Tra ve (df moi, so dong da xoa).
    """
    cot_target = schema.target_column(task_type)
    if cot_target not in df.columns:
        raise KeyError(f"Thieu cot target {cot_target!r} trong DataFrame")
    so_dong_truoc = len(df)
    ket_qua = df[df[cot_target].notna()].reset_index(drop=True)
    return ket_qua, so_dong_truoc - len(ket_qua)
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
def df_tho():
    """Du lieu THO — dung nhu du lieu that truoc khi lam sach."""
    so_dong = 40
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "property_id": range(so_dong),
            "listing_date": ["2023-07-15", "07/15/2023"] * (so_dong // 2),
            "city": ["NEW YORK", "new_york", "  Boston ", "BOSTON"] * (so_dong // 4),
            "state": ["NY", "ny", "MA", "ma"] * (so_dong // 4),
            "zipcode": ["10001", "1000"] * (so_dong // 2),
            "property_type": ["Single_Family", "MULTI FAMILY"] * (so_dong // 2),
            "lot_size_sqft": rng.uniform(1000, 9000, so_dong),
            "living_area_sqft": rng.uniform(800, 4000, so_dong),
            "bedrooms": rng.integers(1, 6, so_dong).astype(float),
            "bathrooms": rng.choice([1.0, 1.5, 2.0, 2.5], so_dong),
            "year_built": rng.integers(1950, 2020, so_dong).astype(float),
            "stories": rng.integers(1, 4, so_dong).astype(float),
            "garage_spaces": rng.integers(0, 3, so_dong).astype(float),
            "has_pool": ["Yes", "N", "1", "False"] * (so_dong // 4),
            "hoa_fee_monthly": rng.uniform(0, 400, so_dong),
            "school_rating": rng.uniform(1, 10, so_dong),
            "crime_index": rng.uniform(0, 100, so_dong),
            "distance_to_city_center_km": rng.uniform(0, 40, so_dong),
            "condition": ["Good", "EXCELLENT", "poor", "Fair"] * (so_dong // 4),
            "days_on_market": rng.integers(1, 200, so_dong),
            "list_price": ["$450,000", 500000] * (so_dong // 2),
            "sale_price": [440000, "$490,000"] * (so_dong // 2),
            "price_category": ["Medium", "High"] * (so_dong // 2),
            "sold_within_30_days": ["Yes", "No"] * (so_dong // 2),
        }
    )


def test_tra_ve_pipeline_cua_sklearn():
    ket_qua = features.build_pipeline("regression", DummyRegressor())
    assert isinstance(ket_qua, Pipeline)


def test_task_type_sai_thi_bao_loi():
    with pytest.raises(ValueError, match="task_type"):
        features.build_pipeline("clustering", DummyRegressor())


def test_regression_fit_va_predict_tren_du_lieu_THO(df_tho):
    """Day la dam bao quan trong nhat: Pipeline nhan du lieu tho, khong can
    lam sach truoc. Neu test nay pass thi serving goi /predict voi record
    tho se chay dung."""
    pipeline = features.build_pipeline("regression", DummyRegressor())
    X = df_tho.drop(columns=["sale_price"])
    y = pd.to_numeric(df_tho["sale_price"].astype(str).str.replace(r"[$,]", "", regex=True))
    pipeline.fit(X, y)
    du_doan = pipeline.predict(X)
    assert len(du_doan) == len(df_tho)


def test_classification_fit_va_predict_tren_du_lieu_THO(df_tho):
    pipeline = features.build_pipeline("classification", DummyClassifier())
    X = df_tho.drop(columns=["sold_within_30_days"])
    y = df_tho["sold_within_30_days"].map({"Yes": 1, "No": 0})
    pipeline.fit(X, y)
    du_doan = pipeline.predict(X)
    assert len(du_doan) == len(df_tho)


def test_predict_duoc_voi_MOT_record(df_tho):
    """Serving nhan mot record don le."""
    pipeline = features.build_pipeline("regression", DummyRegressor())
    X = df_tho.drop(columns=["sale_price"])
    y = pd.to_numeric(df_tho["sale_price"].astype(str).str.replace(r"[$,]", "", regex=True))
    pipeline.fit(X, y)
    du_doan = pipeline.predict(X.head(1))
    assert len(du_doan) == 1


def test_cot_leakage_khong_lot_vao_pipeline(df_tho):
    """price_category va list_price khong duoc anh huong model regression.

    Dung DecisionTreeRegressor chu KHONG dung DummyRegressor: Dummy bo qua
    moi feature nen se pass du Pipeline co bug, cho ta niem tin gia.
    """
    from sklearn.tree import DecisionTreeRegressor

    pipeline = features.build_pipeline("regression", DecisionTreeRegressor(random_state=0))
    X = df_tho.drop(columns=["sale_price"])
    y = pd.to_numeric(df_tho["sale_price"].astype(str).str.replace(r"[$,]", "", regex=True))
    pipeline.fit(X, y)

    X_doi = X.copy()
    X_doi["price_category"] = "Luxury"
    X_doi["list_price"] = "$9,999,999"
    np.testing.assert_array_equal(pipeline.predict(X), pipeline.predict(X_doi))


def test_selectcolumns_that_su_loai_bo_cot_leakage():
    """Kiem tra truc tiep danh sach cot, khong qua ket qua predict."""
    from sklearn.dummy import DummyRegressor as _Dummy

    pipeline = features.build_pipeline("regression", _Dummy())
    cot_duoc_chon = pipeline.named_steps["chon_cot"].columns
    assert "price_category" not in cot_duoc_chon
    assert "list_price" not in cot_duoc_chon
    assert "sale_price" not in cot_duoc_chon
    assert "property_id" not in cot_duoc_chon
    assert "living_area_sqft" in cot_duoc_chon


def test_gia_tri_categorical_chua_tung_thay_khong_lam_sap(df_tho):
    """Agent o Plan 4 se gui property_type moi (drift_scenario=new_segment)."""
    pipeline = features.build_pipeline("regression", DummyRegressor())
    X = df_tho.drop(columns=["sale_price"])
    y = pd.to_numeric(df_tho["sale_price"].astype(str).str.replace(r"[$,]", "", regex=True))
    pipeline.fit(X, y)

    X_moi = X.head(1).copy()
    X_moi["property_type"] = "Houseboat"
    X_moi["city"] = "Atlantis"
    du_doan = pipeline.predict(X_moi)
    assert len(du_doan) == 1


def test_gia_tri_thieu_khong_lam_sap(df_tho):
    pipeline = features.build_pipeline("regression", DummyRegressor())
    X = df_tho.drop(columns=["sale_price"])
    y = pd.to_numeric(df_tho["sale_price"].astype(str).str.replace(r"[$,]", "", regex=True))
    pipeline.fit(X, y)

    X_thieu = X.head(1).copy()
    for cot in ["bedrooms", "bathrooms", "year_built", "school_rating", "hoa_fee_monthly"]:
        X_thieu[cot] = np.nan
    du_doan = pipeline.predict(X_thieu)
    assert len(du_doan) == 1
```

- [ ] **Step 2: Chạy test để xác nhận nó thất bại**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_features.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.features'`

- [ ] **Step 3: Viết `common/ml_common/features.py`**

```python
"""Dung sklearn Pipeline hoan chinh cho tung bai toan.

Pipeline tra ve tu day duoc log nguyen ven vao MLflow o stage `train`, nen
no phai TU CHUA toan bo logic lam sach: model trong Registry nhan record
THO va tu xu ly. Day la co che chong training/serving skew — xem muc 7.1
cua tai lieu thiet ke.
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
    """Giu lai dung danh sach cot, theo dung thu tu.

    Cot thieu duoc them vao voi gia tri None. Nho vay serving khong sap khi
    nguoi goi quen mot cot tuy chon, va cot leakage bi loai bo triet de du
    nguoi goi co gui len.
    """

    def __init__(self, columns: list[str]):
        self.columns = columns

    def fit(self, X, y=None):  # noqa: N803
        return self

    def transform(self, X):  # noqa: N803
        ket_qua = X.copy()
        for ten_cot in self.columns:
            if ten_cot not in ket_qua.columns:
                ket_qua[ten_cot] = None
        return ket_qua[self.columns]


def _cot_so_va_cot_chu(task_type: str) -> tuple[list[str], list[str]]:
    """Chia feature thanh nhom so va nhom chu, SAU khi DateFeatures da chay."""
    feature = schema.feature_columns(task_type)
    cot_so: list[str] = []
    cot_chu: list[str] = []
    for ten_cot in feature:
        if ten_cot == "listing_date":
            continue  # da bien thanh listing_year / listing_month
        spec = schema.COLUMNS[ten_cot]
        if spec.kind in ("numeric", "money"):
            cot_so.append(ten_cot)
        elif spec.kind == "boolean":
            cot_so.append(ten_cot)  # True/False -> 1/0
        else:  # categorical, zipcode
            cot_chu.append(ten_cot)
    if "listing_date" in feature:
        cot_so.extend(["listing_year", "listing_month"])
    return cot_so, cot_chu


def build_pipeline(task_type: str, estimator) -> Pipeline:
    """Dung Pipeline day du: lam sach -> chon cot -> ma hoa -> model.

    Args:
        task_type: "regression" hoac "classification".
        estimator: mot estimator cua sklearn, da khoi tao.

    Returns:
        Pipeline nhan DataFrame THO o dau vao.
    """
    if task_type not in schema.TASK_TYPES:
        raise ValueError(
            f"task_type phai thuoc {schema.TASK_TYPES}, nhan duoc: {task_type!r}"
        )

    cot_so, cot_chu = _cot_so_va_cot_chu(task_type)

    nhanh_so = Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]
    )
    nhanh_chu = Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            # handle_unknown="infrequent_if_exist" giu cho serving khong sap
            # khi gap gia tri chua tung thay (agent drift_scenario=new_segment).
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

    ma_hoa = ColumnTransformer(
        [
            ("so", nhanh_so, cot_so),
            ("chu", nhanh_chu, cot_chu),
        ],
        remainder="drop",
    )

    return Pipeline(
        [
            ("lam_sach", RawRecordCleaner()),
            ("clip_outlier", OutlierClipper()),
            ("dac_trung_ngay", DateFeatures()),
            ("chon_cot", SelectColumns(cot_so + cot_chu)),
            ("ma_hoa", ma_hoa),
            ("model", estimator),
        ]
    )
```

- [ ] **Step 4: Chạy test để xác nhận nó pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_features.py -v`
Expected: PASS toàn bộ 9 test

Nếu `test_gia_tri_categorical_chua_tung_thay_khong_lam_sap` thất bại với `Found unknown categories`, kiểm tra lại `handle_unknown` của `OneHotEncoder` — đây chính là lỗi sẽ làm serving sập ở Plan 4.

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

Run: `.venv\Scripts\python.exe -c "import shutil; print(f'{shutil.disk_usage(\"C:/\").free/2**30:.1f} GB trong')"`
Expected: ≥ 8 GB. Nếu ít hơn, dọn đĩa trước — `docker system prune -a` nếu có image cũ không dùng.

- [ ] **Step 2: Tạo `docker/postgres/init-databases.sql`**

Script này chỉ chạy đúng một lần, lúc volume Postgres được khởi tạo lần đầu.

```sql
-- Database `airflow` da duoc tao boi bien POSTGRES_DB.
-- Tao them database rieng cho MLflow: khong dung chung de metadata cua
-- Airflow va cua MLflow khong anh huong lan nhau khi backup hay reset.
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
    image: minio/minio:latest
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
    image: minio/mc:latest
    container_name: mlops-minio-init
    depends_on:
      minio:
        condition: service_healthy
    entrypoint: >
      /bin/sh -c "
      mc alias set local http://minio:9000 ${MINIO_ACCESS_KEY} ${MINIO_SECRET_KEY} &&
      mc mb --ignore-existing local/${ML_BUCKET} &&
      echo 'Bucket ${ML_BUCKET} san sang'
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
Expected: dòng `Bucket ml-pipeline san sang`

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
def kho():
    with mock_aws():
        import boto3

        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        yield storage.Storage(
            endpoint_url=None,
            access_key="test",
            secret_key="test",
            bucket=BUCKET,
        )


class TestDuongDan:
    def test_raw_key(self):
        assert storage.raw_key("v1") == "raw/v1/data.parquet"

    def test_processed_key(self):
        assert storage.processed_key("abc123", "train") == "processed/abc123/train.parquet"
        assert storage.processed_key("abc123", "test") == "processed/abc123/test.parquet"

    def test_processed_key_split_sai_thi_bao_loi(self):
        with pytest.raises(ValueError, match="split"):
            storage.processed_key("abc123", "validation")

    def test_baseline_key(self):
        ket_qua = storage.baseline_key("house_price_regressor", 3)
        assert ket_qua == "monitoring-baseline/house_price_regressor/3/profile.json"

    def test_inference_log_key_phan_vung_theo_ngay(self):
        ket_qua = storage.inference_log_key("house_price_regressor", date(2026, 9, 17), "0001")
        assert ket_qua == "inference-log/house_price_regressor/dt=2026-09-17/part-0001.parquet"

    def test_ground_truth_key_phan_vung_theo_ngay(self):
        ket_qua = storage.ground_truth_key("house_price_regressor", date(2026, 9, 17), "0001")
        assert ket_qua == "ground-truth/house_price_regressor/dt=2026-09-17/part-0001.parquet"

    def test_report_key(self):
        ket_qua = storage.report_key("house_price_regressor", "run-42", "html")
        assert ket_qua == "reports/house_price_regressor/run-42/evidently.html"

    def test_moi_duong_dan_khong_bat_dau_bang_gach_cheo(self):
        cac_key = [
            storage.raw_key("v1"),
            storage.processed_key("a", "train"),
            storage.baseline_key("m", 1),
            storage.inference_log_key("m", date(2026, 1, 1), "0001"),
            storage.ground_truth_key("m", date(2026, 1, 1), "0001"),
            storage.report_key("m", "r", "json"),
        ]
        for key in cac_key:
            assert not key.startswith("/"), f"{key} bat dau bang gach cheo"


class TestStorage:
    def test_ghi_va_doc_parquet_giu_nguyen_du_lieu(self, kho):
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        kho.write_parquet(df, "thu/muc/file.parquet")
        ket_qua = kho.read_parquet("thu/muc/file.parquet")
        pd.testing.assert_frame_equal(df, ket_qua)

    def test_ghi_va_doc_json(self, kho):
        du_lieu = {"ten": "test", "so": 42, "danh_sach": [1, 2, 3]}
        kho.write_json(du_lieu, "thu/muc/file.json")
        assert kho.read_json("thu/muc/file.json") == du_lieu

    def test_exists_dung_voi_key_co_va_khong_co(self, kho):
        kho.write_json({"a": 1}, "co/that.json")
        assert kho.exists("co/that.json") is True
        assert kho.exists("khong/co.json") is False

    def test_list_keys_theo_prefix(self, kho):
        kho.write_json({}, "prefix-a/mot.json")
        kho.write_json({}, "prefix-a/hai.json")
        kho.write_json({}, "prefix-b/ba.json")
        ket_qua = kho.list_keys("prefix-a/")
        assert sorted(ket_qua) == ["prefix-a/hai.json", "prefix-a/mot.json"]

    def test_list_keys_prefix_rong_tra_ve_danh_sach_rong(self, kho):
        assert kho.list_keys("khong-ton-tai/") == []

    def test_doc_key_khong_ton_tai_thi_bao_loi(self, kho):
        with pytest.raises(FileNotFoundError, match="khong/co.parquet"):
            kho.read_parquet("khong/co.parquet")

    def test_ghi_de_key_da_co(self, kho):
        kho.write_json({"phien_ban": 1}, "file.json")
        kho.write_json({"phien_ban": 2}, "file.json")
        assert kho.read_json("file.json") == {"phien_ban": 2}
```

- [ ] **Step 2: Chạy test để xác nhận nó thất bại**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_storage.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.storage'`

- [ ] **Step 3: Viết `common/ml_common/storage.py`**

```python
"""Wrapper boto3 va TOAN BO convention duong dan tren MinIO/S3.

Day la diem duy nhat trong he thong biet ve object storage. Khi migrate
sang S3 that, chi can bo `endpoint_url` — khong file nao khac phai sua.

Khong noi chuoi duong dan thu cong o bat ky dau khac: dung cac ham *_key()
o day. Xem Global Constraints cua plan.
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
    """Duong dan raw data cua mot phien ban dataset."""
    return f"raw/{dataset_version}/data.parquet"


def processed_key(fingerprint: str, split: str) -> str:
    """Duong dan du lieu da xu ly, dat ten theo fingerprint cua raw data.

    Fingerprint lam cache key: `preprocess` skip neu prefix nay da ton tai.
    """
    if split not in _SPLITS:
        raise ValueError(f"split phai thuoc {_SPLITS}, nhan duoc: {split!r}")
    return f"processed/{fingerprint}/{split}.parquet"


def processed_prefix(fingerprint: str) -> str:
    """Prefix chua ca train va test cua mot fingerprint."""
    return f"processed/{fingerprint}/"


def baseline_key(model_name: str, version: int | str) -> str:
    """Profile thong ke cua tap train, gan voi mot model version cu the."""
    return f"monitoring-baseline/{model_name}/{version}/profile.json"


def inference_log_key(model_name: str, day: date, part_id: str) -> str:
    """Mot file log inference, phan vung theo ngay."""
    return f"inference-log/{model_name}/dt={day.isoformat()}/part-{part_id}.parquet"


def inference_log_prefix(model_name: str, day: date) -> str:
    """Prefix chua toan bo log inference cua mot ngay."""
    return f"inference-log/{model_name}/dt={day.isoformat()}/"


def ground_truth_key(model_name: str, day: date, part_id: str) -> str:
    """Mot file ground truth tu /feedback, phan vung theo ngay."""
    return f"ground-truth/{model_name}/dt={day.isoformat()}/part-{part_id}.parquet"


def ground_truth_prefix(model_name: str, day: date) -> str:
    """Prefix chua toan bo ground truth cua mot ngay."""
    return f"ground-truth/{model_name}/dt={day.isoformat()}/"


def report_key(model_name: str, run_id: str, ext: str) -> str:
    """Report Evidently cua mot lan chay monitoring."""
    return f"reports/{model_name}/{run_id}/evidently.{ext}"


class Storage:
    """Doc/ghi parquet va json tren object storage tuong thich S3."""

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
        """Dung Storage tu bien moi truong.

        Trong container dung MINIO_ENDPOINT_INTERNAL (http://minio:9000);
        chay tu may host thi dung MINIO_ENDPOINT (http://localhost:9000).
        """
        endpoint = os.environ.get("MINIO_ENDPOINT_INTERNAL") or os.environ["MINIO_ENDPOINT"]
        return cls(
            endpoint_url=endpoint,
            access_key=os.environ["MINIO_ACCESS_KEY"],
            secret_key=os.environ["MINIO_SECRET_KEY"],
            bucket=os.environ.get("ML_BUCKET", "ml-pipeline"),
        )

    def write_parquet(self, df: pd.DataFrame, key: str) -> None:
        """Ghi DataFrame duoi dang parquet (nen snappy)."""
        bo_dem = io.BytesIO()
        df.to_parquet(bo_dem, index=False, compression="snappy")
        bo_dem.seek(0)
        self._client.put_object(Bucket=self.bucket, Key=key, Body=bo_dem.getvalue())

    def read_parquet(self, key: str) -> pd.DataFrame:
        """Doc mot file parquet thanh DataFrame."""
        try:
            phan_hoi = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as loi:
            if loi.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"Khong tim thay key: {key}") from loi
            raise
        return pd.read_parquet(io.BytesIO(phan_hoi["Body"].read()))

    def write_json(self, obj: dict, key: str) -> None:
        """Ghi mot dict duoi dang JSON UTF-8."""
        noi_dung = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=noi_dung.encode("utf-8"),
            ContentType="application/json",
        )

    def read_json(self, key: str) -> dict:
        """Doc mot file JSON thanh dict."""
        try:
            phan_hoi = self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as loi:
            if loi.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"Khong tim thay key: {key}") from loi
            raise
        return json.loads(phan_hoi["Body"].read().decode("utf-8"))

    def write_bytes(self, data: bytes, key: str, content_type: str) -> None:
        """Ghi bytes tho — dung cho report HTML cua Evidently o Plan 4."""
        self._client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    def exists(self, key: str) -> bool:
        """True neu key ton tai."""
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def list_keys(self, prefix: str) -> list[str]:
        """Danh sach key duoi mot prefix, co phan trang."""
        ket_qua: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for trang in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in trang.get("Contents", []):
                ket_qua.append(obj["Key"])
        return ket_qua
```

- [ ] **Step 4: Chạy test để xác nhận nó pass**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_storage.py -v`
Expected: PASS toàn bộ 15 test

- [ ] **Step 5: Kiểm tra thủ công với MinIO thật**

Test ở Step 4 dùng `moto` (S3 giả lập trong bộ nhớ). Bước này xác nhận nó nói chuyện được với MinIO thật.

Tạo `scripts/smoke_storage.py`:

```python
"""Smoke test: ghi va doc mot file parquet tren MinIO that."""

import os

import pandas as pd

os.environ["MINIO_ENDPOINT"] = "http://localhost:9000"
os.environ.pop("MINIO_ENDPOINT_INTERNAL", None)  # chay tu host, khong phai trong container
os.environ["MINIO_ACCESS_KEY"] = "minioadmin"
os.environ["MINIO_SECRET_KEY"] = "minioadmin"
os.environ["ML_BUCKET"] = "ml-pipeline"

from ml_common.storage import Storage  # noqa: E402

kho = Storage.from_env()
kho.write_parquet(pd.DataFrame({"a": [1, 2, 3]}), "smoke-test/thu.parquet")
print(kho.read_parquet("smoke-test/thu.parquet"))
print("keys:", kho.list_keys("smoke-test/"))
print("exists:", kho.exists("smoke-test/thu.parquet"))
```

Run: `.venv\Scripts\python.exe scripts\smoke_storage.py`
Expected: in ra DataFrame 3 dòng, danh sách key có `smoke-test/thu.parquet`, và `exists: True`

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
        "<ten_cot>": {
            "kind": "numeric",
            "missing_rate": float,
            "mean": float, "std": float, "min": float, "max": float,
            "quantiles": {"p25": float, "p50": float, "p75": float},
            "histogram": {"bin_edges": [float, ...], "counts": [int, ...]},
        },
        "<ten_cot_khac>": {
            "kind": "categorical",
            "missing_rate": float,
            "n_unique": int,
            "distribution": {"<gia_tri>": float, ...},   # ty le, tong = 1.0
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


def df_mau():
    rng = np.random.default_rng(7)
    return pd.DataFrame(
        {
            "living_area_sqft": rng.uniform(800, 4000, 500),
            "bedrooms": rng.integers(1, 6, 500).astype(float),
            "city": rng.choice(["new york", "boston", "austin"], 500),
            "condition": rng.choice(["good", "fair"], 500),
        }
    )


def test_co_metadata_chung():
    profile = profiling.compute_profile(df_mau(), ["living_area_sqft", "city"])
    assert profile["n_rows"] == 500
    assert isinstance(profile["computed_at"], str)
    assert set(profile["columns"]) == {"living_area_sqft", "city"}


def test_cot_so_co_du_thong_ke():
    profile = profiling.compute_profile(df_mau(), ["living_area_sqft"])
    cot = profile["columns"]["living_area_sqft"]
    assert cot["kind"] == "numeric"
    assert 800 <= cot["mean"] <= 4000
    assert cot["std"] > 0
    assert cot["min"] >= 800
    assert cot["max"] <= 4000
    assert cot["quantiles"]["p25"] < cot["quantiles"]["p50"] < cot["quantiles"]["p75"]


def test_histogram_dung_so_bin():
    profile = profiling.compute_profile(df_mau(), ["living_area_sqft"], n_bins=20)
    hist = profile["columns"]["living_area_sqft"]["histogram"]
    assert len(hist["counts"]) == 20
    assert len(hist["bin_edges"]) == 21
    assert sum(hist["counts"]) == 500


def test_cot_chu_co_phan_phoi_cong_bang_mot():
    profile = profiling.compute_profile(df_mau(), ["city"])
    cot = profile["columns"]["city"]
    assert cot["kind"] == "categorical"
    assert cot["n_unique"] == 3
    assert abs(sum(cot["distribution"].values()) - 1.0) < 1e-9


def test_ty_le_thieu_duoc_tinh_dung():
    df = pd.DataFrame({"bedrooms": [1.0, 2.0, np.nan, np.nan]})
    profile = profiling.compute_profile(df, ["bedrooms"])
    assert profile["columns"]["bedrooms"]["missing_rate"] == 0.5


def test_cot_toan_gia_tri_thieu_khong_lam_sap():
    df = pd.DataFrame({"bedrooms": [np.nan, np.nan]})
    profile = profiling.compute_profile(df, ["bedrooms"])
    cot = profile["columns"]["bedrooms"]
    assert cot["missing_rate"] == 1.0
    assert cot["mean"] is None


def test_cot_khong_co_trong_df_bi_bo_qua():
    profile = profiling.compute_profile(df_mau(), ["city", "cot_khong_ton_tai"])
    assert set(profile["columns"]) == {"city"}


def test_profile_serialise_duoc_thanh_json():
    import json

    profile = profiling.compute_profile(df_mau(), ["living_area_sqft", "city"])
    chuoi = json.dumps(profile)
    assert json.loads(chuoi)["n_rows"] == 500


def test_khong_con_kieu_numpy_trong_ket_qua():
    """Kieu numpy khong serialise duoc bang json chuan."""
    profile = profiling.compute_profile(df_mau(), ["living_area_sqft", "city"])
    cot = profile["columns"]["living_area_sqft"]
    assert type(cot["mean"]) is float
    assert all(type(c) is int for c in cot["histogram"]["counts"])
```

- [ ] **Step 2: Chạy test để xác nhận nó thất bại**

Run: `.venv\Scripts\python.exe -m pytest common/tests/test_profiling.py -v`
Expected: FAIL với `ModuleNotFoundError: No module named 'ml_common.profiling'`

- [ ] **Step 3: Viết `common/ml_common/profiling.py`**

```python
"""Tinh profile thong ke cua mot DataFrame — dung lam baseline cho drift.

Stage `register` goi ham nay tren tap train cua model vua duoc promote, roi
ghi ket qua vao monitoring-baseline/{model}/{version}/profile.json. Nho vay
baseline luon gan voi dung model version da dung no.

Ket qua phai serialise duoc bang `json.dumps` chuan, nen moi kieu numpy
deu duoc doi ve kieu Python goc.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ml_common import schema

_KIND_LA_SO = {"numeric", "money", "boolean"}


def _so_thuc(value) -> float | None:
    """Doi gia tri numpy ve float Python, NaN thanh None."""
    if value is None or pd.isna(value):
        return None
    return float(value)


def _profile_cot_so(chuoi: pd.Series, n_bins: int) -> dict:
    hop_le = pd.to_numeric(chuoi, errors="coerce").dropna()
    ket_qua: dict = {
        "kind": "numeric",
        "missing_rate": float(1 - len(hop_le) / len(chuoi)) if len(chuoi) else 1.0,
        "mean": _so_thuc(hop_le.mean()) if len(hop_le) else None,
        "std": _so_thuc(hop_le.std()) if len(hop_le) else None,
        "min": _so_thuc(hop_le.min()) if len(hop_le) else None,
        "max": _so_thuc(hop_le.max()) if len(hop_le) else None,
        "quantiles": {
            "p25": _so_thuc(hop_le.quantile(0.25)) if len(hop_le) else None,
            "p50": _so_thuc(hop_le.quantile(0.50)) if len(hop_le) else None,
            "p75": _so_thuc(hop_le.quantile(0.75)) if len(hop_le) else None,
        },
        "histogram": {"bin_edges": [], "counts": []},
    }
    if len(hop_le):
        counts, bin_edges = np.histogram(hop_le, bins=n_bins)
        ket_qua["histogram"] = {
            "bin_edges": [float(x) for x in bin_edges],
            "counts": [int(x) for x in counts],
        }
    return ket_qua


def _profile_cot_chu(chuoi: pd.Series) -> dict:
    hop_le = chuoi.dropna()
    phan_phoi = (
        {str(k): float(v) for k, v in hop_le.value_counts(normalize=True).items()}
        if len(hop_le)
        else {}
    )
    return {
        "kind": "categorical",
        "missing_rate": float(1 - len(hop_le) / len(chuoi)) if len(chuoi) else 1.0,
        "n_unique": int(hop_le.nunique()),
        "distribution": phan_phoi,
    }


def compute_profile(df: pd.DataFrame, columns: list[str], n_bins: int = 20) -> dict:
    """Tinh profile thong ke cho cac cot chi dinh.

    Args:
        df: DataFrame da lam sach.
        columns: danh sach cot can profile. Cot khong co trong df bi bo qua.
        n_bins: so bin cua histogram cho cot so.

    Returns:
        Dict serialise duoc bang json.dumps — xem cau truc o phan Interfaces.
    """
    ket_qua_cot: dict[str, dict] = {}
    for ten_cot in columns:
        if ten_cot not in df.columns:
            continue
        spec = schema.COLUMNS.get(ten_cot)
        la_so = spec.kind in _KIND_LA_SO if spec else pd.api.types.is_numeric_dtype(df[ten_cot])
        if la_so:
            ket_qua_cot[ten_cot] = _profile_cot_so(df[ten_cot], n_bins)
        else:
            ket_qua_cot[ten_cot] = _profile_cot_chu(df[ten_cot])

    return {
        "n_rows": int(len(df)),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "columns": ket_qua_cot,
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
"""Smoke test: log mot run va mot model vao MLflow that."""

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
    mlflow.log_param("thu_nghiem", "smoke")
    mlflow.log_metric("rmse", 1.23)
    # MLflow 2.x dung `artifact_path`; tham so `name` chi co tu MLflow 3.
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

Run: `.venv\Scripts\python.exe -c "import shutil; print(f'{shutil.disk_usage(\"C:/\").free/2**30:.1f} GB trong')"`
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
    entrypoint: >
      /bin/bash -c "
      airflow db migrate &&
      airflow users create
        --username ${AIRFLOW_ADMIN_USER}
        --password ${AIRFLOW_ADMIN_PASSWORD}
        --firstname Admin --lastname User
        --role Admin --email admin@example.com
      || true
      "

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
"""DAG smoke test — chung minh Airflow doc duoc thu muc dags/ va chay duoc task.

DAG nay bi xoa o Plan 2 khi ml_pipeline_dag.py ra doi.
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
    def chao():
        print("Airflow doc duoc dags/ va chay duoc task.")
        return "ok"

    @task
    def kiem_tra_bien_moi_truong():
        import os

        for ten in ("MLFLOW_TRACKING_URI", "MINIO_ENDPOINT_INTERNAL", "ML_BUCKET"):
            gia_tri = os.environ.get(ten)
            print(f"{ten} = {gia_tri}")
            assert gia_tri, f"Thieu bien moi truong {ten}"
        return "ok"

    chao() >> kiem_tra_bien_moi_truong()


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

Expected: cả hai task `chao` và `kiem_tra_bien_moi_truong` đều `success`, log in ra ba biến môi trường có giá trị.

Nếu `kiem_tra_bien_moi_truong` thất bại, biến môi trường chưa truyền được vào container — kiểm tra lại khối `&airflow-env` và file `.env`.

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
# Image nen cho moi stage cua pipeline.
#
# Ly do ton tai: neu moi stage tu cai pandas/scikit-learn rieng thi build
# rat lau va version de lech giua cac stage. Version scikit-learn lech giua
# luc train va luc serve la kieu bug kho tim nhat — model unpickle ra sai
# hoac khong unpickle duoc.
#
# Python 3.12 (khong phai 3.13): khop voi image Airflow va voi serving.
FROM python:3.12-slim

WORKDIR /app

# Cai dependency truoc, copy code sau: doi code khong lam mat cache lop nay.
COPY common/pyproject.toml /app/common/pyproject.toml
RUN mkdir -p /app/common/ml_common \
    && touch /app/common/ml_common/__init__.py \
    && pip install --no-cache-dir -e /app/common

# Gio moi copy code that
COPY common/ /app/common/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-c", "import ml_common; print('ml-base san sang, ml_common', ml_common.__version__)"]
```

- [ ] **Step 2: Tạo `scripts/build_base_image.ps1`**

Build phải chạy từ thư mục gốc của repo vì Dockerfile tham chiếu `common/`.

```powershell
# Build image nen. Chay tu thu muc goc cua repo.
docker build -f stages/base/Dockerfile -t ml-base:latest .
```

- [ ] **Step 3: Build image**

Run: `powershell -ExecutionPolicy Bypass -File scripts\build_base_image.ps1`
Expected: build thành công, dòng cuối `naming to docker.io/library/ml-base:latest`

- [ ] **Step 4: Xác nhận `ml_common` import được trong image**

Run: `docker run --rm ml-base:latest`
Expected: `ml-base san sang, ml_common 0.1.0`

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
# Xac nhan toan bo nen tang Plan 1 hoat dong.
$ErrorActionPreference = "Stop"

Write-Host "== 1/5 Test suite local ==" -ForegroundColor Cyan
.venv\Scripts\python.exe -m pytest common/ -q

Write-Host "== 2/5 Lint ==" -ForegroundColor Cyan
.venv\Scripts\python.exe -m ruff check common/

Write-Host "== 3/5 Container dang chay ==" -ForegroundColor Cyan
docker compose ps

Write-Host "== 4/5 Storage noi duoc toi MinIO that ==" -ForegroundColor Cyan
.venv\Scripts\python.exe scripts\smoke_storage.py

Write-Host "== 5/5 Test suite trong image Python 3.12 ==" -ForegroundColor Cyan
docker run --rm ml-base:latest sh -c "pip install --quiet 'pytest>=8.0' 'moto[s3]>=5.0' && python -m pytest /app/common/tests -q"

Write-Host "`nNen tang san sang cho Plan 2." -ForegroundColor Green
```

- [ ] **Step 2: Chạy script xác nhận**

Run: `powershell -ExecutionPolicy Bypass -File scripts\verify_foundation.ps1`
Expected: cả 5 mục đều pass, dòng cuối `Nen tang san sang cho Plan 2.`

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

| Service | URL | Đăng nhập |
| --- | --- | --- |
| Airflow | http://localhost:8080 | admin / admin |
| MLflow | http://localhost:5000 | — |
| MinIO Console | http://localhost:9001 | minioadmin / minioadmin |

## Kiểm tra

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_foundation.ps1
```

## Cấu trúc

| Thư mục | Nội dung |
| --- | --- |
| `common/` | Package `ml_common` — schema, parser, transformer, storage, profiling |
| `dags/` | DAG của Airflow |
| `docker/` | Dockerfile cho hạ tầng |
| `stages/base/` | Image nền cho các stage |
| `scripts/` | Script smoke test và tiện ích |
| `docs/superpowers/` | Spec và implementation plan |

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
- [ ] `docker run --rm ml-base:latest` in ra `ml-base san sang, ml_common 0.1.0`
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

| Plan | Nội dung | Phụ thuộc |
| --- | --- | --- |
| 2 — Batch pipeline | `stages/` extract, validate, preprocess (có cache fingerprint), train, evaluate (2 cổng), register (+ baseline profile); `ml_pipeline` DAG cho regression | Plan 1 |
| 3 — Serving | `services/serving/` với `/predict` `/reload` `/health`, ghi inference log theo batch; task `deploy`; nhánh classification | Plan 2 |
| 4 — Monitoring | `services/agent/` với `drift_scenario`; `/feedback` + ground truth; `stages/monitor/` với Evidently; `monitoring_dag` | Plan 3 |
| 5 — Dashboard | `services/api/` theo contract mục 8.3; nối `dashboard/` bỏ mock JS | Plan 4 |

Mỗi plan được viết sau khi plan trước chạy xong, vì mỗi lần chạy sẽ lộ ra thứ cần điều chỉnh cho plan kế tiếp.
