from db_connection import run_query

def check_table(table_name, name_column, known_names):
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

    print("Known performers:")
    for name in known_names:
        result = run_query(
            f"SELECT {name_column}, lifetime_rank, trajectory, readiness_flag FROM {table_name} WHERE {name_column} = %s",
            params=(name,), fetch=True
        )
        print(f"  {result}")

    print("New/no-history entries (lifetime_rank IS NULL):")
    null_rows = run_query(
        f"SELECT {name_column}, readiness_flag FROM {table_name} WHERE lifetime_rank IS NULL",
        fetch=True
    )
    for row in null_rows:
        print(f"  {row}")

check_table('bd_readiness_calculated', 'bd_name', ['Komal Suresh Bhanushali', 'Rajalaxmi Das Das', 'Sammed Santosh Magdum'])
check_table('tl_readiness_calculated', 'tl_name', ['Surbhi Vinod Jain', 'Joyeeta Joydeb Khaskel'])