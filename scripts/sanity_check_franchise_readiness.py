from db_connection import run_query

def check_table(table_name, known_names):
    print(f"\n--- {table_name} ---")

    total = run_query(f"SELECT COUNT(*) FROM {table_name}", fetch=True)
    print(f"Total rows: {total[0][0]}")

    flag_counts = run_query(
        f"SELECT readiness_flag, COUNT(*) FROM {table_name} GROUP BY readiness_flag ORDER BY COUNT(*) DESC",
        fetch=True
    )
    print("readiness_flag distribution:")
    for flag, count in flag_counts:
        print(f"  {flag}: {count}")

    print("Known top performers:")
    for name in known_names:
        result = run_query(
            f"SELECT franchise_name, lifetime_rank, readiness_flag, computed_at FROM {table_name} WHERE franchise_name = %s",
            params=(name,), fetch=True
        )
        print(f"  {result}")

known_top = ['Aastha Kakkar', 'Sitalaxmi Shrivas And Kalpana Joshi', 'Pooja Acharya']

check_table('franchise_readiness_calculated_net', known_top)
check_table('franchise_readiness_calculated_gross', known_top)