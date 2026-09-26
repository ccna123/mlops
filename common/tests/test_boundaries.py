"""The boundaries between components, checked on every change (PCN-09, PCN-13, 02 11.6).

These rules were kept by convention until now; a later change could break one
without anyone noticing. Skipped inside the ml-base image, which holds only
common/.
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    not (ROOT / "services").exists(), reason="the full repository is not present"
)

# Modules that drop or replace rows. None of them may reach a Pipeline or
# serving: a row-dropping step handed one record returns an empty frame and
# serving fails (PCN-09).
ROW_MODULES = {"rowops", "preparation", "feedback"}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def _touches_row_modules(path: Path) -> set[str]:
    found = set()
    for name in _imported_modules(path):
        parts = set(name.replace("ml_common.", "").split("."))
        found |= parts & ROW_MODULES
    return found


@pytest.mark.parametrize(
    "path",
    [
        "common/ml_common/features.py",
        "common/ml_common/cleaning.py",
        "common/ml_common/estimators.py",
        *[str(p.relative_to(ROOT)) for p in (ROOT / "services" / "serving").glob("*.py")],
    ],
)
def test_model_building_and_serving_never_import_row_operations(path):
    assert not _touches_row_modules(ROOT / path), f"{path} imports a row-dropping module"


def test_serving_does_not_clean_records_itself():
    # The model cleans its own input; a second copy of cleaning in serving is
    # exactly the training/serving skew the design exists to prevent (NV-04).
    for path in (ROOT / "services" / "serving").glob("*.py"):
        assert "cleaning" not in {
            part for name in _imported_modules(path) for part in name.split(".")
        }, path


BACKEND_ADDRESSES = re.compile(
    r"localhost:(8080|5000|9000|9001|9090|9091|3000)|airflow-webserver|mlflow:5000|minio:9000"
    r"|/api/v1/dags|/api/2\.0/mlflow"
)


def test_dashboard_talks_only_to_the_backend_layer():
    # Credentials of Airflow, MLflow and MinIO must never reach the browser
    # (PCN-13): every call goes through /api.
    offenders = []
    for path in (ROOT / "dashboard" / "src").rglob("*"):
        if path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if BACKEND_ADDRESSES.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_only_storage_builds_object_storage_keys():
    # 要件定義書 PCN-15: storage.py is the one place that knows paths.
    prefixes = "raw|processed|extracted|inference-log|ground-truth|reports|monitoring-baseline"
    pattern = re.compile(rf"""["']({prefixes})/""")
    offenders = []
    for folder in ("common/ml_common", "services", "stages"):
        for path in (ROOT / folder).rglob("*.py"):
            if "tests" in path.parts or path.name == "storage.py":
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if pattern.search(line) and '"""' not in line and "# ->" not in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: {stripped}")
    assert not offenders, "\n".join(offenders)
