# Prepare-dataset stage. Build from the repo root:
#   docker build -f stages/prepare_dataset_for_train/Dockerfile -t ml-prepare-dataset:latest .
FROM ml-base:latest

COPY stages/prepare_dataset_for_train/main.py /app/main.py

ENTRYPOINT ["python", "/app/main.py"]
