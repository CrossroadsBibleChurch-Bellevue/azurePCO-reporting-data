import os
import time
import pyodbc
from dotenv import load_dotenv
from typing import Dict, Any

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


def upsert_people_from_staging(conn):
    sql = """
    UPDATE target
    SET
        target.BirthDate = source.BirthDate,
        target.Child = source.Child,
        target.CreatedAt = source.CreatedAt,
        target.CurrentStatus = source.CurrentStatus,
        target.FirstName = source.FirstName,
        target.FullName = source.FullName,
        target.Gender = source.Gender,
        target.GivenName = source.GivenName,
        target.Grade = source.Grade,
        target.GraduationYear = source.GraduationYear,
        target.InactivatedAt = source.InactivatedAt,
        target.InactiveReason = source.InactiveReason,
        target.LastName = source.LastName,
        target.MaritalStatus = source.MaritalStatus,
        target.MedicalNotes = source.MedicalNotes,
        target.Membership = source.Membership,
        target.MiddleName = source.MiddleName,
        target.NickName = source.NickName,
        target.PassedBackgroundCheck = source.PassedBackgroundCheck,
        target.UpdatedAt = source.UpdatedAt

    FROM dbo.PCO_People_Core target
    INNER JOIN dbo.PCO_People_Core_Staging source
        ON target.PlanningCenterId = source.PlanningCenterId;

    INSERT INTO dbo.PCO_People_Core (
        PlanningCenterId,
        BirthDate,
        Child,
        CreatedAt,
        CurrentStatus,
        FirstName,
        FullName,
        Gender,
        GivenName,
        Grade,
        GraduationYear,
        InactivatedAt,
        InactiveReason,
        LastName,
        MaritalStatus,
        MedicalNotes,
        Membership,
        MiddleName,
        NickName,
        PassedBackgroundCheck,
        UpdatedAt
    )
    SELECT
        source.PlanningCenterId,
        source.BirthDate,
        source.Child,
        source.CreatedAt,
        source.CurrentStatus,
        source.FirstName,
        source.FullName,
        source.Gender,
        source.GivenName,
        source.Grade,
        source.GraduationYear,
        source.InactivatedAt,
        source.InactiveReason,
        source.LastName,
        source.MaritalStatus,
        source.MedicalNotes,
        source.Membership,
        source.MiddleName,
        source.NickName,
        source.PassedBackgroundCheck,
        source.UpdatedAt
    FROM dbo.PCO_People_Core_Staging source
    LEFT JOIN dbo.PCO_People_Core target
        ON target.PlanningCenterId = source.PlanningCenterId
    WHERE target.PlanningCenterId IS NULL;
    """

    cursor = conn.cursor()
    cursor.execute(sql)
    conn.commit()
    print("Upserted into main table")


def load_people_staging(conn, people):
    cursor = conn.cursor()

    cursor.execute("TRUNCATE TABLE dbo.PCO_People_Core_Staging;")

    if isinstance(people, dict):
        people_rows = [people]
    elif isinstance(people, (list, tuple)):
        people_rows = list(people)
    else:
        raise TypeError("people must be a dictionary or a list of dictionaries")

    rows = [
        (
            p["person_id"],
            p["birthdate"],
            p["child"],
            p["created_at"],
            p["first_name"],
            p["gender"],
            p["given_name"],
            p["grade"],
            p["graduation_year"],
            p["inactivated_at"],
            p["inactive_reason"],
            p["last_name"],
            p["marital_status"],
            p["medical_notes"],
            p["membership"],
            p["middle_name"],
            p["name"],
            p["nickname"],
            p["passed_background_check"],
            p["status"],
            p["updated_at"]
        )
        for p in people_rows
    ]

    cursor.fast_executemany = True

    cursor.executemany("""
        INSERT INTO dbo.PCO_People_Core_Staging (
            PlanningCenterId,
            BirthDate,
            Child,
            CreatedAt,
            CurrentStatus,
            FirstName,
            FullName,
            Gender,
            GivenName,
            Grade,
            GraduationYear,
            InactivatedAt,
            InactiveReason,
            LastName,
            MaritalStatus,
            MedicalNotes,
            Membership,
            MiddleName,
            NickName,
            PassedBackgroundCheck,
            UpdatedAt
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, rows)

    conn.commit()
    print("Loaded people into staging table")


def uploader(tables: Dict[str, Any]):
    try:
        with get_connection() as conn:
            load_people_staging(conn, tables)
            upsert_people_from_staging(conn)
    finally:
        conn.close()


def main():
    tables = {}
    uploader(tables)
    

if __name__ == "__main__":
    main()