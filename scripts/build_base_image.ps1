# Build the base image. Run from the repo root.
docker build -f stages/base/Dockerfile -t ml-base:latest .
# A failing native command does not stop a Windows PowerShell 5.1 script by
# itself; without this check a failed build would look like a successful one.
if ($LASTEXITCODE -ne 0) {
    throw "docker build failed for ml-base:latest (exit code $LASTEXITCODE)"
}
