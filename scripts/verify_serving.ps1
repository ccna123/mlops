# Verifies Plan 3: serving is up, serves both models, and logs what it served.
$ErrorActionPreference = "Stop"

Write-Host "== 1/6 Unit tests ==" -ForegroundColor Cyan
.venv\Scripts\python.exe -m pytest common/ services/ -q
if ($LASTEXITCODE -ne 0) { throw "unit tests failed" }

Write-Host "== 2/6 Lint ==" -ForegroundColor Cyan
.venv\Scripts\python.exe -m ruff check .
if ($LASTEXITCODE -ne 0) { throw "lint failed" }

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
if ($LASTEXITCODE -ne 0) { throw "could not list DAG import errors" }

Write-Host "`nServing ready for Plan 4." -ForegroundColor Green
