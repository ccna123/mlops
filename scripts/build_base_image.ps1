# Build the base image. Run from the repo root.
#
# The source commit is baked into the image (GIT_COMMIT) so every training run
# can record which code produced it. A tree with uncommitted changes gets a
# "-dirty" suffix: that commit alone would not reproduce the image.
$commit = (git rev-parse --short HEAD).Trim()
if ($LASTEXITCODE -ne 0) { $commit = "unknown" }
elseif (git status --porcelain) { $commit = "$commit-dirty" }

docker build -f stages/base/Dockerfile --build-arg "GIT_COMMIT=$commit" -t ml-base:latest .
# A failing native command does not stop a Windows PowerShell 5.1 script by
# itself; without this check a failed build would look like a successful one.
if ($LASTEXITCODE -ne 0) {
    throw "docker build failed for ml-base:latest (exit code $LASTEXITCODE)"
}
Write-Host "ml-base:latest built from commit $commit"
