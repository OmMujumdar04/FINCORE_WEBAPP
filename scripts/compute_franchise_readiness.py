import pandas as pd
from datetime import datetime, timezone
from db_connection import fetch_dataframe, run_query, get_connection


# ============================================================
# SHARED: load + clean invoice once, used by both pipelines
# ============================================================

def load_invoice():
    df = fetch_dataframe("SELECT * FROM invoice")
    df['billDate'] = pd.to_datetime(df['billDate'], errors='coerce')

    # MySQL DECIMAL columns come back as Python Decimal, which breaks pandas'
    # numeric operations (quantile, etc.) when mixed with floats — cast explicitly
    for col in ['ourShare', 'serviceCharges']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


# ============================================================
# NET PIPELINE (ourShare) — mirrors franchise_performance_workforce.ipynb
# ============================================================

def run_net_pipeline(invoice_df):
    df = invoice_df.copy()
    df['franchiseName'] = df['franchiseName'].replace('', pd.NA)
    df['franchiseName_clean'] = df['franchiseName'].fillna('Unattributed').str.strip()

    def derive_fy(date):
        if pd.isna(date):
            return None
        return f"{date.year}-{date.year+1}" if date.month >= 4 else f"{date.year-1}-{date.year}"

    df['financial_year'] = df['billDate'].apply(derive_fy)
    fy_df = df.dropna(subset=['financial_year']).copy()

    by_fy = (
        fy_df.groupby(['franchiseName_clean', 'financial_year'])
        .agg(revenue=('ourShare', 'sum'), bills=('ourShare', 'count'))
        .reset_index()
    )
    by_fy['low_data_year'] = by_fy['bills'] < 3

    max_date = df['billDate'].max()
    CURRENT_FY = derive_fy(max_date)

    full_years = by_fy[by_fy['financial_year'] != CURRENT_FY].copy()

    # --- Momentum ---
    if max_date.month >= 4:
        window_start_this = pd.Timestamp(year=max_date.year, month=4, day=1)
    else:
        window_start_this = pd.Timestamp(year=max_date.year - 1, month=4, day=1)
    window_end_this = max_date
    window_start_last = window_start_this - pd.DateOffset(years=1)
    window_end_last = window_end_this - pd.DateOffset(years=1)

    cur_mask = (df['billDate'] >= window_start_this) & (df['billDate'] <= window_end_this)
    prior_mask = (df['billDate'] >= window_start_last) & (df['billDate'] <= window_end_last)

    cur_agg = df[cur_mask].groupby('franchiseName_clean').agg(
        current_revenue=('ourShare', 'sum'), current_bills=('ourShare', 'count')
    ).reset_index()
    prior_agg = df[prior_mask].groupby('franchiseName_clean').agg(
        prior_revenue=('ourShare', 'sum'), prior_bills=('ourShare', 'count')
    ).reset_index()

    momentum = pd.merge(cur_agg, prior_agg, on='franchiseName_clean', how='outer').fillna(0)

    def classify_momentum(row):
        cur_b, prior_b = row['current_bills'], row['prior_bills']
        cur_r, prior_r = row['current_revenue'], row['prior_revenue']
        if cur_b == 0 and prior_b == 0:
            return 'Dormant — No Recent Activity'
        if prior_b == 0 and cur_b > 0:
            return 'New This Year'
        if cur_b == 0 and prior_b > 0:
            return 'Dormant — No Recent Activity'
        if cur_b < 3 or prior_b < 3:
            return 'Insufficient Data'
        pct = (cur_r - prior_r) / prior_r if prior_r != 0 else float('inf')
        if pct > 0.15:
            return 'Up'
        elif pct < -0.15:
            return 'Down'
        return 'Flat'

    momentum['momentum_flag'] = momentum.apply(classify_momentum, axis=1)

    # --- Trajectory ---
    usable_years = full_years[~full_years['low_data_year']].copy()
    revenue_floor = usable_years['revenue'].quantile(0.25)
    usable_years['above_floor'] = usable_years['revenue'] >= revenue_floor
    trajectory_input = usable_years[usable_years['above_floor']].copy()

    def classify_trajectory(group):
        group = group.sort_values('financial_year')
        revenues = group['revenue'].tolist()
        if len(revenues) < 2:
            return pd.Series({'trajectory': 'Insufficient History'})
        yoy = [(revenues[i] - revenues[i-1]) / revenues[i-1] for i in range(1, len(revenues)) if revenues[i-1] != 0]
        if not yoy:
            return pd.Series({'trajectory': 'Insufficient History'})
        if all(r > 0 for r in yoy):
            if len(yoy) >= 2 and yoy[-1] > sum(yoy[:-1]) / len(yoy[:-1]):
                return pd.Series({'trajectory': 'Accelerating'})
            return pd.Series({'trajectory': 'Steady Growth'})
        elif all(r < 0 for r in yoy):
            return pd.Series({'trajectory': 'Declining'})
        return pd.Series({'trajectory': 'Flat / Inconsistent'})

    trajectory = trajectory_input.groupby('franchiseName_clean').apply(classify_trajectory).reset_index()

    all_franchises = full_years['franchiseName_clean'].unique()
    trajectory = trajectory.set_index('franchiseName_clean').reindex(all_franchises).reset_index()
    trajectory.rename(columns={'index': 'franchiseName_clean'}, inplace=True)
    trajectory['trajectory'] = trajectory['trajectory'].fillna('Insufficient History')

    # --- Scale ---
    lifetime = by_fy.groupby('franchiseName_clean')['revenue'].sum().reset_index()
    lifetime.columns = ['franchiseName_clean', 'lifetime_revenue']
    lifetime['lifetime_rank'] = lifetime['lifetime_revenue'].rank(ascending=False, method='min').astype(int)

    most_recent_full_fy = sorted(full_years['financial_year'].unique())[-1]
    recent_fy = full_years[full_years['financial_year'] == most_recent_full_fy][
        ['franchiseName_clean', 'revenue']
    ].rename(columns={'revenue': 'recent_fy_revenue'})
    recent_fy['recent_fy_rank'] = recent_fy['recent_fy_revenue'].rank(ascending=False, method='min').astype(int)

    scale = lifetime.merge(recent_fy, on='franchiseName_clean', how='left')
    scale['recent_fy_status'] = scale['recent_fy_revenue'].apply(
        lambda x: 'Active in Latest Full FY' if pd.notna(x) else 'Not Active in Latest Full FY'
    )

    # --- Merge + classify ---
    all_names = scale['franchiseName_clean'].unique()
    trajectory = trajectory.set_index('franchiseName_clean').reindex(all_names).reset_index()
    trajectory.rename(columns={'index': 'franchiseName_clean'}, inplace=True)
    trajectory['trajectory'] = trajectory['trajectory'].fillna('Insufficient History')

    readiness = scale.merge(trajectory, on='franchiseName_clean', how='left')
    readiness = readiness.merge(momentum[['franchiseName_clean', 'momentum_flag']], on='franchiseName_clean', how='left')
    readiness['momentum_flag'] = readiness['momentum_flag'].fillna('Insufficient Data')

    TOTAL = len(readiness)
    TOP_TIER_CUTOFF = max(1, TOTAL // 2)

    def classify_readiness(row):
        name = row['franchiseName_clean']
        traj, mom = row['trajectory'], row['momentum_flag']
        is_top = row['lifetime_rank'] <= TOP_TIER_CUTOFF

        if name == 'Unattributed':
            return 'Not Applicable (Unattributed)'
        if traj == 'Insufficient History' and mom == 'New This Year':
            return 'New Hire — No Trajectory Yet'
        if traj == 'Insufficient History' and mom in ('Insufficient Data', 'Dormant — No Recent Activity'):
            return 'Insufficient Data Overall'
        if traj == 'Flat / Inconsistent' and mom == 'Up' and is_top:
            return 'Established — Currently Strong'
        if traj == 'Flat / Inconsistent' and mom == 'Up':
            return 'Recent Turnaround Signal (watch)'
        if traj == 'Flat / Inconsistent' and mom == 'Down':
            return 'At Risk — Declining'
        if traj == 'Declining':
            return 'At Risk — Declining'
        if traj == 'Accelerating':
            return 'High Confidence — Scaled & Accelerating' if is_top else 'Rising — Accelerating but Smaller Scale'
        if traj == 'Steady Growth':
            return 'Stable Core Performer' if is_top else 'Growing — Smaller Scale'
        if traj == 'Insufficient History':
            return 'Insufficient Data Overall'
        if traj == 'Flat / Inconsistent':
            return 'Mixed Signal — No Clear Read'
        return 'Needs Review'

    readiness['readiness_flag'] = readiness.apply(classify_readiness, axis=1)

    readiness = readiness.rename(columns={
        'franchiseName_clean': 'franchise_name',
        'momentum_flag': 'momentum',
    })
    return readiness[[
        'franchise_name', 'lifetime_revenue', 'lifetime_rank', 'recent_fy_revenue',
        'recent_fy_rank', 'recent_fy_status', 'trajectory', 'momentum', 'readiness_flag'
    ]]


# ============================================================
# GROSS PIPELINE (serviceCharges) — mirrors franchise_performance_workforce_gross.ipynb
# ============================================================

def run_gross_pipeline(invoice_df):
    df = invoice_df.copy()
    df['franchiseName'] = df['franchiseName'].replace('', pd.NA).fillna('Unattributed')
    df['franchiseName'] = df['franchiseName'].str.strip().str.replace(r'\s+', ' ', regex=True)
    df = df.dropna(subset=['serviceCharges'])

    def derive_fy(d):
        return f"{d.year}-{d.year+1}" if d.month >= 4 else f"{d.year-1}-{d.year}"
    df['financial_year'] = df['billDate'].apply(derive_fy)

    fy_table = (
        df.groupby(['franchiseName', 'financial_year'])
        .agg(revenue=('serviceCharges', 'sum'), bills=('serviceCharges', 'count'))
        .reset_index()
    )
    fy_table['low_data_year'] = fy_table['bills'] < 3

    undated_rows = fy_table[fy_table['financial_year'] == 'nan-nan'].copy()
    fy_dated = fy_table[fy_table['financial_year'] != 'nan-nan'].copy()
    fy_dated['fy_start_year'] = fy_dated['financial_year'].str.split('-').str[0].astype(int)
    CURRENT_FY_START = fy_dated['fy_start_year'].max()
    CURRENT_FY = fy_dated.loc[fy_dated['fy_start_year'] == CURRENT_FY_START, 'financial_year'].iloc[0]

    full_year_rows = fy_dated[fy_dated['financial_year'] != CURRENT_FY].copy()
    current_partial_rows = fy_dated[fy_dated['financial_year'] == CURRENT_FY].copy()

    # --- Momentum ---
    df2 = df.dropna(subset=['billDate']).copy()
    max_date = df2['billDate'].max()
    cur_fy_start_year = max_date.year if max_date.month >= 4 else max_date.year - 1
    window_start_this = pd.Timestamp(year=cur_fy_start_year, month=4, day=1)
    window_end_this = max_date
    window_start_last = window_start_this - pd.DateOffset(years=1)
    window_end_last = window_end_this - pd.DateOffset(years=1)

    def window_revenue(d, start, end):
        mask = (d['billDate'] >= start) & (d['billDate'] <= end)
        return d[mask].groupby('franchiseName').agg(revenue=('serviceCharges', 'sum'), bills=('serviceCharges', 'count'))

    this_year = window_revenue(df2, window_start_this, window_end_this)
    last_year = window_revenue(df2, window_start_last, window_end_last)
    momentum = this_year.join(last_year, how='outer', lsuffix='_this', rsuffix='_last').fillna(0)

    def classify_momentum(row):
        if row['bills_this'] == 0 and row['bills_last'] == 0:
            return 'Insufficient Data'
        if row['bills_this'] == 0 and row['bills_last'] > 0:
            return 'Dormant — No Recent Activity'
        if row['bills_this'] > 0 and row['bills_last'] == 0:
            return 'New This Year'
        if row['bills_this'] < 3 or row['bills_last'] < 3:
            return 'Insufficient Data'
        pct = (row['revenue_this'] - row['revenue_last']) / row['revenue_last'] if row['revenue_last'] > 0 else 0
        if pct > 0.15:
            return 'Up'
        elif pct < -0.15:
            return 'Down'
        return 'Flat'

    momentum['momentum'] = momentum.apply(classify_momentum, axis=1)
    momentum = momentum.reset_index()

    # --- Trajectory ---
    non_low = full_year_rows[~full_year_rows['low_data_year']]
    REVENUE_FLOOR = non_low['revenue'].quantile(0.25)
    full_year_rows['usable_year'] = (~full_year_rows['low_data_year']) & (full_year_rows['revenue'] >= REVENUE_FLOOR)
    usable = full_year_rows[full_year_rows['usable_year']].copy()
    usable['fy_start_year'] = usable['financial_year'].str.split('-').str[0].astype(int)
    usable = usable.sort_values(['franchiseName', 'fy_start_year'])

    def classify_trajectory(group):
        revenues = group['revenue'].tolist()
        if len(revenues) < 2:
            return 'Insufficient History'
        steps = [(revenues[i] - revenues[i-1]) / revenues[i-1] if revenues[i-1] > 0 else 0 for i in range(1, len(revenues))]
        if all(s > 0 for s in steps):
            if len(steps) >= 2 and steps[-1] > sum(steps[:-1]) / len(steps[:-1]):
                return 'Accelerating'
            return 'Steady Growth'
        elif all(s < 0 for s in steps):
            return 'Declining'
        return 'Flat / Inconsistent'

    trajectory = usable.groupby('franchiseName').apply(classify_trajectory).reset_index()
    trajectory.columns = ['franchiseName', 'trajectory']

    all_franchises = full_year_rows['franchiseName'].unique()
    missing = set(all_franchises) - set(trajectory['franchiseName'])
    missing_df = pd.DataFrame({'franchiseName': list(missing), 'trajectory': 'Insufficient History'})
    trajectory = pd.concat([trajectory, missing_df], ignore_index=True)

    # --- Scale ---
    all_revenue = pd.concat([full_year_rows, current_partial_rows, undated_rows], ignore_index=True)
    lifetime = all_revenue.groupby('franchiseName')['revenue'].sum().reset_index()
    lifetime.columns = ['franchiseName', 'lifetime_revenue']
    lifetime['lifetime_rank'] = lifetime['lifetime_revenue'].rank(ascending=False, method='min')

    most_recent_full_fy = full_year_rows['financial_year'].str.split('-').str[0].astype(int).max()
    most_recent_full_fy_label = full_year_rows.loc[
        full_year_rows['financial_year'].str.split('-').str[0].astype(int) == most_recent_full_fy, 'financial_year'
    ].iloc[0]
    recent_fy = full_year_rows[full_year_rows['financial_year'] == most_recent_full_fy_label][
        ['franchiseName', 'revenue']
    ].copy()
    recent_fy.columns = ['franchiseName', 'recent_fy_revenue']
    recent_fy['recent_fy_rank'] = recent_fy['recent_fy_revenue'].rank(ascending=False, method='min')

    scale = lifetime.merge(recent_fy, on='franchiseName', how='left')
    scale['recent_fy_status'] = scale['recent_fy_revenue'].apply(
        lambda x: 'Active in Latest Full FY' if pd.notna(x) else 'Not Active in Latest Full FY'
    )

    # --- Merge + classify ---
    readiness = scale.merge(trajectory, on='franchiseName', how='left')
    readiness = readiness.merge(momentum[['franchiseName', 'momentum']], on='franchiseName', how='left')
    readiness['trajectory'] = readiness['trajectory'].fillna('Insufficient History')
    readiness['momentum'] = readiness['momentum'].fillna('Insufficient Data')

    TOTAL = len(readiness)
    TOP_TIER_CUTOFF = max(1, TOTAL // 2)

    def classify_readiness(row):
        traj, mom = row['trajectory'], row['momentum']
        is_top = row['lifetime_rank'] <= TOP_TIER_CUTOFF
        if traj == 'Insufficient History':
            if mom == 'New This Year':
                return 'New Hire — No Trajectory Yet'
            elif mom in ('Insufficient Data', 'Dormant — No Recent Activity'):
                return 'Insufficient Data Overall'
            elif mom == 'Up' and is_top:
                return 'Established — Currently Strong'
            elif mom == 'Up':
                return 'Rising — Accelerating but Smaller Scale'
            elif mom == 'Down':
                return 'At Risk — Declining'
            return 'Insufficient Data Overall'
        if traj == 'Accelerating':
            return 'High Confidence — Scaled & Accelerating' if is_top else 'Rising — Accelerating but Smaller Scale'
        if traj == 'Steady Growth':
            return 'Stable Core Performer' if is_top else 'Growing — Smaller Scale'
        if traj == 'Declining':
            return 'At Risk — Declining'
        if traj == 'Flat / Inconsistent':
            if mom == 'Down':
                return 'At Risk — Declining'
            elif mom == 'Up' and is_top:
                return 'Established — Currently Strong'
            elif mom == 'Up':
                return 'Recent Turnaround Signal (watch)'
            return 'Mixed Signal — No Clear Read'
        return 'Needs Review'

    readiness['readiness_flag'] = readiness.apply(classify_readiness, axis=1)
    readiness['lifetime_rank'] = readiness['lifetime_rank'].astype(int)
    readiness['recent_fy_rank'] = readiness['recent_fy_rank'].apply(lambda x: int(x) if pd.notna(x) else None)

    return readiness[[
        'franchiseName', 'lifetime_revenue', 'lifetime_rank', 'recent_fy_revenue',
        'recent_fy_rank', 'recent_fy_status', 'trajectory', 'momentum', 'readiness_flag'
    ]].rename(columns={'franchiseName': 'franchise_name'})


# ============================================================
# WRITE TO AIVEN
# ============================================================

def write_to_table(readiness_df, table_name):
    now = datetime.now(timezone.utc)
    run_query(f"TRUNCATE TABLE {table_name}")

    conn = get_connection()
    cursor = conn.cursor()
    insert_sql = f"""
        INSERT INTO {table_name}
        (franchise_name, lifetime_revenue, lifetime_rank, recent_fy_revenue,
         recent_fy_rank, recent_fy_status, trajectory, momentum, readiness_flag, computed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    for _, row in readiness_df.iterrows():
        recent_fy_rank = row['recent_fy_rank']
        recent_fy_rank = int(recent_fy_rank) if pd.notna(recent_fy_rank) else None
        recent_fy_revenue = row['recent_fy_revenue']
        recent_fy_revenue = float(recent_fy_revenue) if pd.notna(recent_fy_revenue) else None

        cursor.execute(insert_sql, (
            row['franchise_name'], float(row['lifetime_revenue']), int(row['lifetime_rank']),
            recent_fy_revenue, recent_fy_rank, row['recent_fy_status'],
            row['trajectory'], row['momentum'], row['readiness_flag'], now
        ))
    conn.commit()
    cursor.close()
    conn.close()
    print(f"Inserted {len(readiness_df)} rows into {table_name}, computed_at = {now}")


if __name__ == "__main__":
    print("Loading invoice from Aiven...")
    invoice_df = load_invoice()
    print(f"Loaded {len(invoice_df)} invoice rows")

    print("\nRunning NET pipeline...")
    net_readiness = run_net_pipeline(invoice_df)
    print(net_readiness['readiness_flag'].value_counts())
    write_to_table(net_readiness, 'franchise_readiness_calculated_net')

    print("\nRunning GROSS pipeline...")
    gross_readiness = run_gross_pipeline(invoice_df)
    print(gross_readiness['readiness_flag'].value_counts())
    write_to_table(gross_readiness, 'franchise_readiness_calculated_gross')