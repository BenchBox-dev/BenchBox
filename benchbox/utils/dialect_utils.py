"""SQL dialect utilities for cross-database compatibility.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import re
from typing import Callable


def _query_has_group_or_order_by_all(query: str) -> bool:
    """Return True when the original query explicitly uses GROUP BY ALL or ORDER BY ALL."""

    return bool(re.search(r"(?i)\b(?:GROUP|ORDER)\s+BY\s+ALL\b", query))


def _restore_group_order_by_all_keyword(query: str) -> str:
    """Restore ALL keyword when SQLGlot quoted it as an identifier."""

    return re.sub(
        r"(?i)\b((?:GROUP|ORDER)\s+BY)\s+(\"ALL\"|`ALL`|\[ALL\])",
        r"\1 ALL",
        query,
    )


def _fix_sqlite_unsupported_syntax(query: str) -> str:
    """Rewrite SQLGlot output that SQLite cannot execute."""

    def replace_date_interval(match: re.Match[str]) -> str:
        date_literal = match.group("date")
        sign = match.group("op")
        value = match.group("value")
        unit = match.group("unit").lower()
        return f"DATE('{date_literal}', '{sign}{value} {unit}')"

    query = re.sub(
        r"\bDATE\s*\(\s*'(?P<date>\d{4}-\d{2}-\d{2})'\s*\)\s*"
        r"(?P<op>[+-])\s*INTERVAL\s+'(?P<value>\d+)'\s+(?P<unit>DAY|MONTH|YEAR)\b",
        replace_date_interval,
        query,
        flags=re.IGNORECASE,
    )

    date_parts = {
        "DAY": "%d",
        "MONTH": "%m",
        "YEAR": "%Y",
    }

    def replace_extract(match: re.Match[str]) -> str:
        part = match.group("part").upper()
        expression = match.group("expression").strip()
        return f"CAST(STRFTIME('{date_parts[part]}', {expression}) AS INTEGER)"

    return re.sub(
        r"\bEXTRACT\s*\(\s*(?P<part>DAY|MONTH|YEAR)\s+FROM\s+(?P<expression>[^()]+?)\s*\)",
        replace_extract,
        query,
        flags=re.IGNORECASE,
    )


def normalize_dialect_for_sqlglot(dialect: str) -> str:
    """Normalize dialect names for SQLGlot compatibility.

    Some database dialects are not directly supported by SQLGlot but are
    based on dialects that are supported. This function maps unsupported
    dialects to their closest supported equivalent.

    SQLGlot supports these dialects: 'athena', 'bigquery', 'clickhouse',
    'databricks', 'doris', 'drill', 'druid', 'duckdb', 'dune', 'hive',
    'materialize', 'mysql', 'oracle', 'postgres', 'presto', 'prql',
    'redshift', 'risingwave', 'snowflake', 'spark', 'spark2', 'sqlite',
    'starrocks', 'tableau', 'teradata', 'trino', 'tsql'.

    Args:
        dialect: The dialect name to normalize (case-insensitive)

    Returns:
        The normalized dialect name that SQLGlot can process

    Examples:
        >>> normalize_dialect_for_sqlglot("netezza")
        'postgres'
        >>> normalize_dialect_for_sqlglot("duckdb")
        'duckdb'
        >>> normalize_dialect_for_sqlglot("NETEZZA")
        'postgres'
    """
    # Convert to lowercase for case-insensitive matching
    dialect_lower = dialect.lower() if dialect else ""

    # Map unsupported dialects to their SQLGlot-compatible equivalents
    dialect_mapping = {
        "netezza": "postgres",  # Netezza is based on PostgreSQL
        "greenplum": "postgres",  # Greenplum is PostgreSQL-based
        "vertica": "postgres",  # Vertica uses PostgreSQL-compatible SQL
        "datafusion": "postgres",  # DataFusion uses PostgreSQL-compatible SQL
        "ansi": "postgres",  # ANSI SQL → PostgreSQL (defensive mapping, should not be used)
        "standard": "postgres",  # Standard SQL → PostgreSQL (defensive mapping, should not be used)
        # DuckDB, ClickHouse, BigQuery, Snowflake, Redshift already supported directly
    }

    return dialect_mapping.get(dialect_lower, dialect_lower)


def translate_sql_query(
    query: str,
    target_dialect: str,
    source_dialect: str = "netezza",
    identify: bool = True,
    pre_processors: list[Callable[[str], str]] | None = None,
    post_processors: list[Callable[[str], str]] | None = None,
) -> str:
    """Translate SQL query from source dialect to target dialect using SQLGlot.

    This is the centralized SQL translation function used by all benchmarks.
    It follows the TPC-DS gold standard pattern with comprehensive error handling.

    The default source dialect is "netezza" (Postgres-compatible), which provides
    the best compatibility with modern SQL features across platforms. This can be
    overridden for benchmarks that use platform-specific source queries (e.g.,
    ClickBench uses "clickhouse" as the source dialect).

    Args:
        query: SQL query text to translate
        target_dialect: Target SQL dialect (e.g., 'duckdb', 'bigquery', 'snowflake')
        source_dialect: Source SQL dialect (default: 'netezza' for modern SQL compatibility)
        identify: Whether to quote identifiers to prevent reserved keyword conflicts (default: True)
        pre_processors: Optional list of functions to pre-process query before translation
        post_processors: Optional list of functions to post-process query after translation

    Returns:
        Translated SQL query text. Returns original query if translation fails.

    Examples:
        >>> translate_sql_query("SELECT * FROM orders", "duckdb")
        'SELECT * FROM "orders"'

        >>> translate_sql_query("SELECT * FROM orders", "bigquery", source_dialect="postgres")
        'SELECT * FROM `orders`'

        >>> # With custom pre-processor
        >>> def fix_syntax(q): return q.replace("LIMIT", "FETCH FIRST")
        >>> translate_sql_query("SELECT * FROM t LIMIT 10", "oracle", pre_processors=[fix_syntax])
        'SELECT * FROM "t" FETCH FIRST 10 ROWS ONLY'
    """
    import logging

    logger = logging.getLogger(__name__)

    try:
        import sqlglot
    except ImportError:
        logger.warning("SQLGlot not available, returning original query")
        return query

    try:
        # Normalize both source and target dialects for SQLGlot compatibility
        src = normalize_dialect_for_sqlglot(source_dialect.lower())
        tgt = normalize_dialect_for_sqlglot(target_dialect.lower())

        # Apply pre-processors (e.g., TPC-DS interval syntax normalization)
        processed_query = query
        if pre_processors:
            for pre_proc in pre_processors:
                processed_query = pre_proc(processed_query)

        # Translate using SQLGlot
        # Some databases don't need identifier quoting:
        # - ClickHouse: case-sensitive without case-folding, lowercase schema matches unquoted lowercase
        # - PostgreSQL/DataFusion: unquoted identifiers are folded to lowercase by the engine
        # Quoting preserves case which causes mismatches with lowercase schemas.
        should_identify = identify and (tgt not in ("clickhouse", "postgres"))
        translated = sqlglot.transpile(processed_query, read=src, write=tgt, identify=should_identify)[0]

        # Built-in optional post-fix:
        # SQLGlot + identify=True can emit ORDER/GROUP BY "ALL" for DuckDB,
        # but DuckDB expects ALL as a keyword in these clauses.
        if tgt == "duckdb" and _query_has_group_or_order_by_all(query):
            translated = _restore_group_order_by_all_keyword(translated)
        elif tgt == "sqlite":
            translated = _fix_sqlite_unsupported_syntax(translated)

        # Apply post-processors (e.g., TPC-DS Query 58 ambiguity fix)
        if post_processors:
            for post_proc in post_processors:
                translated = post_proc(translated)

        return translated

    except Exception as e:
        logger.warning(
            f"SQLGlot translation failed from {source_dialect} to {target_dialect}: {e}. Returning original query."
        )
        return query


def fix_postgres_date_arithmetic(query: str) -> str:
    """Convert integer date arithmetic to INTERVAL syntax for PostgreSQL/DataFusion.

    PostgreSQL and DataFusion don't support `date + integer` directly.
    This converts patterns like `d_date + 5` to `d_date + INTERVAL '5' DAY`.

    Args:
        query: SQL query with potential date arithmetic

    Returns:
        Query with date arithmetic converted to INTERVAL syntax
    """
    import re

    # Pattern: column_name + integer or column_name - integer
    # where column_name contains 'date' (case-insensitive)
    # Matches: d_date + 5, d1.d_date + 30, d_date - 7
    pattern = r"(\b\w*\.?\w*d_date\w*)\s*([+-])\s*(\d+)"

    def replace_with_interval(match: re.Match) -> str:
        col = match.group(1)
        op = match.group(2)
        num = match.group(3)
        return f"{col} {op} INTERVAL '{num}' DAY"

    return re.sub(pattern, replace_with_interval, query, flags=re.IGNORECASE)
