import pyodbc
import os
from typing import List, Optional
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from database import get_connection

load_dotenv()


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

conn = get_connection()
conn.autocommit = False

def drop_tables_with_prefix(
    conn: pyodbc.Connection,
    prefix: str = "PCO_GROUPS_",
    schema: Optional[str] = "dbo",
    dry_run: bool = True,
) -> List[str]:
    """
    Drop all SQL server names start with the given prefix.

    Args:
        conn: Existing pyodbc SQL Server connection.
        prefix: Table name prefix to match.
        schema: Schema to limit drops to. Use None to search all schemas.
        dry_run: If True, only returns DROP statements without executing them.

    Returns:
        List of DROP TABLE statements generated.
    """

    def quote_sql_identifier(name: str) -> str:
        return "[" + name.replace("]", "]]") + "]"

    cursor = conn.cursor()

    if schema is None:
        cursor.execute(
            """
            SELECT 
                s.name AS schema_name,
                t.name AS table_name
            FROM sys.tables t
            INNER JOIN sys.schemas s
                ON t.schema_id = s.schema_id
            WHERE LEFT(t.name, LEN(?)) = ?
            ORDER BY s.name, t.name;
            """,
            prefix,
            prefix,
        )
    else:
        cursor.execute(
            """
            SELECT 
                s.name AS schema_name,
                t.name AS table_name
            FROM sys.tables t
            INNER JOIN sys.schemas s
                ON t.schema_id = s.schema_id
            WHERE s.name = ?
              AND LEFT(t.name, LEN(?)) = ?
            ORDER BY s.name, t.name;
            """,
            schema,
            prefix,
            prefix,
        )

    rows = cursor.fetchall()

    drop_statements = []

    for row in rows:
        schema_name = row[0]
        table_name = row[1]

        statement = (
            f"DROP TABLE "
            f"{quote_sql_identifier(schema_name)}.{quote_sql_identifier(table_name)};"
        )

        drop_statements.append(statement)

    if dry_run:
        return drop_statements

    try:
        for statement in drop_statements:
            cursor.execute(statement)

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    return drop_statements



try:
    # Preview first
    statements = drop_tables_with_prefix(
        conn=conn,
        prefix="PCO_GROUPS_",
        schema="dbo",
        dry_run=True,
    )

    print("Tables that would be dropped:")
    for stmt in statements:
        print(stmt)

    # Actually drop them
    dropped = drop_tables_with_prefix(
        conn=conn,
        prefix="PCO_GROUPS_",
        schema="dbo",
        dry_run=False,
    )

    print("Dropped tables:")
    for stmt in dropped:
        print(stmt)

finally:
    conn.close()