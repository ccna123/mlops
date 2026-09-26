# Build every stage image. Run from the repo root.
# ml-base must be current first: build_base_image.ps1 rebuilds it from common/.
$ErrorActionPreference = "Stop"

$stages = @(
    @{ Dir = "extract";                   Tag = "ml-extract:latest" },
    @{ Dir = "validate";                  Tag = "ml-validate:latest" },
    @{ Dir = "prepare_dataset_for_train"; Tag = "ml-prepare-dataset:latest" },
    @{ Dir = "train";                     Tag = "ml-train:latest" },
    @{ Dir = "evaluate";                  Tag = "ml-evaluate:latest" },
    @{ Dir = "register";                  Tag = "ml-register:latest" },
    @{ Dir = "monitor";                   Tag = "ml-monitor:latest" },
    @{ Dir = "build_feedback";            Tag = "ml-build-feedback:latest" }
)

foreach ($stage in $stages) {
    Write-Host "== Building $($stage.Tag) ==" -ForegroundColor Cyan
    docker build -f "stages/$($stage.Dir)/Dockerfile" -t $stage.Tag .
    # $ErrorActionPreference does not stop on a failing native command in
    # Windows PowerShell 5.1, so check the exit code: a stage image left stale
    # after a failed build makes the DAG run old code while the tests are green.
    if ($LASTEXITCODE -ne 0) {
        throw "docker build failed for $($stage.Tag) (exit code $LASTEXITCODE)"
    }
}

Write-Host "`nAll stage images built." -ForegroundColor Green
