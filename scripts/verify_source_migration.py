from db_connection import run_query

for table in ['invoice', 'franchisees_forms', 'enquiries']:
    result = run_query(f"SELECT COUNT(*) FROM {table}", fetch=True)
    print(f"{table}: {result[0][0]} rows")