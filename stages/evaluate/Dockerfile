# Evaluate stage. Build from the repo root:
#   docker build -f stages/evaluate/Dockerfile -t ml-evaluate:latest .
FROM ml-base:latest

COPY stages/evaluate/main.py /app/main.py

ENTRYPOINT ["python", "/app/main.py"]
