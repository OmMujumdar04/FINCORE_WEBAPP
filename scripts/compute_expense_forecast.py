import pandas as pd
import numpy as np
from datetime import datetime, timezone
from prophet import Prophet
from db_connection import fetch_dataframe, run_query, get_connection

def compute_expense_forecast():
    print("--- Running Expense Forecast ETL Pipeline (Prophet - Validation Only) ---")
    now_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    # 1. Fetch source data from Aiven
    df = fetch_dataframe("SELECT billDate, amount FROM expenditure WHERE billDate IS NOT NULL AND amount IS NOT NULL")
    df['billDate'] = pd.to_datetime(df['billDate'], errors='coerce')
    df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
    clean_df = df.dropna(subset=['billDate', 'amount'])

    # 2. Restrict to confirmed reliable 24-month window (Apr 2023 – Mar 2025 per Data Rule 9)
    reliable_df = clean_df[(clean_df['billDate'] >= '2023-04-01') & (clean_df['billDate'] <= '2025-03-31')].copy()

    monthly_expense = (
        reliable_df
        .groupby(pd.Grouper(key='billDate', freq='MS'))['amount']
        .sum()
        .reset_index()
    )
    monthly_expense.columns = ['ds', 'y']
    monthly_expense = monthly_expense.sort_values('ds').reset_index(drop=True)

    max_hist_date = monthly_expense['ds'].max()
    print(f"Reliable historical expense records: {len(monthly_expense)} months (from {monthly_expense['ds'].min().strftime('%b %Y')} to {max_hist_date.strftime('%b %Y')})")

    # 3. Fit Prophet model
    expense_model = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
        seasonality_mode='additive',
        interval_width=0.80
    )
    expense_model.fit(monthly_expense)

    # 4. Generate 6-month future prediction (Apr 2025 - Sep 2025 validation window)
    future_exp = expense_model.make_future_dataframe(periods=6, freq='MS')
    forecast_exp = expense_model.predict(future_exp)

    # 5. Build full timeseries for DB & chart rendering
    timeseries_rows = []

    # Historical entries
    for _, row in monthly_expense.iterrows():
        timeseries_rows.append({
            'ds': row['ds'].strftime('%Y-%m-%d'),
            'month_label': row['ds'].strftime('%b-%y'),
            'actual': float(row['y']),
            'forecast': None,
            'lower_bound': None,
            'upper_bound': None,
            'is_forecast': False,
            'validation_flag': 'Reliable Historical Actual'
        })

    # Validation forecast entries
    future_forecast = forecast_exp[forecast_exp['ds'] > max_hist_date].copy().reset_index(drop=True)
    for _, row in future_forecast.iterrows():
        timeseries_rows.append({
            'ds': row['ds'].strftime('%Y-%m-%d'),
            'month_label': row['ds'].strftime('%b-%y'),
            'actual': None,
            'forecast': round(float(row['yhat']), 2),
            'lower_bound': round(float(row['yhat_lower']), 2),
            'upper_bound': round(float(row['yhat_upper']), 2),
            'is_forecast': True,
            'validation_flag': 'Validation Forecast'
        })

    # 6. Compute dynamic KPIs
    next_month = future_forecast.iloc[0]
    next_month_date = next_month['ds']
    next_month_val = round(float(next_month['yhat']), 2)
    next_month_lower = round(float(next_month['yhat_lower']), 2)
    next_month_upper = round(float(next_month['yhat_upper']), 2)
    next_month_label = next_month_date.strftime('%b %Y')

    historical_avg_val = round(float(monthly_expense['y'].mean()), 2)
    validation_total_6m = round(float(future_forecast['yhat'].sum()), 2)
    validation_period_label = f"{future_forecast.iloc[0]['ds'].strftime('%b %Y')} - {future_forecast.iloc[-1]['ds'].strftime('%b %Y')}"

    print(f"Next Validation Month ({next_month_label}): Rs {next_month_val/100000:.2f}L (Range: Rs {next_month_lower/100000:.2f}L - Rs {next_month_upper/100000:.2f}L)")
    print(f"Historical 24-Month Average Spend: Rs {historical_avg_val/100000:.2f}L/month")
    print(f"6-Month Validation Forecast Total ({validation_period_label}): Rs {validation_total_6m/100000:.2f}L")

    # 7. Write to Aiven MySQL (Full Refresh)
    run_query("TRUNCATE TABLE ml_expense_forecast;")
    run_query("TRUNCATE TABLE ml_expense_forecast_kpis;")

    conn = get_connection()
    cursor = conn.cursor()

    insert_ts_sql = """
    INSERT INTO ml_expense_forecast (
        ds, month_label, actual, forecast, lower_bound, upper_bound, is_forecast, validation_flag, computed_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    db_ts_data = [
        (
            r['ds'],
            r['month_label'],
            r['actual'],
            r['forecast'],
            r['lower_bound'],
            r['upper_bound'],
            r['is_forecast'],
            r['validation_flag'],
            now_utc
        )
        for r in timeseries_rows
    ]

    cursor.executemany(insert_ts_sql, db_ts_data)

    insert_kpi_sql = """
    INSERT INTO ml_expense_forecast_kpis (
        kpi_id, next_month_label, next_month_val, next_month_lower, next_month_upper,
        historical_avg_val, validation_total_6m, validation_period_label, computed_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    cursor.execute(insert_kpi_sql, (
        'latest',
        next_month_label,
        next_month_val,
        next_month_lower,
        next_month_upper,
        historical_avg_val,
        validation_total_6m,
        validation_period_label,
        now_utc
    ))

    conn.commit()
    cursor.close()
    conn.close()

    print(f"[SUCCESS] Inserted {len(db_ts_data)} rows into ml_expense_forecast and 1 row into ml_expense_forecast_kpis.")

if __name__ == "__main__":
    compute_expense_forecast()
