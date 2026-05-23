# ruff: noqa: SIM905
"""Workload execution helpers for StarRocks."""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any

from benchbox.platforms.base.data_loading import (
    DataSource,
    FileFormatHandler,
    FileFormatRegistry,
    resolve_csv_dialect,
    validate_sql_identifier,
)
from benchbox.platforms.base.ddl_helpers import strip_foreign_keys
from benchbox.platforms.base.sql_execution import execute_sql_query
from benchbox.utils.clock import elapsed_seconds, mono_time

logger = logging.getLogger(__name__)


def _stream_load_treats_empty_as_null(delimiter: str) -> bool:
    """Decide the StarRocks Stream Load null_format header from the CSV delimiter.

    Comma-delimited CSV is the historical StarRocks default for empty=NULL ingest
    (null_format=""); pipe-delimited TPC TBL and tab CSV keep empties as literal
    empty strings (null_format=\\N). Keying on delimiter — rather than the
    resolver's null_marker signal — preserves behaviour for unannotated comma
    CSVs whose dialect resolves to null_marker=None.
    """
    return delimiter == ","


def _split_sql_literals(query: str) -> list[tuple[str, bool]]:
    """Split SQL into alternating (text, is_literal) segments.

    ``is_literal`` is True for single-quoted string literals (including their
    surrounding quotes). Double-quotes and backticks are left in the code
    segment because StarRocks needs to rewrite ANSI-quoted identifiers; any
    MySQL-style double-quoted *literal* would be non-portable and isn't used
    by in-repo benchmark queries. MySQL escape forms handled: backslash escape
    and SQL-standard ``''`` doubling inside single-quoted literals.
    """
    segments: list[tuple[str, bool]] = []
    n = len(query)
    i = 0
    start = 0
    while i < n:
        if query[i] == "'":
            if start < i:
                segments.append((query[start:i], False))
            lit_start = i
            i += 1
            while i < n:
                c = query[i]
                if c == "\\" and i + 1 < n:
                    i += 2
                    continue
                if c == "'":
                    if i + 1 < n and query[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            segments.append((query[lit_start:i], True))
            start = i
        else:
            i += 1
    if start < n:
        segments.append((query[start:], False))
    return segments


def _apply_outside_literals(pattern: re.Pattern[str], repl: str, query: str) -> str:
    """Run ``pattern.sub(repl, …)`` on code segments only, preserving string literals."""
    parts = _split_sql_literals(query)
    return "".join(text if is_lit else pattern.sub(repl, text) for text, is_lit in parts)


class StarRocksWorkloadMixin:
    """Provide schema management and workload execution utilities for StarRocks."""

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using StarRocks-optimized table definitions."""
        start_time = mono_time()

        # Get constraint settings from tuning configuration
        enable_primary_keys, enable_foreign_keys = self._get_constraint_configuration()
        self._log_constraint_configuration(enable_primary_keys, enable_foreign_keys)

        try:
            effective_config = self.get_effective_tuning_configuration()
            schema_sql = benchmark.get_create_tables_sql(
                dialect="duckdb",
                tuning_config=effective_config,
            )

            # Strip SQL line comments before splitting so comment-prefixed blocks
            # (e.g. metadata_primitives header, write_primitives staging separator)
            # don't hide the CREATE TABLE from _optimize_table_definition.
            schema_sql_clean = re.sub(r"--[^\n]*\n?", "", schema_sql)
            statements = [stmt.strip() for stmt in schema_sql_clean.split(";") if stmt.strip()]

            cursor = connection.cursor()
            try:
                # Increase tablet creation timeout to avoid spurious DDL failures
                # under concurrent load. This is a server-wide frontend config;
                # we ignore errors so managed deployments without ADMIN privilege
                # still work - they just get the default 10s timeout.
                try:
                    cursor.execute('ADMIN SET FRONTEND CONFIG("tablet_create_timeout_second"="600")')
                except Exception:
                    pass

                for statement in statements:
                    statement = self._optimize_table_definition(statement)
                    cursor.execute(statement)
                    self.logger.debug(f"Executed schema statement: {statement[:100]}...")
            finally:
                cursor.close()

            self.logger.info(f"Schema created (PKs: {enable_primary_keys}, FKs: {enable_foreign_keys})")

        except Exception as e:
            self.logger.error(f"Schema creation failed: {e}")
            raise

        return elapsed_seconds(start_time)

    def _optimize_table_definition(self, statement: str) -> str:
        """Optimize table definition for StarRocks compatibility."""
        if not statement.upper().startswith("CREATE TABLE"):
            return statement

        # Remove AUTOINCREMENT / AUTO_INCREMENT (not standard in StarRocks DDL from DuckDB)
        statement = re.sub(r"\bAUTOINCREMENT\b", "", statement, flags=re.IGNORECASE)
        statement = re.sub(r"\bAUTO_INCREMENT\b", "", statement, flags=re.IGNORECASE)

        # StarRocks uses Duplicate Key model by default (good for OLAP)
        # Ensure ENGINE is not present (StarRocks uses different syntax)

        # Remove any ENGINE clauses from DuckDB-style DDL
        statement = re.sub(r"\s+ENGINE\s*=\s*\w+(\([^)]*\))?", "", statement, flags=re.IGNORECASE)

        # Convert DuckDB types to StarRocks types
        statement = self._convert_types(statement)

        statement = strip_foreign_keys(statement)

        # Extract primary key columns BEFORE stripping, so we can preserve the
        # PRIMARY KEY model for StarRocks (which supports UPDATE/DELETE on PK tables).
        # Check for table-level "PRIMARY KEY (col1, col2)" first, then inline "col TYPE PRIMARY KEY".
        pk_match = re.search(r"\bPRIMARY\s+KEY\s*\(([^)]+)\)", statement, re.IGNORECASE)
        if pk_match:
            pk_cols_raw = pk_match.group(1)
        else:
            # Inline PRIMARY KEY on a column definition line: "  col_name TYPE PRIMARY KEY"
            # Use MULTILINE so ^ anchors to the line start, and avoid . crossing lines.
            pk_inline = re.search(r"^\s+(\w+)\s+\w[\w()]*.*\bPRIMARY\s+KEY\b", statement, re.IGNORECASE | re.MULTILINE)
            pk_cols_raw = pk_inline.group(1) if pk_inline else None

        # Remove table-level PRIMARY KEY constraint first so its argument list
        # is consumed before the inline-PK regex can strip just the keywords.
        # Handles: "  last_col TYPE NOT NULL,\n  PRIMARY KEY (col1, col2)"
        statement = re.sub(r",?\s*PRIMARY\s+KEY\s*\([^)]+\)", "", statement, flags=re.IGNORECASE)

        # Remove inline PRIMARY KEY from column definitions (no argument list follows).
        # Handles: "  o_orderkey INTEGER PRIMARY KEY"
        statement = re.sub(r"\s+PRIMARY\s+KEY\b", "", statement, flags=re.IGNORECASE)

        # Cache first column - used by both DUPLICATE KEY and DISTRIBUTED BY clauses.
        first_col = self._extract_first_column(statement)

        # Add table model if not present (recompute upper after mutations).
        # If the original DDL had a PRIMARY KEY, preserve that model so StarRocks
        # allows UPDATE/DELETE operations (DUPLICATE KEY tables are append-only).
        # StarRocks requires PK columns to be the FIRST N columns in schema order,
        # so we verify that before committing to PRIMARY KEY model.
        current_upper = statement.upper()
        if "DUPLICATE KEY" not in current_upper and "PRIMARY KEY" not in current_upper:
            use_pk = False
            if pk_cols_raw:
                pk_cols = [c.strip().strip("`").strip('"') for c in pk_cols_raw.split(",")]
                col_names = re.findall(r"^\s+(\w+)\s+\w", statement, re.MULTILINE)
                # Fall back to DUPLICATE KEY if column-name extraction failed - a
                # malformed parse must not silently accept an unverified PK order.
                # PK columns must appear in order as the first len(pk_cols) columns.
                use_pk = len(col_names) > 0 and len(col_names) >= len(pk_cols) and col_names[: len(pk_cols)] == pk_cols

            if use_pk and pk_cols_raw:
                # Preserve PRIMARY KEY model: StarRocks syntax is "PRIMARY KEY (col)"
                # outside the column list, before DISTRIBUTED BY.
                pk_clause = f"PRIMARY KEY ({pk_cols_raw.strip()})"
                stripped = statement.rstrip()
                if stripped.endswith(";"):
                    statement = stripped[:-1] + f"\n{pk_clause};"
                else:
                    statement = stripped + f"\n{pk_clause}"
            elif first_col:
                stripped = statement.rstrip()
                if stripped.endswith(";"):
                    statement = stripped[:-1] + f"\nDUPLICATE KEY(`{first_col}`);"
                else:
                    statement = stripped + f"\nDUPLICATE KEY(`{first_col}`)"

        # Recompute after possible DUPLICATE KEY mutation
        current_upper = statement.upper()

        # Add DISTRIBUTED BY HASH if not present
        if "DISTRIBUTED BY" not in current_upper:
            if first_col:
                # Append distribution clause
                if statement.rstrip().endswith(";"):
                    statement = statement.rstrip()[:-1] + f"\nDISTRIBUTED BY HASH(`{first_col}`) BUCKETS 8;"
                else:
                    statement = statement.rstrip() + f"\nDISTRIBUTED BY HASH(`{first_col}`) BUCKETS 8"

        return statement

    # DuckDB/standard SQL → StarRocks type mappings.
    # Each entry is (pattern, replacement, case_sensitive). TIMESTAMP and TIME are
    # reserved SQL words that also appear as column names (write_primitives uses
    # "timestamp"); marking those case-sensitive avoids mangling the column names,
    # since SQL type keywords are conventionally uppercase.
    _TYPE_MAPPINGS: tuple[tuple[str, str, bool], ...] = (
        (r"\bHUGEINT\b", "LARGEINT", False),
        (r"\bINTEGER\b", "INT", False),
        # ClickBench data contains uint16 values (e.g. 51544) that exceed signed
        # SMALLINT range (-32768..32767); promote to INT to avoid load failures.
        (r"\bSMALLINT\b", "INT", False),
        (r"\bTIMESTAMP\b", "DATETIME", True),
        (r"\bTIME\b", "VARCHAR(10)", True),
        (r"\bSTRING\b", "VARCHAR(65533)", False),
        (r"\bTEXT\b", "VARCHAR(65533)", False),
        # DuckDB/SQLite allow bare VARCHAR (unbounded); StarRocks requires a size.
        # Only match when NOT followed by '(' to avoid mangling VARCHAR(50) etc.
        (r"\bVARCHAR\b(?!\s*\()", "VARCHAR(65533)", False),
        (r"\bBOOLEAN\b", "BOOLEAN", False),
        (r"\bDOUBLE\s+PRECISION\b", "DOUBLE", False),
        (r"\bREAL\b", "FLOAT", False),
        (r"\bBLOB\b", "VARCHAR(65533)", False),
        # DuckDB fixed-size float arrays (e.g. FLOAT[128]) → ARRAY<FLOAT>
        (r"\bFLOAT\[\d+\]", "ARRAY<FLOAT>", False),
        # DECIMAL with precision is fine as-is
    )

    def _convert_types(self, statement: str) -> str:
        """Convert DuckDB/standard SQL types to StarRocks-compatible types."""
        for pattern, replacement, case_sensitive in self._TYPE_MAPPINGS:
            flags = 0 if case_sensitive else re.IGNORECASE
            statement = re.sub(pattern, replacement, statement, flags=flags)
        return statement

    def _extract_first_column(self, statement: str) -> str | None:
        """Extract the first column name from a CREATE TABLE statement.

        The extracted name is validated against the SQL identifier pattern
        before return, so it is safe to interpolate into DDL fragments
        (backticks are still applied by the caller).
        """
        paren_start = statement.find("(")
        if paren_start == -1:
            return None

        content = statement[paren_start + 1 :]
        match = re.match(r"\s*`?(\w+)`?", content)
        if not match:
            return None
        name = match.group(1)
        try:
            validate_sql_identifier(name, "column name")
        except ValueError:
            return None
        return name

    def load_data(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data using INSERT statements for compatibility."""
        from benchbox.platforms.base.data_loading import DataLoader

        def starrocks_handler_factory(file_path, adapter, benchmark_instance, table_name=None, data_source=None):
            base_ext = FileFormatRegistry.get_base_data_extension(file_path)

            # Use STREAM LOAD (HTTP) for CSV/TBL files: produces exactly one
            # tablet rowset per table rather than one per INSERT batch, avoiding
            # the compaction-pressure failures that hit large tables (6M+ rows)
            # when batch INSERT accumulates 600+ rowsets before StarRocks BE can
            # compact them.  expr_children_limit is also irrelevant for STREAM LOAD.
            if base_ext in (".tbl", ".dat", ".csv"):
                dialect_source = data_source or DataSource(source_type="starrocks_handler", tables={})
                dialect = resolve_csv_dialect(
                    dialect_source, table_name or file_path.stem, file_path, benchmark_instance
                )
                null_empty = _stream_load_treats_empty_as_null(dialect.delimiter)
                return StarRocksStreamLoadHandler(
                    delimiter=dialect.delimiter,
                    host=self.host,
                    http_port=self.http_port,
                    database=self.database,
                    username=self.username,
                    password=self.password,
                    null_empty_strings=null_empty,
                    has_header=dialect.has_header,
                )
            elif base_ext == ".parquet":
                # Generic ParquetFileHandler uses '?' placeholders (DuckDB) and
                # connection.executemany() - both incompatible with PyMySQL.
                return StarRocksParquetHandler()
            return None  # Fall back to generic handler

        # Raise per-query and network timeouts to survive multi-hour bulk-INSERT
        # sessions (loading 10M+ rows via batch INSERT can take 45-90 min).
        # net_read_timeout / net_write_timeout are server-side socket budgets per
        # packet read/write; without them StarRocks closes connections that stall
        # mid-batch even if query_timeout is generous.
        #
        # max_allowed_packet: StarRocks defaults to 4 MB which is too small for
        # wide-table multi-row INSERTs (e.g. tpcds_obt has 518 cols; 400 rows ×
        # 518 cols × ~20 bytes/value ≈ 4 MB - right at the limit).  64 MB gives
        # wide tables plenty of headroom.
        cursor = connection.cursor()
        try:
            cursor.execute("SET query_timeout = 86400")
            cursor.execute("SET SESSION net_read_timeout = 86400")
            cursor.execute("SET SESSION net_write_timeout = 86400")
            cursor.execute("SET SESSION max_allowed_packet = 67108864")
        except Exception:
            pass
        finally:
            cursor.close()

        loader = DataLoader(
            adapter=self,
            benchmark=benchmark,
            connection=connection,
            data_dir=data_dir,
            handler_factory=starrocks_handler_factory,
            tuning_config=self.unified_tuning_configuration if self.tuning_enabled else None,
        )
        table_stats, loading_time = loader.load()
        return table_stats, loading_time, None

    def _get_existing_tables(self, connection) -> list[str]:
        """Get list of existing tables in the StarRocks database."""
        try:
            cursor = connection.cursor()
            try:
                cursor.execute("SHOW TABLES")
                tables = [row[0].lower() for row in cursor.fetchall()]
                return tables
            finally:
                cursor.close()
        except Exception as e:
            self.logger.debug(f"Failed to get existing tables: {e}")
            return []

    # StarRocks / MySQL reserved words that are legal SQL aliases on other
    # platforms (DuckDB, PostgreSQL, SQLite) but require backtick-quoting here.
    # Seeded from the StarRocks and MySQL reserved-word lists with the words
    # most likely to appear as column aliases in benchmark query catalogs.
    _RESERVED_ALIAS_WORDS: frozenset[str] = frozenset(  # noqa: SIM905
        "character rank order group key value values partition range rows select table column columns index database "
        "schema status type default primary unique current_date current_time current_timestamp interval match natural "
        "dense_rank row_number percent_rank cume_dist ntile lead lag".split()  # noqa: SIM905
    )

    _ALIAS_RE = re.compile(r"\bAS\s+(\w+)\b", re.IGNORECASE)

    # ANSI SUBSTRING(expr FROM start FOR length) → MySQL SUBSTRING(expr, start, length).
    # All three groups accept any content that does not contain parentheses, so simple
    # column refs, dotted references, and arithmetic expressions all translate. Nested
    # function calls are rejected by the outer `[^()]` bound - the caller emits a
    # one-shot warning if an untranslated ANSI form slips through.
    _ANSI_SUBSTRING_RE = re.compile(
        r"\bSUBSTRING\s*\(\s*([^()]+?)\s+FROM\s+([^()]+?)\s+FOR\s+([^()]+?)\s*\)",
        re.IGNORECASE,
    )
    # Detects any remaining ANSI SUBSTRING ... FROM ... FOR form (including nested
    # parens the main regex can't describe). Used to emit a translation warning.
    _ANSI_SUBSTRING_DETECT_RE = re.compile(r"\bSUBSTRING\b[^;]*?\bFROM\b[^;]*?\bFOR\b", re.IGNORECASE)

    def _quote_reserved_aliases(self, query: str) -> str:
        """Backtick-quote column aliases that clash with StarRocks reserved words."""

        def replacer(m: re.Match) -> str:
            alias = m.group(1)
            if alias.lower() in self._RESERVED_ALIAS_WORDS:
                return f"AS `{alias}`"
            return m.group(0)

        parts = _split_sql_literals(query)
        return "".join(text if is_lit else self._ALIAS_RE.sub(replacer, text) for text, is_lit in parts)

    def _translate_ansi_substring(self, query: str) -> str:
        """Convert ANSI SUBSTRING(expr FROM n FOR m) to MySQL SUBSTRING(expr, n, m).

        Operates on code segments only (literals are preserved). Warns once per
        process if an ANSI SUBSTRING form remains after translation - that form
        will fail at execute time and the warning points at translation, not the
        server.
        """
        result = _apply_outside_literals(self._ANSI_SUBSTRING_RE, r"SUBSTRING(\1, \2, \3)", query)
        # Detector runs on code segments only so literal strings containing the
        # pattern (e.g. inside an error message or JSON) don't trigger warnings.
        code_only = "".join(text for text, is_lit in _split_sql_literals(result) if not is_lit)
        if self._ANSI_SUBSTRING_DETECT_RE.search(code_only):
            logger.warning(
                "StarRocks SUBSTRING translator left an ANSI 'FROM … FOR' form in the "
                "query; StarRocks will reject it. Query fragment: %s...",
                result[:200].replace("\n", " "),
            )
        return result

    # Keywords that cannot be implicit aliases - when one follows a subquery's closing ),
    # we know no alias was provided and we need to inject one.
    _SQL_KEYWORDS = frozenset(  # noqa: SIM905
        "WHERE HAVING GROUP ORDER LIMIT UNION EXCEPT INTERSECT JOIN INNER LEFT RIGHT FULL CROSS ON AND OR NOT THEN "
        "ELSE END CASE WHEN SELECT FROM AS IS IN NULL TRUE FALSE BETWEEN LIKE ILIKE SIMILAR".split()  # noqa: SIM905
    )

    def _inject_missing_subquery_aliases(self, query: str) -> str:  # noqa: C901
        """Add AS aliases to unaliased FROM subqueries (required by StarRocks / MySQL).

        Standard SQL allows ``FROM (SELECT …)`` and ``FROM t, (SELECT …)``, but
        StarRocks inherits MySQL's rule that every derived table must carry an alias.
        This method does a single left-to-right pass, tracking parenthesis depth to
        locate each closing ``)`` of a FROM-subquery or comma-joined subquery, then
        checks whether an alias immediately follows.  If not, it inserts one.
        Triggers: ``FROM (`` and ``, (`` (which introduce derived tables in FROM).
        """
        out: list[str] = []
        i = 0
        n = len(query)
        counter = 0

        def skip_quoted(pos: int) -> int:
            q = query[pos]
            pos += 1
            while pos < n:
                if query[pos] == "\\" and q != "`":
                    pos += 2
                    continue
                if query[pos] == q:
                    return pos + 1
                pos += 1
            return pos

        def consume_subquery_and_alias(open_paren_pos: int) -> int:
            """Consume from open_paren_pos (inclusive) to closing ), injecting alias if needed.
            Returns position after closing ) (plus any injected alias text)."""
            nonlocal counter
            out.append("(")
            pos = open_paren_pos + 1
            depth = 1
            while pos < n and depth > 0:
                c = query[pos]
                if c in ("'", '"', "`"):
                    j = skip_quoted(pos)
                    out.append(query[pos:j])
                    pos = j
                    continue
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                    if depth == 0:
                        out.append(")")
                        pos += 1
                        break
                out.append(c)
                pos += 1

            # Check what follows the closing )
            j = pos
            while j < n and query[j] in " \t\n\r":
                j += 1
            after_sub = query[j:]

            if re.match(r"^AS\s+", after_sub, re.IGNORECASE):
                return pos  # already aliased

            m_id = re.match(r"^([A-Za-z_`]\w*)", after_sub)
            if m_id:
                word = m_id.group(1).strip("`").upper()
                if word not in self._SQL_KEYWORDS:
                    return pos  # implicit alias

            # Peek inside: only inject if the subquery starts with SELECT/WITH
            # (avoids aliasing IN (...) or function-call parens after commas)
            inner_start = open_paren_pos + 1
            inner_stripped = query[inner_start:].lstrip()
            first_kw = re.match(r"^(SELECT|WITH)\b", inner_stripped, re.IGNORECASE)
            if first_kw:
                out.append(f" AS `_sq{counter}`")
                counter += 1

            return pos

        while i < n:
            ch = query[i]

            if ch in ("'", '"', "`"):
                j = skip_quoted(i)
                out.append(query[i:j])
                i = j
                continue

            # Trigger 1: FROM (
            if ch in ("F", "f") and query[i : i + 4].upper() == "FROM":
                before_ok = i == 0 or not (query[i - 1].isalnum() or query[i - 1] == "_")
                j = i + 4
                after_ok = j >= n or not (query[j].isalnum() or query[j] == "_")
                if before_ok and after_ok:
                    ws_end = j
                    while ws_end < n and query[ws_end] in " \t\n\r":
                        ws_end += 1
                    if ws_end < n and query[ws_end] == "(":
                        out.append(query[i:ws_end])  # FROM + whitespace
                        i = consume_subquery_and_alias(ws_end)
                        continue

            # Trigger 2: , ( - comma-joined derived table
            if ch == ",":
                out.append(",")
                i += 1
                ws_end = i
                while ws_end < n and query[ws_end] in " \t\n\r":
                    ws_end += 1
                if ws_end < n and query[ws_end] == "(":
                    out.append(query[i:ws_end])  # whitespace after comma
                    i = consume_subquery_and_alias(ws_end)
                continue  # always skip fallthrough out.append(ch) + i+=1

            out.append(ch)
            i += 1

        return "".join(out)

    # Matches ANSI double-quoted simple identifiers: "table_name", "column_name", etc.
    # StarRocks uses MySQL mode where double-quotes denote string literals, not identifiers.
    _ANSI_IDENTIFIER_RE = re.compile(r'"([a-zA-Z_][a-zA-Z0-9_]*)"')

    def _translate_ansi_identifiers(self, query: str) -> str:
        """Convert ANSI double-quoted identifiers to MySQL backtick-quoted identifiers.

        Runs only on code segments; anything inside single-quoted string literals
        is passed through unchanged. This protects against silent semantic
        corruption when a literal happens to contain a token that matches the
        identifier shape (e.g. ``'... "active" ...'``).
        """
        return _apply_outside_literals(self._ANSI_IDENTIFIER_RE, r"`\1`", query)

    def execute_query(
        self,
        connection: Any,
        query: str,
        query_id: str,
        benchmark_type: str | None = None,
        scale_factor: float | None = None,
        validate_row_count: bool = True,
        stream_id: int | None = None,
    ) -> dict[str, Any]:
        """Execute query with detailed timing."""
        query = self._quote_reserved_aliases(query)
        query = self._translate_ansi_substring(query)
        query = self._translate_ansi_identifiers(query)
        query = self._inject_missing_subquery_aliases(query)
        result = execute_sql_query(
            connection,
            query,
            query_id,
            log_verbose=self.log_verbose,
            build_query_result_with_validation=self._build_query_result_with_validation,
            benchmark_type=benchmark_type,
            scale_factor=scale_factor,
            validate_row_count=validate_row_count,
            stream_id=stream_id,
        )
        result.setdefault("translated_query", None)
        return result


class StarRocksStreamLoadHandler(FileFormatHandler):
    """Load CSV/TBL data via StarRocks STREAM LOAD HTTP API.

    Each call produces exactly one tablet rowset regardless of data size,
    eliminating the compaction-pressure / expr_children_limit tensions that
    plague INSERT VALUES for large tables.
    """

    def __init__(
        self,
        delimiter: str,
        host: str,
        http_port: int,
        database: str,
        username: str,
        password: str,
        *,
        null_empty_strings: bool = True,
        has_header: bool = False,
    ) -> None:
        self.delimiter = delimiter
        self.host = host
        self.http_port = http_port
        self.database = database
        self.username = username
        self.password = password
        self.null_empty_strings = null_empty_strings
        self.has_header = has_header

    def get_delimiter(self) -> str:
        return self.delimiter

    def load_table(
        self,
        table_name: str,
        file_path: Path,
        connection: Any,
        benchmark: Any,
        logger: Any,
    ) -> int:
        import base64
        import json as _json
        import time as _time

        import requests as _requests

        validate_sql_identifier(table_name, "table name")

        url = f"http://{self.host}:{self.http_port}/api/{self.database}/{table_name}/_stream_load"
        creds = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        headers = {
            "Authorization": f"Basic {creds}",
            "Expect": "100-continue",
            "column_separator": self.delimiter,
            "format": "CSV",
            "max_filter_ratio": "0",
            "strict_mode": "false",
        }
        if self.null_empty_strings:
            # Mark empty/NaN/Inf cells with \N so StarRocks stores NULL.
            headers["null_format"] = "\\N"

        compression_handler = FileFormatRegistry.get_compression_handler(file_path)
        null_markers = frozenset(("nan", "inf", "-inf", "+inf"))

        def _data_stream():
            with compression_handler.open(file_path) as f:
                reader = csv.reader(f, delimiter=self.delimiter)
                if self.has_header:
                    next(reader, None)
                for row in reader:
                    if self.null_empty_strings:
                        row = ["\\N" if (cell == "" or cell.lower() in null_markers) else cell for cell in row]
                    yield (self.delimiter.join(row) + "\n").encode("utf-8")

        # Retry on transient HTTP 5xx, network errors, or BE-unavailable responses.
        # Loads can run for hours; a single TCP reset or BE pause shouldn't kill the
        # whole benchmark. max_filter_ratio=0 stays in force so a restarted load
        # still fails fast on bad rows.
        # BE-unavailable symptom: StarRocks FE returns HTTP 200 with a JSON body
        # whose Message contains ":0" (empty host) when no BE is reachable.
        max_attempts = 3
        last_err: Exception | None = None
        resp: Any = None
        for attempt in range(1, max_attempts + 1):
            try:
                resp = _requests.put(url, headers=headers, data=_data_stream(), timeout=7200)
                if resp.status_code in (200, 307):
                    # Check for BE-unavailable error in a successful HTTP response
                    # before breaking so we can retry instead of silently failing.
                    try:
                        body = _json.loads(resp.text)
                        msg = body.get("Message", "")
                        if ":0" in msg and attempt < max_attempts:
                            logger.warning(
                                "STREAM LOAD BE unavailable for %s (attempt %d/%d, msg=%r); retrying",
                                table_name,
                                attempt,
                                max_attempts,
                                msg,
                            )
                            _time.sleep(10 * attempt)
                            continue
                    except Exception:
                        pass
                    break
                # 5xx → retriable
                if 500 <= resp.status_code < 600 and attempt < max_attempts:
                    logger.warning(
                        "STREAM LOAD HTTP %s for %s (attempt %d/%d); retrying",
                        resp.status_code,
                        table_name,
                        attempt,
                        max_attempts,
                    )
                    _time.sleep(5 * attempt)
                    continue
                raise RuntimeError(f"STREAM LOAD HTTP {resp.status_code} for {table_name}: {resp.text[:500]}")
            except _requests.ConnectionError as e:
                last_err = e
                if attempt < max_attempts:
                    logger.warning(
                        "STREAM LOAD connection error for %s (attempt %d/%d): %s; retrying",
                        table_name,
                        attempt,
                        max_attempts,
                        e,
                    )
                    _time.sleep(5 * attempt)
                    continue
                raise RuntimeError(f"STREAM LOAD connection error for {table_name}: {e}") from e
        else:  # loop exited without break - only possible when last attempt raised
            raise RuntimeError(f"STREAM LOAD exhausted retries for {table_name}: {last_err}")

        result = _json.loads(resp.text)
        status = result.get("Status", "")
        if status not in ("Success", "Publish Timeout"):
            raise RuntimeError(f"STREAM LOAD failed for {table_name}: {result.get('Message', result)}")

        return int(result.get("NumberLoadedRows", 0))


class StarRocksCSVHandler(FileFormatHandler):
    """Handle CSV/TBL data loading into StarRocks via INSERT statements."""

    def __init__(self, delimiter: str, *, null_empty_strings: bool = True, has_header: bool = False):
        self.delimiter = delimiter
        # Some benchmarks (e.g. ClickBench) use empty strings as real values
        # for NOT NULL columns; others (TPC-H/DS) use '' to represent NULL.
        self.null_empty_strings = null_empty_strings
        self.has_header = has_header

    def get_delimiter(self) -> str:
        """Get delimiter for this file format."""
        return self.delimiter

    def load_table(self, table_name: str, file_path: Path, connection: Any, benchmark: Any, logger: Any) -> int:
        """Load data from CSV/TBL file into StarRocks table using batch INSERT."""
        validate_sql_identifier(table_name, "table name")

        row_count = 0
        # StarRocks has two competing constraints for INSERT VALUES batches:
        #  1. expr_children_limit (FE config, default 10 000): hard cap on the
        #     number of rows per INSERT statement.  Exceeding it yields
        #     "Getting syntax error … The inserted rows are N exceeded the
        #     maximum limit 10 000".
        #  2. Tablet-version compaction pressure: each INSERT creates one tablet
        #     version; >~1 000 uncommitted versions causes the BE to drop
        #     connections (error 2013).
        # Staying at 9 999 keeps us under the expr_children_limit while still
        # producing far fewer versions than the original 5 000 batch size.
        batch_size = 9_999
        compression_handler = FileFormatRegistry.get_compression_handler(file_path)
        sql: str | None = None

        cursor = connection.cursor()
        try:
            with compression_handler.open(file_path) as f:
                reader = csv.reader(f, delimiter=self.delimiter)
                if self.has_header:
                    next(reader, None)  # discard header row
                batch: list[list] = []

                for row in reader:
                    if self.null_empty_strings:
                        # Convert empty strings and IEEE non-finite representations to
                        # None so StarRocks receives NULL rather than a string that
                        # fails implicit conversion for numeric columns (e.g. nyctaxi
                        # uses 'nan' for missing congestion_surcharge values).
                        batch.append(
                            [
                                None if cell == "" or cell.lower() in ("nan", "inf", "-inf", "+inf") else cell
                                for cell in row
                            ]
                        )
                    else:
                        batch.append(list(row))
                    row_count += 1

                    if sql is None:
                        placeholders = ", ".join(["%s"] * len(row))
                        sql = f"INSERT INTO `{table_name}` VALUES ({placeholders})"

                    if len(batch) >= batch_size:
                        cursor.executemany(sql, batch)
                        batch = []

                if batch and sql:
                    cursor.executemany(sql, batch)

        except Exception as e:
            logger.error(f"Failed to load data from {file_path} into {table_name}: {e}")
            raise
        finally:
            cursor.close()

        return row_count


class StarRocksParquetHandler(FileFormatHandler):
    """Handle Parquet data loading into StarRocks using PyArrow + batch INSERT.

    ParquetFileHandler in the base layer uses '?' placeholders (DuckDB-style)
    and calls connection.executemany() directly.  StarRocks speaks MySQL protocol
    (%s placeholders) and exposes executemany() only on cursors, so we need a
    platform-specific handler.
    """

    def get_delimiter(self) -> str:
        return ""

    def load_table(self, table_name: str, file_path: Path, connection: Any, benchmark: Any, logger: Any) -> int:
        validate_sql_identifier(table_name, "table name")

        try:
            import pyarrow.parquet as pq
        except ImportError as e:
            raise RuntimeError("pyarrow is required to load Parquet files") from e

        pf = pq.ParquetFile(file_path)
        if pf.metadata.num_rows == 0:
            return 0

        schema = pf.schema_arrow
        column_names = schema.names
        validated_cols = [validate_sql_identifier(c, "column name") for c in column_names]
        placeholders = ", ".join(["%s"] * len(validated_cols))
        columns_str = ", ".join(f"`{c}`" for c in validated_cols)
        insert_sql = f"INSERT INTO `{table_name}` ({columns_str}) VALUES ({placeholders})"

        # Scale batch size to keep each multi-row INSERT safely under the
        # max_allowed_packet limit (which we raise to 64 MB in load_data but
        # default is 4 MB).  Fewer, larger batches also reduce the tablet
        # version count, limiting compaction pressure in StarRocks.
        num_cols = len(column_names)
        if num_cols <= 30:
            batch_size = 10_000  # narrow tables (tsbs, tpch_skew)
        elif num_cols <= 100:
            batch_size = 2_000  # medium tables
        else:
            batch_size = 100  # wide tables: 518 cols × 100 rows ≈ 1 MB - safe

        row_count = 0
        cursor = connection.cursor()
        try:
            for batch in pf.iter_batches(batch_size=batch_size):
                # batch.to_pylist() returns list[dict]; convert to list[tuple] in
                # column order for executemany.
                rows = [tuple(row[col] for col in column_names) for row in batch.to_pylist()]
                if rows:
                    cursor.executemany(insert_sql, rows)
                    row_count += len(rows)
        except Exception as e:
            logger.error(f"Failed to load Parquet data from {file_path} into {table_name}: {e}")
            raise
        finally:
            cursor.close()

        return row_count


__all__ = ["StarRocksWorkloadMixin", "StarRocksCSVHandler", "StarRocksParquetHandler"]
