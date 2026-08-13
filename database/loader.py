import time
from typing import Any, Dict, List, Optional,  Tuple
from datetime import datetime, timezone
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


def log_fast_executemany_environment(
    conn: pyodbc.Connection,
    table_name: str,
    config: Dict[str, Any],
) -> None:
    try:
        driver_name = conn.getinfo(pyodbc.SQL_DRIVER_NAME)
    except Exception as error:
        driver_name = f"<unavailable: {error}>"

    try:
        driver_version = conn.getinfo(pyodbc.SQL_DRIVER_VER)
    except Exception as error:
        driver_version = f"<unavailable: {error}>"

    try:
        dbms_name = conn.getinfo(pyodbc.SQL_DBMS_NAME)
    except Exception as error:
        dbms_name = f"<unavailable: {error}>"

    try:
        dbms_version = conn.getinfo(pyodbc.SQL_DBMS_VER)
    except Exception as error:
        dbms_version = f"<unavailable: {error}>"

    logging.error(
        "FAST_EXECUTEMANY ENVIRONMENT | "
        "Table=%s | pyodbc=%s | Driver=%s | DriverVersion=%s | "
        "DBMS=%s | DBMSVersion=%s | fast_executemany=%s | "
        "batch_size=%s",
        table_name,
        pyodbc.version,
        driver_name,
        driver_version,
        dbms_name,
        dbms_version,
        config.get("fast_executemany", True),
        config.get("batch_size", 5000),
    )

    logging.error(
        "COLUMN MAP ORDER | Table=%s | ColumnCount=%d | Columns=%r",
        table_name,
        len(config["column_map"]),
        list(config["column_map"].items()),
    )

    logging.error(
        "CONFIGURED INPUT SIZES | Table=%s | InputSizes=%r",
        table_name,
        config.get("input_sizes"),
    )



def validate_input_sizes(
    table_name: str,
    columns: List[str],
    input_sizes: Any,
) -> None:
    if input_sizes is None:
        return

    if not isinstance(input_sizes, (list, tuple)):
        raise TypeError(
            f"input_sizes for table '{table_name}' must be a list or tuple."
        )

    if len(input_sizes) != len(columns):
        raise ValueError(
            f"input_sizes for table '{table_name}' has "
            f"{len(input_sizes)} entries, but the INSERT contains "
            f"{len(columns)} columns.\n"
            f"Columns: {columns!r}\n"
            f"Input sizes: {input_sizes!r}"
        )

    for position, (column, input_size) in enumerate(
        zip(columns, input_sizes)
    ):
        logging.info(
            "INPUT SIZE POSITION | Table=%s | Position=%d | "
            "Column=%s | InputSize=%r",
            table_name,
            position,
            column,
            input_size,
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

NULL_STRINGS = {
    "",
    "none",
    "null",
    "nan",
    "n/a",
    "undefined",
}


def normalize_optional_datetime(value: Any):
    if value is None:
        return None

    if isinstance(value, datetime):
        parsed_value = value

    elif isinstance(value, str):
        cleaned_value = value.strip()

        if cleaned_value.lower() in NULL_STRINGS:
            return None

        try:
            parsed_value = datetime.fromisoformat(
                cleaned_value.replace("Z", "+00:00")
            )

        except ValueError as error:
            raise ValueError(
                f"Invalid datetime value: {value!r}"
            ) from error

    else:
        raise TypeError(
            f"Expected datetime, string, or None, but received "
            f"{type(value).__name__}: {value!r}"
        )

    # SQL Server datetime/datetime2 does not preserve timezone information.
    # Convert aware values to naive UTC before uploading.
    if parsed_value.tzinfo is not None:
        parsed_value = (
            parsed_value
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )

    return parsed_value

def build_rows(
    records: List[Dict[str, Any]],
    column_map: Dict[str, str],
    converters: Optional[Dict[str, Any]] = None,
) -> List[Tuple[Any, ...]]:
    converters = converters or {}
    rows: List[Tuple[Any, ...]] = []

    for record_index, record in enumerate(records):
        row_values = []

        for sql_column, source_key in column_map.items():
            value = record.get(source_key)
            converter = converters.get(sql_column)

            if converter is not None:
                try:
                    value = converter(value)

                except (TypeError, ValueError, OverflowError) as error:
                    raise ValueError(
                        f"Failed to convert value while building SQL row | "
                        f"RecordIndex={record_index} | "
                        f"SQLColumn={sql_column} | "
                        f"SourceKey={source_key} | "
                        f"PythonType={type(value).__name__} | "
                        f"Value={value!r}"
                    ) from error

            row_values.append(value)

        rows.append(tuple(row_values))

    return rows


def chunk_rows(rows: List[tuple], chunk_size: int):
    for start in range(0, len(rows), chunk_size):
        yield rows[start:start + chunk_size]


def log_failed_batch_profile(
    table_name: str,
    columns: List[str],
    source_keys: List[str],
    batch: List[Tuple[Any, ...]],
    batch_start_index: int,
) -> None:
    logging.error("=" * 100)
    logging.error(
        "FAILED FAST_EXECUTEMANY BATCH PROFILE | "
        "Table=%s | BatchSize=%d | DatasetStartIndex=%d",
        table_name,
        len(batch),
        batch_start_index,
    )

    suspicious_strings = {
        "",
        "none",
        "null",
        "nan",
        "n/a",
        "undefined",
    }

    for position, (sql_column, source_key) in enumerate(
        zip(columns, source_keys)
    ):
        type_counts: Dict[str, int] = {}
        type_examples: Dict[str, List[Tuple[int, Any]]] = {}

        null_count = 0
        empty_string_count = 0
        placeholder_string_count = 0

        min_length: Optional[int] = None
        max_length: Optional[int] = None
        max_length_dataset_index: Optional[int] = None

        first_value = batch[0][position]
        first_non_null_value = None
        first_non_null_dataset_index = None

        for batch_row_index, row in enumerate(batch):
            dataset_row_index = batch_start_index + batch_row_index
            value = row[position]

            if value is None:
                null_count += 1
                continue

            if first_non_null_value is None:
                first_non_null_value = value
                first_non_null_dataset_index = dataset_row_index

            type_name = type(value).__name__
            type_counts[type_name] = type_counts.get(type_name, 0) + 1

            type_examples.setdefault(type_name, [])

            if len(type_examples[type_name]) < 5:
                type_examples[type_name].append(
                    (dataset_row_index, value)
                )

            if isinstance(value, str):
                normalized = value.strip().lower()

                if value == "":
                    empty_string_count += 1

                if normalized in suspicious_strings:
                    placeholder_string_count += 1

                value_length = len(value)

                if min_length is None or value_length < min_length:
                    min_length = value_length

                if max_length is None or value_length > max_length:
                    max_length = value_length
                    max_length_dataset_index = dataset_row_index

            elif isinstance(value, (bytes, bytearray)):
                value_length = len(value)

                if min_length is None or value_length < min_length:
                    min_length = value_length

                if max_length is None or value_length > max_length:
                    max_length = value_length
                    max_length_dataset_index = dataset_row_index

        logging.error(
            "COLUMN PROFILE | Position=%d | SQLColumn=%s | "
            "SourceKey=%s | NullCount=%d | PythonTypes=%r | "
            "EmptyStrings=%d | PlaceholderStrings=%d | "
            "MinLength=%s | MaxLength=%s | "
            "MaxLengthDatasetIndex=%s",
            position,
            sql_column,
            source_key,
            null_count,
            type_counts,
            empty_string_count,
            placeholder_string_count,
            min_length,
            max_length,
            max_length_dataset_index,
        )

        logging.error(
            "COLUMN FIRST VALUE | Position=%d | SQLColumn=%s | "
            "FirstValueType=%s | FirstValue=%r | "
            "FirstNonNullType=%s | FirstNonNullValue=%r | "
            "FirstNonNullDatasetIndex=%s",
            position,
            sql_column,
            type(first_value).__name__,
            first_value,
            (
                type(first_non_null_value).__name__
                if first_non_null_value is not None
                else None
            ),
            first_non_null_value,
            first_non_null_dataset_index,
        )

        logging.error(
            "COLUMN TYPE EXAMPLES | Position=%d | SQLColumn=%s | "
            "Examples=%r",
            position,
            sql_column,
            type_examples,
        )

        if len(type_counts) > 1:
            logging.error(
                "LIKELY PROBLEM: MIXED NON-NULL PYTHON TYPES | "
                "Position=%d | SQLColumn=%s | Types=%r",
                position,
                sql_column,
                type_counts,
            )

        if placeholder_string_count > 0:
            logging.error(
                "LIKELY PROBLEM: PLACEHOLDER STRING VALUES | "
                "Position=%d | SQLColumn=%s | Count=%d",
                position,
                sql_column,
                placeholder_string_count,
            )

    logging.error("=" * 100)

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
    source_keys = list(column_map.values())
    rows = build_rows(
        records=records,
        column_map=column_map,
        converters=config.get("converters"),
    )

    insert_sql = build_staging_insert_sql(
        staging_table=staging_table,
        columns=columns,
    )

    cursor = conn.cursor()

    failed_batch: Optional[List[Tuple[Any, ...]]] = None
    failed_batch_number: Optional[int] = None
    failed_batch_start_index: Optional[int] = None


    try:
        cursor.execute(build_truncate_sql(staging_table))

        if not rows:
            return 0

        cursor.fast_executemany = config.get("fast_executemany", True)

        input_sizes = config.get("input_sizes")

        if input_sizes is not None:
            cursor.setinputsizes(input_sizes)

        batch_size = 10000

        for batch_number, batch in enumerate(
            chunk_rows(rows, chunk_size=batch_size),
            start=1,
        ):
            batch_start_index = (batch_number - 1) * batch_size

            try:
                cursor.executemany(insert_sql, batch)

            except pyodbc.Error:
                failed_batch = batch
                failed_batch_number = batch_number
                failed_batch_start_index = batch_start_index

                log_failed_batch_profile(
                    table_name=table_name,
                    columns=columns,
                    source_keys=source_keys,
                    batch=batch,
                    batch_start_index=batch_start_index,
                )

                raise
        

        #cursor.executemany(insert_sql, rows)

        return len(rows)

    except pyodbc.Error as batch_error:
        logging.exception(
            "Batch insert failed | LogicalTable=%s | "
            "StagingTable=%s | TotalRecordCount=%d | "
            "FailedBatch=%s | FailedBatchSize=%s | "
            "FailedBatchStartIndex=%s",
            table_name,
            staging_table,
            len(rows),
            failed_batch_number,
            len(failed_batch) if failed_batch is not None else None,
            failed_batch_start_index,
        )

        for argument_index, argument in enumerate(batch_error.args):
            logging.error(
                "Batch pyodbc argument %d: %r",
                argument_index,
                argument,
            )

        logging.error("Generated insert SQL:\n%s", insert_sql)

        conn.rollback()

        raise RuntimeError(
            f"fast_executemany failed for logical table '{table_name}', "
            f"staging table '{staging_table}', batch "
            f"{failed_batch_number}, starting at dataset index "
            f"{failed_batch_start_index}. Review the preceding "
            f"COLUMN PROFILE entries."
        ) from batch_error

    finally:
        cursor.close()


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

def update_delta_record(conn: pyodbc.Connection, endpoint):
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

    if endpoint == "people":
        cursor.execute(sql,
                    "PeopleDeltaRefresh",
                    "PeopleDeltaRefresh")
    elif endpoint == "check_ins":
        cursor.execute(sql,
                    "CheckInsDeltaRefresh",
                    "CheckInsDeltaRefresh")

    conn.commit()


def uploader(tables: Dict[str, Any], endpoint) -> None:
    if not isinstance(tables, dict):
        raise TypeError("tables must be a dictionary like {'people_core': records}.")

    conn = None
    group_name = None

    try:
        conn = get_connection()

        for table_name in list(tables):
            rows = tables.pop(table_name)

            try:
                process_table(
                    conn=conn,
                    table_name=table_name,
                    raw_records=rows,
                    group_name=group_name
                )
            finally:
                rows.clear()
                del rows

        update_delta_record(conn, endpoint)

    finally:
        
        if conn is not None:
            conn.close()