import pandas as pd
import numpy as np
from datetime import datetime, timezone
from prophet import Prophet
from db_connection import fetch_dataframe, run_query, get_connection

def compute_revenue_forecast():
    print("--- Running Revenue Forecast ETL Pipeline (Prophet) ---")
    now_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    # 1. Fetch source data from Aiven
    df = fetch_dataframe("SELECT billDate, ourShare FROM invoice WHERE billDate IS NOT NULL AND ourShare IS NOT NULL")
    df['billDate'] = pd.to_datetime(df['billDate'], errors='coerce')
    df['ourShare'] = pd.to_numeric(df['ourShare'], errors='coerce')
    clean_df = df.dropna(subset=['billDate', 'ourShare'])

    # 2. Monthly aggregation
    monthly_revenue = (
        clean_df
        .groupby(pd.Grouper(key='billDate', freq='MS'))['ourShare']
        .sum()
        .reset_index()
    )
    monthly_revenue.columns = ['ds', 'y']
    monthly_revenue = monthly_revenue.sort_values('ds').reset_index(drop=True)

    max_hist_date = monthly_revenue['ds'].max()
    print(f"Historical monthly revenue records: {len(monthly_revenue)} months (from {monthly_revenue['ds'].min().strftime('%b %Y')} to {max_hist_date.strftime('%b %Y')})")

    # 3. Fit Prophet model
    model = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
        seasonality_mode='additive',
        interval_width=0.80
    )
    model.fit(monthly_revenue)

    # 4. Generate 6-month future prediction
    future = model.make_future_dataframe(periods=6, freq='MS')
    forecast = model.predict(future)

    # 5. Build full timeseries for DB & chart rendering
    timeseries_rows = []

    # Historical entries
    for _, row in monthly_revenue.iterrows():
        timeseries_rows.append({
            'ds': row['ds'].strftime('%Y-%m-%d'),
            'month_label': row['ds'].strftime('%b-%y'),
            'actual': float(row['y']),
            'forecast': None,
            'lower_bound': None,
            'upper_bound': None,
            'is_forecast': False
        })

    # Future forecast entries
    future_forecast = forecast[forecast['ds'] > max_hist_date].copy().reset_index(drop=True)
    for _, row in future_forecast.iterrows():
        timeseries_rows.append({
            'ds': row['ds'].strftime('%Y-%m-%d'),
            'month_label': row['ds'].strftime('%b-%y'),
            'actual': None,
            'forecast': round(float(row['yhat']), 2),
            'lower_bound': round(float(row['yhat_lower']), 2),
            'upper_bound': round(float(row['yhat_upper']), 2),
            'is_forecast': True
        })

    # 6. Compute dynamic KPIs
    next_month = future_forecast.iloc[0]
    next_month_date = next_month['ds']
    next_month_val = round(float(next_month['yhat']), 2)
    next_month_lower = round(float(next_month['yhat_lower']), 2)
    next_month_upper = round(float(next_month['yhat_upper']), 2)
    next_month_label = next_month_date.strftime('%b %Y')

    # YoY comparison with same month last year
    prior_year_date = next_month_date - pd.DateOffset(years=1)
    prior_actual = monthly_revenue[monthly_revenue['ds'] == prior_year_date]
    if not prior_actual.empty and prior_actual.iloc[0]['y'] > 0:
        prior_val = prior_actual.iloc[0]['y']
        next_month_yoy_pct = round(((next_month_val - prior_val) / prior_val) * 100, 2)
    else:
        next_month_yoy_pct = None

    last_actual = monthly_revenue.iloc[-1]
    last_actual_val = round(float(last_actual['y']), 2)
    last_actual_label = last_actual['ds'].strftime('%b %Y')

    forecast_total_6m = round(float(future_forecast['yhat'].sum()), 2)
    forecast_period_label = f"{future_forecast.iloc[0]['ds'].strftime('%b %Y')} - {future_forecast.iloc[-1]['ds'].strftime('%b %Y')}"

    print(f"Next Month Forecast ({next_month_label}): Rs {next_month_val/100000:.2f}L (Range: Rs {next_month_lower/100000:.2f}L - Rs {next_month_upper/100000:.2f}L, YoY: {next_month_yoy_pct}%)")
    print(f"Last Actual Month ({last_actual_label}): Rs {last_actual_val/100000:.2f}L")
    print(f"6-Month Forecast Total ({forecast_period_label}): Rs {forecast_total_6m/10000000:.2f} Cr (Rs {forecast_total_6m/100000:.2f}L)")

    # 7. Write to Aiven MySQL (Full Refresh)
    run_query("TRUNCATE TABLE ml_revenue_forecast;")
    run_query("TRUNCATE TABLE ml_revenue_forecast_kpis;")

    conn = get_connection()
    cursor = conn.cursor()

    insert_ts_sql = """
    INSERT INTO ml_revenue_forecast (
        ds, month_label, actual, forecast, lower_bound, upper_bound, is_forecast, computed_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
            now_utc
        )
        for r in timeseries_rows
    ]

    cursor.executemany(insert_ts_sql, db_ts_data)

    insert_kpi_sql = """
    INSERT INTO ml_revenue_forecast_kpis (
        kpi_id, next_month_label, next_month_val, next_month_lower, next_month_upper,
        next_month_yoy_pct, last_actual_label, last_actual_val, forecast_total_6m,
        forecast_period_label, computed_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    cursor.execute(insert_kpi_sql, (
        'latest',
        next_month_label,
        next_month_val,
        next_month_lower,
        next_month_upper,
        next_month_yoy_pct,
        last_actual_label,
        last_actual_val,
        forecast_total_6m,
        forecast_period_label,
        now_utc
    ))

    conn.commit()
    cursor.close()
    conn.close()

    print(f"[SUCCESS] Inserted {len(db_ts_data)} rows into ml_revenue_forecast and 1 row into ml_revenue_forecast_kpis.")

if __name__ == "__main__":
    compute_revenue_forecast()
