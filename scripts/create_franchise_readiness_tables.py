from db_connection import run_query

CREATE_NET = """
CREATE TABLE IF NOT EXISTS franchise_readiness_calculated_net (
    franchise_name VARCHAR(255) NOT NULL,
    lifetime_revenue DECIMAL(14,2) NOT NULL,
    lifetime_rank INT NOT NULL,
    recent_fy_revenue DECIMAL(14,2) NULL,
    recent_fy_rank INT NULL,
    recent_fy_status VARCHAR(50) NOT NULL,
    trajectory VARCHAR(50) NOT NULL,
    momentum VARCHAR(50) NOT NULL,
    readiness_flag VARCHAR(50) NOT NULL,
    computed_at DATETIME NOT NULL,
    PRIMARY KEY (franchise_name)
);
"""

CREATE_GROSS = """
CREATE TABLE IF NOT EXISTS franchise_readiness_calculated_gross (
    franchise_name VARCHAR(255) NOT NULL,
    lifetime_revenue DECIMAL(14,2) NOT NULL,
    lifetime_rank INT NOT NULL,
    recent_fy_revenue DECIMAL(14,2) NULL,
    recent_fy_rank INT NULL,
    recent_fy_status VARCHAR(50) NOT NULL,
    trajectory VARCHAR(50) NOT NULL,
    momentum VARCHAR(50) NOT NULL,
    readiness_flag VARCHAR(50) NOT NULL,
    computed_at DATETIME NOT NULL,
    PRIMARY KEY (franchise_name)
);
"""

run_query(CREATE_NET)
print("Created franchise_readiness_calculated_net")

run_query(CREATE_GROSS)
print("Created franchise_readiness_calculated_gross")