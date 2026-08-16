from db_connection import run_query

tables = run_query("SHOW TABLES;", fetch=True)
print("Tables in defaultdb:")
for t in tables:
    print(" -", t[0])