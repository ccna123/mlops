# Feedback data stage. Build from the repo root:
#   docker build -f stages/build_feedback/Dockerfile -t ml-build-feedback:latest .
FROM ml-base:latest

COPY stages/build_feedback/main.py /app/main.py

ENTRYPOINT ["python", "/app/main.py"]
