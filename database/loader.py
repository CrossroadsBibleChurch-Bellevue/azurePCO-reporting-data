import time
from typing import Any, Dict, List
import sys
import re

import pyodbc

from database.database import get_connection
from database.table_configs import TABLE_CONFIGS
from database.sql_builders import (
    build_truncate_sql,
    build_staging_insert_sql,
    build_upsert_sql,
)


def normalize_records(records: Any) -> List[Dict[str, Any]]:
    if records is None:
        return []

    if isinstance(records, dict):
        return [records]

    if isinstance(records, (list, tuple)):
        if not all(isinstance(record, dict) for record in records):
            raise TypeError("All records must be dictionaries.")
        return list(records)

    raise TypeError("Records must be a dictionary or a list of dictionaries.")


def get_table_config(table_name: str) -> Dict[str, Any]:
    if table_name not in TABLE_CONFIGS:
        valid_tables = ", ".join(TABLE_CONFIGS.keys())
        raise KeyError(
            f"Unknown table config '{table_name}'. "
            f"Valid table names: {valid_tables}"
        )

    return TABLE_CONFIGS[table_name]


def validate_table_config(table_name: str, config: Dict[str, Any]) -> None:
    required_config_keys = [
        "target_table",
        "staging_table",
        "key_columns",
        "column_map",
    ]

    for key in required_config_keys:
        if key not in config:
            raise ValueError(f"Table config '{table_name}' is missing '{key}'.")

    if not config["key_columns"]:
        raise ValueError(f"Table config '{table_name}' must have at least one key column.")

    if not config["column_map"]:
        raise ValueError(f"Table config '{table_name}' must have at least one mapped column.")

    for key_column in config["key_columns"]:
        if key_column not in config["column_map"]:
            raise ValueError(
                f"Key column '{key_column}' for table '{table_name}' "
                f"is not present in column_map."
            )


def validate_records(
    table_name: str,
    records: List[Dict[str, Any]],
    config: Dict[str, Any],
) -> None:
    required_source_keys = set(config.get("required_source_keys", []))

    for key_column in config["key_columns"]:
        required_source_keys.add(config["column_map"][key_column])

    for index, record in enumerate(records):
        for source_key in required_source_keys:
            if source_key not in record:
                raise KeyError(
                    f"Missing required source key '{source_key}' "
                    f"in table '{table_name}', record index {index}."
                )

            if record[source_key] is None:
                raise ValueError(
                    f"Required source key '{source_key}' is None "
                    f"in table '{table_name}', record index {index}."
                )


def build_rows(
    records: List[Dict[str, Any]],
    column_map: Dict[str, str],
) -> List[tuple]:
    rows = []

    for record in records:
        row = tuple(
            record.get(source_key)
            for source_key in column_map.values()
        )
        rows.append(row)

    return rows


def load_staging(
    conn: pyodbc.Connection,
    table_name: str,
    records: List[Dict[str, Any]],
    config: Dict[str, Any],
    group_name: str,
) -> int:
    if table_name == "group_attendance":
        staging_table = f"dbo.PCO_GROUPS_{group_name}_STAGING"
    else:
        staging_table = config["staging_table"]
    column_map = config["column_map"]
    columns = list(column_map.keys())

    rows = build_rows(records, column_map)

    cursor = conn.cursor()

    cursor.execute(build_truncate_sql(staging_table))

    if not rows:
        return 0

    cursor.fast_executemany = True

    insert_sql = build_staging_insert_sql(
        staging_table=staging_table,
        columns=columns,
    )
    #print(insert_sql)

    #for i, value in enumerate(rows):
    #    for val in value:
    #        print(val, type(val))
    try:
        cursor.executemany(insert_sql, rows)
    except pyodbc.Error as e:
        print("Batch insert failed:")
        print(e)

        print("\nTesting rows one-by-one to find bad record...\n")

        for i, row in enumerate(rows):
            try:
                cursor.execute(insert_sql, row)
                #print(f"Row {i} successfully inserted")
            except pyodbc.Error as row_error:
                print(f"Bad row index: {i}")
                print(f"Bad row data: {row}")
                print(f"Error: {row_error}")

                # Optional: print string lengths for that row
                print("\nString field lengths:")
                for col_index, value in enumerate(row):
                    if isinstance(value, str):
                        print(f"  Column position {col_index}: length={len(value)}, value={value!r}")

                raise

    return len(rows)


def upsert_from_staging(
    conn: pyodbc.Connection,
    table_name: str,
    config: Dict[str, Any],
    group_name: str,
) -> None:
    if table_name == "group_attendance":
        target_table = f"dbo.PCO_GROUPS_{group_name}"
    else:
        target_table = config["target_table"]
    if table_name == "group_attendance":
        staging_table = f"dbo.PCO_GROUPS_{group_name}_STAGING"
    else:
        staging_table = config["staging_table"]
    columns = list(config["column_map"].keys())
    key_columns = config["key_columns"]

    sql = build_upsert_sql(
        target_table=target_table,
        staging_table=staging_table,
        columns=columns,
        key_columns=key_columns,
    )

    cursor = conn.cursor()
    cursor.execute(sql)

    cursor.execute(build_truncate_sql(staging_table))


def process_table(
    conn: pyodbc.Connection,
    table_name: str,
    raw_records: Any,
    group_name: str,
) -> None:
    start_time = time.perf_counter()

    config = get_table_config(table_name)
    validate_table_config(table_name, config)

    records = normalize_records(raw_records)
    validate_records(table_name, records, config)

    try:
        print(f"Processing table '{table_name}'...")

        loaded_count = load_staging(
            conn=conn,
            table_name=table_name,
            records=records,
            config=config,
            group_name=group_name,
        )

        upsert_from_staging(
            conn=conn,
            table_name=table_name,
            config=config,
            group_name=group_name,
        )

        conn.commit()

        elapsed = round(time.perf_counter() - start_time, 2)
        if table_name == "group_attendance":
            print(
                f"Finished table '{group_name}'. "
                f"Loaded {loaded_count}. "
                f"Elapsed: {elapsed} seconds."
            )
        else:
            print(
                f"Finished table '{table_name}'. "
                f"Loaded {loaded_count}. "
                f"Elapsed: {elapsed} seconds."
            )

    except Exception:
        conn.rollback()
        print(f"Rolled back table '{table_name}' due to an error.")
        raise

def update_delta_record(conn: pyodbc.Connection):
    sql = f"""
    BEGIN TRANSACTION;

    UPDATE dbo.records
    SET
        RecordValue = SYSUTCDATETIME(),
        LastUpdated = SYSUTCDATETIME()
    WHERE RecordType = ?;

    IF @@ROWCOUNT = 0
    BEGIN
        INSERT INTO dbo.records (
            RecordType,
            RecordValue,
            LastUpdated
        )
        VALUES (
            ?,
            SYSUTCDATETIME(),
            SYSUTCDATETIME()
        );
    END;

    COMMIT TRANSACTION;
    """

    cursor = conn.cursor()
    cursor.execute(sql,
                   "PeopleDeltaRefresh",
                   "PeopleDeltaRefresh")

    conn.commit()


def uploader(tables: Dict[str, Any]) -> None:
    if not isinstance(tables, dict):
        raise TypeError("tables must be a dictionary like {'people_core': records}.")

    conn = None
    group_name = None

    try:
        conn = get_connection()

        for table_name, records in tables.items():
            if table_name == "group_attendance":
                for value in records:
                    group_name = value.get("group_name")
                    group_name = re.sub(r"\s+", "_", group_name.strip())
                    group_records = value.get("rows")
                    process_table(
                        conn=conn,
                        table_name=table_name,
                        raw_records=group_records,
                        group_name=group_name
                    )
                #sys.exit(0)
            else:
                process_table(
                    conn=conn,
                    table_name=table_name,
                    raw_records=records,
                    group_name=group_name
                )
        
        update_delta_record(conn)

    finally:
        
        if conn is not None:
            conn.close()