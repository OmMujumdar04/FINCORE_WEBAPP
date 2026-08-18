import pandas as pd
import numpy as np
from datetime import datetime, timezone
from db_connection import fetch_dataframe, run_query, get_connection


def load_invoice():
    df = fetch_dataframe("SELECT * FROM invoice")
    df['billDate'] = pd.to_datetime(df['billDate'], errors='coerce')
    df['ourShare'] = pd.to_numeric(df['ourShare'], errors='coerce')
    return df


def run_pipeline(invoice_df, name_col):
    df = invoice_df.copy()
    df[name_col] = df[name_col].replace('', pd.NA).fillna('Unattributed')
    df[name_col] = df[name_col].str.strip().str.replace(r'\s+', ' ', regex=True)

    def derive_fy(d):
        if pd.isna(d):
            return None
        return f"{d.year}-{d.year+1}" if d.month >= 4 else f"{d.year-1}-{d.year}"
    df['fy'] = df['billDate'].apply(derive_fy)
    clean = df.dropna(subset=['billDate'])

    by_fy = clean.groupby([name_col, 'fy']).agg(
        revenue=('ourShare', 'sum'), bills=('ourShare', 'count')
    ).reset_index()
    by_fy['low_data_year'] = by_fy['bills'] < 3

    CURRENT_FY = derive_fy(df['billDate'].max())
    full = by_fy[by_fy['fy'] != CURRENT_FY].copy()

    # --- Momentum ---
    latest = df['billDate'].max()
    cur_start = pd.Timestamp(year=latest.year if latest.month >= 4 else latest.year - 1, month=4, day=1)
    prior_start = cur_start - pd.DateOffset(years=1)
    prior_end = latest - pd.DateOffset(years=1)

    cur_win = df[(df['billDate'] >= cur_start) & (df['billDate'] <= latest)]
    prior_win = df[(df['billDate'] >= prior_start) & (df['billDate'] <= prior_end)]

    def summarize(d, label):
        g = d.groupby(name_col).agg(revenue=('ourShare', 'sum'), bills=('ourShare', 'count')).reset_index()
        g.columns = [name_col, f'revenue_{label}', f'bills_{label}']
        return g

    momentum = pd.merge(summarize(prior_win, 'prior'), summarize(cur_win, 'current'), on=name_col, how='outer').fillna(0)
    momentum['revenue_change_pct'] = (
        (momentum['revenue_current'] - momentum['revenue_prior']) / momentum['revenue_prior'].replace(0, pd.NA) * 100
    )
    momentum['low_data_momentum'] = (momentum['bills_current'] < 3) | (momentum['bills_prior'] < 3)
    momentum['is_new_this_year'] = (momentum['bills_prior'] == 0) & (momentum['bills_current'] > 0)

    def classify_momentum(row):
        if row['is_new_this_year']:
            return 'New This Year'
        if pd.isna(row['revenue_change_pct']):
            return 'Dormant — No Recent Activity'
        if row['low_data_momentum']:
            return 'Insufficient Data'
        if row['revenue_change_pct'] > 15:
            return 'Up'
        elif row['revenue_change_pct'] < -15:
            return 'Down'
        return 'Flat'

    momentum['momentum_status'] = momentum.apply(classify_momentum, axis=1)

    # --- Trajectory ---
    non_low = full[~full['low_data_year']]
    MIN_BASE = non_low['revenue'].quantile(0.25)

    def classify_trajectory(name, group):
        if name == 'Unattributed':
            return pd.Series({'trajectory': 'Not Applicable', 'yoy_growth_rates': None})
        g = group[(~group['low_data_year']) & (group['revenue'] >= MIN_BASE)].sort_values('fy')
        if len(g) < 2:
            return pd.Series({'trajectory': 'Insufficient History', 'yoy_growth_rates': None})
        revs = g['revenue'].values
        yoy = [(revs[i] - revs[i-1]) / revs[i-1] * 100 for i in range(1, len(revs))]
        all_pos, all_neg = all(x > 0 for x in yoy), all(x < 0 for x in yoy)
        if all_pos and len(yoy) >= 2:
            label = 'Accelerating' if yoy[-1] > np.mean(yoy[:-1]) else 'Steady Growth'
        elif all_pos:
            label = 'Steady Growth'
        elif all_neg:
            label = 'Declining'
        else:
            label = 'Flat / Inconsistent'
        return pd.Series({'trajectory': label, 'yoy_growth_rates': ', '.join(f'{x:.1f}%' for x in yoy)})

    trajectory = full.groupby(name_col).apply(lambda g: classify_trajectory(g.name, g)).reset_index()

    # --- Scale ---
    lifetime = full.groupby(name_col)['revenue'].sum().reset_index()
    lifetime.columns = [name_col, 'lifetime_revenue']
    lifetime['lifetime_rank'] = lifetime['lifetime_revenue'].rank(ascending=False, method='min').astype(int)

    latest_full_fy = sorted(full['fy'].unique())[-1]
    recent = full[full['fy'] == latest_full_fy][[name_col, 'revenue']].copy()
    recent.columns = [name_col, 'recent_fy_revenue']
    recent['recent_fy_rank'] = recent['recent_fy_revenue'].rank(ascending=False, method='min').astype(int)
    scale = pd.merge(lifetime, recent, on=name_col, how='outer')
    scale['recent_fy_status'] = scale['recent_fy_revenue'].apply(
        lambda x: 'Active in Latest Full FY' if pd.notna(x) else 'Not Active in Latest Full FY'
    )

    # --- Merge + classify ---
    readiness = trajectory.merge(
        momentum[[name_col, 'momentum_status', 'revenue_change_pct']], on=name_col, how='outer'
    ).merge(scale, on=name_col, how='outer')

    readiness['recent_fy_status'] = readiness['recent_fy_status'].fillna('Not Active in Latest Full FY')

    total_ranked = scale['lifetime_rank'].nunique()
    TOP_TIER_CUTOFF = max(1, total_ranked // 2)

    def readiness_flag(row):
        if row[name_col] == 'Unattributed':
            return 'Not Applicable (Unattributed)'
        if row['momentum_status'] == 'New This Year':
            return 'New Hire — No Trajectory Yet'
        traj, mom = row['trajectory'], row['momentum_status']
        is_top = pd.notna(row['lifetime_rank']) and row['lifetime_rank'] <= TOP_TIER_CUTOFF

        if traj in ('Insufficient History', None) and mom in ('Insufficient Data', 'Dormant — No Recent Activity', None):
            return 'Insufficient Data Overall'
        if traj == 'Accelerating':
            return 'High Confidence — Scaled & Accelerating' if is_top else 'Rising — Accelerating but Smaller Scale'
        if traj == 'Steady Growth':
            return 'Stable Core Performer' if is_top else 'Growing — Smaller Scale'
        if traj == 'Flat / Inconsistent' and mom == 'Up' and is_top:
            return 'Established — Currently Strong'
        if mom == 'Up' and traj in ('Insufficient History', 'Flat / Inconsistent'):
            return 'Recent Turnaround Signal (watch)'
        if traj == 'Declining' or mom == 'Down':
            return 'At Risk — Declining'
        return 'Needs Review'

    readiness['readiness_flag'] = readiness.apply(readiness_flag, axis=1)

    return readiness.rename(columns={
        name_col: 'name_col_value',
        'revenue_change_pct': 'revenue_change_pct',
    })[[
        'name_col_value', 'trajectory', 'yoy_growth_rates', 'momentum_status', 'revenue_change_pct',
        'lifetime_revenue', 'lifetime_rank', 'recent_fy_revenue', 'recent_fy_rank',
        'recent_fy_status', 'readiness_flag'
    ]]


def write_to_table(df, table_name, name_db_column):
    now = datetime.now(timezone.utc)
    run_query(f"TRUNCATE TABLE {table_name}")

    conn = get_connection()
    cursor = conn.cursor()
    insert_sql = f"""
        INSERT INTO {table_name}
        ({name_db_column}, trajectory, yoy_growth_rates, momentum_status, revenue_change_pct,
         lifetime_revenue, lifetime_rank, recent_fy_revenue, recent_fy_rank, recent_fy_status,
         readiness_flag, computed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    for _, row in df.iterrows():
        def safe_float(v): return float(v) if pd.notna(v) else None
        def safe_int(v): return int(v) if pd.notna(v) else None

        cursor.execute(insert_sql, (
            row['name_col_value'],
            None if pd.isna(row['trajectory']) else row['trajectory'],
            row['yoy_growth_rates'] if pd.notna(row['yoy_growth_rates']) else None,
            None if pd.isna(row['momentum_status']) else row['momentum_status'],
            safe_float(row['revenue_change_pct']),
            safe_float(row['lifetime_revenue']),
            safe_int(row['lifetime_rank']),
            safe_float(row['recent_fy_revenue']),
            safe_int(row['recent_fy_rank']),
            row['recent_fy_status'],
            row['readiness_flag'],
            now
        ))
    conn.commit()
    cursor.close()
    conn.close()
    print(f"Inserted {len(df)} rows into {table_name}, computed_at = {now}")


if __name__ == "__main__":
    print("Loading invoice from Aiven...")
    invoice_df = load_invoice()

    print("\nRunning BD pipeline...")
    bd_readiness = run_pipeline(invoice_df, 'nameOfBd')
    print(bd_readiness['readiness_flag'].value_counts())
    write_to_table(bd_readiness, 'bd_readiness_calculated', 'bd_name')

    print("\nRunning TL pipeline...")
    tl_readiness = run_pipeline(invoice_df, 'teamLeader')
    print(tl_readiness['readiness_flag'].value_counts())
    write_to_table(tl_readiness, 'tl_readiness_calculated', 'tl_name')