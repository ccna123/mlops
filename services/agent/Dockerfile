# Traffic agent. Build from the repo root:
#   docker build -f services/agent/Dockerfile -t ml-agent:latest .
#
# FROM ml-base because the agent derives the true label with
# ml_common.targets.derive_target - the same function the prepare stage uses.
# Reimplementing "poor or fair means needs renovation" here would be a second
# copy of a rule that must not drift.
FROM ml-base:latest

RUN pip install --no-cache-dir "httpx>=0.27"

COPY services/__init__.py /app/services/__init__.py
COPY services/agent/ /app/services/agent/

WORKDIR /app
ENV PYTHONPATH=/app
CMD ["python", "-m", "services.agent", "--help"]
