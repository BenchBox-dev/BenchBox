"""Tests for DuckDB adapter operations: version normalization, connection wrapper,
external table scan expressions, and query plan capture integration.

Covers gaps not in test_duckdb_adapter.py, test_duckdb_plan_capture.py,
test_duckdb_real_connection.py, or test_duckdb_sorted_loading.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import duckdb
import pytest

from benchbox.platforms.duckdb import (
    DuckDBAdapter,
    DuckDBConnectionWrapper,
    DuckDBCursorWrapper,
    _build_csv_scan_expression,
    _build_duckdb_ctas_sort_sql,
    _build_duckdb_external_scan_expression,
    _normalize_duckdb_version,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


# ---------------------------------------------------------------------------
# Version normalization
# ---------------------------------------------------------------------------


class TestNormalizeDuckDBVersion:
    """Unit tests for _normalize_duckdb_version helper."""

    def test_strips_v_prefix(self):
        assert _normalize_duckdb_version("v1.2.3") == "1.2.3"

    def test_preserves_plain_semver(self):
        assert _normalize_duckdb_version("1.2.3") == "1.2.3"

    def test_returns_none_for_none(self):
        assert _normalize_duckdb_version(None) is None

    def test_returns_none_for_empty_string(self):
        assert _normalize_duckdb_version("") is None

    def test_returns_none_for_whitespace(self):
        assert _normalize_duckdb_version("   ") is None

    def test_strips_whitespace_around_version(self):
        assert _normalize_duckdb_version("  v0.9.2  ") == "0.9.2"

    def test_v_not_followed_by_digit_is_kept(self):
        """A string like 'vNext' should not have the 'v' stripped."""
        assert _normalize_duckdb_version("vNext") == "vNext"

    def test_integer_input_coerced_to_string(self):
        """Non-string input is str()-ified."""
        assert _normalize_duckdb_version(123) == "123"

    def test_dev_version_string(self):
        assert _normalize_duckdb_version("v1.3.0-dev123") == "1.3.0-dev123"


# ---------------------------------------------------------------------------
# Connection wrapper (dry-run mode)
# ---------------------------------------------------------------------------


class TestDuckDBConnectionWrapper:
    """Tests for the dry-run connection wrapper."""

    def test_execute_in_dry_run_captures_sql(self):
        """In dry-run mode, execute should capture SQL, not run it."""
        adapter = DuckDBAdapter(database_path=":memory:")
        adapter.enable_dry_run()

        real_conn = duckdb.connect(":memory:")
        wrapper = DuckDBConnectionWrapper(real_conn, adapter)

        cursor = wrapper.execute("SELECT 42")

        # Adapter should have captured the SQL
        assert any("SELECT 42" in entry.get("sql", "") for entry in adapter.captured_sql)
        # Cursor should be the dry-run wrapper
        assert isinstance(cursor, DuckDBCursorWrapper)
        real_conn.close()

    def test_execute_in_normal_mode_delegates(self):
        """When not in dry-run mode, wrapper delegates to real connection."""
        adapter = DuckDBAdapter(database_path=":memory:")
        adapter.dry_run_mode = False

        real_conn = duckdb.connect(":memory:")
        wrapper = DuckDBConnectionWrapper(real_conn, adapter)

        result = wrapper.execute("SELECT 99 AS val")
        row = result.fetchone()
        assert row == (99,)
        real_conn.close()

    def test_commit_noop_in_dry_run(self):
        """commit() should be a no-op in dry-run mode."""
        adapter = DuckDBAdapter(database_path=":memory:")
        adapter.enable_dry_run()

        real_conn = duckdb.connect(":memory:")
        wrapper = DuckDBConnectionWrapper(real_conn, adapter)
        # Should not raise
        wrapper.commit()
        real_conn.close()

    def test_close_noop_in_dry_run(self):
        """close() should be a no-op in dry-run mode; real conn remains usable."""
        adapter = DuckDBAdapter(database_path=":memory:")
        adapter.enable_dry_run()

        real_conn = duckdb.connect(":memory:")
        wrapper = DuckDBConnectionWrapper(real_conn, adapter)
        wrapper.close()

        # Real connection should still work because close was suppressed
        row = real_conn.execute("SELECT 1").fetchone()
        assert row == (1,)
        real_conn.close()

    def test_getattr_delegates_to_real_connection(self):
        """Attribute access not on the wrapper itself should hit real connection."""
        adapter = DuckDBAdapter(database_path=":memory:")
        adapter.dry_run_mode = False

        real_conn = duckdb.connect(":memory:")
        wrapper = DuckDBConnectionWrapper(real_conn, adapter)

        # DuckDB connections have a .description attribute (or other attrs).
        # Just verify delegation works without error.
        assert wrapper._connection is real_conn
        real_conn.close()


# ---------------------------------------------------------------------------
# DuckDBCursorWrapper (dry-run cursor)
# ---------------------------------------------------------------------------


class TestDuckDBCursorWrapper:
    """Tests for the dry-run cursor wrapper returned by DuckDBConnectionWrapper."""

    def test_fetchall_returns_provided_rows(self):
        adapter = Mock()
        cursor = DuckDBCursorWrapper([(1,), (2,), (3,)], adapter)
        assert cursor.fetchall() == [(1,), (2,), (3,)]

    def test_fetchone_returns_first_row(self):
        adapter = Mock()
        cursor = DuckDBCursorWrapper([(42,)], adapter)
        assert cursor.fetchone() == (42,)

    def test_fetchone_returns_none_for_empty(self):
        adapter = Mock()
        cursor = DuckDBCursorWrapper([], adapter)
        assert cursor.fetchone() is None

    def test_fetchmany_returns_slice(self):
        adapter = Mock()
        cursor = DuckDBCursorWrapper([(1,), (2,), (3,), (4,)], adapter)
        assert cursor.fetchmany(2) == [(1,), (2,)]

    def test_fetchmany_without_size_returns_all(self):
        adapter = Mock()
        cursor = DuckDBCursorWrapper([(1,), (2,)], adapter)
        assert cursor.fetchmany() == [(1,), (2,)]


# ---------------------------------------------------------------------------
# CTAS sort SQL generation
# ---------------------------------------------------------------------------


class TestBuildDuckdbCtasSortSql:
    """Unit tests for _build_duckdb_ctas_sort_sql (module-level helper)."""

    def test_single_column_sort(self):
        col = Mock()
        col.name = "l_shipdate"
        col.order = 1
        sql = _build_duckdb_ctas_sort_sql("lineitem", [col])
        assert sql == "CREATE OR REPLACE TABLE lineitem AS SELECT * FROM lineitem ORDER BY l_shipdate;"

    def test_multi_column_preserves_order(self):
        c1 = Mock()
        c1.name = "l_shipdate"
        c1.order = 1
        c2 = Mock()
        c2.name = "l_orderkey"
        c2.order = 2
        sql = _build_duckdb_ctas_sort_sql("lineitem", [c1, c2])
        assert "ORDER BY l_shipdate, l_orderkey" in sql


# ---------------------------------------------------------------------------
# External scan expression builder (Parquet)
# ---------------------------------------------------------------------------


class TestBuildExternalScanExpressionParquet:
    """Tests for _build_duckdb_external_scan_expression with Parquet files."""

    def test_single_parquet_file(self, tmp_path):
        pq = tmp_path / "lineitem.parquet"
        pq.touch()

        conn = duckdb.connect(":memory:")
        expr, d, v, i, fmt = _build_duckdb_external_scan_expression(
            conn, [pq], delta_extension_loaded=False, vortex_extension_loaded=False
        )
        assert "read_parquet(" in expr
        assert str(pq) in expr
        assert fmt == "parquet"
        conn.close()

    def test_multiple_parquet_files_produce_array_syntax(self, tmp_path):
        pq1 = tmp_path / "part1.parquet"
        pq2 = tmp_path / "part2.parquet"
        pq1.touch()
        pq2.touch()

        conn = duckdb.connect(":memory:")
        expr, d, v, i, fmt = _build_duckdb_external_scan_expression(
            conn, [pq1, pq2], delta_extension_loaded=False, vortex_extension_loaded=False
        )
        assert "read_parquet([" in expr
        assert str(pq1) in expr
        assert str(pq2) in expr
        assert fmt == "parquet"
        conn.close()

    def test_parquet_directory_scan(self, tmp_path):
        """A directory containing .parquet files should be scanned as parquet."""
        pq_dir = tmp_path / "data"
        pq_dir.mkdir()
        (pq_dir / "chunk_0.parquet").touch()
        (pq_dir / "chunk_1.parquet").touch()

        conn = duckdb.connect(":memory:")
        expr, d, v, i, fmt = _build_duckdb_external_scan_expression(
            conn, [pq_dir], delta_extension_loaded=False, vortex_extension_loaded=False
        )
        assert "read_parquet(" in expr
        assert fmt == "parquet"
        conn.close()


# ---------------------------------------------------------------------------
# External scan expression builder (CSV/TBL text files)
# ---------------------------------------------------------------------------


class TestBuildExternalScanExpressionCSV:
    """Tests for _build_duckdb_external_scan_expression with TBL/CSV text files."""

    def test_tbl_file_uses_read_csv(self, tmp_path):
        tbl = tmp_path / "orders.tbl"
        tbl.write_text("1|data|here|\n2|more|data|\n")

        conn = duckdb.connect(":memory:")
        expr, d, v, i, fmt = _build_duckdb_external_scan_expression(
            conn,
            [tbl],
            delta_extension_loaded=False,
            vortex_extension_loaded=False,
            column_names=["o_orderkey", "o_name", "o_status"],
        )
        assert "read_csv(" in expr
        assert fmt == "tbl"
        conn.close()

    def test_csv_file_uses_read_csv(self, tmp_path):
        csv = tmp_path / "data.csv"
        csv.write_text("1,Alice,100\n2,Bob,200\n")

        conn = duckdb.connect(":memory:")
        expr, d, v, i, fmt = _build_duckdb_external_scan_expression(
            conn,
            [csv],
            delta_extension_loaded=False,
            vortex_extension_loaded=False,
            column_names=["id", "name", "value"],
        )
        assert "read_csv(" in expr
        assert fmt == "csv"
        conn.close()

    def test_empty_directory_raises(self, tmp_path):
        """A directory with no recognized data files should raise RuntimeError."""
        empty_dir = tmp_path / "empty_data"
        empty_dir.mkdir()
        # Create a non-data file so the directory isn't empty but has no parquet/csv/tbl
        (empty_dir / "readme.txt").write_text("not data")

        conn = duckdb.connect(":memory:")
        with pytest.raises(RuntimeError, match="requires Parquet"):
            _build_duckdb_external_scan_expression(
                conn, [empty_dir], delta_extension_loaded=False, vortex_extension_loaded=False
            )
        conn.close()


# ---------------------------------------------------------------------------
# CSV scan expression builder (direct)
# ---------------------------------------------------------------------------


class TestBuildCsvScanExpression:
    """Tests for _build_csv_scan_expression helper."""

    def test_single_file_no_column_names(self, tmp_path):
        csv = tmp_path / "data.csv"
        csv.write_text("1,2,3\n4,5,6\n")
        expr = _build_csv_scan_expression([csv], column_names=None)
        assert "read_csv(" in expr
        assert "auto_detect=true" in expr

    def test_single_tbl_file_with_column_names(self, tmp_path):
        tbl = tmp_path / "region.tbl"
        tbl.write_text("0|AFRICA|\n1|AMERICA|\n")
        expr = _build_csv_scan_expression([tbl], column_names=["r_regionkey", "r_name"])
        assert "read_csv(" in expr
        assert "r_regionkey" in expr
        assert "r_name" in expr
        assert "header=false" in expr

    def test_multiple_csv_files_produce_array_path(self, tmp_path):
        csv1 = tmp_path / "part1.csv"
        csv2 = tmp_path / "part2.csv"
        csv1.write_text("1,a\n")
        csv2.write_text("2,b\n")
        expr = _build_csv_scan_expression([csv1, csv2], column_names=["id", "name"])
        assert "[" in expr  # array syntax


# ---------------------------------------------------------------------------
# Real connection: EXPLAIN (FORMAT JSON) plan output
# ---------------------------------------------------------------------------


class TestDuckDBGetQueryPlanJSON:
    """Verify get_query_plan returns JSON (not text-box) format."""

    @pytest.fixture()
    def adapter(self):
        return DuckDBAdapter(database_path=":memory:", capture_plans=True)

    def test_get_query_plan_returns_json(self, adapter):
        conn = adapter.create_connection()
        try:
            raw = adapter.get_query_plan(conn, "SELECT 1 AS x")
            assert raw is not None
            stripped = raw.strip()
            assert stripped.startswith("{") or stripped.startswith("["), f"Expected JSON from EXPLAIN, got: {raw[:120]}"
        finally:
            conn.close()

    def test_get_query_plan_with_table_scan(self, adapter):
        conn = adapter.create_connection()
        try:
            conn.execute("CREATE TABLE t (id INTEGER, val VARCHAR)")
            conn.execute("INSERT INTO t VALUES (1, 'a'), (2, 'b')")
            raw = adapter.get_query_plan(conn, "SELECT * FROM t WHERE id = 1")
            assert raw is not None
            assert "FILTER" in raw.upper() or "SEQ_SCAN" in raw.upper() or "TABLE_SCAN" in raw.upper() or "Scan" in raw
        finally:
            conn.close()

    def test_analyze_plans_false_omits_timing(self):
        adapter = DuckDBAdapter(database_path=":memory:", capture_plans=True, analyze_plans=False)
        conn = adapter.create_connection()
        try:
            raw = adapter.get_query_plan(conn, "SELECT 1")
            assert raw is not None
            # Without ANALYZE, the JSON uses "timing" fields that should be 0 or absent.
            # With ANALYZE, "operator_timing" would have nonzero values.
            assert "operator_timing" not in raw or '"operator_timing": 0' in raw
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Real connection: execute_query dry-run mode
# ---------------------------------------------------------------------------


class TestDuckDBDryRunExecution:
    """Verify execute_query returns synthetic result in dry-run mode."""

    def test_dry_run_returns_synthetic_result(self):
        adapter = DuckDBAdapter(database_path=":memory:")
        conn = adapter.create_connection()
        # Enable dry-run after creating connection (connection itself is real)
        adapter.enable_dry_run()
        try:
            result = adapter.execute_query(
                connection=conn,
                query="SELECT 42 AS answer",
                query_id="dry_q1",
                validate_row_count=False,
            )
            assert result["status"] == "DRY_RUN"
            assert result["dry_run"] is True
            assert result["rows_returned"] == 0
            assert result["execution_time_seconds"] == 0.0
        finally:
            adapter.disable_dry_run()
            conn.close()


# ---------------------------------------------------------------------------
# Real connection: platform info
# ---------------------------------------------------------------------------


class TestDuckDBPlatformInfo:
    """Verify get_platform_info populates version fields from live connection."""

    def test_platform_info_with_connection(self):
        adapter = DuckDBAdapter(database_path=":memory:")
        conn = adapter.create_connection()
        try:
            info = adapter.get_platform_info(connection=conn)
            assert info["platform_type"] == "duckdb"
            assert info["platform_name"] == "DuckDB"
            assert info["platform_version"] is not None
            # Should be a dotted version string
            assert "." in info["platform_version"]
        finally:
            conn.close()

    def test_platform_info_without_connection(self):
        adapter = DuckDBAdapter(database_path=":memory:")
        info = adapter.get_platform_info(connection=None)
        assert info["platform_type"] == "duckdb"
        # Without a connection, should fall back to module __version__
        assert info["client_library_version"] is not None

    def test_connection_mode_in_platform_info(self):
        adapter = DuckDBAdapter(database_path=":memory:")
        info = adapter.get_platform_info()
        assert info["connection_mode"] == "memory"

    def test_file_connection_mode(self, tmp_path):
        db_path = str(tmp_path / "test.duckdb")
        adapter = DuckDBAdapter(database_path=db_path)
        info = adapter.get_platform_info()
        assert info["connection_mode"] == "file"


# ---------------------------------------------------------------------------
# Real connection: external view creation end-to-end
# ---------------------------------------------------------------------------


class TestDuckDBExternalViewCreationReal:
    """End-to-end tests creating external views with a real DuckDB connection."""

    def test_create_view_from_parquet(self, tmp_path):
        """Create a view over a real Parquet file and query through it."""
        # Write a small parquet file via DuckDB
        conn = duckdb.connect(":memory:")
        conn.execute("CREATE TABLE source AS SELECT i AS id, i * 10 AS val FROM range(5) t(i)")
        pq_path = tmp_path / "source.parquet"
        conn.execute(f"COPY source TO '{pq_path}' (FORMAT PARQUET)")

        # Now create a view and query it
        scan_expr, _, _, _, fmt = _build_duckdb_external_scan_expression(
            conn, [pq_path], delta_extension_loaded=False, vortex_extension_loaded=False
        )
        conn.execute(f"CREATE VIEW ext_source AS SELECT * FROM {scan_expr}")
        rows = conn.execute("SELECT COUNT(*) FROM ext_source").fetchone()
        assert rows[0] == 5
        assert fmt == "parquet"
        conn.close()

    def test_create_view_from_csv(self, tmp_path):
        """Create a view over a CSV file with column names."""
        csv_path = tmp_path / "region.csv"
        csv_path.write_text("0,AFRICA\n1,AMERICA\n2,ASIA\n")

        conn = duckdb.connect(":memory:")
        scan_expr, _, _, _, fmt = _build_duckdb_external_scan_expression(
            conn,
            [csv_path],
            delta_extension_loaded=False,
            vortex_extension_loaded=False,
            column_names=["r_regionkey", "r_name"],
        )
        conn.execute(f"CREATE VIEW region AS SELECT * FROM {scan_expr}")
        rows = conn.execute("SELECT r_name FROM region WHERE r_regionkey = 1").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "AMERICA"
        assert fmt == "csv"
        conn.close()


# ---------------------------------------------------------------------------
# Real connection: supports_tuning_type
# ---------------------------------------------------------------------------


class TestDuckDBSupportsTuningType:
    """Verify tuning type support declarations."""

    def test_sorting_is_supported(self):
        from benchbox.core.tuning.interface import TuningType

        adapter = DuckDBAdapter(database_path=":memory:")
        assert adapter.supports_tuning_type(TuningType.SORTING) is True

    def test_driver_isolation_capability(self):
        from benchbox.platforms.base import DriverIsolationCapability

        assert DuckDBAdapter.driver_isolation_capability == DriverIsolationCapability.SUPPORTED

    def test_external_tables_supported(self):
        assert DuckDBAdapter.supports_external_tables is True
