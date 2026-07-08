import re
import pyodbc
import time
from typing import Dict, Any
from database.database import get_connection

def table_exists(table_name_raw: str, cursor, conn: pyodbc.Connection):
    table_name = f"PCO_GROUPS_{table_name_raw}"
    cursor.execute("""
        SELECT 1
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_NAME = ?
          AND TABLE_TYPE = 'BASE TABLE'
    """, table_name)

    return cursor.fetchone() is not None

def create_table(table_name_raw: str, cursor, conn: pyodbc.Connection):
    table_name = f"PCO_GROUPS_{table_name_raw}"

    sql = f"""
    CREATE TABLE dbo.{table_name}_STAGING
    (
        HashId NVARCHAR(200) NOT NULL PRIMARY KEY,
        GroupID INT NULL,
        EventID INT NULL,
        EventName NVARCHAR(200) NULL,
        StartsAt NVARCHAR(200) NULL,
        PersonID INT NULL,
        PersonName NVARCHAR(200) NULL,
        MembershipRole NVARCHAR(100) NULL,
        Attended BIT NULL,
        AttendanceRecordExists BIT NULL
    )

    CREATE TABLE dbo.{table_name}
    (
        HashId NVARCHAR(200) NOT NULL PRIMARY KEY,
        GroupID INT NULL,
        EventID INT NULL,
        EventName NVARCHAR(200) NULL,
        StartsAt NVARCHAR(200) NULL,
        PersonID INT NULL,
        PersonName NVARCHAR(200) NULL,
        MembershipRole NVARCHAR(100) NULL,
        Attended BIT NULL,
        AttendanceRecordExists BIT NULL
    )
    """
    cursor.execute(sql)
    conn.commit()
    time.sleep(0.1)
    if table_exists(table_name_raw, cursor, conn):
        print("Table exists now")

def table_prep(tables: Dict[str, Any]) -> None:
    conn = None

    try:
        conn = get_connection()
        cursor = conn.cursor()
        for table_name, records in tables.items():
            print(table_name)
            if table_name == "group_attendance":
                for value in records:
                    group_name = value.get("group_name")
                    group_name = re.sub(r"\s+", "_", group_name.strip())
                    print(group_name)
                    if table_exists(group_name, cursor, conn):
                        print("Table exists")
                        pass
                    else:
                        #print("Table does not exist, creating currently")
                        create_table(group_name, cursor, conn)
                    #print(type(value))
        

    finally:
        
        if conn is not None:
            conn.close()
    