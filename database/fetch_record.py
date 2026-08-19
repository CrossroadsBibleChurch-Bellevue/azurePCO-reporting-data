from database.database import get_connection


# This is the file that fetches the delta records for use in delta refresh.
# When adding future endpoints that are a delta refresh, just add a record into the SQL records table, then make sure in loader there is a query to update the record in the SQL and add a function here to get it from SQL for the extractor.


def fetch_updated_at_people():
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

def fetch_updated_at_checkins():
    conn = None

    try:
        conn = get_connection()

        sql = "SELECT RecordValue FROM dbo.records WHERE RecordType = 'CheckInsDeltaRefresh'"

        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        return rows[0][0]

    finally:
        
        if conn is not None:
            conn.close()

def fetch_instances(function_call) -> list:
    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute("""
            SELECT EventInstanceID
            FROM dbo.PCO_Groups_Event_Instances
            WHERE EventInstanceID IS NOT NULL;
        """)
        event_instance_ids = [row.EventInstanceID for row in cursor.fetchall()]
        length = len(event_instance_ids)//2
        if function_call == "first_call":
            event_instance_ids = event_instance_ids[:length]
            return event_instance_ids
        else:
            event_instance_ids = event_instance_ids[length:]
            return event_instance_ids
            

    finally:
        connection.close()