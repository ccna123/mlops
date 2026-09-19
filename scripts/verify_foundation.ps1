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
