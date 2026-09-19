# Register stage. Build from the repo root:
#   docker build -f stages/register/Dockerfile -t ml-register:latest .
FROM ml-base:latest

COPY stages/register/main.py /app/main.py

ENTRYPOINT ["python", "/app/main.py"]
