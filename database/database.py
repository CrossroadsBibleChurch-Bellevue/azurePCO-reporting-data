import os
import time
import struct
import pyodbc
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential

load_dotenv()


# This file is how the function connects to the database, just gets the appropriate server and database string from the environmental variables then connects and returns the connection
# Shouldn't need to change anything here when adding new endpoints since the loader already fetches it fine.


SQL_COPT_SS_ACCESS_TOKEN = 1256
TOKEN_SCOPE = "https://database.windows.net/.default"

credential = DefaultAzureCredential()

connection_string = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    f"SERVER={os.getenv('AZURE_SQL_SERVER')},1433;"
    f"DATABASE={os.getenv('AZURE_SQL_DATABASE')};"
    "Encrypt=yes;"
    "TrustServerCertificate=no;"
    "Connection Timeout=30;"
)


def get_access_token():
    token = credential.get_token(TOKEN_SCOPE).token
    token_bytes = token.encode("utf-16-le")
    token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)
    return token_struct


def get_connection(max_retries=5):
    for attempt in range(1, max_retries + 1):
        try:
            access_token = get_access_token()

            return pyodbc.connect(
                connection_string,
                attrs_before={
                    SQL_COPT_SS_ACCESS_TOKEN: access_token
                }
            )

        except pyodbc.Error:
            if attempt == max_retries:
                raise

            wait_seconds = attempt * 5
            print(f"Connection failed. Retrying in {wait_seconds} seconds...")
            time.sleep(wait_seconds)