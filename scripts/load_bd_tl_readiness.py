import pandas as pd
from datetime import datetime, timezone
from db_connection import run_query, get_connection

def try_parse_number(value):
    """Returns a float if value is genuinely numeric, else None."""
    if pd.isna(value):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def load_table(csv_path, table_name, name_column, name_db_column):
    df = pd.read_csv(csv_path)
    now = datetime.now(timezone.utc)

    run_query(f"TRUNCATE TABLE {table_name}")
    print(f"Truncated {table_name}")

    conn = get_connection()
    cursor = conn.cursor()

    insert_sql = f"""
        INSERT INTO {table_name}
        ({name_db_column}, trajectory, yoy_growth_rates, momentum_status, revenue_change_pct,
         lifetime_revenue, lifetime_rank, recent_fy_revenue, recent_fy_rank, recent_fy_status,
         readiness_flag, computed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    rows_inserted = 0
    for _, row in df.iterrows():
        recent_fy_revenue = try_parse_number(row['recent_fy_revenue'])

        raw_rank = row['recent_fy_rank']
        rank_as_number = try_parse_number(raw_rank)

        if rank_as_number is not None:
            recent_fy_rank = int(rank_as_number)
            recent_fy_status = 'Active in Latest Full FY'
        else:
            recent_fy_rank = None
            # If the raw value is a real status string, use it directly;
            # otherwise (blank/NaN) derive from revenue as a fallback
            if pd.notna(raw_rank) and isinstance(raw_rank, str):
                recent_fy_status = raw_rank
            else:
                recent_fy_status = (
                    'Not Active in Latest Full FY' if recent_fy_revenue is None
                    else 'Active in Latest Full FY'
                )

        revenue_change_pct = try_parse_number(row['revenue_change_pct'])
        yoy_growth_rates = None if pd.isna(row['yoy_growth_rates']) else str(row['yoy_growth_rates'])
        momentum_status = None if pd.isna(row['momentum_status']) else row['momentum_status']

        lifetime_revenue = try_parse_number(row['lifetime_revenue'])
        lifetime_rank_num = try_parse_number(row['lifetime_rank'])
        lifetime_rank = int(lifetime_rank_num) if lifetime_rank_num is not None else None

        trajectory = None if pd.isna(row['trajectory']) else row['trajectory']

        cursor.execute(insert_sql, (
            row[name_column],
            trajectory,
            yoy_growth_rates,
            momentum_status,
            revenue_change_pct,
            lifetime_revenue,
            lifetime_rank,
            recent_fy_revenue,
            recent_fy_rank,
            recent_fy_status,
            row['readiness_flag'],
            now
        ))
        rows_inserted += 1

    conn.commit()
    cursor.close()
    conn.close()
    print(f"Inserted {rows_inserted} rows into {table_name}, computed_at = {now}")

load_table(
    csv_path="data/bd_readiness_full.csv",
    table_name="bd_readiness_calculated",
    name_column="nameOfBd",
    name_db_column="bd_name"
)

load_table(
    csv_path="data/tl_readiness_full.csv",
    table_name="tl_readiness_calculated",
    name_column="teamLeader",
    name_db_column="tl_name"
)