import pyodbc

from database.database import get_connection

def fetch_updated_at():
    conn = None

    try:
        conn = get_connection()

        sql = "SELECT RecordValue FROM dbo.records WHERE RecordType = 'PeopleDeltaRefresh'"

        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        return rows[0][0]

    finally:
        
        if conn is not None:
            conn.close()