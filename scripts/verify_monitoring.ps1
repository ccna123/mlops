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
# agent bi profiles loai khoi `docker compose ps`/`config --services` thuong -
# tren Compose v5.3.1 service co profile bi loai hoan toan khoi output khong-
# profile. Phai bat profile len moi thay no, nguoc lai se luon thay "khong co"
# ke ca khi ai do lo xoa dong `profiles: ["agent"]` trong docker-compose.yml.
$withProfile = docker compose --profile agent config --services
if ($withProfile -notcontains "agent") { throw "service agent bi mat khoi docker-compose.yml" }

Write-Host "== 5/5 Image ml-monitor ton tai ==" -ForegroundColor Cyan
docker image inspect ml-monitor:latest | Out-Null
if ($LASTEXITCODE -ne 0) { throw "chua build ml-monitor" }

Write-Host "`nPlan 4 xanh." -ForegroundColor Green
Write-Host "Bang kich ban phai kiem bang tay - xem Task 11 cua plan." -ForegroundColor Yellow
