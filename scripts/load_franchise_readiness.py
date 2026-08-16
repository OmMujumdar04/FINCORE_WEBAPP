import pandas as pd
from datetime import datetime, timezone
from db_connection import run_query, get_connection

def load_table(csv_path, table_name, name_column, momentum_column, has_recent_fy_status):
    df = pd.read_csv(csv_path)
    now = datetime.now(timezone.utc)

    run_query(f"TRUNCATE TABLE {table_name}")
    print(f"Truncated {table_name}")

    conn = get_connection()
    cursor = conn.cursor()

    insert_sql = f"""
        INSERT INTO {table_name}
        (franchise_name, lifetime_revenue, lifetime_rank, recent_fy_revenue,
         recent_fy_rank, recent_fy_status, trajectory, momentum, readiness_flag, computed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    rows_inserted = 0
    for _, row in df.iterrows():
        recent_fy_revenue = None if pd.isna(row['recent_fy_revenue']) else float(row['recent_fy_revenue'])

        raw_rank = row['recent_fy_rank']
        if pd.isna(raw_rank):
            recent_fy_rank = None
        else:
            # recent_fy_rank may be numeric ('125.0') or, in the net file, sometimes
            # literally the status string itself (e.g. 'Not Active in Latest Full FY')
            try:
                rank_as_float = float(raw_rank)
                recent_fy_rank = None if rank_as_float == -1 else int(rank_as_float)
            except (ValueError, TypeError):
                recent_fy_rank = None

        if has_recent_fy_status:
            recent_fy_status = row['recent_fy_status']
        else:
            # Net file has no dedicated status column — derive it the same way
            # the value would've been implied: no revenue = not active
            recent_fy_status = (
                'Not Active in Latest Full FY' if recent_fy_revenue is None
                else 'Active in Latest Full FY'
            )

        cursor.execute(insert_sql, (
            row[name_column],
            float(row['lifetime_revenue']),
            int(row['lifetime_rank']),
            recent_fy_revenue,
            recent_fy_rank,
            recent_fy_status,
            row['trajectory'],
            row[momentum_column],
            row['readiness_flag'],
            now
        ))
        rows_inserted += 1

    conn.commit()
    cursor.close()
    conn.close()
    print(f"Inserted {rows_inserted} rows into {table_name}, computed_at = {now}")

# Net-basis file — older schema: momentum_flag instead of momentum, no recent_fy_status column
load_table(
    csv_path="data/franchise_readiness_CALCULATED_latest.csv",
    table_name="franchise_readiness_calculated_net",
    name_column="franchiseName_clean",
    momentum_column="momentum_flag",
    has_recent_fy_status=False
)

# Gross-basis file — has both columns natively
load_table(
    csv_path="data/franchise_readiness_CALCULATED_GROSS_latest.csv",
    table_name="franchise_readiness_calculated_gross",
    name_column="franchiseName",
    momentum_column="momentum",
    has_recent_fy_status=True
)