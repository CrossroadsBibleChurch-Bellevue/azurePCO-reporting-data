import os
import time
import pyodbc
from dotenv import load_dotenv

load_dotenv()

connection_string = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={os.getenv('AZURE_SQL_SERVER')},1433;"
    f"DATABASE={os.getenv('AZURE_SQL_DATABASE')};"
    f"UID={os.getenv('AZURE_SQL_USERNAME')};"
    f"PWD={os.getenv('AZURE_SQL_PASSWORD')};"
    "Encrypt=yes;"
    "TrustServerCertificate=no;"
    "Connection Timeout=30;"
)


def get_connection(max_retries=5):
    for attempt in range(1, max_retries + 1):
        try:
            return pyodbc.connect(connection_string)
        except pyodbc.Error:
            if attempt == max_retries:
                raise

            wait_seconds = attempt * 5
            print(f"Connection failed. Retrying in {wait_seconds} seconds...")
            time.sleep(wait_seconds)