import os
import pandas as pd
from scripts.db_connection import run_query


def setup_anomaly_tables():
    create_rev_anom_sql = """
    CREATE TABLE IF NOT EXISTS ml_revenue_anomalies (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        ds DATE NOT NULL,
        y DOUBLE NOT NULL,
        anomaly_flag INT NOT NULL,
        anomaly_score DOUBLE NOT NULL,
        computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    create_exp_anom_sql = """
    CREATE TABLE IF NOT EXISTS ml_expense_anomalies (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        ds DATE NOT NULL,
        y DOUBLE NOT NULL,
        anomaly_flag INT NOT NULL,
        anomaly_score DOUBLE NOT NULL,
        computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    run_query(create_rev_anom_sql)
    run_query(create_exp_anom_sql)
    print("Anomaly tables ensured.")

if __name__ == "__main__":
    setup_anomaly_tables()
