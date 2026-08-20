"""
compute_growth_levers.py
Computes live Growth Lever Simulator inputs from Aiven and writes results tables.
Mirrors the pattern established in compute_franchise_readiness.py:
full TRUNCATE + re-INSERT per table, computed_at timestamp, no CSV dependency.

STEP 1 (revised) — Lever 1 + Lever 3, matched exactly against the validated
logic in growth_level_simulator.ipynb (Cells 10 & 11). Lever 2, base revenue,
and Nx-Fit added in later steps.

KEY CORRECTION FROM FIRST DRAFT:
- The franchise "universe" used for TOTAL_ACTIVE_FRANCHISE_BASE is NOT raw
  franchisees_forms (917 rows) — it's franchises that have billed at least
  once, ever (i.e. unique names in `invoice`, same population the Franchise
  Clustering pipeline uses, ~470 franchises), joined to franchisees_forms.status.
- "Departed" = status != 'active' (ALL other statuses count — old_franchisee,
  blank, inactive, Closed, Taken a Break — not a curated subset), restricted
  to franchises that had revenue in RECENT_FULL_FY specifically (i.e. were
  active-with-billing that year, and have since left).
- RECENT_FULL_FY is derived from today's real calendar date, not from
  MAX(billDate) in invoice — matches the notebook exactly, so the FY boundary
  advances correctly even if invoice data lags behind.
"""

from datetime import date, datetime
import pandas as pd
from db_connection import fetch_dataframe, run_query

MIN_REAL_ACTIVATIONS_TO_TRUST = 3  # same "too small a sample" threshold used project-wide


# ──────────────────────────────────────────────────────────
# STEP A — FY derivation (matches notebook: from today's real date)
# ──────────────────────────────────────────────────────────

def get_current_and_recent_full_fy():
    today = date.today()
    if today.month >= 4:
        current_fy = f"{today.year}-{today.year + 1}"
    else:
        current_fy = f"{today.year - 1}-{today.year}"
    start_year = int(current_fy.split("-")[0])
    recent_full_fy = f"{start_year - 1}-{start_year}"
    return current_fy, recent_full_fy


def derive_fy(d):
    if pd.isna(d):
        return None
    return f"{d.year}-{d.year + 1}" if d.month >= 4 else f"{d.year - 1}-{d.year}"


# ──────────────────────────────────────────────────────────
# STEP B — Shared base data: franchise_fy + franchise_status
# (both Lever 1 and Lever 3 consume these, computed once)
# ──────────────────────────────────────────────────────────

def build_franchise_fy_and_status():
    invoice = fetch_dataframe("SELECT franchiseName, ourShare, billDate FROM invoice")
    invoice["ourShare"] = pd.to_numeric(invoice["ourShare"], errors="coerce")
    invoice["billDate"] = pd.to_datetime(invoice["billDate"], errors="coerce")
    invoice["franchiseName"] = invoice["franchiseName"].str.strip()
    invoice["fy"] = invoice["billDate"].apply(derive_fy)

    # Per-franchise, per-FY revenue + bill count (Rule 1 FY derivation, lifetime coverage)
    franchise_fy = (
        invoice.dropna(subset=["franchiseName", "fy"])
        .groupby(["franchiseName", "fy"])
        .agg(revenue=("ourShare", "sum"), bills=("ourShare", "count"))
        .reset_index()
    )
    franchise_fy["low_data_year"] = franchise_fy["bills"] < 3

    # The franchise "universe" = every franchise that has billed at least once,
    # ever (matches the ~470-franchise population Franchise Clustering uses) —
    # NOT raw franchisees_forms. This is the deliberate, validated definition.
    franchise_universe = pd.DataFrame({"franchiseName": franchise_fy["franchiseName"].unique()})

    franchisees_forms = fetch_dataframe("SELECT nameAsPerAgreement, status FROM franchisees_forms")
    franchisees_forms["nameAsPerAgreement"] = franchisees_forms["nameAsPerAgreement"].str.strip()

    franchise_status = franchise_universe.merge(
        franchisees_forms.rename(columns={"nameAsPerAgreement": "franchiseName"}),
        on="franchiseName", how="left"
    )

    return franchise_fy, franchise_status


# ──────────────────────────────────────────────────────────
# STEP C — Lever 1: Franchise Attrition Reduction
# ──────────────────────────────────────────────────────────

def compute_lever1_inputs(franchise_fy, franchise_status, recent_full_fy):
    print("Computing Lever 1 inputs (Franchise Attrition Reduction)...")

    recent_revenue = franchise_fy[franchise_fy["fy"] == recent_full_fy][["franchiseName", "revenue"]]

    merged = recent_revenue.merge(
        franchise_status[["franchiseName", "status"]], on="franchiseName", how="left"
    )
    merged["left_company"] = merged["status"] != "active"

    departed = merged[merged["left_company"]]
    if len(departed) > 0:
        avg_departed_revenue = departed["revenue"].mean()
    else:
        avg_departed_revenue = merged["revenue"].mean()  # fallback if nobody left this run

    total_active_franchise_base = (franchise_status["status"] == "active").sum()

    result = pd.DataFrame([{
        "total_active_franchises": int(total_active_franchise_base),
        "departed_franchise_count": int(len(departed)),
        "avg_departed_revenue": round(float(avg_departed_revenue), 2),
        "recent_full_fy": recent_full_fy,
        "computed_at": datetime.now(),
    }])

    print(f"  Active franchise base (billed-at-least-once universe): {total_active_franchise_base}")
    print(f"  Departed this run (status != active, had {recent_full_fy} revenue): {len(departed)}")
    print(f"  Avg departed revenue: ₹{avg_departed_revenue:,.2f}")

    return result


# ──────────────────────────────────────────────────────────
# STEP D — Lever 3: Dormant Franchise Activation
# ──────────────────────────────────────────────────────────

def compute_lever3_inputs(franchise_fy, franchise_status, recent_full_fy):
    print("\nComputing Lever 3 inputs (Dormant Franchise Activation)...")

    recent_revenue = franchise_fy[franchise_fy["fy"] == recent_full_fy][["franchiseName", "revenue"]]
    merged = recent_revenue.merge(
        franchise_status[["franchiseName", "status"]], on="franchiseName", how="left"
    )

    # Real-activation path: franchises whose FIRST-EVER bill fell in recent_full_fy
    first_bill_fy = franchise_fy.groupby("franchiseName")["fy"].min().reset_index()
    first_bill_fy.columns = ["franchiseName", "first_fy"]
    newly_activated_names = first_bill_fy[first_bill_fy["first_fy"] == recent_full_fy]["franchiseName"]
    real_activations = recent_revenue[recent_revenue["franchiseName"].isin(newly_activated_names)]

    if len(real_activations) >= MIN_REAL_ACTIVATIONS_TO_TRUST:
        avg_activated_revenue_recent_fy = real_activations["revenue"].mean()
        method_used = f"REAL DATA — {len(real_activations)} genuine first-year activations"
    else:
        # Proxy fallback — top-decile-by-revenue substitutes for the old
        # cluster_label != 'Top Performer' check (K-Means tiers aren't
        # migrated to Aiven; this preserves the same intent: exclude the
        # strongest performers from the proxy average). Flagged explicitly
        # since it's a live substitution, not a reused label.
        top_decile_cutoff = merged["revenue"].quantile(0.90)
        non_top_performers = merged[merged["revenue"] < top_decile_cutoff]
        avg_activated_revenue_recent_fy = non_top_performers["revenue"].mean()
        method_used = (f"PROXY (top-decile-by-revenue substitute for K-Means tier) — "
                        f"only {len(real_activations)} real activations found "
                        f"(need {MIN_REAL_ACTIVATIONS_TO_TRUST}+)")

    # Lifetime average, computed separately (per your instruction: keep both,
    # don't collapse to one) — avg lifetime revenue of currently-dormant franchises
    # once we identify them below is not meaningful (they have ~0 lifetime revenue
    # by definition of being dormant); instead this lifetime figure is the avg
    # LIFETIME revenue of the same real-activation cohort, for comparison.
    if len(real_activations) > 0:
        lifetime_for_activated = franchise_fy[
            franchise_fy["franchiseName"].isin(real_activations["franchiseName"])
        ].groupby("franchiseName")["revenue"].sum()
        avg_activated_revenue_lifetime = lifetime_for_activated.mean()
    else:
        avg_activated_revenue_lifetime = None

    # Dormant franchise list: active status, ZERO bills ever, Demo/Test/Sample filtered
    franchisees_forms_full = fetch_dataframe(
        "SELECT nameAsPerAgreement, status, joiningDate FROM franchisees_forms"
    )
    franchisees_forms_full["nameAsPerAgreement"] = franchisees_forms_full["nameAsPerAgreement"].str.strip()

    billed_names = set(franchise_fy["franchiseName"].unique())
    dormant = franchisees_forms_full[
        (franchisees_forms_full["status"] == "active") &
        (~franchisees_forms_full["nameAsPerAgreement"].isin(billed_names)) &
        (~franchisees_forms_full["nameAsPerAgreement"].str.contains(
            "Demo|Test|Sample", case=False, na=False))
    ]
    max_dormant_available = len(dormant)

    result = pd.DataFrame([{
        "max_dormant_available": int(max_dormant_available),
        "avg_activated_revenue_recent_fy": round(float(avg_activated_revenue_recent_fy), 2),
        "avg_activated_revenue_lifetime": (
            round(float(avg_activated_revenue_lifetime), 2)
            if avg_activated_revenue_lifetime is not None else None
        ),
        "real_activation_count": int(len(real_activations)),
        "method_used": method_used,
        "recent_full_fy": recent_full_fy,
        "computed_at": datetime.now(),
    }])

    print(f"  Dormant franchises available (active, zero bills, Demo/Test filtered): {max_dormant_available}")
    print(f"  Method: {method_used}")
    print(f"  Avg activated revenue (recent FY basis): ₹{avg_activated_revenue_recent_fy:,.2f}")
    if avg_activated_revenue_lifetime is not None:
        print(f"  Avg activated revenue (lifetime basis, same cohort): ₹{avg_activated_revenue_lifetime:,.2f}")

    return result


# ──────────────────────────────────────────────────────────
# STEP E — Write to Aiven
# ──────────────────────────────────────────────────────────

def write_lever1_table(df):
    run_query("""
        CREATE TABLE IF NOT EXISTS growth_lever1_inputs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            total_active_franchises INT NOT NULL,
            departed_franchise_count INT NOT NULL,
            avg_departed_revenue DECIMAL(14,2) NOT NULL,
            recent_full_fy VARCHAR(20) NOT NULL,
            computed_at DATETIME NOT NULL
        )
    """)
    run_query("TRUNCATE TABLE growth_lever1_inputs")
    row = df.iloc[0]
    run_query(
        """INSERT INTO growth_lever1_inputs
           (total_active_franchises, departed_franchise_count, avg_departed_revenue,
            recent_full_fy, computed_at)
           VALUES (%s, %s, %s, %s, %s)""",
        (
            int(row["total_active_franchises"]),
            int(row["departed_franchise_count"]),
            float(row["avg_departed_revenue"]),
            row["recent_full_fy"],
            row["computed_at"],
        ),
    )
    print("\n  Written to growth_lever1_inputs (1 row).")


def write_lever3_table(df):
    run_query("""
        CREATE TABLE IF NOT EXISTS growth_lever3_inputs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            max_dormant_available INT NOT NULL,
            avg_activated_revenue_recent_fy DECIMAL(14,2) NOT NULL,
            avg_activated_revenue_lifetime DECIMAL(14,2) NULL,
            real_activation_count INT NOT NULL,
            method_used VARCHAR(255) NOT NULL,
            recent_full_fy VARCHAR(20) NOT NULL,
            computed_at DATETIME NOT NULL
        )
    """)
    run_query("TRUNCATE TABLE growth_lever3_inputs")
    row = df.iloc[0]
    run_query(
        """INSERT INTO growth_lever3_inputs
           (max_dormant_available, avg_activated_revenue_recent_fy, avg_activated_revenue_lifetime,
            real_activation_count, method_used, recent_full_fy, computed_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (
            int(row["max_dormant_available"]),
            float(row["avg_activated_revenue_recent_fy"]),
            (float(row["avg_activated_revenue_lifetime"])
             if row["avg_activated_revenue_lifetime"] is not None else None),
            int(row["real_activation_count"]),
            row["method_used"],
            row["recent_full_fy"],
            row["computed_at"],
        ),
    )
    print("  Written to growth_lever3_inputs (1 row).")


# ──────────────────────────────────────────────────────────
# STEP G — Lever 2: Strike Ratio Improvement
# NEW logic — never built/validated before this. Per P5's
# clarified mechanics: enquiryStatus does NOT reliably mark
# billed enquiries (e.g. 'closed' is only 73.3% invoice-matched).
# The only trustworthy conversion signal is the direct join:
# enquiries.id = invoice.enquiry_id.
# ──────────────────────────────────────────────────────────

def compute_lever2_inputs(recent_full_fy):
    print("\nComputing Lever 2 inputs (Strike Ratio Improvement)...")

    enquiries = fetch_dataframe("SELECT id, dateOfAllocation FROM enquiries")
    enquiries["dateOfAllocation"] = pd.to_datetime(enquiries["dateOfAllocation"], errors="coerce")

    missing_date_count = enquiries["dateOfAllocation"].isna().sum()
    missing_date_pct = missing_date_count / len(enquiries) if len(enquiries) else 0
    print(f"  Total enquiry rows: {len(enquiries)}")
    print(f"  Missing/unparseable dateOfAllocation: {missing_date_count} ({missing_date_pct:.1%})")

    enquiries["fy"] = enquiries["dateOfAllocation"].apply(derive_fy)

    invoice = fetch_dataframe("SELECT ourShare, enquiry_id, billDate FROM invoice")
    invoice["ourShare"] = pd.to_numeric(invoice["ourShare"], errors="coerce")
    invoice["billDate"] = pd.to_datetime(invoice["billDate"], errors="coerce")
    invoice["fy"] = invoice["billDate"].apply(derive_fy)

    # --- Total enquiries in RECENT_FULL_FY (via dateOfAllocation, Rule 2) ---
    recent_fy_enquiries = enquiries[enquiries["fy"] == recent_full_fy]
    total_enquiries_recent_fy = len(recent_fy_enquiries)

    if total_enquiries_recent_fy == 0:
        raise ValueError(
            f"⚠️ No enquiries found with dateOfAllocation in {recent_full_fy} — "
            f"check data coverage before trusting this lever."
        )

    # --- Avg revenue per bill, RECENT_FULL_FY (same FY window as Lever 1/3) ---
    recent_fy_invoice = invoice[invoice["fy"] == recent_full_fy]
    total_bills_recent_fy = len(recent_fy_invoice)
    total_revenue_recent_fy = recent_fy_invoice["ourShare"].sum()
    avg_revenue_per_bill = (
        total_revenue_recent_fy / total_bills_recent_fy if total_bills_recent_fy else 0
    )

    # --- Current strike ratio, via the real join (P5-clarified logic,
    #     NOT enquiryStatus). Computed on RECENT_FULL_FY's enquiry cohort,
    #     matched against ALL invoice rows (an enquiry allocated in FY X
    #     can be billed later, so we don't restrict invoice's FY here). ---
    billed_enquiry_ids = set(invoice["enquiry_id"].dropna())
    recent_fy_enquiries = recent_fy_enquiries.copy()
    recent_fy_enquiries["was_billed"] = recent_fy_enquiries["id"].isin(billed_enquiry_ids)
    billed_count = recent_fy_enquiries["was_billed"].sum()
    current_strike_ratio = billed_count / total_enquiries_recent_fy

    result = pd.DataFrame([{
        "total_enquiries_recent_fy": int(total_enquiries_recent_fy),
        "billed_enquiries_recent_fy": int(billed_count),
        "current_strike_ratio": round(float(current_strike_ratio), 4),
        "avg_revenue_per_bill": round(float(avg_revenue_per_bill), 2),
        "missing_date_pct": round(float(missing_date_pct), 4),
        "recent_full_fy": recent_full_fy,
        "computed_at": datetime.now(),
    }])

    print(f"  Total enquiries ({recent_full_fy}): {total_enquiries_recent_fy}")
    print(f"  Billed (via id=enquiry_id join): {billed_count}")
    print(f"  Current strike ratio: {current_strike_ratio:.1%}")
    print(f"  Avg revenue per bill: ₹{avg_revenue_per_bill:,.2f}")

    return result


def write_lever2_table(df):
    run_query("""
        CREATE TABLE IF NOT EXISTS growth_lever2_inputs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            total_enquiries_recent_fy INT NOT NULL,
            billed_enquiries_recent_fy INT NOT NULL,
            current_strike_ratio DECIMAL(6,4) NOT NULL,
            avg_revenue_per_bill DECIMAL(14,2) NOT NULL,
            missing_date_pct DECIMAL(6,4) NOT NULL,
            recent_full_fy VARCHAR(20) NOT NULL,
            computed_at DATETIME NOT NULL
        )
    """)
    run_query("TRUNCATE TABLE growth_lever2_inputs")
    row = df.iloc[0]
    run_query(
        """INSERT INTO growth_lever2_inputs
           (total_enquiries_recent_fy, billed_enquiries_recent_fy, current_strike_ratio,
            avg_revenue_per_bill, missing_date_pct, recent_full_fy, computed_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (
            int(row["total_enquiries_recent_fy"]),
            int(row["billed_enquiries_recent_fy"]),
            float(row["current_strike_ratio"]),
            float(row["avg_revenue_per_bill"]),
            float(row["missing_date_pct"]),
            row["recent_full_fy"],
            row["computed_at"],
        ),
    )
    print("  Written to growth_lever2_inputs (1 row).")


# ──────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────
# STEP F — Base Revenue (company-wide, RECENT_FULL_FY only)
# Matches notebook Cell 4 exactly: live sum of invoice.ourShare
# for the most recent FULL FY — not lifetime, not partial current year.
# ──────────────────────────────────────────────────────────

def compute_base_revenue(recent_full_fy):
    print("\nComputing Base Revenue...")

    invoice = fetch_dataframe("SELECT ourShare, billDate FROM invoice")
    invoice["ourShare"] = pd.to_numeric(invoice["ourShare"], errors="coerce")
    invoice["billDate"] = pd.to_datetime(invoice["billDate"], errors="coerce")
    invoice["fy"] = invoice["billDate"].apply(derive_fy)

    company_revenue_by_fy = (
        invoice.dropna(subset=["fy"])
        .groupby("fy")["ourShare"]
        .sum()
    )

    if recent_full_fy not in company_revenue_by_fy.index:
        raise ValueError(
            f"⚠️ {recent_full_fy} not found in computed revenue — check invoice data coverage"
        )

    current_revenue_base = float(company_revenue_by_fy[recent_full_fy])

    result = pd.DataFrame([{
        "revenue": round(current_revenue_base, 2),
        "recent_full_fy": recent_full_fy,
        "computed_at": datetime.now(),
    }])

    print(f"  Base Revenue ({recent_full_fy}, live): ₹{current_revenue_base:,.2f}")
    return result


def write_base_revenue_table(df):
    run_query("""
        CREATE TABLE IF NOT EXISTS growth_base_revenue (
            id INT AUTO_INCREMENT PRIMARY KEY,
            revenue DECIMAL(14,2) NOT NULL,
            recent_full_fy VARCHAR(20) NOT NULL,
            computed_at DATETIME NOT NULL
        )
    """)
    run_query("TRUNCATE TABLE growth_base_revenue")
    row = df.iloc[0]
    run_query(
        """INSERT INTO growth_base_revenue (revenue, recent_full_fy, computed_at)
           VALUES (%s, %s, %s)""",
        (float(row["revenue"]), row["recent_full_fy"], row["computed_at"]),
    )
    print("  Written to growth_base_revenue (1 row).")



# ──────────────────────────────────────────────────────────
# STEP H — Nx-Fit (BD + TL): Historical CAGR vs Required CAGR
# Matches growth_level_simulator.ipynb Cells 6-7 exactly, live
# from Aiven instead of CSVs. Confirmed staying on CAGR per
# your instruction — fair-share model is a documented future swap.
# ──────────────────────────────────────────────────────────

def build_entity_fy(entity_col):
    """Generic version of the BD/TL per-FY builder — same pattern for both."""
    invoice = fetch_dataframe(f"SELECT {entity_col}, ourShare, billDate FROM invoice")
    invoice["ourShare"] = pd.to_numeric(invoice["ourShare"], errors="coerce")
    invoice["billDate"] = pd.to_datetime(invoice["billDate"], errors="coerce")
    invoice["fy"] = invoice["billDate"].apply(derive_fy)

    invoice[entity_col] = (
        invoice[entity_col].fillna("Unattributed")
        .str.strip().str.replace(r"\s+", " ", regex=True)
    )
    invoice_clean = invoice.dropna(subset=["billDate", entity_col])

    entity_fy = invoice_clean.groupby([entity_col, "fy"]).agg(
        revenue=("ourShare", "sum"), bills=("ourShare", "count")
    ).reset_index()
    entity_fy["low_data_year"] = entity_fy["bills"] < 3

    # Split off current (partial) FY — Nx-Fit CAGR only uses full years
    latest_date = invoice["billDate"].max()
    current_fy_from_data = derive_fy(latest_date)
    entity_fy_full = entity_fy[entity_fy["fy"] != current_fy_from_data].copy()

    return entity_fy_full


def compute_entity_cagr(fy_df, entity_col, current_fy_label):
    """Exact port of notebook Cell 6's compute_entity_cagr."""
    df = fy_df[fy_df["fy"] != current_fy_label].copy()
    clean_years = df[~df["low_data_year"]]
    revenue_floor = clean_years["revenue"].quantile(0.25) if len(clean_years) else 0
    df["excluded_low_base"] = (df["low_data_year"]) | (df["revenue"] < revenue_floor)
    usable = df[~df["excluded_low_base"]].sort_values("fy")

    results = []
    for entity, group in usable.groupby(entity_col):
        years_available = group["fy"].nunique()
        if years_available < 2:
            results.append({entity_col: entity, "entity_cagr": None, "usable_years": years_available})
            continue
        group = group.sort_values("fy")
        first_rev, last_rev = group["revenue"].iloc[0], group["revenue"].iloc[-1]
        n_periods = years_available - 1
        if first_rev <= 0:
            results.append({entity_col: entity, "entity_cagr": None, "usable_years": years_available})
            continue
        cagr = (last_rev / first_rev) ** (1 / n_periods) - 1
        results.append({entity_col: entity, "entity_cagr": cagr, "usable_years": years_available})
    return pd.DataFrame(results)


def required_cagr(current_revenue, target_revenue, current_fy, target_fy):
    years = int(target_fy.split("-")[0]) - int(current_fy.split("-")[0])
    if years <= 0:
        raise ValueError("target_fy must be after current_fy")
    return (target_revenue / current_revenue) ** (1 / years) - 1, years


MIN_YEARS_FOR_CONFIDENT_CAGR = 3

def assign_nx_fit_status(entity_cagr, req_cagr):
    if entity_cagr is None or pd.isna(entity_cagr):
        return "Insufficient Data for Nx-Fit"
    if entity_cagr < 0:
        return "Off Pace"
    if entity_cagr >= req_cagr:
        return "On Pace for This Goal"
    return "Below Pace — Would Need Acceleration"


def run_nx_fit(entity_cagr_df, current_revenue, target_revenue, current_fy, target_fy):
    req_cagr, years = required_cagr(current_revenue, target_revenue, current_fy, target_fy)
    out = entity_cagr_df.copy()
    out["required_cagr"] = req_cagr
    out["nx_fit_status"] = out["entity_cagr"].apply(lambda c: assign_nx_fit_status(c, req_cagr))
    out["low_confidence_nx"] = out["usable_years"] < MIN_YEARS_FOR_CONFIDENT_CAGR
    return out, req_cagr, years


def split_by_confidence(nx_df, entity_col):
    confident = nx_df[~nx_df["low_confidence_nx"]].drop(columns=["low_confidence_nx"]).copy()
    low_confidence = nx_df[nx_df["low_confidence_nx"]].drop(columns=["low_confidence_nx"]).copy()

    def reason(row):
        if row["usable_years"] <= 1:
            return "Fewer than 2 full-FY years of data — cannot compute a growth rate at all"
        return "Only 2 usable years — CAGR is a single year-over-year swing, not a smoothed trend"

    if len(low_confidence) > 0:
        low_confidence["reason"] = low_confidence.apply(reason, axis=1)
    return confident, low_confidence


def compute_nx_fit(current_fy, recent_full_fy, base_revenue, target_multiplier=3, horizon_years=5):
    """
    target_multiplier / horizon_years are placeholders standing in for the
    founder's real target input (per notebook Cell 6's own comment: 'not
    the final UI input'). FastAPI endpoint will accept these as real
    query params later — this default just proves the pipeline end-to-end.
    """
    print(f"\nComputing Nx-Fit (BD + TL), target = {target_multiplier}x over {horizon_years} years...")

    bd_fy = build_entity_fy("nameOfBd")
    tl_fy = build_entity_fy("teamLeader")

    bd_cagr = compute_entity_cagr(bd_fy, "nameOfBd", current_fy)
    tl_cagr = compute_entity_cagr(tl_fy, "teamLeader", current_fy)

    target_year_start = int(recent_full_fy.split("-")[0]) + horizon_years
    target_fy = f"{target_year_start}-{target_year_start + 1}"
    target_revenue = base_revenue * target_multiplier

    bd_nx, req_cagr, years = run_nx_fit(bd_cagr, base_revenue, target_revenue, recent_full_fy, target_fy)
    tl_nx, _, _ = run_nx_fit(tl_cagr, base_revenue, target_revenue, recent_full_fy, target_fy)

    print(f"  Scenario: {target_multiplier}x revenue (₹{target_revenue:,.0f}) by {target_fy} ({years} years)")
    print(f"  Required CAGR: {req_cagr:.1%}")

    bd_confident, bd_watch = split_by_confidence(bd_nx, "nameOfBd")
    tl_confident, tl_watch = split_by_confidence(tl_nx, "teamLeader")

    print(f"  BD — Confident: {len(bd_confident)}, Watchlist: {len(bd_watch)}")
    print(f"  TL — Confident: {len(tl_confident)}, Watchlist: {len(tl_watch)}")

    return bd_confident, bd_watch, tl_confident, tl_watch, req_cagr, target_fy


def write_nx_fit_tables(bd_confident, bd_watch, tl_confident, tl_watch, target_fy, req_cagr):
    computed_at = datetime.now()

    run_query("""
        CREATE TABLE IF NOT EXISTS growth_nx_fit_bd (
            id INT AUTO_INCREMENT PRIMARY KEY,
            nameOfBd VARCHAR(255) NOT NULL,
            entity_cagr DECIMAL(10,6) NULL,
            usable_years INT NOT NULL,
            required_cagr DECIMAL(10,6) NOT NULL,
            nx_fit_status VARCHAR(100) NOT NULL,
            confidence VARCHAR(20) NOT NULL,
            reason VARCHAR(255) NULL,
            target_fy VARCHAR(20) NOT NULL,
            computed_at DATETIME NOT NULL
        )
    """)
    run_query("""
        CREATE TABLE IF NOT EXISTS growth_nx_fit_tl (
            id INT AUTO_INCREMENT PRIMARY KEY,
            teamLeader VARCHAR(255) NOT NULL,
            entity_cagr DECIMAL(10,6) NULL,
            usable_years INT NOT NULL,
            required_cagr DECIMAL(10,6) NOT NULL,
            nx_fit_status VARCHAR(100) NOT NULL,
            confidence VARCHAR(20) NOT NULL,
            reason VARCHAR(255) NULL,
            target_fy VARCHAR(20) NOT NULL,
            computed_at DATETIME NOT NULL
        )
    """)
    run_query("TRUNCATE TABLE growth_nx_fit_bd")
    run_query("TRUNCATE TABLE growth_nx_fit_tl")

    def insert_rows(df, entity_col, table, confidence_label):
        for _, row in df.iterrows():
            reason = row["reason"] if "reason" in df.columns else None
            entity_cagr = None if pd.isna(row["entity_cagr"]) else float(row["entity_cagr"])
            run_query(
                f"""INSERT INTO {table}
                   ({entity_col}, entity_cagr, usable_years, required_cagr,
                    nx_fit_status, confidence, reason, target_fy, computed_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (row[entity_col], entity_cagr, int(row["usable_years"]), float(row["required_cagr"]),
                 row["nx_fit_status"], confidence_label, reason, target_fy, computed_at),
            )

    insert_rows(bd_confident, "nameOfBd", "growth_nx_fit_bd", "Confident")
    insert_rows(bd_watch, "nameOfBd", "growth_nx_fit_bd", "Watchlist")
    insert_rows(tl_confident, "teamLeader", "growth_nx_fit_tl", "Confident")
    insert_rows(tl_watch, "teamLeader", "growth_nx_fit_tl", "Watchlist")

    print("  Written to growth_nx_fit_bd and growth_nx_fit_tl.")


# ──────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    current_fy, recent_full_fy = get_current_and_recent_full_fy()
    print(f"CURRENT_FY (from today's date): {current_fy}")
    print(f"RECENT_FULL_FY (derived): {recent_full_fy}\n")

    franchise_fy, franchise_status = build_franchise_fy_and_status()
    print(f"Franchise universe (billed at least once, ever): {len(franchise_status)}\n")

    lever1_df = compute_lever1_inputs(franchise_fy, franchise_status, recent_full_fy)
    lever3_df = compute_lever3_inputs(franchise_fy, franchise_status, recent_full_fy)
    base_revenue_df = compute_base_revenue(recent_full_fy)
    lever2_df = compute_lever2_inputs(recent_full_fy)


    print("\n=== Lever 2 ===")
    print(lever2_df.to_string(index=False))

    write_lever1_table(lever1_df)
    write_lever3_table(lever3_df)
    write_lever2_table(lever2_df)
    write_base_revenue_table(base_revenue_df)

    print("\n=== Lever 1 ===")
    print(lever1_df.to_string(index=False))
    print("\n=== Lever 2 ===")
    print(lever2_df.to_string(index=False))
    print("\n=== Lever 3 ===")
    print(lever3_df.to_string(index=False))
    print("\n=== Base Revenue ===")
    print(base_revenue_df.to_string(index=False))

    # Sanity-check preview
    example_attrition_pct = 0.10
    example_dormant_activated = 20
    l1 = lever1_df.iloc[0]
    l3 = lever3_df.iloc[0]
    lever1_revenue = example_attrition_pct * l1["total_active_franchises"] * l1["avg_departed_revenue"]
    lever3_revenue = example_dormant_activated * l3["avg_activated_revenue_recent_fy"]
    print(f"\nSanity check — Lever 1 @ 10pp attrition reduction: ₹{lever1_revenue:,.2f}")
    print(f"Sanity check — Lever 3 @ activate 20 dormant: ₹{lever3_revenue:,.2f}")
    print(f"Combined: ₹{lever1_revenue + lever3_revenue:,.2f}")
    print(f"Base Revenue: ₹{base_revenue_df.iloc[0]['revenue']:,.2f}")

    bd_confident, bd_watch, tl_confident, tl_watch, req_cagr, target_fy = compute_nx_fit(
        current_fy, recent_full_fy, base_revenue_df.iloc[0]["revenue"]
    )
    write_nx_fit_tables(bd_confident, bd_watch, tl_confident, tl_watch, target_fy, req_cagr)