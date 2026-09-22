"""Native ClickHouse reads of Delta Lake tables.

ClickHouse can query Delta Lake tables directly without a Parquet conversion
step: the ``DeltaLake`` table engine attaches to a Delta table in object
storage, and the ``deltaLake`` table-function family reads Delta tables from
S3 (``deltaLake`` / ``deltaLakeS3``), Azure Blob Storage (``deltaLakeAzure``),
or a locally mounted filesystem (``deltaLakeLocal``). This module builds those
SQL expressions with safe literal/identifier quoting so BenchBox can generate
native Delta reads instead of shelling out to ad-hoc string formatting.

Support is deployment dependent: the engine covers S3/GCS/Azure locations,
local reads go through the ``deltaLakeLocal`` table function, and minimal or
embedded builds may not register the Delta integration at all. When native
reads are unavailable, fall back to the Parquet snapshot export in
:mod:`benchbox.utils.delta_export`; :func:`has_native_delta_support` answers
the availability question from the server's system tables, while choosing
between the paths inside an adapter run is follow-up work.

Evidence: the ``DeltaLake`` table engine and ``deltaLake`` table-function family
in the ClickHouse documentation, corroborated in-repo by the Docker-gated
registration probe in ``tests/integration/platforms/`` (which names the server
version on failure). The format registry stays untouched until loading code
exists. GCS locations use the same engine/table-function URL form; there is no
separate GCS builder.

Trust contract: ``url``, ``path``, table/database names, and credential values
are quoted; ``source`` expressions and string-form ``columns`` are trusted
caller-provided SQL fragments and are interpolated verbatim. Pass only
module-built expressions (or constants) as ``source``, and prefer the
``list[str]`` column form, which is quoted per identifier.

Locations are passed through without scheme checks: valid forms vary per
backend (``s3://`` URLs, GCS XML-API URLs, Azure connection strings, local
paths), so the server is the authority on location validity.

Quoting note: these helpers escape backslash-then-quote for ClickHouse rather
than reusing :mod:`benchbox.utils.input_validation`, which has no ClickHouse
platform branch, vetoes identifiers containing reserved-word substrings, and
escapes only quote doubling without backslash handling. The in-package staging
loader (``clickhouse_cloud.py``) uses ``''``-doubling only; whether a backslash
survives that path is unaudited follow-up work, not a premise of this module.

See the ClickHouse documentation for the ``DeltaLake`` table engine and the
``deltaLake`` table function.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

#: S3-backed Delta Lake table functions sharing one argument shape.
_S3_TABLE_FUNCTIONS = frozenset({"deltaLake", "deltaLakeS3"})

#: Base Delta Lake table function; required for native reads.
DELTA_BASE_FUNCTION = "deltaLake"

#: Native Delta Lake table functions emitted by this module.
DELTA_TABLE_FUNCTION_NAMES = (DELTA_BASE_FUNCTION, "deltaLakeS3", "deltaLakeLocal", "deltaLakeAzure")

#: Native Delta Lake table engine name as registered in ``system.table_engines``.
DELTA_ENGINE_NAME = "DeltaLake"

__all__ = [
    "DELTA_BASE_FUNCTION",
    "DELTA_ENGINE_NAME",
    "DELTA_TABLE_FUNCTION_NAMES",
    "delta_engine_probe_sql",
    "delta_function_probe_sql",
    "delta_lake_azure_table_function",
    "delta_lake_count_sql",
    "delta_lake_engine_ddl",
    "delta_lake_local_table_function",
    "delta_lake_select_sql",
    "delta_lake_table_function",
    "has_native_delta_registration",
    "quote_identifier",
    "quote_literal",
]


def _require_credential(value: str | None, label: str) -> None:
    """Reject a blank credential value, naming the offending parameter."""
    if value is not None and not value.strip():
        raise ValueError(f"Delta Lake {label} must be non-blank when provided.")


def quote_literal(value: str) -> str:
    """Quote a string as a ClickHouse single-quoted literal.

    Args:
        value: Raw string value.

    Returns:
        The value wrapped in single quotes with backslash and quote escapes.

    Raises:
        ValueError: If the value is empty or contains a NUL character.
    """
    if not value:
        raise ValueError("Cannot quote an empty string literal.")
    if "\x00" in value:
        raise ValueError("Cannot quote a string literal containing NUL.")
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def quote_identifier(name: str) -> str:
    """Quote a table or database name as a ClickHouse identifier.

    Args:
        name: Raw identifier.

    Returns:
        The name wrapped in backticks with escapes applied.

    Raises:
        ValueError: If the name is empty or contains a NUL character.
    """
    if not name:
        raise ValueError("Cannot quote an empty identifier.")
    if "\x00" in name:
        raise ValueError("Cannot quote an identifier containing NUL.")
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
        ValueError: If the URL is empty or blank, the function name is unknown,
            only one credential is given, or a credential is blank.
    """
    if not url or not url.strip():
        raise ValueError("Delta Lake table function requires a non-empty URL.")
    if function not in _S3_TABLE_FUNCTIONS:
        raise ValueError(f"Unknown Delta Lake table function {function!r}: expected 'deltaLake' or 'deltaLakeS3'.")
    if (access_key_id is None) != (secret_access_key is None):
        raise ValueError("access_key_id and secret_access_key must be provided together or not at all.")
    _require_credential(access_key_id, "access_key_id")
    _require_credential(secret_access_key, "secret_access_key")
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
        ValueError: If names/URL are empty or blank, only one credential is
            given, or a credential is blank.
    """
    if not url or not url.strip():
        raise ValueError("DeltaLake engine DDL requires a non-empty URL.")
    if not table or not table.strip():
        raise ValueError("DeltaLake engine DDL requires a non-empty table name.")
    if (access_key_id is None) != (secret_access_key is None):
        raise ValueError("access_key_id and secret_access_key must be provided together or not at all.")
    name = quote_identifier(table)
    if database is not None:
        if not database.strip():
            raise ValueError("DeltaLake engine DDL requires a non-empty database name.")
        name = f"{quote_identifier(database)}.{name}"
    statement = f"CREATE TABLE {name} ENGINE = DeltaLake({quote_literal(url)}"
    if access_key_id is not None and secret_access_key is not None:
        statement += f", {quote_literal(access_key_id)}, {quote_literal(secret_access_key)}"
    return statement + ")"


def delta_lake_select_sql(
    source: str,
    *,
    columns: str | list[str] | tuple[str, ...] = "*",
    limit: int | None = None,
) -> str:
    """Build ``SELECT ... FROM <delta source>`` over a table-function expression or table name.

    The ``source`` is a trusted caller-provided SQL fragment (normally a
    module-built table-function expression) and is interpolated verbatim, as
    is a string-form ``columns`` value; the ``list[str]`` column form is
    quoted per identifier.

    Args:
        source: FROM-clause source, e.g. the output of :func:`delta_lake_table_function`.
        columns: Column list or ``"*"``.
        limit: Optional non-negative row limit (bools are rejected).

    Returns:
        SELECT statement reading the Delta source natively.

    Raises:
        ValueError: If the source is empty or blank, no usable columns are
            given, or the limit is not a non-negative int.
    """
    if not source or not source.strip():
        raise ValueError("Delta Lake SELECT requires a non-empty source expression.")
    if isinstance(columns, tuple):
        columns = list(columns)
    if isinstance(columns, list):
        if not columns or any(not column or not column.strip() for column in columns):
            raise ValueError("Delta Lake SELECT requires at least one non-blank column.")
        column_sql = ", ".join(quote_identifier(column) for column in columns)
    else:
        if not columns or not columns.strip():
            raise ValueError("Delta Lake SELECT requires at least one column.")
        column_sql = columns
    if isinstance(limit, bool) or (limit is not None and (not isinstance(limit, int) or limit < 0)):
        raise ValueError(f"Delta Lake SELECT limit must be a non-negative int, got {limit!r}.")
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


def delta_lake_azure_table_function(
    account_url: str,
    container: str,
    blobpath: str,
    *,
    account_name: str | None = None,
    account_key: str | None = None,
) -> str:
    """Build a ``deltaLakeAzure(url, container, blobpath[, account, key])`` expression.

    Args:
        account_url: Storage account URL (or connection string) for the account holding the table.
        container: Container holding the Delta Lake table.
        blobpath: Blob path to the Delta table directory within the container.
        account_name: Optional account name (requires ``account_key``).
        account_key: Optional account key (requires ``account_name``).

    Returns:
        SQL expression such as ``deltaLakeAzure('https://acct...', 'lake', 'orders')``.

    Raises:
        ValueError: If a location part is empty or blank, only one of account
            name/key is given, or a credential is blank.
    """
    for label, part in (("account URL", account_url), ("container", container), ("blob path", blobpath)):
        if not part or not part.strip():
            raise ValueError(f"Delta Lake Azure table function requires a non-empty {label}.")
    if (account_name is None) != (account_key is None):
        raise ValueError("account_name and account_key must be provided together or not at all.")
    _require_credential(account_name, "account_name")
    _require_credential(account_key, "account_key")
    expression = f"deltaLakeAzure({quote_literal(account_url)}, {quote_literal(container)}, {quote_literal(blobpath)}"
    if account_name is not None and account_key is not None:
        expression += f", {quote_literal(account_name)}, {quote_literal(account_key)}"
    return expression + ")"


def delta_function_probe_sql() -> str:
    """Build the ``system.functions`` query probing native Delta support.

    Whether ClickHouse registers table functions in ``system.functions`` or in
    ``system.table_functions`` is settled by running both probes on a Docker
    host (follow-up work); until then this targets ``system.functions``.

    Returns:
        SELECT statement listing the registered native Delta table functions.
    """
    names = ", ".join(quote_literal(name) for name in DELTA_TABLE_FUNCTION_NAMES)
    return f"SELECT name FROM system.functions WHERE name IN ({names})"


def delta_engine_probe_sql() -> str:
    """Build the ``system.table_engines`` query probing native Delta support.

    Returns:
        SELECT statement listing the native Delta table engine when registered.
    """
    return f"SELECT name FROM system.table_engines WHERE name = {quote_literal(DELTA_ENGINE_NAME)}"


def has_native_delta_registration(function_names: list[str], engine_names: list[str]) -> bool:
    """Decide native Delta registration from probed system-table names.

    This certifies registration only: the base ``deltaLake`` function plus the
    ``DeltaLake`` engine being present. It says nothing about per-backend
    (S3/local/Azure) executability, which needs a data-level read.

    Args:
        function_names: Function names reported by :func:`delta_function_probe_sql`.
        engine_names: Engine names reported by :func:`delta_engine_probe_sql`.

    Returns:
        True when the ``deltaLake`` function and the ``DeltaLake`` engine are
        both registered; the S3/local/Azure aliases alone are not sufficient.
    """
    return DELTA_BASE_FUNCTION in function_names and DELTA_ENGINE_NAME in engine_names
