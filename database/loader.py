import time
from typing import Any, Dict, List
import sys
import logging
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

    try:
        cursor.executemany(insert_sql, rows)
    except pyodbc.Error:
        logging.exception(
            "Batch insert failed for table '%s' using staging table '%s'.",
            table_name,
            staging_table,
        )

        # Remove any rows that may have been partially inserted by executemany().
        conn.rollback()

        diagnostic_cursor = conn.cursor()
        diagnostic_cursor.execute(build_truncate_sql(staging_table))

        source_keys = list(column_map.values())

        logging.info("Testing rows individually to locate the bad value...")

        for row_index, row in enumerate(rows):
            try:
                diagnostic_cursor.execute(insert_sql, row)

            except pyodbc.Error as row_error:
                logging.error("=" * 80)
                logging.error("INSERT FAILURE DETAILS")
                logging.error("Logical table name: %s", table_name)
                logging.error("SQL staging table: %s", staging_table)
                logging.error("Record index: %d", row_index)
                logging.error("SQL error: %s", row_error)
                logging.error("=" * 80)

                original_record = records[row_index]

                logging.error("Values in the failing row:")

                for position, (sql_column, source_key, value) in enumerate(
                    zip(columns, source_keys, row)
                ):
                    logging.error(
                        "Position=%d | SQL column=%s | Source variable=%s | "
                        "Python type=%s | Value=%r",
                        position,
                        sql_column,
                        source_key,
                        type(value).__name__,
                        value,
                    )

                logging.error("Original source record: %r", original_record)

                # Specifically flag values that look suspicious for bigint columns.
                logging.error("Potential invalid integer values:")

                suspicious_value_found = False

                for sql_column, source_key, value in zip(
                    columns,
                    source_keys,
                    row,
                ):
                    if value is None:
                        continue

                    # Empty strings and non-numeric strings commonly cause:
                    # "Error converting data type nvarchar to bigint."
                    if isinstance(value, str):
                        stripped_value = value.strip()

                        if stripped_value == "":
                            suspicious_value_found = True
                            logging.error(
                                "SQL column=%s | Source variable=%s | "
                                "Value is an empty string",
                                sql_column,
                                source_key,
                            )
                        else:
                            try:
                                int(stripped_value)
                            except ValueError:
                                suspicious_value_found = True
                                logging.error(
                                    "SQL column=%s | Source variable=%s | "
                                    "Value cannot be converted to an integer: %r",
                                    sql_column,
                                    source_key,
                                    value,
                                )

                if not suspicious_value_found:
                    logging.error(
                        "No obvious invalid integer string was found. "
                        "Compare the logged values against the SQL staging "
                        "table data types."
                    )

                raise RuntimeError(
                    f"Failed loading logical table '{table_name}', "
                    f"staging table '{staging_table}', "
                    f"record index {row_index}. "
                    f"See the preceding log entries for the SQL column, "
                    f"source variable, type, and value."
                ) from row_error

    return len(rows)


def upsert_from_staging(
    conn: pyodbc.Connection,
    table_name: str,
    config: Dict[str, Any],
    group_name: str,
) -> None:
    target_table = config["target_table"]
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

    try:
        cursor.execute(sql)
        cursor.execute(build_truncate_sql(staging_table))

    except pyodbc.Error as error:
        logging.exception(
            "UPSERT FAILED | LogicalTable=%s | TargetTable=%s | "
            "StagingTable=%s | KeyColumns=%s",
            table_name,
            target_table,
            staging_table,
            key_columns,
        )

        for argument_index, argument in enumerate(error.args):
            logging.error(
                "pyodbc error argument %d: %r",
                argument_index,
                argument,
            )

        logging.error("Generated upsert SQL:\n%s", sql)

        raise

def stored_proc(conn: pyodbc.Connection):
    cursor = conn.cursor()

    cursor.execute("EXEC dbo.SyncGroupMemberships;")

    conn.commit()


def process_table(
    conn: pyodbc.Connection,
    table_name: str,
    raw_records: Any,
    group_name: str,
) -> None:
    start_time = time.perf_counter()
    phase = "initialization"

    try:
        phase = "loading table configuration"
        config = get_table_config(table_name)
        validate_table_config(table_name, config)

        phase = "normalizing records"
        records = normalize_records(raw_records)

        phase = "validating records"
        validate_records(table_name, records, config)

        logging.info(
            "Processing table '%s' with %d records...",
            table_name,
            len(records),
        )

        phase = "loading staging table"
        loaded_count = load_staging(
            conn=conn,
            table_name=table_name,
            records=records,
            config=config,
            group_name=group_name,
        )

        phase = "upserting staging data into target table"
        if table_name == "group_members_history":
            stored_proc(conn=conn)
        else:
            upsert_from_staging(
                conn=conn,
                table_name=table_name,
                config=config,
                group_name=group_name,
            )

        phase = "committing transaction"
        conn.commit()

        elapsed = time.perf_counter() - start_time

        logging.info(
            "Finished table '%s'. Loaded %d records. Elapsed: %.2f seconds.",
            table_name,
            loaded_count,
            elapsed,
        )

    except Exception as error:
        elapsed = time.perf_counter() - start_time

        # logging.exception automatically includes the complete traceback.
        logging.exception(
            "TABLE PROCESSING FAILED | "
            "Table=%s | Phase=%s | ExceptionType=%s | "
            "ExceptionMessage=%s | Elapsed=%.2f seconds",
            table_name,
            phase,
            type(error).__name__,
            str(error),
            elapsed,
        )

        # pyodbc exceptions often contain SQLSTATE and native SQL Server details.
        if isinstance(error, pyodbc.Error):
            logging.error("pyodbc diagnostic arguments:")

            for argument_index, argument in enumerate(error.args):
                logging.error(
                    "pyodbc error argument %d: %r",
                    argument_index,
                    argument,
                )

        try:
            conn.rollback()
        except Exception:
            logging.exception(
                "ROLLBACK FAILED | Table=%s | OriginalPhase=%s",
                table_name,
                phase,
            )
        else:
            logging.error(
                "Rolled back table '%s' because an error occurred "
                "during phase '%s'.",
                table_name,
                phase,
            )

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


def uploader(tables: Dict[str, Any], endpoint) -> None:
    if not isinstance(tables, dict):
        raise TypeError("tables must be a dictionary like {'people_core': records}.")

    conn = None
    group_name = None

    try:
        conn = get_connection()

        for table_name, records in tables.items():
            process_table(
                conn=conn,
                table_name=table_name,
                raw_records=records,
                group_name=group_name
            )

        if endpoint == "people":
            update_delta_record(conn)

    finally:
        
        if conn is not None:
            conn.close()