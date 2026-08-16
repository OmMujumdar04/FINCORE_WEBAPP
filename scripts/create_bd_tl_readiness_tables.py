from db_connection import run_query

CREATE_BD = """
CREATE TABLE IF NOT EXISTS bd_readiness_calculated (
    bd_name VARCHAR(255) NOT NULL,
    trajectory VARCHAR(50) NOT NULL,
    yoy_growth_rates VARCHAR(255) NULL,
    momentum_status VARCHAR(50) NULL,
    revenue_change_pct DECIMAL(10,4) NULL,
    lifetime_revenue DECIMAL(14,2) NOT NULL,
    lifetime_rank INT NOT NULL,
    recent_fy_revenue DECIMAL(14,2) NULL,
    recent_fy_rank INT NULL,
    recent_fy_status VARCHAR(50) NOT NULL,
    readiness_flag VARCHAR(50) NOT NULL,
    computed_at DATETIME NOT NULL,
    PRIMARY KEY (bd_name)
);
"""

CREATE_TL = """
CREATE TABLE IF NOT EXISTS tl_readiness_calculated (
    tl_name VARCHAR(255) NOT NULL,
    trajectory VARCHAR(50) NOT NULL,
    yoy_growth_rates VARCHAR(255) NULL,
    momentum_status VARCHAR(50) NULL,
    revenue_change_pct DECIMAL(10,4) NULL,
    lifetime_revenue DECIMAL(14,2) NOT NULL,
    lifetime_rank INT NOT NULL,
    recent_fy_revenue DECIMAL(14,2) NULL,
    recent_fy_rank INT NULL,
    recent_fy_status VARCHAR(50) NOT NULL,
    readiness_flag VARCHAR(50) NOT NULL,
    computed_at DATETIME NOT NULL,
    PRIMARY KEY (tl_name)
);
"""

run_query(CREATE_BD)
print("Created bd_readiness_calculated")

run_query(CREATE_TL)
print("Created tl_readiness_calculated")