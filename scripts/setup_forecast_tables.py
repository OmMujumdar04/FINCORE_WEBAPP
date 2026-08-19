import pandas as pd
from db_connection import get_connection, run_query

def migrate_expenditure():
    print("Checking / migrating expenditure table to Aiven MySQL...")
    create_exp_table_sql = """
    CREATE TABLE IF NOT EXISTS expenditure (
        id INT NOT NULL,
        srNo VARCHAR(50),
        billDate DATE,
        particulars VARCHAR(500),
        vendorId VARCHAR(50),
        expenses VARCHAR(255),
        amount DECIMAL(14,2),
        gst DECIMAL(14,2),
        tds DECIMAL(14,2),
        net DECIMAL(14,2),
        supplyBillNo VARCHAR(100),
        purchaseNo VARCHAR(100),
        createdAt DATETIME,
        supportingDocument VARCHAR(255),
        supportingDocumentName VARCHAR(255),
        expenseType VARCHAR(50),
        franchiseeAmount DECIMAL(14,2),
        recruitmentAmount DECIMAL(14,2),
        PRIMARY KEY (id)
    );
    """
    run_query(create_exp_table_sql)

    # Check row count
    res = run_query("SELECT COUNT(*) FROM expenditure", fetch=True)
    if res and res[0][0] > 0:
        print(f"expenditure already has {res[0][0]} rows. Truncating and reloading clean data...")
        run_query("TRUNCATE TABLE expenditure")

    df = pd.read_csv("d:/FINCORE/exp.csv")
    print(f"Loaded {len(df)} rows from exp.csv. Inserting into Aiven...")

    insert_sql = """
    INSERT INTO expenditure (
        id, srNo, billDate, particulars, vendorId, expenses, amount, gst, tds, net,
        supplyBillNo, purchaseNo, createdAt, supportingDocument, supportingDocumentName,
        expenseType, franchiseeAmount, recruitmentAmount
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    conn = get_connection()
    cursor = conn.cursor()

    rows = []
    for _, r in df.iterrows():
        def clean_val(val, is_num=False, is_date=False):
            if pd.isna(val) or str(val).strip().upper() in ['NULL', 'NONE', '']:
                return None
            if is_num:
                return float(val)
            if is_date:
                return str(val).strip()
            return str(val).strip()

        row = (
            int(r['id']),
            clean_val(r['srNo']),
            clean_val(r['billDate'], is_date=True),
            clean_val(r['particulars']),
            clean_val(r['vendorId']),
            clean_val(r['expenses']),
            clean_val(r['amount'], is_num=True),
            clean_val(r['gst'], is_num=True),
            clean_val(r['tds'], is_num=True),
            clean_val(r['net'], is_num=True),
            clean_val(r['supplyBillNo']),
            clean_val(r['purchaseNo']),
            clean_val(r['createdAt'], is_date=True),
            clean_val(r['supportingDocument']),
            clean_val(r['supportingDocumentName']),
            clean_val(r['expenseType']),
            clean_val(r['franchiseeAmount'], is_num=True),
            clean_val(r['recruitmentAmount'], is_num=True),
        )
        rows.append(row)

    cursor.executemany(insert_sql, rows)
    conn.commit()
    cursor.close()
    conn.close()

    count_check = run_query("SELECT COUNT(*) FROM expenditure", fetch=True)
    print(f"[SUCCESS] Successfully inserted {count_check[0][0]} rows into expenditure.")

def create_forecast_tables():
    print("Creating forecast results tables...")
    
    tables_sql = [
        """
        CREATE TABLE IF NOT EXISTS ml_revenue_forecast (
            ds DATE NOT NULL,
            month_label VARCHAR(50) NOT NULL,
            actual DECIMAL(14,2) NULL,
            forecast DECIMAL(14,2) NULL,
            lower_bound DECIMAL(14,2) NULL,
            upper_bound DECIMAL(14,2) NULL,
            is_forecast BOOLEAN NOT NULL,
            computed_at DATETIME NOT NULL,
            PRIMARY KEY (ds)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS ml_revenue_forecast_kpis (
            kpi_id VARCHAR(50) NOT NULL,
            next_month_label VARCHAR(50) NOT NULL,
            next_month_val DECIMAL(14,2) NOT NULL,
            next_month_lower DECIMAL(14,2) NOT NULL,
            next_month_upper DECIMAL(14,2) NOT NULL,
            next_month_yoy_pct DECIMAL(8,2) NULL,
            last_actual_label VARCHAR(50) NOT NULL,
            last_actual_val DECIMAL(14,2) NOT NULL,
            forecast_total_6m DECIMAL(14,2) NOT NULL,
            forecast_period_label VARCHAR(100) NOT NULL,
            computed_at DATETIME NOT NULL,
            PRIMARY KEY (kpi_id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS ml_expense_forecast (
            ds DATE NOT NULL,
            month_label VARCHAR(50) NOT NULL,
            actual DECIMAL(14,2) NULL,
            forecast DECIMAL(14,2) NULL,
            lower_bound DECIMAL(14,2) NULL,
            upper_bound DECIMAL(14,2) NULL,
            is_forecast BOOLEAN NOT NULL,
            validation_flag VARCHAR(50) NOT NULL,
            computed_at DATETIME NOT NULL,
            PRIMARY KEY (ds)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS ml_expense_forecast_kpis (
            kpi_id VARCHAR(50) NOT NULL,
            next_month_label VARCHAR(50) NOT NULL,
            next_month_val DECIMAL(14,2) NOT NULL,
            next_month_lower DECIMAL(14,2) NOT NULL,
            next_month_upper DECIMAL(14,2) NOT NULL,
            historical_avg_val DECIMAL(14,2) NOT NULL,
            validation_total_6m DECIMAL(14,2) NOT NULL,
            validation_period_label VARCHAR(100) NOT NULL,
            computed_at DATETIME NOT NULL,
            PRIMARY KEY (kpi_id)
        );
        """
    ]

    for q in tables_sql:
        run_query(q)

    print("[SUCCESS] Forecast results tables created successfully.")

if __name__ == "__main__":
    migrate_expenditure()
    create_forecast_tables()
