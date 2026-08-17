from dotenv import load_dotenv
load_dotenv(override=True)

import os
import mysql.connector
import pandas as pd

def fetch_dataframe(query):
    """Runs a query and returns results as a pandas DataFrame, columns included."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(query)
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return pd.DataFrame(rows, columns=columns)

AIVEN_CONFIG = {
    "host": os.environ["AIVEN_MYSQL_HOST"],
    "port": int(os.environ["AIVEN_MYSQL_PORT"]),
    "user": os.environ["AIVEN_MYSQL_USER"],
    "password": os.environ["AIVEN_MYSQL_PASSWORD"],
    "database": os.environ["AIVEN_MYSQL_DATABASE"],
    "ssl_ca": os.environ["AIVEN_MYSQL_CA_PATH"],
    "ssl_verify_cert": True,
}

def get_connection():
    return mysql.connector.connect(**AIVEN_CONFIG)

def run_query(query, params=None, fetch=False):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(query, params or ())
    result = cursor.fetchall() if fetch else None
    conn.commit()
    cursor.close()
    conn.close()
    return result