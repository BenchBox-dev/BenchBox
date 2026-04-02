"""Shared utilities for benchmark schema SQL generation."""

from __future__ import annotations

from collections.abc import Callable


def collect_create_table_sql(
    table_order: list[str],
    get_single_table_fn: Callable[..., str],
    dialect: str = "standard",
    *,
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:
    """Collect CREATE TABLE SQL for a list of tables in dependency order.

    Centralises the iterate-and-join pattern shared across benchmark schema
    modules (AMPLab, Read-Primitives/TPC-H, SSB).

    Args:
        table_order: Table names in dependency order.
        get_single_table_fn: Function that generates DDL for a single table.
            Must accept ``(table_name, dialect, *, enable_primary_keys, enable_foreign_keys)``.
        dialect: SQL dialect to use.
        enable_primary_keys: Whether to include primary key constraints.
        enable_foreign_keys: Whether to include foreign key constraints.

    Returns:
        Complete SQL schema creation script.
    """
    sql_statements = []
    for table_name in table_order:
        sql_statements.append(
            get_single_table_fn(
                table_name,
                dialect,
                enable_primary_keys=enable_primary_keys,
                enable_foreign_keys=enable_foreign_keys,
            )
        )
    return "\n\n".join(sql_statements)
