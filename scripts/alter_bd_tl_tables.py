from db_connection import run_query

run_query("ALTER TABLE bd_readiness_calculated MODIFY lifetime_revenue DECIMAL(14,2) NULL")
run_query("ALTER TABLE bd_readiness_calculated MODIFY lifetime_rank INT NULL")
run_query("ALTER TABLE tl_readiness_calculated MODIFY lifetime_revenue DECIMAL(14,2) NULL")
run_query("ALTER TABLE tl_readiness_calculated MODIFY lifetime_rank INT NULL")
run_query("ALTER TABLE bd_readiness_calculated MODIFY trajectory VARCHAR(50) NULL")
run_query("ALTER TABLE tl_readiness_calculated MODIFY trajectory VARCHAR(50) NULL")
print("Tables updated: lifetime_revenue and lifetime_rank now nullable")