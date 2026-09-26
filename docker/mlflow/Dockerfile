FROM python:3.12-slim

# SQLAlchemy 2.1 removed FallbackAsyncAdaptedQueuePool, which mlflow 2.x's
# db utils import at startup; mlflow only declares sqlalchemy<3, so pin it here.
RUN pip install --no-cache-dir \
    "mlflow>=2.14,<3" \
    "sqlalchemy>=2.0,<2.1" \
    "psycopg2-binary>=2.9" \
    "boto3>=1.34"

EXPOSE 5000

ENTRYPOINT ["mlflow", "server"]
