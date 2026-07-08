import re
import pyodbc
import time
import logging
from typing import Dict, Any
from datetime import datetime
from database.database import get_connection, connection_string

def wake_up_server():
    try:
        pyodbc.connect(connection_string)
        logging.info("Server awake")
    except pyodbc.Error:
        logging.info("Waking server up")

def table_exists_attendance(table_name_raw: str, cursor, conn: pyodbc.Connection):
    table_name = f"PCO_GROUPS_{table_name_raw}"
    cursor.execute("""
        SELECT 1
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_NAME = ?
          AND TABLE_TYPE = 'BASE TABLE'
    """, table_name)

    return cursor.fetchone() is not None

def table_exists_snapshot(table_name_raw: str, cursor, conn: pyodbc.Connection):
    table_name = f"PCO_GROUPS_{table_name_raw}_SNAPSHOT"
    cursor.execute("""
        SELECT 1
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_NAME = ?
          AND TABLE_TYPE = 'BASE TABLE'
    """, table_name)

    return cursor.fetchone() is not None

def create_table_attendance(table_name_raw: str, cursor, conn: pyodbc.Connection):
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

def create_table_snapshot(table_name_raw: str, cursor, conn: pyodbc.Connection):
    table_name = f"PCO_GROUPS_{table_name_raw}"

    sql = f"""
    CREATE TABLE dbo.{table_name}_SNAPSHOT_STAGING
    (
        HashId NVARCHAR(200) NOT NULL PRIMARY KEY,
        GroupID INT NULL,
        GroupName NVARCHAR(100) NULL,
        MembershipID INT NULL,
        PersonID INT NULL,
        MemberName NVARCHAR(100) NULL,
        GroupRole NVARCHAR(100) NULL,
        JoinedAt NVARCHAR(200) NULL
    )

    CREATE TABLE dbo.{table_name}_SNAPSHOT
    (
        HashId NVARCHAR(200) NOT NULL PRIMARY KEY,
        GroupID INT NULL,
        GroupName NVARCHAR(100) NULL,
        MembershipID INT NULL,
        PersonID INT NULL,
        MemberName NVARCHAR(100) NULL,
        GroupRole NVARCHAR(100) NULL,
        JoinedAt NVARCHAR(200) NULL
    )
    """
    cursor.execute(sql)
    conn.commit()
    time.sleep(0.1)

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
                    group_name = re.sub(r'[^A-Za-z0-9_]+', '', group_name.strip())
                    if table_exists_attendance(group_name, cursor, conn):
                        pass
                    else:
                        create_table_attendance(group_name, cursor, conn)
            elif table_name == "group_snapshot":
                month = datetime.now().strftime("%B")
                year = datetime.now().year
                snapshot = f"{month}_{year}"
                if table_exists_snapshot(table_name_raw=snapshot, cursor=cursor, conn=conn):
                        pass
                else:
                    create_table_snapshot(table_name_raw=snapshot, cursor=cursor, conn=conn)
        

    finally:
        
        if conn is not None:
            conn.close()
    