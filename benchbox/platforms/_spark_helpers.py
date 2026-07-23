"""Shared helpers for Spark-dialect SQL adapters (spark, lakesail, velox).

These helpers live here rather than in ``benchbox/platforms/base/`` to keep
the adapter-base refactor scope clean - they are intra-platform utilities
shared between Spark-ecosystem adapters, not cross-platform abstractions.

Import discipline: adapter modules MUST import these names directly
(``from ._spark_helpers import is_spark_connect_reachable``) rather than
via attribute access (``from . import _spark_helpers; _spark_helpers.is_spark_connect_reachable(...)``).
Tests patch the imported name in the adapter module
(``benchbox.platforms.lakesail.is_spark_connect_reachable``), and
attribute-access calls would bypass that patch and try to open a real TCP
socket against ``localhost:50051`` during integration runs.
"""

from __future__ import annotations

import logging
import re
import socket
from collections.abc import Callable
from typing import Any

from benchbox.core.sql_utils import (
    extract_table_name as _extract_table_name,
    normalize_table_name_in_sql as _normalize_table_name_in_sql,
)
from benchbox.utils.sql_identifier import is_valid_sql_identifier

# Spark / Hive metastore caps identifiers at 128 characters.
_SPARK_IDENTIFIER_MAX_LEN = 128


def validate_spark_identifier(identifier: str) -> bool:
    """Validate a SQL identifier (database/table/column name) for Spark.

    Thin wrapper over ``benchbox.utils.sql_identifier.is_valid_sql_identifier``
    that pins the Spark/Hive 128-character cap.  Used as a safety gate before
    string-interpolating identifiers into SQL DDL where parameter binding is
    not available (Spark catalog ops).
    """
    return is_valid_sql_identifier(identifier, max_length=_SPARK_IDENTIFIER_MAX_LEN)


def extract_spark_table_name(statement: str) -> str | None:
    """Extract the table name from a CREATE TABLE statement."""
    return _extract_table_name(statement)


def _unquote_spark_retry_identifier(identifier: str | None) -> str | None:
    """Return a simple extracted Spark identifier suitable for retry SQL."""
    if not identifier:
        return None
    identifier = identifier.strip()
    if len(identifier) >= 2 and identifier[0] == identifier[-1] and identifier[0] in {'"', "`"}:
        identifier = identifier[1:-1]
    return identifier


def normalize_spark_table_name_in_sql(sql: str) -> str:
    """Normalize table names in SQL to lowercase for Spark."""
    return _normalize_table_name_in_sql(sql)


def parse_spark_connect_endpoint(endpoint: str, *, default_port: int = 50051) -> tuple[str, int]:
    """Extract host and port from a Spark Connect endpoint URL (sc://host:port)."""
    url = endpoint
    if url.startswith("sc://"):
        url = url[5:]
    host, _, port_str = url.partition(":")
    try:
        port = int(port_str) if port_str else default_port
    except ValueError:
        port = default_port
    return host or "localhost", port


def is_spark_connect_reachable(endpoint: str, *, timeout: float = 2.0) -> bool:
    """TCP probe: is the Spark Connect server reachable at the given endpoint?"""
    host, port = parse_spark_connect_endpoint(endpoint)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def list_spark_tables(connection: Any) -> list[str]:
    """List existing tables (lowercased) via the Spark catalog API.

    Returns an empty list when the catalog call fails (e.g. session lost,
    permissions, Connect plan-node not implemented). Callers are expected
    to treat the empty list as "unknown" rather than "definitely empty".
    """
    try:
        return [t.name.lower() for t in connection.catalog.listTables()]
    except Exception:
        return []


def analyze_spark_table(connection: Any, table_name: str, *, logger: logging.Logger) -> None:
    """Run ``ANALYZE TABLE ... COMPUTE STATISTICS`` for query optimisation."""
    if not validate_spark_identifier(table_name):
        logger.warning(f"Skipping ANALYZE: invalid table identifier '{table_name}'")
        return
    try:
        connection.sql(f"ANALYZE TABLE {table_name.lower()} COMPUTE STATISTICS")
        logger.debug(f"Analyzed table {table_name}")
    except Exception as e:
        logger.warning(f"Failed to analyze table {table_name}: {e}")


def get_spark_query_plan(connection: Any, query: str) -> str:
    """Return the ``EXPLAIN EXTENDED`` plan text for a Spark-like session.

    Works for both full PySpark sessions and Spark Connect sessions (LakeSail)
    since both expose ``spark.sql(...).collect()``.

    Args:
        connection: Active Spark / Spark Connect session.
        query: SQL query to explain.

    Returns:
        Multi-line plan text, or a short error string on failure.
    """
    spark = connection
    try:
        result_df = spark.sql(f"EXPLAIN EXTENDED {query}")
        plan_rows = result_df.collect()
        return "\n".join([str(row[0]) for row in plan_rows])
    except Exception as e:
        return f"Could not get query plan: {e}"


# Spark V1 datasource tables (USING PARQUET / ORC) do not support PRIMARY KEY,
# FOREIGN KEY, UNIQUE, or CHECK constraints - those are only valid for V2
# catalog tables (Delta Lake, Iceberg, etc.). Benchmarks whose schemas carry
# these constraints (write_primitives, metadata_primitives, transaction_primitives,
# datavault) fail at CREATE TABLE without stripping.
_USING_CLAUSE_RE = re.compile(r"\s+USING\s+\w+", re.IGNORECASE)
_SMALLINT_RE = re.compile(r"\bSMALLINT\b", re.IGNORECASE)
# Inline column-level PRIMARY KEY: matches the keyword pair only when it is NOT
# followed by '(' - that '(' marks a table-level ``PRIMARY KEY (cols)`` clause,
# which the balanced-paren stripper handles separately. Without the lookahead,
# this regex stripped just the keywords and left a dangling ``(cols)`` group
# that no longer matched the table-constraint stripper, producing invalid DDL
# like ``service_zone VARCHAR, (location_id))``.
_INLINE_PK_RE = re.compile(r"\bPRIMARY\s+KEY\b(?!\s*\()", re.IGNORECASE)
# Inline column-level UNIQUE: matches the bare keyword only when it is NOT
# followed by '(' - that '(' would mark a table-level UNIQUE clause, which
# the balanced-paren stripper handles separately.
_INLINE_UNIQUE_RE = re.compile(r"\bUNIQUE\b(?!\s*\()", re.IGNORECASE)
_TABLE_CONSTRAINT_KEYWORD_RE = re.compile(
    r",\s*(PRIMARY\s+KEY|UNIQUE|FOREIGN\s+KEY|CHECK)\s*\(",
    re.IGNORECASE,
)
_REFERENCES_TAIL_RE = re.compile(r"\s+REFERENCES\s+\S+\s*\(", re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",\s*\)")
# Collapse runs of plain spaces or tabs only.  Using ``\s`` here would also
# fold newlines, flattening multi-line DDL in debug logs to a single line.
_REPEATED_SPACE_RE = re.compile(r"[ \t]{2,}")
# Leading SQL comments that some benchmark schema generators emit ahead of the
# ``CREATE TABLE`` - both ``-- line`` comments and ``/* block */`` comments
# (SQLGlot transpilation rewrites ``-- ...`` headers into ``/* ... */`` form and
# folds them onto the first statement). They must be stripped before the
# ``CREATE TABLE`` detection below, otherwise the whole statement is returned
# un-normalised and the table-level constraint clauses reach Spark/Sail verbatim
# (e.g. ``PRIMARY KEY (col)`` -> "found KEY expected data type").
_LEADING_COMMENTS_RE = re.compile(r"\A(?:\s*(?:--[^\n]*(?:\n|$)|/\*.*?\*/))+\s*", re.DOTALL)
# DuckDB-style fixed-size array column type ``<TYPE>[<N>]`` (e.g. vector_search's
# ``embedding FLOAT[128]``). Spark and Sail DDL parsers reject the postfix
# bracket form; rewrite to the portable ``ARRAY<TYPE>`` element-typed form
# (the fixed length is not enforceable on a V1 parquet table anyway).
_FIXED_SIZE_ARRAY_TYPE_RE = re.compile(r"\b([A-Za-z]\w*)\s*\[\s*\d+\s*\]")
# SQLGlot may transpile ``FLOAT[128]`` to ``ARRAY<FLOAT>[128]`` (element type
# converted but the fixed-size suffix left in place); drop the trailing suffix.
_ARRAY_FIXED_SIZE_SUFFIX_RE = re.compile(r"(>)\s*\[\s*\d+\s*\]")


def _strip_balanced_paren_constraints(statement: str) -> str:
    """Remove ``, KEYWORD(...)`` table-level constraint clauses with balanced parens.

    Replaces the previous ``,\\s*KEYWORD\\s*\\([^)]*\\)`` regex, which corrupted
    DDL containing nested parens (e.g. ``CHECK ((a > 0) AND (b > 0))``) by
    matching only ``CHECK ((a > 0)`` and leaving the rest of the clause dangling.
    Counts parens from the constraint's opening ``(`` and consumes the optional
    trailing ``REFERENCES tbl(cols)`` for FOREIGN KEY clauses.
    """
    out: list[str] = []
    idx = 0
    while True:
        match = _TABLE_CONSTRAINT_KEYWORD_RE.search(statement, idx)
        if not match:
            out.append(statement[idx:])
            return "".join(out)

        out.append(statement[idx : match.start()])
        depth = 1
        cursor = match.end()
        while cursor < len(statement) and depth:
            ch = statement[cursor]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            cursor += 1
        if depth:
            # Unbalanced source DDL - bail out and leave the remainder intact
            # rather than producing corrupt output.
            out.append(statement[match.start() :])
            return "".join(out)

        # Consume an optional REFERENCES tail (FOREIGN KEY only), which itself
        # has its own paren group.
        ref_match = _REFERENCES_TAIL_RE.match(statement, cursor)
        if ref_match:
            ref_depth = 1
            ref_cursor = ref_match.end()
            while ref_cursor < len(statement) and ref_depth:
                ch = statement[ref_cursor]
                if ch == "(":
                    ref_depth += 1
                elif ch == ")":
                    ref_depth -= 1
                ref_cursor += 1
            if ref_depth == 0:
                cursor = ref_cursor
        idx = cursor


def optimize_spark_table_definition(
    statement: str,
    *,
    table_format: str = "parquet",
    strip_v1_constraints: bool = True,
    upcast_smallint: bool = True,
) -> str:
    """Normalise a CREATE TABLE statement for Spark V1 datasource tables.

    - Strips any existing USING clause and appends ``USING <table_format>``.
    - When ``strip_v1_constraints`` is True (the default for Spark V1 tables),
      removes inline ``PRIMARY KEY`` and column-level ``UNIQUE``, plus
      table-level ``PRIMARY KEY/UNIQUE/FOREIGN KEY/CHECK`` clauses (with
      balanced-paren matching so nested expressions like
      ``CHECK ((a > 0) AND (b > 0))`` are stripped cleanly), and tidies the
      resulting punctuation.
    - When ``upcast_smallint`` is True, rewrites ``SMALLINT`` to ``INT``. Spark's
      SMALLINT is signed INT16 (max 32767) but ClickBench and other benchmarks
      map ClickHouse UInt16 columns (0-65535) to SMALLINT, which would throw
      ``CAST_INVALID_INPUT`` on values > 32767 during data load.

    For V2 catalog formats (Delta, Iceberg) callers should pass
    ``strip_v1_constraints=False`` to preserve constraint metadata.

    Leading ``-- ...`` line comments are stripped first so the ``CREATE TABLE``
    detection (and therefore the whole normalisation) still applies to schema
    text that carries a comment header. Returns ``""`` for a chunk that is only
    comments/whitespace so callers can skip it.
    """
    statement = _LEADING_COMMENTS_RE.sub("", statement)
    if not statement.strip():
        return ""
    if not statement.upper().startswith("CREATE TABLE"):
        return statement

    statement = _USING_CLAUSE_RE.sub("", statement)
    statement = _FIXED_SIZE_ARRAY_TYPE_RE.sub(r"ARRAY<\1>", statement)
    statement = _ARRAY_FIXED_SIZE_SUFFIX_RE.sub(r"\1", statement)

    if upcast_smallint:
        statement = _SMALLINT_RE.sub("INT", statement)

    if strip_v1_constraints:
        statement = _INLINE_PK_RE.sub("", statement)
        statement = _INLINE_UNIQUE_RE.sub("", statement)
        statement = _strip_balanced_paren_constraints(statement)
        statement = _TRAILING_COMMA_RE.sub(")", statement)
        statement = _REPEATED_SPACE_RE.sub(" ", statement)

    if ")" in statement:
        fmt = (table_format or "parquet").upper()
        statement = statement.rstrip(";").rstrip() + f" USING {fmt}"
    return statement


def purge_orphaned_warehouse_directory(spark: Any, *, logger: logging.Logger) -> None:
    """Drop and recreate the current database when the catalog reports no tables.

    Defends against orphaned managed-table directories left behind by a previous
    Spark session (e.g. a Docker container restart that wipes the in-memory
    Derby metastore but leaves ``spark.sql.warehouse.dir`` in place). When the
    catalog says "no tables" but the warehouse still has on-disk dirs, the next
    ``CREATE TABLE`` raises ``LOCATION_ALREADY_EXISTS``.

    The purge runs only when the catalog probe SUCCEEDS and reports empty.
    A probe FAILURE (e.g. transient gRPC error before the session is ready)
    is *not* treated as "empty" - that's the false-positive trap that would
    cause a destructive DROP CASCADE on a populated database.  This helper
    therefore uses a tight catalog probe that distinguishes the two cases,
    rather than the more lenient ``list_spark_tables`` (which swallows probe
    failures and returns the same ``[]`` for both "empty" and "unknown").
    """
    try:
        existing = list(spark.catalog.listTables())
    except Exception as exc:
        # Probe failed - we DO NOT know whether the catalog is empty.
        # Skip the purge; if the on-disk warehouse really is orphaned, the
        # in-loop "already exists" retry will surface a clear error.
        logger.debug(f"Warehouse purge skipped (catalog probe failed): {exc}")
        return
    if existing:
        return
    try:
        rows = spark.sql("SELECT current_database()").collect()
        if not rows:
            return
        current_db = rows[0][0]
        if not validate_spark_identifier(current_db):
            return
        spark.sql(f"DROP DATABASE IF EXISTS `{current_db}` CASCADE")
        spark.sql(f"CREATE DATABASE IF NOT EXISTS `{current_db}`")
        spark.sql(f"USE `{current_db}`")
        # Visible at -v: the purge mutates the user's warehouse, so a successful
        # firing should not be hidden behind debug-only logging.
        logger.info(f"Purged potentially-orphaned warehouse directory for database '{current_db}'")
    except Exception as exc:
        # Best-effort: if DROP/CREATE/USE fails the schema-creation loop will
        # surface the underlying problem.  No silent data loss because this
        # branch only runs when the catalog probe already reported empty.
        logger.debug(f"Warehouse purge aborted mid-cycle: {exc}")


class SparkLikeAdapterMixin:
    """Behaviour shared verbatim by the spark, lakesail, and velox adapters.

    Lifts three methods that had identical (or near-identical) bodies in all
    three adapters:

    - ``apply_constraint_configuration``: Spark-family engines do not enforce
      PRIMARY KEY / FOREIGN KEY constraints; this method only logs that the
      configuration was seen.  The platform display name in the log line is
      taken from ``self.platform_name`` so the output is engine-specific.
    - ``apply_unified_tuning``: dispatches to the constraint, platform-
      optimisation, and per-table tuning hooks in a fixed order.
    - ``apply_platform_optimizations``: forwards each ``platform_config.spark``
      key/value to ``spark.conf.set("spark.<key>", value)``.  Every override
      that fails is logged at WARNING; the final summary line uses
      ``self.platform_name`` for engine-specific output.

    Extending classes must:
      * Provide ``self.logger`` (PlatformAdapter does).
      * Provide ``self.platform_name`` (each Spark-family adapter does).
      * Define ``apply_table_tunings(table_tuning, connection)`` for any
        table-level work; ``apply_unified_tuning`` calls into it per table.
    """

    def apply_constraint_configuration(
        self,
        primary_key_config: Any,
        foreign_key_config: Any,
        connection: Any,
    ) -> None:
        """Log informational notices for PK/FK config; Spark engines do not enforce."""
        platform = self.platform_name  # type: ignore[attr-defined]
        if primary_key_config and primary_key_config.enabled:
            self.logger.info(  # type: ignore[attr-defined]
                f"Primary key constraints enabled for {platform} (informational only, not enforced)"
            )
        if foreign_key_config and foreign_key_config.enabled:
            self.logger.info(  # type: ignore[attr-defined]
                f"Foreign key constraints enabled for {platform} (informational only, not enforced)"
            )

    def apply_unified_tuning(self, unified_config: Any, connection: Any) -> None:
        """Dispatch unified tuning to the constraint / platform / per-table hooks."""
        from benchbox.platforms.base.tuning_config import apply_standard_unified_tuning

        apply_standard_unified_tuning(self, unified_config, connection)

    def apply_platform_optimizations(self, platform_config: Any, connection: Any) -> None:
        """Forward ``platform_config.spark`` settings to ``spark.conf.set``."""
        if not platform_config:
            return

        spark = connection
        platform = self.platform_name  # type: ignore[attr-defined]
        if hasattr(platform_config, "spark") and platform_config.spark:
            for key, value in platform_config.spark.items():
                try:
                    spark.conf.set(f"spark.{key}", str(value))
                    self.logger.debug(f"Applied {platform} config: spark.{key} = {value}")  # type: ignore[attr-defined]
                except Exception as exc:
                    self.logger.warning(  # type: ignore[attr-defined]
                        f"Failed to apply {platform} config spark.{key}: {exc}"
                    )

        self.logger.info(f"{platform} platform optimizations applied")  # type: ignore[attr-defined]


def run_spark_schema_creation_loop(
    spark: Any,
    statements: list[str],
    optimize_statement: Callable[[str], str],
    *,
    logger: logging.Logger,
    on_pre_loop: Callable[[Any], None] | None = None,
    on_location_collision: Callable[[Any, str], None] | None = None,
) -> None:
    """Execute a sequence of CREATE TABLE statements with shared retry semantics.

    Steps for each statement:
      1. ``normalize_spark_table_name_in_sql``
      2. ``optimize_statement`` (caller-supplied; typically wraps
         ``optimize_spark_table_definition`` with the right flags)
      3. ``spark.sql(statement)``
      4. On "already exists": extract the table name, ``DROP TABLE IF EXISTS``,
         optionally call ``on_location_collision`` (e.g. spark.py's filesystem
         cleanup of the orphaned warehouse dir), then retry ``spark.sql(statement)``.

    Args:
        spark: Active Spark or Spark-Connect session.
        statements: Pre-split CREATE TABLE statements (no terminating ``;``).
        optimize_statement: Function applied to each statement after table-name
            normalisation (typically ``optimize_spark_table_definition`` with
            adapter-specific flags).
        logger: Logger for debug output of each executed statement.
        on_pre_loop: Optional hook fired exactly once before the loop runs.
            Velox uses this to call ``purge_orphaned_warehouse_directory``.
        on_location_collision: Optional hook fired when the retry path detects
            a ``LOCATION_ALREADY_EXISTS`` error.  Receives ``(spark, table_name)``
            so adapters with filesystem access can drop the orphaned dir.
            Spark.py uses this; remote adapters (Velox/LakeSail) leave it None
            because they cannot reach the server's filesystem.

    Raises:
        Any exception not matching ``"already exists"``, OR an "already exists"
        error whose statement we cannot extract a valid table name from (the
        retry path is unsafe in that case - explicit raise rather than silent
        swallow).
    """
    if on_pre_loop is not None:
        on_pre_loop(spark)

    for statement in statements:
        statement = statement.strip() if statement else ""
        if not statement:
            continue
        statement = normalize_spark_table_name_in_sql(statement)
        statement = optimize_statement(statement)
        if not statement.strip():
            # optimize_statement collapsed a comment-only chunk to nothing.
            continue
        try:
            spark.sql(statement)
            logger.debug(f"Executed schema statement: {statement[:100]}...")
        except Exception as exc:
            error_lower = str(exc).lower()
            if "already exists" not in error_lower:
                raise

            extracted_table_name = extract_spark_table_name(statement)
            table_name = _unquote_spark_retry_identifier(extracted_table_name)
            if not (table_name and validate_spark_identifier(table_name)):
                # Cannot safely recover - re-raise rather than silently
                # consuming the error and leaving the schema half-built.
                # Wrap with a clearer message so the user sees that the
                # extracted table name failed strict-ASCII validation, not
                # just the original Spark "already exists" string.
                raise RuntimeError(
                    "Cannot safely retry CREATE: extracted table name "
                    f"{extracted_table_name!r} from statement {statement[:80]!r} failed "
                    "strict-ASCII identifier validation. Either rename the "
                    "table to match ^[a-zA-Z_][a-zA-Z0-9_]*$ (<=128 chars) or "
                    "drop the conflicting object manually."
                ) from exc

            spark.sql(f"DROP TABLE IF EXISTS {table_name}")
            if on_location_collision is not None and "location_already_exists" in error_lower:
                on_location_collision(spark, table_name)
            spark.sql(statement)
