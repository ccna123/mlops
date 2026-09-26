# Serving. Build from the repo root:
#   docker build -f services/serving/Dockerfile -t ml-serving:latest .
#
# FROM ml-base is a hard requirement, not convenience: a model pickled by one
# scikit-learn version does not reliably load in another. Sharing the base image
# with the train stage makes the versions match structurally.
FROM ml-base:latest

RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.30" \
    "prometheus-client>=0.20"

COPY services/ /app/services/

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "services.serving.app:app", "--host", "0.0.0.0", "--port", "8000"]
