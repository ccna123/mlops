-- Database `airflow` is already created by the POSTGRES_DB variable.
-- Create a separate database for MLflow: keeping them apart means Airflow's
-- and MLflow's metadata don't affect each other on backup or reset.
CREATE DATABASE mlflow;
