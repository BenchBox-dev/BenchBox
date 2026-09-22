"""Native ClickHouse reads of Delta Lake tables.

ClickHouse can query Delta Lake tables directly without a Parquet conversion
step: the ``DeltaLake`` table engine attaches to a Delta table in object
storage, and the ``deltaLake`` table-function family reads Delta tables from
S3 (``deltaLake`` / ``deltaLakeS3``), Azure Blob Storage (``deltaLakeAzure``),
or a locally mounted filesystem (``deltaLakeLocal``). This module builds those
SQL expressions with safe literal/identifier quoting so BenchBox can generate
native Delta reads instead of shelling out to ad-hoc string formatting.

Support is deployment dependent: the engine covers S3/GCS/Azure locations,
local reads go through the ``deltaLakeLocal`` table function, and minimal
embedded builds may omit the Delta integration entirely (observed: the
``chdb`` 26.1.2.1 build registers neither the functions nor the engine). When
native reads are unavailable, fall back to the Parquet snapshot export in
:mod:`benchbox.utils.delta_export`.

See the ClickHouse documentation for the ``DeltaLake`` table engine and the
``deltaLake`` table function.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

#: S3-backed Delta Lake table functions sharing one argument shape.
S3_TABLE_FUNCTIONS = frozenset({"deltaLake", "deltaLakeS3"})


def quote_literal(value: str) -> str:
    """Quote a string as a ClickHouse single-quoted literal.

    Args:
        value: Raw string value.

    Returns:
        The value wrapped in single quotes with backslash and quote escapes.

    Raises:
        ValueError: If the value is empty or whitespace-only.
    """
    if not value or not value.strip():
        raise ValueError("Cannot quote an empty string literal.")
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def quote_identifier(name: str) -> str:
    """Quote a table or database name as a ClickHouse identifier.

    Args:
        name: Raw identifier.

    Returns:
        The name wrapped in backticks with escapes applied.

    Raises:
        ValueError: If the name is empty or whitespace-only.
    """
    if not name or not name.strip():
        raise ValueError("Cannot quote an empty identifier.")
    return "`" + name.replace("\\", "\\\\").replace("`", "\\`") + "`"


def delta_lake_table_function(
    url: str,
    *,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    function: str = "deltaLake",
) -> str:
    """Build a ``deltaLake(url[, key, secret])`` table-function expression.

    Args:
        url: Bucket URL with the path to the Delta Lake table.
        access_key_id: Optional object-store access key (requires ``secret_access_key``).
        secret_access_key: Optional object-store secret (requires ``access_key_id``).
        function: Table function name; ``deltaLake`` or ``deltaLakeS3``.

    Returns:
        SQL expression such as ``deltaLake('s3://bucket/table')``.

    Raises:
        ValueError: If the URL is empty, the function name is unknown, or only one credential is given.
    """
    if not url or not url.strip():
        raise ValueError("Delta Lake table function requires a non-empty URL.")
    if function not in S3_TABLE_FUNCTIONS:
        raise ValueError(f"Unknown Delta Lake table function {function!r}: expected 'deltaLake' or 'deltaLakeS3'.")
    if (access_key_id is None) != (secret_access_key is None):
        raise ValueError("access_key_id and secret_access_key must be provided together or not at all.")
    expression = f"{function}({quote_literal(url)}"
    if access_key_id is not None and secret_access_key is not None:
        expression += f", {quote_literal(access_key_id)}, {quote_literal(secret_access_key)}"
    return expression + ")"


def delta_lake_local_table_function(path: str) -> str:
    """Build a ``deltaLakeLocal(path)`` expression for a locally mounted Delta table.

    Args:
        path: Filesystem path to the Delta table directory (must be visible to the ClickHouse server).

    Returns:
        SQL expression such as ``deltaLakeLocal('/data/orders')``.

    Raises:
        ValueError: If the path is empty.
    """
    if not path or not path.strip():
        raise ValueError("Delta Lake local table function requires a non-empty path.")
    return f"deltaLakeLocal({quote_literal(path)})"


def delta_lake_engine_ddl(
    table: str,
    url: str,
    *,
    database: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
) -> str:
    """Build ``CREATE TABLE ... ENGINE = DeltaLake(...)`` attaching to an existing Delta table.

    Args:
        table: Name of the ClickHouse table to create.
        url: Bucket URL with the path to the existing Delta Lake table.
        database: Optional database qualifier for the created table.
        access_key_id: Optional object-store access key (requires ``secret_access_key``).
        secret_access_key: Optional object-store secret (requires ``access_key_id``).

    Returns:
        DDL statement attaching to the Delta table without column definitions.

    Raises:
        ValueError: If names/URL are empty or only one credential is given.
    """
    if not url or not url.strip():
        raise ValueError("DeltaLake engine DDL requires a non-empty URL.")
    if (access_key_id is None) != (secret_access_key is None):
        raise ValueError("access_key_id and secret_access_key must be provided together or not at all.")
    name = quote_identifier(table)
    if database is not None:
        name = f"{quote_identifier(database)}.{name}"
    statement = f"CREATE TABLE {name} ENGINE = DeltaLake({quote_literal(url)}"
    if access_key_id is not None and secret_access_key is not None:
        statement += f", {quote_literal(access_key_id)}, {quote_literal(secret_access_key)}"
    return statement + ")"


def delta_lake_select_sql(
    source: str,
    *,
    columns: str | list[str] = "*",
    limit: int | None = None,
) -> str:
    """Build ``SELECT ... FROM <delta source>`` over a table-function expression or table name.

    Args:
        source: FROM-clause source, e.g. the output of :func:`delta_lake_table_function`.
        columns: Column list or ``"*"``.
        limit: Optional non-negative row limit.

    Returns:
        SELECT statement reading the Delta source natively.

    Raises:
        ValueError: If the source is empty, no columns are given, or the limit is negative.
    """
    if not source or not source.strip():
        raise ValueError("Delta Lake SELECT requires a non-empty source expression.")
    if isinstance(columns, list):
        if not columns:
            raise ValueError("Delta Lake SELECT requires at least one column.")
        column_sql = ", ".join(quote_identifier(column) for column in columns)
    else:
        if not columns or not columns.strip():
            raise ValueError("Delta Lake SELECT requires at least one column.")
        column_sql = columns
    if limit is not None and limit < 0:
        raise ValueError(f"Delta Lake SELECT limit must be non-negative, got {limit}.")
    statement = f"SELECT {column_sql} FROM {source}"
    if limit is not None:
        statement += f" LIMIT {limit}"
    return statement


def delta_lake_count_sql(source: str) -> str:
    """Build ``SELECT count() FROM <delta source>`` for row-count verification.

    Args:
        source: FROM-clause source, e.g. the output of :func:`delta_lake_table_function`.

    Returns:
        Count statement over the Delta source.

    Raises:
        ValueError: If the source is empty.
    """
    if not source or not source.strip():
        raise ValueError("Delta Lake COUNT requires a non-empty source expression.")
    return f"SELECT count() FROM {source}"
