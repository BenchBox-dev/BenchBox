"""Shared SQL utility functions for cross-platform table name normalization.

These utilities handle common SQL transformations needed by multiple platform
adapters, particularly lowercase normalization of table names for platforms
that are case-sensitive or convert unquoted identifiers to lowercase.
"""

from __future__ import annotations

import re


def normalize_table_name_in_sql(sql: str) -> str:
    """Normalize table names in SQL to lowercase.

    Handles CREATE TABLE statements (with optional IF NOT EXISTS and EXTERNAL
    keywords) and REFERENCES clauses. Strips quotes and lowercases identifiers.

    This is the canonical implementation used by platforms that require lowercase
    table names (Firebolt, Presto, Redshift, Spark, Trino, Athena, LakeSail).

    Args:
        sql: SQL statement to normalize.

    Returns:
        SQL with table names converted to unquoted lowercase.
    """
    # Match CREATE [EXTERNAL] TABLE [IF NOT EXISTS] "TableName" or TableName
    # Groups: (1) optional EXTERNAL, (2) optional IF NOT EXISTS, (3) table name
    sql = re.sub(
        r'CREATE(\s+EXTERNAL)?\s+TABLE(\s+IF\s+NOT\s+EXISTS)?\s+"?([A-Za-z_][A-Za-z0-9_]*)"?',
        lambda m: f"CREATE{m.group(1) or ''} TABLE{m.group(2) or ''} {m.group(3).lower()}",
        sql,
        flags=re.IGNORECASE,
    )

    # Match foreign key REFERENCES "TableName" or REFERENCES TableName
    sql = re.sub(
        r'REFERENCES\s+"?([A-Za-z_][A-Za-z0-9_]*)"?',
        lambda m: f"REFERENCES {m.group(1).lower()}",
        sql,
        flags=re.IGNORECASE,
    )

    return sql


def extract_table_name(statement: str) -> str | None:
    """Extract table name from a CREATE TABLE statement.

    Handles both plain ``CREATE TABLE name`` and
    ``CREATE TABLE IF NOT EXISTS name`` variants.

    Args:
        statement: SQL DDL statement.

    Returns:
        Extracted table name or ``None`` if no match.
    """
    try:
        match = re.search(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)",
            statement,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
    except Exception:
        pass
    return None
