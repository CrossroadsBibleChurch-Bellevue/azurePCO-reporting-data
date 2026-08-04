import re
import pyodbc
import time
import logging
from typing import Dict, Any
from datetime import datetime
from database.database import get_connection, connection_string, get_access_token, SQL_COPT_SS_ACCESS_TOKEN

def wake_up_server():
    try:
        access_token = get_access_token()

        pyodbc.connect(
            connection_string,
            attrs_before={
                SQL_COPT_SS_ACCESS_TOKEN: access_token
            }
        )
        print("Server awake")
    except pyodbc.Error:
        print("Waking server up")
    