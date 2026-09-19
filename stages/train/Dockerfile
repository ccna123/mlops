# Train stage. Build from the repo root:
#   docker build -f stages/train/Dockerfile -t ml-train:latest .
FROM ml-base:latest

COPY stages/train/main.py /app/main.py

ENTRYPOINT ["python", "/app/main.py"]
