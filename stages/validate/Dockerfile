# Validate stage. Build from the repo root:
#   docker build -f stages/validate/Dockerfile -t ml-validate:latest .
FROM ml-base:latest

COPY stages/validate/main.py /app/main.py

ENTRYPOINT ["python", "/app/main.py"]
