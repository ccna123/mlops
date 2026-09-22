# Verifies Plan 5a (the API layer).
#
# Preconditions: run from the repo root, with the WHOLE stack up (postgres, minio,
# mlflow, airflow, serving and the api service) - steps 3 to 8 call the live
# services. A dependency that is down is a failure here, not a skip.
#
# Step 8 also needs the raw dataset `raw/v1/data.parquet` to be in object storage
# (upload it through POST /api/data/upload or the ingest step of the pipeline). A
# stack without raw v1 FAILS step 8: the preview is 404 there, and this script
# cannot tell "not uploaded yet" from "the route is broken".
#
# Every step must be able to fail: a curl that cannot connect, an empty body or
# a wrong value throws. The only thing that is not a failure is a check that has
# nothing to look at (a model with an empty versions list, an Airflow that has
# no version yet); it is printed as SKIP and counted separately in the
# last lines, never as a pass. A payload that is malformed - a model with no
# `versions` key at all - is a failure, not a skip. Since the log step went
# (2026-09-22), the only skip left is a model with no versions.
#
# Steps 7 and 8 each guard a bug that unit tests with mocks let through and the
# live stack exposed (Task 12): an unknown run answered 500 instead of 404, and
# the preview reported every column as 0% missing. A third such step covered the
# log route, which was removed with the feature on 2026-09-22.
$ErrorActionPreference = "Stop"
$api = "http://localhost:8001/api"
$totalSteps = 8
$stepsPassed = 0
$modelsChecked = 0
$skipped = 0

function Get-HttpCode {
    # Returns the HTTP status of a GET as a string. Throws when curl itself
    # fails (connection refused, timeout), so "000" is never mistaken for an answer.
    param([string]$Url, [string[]]$ExtraArgs = @())
    $code = curl.exe -s -S --max-time 30 -o NUL -w "%{http_code}" @ExtraArgs $Url
    if ($LASTEXITCODE -ne 0) { throw "curl could not reach $Url (exit code $LASTEXITCODE)" }
    return "$code"
}

function Get-Json {
    # Returns the decoded JSON body of a GET. Throws when curl fails, when the
    # status is not 200, or when the body is empty.
    param([string]$Url)
    $code = Get-HttpCode $Url
    if ($code -ne "200") { throw "GET $Url returned HTTP $code" }
    $body = curl.exe -s -S --max-time 30 $Url
    if ($LASTEXITCODE -ne 0) { throw "curl could not reach $Url (exit code $LASTEXITCODE)" }
    if ([string]::IsNullOrWhiteSpace("$body")) { throw "GET $Url returned an empty body" }
    return ($body | ConvertFrom-Json)
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "run this script from the repo root: .venv\Scripts\python.exe not found"
}

Write-Host "== 1/8 Tests on the dev machine ==" -ForegroundColor Cyan
.venv\Scripts\python.exe -m pytest common/ services/ -q
if ($LASTEXITCODE -ne 0) { throw "pytest failed" }
$stepsPassed++

Write-Host "== 2/8 Ruff ==" -ForegroundColor Cyan
.venv\Scripts\python.exe -m ruff check .
if ($LASTEXITCODE -ne 0) { throw "ruff failed" }
$stepsPassed++

Write-Host "== 3/8 Airflow REST accepts basic auth ==" -ForegroundColor Cyan
$code = Get-HttpCode "http://localhost:8080/api/v1/dags" @("-u", "admin:admin")
if ($code -ne "200") {
    throw "Airflow REST returned HTTP $code - check AIRFLOW__API__AUTH_BACKENDS includes basic_auth"
}
Write-Host "   HTTP 200"
$stepsPassed++

Write-Host "== 4/8 /api/health reports exactly the five dependencies ==" -ForegroundColor Cyan
$health = Get-Json "$api/health"
if (-not $health.services) { throw "/api/health has no services object" }
$expected = @("airflow", "minio", "mlflow", "postgres", "serving")
$actual = @($health.services.PSObject.Properties.Name | Sort-Object)
if (($actual -join ",") -ne ($expected -join ",")) {
    throw "/api/health services are [$($actual -join ', ')], expected [$($expected -join ', ')]"
}
foreach ($name in $expected) { Write-Host "   $name = $($health.services.$name)" }
# postgres and serving are printed but not required: postgres is only inferred
# from Airflow, and serving has no model until a champion has been promoted.
foreach ($name in @("airflow", "mlflow", "minio")) {
    if ($health.services.$name -ne "ok") {
        throw "/api/health says $name is '$($health.services.$name)' - the stack must be up"
    }
}
$stepsPassed++

Write-Host "== 5/8 /api/models returns metrics that fit each model's task type ==" -ForegroundColor Cyan
$models = Get-Json "$api/models"
if ($models.PSObject.Properties.Name -notcontains "models") { throw "/api/models has no models list" }
foreach ($m in @($models.models)) {
    # "versions": [] is a model nothing was registered for yet (skip); no
    # `versions` key, or null, is a payload the API should never send (fail).
    if ($m.PSObject.Properties.Name -notcontains "versions" -or $null -eq $m.versions) {
        throw "$($m.name) has no versions list in /api/models - malformed payload"
    }
    if (@($m.versions).Count -eq 0) {
        Write-Host "   SKIP: $($m.name) has no versions" -ForegroundColor Yellow
        $skipped++
        continue
    }
    $keys = @($m.versions[0].metrics.PSObject.Properties.Name)
    Write-Host "   $($m.name) [$($m.task_type)] version $($m.versions[0].version): $($keys -join ',')"
    if ($m.task_type -eq "regression") {
        if ($keys -notcontains "rmse") { throw "$($m.name) is a regressor but has no rmse" }
        if ($keys -contains "accuracy") { throw "$($m.name) is a regressor but reports accuracy" }
    } elseif ($m.task_type -eq "classification") {
        if ($keys -notcontains "accuracy") { throw "$($m.name) is a classifier but has no accuracy" }
        if ($keys -contains "rmse") { throw "$($m.name) is a classifier but reports rmse" }
    } else {
        throw "$($m.name) has task_type '$($m.task_type)', expected regression or classification"
    }
    $modelsChecked++
}
if ($modelsChecked -eq 0) {
    # Nothing was actually looked at, so this step is not counted as passed.
    Write-Host "   SKIP: no model versions" -ForegroundColor Yellow
} else {
    $stepsPassed++
}

Write-Host "== 6/8 /api/drift/latest ==" -ForegroundColor Cyan
$code = Get-HttpCode "$api/drift/latest?model_name=house_price_regressor"
if ($code -ne "200" -and $code -ne "404") { throw "/api/drift/latest returned HTTP $code, expected 200 or 404" }
Write-Host "   HTTP $code (404 is valid before monitoring has ever run)"
$stepsPassed++

Write-Host "== 7/8 an unknown run is a 404, not a 500 ==" -ForegroundColor Cyan
$unknownRunId = "does-not-exist-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
# Any 404 is not enough: FastAPI also answers {"detail":"Not Found"} for a path
# that no route matches. The run route's own 404 names the id it looked for
# ({"detail":"no run '<id>' in DAG 'ml_pipeline'"}), so require that.
$unknownRunUrl = "$api/pipeline/runs/$unknownRunId"
$unknownRunBodyFile = [System.IO.Path]::GetTempFileName()
try {
    $code = curl.exe -s -S --max-time 30 -o $unknownRunBodyFile -w "%{http_code}" $unknownRunUrl
    if ($LASTEXITCODE -ne 0) { throw "curl could not reach $unknownRunUrl (exit code $LASTEXITCODE)" }
    $unknownRunBody = Get-Content -Raw -Encoding UTF8 -LiteralPath $unknownRunBodyFile
} finally {
    Remove-Item -LiteralPath $unknownRunBodyFile -Force
}
if ("$code" -ne "404") {
    throw "GET $unknownRunUrl returned HTTP $code, expected exactly 404"
}
try {
    $unknownRunError = $unknownRunBody | ConvertFrom-Json
} catch {
    throw "the 404 for $unknownRunId has no JSON body: $unknownRunBody"
}
$unknownRunDetail = "$($unknownRunError.detail)"
if (-not $unknownRunDetail.Contains($unknownRunId)) {
    throw "the 404 for $unknownRunId does not name that run (detail: '$unknownRunDetail') - this looks like an unrouted path, not the run route reporting an unknown run"
}
Write-Host "   HTTP 404 for $($unknownRunId): $unknownRunDetail"
$stepsPassed++

Write-Host "== 8/8 the data preview counts blank cells as missing ==" -ForegroundColor Cyan
# The raw copy stores a missing cell as an empty string. When the preview counted
# only nulls, every column of the real dataset read 0% missing. One request only:
# the preview downloads the whole raw object from MinIO every time.
$previewUrl = "$api/data/v1/preview?rows=1"
$previewFile = [System.IO.Path]::GetTempFileName()
try {
    $code = curl.exe -s -S --max-time 120 -o $previewFile -w "%{http_code}" $previewUrl
    if ($LASTEXITCODE -ne 0) { throw "curl could not reach $previewUrl (exit code $LASTEXITCODE)" }
    if ("$code" -ne "200") {
        throw "GET $previewUrl returned HTTP $code - raw dataset v1 must be in object storage (see the preconditions at the top of this script)"
    }
    $preview = Get-Content -Raw -Encoding UTF8 -LiteralPath $previewFile | ConvertFrom-Json
} finally {
    Remove-Item -LiteralPath $previewFile -Force
}
if ($preview.PSObject.Properties.Name -notcontains "columns" -or @($preview.columns).Count -eq 0) {
    throw "the preview of v1 has no columns"
}
$withMissing = @($preview.columns | Where-Object { $_.missing_rate -gt 0 })
if ($withMissing.Count -eq 0) {
    throw "the preview of v1 reports missing_rate 0 for all $(@($preview.columns).Count) columns - blank cells are not being counted as missing"
}
$worst = $withMissing | Sort-Object -Property missing_rate -Descending | Select-Object -First 3
foreach ($column in $worst) { Write-Host "   $($column.name) missing_rate = $($column.missing_rate)" }
Write-Host "   $($withMissing.Count) of $(@($preview.columns).Count) columns have missing_rate > 0 (stats_rows = $($preview.stats_rows))"
$stepsPassed++

Write-Host ""
Write-Host "steps passed:   $stepsPassed/$totalSteps"
Write-Host "models checked: $modelsChecked"
Write-Host "skipped:        $skipped"
if ($stepsPassed -eq $totalSteps -and $skipped -eq 0) {
    Write-Host "`nPlan 5a green." -ForegroundColor Green
} else {
    Write-Host "`nPlan 5a: no check failed, but it is NOT fully verified - see SKIP above." -ForegroundColor Yellow
}
