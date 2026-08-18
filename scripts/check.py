from db_connection import run_query

rows = run_query("""
    SELECT table_name, ROUND((data_length + index_length) / 1024 / 1024, 2) AS size_mb
    FROM information_schema.tables
    WHERE table_schema = 'defaultdb'
    ORDER BY size_mb DESC
""", fetch=True)
for name, size in rows:
    print(f"{name}: {size} MB")