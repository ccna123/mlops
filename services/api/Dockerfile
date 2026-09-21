# API layer. Build from the repo root:
#   docker build -f services/api/Dockerfile -t ml-api:latest .
#
# FROM ml-base because this service reads what the pipeline wrote, using the
# same ml_common.storage key functions. Rebuilding those paths here would be
# a second copy of the one thing only storage.py is allowed to know.
FROM ml-base:latest

RUN pip install --no-cache-dir \
    "fastapi>=0.115" "uvicorn[standard]>=0.30" \
    "httpx>=0.27" "python-multipart>=0.0.9"

COPY services/ /app/services/

ENV PYTHONPATH=/app
EXPOSE 8001

CMD ["uvicorn", "services.api.app:app", "--host", "0.0.0.0", "--port", "8001"]
