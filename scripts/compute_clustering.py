import pandas as pd
from datetime import datetime, timezone
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from db_connection import fetch_dataframe, run_query, get_connection

CHOSEN_K = 4  # Validated by comparing real names at k=3 vs k=4 across all
              # three notebooks (Franchise/Industry/Sub-Industry) — a settled
              # human decision, not re-derived live. Per project rule: "human
              # must re-examine if business shape fundamentally changes."
LOW_DATA_THRESHOLD = 3


def compute_franchise_clustering():
    print("--- Franchise Clustering (gross revenue, K-Means k=4) ---")

    invoice = fetch_dataframe("SELECT franchiseName, serviceCharges, billDate FROM invoice")
    invoice["serviceCharges"] = pd.to_numeric(invoice["serviceCharges"], errors="coerce")
    invoice["billDate"] = pd.to_datetime(invoice["billDate"], errors="coerce")
    df = invoice.dropna(subset=["serviceCharges", "billDate", "franchiseName"]).copy()

    franchise_agg = df.groupby("franchiseName").agg(
        total_revenue=("serviceCharges", "sum"),
        total_bills=("serviceCharges", "count"),
        avg_revenue_per_bill=("serviceCharges", "mean"),
        first_bill=("billDate", "min"),
        last_bill=("billDate", "max"),
    ).reset_index()

    franchise_agg["active_months"] = (
        (franchise_agg["last_bill"].dt.year - franchise_agg["first_bill"].dt.year) * 12 +
        (franchise_agg["last_bill"].dt.month - franchise_agg["first_bill"].dt.month) + 1
    )
    franchise_agg["bills_per_month"] = franchise_agg["total_bills"] / franchise_agg["active_months"]

    print(f"  Unique franchises: {len(franchise_agg)} (validated baseline: 470)")

    low_history = franchise_agg[franchise_agg["total_bills"] < LOW_DATA_THRESHOLD].copy()
    established = franchise_agg[franchise_agg["total_bills"] >= LOW_DATA_THRESHOLD].copy()
    print(f"  New / Insufficient History: {len(low_history)}, Established: {len(established)}")

    features = ["total_revenue", "total_bills", "avg_revenue_per_bill", "bills_per_month"]
    X_scaled = StandardScaler().fit_transform(established[features])

    km = KMeans(n_clusters=CHOSEN_K, random_state=42, n_init=10)
    established["cluster_raw"] = km.fit_predict(X_scaled)

    cluster_stats = established.groupby("cluster_raw").agg(
        avg_revenue=("total_revenue", "mean"),
        avg_bills_per_month=("bills_per_month", "mean"),
        count=("franchiseName", "size"),
    )

    # Burst = highest bills/month among clusters smaller than the largest
    burst_id = cluster_stats[cluster_stats["count"] < cluster_stats["count"].max()]["avg_bills_per_month"].idxmax()
    remaining = cluster_stats.drop(index=burst_id).sort_values("avg_revenue", ascending=False)
    remaining_labels = ["Top Performer", "Established – High Value", "Core / Established"]

    rank_to_label = {burst_id: "High-Frequency Burst"}
    for rank, cluster_id in enumerate(remaining.index):
        rank_to_label[cluster_id] = remaining_labels[rank] if rank < len(remaining_labels) else f"Tier {rank+1}"

    established["cluster_label"] = established["cluster_raw"].map(rank_to_label)
    established["low_confidence"] = established["total_bills"] < LOW_DATA_THRESHOLD

    low_history["cluster_label"] = "New / Insufficient History"
    low_history["low_confidence"] = True

    cols = ["franchiseName", "total_revenue", "total_bills", "avg_revenue_per_bill",
            "bills_per_month", "active_months", "cluster_label", "low_confidence"]
    franchise_full = pd.concat([established[cols], low_history[cols]], ignore_index=True)

    # Status join, with dedupe for franchises with multiple forms rows (e.g. Pradheep Kumar Janarthanan)
    franchise_status = fetch_dataframe("SELECT nameAsPerAgreement, status, city, state, joiningDate FROM franchisees_forms")
    franchise_status["nameAsPerAgreement"] = franchise_status["nameAsPerAgreement"].str.strip()
    franchise_status_dedup = franchise_status.sort_values("status").drop_duplicates(subset="nameAsPerAgreement", keep="first")

    franchise_full["franchiseName_clean"] = franchise_full["franchiseName"].str.strip()
    franchise_full = franchise_full.merge(
        franchise_status_dedup[["nameAsPerAgreement", "status"]],
        left_on="franchiseName_clean", right_on="nameAsPerAgreement", how="left"
    ).drop(columns=["franchiseName_clean", "nameAsPerAgreement"])

    match_rate = franchise_full["status"].notna().sum() / len(franchise_full) * 100
    print(f"  Status join match rate: {match_rate:.1f}%")
    print(f"  Final tier distribution:\n{franchise_full['cluster_label'].value_counts()}")

    # Dormant Active Franchises — active status, zero bills ever, Demo/Test/Sample filtered
    billed_names = set(franchise_full["franchiseName"].str.strip())
    active_forms = franchise_status[franchise_status["status"].str.lower() == "active"].copy()
    dormant = active_forms[
        (~active_forms["nameAsPerAgreement"].isin(billed_names)) &
        (~active_forms["nameAsPerAgreement"].str.lower().str.contains("demo|test|sample", na=False))
    ][["nameAsPerAgreement", "city", "state", "joiningDate", "status"]]
    print(f"  Dormant active franchises: {len(dormant)}")

    return franchise_full, dormant


def write_franchise_clustering(franchise_full, dormant):
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    run_query("DROP TABLE IF EXISTS ml_franchise_clustering")
    run_query("DROP TABLE IF EXISTS ml_dormant_franchises")

    run_query("""
        CREATE TABLE ml_franchise_clustering (
            id INT AUTO_INCREMENT PRIMARY KEY,
            franchiseName VARCHAR(255) NOT NULL,
            total_revenue DECIMAL(14,2) NOT NULL,
            total_bills INT NOT NULL,
            avg_revenue_per_bill DECIMAL(14,2) NOT NULL,
            bills_per_month DECIMAL(10,4) NOT NULL,
            active_months INT NOT NULL,
            cluster_label VARCHAR(100) NOT NULL,
            low_confidence BOOLEAN NOT NULL,
            status VARCHAR(50) NULL,
            computed_at DATETIME NOT NULL
        );
    """)
    run_query("""
        CREATE TABLE ml_dormant_franchises (
            id INT AUTO_INCREMENT PRIMARY KEY,
            nameAsPerAgreement VARCHAR(255) NOT NULL,
            city VARCHAR(100) NULL,
            state VARCHAR(100) NULL,
            joiningDate DATE NULL,
            status VARCHAR(50) NULL,
            computed_at DATETIME NOT NULL
        );
    """)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.executemany(
        """INSERT INTO ml_franchise_clustering
           (franchiseName, total_revenue, total_bills, avg_revenue_per_bill,
            bills_per_month, active_months, cluster_label, low_confidence, status, computed_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        [
            (r["franchiseName"], float(r["total_revenue"]), int(r["total_bills"]),
             float(r["avg_revenue_per_bill"]), float(r["bills_per_month"]), int(r["active_months"]),
             r["cluster_label"], bool(r["low_confidence"]),
             r["status"] if pd.notna(r["status"]) else None, now_utc)
            for _, r in franchise_full.iterrows()
        ]
    )

    cursor.executemany(
        """INSERT INTO ml_dormant_franchises
           (nameAsPerAgreement, city, state, joiningDate, status, computed_at)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        [
            (r["nameAsPerAgreement"],
             r["city"] if pd.notna(r["city"]) else None,
             r["state"] if pd.notna(r["state"]) else None,
             r["joiningDate"].strftime("%Y-%m-%d") if pd.notna(r["joiningDate"]) else None,
             r["status"], now_utc)
            for _, r in dormant.iterrows()
        ]
    )

    conn.commit()
    cursor.close()
    conn.close()
    print(f"  [SUCCESS] Inserted {len(franchise_full)} rows into ml_franchise_clustering, {len(dormant)} into ml_dormant_franchises.")



if __name__ == "__main__":
    franchise_full, dormant = compute_franchise_clustering()
    write_franchise_clustering(franchise_full, dormant)
    print("\nDone.")

# ============================================================
# INDUSTRY CLUSTERING
# ============================================================

def compute_industry_clustering():
    print("\n--- Industry Clustering (gross revenue, K-Means k=4) ---")

    invoice = fetch_dataframe("SELECT industry, serviceCharges, franchiseName FROM invoice")
    invoice["serviceCharges"] = pd.to_numeric(invoice["serviceCharges"], errors="coerce")
    df = invoice.dropna(subset=["industry", "serviceCharges"]).copy()

    df["industry"] = df["industry"].astype(str).str.strip()
    df = df[df["industry"] != ""]
    junk_mask = df["industry"].str.match(r"^\d+$")
    df = df[~junk_mask]

    print(f"  Rows after cleaning: {len(df)}, unique industries: {df['industry'].nunique()}")

    industry_agg = df.groupby("industry").agg(
        total_revenue=("serviceCharges", "sum"),
        total_bills=("serviceCharges", "count"),
        avg_revenue_per_bill=("serviceCharges", "mean"),
        unique_franchises=("franchiseName", "nunique"),
    ).reset_index()

    low_data = industry_agg[industry_agg["total_bills"] < LOW_DATA_THRESHOLD].copy()
    established = industry_agg[industry_agg["total_bills"] >= LOW_DATA_THRESHOLD].copy()
    print(f"  New / Insufficient Data: {len(low_data)}, Established: {len(established)}")

    features = ["total_revenue", "total_bills", "avg_revenue_per_bill", "unique_franchises"]
    X_scaled = StandardScaler().fit_transform(established[features])

    km = KMeans(n_clusters=CHOSEN_K, random_state=42, n_init=10)
    established["cluster_raw"] = km.fit_predict(X_scaled)

    # NOTE: Industry's labeling is simpler than Franchise/Sub-Industry — it ranks
    # clusters purely by avg_revenue descending and assigns labels positionally.
    # It does NOT specifically select "Premium" by avg_revenue_per_bill the way
    # the other two do. This matches the validated notebook exactly, but is a
    # real asymmetry worth knowing: if industry revenue patterns shift, "Premium"
    # here could stop correlating with actual per-bill value. Not fixed — replicating
    # validated behavior as-is, not silently "improving" it.
    cluster_profile = established.groupby("cluster_raw").agg(
        avg_revenue=("total_revenue", "mean")
    ).sort_values("avg_revenue", ascending=False)

    label_names = ["Dominant Industries", "Established / Core", "Premium (High Value/Bill)", "Emerging / Niche"]
    rank_to_label = {cid: label_names[i] if i < len(label_names) else f"Tier {i+1}"
                      for i, cid in enumerate(cluster_profile.index)}

    established["cluster_label"] = established["cluster_raw"].map(rank_to_label)
    established["low_confidence"] = established["unique_franchises"] < 3

    low_data["cluster_label"] = "New / Insufficient Data"
    low_data["low_confidence"] = True

    cols = ["industry", "total_revenue", "total_bills", "avg_revenue_per_bill", "unique_franchises",
            "cluster_label", "low_confidence"]
    final = pd.concat([established[cols], low_data[cols]], ignore_index=True)

    print(f"  Final total: {len(final)}")
    print(f"  Tier distribution:\n{final['cluster_label'].value_counts()}")

    return final


def write_industry_clustering(final):
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    run_query("DROP TABLE IF EXISTS ml_industry_clustering")
    run_query("""
        CREATE TABLE ml_industry_clustering (
            id INT AUTO_INCREMENT PRIMARY KEY,
            industry VARCHAR(255) NOT NULL,
            total_revenue DECIMAL(14,2) NOT NULL,
            total_bills INT NOT NULL,
            avg_revenue_per_bill DECIMAL(14,2) NOT NULL,
            unique_franchises INT NOT NULL,
            cluster_label VARCHAR(100) NOT NULL,
            low_confidence BOOLEAN NOT NULL,
            computed_at DATETIME NOT NULL
        );
    """)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.executemany(
        """INSERT INTO ml_industry_clustering
           (industry, total_revenue, total_bills, avg_revenue_per_bill, unique_franchises,
            cluster_label, low_confidence, computed_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        [
            (r["industry"], float(r["total_revenue"]), int(r["total_bills"]),
             float(r["avg_revenue_per_bill"]), int(r["unique_franchises"]),
             r["cluster_label"], bool(r["low_confidence"]), now_utc)
            for _, r in final.iterrows()
        ]
    )
    conn.commit()
    cursor.close()
    conn.close()
    print(f"  [SUCCESS] Inserted {len(final)} rows into ml_industry_clustering.")



# ============================================================
# SUB-INDUSTRY CLUSTERING
# ============================================================

def compute_subindustry_clustering():
    print("\n--- Sub-Industry Clustering (gross revenue, K-Means k=4) ---")

    invoice = fetch_dataframe("SELECT subIndustry, serviceCharges, franchiseName FROM invoice")
    invoice["serviceCharges"] = pd.to_numeric(invoice["serviceCharges"], errors="coerce")
    df = invoice.dropna(subset=["subIndustry", "serviceCharges"]).copy()

    df["subIndustry"] = df["subIndustry"].astype(str).str.strip()
    df = df[df["subIndustry"] != ""]
    junk_mask = df["subIndustry"].str.match(r"^\d+$")
    df = df[~junk_mask]

    # Dynamic casing-dedup — detected fresh every run, never a fixed list
    case_dupe_groups = df.groupby(df["subIndustry"].str.lower())["subIndustry"].unique()
    case_dupe_groups = case_dupe_groups[case_dupe_groups.apply(len) > 1]

    casing_map = {}
    for lower_key, variants in case_dupe_groups.items():
        counts = df[df["subIndustry"].str.lower() == lower_key]["subIndustry"].value_counts()
        canonical = counts.idxmax()
        for variant in variants:
            if variant != canonical:
                casing_map[variant] = canonical
    df["subIndustry"] = df["subIndustry"].replace(casing_map)

    print(f"  Casing duplicates merged this run: {len(casing_map)}")
    print(f"  Rows after cleaning: {len(df)}, unique sub-industries: {df['subIndustry'].nunique()}")

    subindustry_agg = df.groupby("subIndustry").agg(
        total_revenue=("serviceCharges", "sum"),
        total_bills=("serviceCharges", "count"),
        avg_revenue_per_bill=("serviceCharges", "mean"),
        unique_franchises=("franchiseName", "nunique"),
    ).reset_index()

    low_data = subindustry_agg[subindustry_agg["total_bills"] < LOW_DATA_THRESHOLD].copy()
    established = subindustry_agg[subindustry_agg["total_bills"] >= LOW_DATA_THRESHOLD].copy()
    print(f"  New / Insufficient Data: {len(low_data)}, Established: {len(established)}")

    features = ["total_revenue", "total_bills", "avg_revenue_per_bill", "unique_franchises"]
    X_scaled = StandardScaler().fit_transform(established[features])

    km = KMeans(n_clusters=CHOSEN_K, random_state=42, n_init=10)
    established["cluster_raw"] = km.fit_predict(X_scaled)

    # Sub-Industry's labeling IS metric-aware (unlike Industry): Dominant = highest
    # avg_revenue, Premium = highest avg_revenue_per_bill among the rest,
    # Established = next highest avg_revenue, Niche = whatever's left.
    cluster_profile = established.groupby("cluster_raw").agg(
        avg_revenue=("total_revenue", "mean"),
        avg_rev_per_bill=("avg_revenue_per_bill", "mean"),
    )

    dominant_id = cluster_profile["avg_revenue"].idxmax()
    remaining = cluster_profile.drop(index=dominant_id)

    premium_id = remaining["avg_rev_per_bill"].idxmax()
    remaining2 = remaining.drop(index=premium_id)

    established_id = remaining2["avg_revenue"].idxmax()
    niche_id = remaining2["avg_revenue"].idxmin()

    label_map = {
        dominant_id: "Dominant Sub-Industries",
        premium_id: "Premium (High Value/Bill)",
        established_id: "Established / Core",
        niche_id: "Emerging / Niche",
    }

    established["cluster_label"] = established["cluster_raw"].map(label_map)
    established["low_confidence"] = established["unique_franchises"] < 3

    low_data["cluster_label"] = "New / Insufficient Data"
    low_data["low_confidence"] = True

    cols = ["subIndustry", "total_revenue", "total_bills", "avg_revenue_per_bill", "unique_franchises",
            "cluster_label", "low_confidence"]
    final = pd.concat([established[cols], low_data[cols]], ignore_index=True)

    print(f"  Final total: {len(final)}")
    print(f"  Tier distribution:\n{final['cluster_label'].value_counts()}")

    return final


def write_subindustry_clustering(final):
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    run_query("DROP TABLE IF EXISTS ml_subindustry_clustering")
    run_query("""
        CREATE TABLE ml_subindustry_clustering (
            id INT AUTO_INCREMENT PRIMARY KEY,
            subIndustry VARCHAR(255) NOT NULL,
            total_revenue DECIMAL(14,2) NOT NULL,
            total_bills INT NOT NULL,
            avg_revenue_per_bill DECIMAL(14,2) NOT NULL,
            unique_franchises INT NOT NULL,
            cluster_label VARCHAR(100) NOT NULL,
            low_confidence BOOLEAN NOT NULL,
            computed_at DATETIME NOT NULL
        );
    """)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.executemany(
        """INSERT INTO ml_subindustry_clustering
           (subIndustry, total_revenue, total_bills, avg_revenue_per_bill, unique_franchises,
            cluster_label, low_confidence, computed_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        [
            (r["subIndustry"], float(r["total_revenue"]), int(r["total_bills"]),
             float(r["avg_revenue_per_bill"]), int(r["unique_franchises"]),
             r["cluster_label"], bool(r["low_confidence"]), now_utc)
            for _, r in final.iterrows()
        ]
    )
    conn.commit()
    cursor.close()
    conn.close()
    print(f"  [SUCCESS] Inserted {len(final)} rows into ml_subindustry_clustering.")

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    franchise_full, dormant = compute_franchise_clustering()
    write_franchise_clustering(franchise_full, dormant)

    industry_final = compute_industry_clustering()
    write_industry_clustering(industry_final)

    subindustry_final = compute_subindustry_clustering()
    write_subindustry_clustering(subindustry_final)

    print("\nAll clustering pipelines complete.")