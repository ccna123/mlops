FROM python:3.12-slim

RUN pip install --no-cache-dir \
    "mlflow>=2.14,<3" \
    "psycopg2-binary>=2.9" \
    "boto3>=1.34"

EXPOSE 5000

ENTRYPOINT ["mlflow", "server"]
