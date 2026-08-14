import pyodbc
from database.database import connection_string, get_access_token, SQL_COPT_SS_ACCESS_TOKEN

# Pretty simple file, just pings the server to wake it up if its asleep, if awake keeps it awake

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
    