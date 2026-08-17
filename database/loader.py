import time
from typing import Any, Dict, List, Optional,  Tuple
from datetime import datetime, timezone
import logging

import pyodbc

from database.database import get_connection
from database.table_configs import TABLE_CONFIGS
from database.sql_builders import (
    build_truncate_sql,
    build_staging_insert_sql,
    build_upsert_sql,
)

# This the loading file, which will do the actual upserting into the database. Currently there is a decent amount of debugger functions that is helpful to have in determining why a table won't be upserted.
# This file takes in the data to upload, inserts into the staging table, then upserts from staging into the actual table, so that SQL does the upserting process.
# The SQL queries are created by calling another file, sql_builders, and then getting the query back and using it.
# After the data is finished being uploaded, then the delta records are updated for people and check_ins, since those are the ones that need it.
# When adding a new endpoint delta refresh, make sure to go into update_delta_record and follow the structure there
# Registrations doesn't have a delta refresh process because the API makes it too difficult to do, and groups the easiest way is to just go back 5 events each time.
# When adding a new endpoint, changes shouldn't be needed in this file, as long as the tables being passed in are in a dictionary, then it should work fine. 


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

    if isinstance(records, list):
        if not all(isinstance(record, dict) for record in records):
            raise TypeError("All records must be dictionaries.")

        return records

    if isinstance(records, tuple):
        if not all(isinstance(record, dict) for record in records):
            raise TypeError("All records must be dictionaries.")

        return list(records)

    raise TypeError(
        "Records must be a dictionary, list of dictionaries, "
        "or tuple of dictionaries."
    )

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


def build_record_batch_rows(
    records: List[Dict[str, Any]],
    column_map: Dict[str, str],
    converters: Optional[Dict[str, Any]] = None,
    dataset_start_index: int = 0,
) -> List[Tuple[Any, ...]]:
    converters = converters or {}
    rows: List[Tuple[Any, ...]] = []

    for batch_record_index, record in enumerate(records):
        dataset_record_index = (
            dataset_start_index + batch_record_index
        )

        row_values: List[Any] = []

        for sql_column, source_key in column_map.items():
            value = record.get(source_key)
            converter = converters.get(sql_column)

            if converter is not None:
                try:
                    value = converter(value)

                except (
                    TypeError,
                    ValueError,
                    OverflowError,
                ) as error:
                    raise ValueError(
                        "Failed to convert value while building SQL row | "
                        f"RecordIndex={dataset_record_index} | "
                        f"SQLColumn={sql_column} | "
                        f"SourceKey={source_key} | "
                        f"PythonType={type(value).__name__} | "
                        f"Value={value!r}"
                    ) from error

            row_values.append(value)

        rows.append(tuple(row_values))

    return rows


def iter_table_chunks(
    table_name: str,
    records: Any,
    batch_size: int = 5000,
):
    normalized_records = normalize_records(records)

    for start in range(0, len(normalized_records), batch_size):
        yield {table_name: normalized_records[start:start + batch_size]}


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
    truncate_staging: bool = True,
) -> int:
    staging_table = config["staging_table"]
    column_map = config["column_map"]

    columns = list(column_map.keys())
    source_keys = list(column_map.values())

    insert_sql = build_staging_insert_sql(
        staging_table=staging_table,
        columns=columns,
    )

    cursor = conn.cursor()

    failed_batch: Optional[List[Tuple[Any, ...]]] = None
    failed_batch_number: Optional[int] = None
    failed_batch_start_index: Optional[int] = None

    loaded_count = 0

    try:
        if truncate_staging:
            cursor.execute(build_truncate_sql(staging_table))

        if not records:
            return 0

        cursor.fast_executemany = config.get(
            "fast_executemany",
            True,
        )

        input_sizes = config.get("input_sizes")

        validate_input_sizes(
            table_name=table_name,
            columns=columns,
            input_sizes=input_sizes,
        )

        if input_sizes is not None:
            cursor.setinputsizes(input_sizes)

        database_batch_size = config.get(
            "batch_size",
            1000,
        )

        if database_batch_size <= 0:
            raise ValueError(
                f"batch_size for table '{table_name}' "
                "must be greater than zero."
            )

        for batch_number, batch_start_index in enumerate(
            range(0, len(records), database_batch_size),
            start=1,
        ):
            record_batch = records[
                batch_start_index:
                batch_start_index + database_batch_size
            ]

            batch = build_record_batch_rows(
                records=record_batch,
                column_map=column_map,
                converters=config.get("converters"),
                dataset_start_index=batch_start_index,
            )

            try:
                cursor.executemany(
                    insert_sql,
                    batch,
                )

                loaded_count += len(batch)

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

            finally:
                batch.clear()
                record_batch.clear()

        return loaded_count

    except pyodbc.Error as batch_error:
        logging.exception(
            "Batch insert failed | LogicalTable=%s | "
            "StagingTable=%s | TotalRecordCount=%d | "
            "FailedBatch=%s | FailedBatchSize=%s | "
            "FailedBatchStartIndex=%s",
            table_name,
            staging_table,
            len(records),
            failed_batch_number,
            (
                len(failed_batch)
                if failed_batch is not None
                else None
            ),
            failed_batch_start_index,
        )

        for argument_index, argument in enumerate(
            batch_error.args
        ):
            logging.error(
                "Batch pyodbc argument %d: %r",
                argument_index,
                argument,
            )

        logging.error(
            "Generated insert SQL:\n%s",
            insert_sql,
        )

        conn.rollback()

        raise RuntimeError(
            f"fast_executemany failed for logical table "
            f"'{table_name}', staging table '{staging_table}', "
            f"batch {failed_batch_number}, starting at dataset "
            f"index {failed_batch_start_index}. Review the "
            f"preceding COLUMN PROFILE entries."
        ) from batch_error

    finally:
        cursor.close()


def stage_group_members_history_chunk(
    conn: pyodbc.Connection,
    records: List[Dict[str, Any]],
) -> int:
    table_name = "group_members_history"

    config = get_table_config(table_name)
    validate_table_config(table_name, config)

    normalized_records = normalize_records(records)
    validate_records(
        table_name=table_name,
        records=normalized_records,
        config=config,
    )

    if not normalized_records:
        return 0

    loaded_count = load_staging(
        conn=conn,
        table_name=table_name,
        records=normalized_records,
        config=config,
        group_name=None,
        truncate_staging=False,
    )

    # Commit each staging chunk so the transaction does not grow
    # throughout the entire Groups extraction.
    conn.commit()

    logging.info(
        "Appended %d group membership history rows to staging.",
        loaded_count,
    )

    return loaded_count



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

def stored_proc(
    conn: pyodbc.Connection,
) -> None:
    cursor = conn.cursor()

    try:
        cursor.execute("EXEC dbo.SyncGroupMemberships;")
    finally:
        cursor.close()

def initialize_group_members_history_stream(
    conn: pyodbc.Connection,
) -> None:
    config = get_table_config("group_members_history")
    staging_table = config["staging_table"]

    cursor = conn.cursor()

    try:
        cursor.execute(
            build_truncate_sql(staging_table)
        )
        conn.commit()

        logging.info(
            "Initialized group membership history stream by "
            "truncating staging table '%s'.",
            staging_table,
        )

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()


def finalize_group_members_history_stream(
    conn: pyodbc.Connection,
) -> None:
    config = get_table_config("group_members_history")
    staging_table = config["staging_table"]

    cursor = conn.cursor()

    try:
        logging.info(
            "Executing SyncGroupMemberships after all membership "
            "history chunks were staged."
        )

        cursor.execute("EXEC dbo.SyncGroupMemberships;")

        cursor.execute(
            build_truncate_sql(staging_table)
        )

        conn.commit()

        logging.info(
            "Finished SyncGroupMemberships and cleared staging table '%s'.",
            staging_table,
        )

    except Exception:
        conn.rollback()

        logging.exception(
            "Failed to finalize streamed group membership history."
        )

        raise

    finally:
        cursor.close()


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


def uploader_from_stream(table_batches, endpoint) -> None:
    conn = None
    group_name = None

    is_groups_stream = endpoint == "groups"
    history_staging_initialized = False
    history_row_count = 0
    stream_completed = False

    try:
        conn = get_connection()

        # Clear membership-history staging exactly once before
        # consuming any Groups chunks.
        if is_groups_stream:
            initialize_group_members_history_stream(conn)
            history_staging_initialized = True

        for batch_index, table_batch in enumerate(
            table_batches,
            start=1,
        ):
            if not isinstance(table_batch, dict):
                raise TypeError(
                    "Table batches must be dictionaries like "
                    "{'people_core': records}."
                )

            logging.info(
                "Starting stream batch %d with %d table(s).",
                batch_index,
                len(table_batch),
            )

            try:
                for table_name, rows in table_batch.items():
                    if not rows:
                        logging.info(
                            "Skipping empty stream batch %d "
                            "-> table '%s'.",
                            batch_index,
                            table_name,
                        )
                        continue

                    logging.info(
                        "Processing stream batch %d "
                        "-> table '%s' with %d rows.",
                        batch_index,
                        table_name,
                        len(rows),
                    )

                    try:
                        if table_name == "group_members_history":
                            if not is_groups_stream:
                                raise ValueError(
                                    "Received group_members_history for "
                                    f"endpoint '{endpoint}'."
                                )

                            loaded_count = (
                                stage_group_members_history_chunk(
                                    conn=conn,
                                    records=rows,
                                )
                            )

                            history_row_count += loaded_count

                        else:
                            process_table(
                                conn=conn,
                                table_name=table_name,
                                raw_records=rows,
                                group_name=group_name,
                            )

                        logging.info(
                            "Finished stream batch %d "
                            "-> table '%s'.",
                            batch_index,
                            table_name,
                        )

                    finally:
                        rows.clear()

            finally:
                table_batch.clear()

            logging.info(
                "Completed stream batch %d.",
                batch_index,
            )

        # This is reached only if the extraction iterator completed
        # successfully without raising an exception.
        stream_completed = True

        if is_groups_stream:
            if history_row_count == 0:
                raise RuntimeError(
                    "The Groups extraction completed without producing "
                    "any group_members_history rows. "
                    "SyncGroupMemberships was not executed because an "
                    "empty staging table could mark every active "
                    "membership as having left."
                )

            logging.info(
                "All Groups chunks completed successfully. "
                "Finalizing %d staged membership-history rows.",
                history_row_count,
            )

            finalize_group_members_history_stream(conn)

        update_delta_record(
            conn=conn,
            endpoint=endpoint,
        )

    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                logging.exception(
                    "Failed to roll back streamed upload."
                )

        logging.exception(
            "Streamed upload failed | "
            "Endpoint=%s | "
            "StreamCompleted=%s | "
            "HistoryStagingInitialized=%s | "
            "HistoryRowsStaged=%d",
            endpoint,
            stream_completed,
            history_staging_initialized,
            history_row_count,
        )

        raise

    finally:
        if conn is not None:
            conn.close()

def uploader(tables: Dict[str, Any], endpoint) -> None:
    if not isinstance(tables, dict):
        raise TypeError("tables must be a dictionary like {'people_core': records}.")

    uploader_from_stream([dict(tables)], endpoint)
    tables.clear()