# Base image for every stage of the pipeline.
#
# Why this exists: if each stage installed its own pandas/scikit-learn, the
# build would be slow and versions would drift between stages. A
# scikit-learn version mismatch between train time and serve time is the
# hardest kind of bug to find — the model unpickles wrong or not at all.
#
# Python 3.12 (not 3.13): matches the Airflow image and serving.
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first, copy code after: code changes don't bust this layer's cache.
COPY common/pyproject.toml /app/common/pyproject.toml
RUN mkdir -p /app/common/ml_common \
    && touch /app/common/ml_common/__init__.py \
    && pip install --no-cache-dir -e /app/common

# Now copy the actual code
COPY common/ /app/common/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-c", "import ml_common; print('ml-base ready, ml_common', ml_common.__version__)"]
