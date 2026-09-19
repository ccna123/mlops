# Extract stage. Build from the repo root:
#   docker build -f stages/extract/Dockerfile -t ml-extract:latest .
FROM ml-base:latest

COPY stages/extract/main.py /app/main.py

ENTRYPOINT ["python", "/app/main.py"]
