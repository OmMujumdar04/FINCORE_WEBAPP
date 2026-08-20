import pandas as pd
import numpy as np
from datetime import datetime, timezone
from sklearn.ensemble import IsolationForest
from db_connection import fetch_dataframe, run_query, get_connection


def _build_monthly_series(df, date_col, value_col, freq_start=None, freq_end=None):
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    df = df.dropna(subset=[date_col, value_col])

    if freq_start:
        df = df[df[date_col] >= freq_start]
    if freq_end:
        df = df[df[date_col] <= freq_end]

    monthly = (
        df.groupby(pd.Grouper(key=date_col, freq="MS"))[value_col]
        .sum()
        .reset_index()
    )
    monthly.columns = ["ds", "y"]
    monthly = monthly.sort_values("ds").reset_index(drop=True)
    return monthly


def _run_isolation_forest(monthly, contamination):
    X = monthly["y"].values.reshape(-1, 1)
    model = IsolationForest(n_estimators=200, contamination=contamination, random_state=42)
    model.fit(X)
    

    predictions = model.predict(X)  # -1 = anomaly, 1 = normal
    raw_scores = model.decision_function(X)  # higher = more normal, lower = more anomalous

    monthly = monthly.copy()
    monthly["anomaly_flag"] = predictions == -1
    # Flip sign so higher score = more anomalous (matches the human-readable
    # convention used in the original Phase 3 findings, e.g. Mar-25: 0.22)
    monthly["anomaly_score"] = np.round(-raw_scores, 4)

    # Human-readable context (not written to DB, printed for sanity-checking only)
    baseline = monthly["y"].mean()
    monthly["pct_vs_baseline"] = ((monthly["y"] - baseline) / baseline * 100).round(1)

    return monthly


def compute_revenue_anomalies():
    print("--- Running Revenue Anomaly Detection (Isolation Forest) ---")
    df = fetch_dataframe("SELECT billDate, ourShare FROM invoice WHERE billDate IS NOT NULL AND ourShare IS NOT NULL")
    monthly = _build_monthly_series(df, "billDate", "ourShare")
    print(f"  Revenue window: {monthly['ds'].min().strftime('%b %Y')} to {monthly['ds'].max().strftime('%b %Y')} ({len(monthly)} months)")

    result = _run_isolation_forest(monthly, contamination=0.10)
    flagged = result[result["anomaly_flag"]].sort_values("anomaly_score", ascending=False)
    print("  Flagged anomalies:")
    for _, r in flagged.iterrows():
        print(f"    {r['ds'].strftime('%b-%y')}: ₹{r['y']/100000:.1f}L ({r['pct_vs_baseline']:+.0f}% vs baseline), score={r['anomaly_score']}")

    return result


def compute_expense_anomalies():
    print("\n--- Running Expense Anomaly Detection (Isolation Forest, reliable window only) ---")
    df = fetch_dataframe("SELECT billDate, amount FROM expenditure WHERE billDate IS NOT NULL AND amount IS NOT NULL")
    # Restricted to the confirmed reliable window (Data Rule 9) — same restriction
    # as compute_expense_forecast.py. Months outside this range are bulk-entry
    # or gap artifacts, not real spending, and would poison the anomaly baseline.
    monthly = _build_monthly_series(df, "billDate", "amount", freq_start="2023-04-01", freq_end="2025-03-31")
    print(f"  Expense window (reliable only): {monthly['ds'].min().strftime('%b %Y')} to {monthly['ds'].max().strftime('%b %Y')} ({len(monthly)} months)")

    result = _run_isolation_forest(monthly, contamination=0.125)
    flagged = result[result["anomaly_flag"]].sort_values("anomaly_score", ascending=False)
    print("  Flagged anomalies:")
    for _, r in flagged.iterrows():
        print(f"    {r['ds'].strftime('%b-%y')}: ₹{r['y']/100000:.1f}L ({r['pct_vs_baseline']:+.0f}% vs baseline), score={r['anomaly_score']}")

    return result


def write_anomaly_table(df, table_name):
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    run_query(f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            ds DATE NOT NULL,
            y DECIMAL(14,2) NOT NULL,
            anomaly_flag BOOLEAN NOT NULL,
            anomaly_score DECIMAL(10,4) NOT NULL,
            pct_vs_baseline DECIMAL(8,2) NULL,
            computed_at DATETIME NOT NULL,
            PRIMARY KEY (ds)
        );
    """)
    run_query(f"TRUNCATE TABLE {table_name};")

    conn = get_connection()
    cursor = conn.cursor()
    insert_sql = f"""
        INSERT INTO {table_name} (ds, y, anomaly_flag, anomaly_score, pct_vs_baseline, computed_at)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    rows = [
        (
            r["ds"].strftime("%Y-%m-%d"),
            float(r["y"]),
            bool(r["anomaly_flag"]),
            float(r["anomaly_score"]),
            float(r["pct_vs_baseline"]) if pd.notna(r["pct_vs_baseline"]) else None,
            now_utc,
        )
        for _, r in df.iterrows()
    ]
    cursor.executemany(insert_sql, rows)
    conn.commit()
    cursor.close()
    conn.close()

    print(f"  [SUCCESS] Inserted {len(rows)} rows into {table_name}.")


if __name__ == "__main__":
    revenue_anomalies = compute_revenue_anomalies()
    expense_anomalies = compute_expense_anomalies()

    write_anomaly_table(revenue_anomalies, "ml_revenue_anomalies")
    write_anomaly_table(expense_anomalies, "ml_expense_anomalies")

    print("\nDone.")