from db_connection import run_query
run_query("ALTER TABLE ml_revenue_anomalies ADD COLUMN pct_vs_baseline DECIMAL(8,2) NULL")
run_query("ALTER TABLE ml_expense_anomalies ADD COLUMN pct_vs_baseline DECIMAL(8,2) NULL")