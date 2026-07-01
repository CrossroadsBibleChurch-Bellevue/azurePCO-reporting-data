from typing import List


def quote_identifier_part(identifier: str) -> str:
    return f"[{identifier.replace(']', ']]')}]"


def quote_sql_name(name: str) -> str:
    """
    Converts dbo.TableName into [dbo].[TableName].
    """
    return ".".join(quote_identifier_part(part) for part in name.split("."))


def build_truncate_sql(staging_table: str) -> str:
    return f"TRUNCATE TABLE {quote_sql_name(staging_table)};"


def build_staging_insert_sql(staging_table: str, columns: List[str]) -> str:
    column_sql = ", ".join(quote_identifier_part(col) for col in columns)
    placeholders = ", ".join("?" for _ in columns)

    return f"""
        INSERT INTO {quote_sql_name(staging_table)} (
            {column_sql}
        )
        VALUES (
            {placeholders}
        );
    """


def build_upsert_sql(
    target_table: str,
    staging_table: str,
    columns: List[str],
    key_columns: List[str],
) -> str:
    non_key_columns = [col for col in columns if col not in key_columns]

    if not non_key_columns:
        raise ValueError("At least one non-key column is required for update.")

    join_sql = " AND ".join(
        f"target.{quote_identifier_part(col)} = source.{quote_identifier_part(col)}"
        for col in key_columns
    )

    update_set_sql = ",\n        ".join(
        f"target.{quote_identifier_part(col)} = source.{quote_identifier_part(col)}"
        for col in non_key_columns
    )

    insert_columns_sql = ",\n        ".join(
        quote_identifier_part(col)
        for col in columns
    )

    select_columns_sql = ",\n        ".join(
        f"source.{quote_identifier_part(col)}"
        for col in columns
    )

    null_check_column = key_columns[0]

    sql = f"""
    UPDATE target
    SET
        {update_set_sql}
    FROM {quote_sql_name(target_table)} AS target
    INNER JOIN {quote_sql_name(staging_table)} AS source
        ON {join_sql};

    INSERT INTO {quote_sql_name(target_table)} (
        {insert_columns_sql}
    )
    SELECT
        {select_columns_sql}
    FROM {quote_sql_name(staging_table)} AS source
    LEFT JOIN {quote_sql_name(target_table)} AS target
        ON {join_sql}
    WHERE target.{quote_identifier_part(null_check_column)} IS NULL;
    """

    return sql