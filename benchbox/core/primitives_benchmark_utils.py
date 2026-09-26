"""Shared helpers for Transaction and Write Primitives benchmarks."""

from __future__ import annotations

import re
from typing import Any, Callable

from benchbox.core.connection import DatabaseConnection
from benchbox.core.tpch.schema import get_create_all_tables_sql as get_tpch_ddl, get_table as get_tpch_table


def summarize_validation_failures(validation_results: list[dict[str, Any]]) -> str:
    """Build a one-line summary of failed (non-skipped) validation queries.

    Shared by both primitives benchmarks as the ``error`` message for a
    ``VALIDATION_FAILED`` OperationResult, so the console and result payload name
    which post-conditions the write violated, e.g.
    "validation failed: at_most_one_current_per_business_key (40 rows)".
    A result without a ``skipped`` key is treated as not skipped.
    """
    parts = []
    for vr in validation_results:
        if vr.get("skipped") or vr.get("passed", True):
            continue
        parts.append(f"{vr.get('query_id', '?')} ({vr.get('actual_rows', '?')} rows)")
    if not parts:
        return "validation failed"
    return "validation failed: " + ", ".join(parts)


def quote_identifier(identifier: str) -> str:
    """Quote a SQL identifier after validating it is safe."""
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", identifier):
        raise ValueError(
            f"Invalid SQL identifier: {identifier}. "
            "Only alphanumeric and underscore allowed, must start with letter or underscore."
        )

    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


#: Dialects whose catalog tables are created in UPPERCASE, so a quoted
#: identifier must be uppercased to resolve: Snowflake folds unquoted names
#: to upper (a quoted lowercase name is a different table), and BigQuery is
#: case-sensitive with adapter-created tables uppercased by convention.
UPPERCASE_IDENTIFIER_DIALECTS = frozenset({"snowflake", "bigquery"})


def quote_identifier_for_dialect(identifier: str, dialect: str | None) -> str:
    """Quote an identifier with the case and quoting the dialect's catalog uses.

    BigQuery uses backticks: double quotes denote string literals there, so a
    double-quoted table name is a syntax error, not an identifier. Databricks
    likewise rejects double-quoted identifiers with PARSE_SYNTAX_ERROR on
    warehouses without ANSI mode (verified live), so it uses backticks too.

    Args:
        identifier: Table, column, or schema name (source-case, usually lower)
        dialect: Platform dialect key (e.g. 'snowflake', 'duckdb'); None or
            'standard' keeps source case
    """
    normalized = (dialect or "standard").lower()
    if normalized == "bigquery":
        # Validate first for the same injection guard as quote_identifier.
        quote_identifier(identifier)
        return f"`{identifier.upper()}`"
    if normalized in ("databricks", "starrocks"):
        quote_identifier(identifier)
        escaped = identifier.replace("`", "``")
        return f"`{escaped}`"
    if normalized in UPPERCASE_IDENTIFIER_DIALECTS:
        return quote_identifier(identifier.upper())
    return quote_identifier(identifier)


def failed_platform_error(cursor: Any) -> str | None:
    """Return the adapter-reported error if ``cursor`` wraps a FAILED result.

    Several platform adapters report query failures as a FAILED result
    payload rather than raising. Reading such a cursor as success corrupts
    coverage: a failed write looks executed, and a failed validation SELECT
    materializes placeholder rows that can satisfy vacuous COUNT(*) checks.
    Callers must fail loud instead. Plain DB-API cursors (embedded engines)
    carry no ``platform_result`` and always return None here.

    Args:
        cursor: Cursor (or cursor-like) returned by ``connection.execute``.

    Returns:
        The adapter-reported error string, or None when the result is not a
        reported failure.
    """
    platform_result = getattr(cursor, "platform_result", None)
    if isinstance(platform_result, dict) and platform_result.get("status") == "FAILED":
        return str(platform_result.get("error", "unknown error"))
    if isinstance(cursor, dict) and cursor.get("status") == "FAILED":
        return str(cursor.get("error", "unknown error"))
    return None


def fetch_count_probe(connection: DatabaseConnection, sql: str) -> int:
    """Run a SELECT COUNT(*) probe and return the count.

    Platform adapters report query failures as a FAILED result payload
    rather than raising, which surfaces here as an empty row set. A failed
    probe must raise (fail loud) instead of reading as "0 rows", which would
    misreport a broken query as an empty table.
    """
    cursor = connection.execute(sql)
    if (probe_error := failed_platform_error(cursor)) is not None:
        raise RuntimeError(f"Count probe failed: {probe_error}")
    row = cursor.fetchone()
    return row[0] if row else 0


def table_exists(
    connection: DatabaseConnection,
    table_name: str,
    log_verbose: Callable[[str], None],
    dialect: str | None = None,
) -> bool:
    """Check whether a table exists without requiring information schema access."""
    try:
        quoted_table = quote_identifier_for_dialect(table_name, dialect)
        cursor = connection.execute(f"SELECT 1 FROM {quoted_table} LIMIT 0")
        if (error := failed_platform_error(cursor)) is not None:
            error_msg = error.lower()
            if any(
                phrase in error_msg
                for phrase in ["does not exist", "doesn't exist", "no such table", "unknown table", "not found"]
            ):
                return False
            log_verbose(f"Unexpected error checking table '{table_name}': {error}")
            return False
        return True
    except ValueError as exc:
        log_verbose(f"Invalid table name '{table_name}': {exc}")
        return False
    except Exception as exc:  # pragma: no cover - exercised via benchmark tests
        error_msg = str(exc).lower()
        if any(
            phrase in error_msg
            for phrase in ["does not exist", "doesn't exist", "no such table", "unknown table", "not found"]
        ):
            return False

        log_verbose(f"Unexpected error checking table '{table_name}': {type(exc).__name__}: {exc}")
        return False


def build_tpch_staging_tables_sql(
    *,
    dialect: str,
    tuning_config: Any,
    staging_heading: str,
    get_staging_tables_sql: Callable[[str], str],
) -> str:
    """Build the combined TPC-H plus staging-table DDL used by primitives benchmarks."""
    enable_primary_keys = False
    enable_foreign_keys = False

    if tuning_config is not None:
        pk_config = getattr(tuning_config, "primary_keys", None)
        fk_config = getattr(tuning_config, "foreign_keys", None)
        enable_primary_keys = getattr(pk_config, "enabled", False)
        enable_foreign_keys = getattr(fk_config, "enabled", False)

    tpch_ddl = get_tpch_ddl(
        enable_primary_keys=enable_primary_keys,
        enable_foreign_keys=enable_foreign_keys,
    )
    staging_ddl = get_staging_tables_sql(dialect)

    return f"""{tpch_ddl}

-- ============================================================
-- Generated staging load tables
-- ============================================================
-- These tables receive generator-emitted orders_stage.tbl and
-- lineitem_stage.tbl files during the generic load phase.
-- ============================================================

{_get_generated_stage_load_tables_sql()}

-- ============================================================
-- {staging_heading}
-- ============================================================
-- These tables are created empty and populated via setup()
-- after TPC-H base data is loaded
-- ============================================================

{staging_ddl}"""


def _get_generated_stage_load_tables_sql() -> str:
    """Return CREATE TABLE SQL for generator-emitted primitive staging files."""
    statements = []
    for source_name, stage_name in (("orders", "orders_stage"), ("lineitem", "lineitem_stage")):
        source_sql = get_tpch_table(source_name).get_create_table_sql(
            enable_primary_keys=False,
            enable_foreign_keys=False,
        )
        statements.append(source_sql.replace(f"CREATE TABLE {source_name} (", f"CREATE TABLE {stage_name} (", 1))
    return "\n\n".join(statements)
