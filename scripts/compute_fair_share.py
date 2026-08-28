"""
compute_fair_share.py — Fair Share of the Growth Gap (BD + TL)
Second, additive lens shown side-by-side with CAGR-based Nx-Fit, per owner's instruction — not a replacement.
Fully live/on-demand, same as Nx-Fit: does NOT write to Aiven, since the result depends entirely on
whatever target (multiplier + horizon) the founder is currently testing.

DEPENDENCY: requires bd_readiness_calculated / tl_readiness_calculated to already exist and be reasonably
fresh in Aiven (for lifetime_rank + trajectory). This script only reads them, never writes them.

Methodology, validated in fincore-ml/notebooks/09_fair_share_growth.ipynb:
- Compares only two full FYs (prior_full_fy vs recent_full_fy) — NOT the entire history. Deliberate:
  using more years would mean either averaging (hides the most recent, most decision-relevant year)
  or a compounding rate (reinvents CAGR, which this was built to avoid). The multi-year story is
  already covered by the existing `trajectory` field, carried along here for display only.
- Total Gap = (Base Revenue x target_multiplier) - Base Revenue, using RECENT_FULL_FY base revenue,
  same formula already live in compute_growth_levers.py.
- Annual Gap = Total Gap / horizon_years — an even split across the horizon. This is a deliberate
  simplification, consistent with the project's existing "levers are additive, not compounding, for
  simplicity" standing decision (see master doc). Without this step, one year of real growth was being
  compared against the ENTIRE multi-year gap, which made "on track" nearly impossible for anyone —
  a real bug caught during validation, not just an expected harsh result.
- fair_share_rupees = (entity's recent_fy_revenue / total team recent_fy_revenue) x annual_gap —
  bigger current performers are expected to carry a proportionally bigger share of the annual gap.
- Scale-aware classification: a top-tier entity (by lifetime_rank) with negative growth gets a softer,
  honest label ("Large base, currently flat or declining — worth watching") instead of "Not currently
  contributing to the goal" — mirrors the exact fix applied to the Phase 3 "Turnaround" scale-blindness
  bug (Surbhi/Joyeeta), which this rule would otherwise have repeated (caught live on Surbhi during
  validation of this script).
"""

import re
import pandas as pd
from db_connection import fetch_dataframe


def derive_fy(d):
    """Rule 1 — always derive FY from the date, never trust a stored FY column."""
    if d.month >= 4:
        return f"{d.year}-{d.year+1}"
    else:
        return f"{d.year-1}-{d.year}"


def normalize_name(x):
    """Collapse whitespace + strip. Applied fresh on both sides of every merge — never trust
    a file/table's prior name cleaning (this exact bug was hit and fixed during validation,
    e.g. 'Rajalaxmi  Das Das' vs 'Rajalaxmi Das Das')."""
    return re.sub(r'\s+', ' ', str(x)).strip() if pd.notna(x) else x


def _load_invoice():
    df = fetch_dataframe("SELECT nameOfBd, teamLeader, franchiseName, billDate, ourShare FROM invoice")
    df['billDate'] = pd.to_datetime(df['billDate'], errors='coerce')
    df = df.dropna(subset=['billDate'])
    df['ourShare'] = pd.to_numeric(df['ourShare'], errors='coerce')
    df['FY'] = df['billDate'].apply(derive_fy)
    return df


def _get_fy_boundaries(df):
    current_fy = derive_fy(df['billDate'].max())
    full_fys = sorted([fy for fy in df['FY'].unique() if fy != current_fy])
    recent_full_fy = full_fys[-1]
    prior_full_fy = full_fys[-2]
    return current_fy, recent_full_fy, prior_full_fy


def _clean_entity_name(series):
    """Handles both empty-string AND true-NaN blanks (a real, previously-hit bug — .fillna()
    alone only catches NaN, not '')."""
    return series.apply(
        lambda x: normalize_name(x) if pd.notna(x) and str(x).strip() != '' else pd.NA
    ).fillna('Unattributed')


def _build_entity_fair_share(df, entity_col, recent_full_fy, prior_full_fy, annual_gap,
                              readiness_df, readiness_name_col):
    df = df.copy()
    df[entity_col] = _clean_entity_name(df[entity_col])

    fy_agg = df.groupby([entity_col, 'FY']).agg(
        revenue=('ourShare', 'sum'),
        bills=('ourShare', 'count')
    ).reset_index()

    recent = fy_agg[fy_agg['FY'] == recent_full_fy][[entity_col, 'revenue', 'bills']].rename(
        columns={'revenue': 'recent_fy_revenue', 'bills': 'recent_fy_bills'})
    prior = fy_agg[fy_agg['FY'] == prior_full_fy][[entity_col, 'revenue', 'bills']].rename(
        columns={'revenue': 'prior_fy_revenue', 'bills': 'prior_fy_bills'})

    result = recent.merge(prior, on=entity_col, how='left')
    result['prior_fy_revenue'] = result['prior_fy_revenue'].fillna(0)
    result['prior_fy_bills'] = result['prior_fy_bills'].fillna(0)
    result['actual_growth_rupees'] = result['recent_fy_revenue'] - result['prior_fy_revenue']

    total_recent_revenue = result['recent_fy_revenue'].sum()
    result['fair_share_rupees'] = (result['recent_fy_revenue'] / total_recent_revenue) * annual_gap

    result[f'{entity_col}_norm'] = result[entity_col].apply(normalize_name)
    readiness_df = readiness_df.copy()
    readiness_df[f'{entity_col}_norm'] = readiness_df[readiness_name_col].apply(normalize_name)

    result = result.merge(
        readiness_df[[f'{entity_col}_norm', 'lifetime_rank', 'trajectory']],
        on=f'{entity_col}_norm', how='left'
    ).drop(columns=[f'{entity_col}_norm'])

    top_tier_cutoff = max(1, result['lifetime_rank'].notna().sum() // 2)

    # Same <3 bills threshold used elsewhere in this project (Lesson 1, low_data_year)
    LOW_DATA_BILL_THRESHOLD = 3

    # Split BEFORE classifying — watchlist entities never need a fair-share verdict at all
    is_low_data = (
        ((result['prior_fy_revenue'] == 0) & (result['recent_fy_revenue'] == 0)) |
        (result['recent_fy_bills'] < LOW_DATA_BILL_THRESHOLD) |
        (result['prior_fy_bills'] < LOW_DATA_BILL_THRESHOLD)
    )
    watchlist = result[is_low_data].copy()
    confident = result[~is_low_data].copy()

    def classify(row):
        is_top_tier = pd.notna(row['lifetime_rank']) and row['lifetime_rank'] <= top_tier_cutoff
        if row['actual_growth_rupees'] >= row['fair_share_rupees']:
            return 'On track for goal'
        elif row['actual_growth_rupees'] > 0:
            return 'Contributing, but below required pace'
        else:
            if is_top_tier:
                return 'Large base, currently flat or declining — worth watching'
            else:
                return 'Not currently contributing to the goal'

    confident['fair_share_flag'] = confident.apply(classify, axis=1)

    # Watchlist entries get an honest reason, not a pace verdict — mirrors Nx-Fit's watchlist "reason" field
    def watchlist_reason(row):
        if row['prior_fy_revenue'] == 0 and row['recent_fy_revenue'] == 0:
            return 'No billing activity in either year'
        return f"Fewer than {LOW_DATA_BILL_THRESHOLD} bills in one or both years"

    watchlist['reason'] = watchlist.apply(watchlist_reason, axis=1)

    return confident.sort_values('lifetime_rank'), watchlist.sort_values('lifetime_rank')


def compute_fair_share(target_multiplier: float, horizon_years: int):
    if horizon_years <= 0:
        raise ValueError("horizon_years must be greater than 0")

    invoice_df = _load_invoice()
    current_fy, recent_full_fy, prior_full_fy = _get_fy_boundaries(invoice_df)

    base_revenue = invoice_df[invoice_df['FY'] == recent_full_fy]['ourShare'].sum()
    target_revenue = base_revenue * target_multiplier
    total_gap = target_revenue - base_revenue
    annual_gap = total_gap / horizon_years

    bd_readiness = fetch_dataframe("SELECT bd_name, lifetime_rank, trajectory FROM bd_readiness_calculated")
    tl_readiness = fetch_dataframe("SELECT tl_name, lifetime_rank, trajectory FROM tl_readiness_calculated")
    # Franchise readiness — net basis only, per current scope decision.
    # Column names confirmed from franchise_readiness_calculated_net's live schema (Phase 5):
    # franchise_name, lifetime_rank, trajectory — NOT franchiseName_clean (that's the CSV-only naming;
    # the Aiven table already uses franchise_name, so no column mismatch here).
    franchise_readiness = fetch_dataframe(
        "SELECT franchise_name, lifetime_rank, trajectory FROM franchise_readiness_calculated_net"
    )

    bd_confident, bd_watchlist = _build_entity_fair_share(
        invoice_df, 'nameOfBd', recent_full_fy, prior_full_fy, annual_gap, bd_readiness, 'bd_name'
    )
    tl_confident, tl_watchlist = _build_entity_fair_share(
        invoice_df, 'teamLeader', recent_full_fy, prior_full_fy, annual_gap, tl_readiness, 'tl_name'
    )
    franchise_confident, franchise_watchlist = _build_entity_fair_share(
        invoice_df, 'franchiseName', recent_full_fy, prior_full_fy, annual_gap, franchise_readiness, 'franchise_name'
    )

    return {
        'current_fy': current_fy,
        'recent_full_fy': recent_full_fy,
        'prior_full_fy': prior_full_fy,
        'base_revenue': float(base_revenue),
        'target_multiplier': target_multiplier,
        'horizon_years': horizon_years,
        'target_revenue': float(target_revenue),
        'total_gap': float(total_gap),
        'annual_gap': float(annual_gap),
        'bd': {'confident': bd_confident.to_dict(orient='records'), 'watchlist': bd_watchlist.to_dict(orient='records')},
        'tl': {'confident': tl_confident.to_dict(orient='records'), 'watchlist': tl_watchlist.to_dict(orient='records')},
        'franchise': {
            'confident': franchise_confident.to_dict(orient='records'),
            'watchlist': franchise_watchlist.to_dict(orient='records'),
        },
    }    


if __name__ == "__main__":
    out = compute_fair_share(target_multiplier=3, horizon_years=5)
    print(f"Current FY (partial, excluded): {out['current_fy']}")
    print(f"Recent Full FY: {out['recent_full_fy']}  |  Prior Full FY: {out['prior_full_fy']}")
    print(f"Base Revenue: ₹{out['base_revenue']:,.2f}")
    print(f"Target Revenue ({out['target_multiplier']}x over {out['horizon_years']}yr): ₹{out['target_revenue']:,.2f}")
    print(f"Total Gap: ₹{out['total_gap']:,.2f}  |  Annual Gap: ₹{out['annual_gap']:,.2f}")
    print()

    for entity_name in ('bd', 'tl', 'franchise'):
        confident_df = pd.DataFrame(out[entity_name]['confident'])
        watchlist_count = len(out[entity_name]['watchlist'])
        flag_counts = confident_df['fair_share_flag'].value_counts().to_dict() if not confident_df.empty else {}
        print(f"{entity_name.upper()} — confident: {len(confident_df)}, watchlist: {watchlist_count}")
        print(f"  flags: {flag_counts}")