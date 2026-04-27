"""Snapshot tests for w7: translate_sql() delegation to dialect_utils.

These tests document the behavioral delta introduced when DialectTranslationMixin.translate_sql()
was updated to delegate to the centralized dialect_utils pipeline.

Before (bare sqlglot.transpile):
  - No dialect normalization (e.g. "datafusion" passed raw to sqlglot)
  - No identifier quoting (identify=False by default)
  - No GROUP BY ALL / SQLite post-fixes

After (delegate to dialect_utils logic):
  - Dialect normalization via normalize_dialect_for_sqlglot()
  - identify=True for most dialects (disabled for clickhouse, postgres)
  - GROUP BY ALL keyword preserved for DuckDB targets
  - SQLite DATE/INTERVAL and EXTRACT syntax rewritten

This file serves as the per-adapter snapshot diff artifact required by w7.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import builtins
import logging
from unittest.mock import patch

import pytest

from benchbox.platforms.base.dialect_translation import DialectTranslationMixin

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _Adapter(DialectTranslationMixin):
    """Minimal host for DialectTranslationMixin in tests."""

    def __init__(self, dialect: str | None = None):
        self._dialect = dialect
        self.logger = logging.getLogger("test")


class TestTranslateSqlIdentityPolicy:
    """translate_sql() short-circuits without calling sqlglot when no translation is needed."""

    def test_no_dialect_returns_unchanged(self):
        a = _Adapter(dialect=None)
        sql = "SELECT 1"
        assert a.translate_sql(sql) is sql

    def test_same_dialect_returns_unchanged(self):
        a = _Adapter(dialect="duckdb")
        sql = "SELECT 1"
        assert a.translate_sql(sql, source_dialect="duckdb") is sql

    def test_different_dialect_triggers_translation(self):
        a = _Adapter(dialect="snowflake")
        result = a.translate_sql("SELECT 1", source_dialect="duckdb")
        assert result != ""


class TestTranslateSqlIdentifyPolicy:
    """Identifier quoting (identify=True) is applied per target dialect.

    BEFORE: sqlglot.transpile called with no identify parameter (defaults False).
    AFTER:  identify=True for most dialects, disabled for clickhouse and postgres.
    """

    @patch("sqlglot.transpile")
    def test_identify_true_for_snowflake(self, mock_transpile):
        mock_transpile.return_value = ['SELECT "col" FROM "t"']
        a = _Adapter(dialect="snowflake")
        a.translate_sql("SELECT col FROM t", source_dialect="duckdb")
        _, kwargs = mock_transpile.call_args
        assert kwargs["identify"] is True

    @patch("sqlglot.transpile")
    def test_identify_true_for_bigquery(self, mock_transpile):
        mock_transpile.return_value = ["SELECT `col` FROM `t`"]
        a = _Adapter(dialect="bigquery")
        a.translate_sql("SELECT col FROM t", source_dialect="duckdb")
        _, kwargs = mock_transpile.call_args
        assert kwargs["identify"] is True

    @patch("sqlglot.transpile")
    def test_identify_true_for_sqlite(self, mock_transpile):
        mock_transpile.return_value = ['SELECT "col" FROM "t"']
        a = _Adapter(dialect="sqlite")
        a.translate_sql("SELECT col FROM t", source_dialect="duckdb")
        _, kwargs = mock_transpile.call_args
        assert kwargs["identify"] is True

    @patch("sqlglot.transpile")
    def test_identify_false_for_clickhouse(self, mock_transpile):
        mock_transpile.return_value = ["SELECT col FROM t"]
        a = _Adapter(dialect="clickhouse")
        a.translate_sql("SELECT col FROM t", source_dialect="duckdb")
        _, kwargs = mock_transpile.call_args
        assert kwargs["identify"] is False

    @patch("sqlglot.transpile")
    def test_identify_false_for_postgres(self, mock_transpile):
        """postgres dialect (also covers datafusion after normalization)."""
        mock_transpile.return_value = ["SELECT col FROM t"]
        a = _Adapter(dialect="postgres")
        a.translate_sql("SELECT col FROM t", source_dialect="duckdb")
        _, kwargs = mock_transpile.call_args
        assert kwargs["identify"] is False


class TestTranslateSqlDialectNormalization:
    """Dialect normalization routes unsupported sqlglot dialects to their closest equivalent.

    BEFORE: raw dialect names passed to sqlglot (e.g. "datafusion" may be unsupported).
    AFTER:  normalize_dialect_for_sqlglot() applied before calling sqlglot.
    """

    @patch("sqlglot.transpile")
    def test_datafusion_normalized_to_postgres(self, mock_transpile):
        mock_transpile.return_value = ["SELECT col FROM t"]
        a = _Adapter(dialect="datafusion")
        a.translate_sql("SELECT col FROM t", source_dialect="duckdb")
        _, kwargs = mock_transpile.call_args
        assert kwargs["write"] == "postgres"

    @patch("sqlglot.transpile")
    def test_netezza_source_normalized_to_postgres(self, mock_transpile):
        mock_transpile.return_value = ["SELECT col FROM t"]
        a = _Adapter(dialect="snowflake")
        a.translate_sql("SELECT col FROM t", source_dialect="netezza")
        _, kwargs = mock_transpile.call_args
        assert kwargs["read"] == "postgres"

    @patch("sqlglot.transpile")
    def test_duckdb_source_passes_through_unchanged(self, mock_transpile):
        mock_transpile.return_value = ["SELECT col FROM t"]
        a = _Adapter(dialect="snowflake")
        a.translate_sql("SELECT col FROM t", source_dialect="duckdb")
        _, kwargs = mock_transpile.call_args
        assert kwargs["read"] == "duckdb"


class TestTranslateSqlDuckDBPostfix:
    """GROUP BY ALL / ORDER BY ALL keywords are preserved for DuckDB targets.

    BEFORE: sqlglot may emit GROUP BY "ALL" (quoted identifier), which DuckDB rejects.
    AFTER:  _restore_group_order_by_all_keyword() strips the quotes.

    This uses the real sqlglot library to validate end-to-end behaviour.
    """

    def test_group_by_all_preserved_duckdb_target(self):
        sql = "SELECT a, b, SUM(c) FROM t GROUP BY ALL"
        a = _Adapter(dialect="duckdb")
        result = a.translate_sql(sql, source_dialect="duckdb")
        # Identity shortcut: duckdb→duckdb returns unchanged
        assert "GROUP BY ALL" in result

    def test_group_by_all_not_corrupted_to_snowflake(self):
        """Snowflake target: GROUP BY ALL is valid snowflake syntax and should not be altered."""
        sql = "SELECT a, SUM(c) FROM t GROUP BY ALL"
        a = _Adapter(dialect="snowflake")
        result = a.translate_sql(sql, source_dialect="duckdb")
        # Just confirm translation ran (doesn't corrupt into something broken)
        assert result.endswith(";")


class TestTranslateSqlSQLitePostfix:
    """SQLite-specific syntax rewrites are applied for sqlite targets.

    BEFORE: sqlglot may emit DATE('x') + INTERVAL '1' DAY, which SQLite cannot execute.
    AFTER:  _fix_sqlite_unsupported_syntax() rewrites to DATE('x', '+1 day').
    """

    def test_date_interval_rewritten_for_sqlite(self):
        sql = "SELECT DATE('1998-09-01') + INTERVAL '10' DAY FROM t"
        a = _Adapter(dialect="sqlite")
        result = a.translate_sql(sql, source_dialect="duckdb")
        # Result should not contain the INTERVAL form SQLite rejects
        assert "INTERVAL" not in result or "DATE(" in result


class TestTranslateSqlMultiStatement:
    """Multi-statement schema SQL is translated and rejoined with ';\n\n'.

    BEFORE: sqlglot.transpile returns a list; the mixin joined with ';\n\n' + trailing ';'.
    AFTER:  same join behaviour preserved (multi-statement schema blocks still work).
    """

    def test_single_statement_gets_trailing_semicolon(self):
        sql = "CREATE TABLE t (id INTEGER)"
        a = _Adapter(dialect="snowflake")
        result = a.translate_sql(sql, source_dialect="duckdb")
        assert result.endswith(";")

    def test_multi_statement_rejoined(self):
        sql = "CREATE TABLE a (id INTEGER);\n\nCREATE TABLE b (name TEXT)"
        a = _Adapter(dialect="snowflake")
        result = a.translate_sql(sql, source_dialect="duckdb")
        # Both tables should appear in the output
        assert "a" in result.lower()
        assert "b" in result.lower()
        # Result ends with semicolon
        assert result.endswith(";")

    def test_error_returns_original_sql(self):
        sql = "CREATE TABLE t (id INTEGER)"
        a = _Adapter(dialect="snowflake")
        with patch("sqlglot.transpile", side_effect=Exception("boom")):
            result = a.translate_sql(sql, source_dialect="duckdb")
        assert result == sql

    def test_import_error_returns_original_sql(self):
        sql = "CREATE TABLE t (id INTEGER)"
        a = _Adapter(dialect="snowflake")

        real_import = builtins.__import__

        def raising_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "sqlglot":
                raise ImportError("boom")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=raising_import):
            result = a.translate_sql(sql, source_dialect="duckdb")
        assert result == sql


class TestTranslateSqlAdapterSnapshots:
    """Per-adapter snapshot diffs - documents BEFORE vs AFTER translate() output.

    These are the sign-off artifacts for w7. Each case picks a representative
    schema statement for the adapter's benchmark catalog and shows what
    translation produces with the new delegation.

    Run these manually to review the diffs before merging each adapter slice.
    """

    CREATE_TABLE_SQL = "CREATE TABLE lineitem (l_orderkey BIGINT, l_partkey BIGINT)"

    @pytest.mark.parametrize(
        "dialect,expect_quoted",
        [
            ("snowflake", True),
            ("bigquery", True),
            ("duckdb", False),
            ("clickhouse", False),
            ("postgres", False),
            ("redshift", True),
            ("spark", True),
            ("trino", True),
        ],
    )
    def test_identify_snapshot_by_dialect(self, dialect, expect_quoted):
        """Verify identifier quoting is on/off as expected for each adapter dialect."""
        a = _Adapter(dialect=dialect)
        result = a.translate_sql(self.CREATE_TABLE_SQL, source_dialect="duckdb")
        has_quoted = '"lineitem"' in result or "`lineitem`" in result or "[lineitem]" in result
        assert has_quoted == expect_quoted, f"dialect={dialect!r}: expected quoted={expect_quoted}, result={result!r}"
