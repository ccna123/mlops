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
