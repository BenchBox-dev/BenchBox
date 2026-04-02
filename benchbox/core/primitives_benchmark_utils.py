"""Shared helpers for Transaction and Write Primitives benchmarks."""

from __future__ import annotations

import re
from typing import Any, Callable

from benchbox.core.connection import DatabaseConnection
from benchbox.core.tpch.schema import get_create_all_tables_sql as get_tpch_ddl


def quote_identifier(identifier: str) -> str:
    """Quote a SQL identifier after validating it is safe."""
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", identifier):
        raise ValueError(
            f"Invalid SQL identifier: {identifier}. "
            "Only alphanumeric and underscore allowed, must start with letter or underscore."
        )

    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def table_exists(
    connection: DatabaseConnection,
    table_name: str,
    log_verbose: Callable[[str], None],
) -> bool:
    """Check whether a table exists without requiring information schema access."""
    try:
        quoted_table = quote_identifier(table_name)
        connection.execute(f"SELECT 1 FROM {quoted_table} LIMIT 0")
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
-- {staging_heading}
-- ============================================================
-- These tables are created empty and populated via setup()
-- after TPC-H base data is loaded
-- ============================================================

{staging_ddl}"""
