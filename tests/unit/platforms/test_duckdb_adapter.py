"""Tests for DuckDB platform adapter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import contextlib
import tempfile
from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest

from benchbox.platforms.duckdb import DuckDBAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDuckDBAdapter:
    """Test DuckDB platform adapter functionality."""

    def test_initialization_success(self):
        """Test successful adapter initialization."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter(
                database_path="/tmp/test.db",
                memory_limit="2GB",
                thread_limit=4,
                progress_bar=True,
            )
            assert adapter.platform_name == "DuckDB"
            assert adapter.get_target_dialect() == "duckdb"
            assert adapter.database_path == "/tmp/test.db"
            assert adapter.memory_limit == "2GB"
            assert adapter.thread_limit == 4
            assert adapter.enable_progress_bar is True

    def test_initialization_with_defaults(self):
        """Test initialization with default configuration."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()
            assert adapter.database_path == ":memory:"
            assert adapter.memory_limit == "4GB"
            assert adapter.thread_limit is None
            assert adapter.enable_progress_bar is False

    def test_create_external_tables_uses_read_parquet_views(self, tmp_path):
        """External mode should create views over read_parquet() sources."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()

        parquet_path = tmp_path / "lineitem.parquet"
        parquet_path.touch()
        benchmark = Mock()
        benchmark.tables = {"lineitem": parquet_path}
        benchmark.get_table_loading_order.return_value = ["lineitem"]

        executed_sql: list[str] = []
        connection = Mock()

        def _execute(sql, *args, **kwargs):
            executed_sql.append(str(sql))
            result = Mock()
            if str(sql).strip().upper().startswith("SELECT COUNT(*)"):
                result.fetchone.return_value = (17,)
            else:
                result.fetchone.return_value = None
            return result

        connection.execute.side_effect = _execute

        table_stats, _, per_table_timings = adapter.create_external_tables(benchmark, connection, tmp_path)

        assert adapter.supports_external_tables is True
        assert table_stats == {"lineitem": 17}
        assert per_table_timings is None
        assert any("CREATE VIEW lineitem AS SELECT * FROM read_parquet(" in sql for sql in executed_sql)
        assert adapter.external_format == "parquet"

    def test_create_external_tables_uses_delta_scan_for_delta_sources(self, tmp_path):
        """Delta directories should be mapped to delta_scan() views."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()

        delta_table_dir = tmp_path / "lineitem_delta"
        (delta_table_dir / "_delta_log").mkdir(parents=True)

        benchmark = Mock()
        benchmark.tables = {"lineitem": delta_table_dir}
        benchmark.get_table_loading_order.return_value = ["lineitem"]

        executed_sql: list[str] = []
        connection = Mock()

        def _execute(sql, *args, **kwargs):
            executed_sql.append(str(sql))
            result = Mock()
            if str(sql).strip().upper().startswith("SELECT COUNT(*)"):
                result.fetchone.return_value = (9,)
            else:
                result.fetchone.return_value = None
            return result

        connection.execute.side_effect = _execute

        table_stats, _, _ = adapter.create_external_tables(benchmark, connection, tmp_path)

        assert table_stats == {"lineitem": 9}
        assert "INSTALL delta" in executed_sql
        assert "LOAD delta" in executed_sql
        assert any("delta_scan(" in sql for sql in executed_sql)
        assert adapter.external_format == "delta"

    def test_create_external_tables_detects_tbl_format(self, tmp_path):
        """TBL text files should set external_format to 'tbl'."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()

        tbl_path = tmp_path / "lineitem.tbl"
        tbl_path.write_text("1|data|here\n")

        benchmark = Mock()
        benchmark.tables = {"lineitem": tbl_path}
        benchmark.get_table_loading_order.return_value = ["lineitem"]

        executed_sql: list[str] = []
        connection = Mock()

        def _execute(sql, *args, **kwargs):
            executed_sql.append(str(sql))
            result = Mock()
            if str(sql).strip().upper().startswith("SELECT COUNT(*)"):
                result.fetchone.return_value = (5,)
            else:
                result.fetchone.return_value = None
            return result

        connection.execute.side_effect = _execute

        table_stats, _, _ = adapter.create_external_tables(benchmark, connection, tmp_path)

        assert table_stats == {"lineitem": 5}
        assert any("read_csv(" in sql for sql in executed_sql)
        assert adapter.external_format == "tbl"

    def test_create_external_tables_uses_read_vortex_views(self, tmp_path):
        """External mode should create views over read_vortex() sources."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()

        vortex_path = tmp_path / "customer.vortex"
        vortex_path.touch()
        benchmark = Mock()
        benchmark.tables = {"customer": vortex_path}
        benchmark.get_table_loading_order.return_value = ["customer"]

        executed_sql: list[str] = []
        connection = Mock()

        def _execute(sql, *args, **kwargs):
            executed_sql.append(str(sql))
            result = Mock()
            if str(sql).strip().upper().startswith("SELECT COUNT(*)"):
                result.fetchone.return_value = (11,)
            else:
                result.fetchone.return_value = None
            return result

        connection.execute.side_effect = _execute

        table_stats, _, _ = adapter.create_external_tables(benchmark, connection, tmp_path)

        assert table_stats == {"customer": 11}
        assert "INSTALL vortex" in executed_sql
        assert "LOAD vortex" in executed_sql
        assert any("CREATE VIEW customer AS SELECT * FROM read_vortex(" in sql for sql in executed_sql)
        assert adapter.external_format == "vortex"

    def test_create_external_tables_vortex_extension_failure_is_explicit(self, tmp_path):
        """A missing vortex DuckDB extension should raise a clear external-mode error."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()

        vortex_path = tmp_path / "customer.vortex"
        vortex_path.touch()
        benchmark = Mock()
        benchmark.tables = {"customer": vortex_path}
        benchmark.get_table_loading_order.return_value = ["customer"]

        connection = Mock()

        def _execute(sql, *args, **kwargs):
            sql_text = str(sql)
            if sql_text == "INSTALL vortex":
                raise RuntimeError("extension install failed")
            result = Mock()
            result.fetchone.return_value = None
            return result

        connection.execute.side_effect = _execute

        with pytest.raises(RuntimeError, match="requires the DuckDB vortex extension"):
            adapter.create_external_tables(benchmark, connection, tmp_path)

    def test_create_external_tables_vortex_probe_failure_gives_clear_error(self, tmp_path):
        """When read_vortex probe fails, adapter should raise a clear RuntimeError (no repair)."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()

        vortex_path = tmp_path / "customer.vortex"
        vortex_path.touch()
        benchmark = Mock()
        benchmark.tables = {"customer": vortex_path}
        benchmark.get_table_loading_order.return_value = ["customer"]

        connection = Mock()

        def _execute(sql, *args, **kwargs):
            sql_text = str(sql)
            if sql_text.startswith("SELECT * FROM read_vortex(") and "LIMIT 1" in sql_text:
                raise RuntimeError("Invalid Input Error: Expected 2 buffers, got 3")
            result = Mock()
            result.fetchone.return_value = None
            return result

        connection.execute.side_effect = _execute

        with pytest.raises(RuntimeError, match="DuckDB cannot read these Vortex files"):
            adapter.create_external_tables(benchmark, connection, tmp_path)

    def test_from_config_with_output_dir_places_db_under_databases(self, tmp_path):
        """Auto-generated DB path should use a databases/ subdirectory for output_dir."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            config = {
                "benchmark": "tpch",
                "scale_factor": 0.01,
                "output_dir": str(tmp_path / "custom_output"),
            }

            adapter = DuckDBAdapter.from_config(config)
            assert str(tmp_path / "custom_output" / "databases") in adapter.database_path
            assert ".duckdb" in adapter.database_path

    def test_initialization_missing_driver(self):
        """Test initialization when DuckDB driver is not available."""
        with patch("benchbox.platforms.duckdb.duckdb", None):
            with pytest.raises(ImportError, match="DuckDB not installed"):
                DuckDBAdapter()

    @patch("benchbox.platforms.duckdb.load_driver_module")
    def test_initialization_with_runtime_contract_uses_materialized_module(self, mock_load_driver_module):
        """Runtime contract should materialize and bind the requested DuckDB module."""
        mock_duckdb_module = Mock()
        mock_duckdb_module.__version__ = "0.9.2"
        mock_load_driver_module.return_value = mock_duckdb_module

        with patch("benchbox.platforms.duckdb.duckdb", None):
            adapter = DuckDBAdapter(
                driver_package="duckdb",
                driver_version_requested="0.9.2",
                driver_version_resolved="0.9.2",
                driver_runtime_strategy="isolated-site-packages",
                driver_runtime_path="/tmp/isolated-site-packages",
            )

        assert adapter._duckdb_module is mock_duckdb_module
        assert adapter.driver_version_actual == "0.9.2"
        mock_load_driver_module.assert_called_once()

    @patch("benchbox.platforms.duckdb.load_driver_module")
    def test_auto_install_preference_does_not_trigger_purge(self, mock_load_driver_module):
        """driver_auto_install=True without driver_auto_install_used must not trigger module purge.

        Regression test for SIGSEGV caused by conflating user preference flag
        (driver_auto_install) with actual installation state (driver_auto_install_used).
        When the requested version is already installed, auto_install_used is False and
        load_driver_module must receive auto_install_used=False to avoid purging the
        C extension module (which causes a segfault on reimport via dlopen).
        """
        mock_duckdb_module = Mock()
        mock_duckdb_module.__version__ = "1.2.2"
        mock_load_driver_module.return_value = mock_duckdb_module

        with patch("benchbox.platforms.duckdb.duckdb", None):
            DuckDBAdapter(
                driver_package="duckdb",
                driver_version="1.2.2",
                driver_version_resolved="1.2.2",
                driver_runtime_strategy="current-process",
                # User requested auto-install, but version already matched so it wasn't used.
                driver_auto_install=True,
                driver_auto_install_used=False,
            )

        call_kwargs = mock_load_driver_module.call_args
        resolution = call_kwargs.kwargs.get("resolution") or call_kwargs[1].get("resolution")
        assert resolution.auto_install_used is False, (
            "load_driver_module received auto_install_used=True from driver_auto_install preference; "
            "this would trigger _purge_module_tree and SIGSEGV on C extension reimport"
        )

    @patch("benchbox.platforms.duckdb.load_driver_module")
    def test_create_connection_uses_materialized_duckdb_module(self, mock_load_driver_module):
        """Connection creation should use the runtime-bound DuckDB module."""
        mock_connection = Mock()
        mock_duckdb_module = Mock()
        mock_duckdb_module.__version__ = "1.2.2"
        mock_duckdb_module.connect.return_value = mock_connection
        mock_load_driver_module.return_value = mock_duckdb_module

        with patch("benchbox.platforms.duckdb.duckdb", None):
            adapter = DuckDBAdapter(
                database_path=":memory:",
                driver_package="duckdb",
                driver_version_requested="1.2.2",
                driver_version_resolved="1.2.2",
                driver_runtime_strategy="isolated-site-packages",
                driver_runtime_path="/tmp/runtime",
            )

        with patch.object(adapter, "handle_existing_database"):
            connection = adapter.create_connection()

        assert connection == mock_connection
        mock_duckdb_module.connect.assert_called_once_with(":memory:")

    def test_get_database_path(self):
        """Test database path configuration."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter(database_path="/tmp/test.db")

            # Test with override
            path = adapter.get_database_path(database_path="/tmp/override.db")
            assert path == "/tmp/override.db"

            # Test with default
            path = adapter.get_database_path()
            assert path == "/tmp/test.db"

            # Test fallback to memory
            adapter_none = DuckDBAdapter(database_path=None)
            path = adapter_none.get_database_path()
            assert path == ":memory:"

    def test_get_database_path_with_explicit_none_falls_back_to_instance_path(self):
        """Test that explicit None in connection_config falls back to instance path.

        Regression test: When run_config.connection["database_path"] is explicitly
        set to None (which happens when platform_config doesn't include database_path),
        the adapter should fall back to self.database_path instead of ":memory:".
        This ensures database persistence works correctly.
        """
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter(database_path="/tmp/persistent.db")

            # Simulate what happens when run_config.connection has explicit None
            # (this is what the runner passes when platform_config lacks database_path)
            path = adapter.get_database_path(database_path=None)

            # Should fall back to instance path, NOT to ":memory:"
            assert path == "/tmp/persistent.db"
            assert path != ":memory:"

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_create_connection_memory_database(self, mock_duckdb):
        """Test connection creation with memory database."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter(database_path=":memory:", memory_limit="2GB", thread_limit=2)

        # Mock handle_existing_database
        with patch.object(adapter, "handle_existing_database"):
            connection = adapter.create_connection()

        assert connection == mock_connection
        mock_duckdb.connect.assert_called_once_with(":memory:")

        # Check DuckDB settings were applied
        expected_calls = [
            call("SET memory_limit = '2GB'"),
            call("SET threads TO 2"),
            call("SET default_order = 'ASC'"),
        ]
        for expected_call in expected_calls:
            mock_connection.execute.assert_any_call(expected_call.args[0])

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_create_connection_file_database(self, mock_duckdb):
        """Test connection creation with file database."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter(database_path="/tmp/test.db")

        with patch.object(adapter, "handle_existing_database"):
            connection = adapter.create_connection()

        assert connection == mock_connection
        mock_duckdb.connect.assert_called_once_with("/tmp/test.db")

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_create_connection_with_profiling(self, mock_duckdb):
        """Test connection creation with query profiling enabled."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter(show_query_plans=True)

        with patch.object(adapter, "handle_existing_database"):
            adapter.create_connection()

        # Should enable profiling
        mock_connection.execute.assert_any_call("SET enable_profiling = 'query_tree_optimizer'")

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_create_connection_failure(self, mock_duckdb):
        """Test connection creation failure."""
        mock_duckdb.connect.side_effect = Exception("Connection failed")

        adapter = DuckDBAdapter()

        with patch.object(adapter, "handle_existing_database"):
            with pytest.raises(Exception, match="Connection failed"):
                adapter.create_connection()

    @patch("benchbox.platforms.duckdb.load_driver_module")
    def test_create_connection_records_live_runtime_version(self, mock_load_driver_module):
        """Live connection version should be captured as driver_version_actual."""
        mock_connection = Mock()
        version_result = Mock()
        version_result.fetchone.return_value = ("v1.2.2",)
        generic_result = Mock()

        def execute_side_effect(sql, *args, **kwargs):
            if str(sql).strip().upper().startswith("SELECT VERSION()"):
                return version_result
            return generic_result

        mock_connection.execute.side_effect = execute_side_effect

        mock_duckdb_module = Mock()
        mock_duckdb_module.__version__ = "1.2.2"
        mock_duckdb_module.connect.return_value = mock_connection
        mock_load_driver_module.return_value = mock_duckdb_module

        with patch("benchbox.platforms.duckdb.duckdb", None):
            adapter = DuckDBAdapter(
                driver_package="duckdb",
                driver_version_requested="1.2.2",
                driver_version_resolved="1.2.2",
                driver_runtime_strategy="isolated-site-packages",
                driver_runtime_path="/tmp/runtime",
            )

        with patch.object(adapter, "handle_existing_database"):
            adapter.create_connection()

        assert adapter.driver_version_actual == "1.2.2"

    @patch("benchbox.platforms.duckdb.load_driver_module")
    def test_create_connection_raises_on_live_runtime_version_mismatch(self, mock_load_driver_module):
        """Adapter should fail fast if requested version differs from live runtime."""
        mock_connection = Mock()
        version_result = Mock()
        version_result.fetchone.return_value = ("v1.4.3",)
        generic_result = Mock()

        def execute_side_effect(sql, *args, **kwargs):
            if str(sql).strip().upper().startswith("SELECT VERSION()"):
                return version_result
            return generic_result

        mock_connection.execute.side_effect = execute_side_effect

        mock_duckdb_module = Mock()
        mock_duckdb_module.__version__ = "1.2.2"
        mock_duckdb_module.connect.return_value = mock_connection
        mock_load_driver_module.return_value = mock_duckdb_module

        with patch("benchbox.platforms.duckdb.duckdb", None):
            adapter = DuckDBAdapter(
                driver_package="duckdb",
                driver_version_requested="1.2.2",
                driver_version_resolved="1.2.2",
                driver_runtime_strategy="isolated-site-packages",
                driver_runtime_path="/tmp/runtime",
            )

        with patch.object(adapter, "handle_existing_database"):
            with pytest.raises(RuntimeError, match="runtime version mismatch"):
                adapter.create_connection()

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_create_schema_with_constraints(self, mock_duckdb):
        """Test schema creation with centralized constraint configuration."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        mock_benchmark = Mock()
        mock_benchmark.get_create_tables_sql.return_value = """
            CREATE TABLE table1 (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE table2 (id INTEGER, fk_id INTEGER, FOREIGN KEY(fk_id) REFERENCES table1(id));
        """

        adapter = DuckDBAdapter()

        # Mock the effective tuning configuration to return constraint settings
        mock_config = Mock()
        mock_config.primary_keys.enabled = True
        mock_config.foreign_keys.enabled = True

        with patch.object(adapter, "get_effective_tuning_configuration", return_value=mock_config):
            schema_time = adapter.create_schema(mock_benchmark, mock_connection)

        assert isinstance(schema_time, float)
        assert schema_time >= 0

        # Should call get_create_tables_sql with standardized signature
        mock_benchmark.get_create_tables_sql.assert_called_once_with(dialect="duckdb", tuning_config=mock_config)

        # Should execute CREATE TABLE statements
        assert mock_connection.execute.call_count >= 2

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_create_schema_without_constraint_support(self, mock_duckdb):
        """Test schema creation fallback for benchmarks without constraint support."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        mock_benchmark = Mock()

        # Simulate benchmark without new signature support
        def side_effect(*args, **kwargs):
            if "dialect" in kwargs or "tuning_config" in kwargs:
                raise TypeError("unexpected keyword")
            return "CREATE TABLE test (id INTEGER);"

        mock_benchmark.get_create_tables_sql.side_effect = side_effect

        adapter = DuckDBAdapter()

        with patch.object(adapter, "get_effective_tuning_configuration", return_value=None):
            schema_time = adapter.create_schema(mock_benchmark, mock_connection)

            assert isinstance(schema_time, float)
            # Should first try with new signature, then fall back to simple call
            calls = mock_benchmark.get_create_tables_sql.call_args_list
            assert len(calls) == 2
            assert calls[1] == call()  # Fallback call without parameters

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_create_schema_tpcds_foreign_key_removal(self, mock_duckdb):
        """Test TPC-DS schema creation removes foreign key constraints."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        mock_benchmark = Mock()
        mock_benchmark.__class__.__name__ = "TPCDSBenchmark"
        mock_benchmark.get_create_tables_sql.return_value = """
            CREATE TABLE store_sales (
                ss_sold_date_sk INTEGER,
                FOREIGN KEY (ss_sold_date_sk) REFERENCES date_dim (d_date_sk)
            );
        """

        adapter = DuckDBAdapter()

        schema_time = adapter.create_schema(mock_benchmark, mock_connection)

        assert isinstance(schema_time, float)
        # Should execute CREATE TABLE after removing REFERENCES clauses
        mock_connection.execute.assert_called()

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_load_data_with_benchmark_tables(self, mock_duckdb):
        """Test data loading with benchmark tables."""
        mock_connection = Mock()
        # Call sequence for pipe-delimited .tbl: pragma, COUNT before, INSERT, COUNT after
        pragma_r = Mock()
        pragma_r.fetchall.return_value = [("col1",), ("col2",)]
        before_r = Mock()
        before_r.fetchone.return_value = [0]
        insert_r = Mock()
        after_r = Mock()
        after_r.fetchone.return_value = [100]
        mock_connection.execute.side_effect = [pragma_r, before_r, insert_r, after_r]
        mock_duckdb.connect.return_value = mock_connection

        mock_benchmark = Mock()

        # Create temporary test file in the expected location
        import tempfile

        temp_dir = Path(tempfile.mkdtemp())
        temp_path = temp_dir / "test_table.tbl"

        with open(temp_path, "w", encoding="utf-8") as f:
            f.write("1|test1|\n2|test2|\n")

        try:
            mock_benchmark.tables = {"test_table": str(temp_path)}
            # Mock get_table_loading_order method
            mock_benchmark.get_table_loading_order.return_value = ["test_table"]

            adapter = DuckDBAdapter()

            table_stats, load_time, _ = adapter.load_data(mock_benchmark, mock_connection, temp_dir)

            assert isinstance(table_stats, dict)
            assert isinstance(load_time, float)
            assert load_time >= 0
            assert "test_table" in table_stats
            assert table_stats["test_table"] == 100

            # Should execute INSERT INTO with read_csv
            execute_calls = [str(call) for call in mock_connection.execute.call_args_list]
            assert any("INSERT INTO test_table" in call for call in execute_calls)
            assert any("read_csv" in call for call in execute_calls)

        finally:
            import shutil

            shutil.rmtree(temp_dir)

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_load_data_with_parallel_files(self, mock_duckdb):
        """Test data loading with parallel data files."""
        mock_connection = Mock()
        # Call sequence for pipe-delimited .tbl: pragma, COUNT before, INSERT, COUNT after
        pragma_r = Mock()
        pragma_r.fetchall.return_value = [("col1",), ("col2",)]
        before_r = Mock()
        before_r.fetchone.return_value = [0]
        insert_r = Mock()
        after_r = Mock()
        after_r.fetchone.return_value = [200]
        mock_connection.execute.side_effect = [pragma_r, before_r, insert_r, after_r]
        mock_duckdb.connect.return_value = mock_connection

        mock_benchmark = Mock()

        # Create multiple test files for parallel loading
        temp_files = []
        try:
            for i in range(2):
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=f"_1_{i + 1}.tbl", delete=False, encoding="utf-8"
                ) as f:
                    f.write(f"{i + 1}|test{i + 1}|\n{i + 3}|test{i + 3}|\n")
                    temp_files.append(Path(f.name))

            # Rename files to match parallel pattern
            base_name = temp_files[0].stem.split("_")[0]
            parallel_files = []
            for i, temp_file in enumerate(temp_files):
                new_name = temp_file.parent / f"{base_name}_1_{i + 1}.tbl"
                temp_file.rename(new_name)
                parallel_files.append(new_name)

            mock_benchmark.tables = {base_name: str(parallel_files[0])}
            # Mock get_table_loading_order method
            mock_benchmark.get_table_loading_order.return_value = [base_name]

            adapter = DuckDBAdapter()

            table_stats, load_time, _ = adapter.load_data(
                mock_benchmark, mock_connection, Path(parallel_files[0].parent)
            )

            assert isinstance(table_stats, dict)
            assert table_stats[base_name] == 200

            # Should execute INSERT INTO with array syntax for multiple files
            execute_calls = [str(call) for call in mock_connection.execute.call_args_list]
            insert_calls = [call for call in execute_calls if "INSERT INTO" in call]
            assert len(insert_calls) > 0

        finally:
            for file_path in parallel_files:
                with contextlib.suppress(FileNotFoundError):
                    file_path.unlink()

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_load_data_empty_files(self, mock_duckdb):
        """Test data loading with empty files."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        mock_benchmark = Mock()

        # Create empty test file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tbl", delete=False, encoding="utf-8") as f:
            pass  # Empty file
        temp_path = Path(f.name)

        try:
            mock_benchmark.tables = {"empty_table": str(temp_path)}
            # Mock get_table_loading_order method
            mock_benchmark.get_table_loading_order.return_value = ["empty_table"]

            adapter = DuckDBAdapter()

            table_stats, load_time, _ = adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))

            assert table_stats["empty_table"] == 0

        finally:
            temp_path.unlink()

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_load_data_with_sharded_zstd_files(self, mock_duckdb):
        """DuckDB adapter should handle '*.tbl.1.zst' file naming."""
        mock_connection = Mock()
        # Call sequence for pipe-delimited .tbl.1.zst: pragma, COUNT before, INSERT, COUNT after
        pragma_r = Mock()
        pragma_r.fetchall.return_value = [("col1",), ("col2",)]
        before_r = Mock()
        before_r.fetchone.return_value = [0]
        insert_r = Mock()
        after_r = Mock()
        after_r.fetchone.return_value = [123]
        mock_connection.execute.side_effect = [pragma_r, before_r, insert_r, after_r]
        mock_duckdb.connect.return_value = mock_connection

        mock_benchmark = Mock()

        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # Create a dummy sharded zstd file name; actual contents won't be read because
            # connection is mocked and we only validate SQL generation and handler selection
            fpath = tmp / "customer.tbl.1.zst"
            fpath.write_text("1|foo|\n2|bar|\n")  # content won't matter for mocked connection

            mock_benchmark.tables = {"customer": str(fpath)}
            mock_benchmark.get_table_loading_order.return_value = ["customer"]

            adapter = DuckDBAdapter()
            table_stats, _, _ = adapter.load_data(mock_benchmark, mock_connection, tmp)

            assert table_stats["customer"] == 123
            # Ensure SQL used read_csv (DuckDB native path chosen)
            exec_calls = "\n".join(str(c) for c in mock_connection.execute.call_args_list)
            assert "read_csv" in exec_calls

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_configure_for_benchmark_olap(self, mock_duckdb):
        """Test OLAP benchmark configuration."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter()

        adapter.configure_for_benchmark(mock_connection, "olap")

        # Current implementation only applies profiling when show_query_plans is enabled
        # No specific OLAP optimizations are applied by default
        # Only execute calls should be for profiling if enabled
        if adapter.show_query_plans:
            mock_connection.execute.assert_called_with("SET enable_profiling = 'query_tree'")
        else:
            # No execute calls should be made if profiling not enabled
            mock_connection.execute.assert_not_called()

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_configure_for_benchmark_tpcds(self, mock_duckdb):
        """Test TPC-DS specific configuration."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter()

        adapter.configure_for_benchmark(mock_connection, "tpcds")

        # Current implementation only applies profiling when show_query_plans is enabled
        # No specific TPC-DS optimizations are applied by default
        # Only execute calls should be for profiling if enabled
        if adapter.show_query_plans:
            mock_connection.execute.assert_called_with("SET enable_profiling = 'query_tree'")
        else:
            # No execute calls should be made if profiling not enabled
            mock_connection.execute.assert_not_called()

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_configure_for_benchmark_primitives(self, mock_duckdb):
        """Test primitives benchmark configuration."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter(show_query_plans=True)

        adapter.configure_for_benchmark(mock_connection, "read_primitives")

        # Should enable query tree profiling for primitives
        mock_connection.execute.assert_any_call("SET enable_profiling = 'query_tree'")

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_execute_query_success(self, mock_duckdb):
        """Test successful query execution."""
        mock_connection = Mock()
        mock_result = Mock()
        mock_result.fetchall.return_value = [(1, "test"), (2, "test2")]
        mock_connection.execute.return_value = mock_result
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter()

        # Mock display_query_plan_if_enabled
        with patch.object(adapter, "display_query_plan_if_enabled"):
            result = adapter.execute_query(mock_connection, "SELECT * FROM test", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2
        assert result["first_row"] == (1, "test")
        assert isinstance(result["execution_time_seconds"], float)

        mock_connection.execute.assert_called_with("SELECT * FROM test")

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_execute_query_with_profiling(self, mock_duckdb):
        """Test query execution with profiling enabled."""
        mock_connection = Mock()
        mock_result = Mock()
        mock_result.fetchall.return_value = [(1,)]
        mock_connection.execute.return_value = mock_result
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter(show_query_plans=True)

        with patch.object(adapter, "display_query_plan_if_enabled"):
            result = adapter.execute_query(mock_connection, "SELECT 1", "q1")

        assert result["status"] == "SUCCESS"

        # Should enable and disable profiling
        mock_connection.execute.assert_any_call("PRAGMA enable_profiling = 'query_tree'")
        mock_connection.execute.assert_any_call("PRAGMA disable_profiling")

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_execute_query_failure(self, mock_duckdb):
        """Test query execution failure."""
        mock_connection = Mock()

        def mock_execute(query):
            if "INVALID SQL" in query:
                raise Exception("Query failed")
            return Mock()  # For profiling queries

        mock_connection.execute.side_effect = mock_execute
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter(show_query_plans=True)

        with patch.object(adapter, "display_query_plan_if_enabled"):
            result = adapter.execute_query(mock_connection, "INVALID SQL", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "FAILED"
        assert result["rows_returned"] == 0
        assert result["error"] == "Query failed"
        assert result["error_type"] == "Exception"
        assert isinstance(result["execution_time_seconds"], float)

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_show_plans_displays_without_capture(self, mock_duckdb):
        """--show-plans is decoupled from --capture-plans.

        With show_query_plans=True and capture_plans=False the plan is displayed
        to the console but NOT captured into the result bundle, exercising the
        flag decoupling (run.py no longer ties show_query_plans to capture_plans).
        """
        mock_connection = Mock()
        mock_result = Mock()
        mock_result.fetchall.return_value = [(1,)]
        mock_connection.execute.return_value = mock_result
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter(show_query_plans=True, capture_plans=False)

        with (
            patch.object(adapter, "display_query_plan_if_enabled") as mock_display,
            patch.object(adapter, "capture_query_plan") as mock_capture,
        ):
            result = adapter.execute_query(mock_connection, "SELECT 1", "q1")

        assert result["status"] == "SUCCESS"
        # Display fires for show_query_plans=True, capture_plans=False.
        mock_display.assert_called_once()
        # Capture must not run when capture_plans is False.
        mock_capture.assert_not_called()

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_capture_no_display_suppresses_plan_display(self, mock_duckdb):
        """--capture-plans suppresses console display to avoid a double EXPLAIN.

        With capture_plans=True and show_query_plans=False the plan is captured
        into the result bundle but the display call is suppressed (the guard in
        execute_query), so get_query_plan/EXPLAIN runs once, not twice.
        """
        mock_connection = Mock()
        mock_result = Mock()
        mock_result.fetchall.return_value = [(1,)]
        mock_connection.execute.return_value = mock_result
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter(show_query_plans=False, capture_plans=True)

        with (
            patch.object(adapter, "display_query_plan_if_enabled") as mock_display,
            patch.object(adapter, "capture_query_plan", return_value=(None, 0.0)) as mock_capture,
        ):
            result = adapter.execute_query(mock_connection, "SELECT 1", "q1")

        assert result["status"] == "SUCCESS"
        # Display suppressed while capturing (prevents the double-EXPLAIN path).
        mock_display.assert_not_called()
        # Capture runs exactly once.
        mock_capture.assert_called_once()

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_get_query_plan(self, mock_duckdb):
        """Test query plan retrieval via EXPLAIN (ANALYZE, FORMAT JSON) / EXPLAIN (FORMAT JSON)."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        # Default (analyze_plans=True): uses EXPLAIN (ANALYZE, FORMAT JSON)
        json_payload = '{"operator_type": "SEQ_SCAN", "operator_timing": 0.001}'
        mock_connection.execute.return_value.fetchall.return_value = [("explain_key", json_payload)]
        adapter = DuckDBAdapter()
        plan = adapter.get_query_plan(mock_connection, "SELECT * FROM test")
        assert plan == json_payload
        call_sql = mock_connection.execute.call_args[0][0]
        assert "ANALYZE" in call_sql
        assert "FORMAT JSON" in call_sql

        # analyze_plans=False: uses EXPLAIN (FORMAT JSON) - estimated plan only
        mock_connection.execute.reset_mock()
        estimated_payload = '{"name": "SEQ_SCAN", "timing": null}'
        mock_connection.execute.return_value.fetchall.return_value = [("explain_key", estimated_payload)]
        adapter_no_analyze = DuckDBAdapter(analyze_plans=False)
        plan = adapter_no_analyze.get_query_plan(mock_connection, "SELECT * FROM test")
        assert plan == estimated_payload
        call_sql = mock_connection.execute.call_args[0][0]
        assert "ANALYZE" not in call_sql
        assert "FORMAT JSON" in call_sql

        # Exception during EXPLAIN → returns None
        mock_connection.execute.side_effect = Exception("explain failed")
        plan = adapter.get_query_plan(mock_connection, "SELECT * FROM test")
        assert plan is None

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_get_platform_metadata(self, mock_duckdb):
        """Test platform metadata collection."""
        mock_connection = Mock()
        mock_connection.execute.return_value.fetchall.side_effect = [
            [("memory_limit", "4GB"), ("threads", "4")],  # Settings
            [("test.db", "1MB", "2024-01-01")],  # Database size
        ]
        mock_duckdb.__version__ = "0.9.2"
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter()

        metadata = adapter._get_platform_metadata(mock_connection)

        assert metadata["platform"] == "DuckDB"
        assert metadata["duckdb_version"] == "0.9.2"
        assert "settings" in metadata
        assert "database_size" in metadata

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_get_platform_info_prefers_live_connection_version(self, mock_duckdb):
        """Platform info should prefer live connection runtime version when available."""
        mock_connection = Mock()
        version_result = Mock()
        version_result.fetchone.return_value = ("v0.9.2",)
        mock_connection.execute.return_value = version_result
        mock_duckdb.__version__ = "1.4.3"

        adapter = DuckDBAdapter()
        info = adapter.get_platform_info(connection=mock_connection)

        assert info["client_library_version"] == "1.4.3"
        assert info["platform_version"] == "0.9.2"
        assert info["driver_version_actual"] == "0.9.2"

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_analyze_tables(self, mock_duckdb):
        """Test table analysis for query optimization."""
        mock_connection = Mock()
        mock_connection.execute.return_value.fetchall.return_value = [
            ("table1",),
            ("table2",),
        ]
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter()

        adapter.analyze_tables(mock_connection)

        # Should query tables and run ANALYZE on each
        mock_connection.execute.assert_any_call("ANALYZE table1")
        mock_connection.execute.assert_any_call("ANALYZE table2")

    def test_supports_tuning_type(self):
        """Test tuning type support checking."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()

            # Mock TuningType
            with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
                mock_tuning_type.SORTING = "sorting"
                mock_tuning_type.PARTITIONING = "partitioning"
                mock_tuning_type.CLUSTERING = "clustering"

                assert adapter.supports_tuning_type(mock_tuning_type.SORTING) is True
                assert adapter.supports_tuning_type(mock_tuning_type.PARTITIONING) is True
                assert adapter.supports_tuning_type(mock_tuning_type.CLUSTERING) is False

    def test_generate_tuning_clause(self):
        """Test tuning clause generation (limited support in DuckDB)."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()

            mock_table_tuning = Mock()

            # DuckDB doesn't have explicit CREATE TABLE tuning clauses
            clause = adapter.generate_tuning_clause(mock_table_tuning)
            assert clause == ""

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_apply_table_tunings_with_sorting(self, mock_duckdb):
        """Test applying table tunings with sorting."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter()

        # Mock table tuning
        mock_tuning = Mock()
        mock_tuning.has_any_tuning.return_value = True

        # Mock sorting column
        mock_column = Mock()
        mock_column.name = "sort_key"
        mock_column.order = 1

        with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
            mock_tuning_type.SORTING = "sorting"
            mock_tuning_type.CLUSTERING = "clustering"
            mock_tuning_type.PARTITIONING = "partitioning"
            mock_tuning_type.DISTRIBUTION = "distribution"

            def mock_get_columns_by_type(tuning_type):
                if tuning_type == mock_tuning_type.SORTING:
                    return [mock_column]
                return []

            mock_tuning.get_columns_by_type.side_effect = mock_get_columns_by_type

            adapter.apply_table_tunings("test_table", mock_tuning, mock_connection)

            # Should create index for sorting optimization
            execute_calls = [str(call) for call in mock_connection.execute.call_args_list]
            assert any("CREATE INDEX" in call and "sort" in call for call in execute_calls)

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_apply_table_tunings_with_clustering(self, mock_duckdb):
        """Test applying table tunings with clustering."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter()

        # Mock table tuning with clustering
        mock_tuning = Mock()
        mock_tuning.has_any_tuning.return_value = True

        mock_column = Mock()
        mock_column.name = "cluster_key"
        mock_column.order = 1

        with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
            mock_tuning_type.SORTING = "sorting"
            mock_tuning_type.CLUSTERING = "clustering"
            mock_tuning_type.PARTITIONING = "partitioning"
            mock_tuning_type.DISTRIBUTION = "distribution"

            def mock_get_columns_by_type(tuning_type):
                if tuning_type == mock_tuning_type.CLUSTERING:
                    return [mock_column]
                return []

            mock_tuning.get_columns_by_type.side_effect = mock_get_columns_by_type

            adapter.apply_table_tunings("test_table", mock_tuning, mock_connection)

            # Should create cluster index
            execute_calls = [str(call) for call in mock_connection.execute.call_args_list]
            assert any("CREATE INDEX" in call and "cluster" in call for call in execute_calls)

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_apply_unified_tuning(self, mock_duckdb):
        """Test unified tuning configuration application."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter()

        # Mock unified tuning config
        mock_config = Mock()
        mock_config.table_tunings = {"test_table": Mock()}

        with patch.object(adapter, "apply_table_tunings"):
            with patch.object(adapter, "apply_platform_optimizations"):
                adapter.apply_unified_tuning(mock_config, mock_connection)

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_apply_platform_optimizations(self, mock_duckdb):
        """Test platform optimizations application."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter()

        # Mock tuning config
        mock_config = Mock()
        mock_config.platform_optimizations = Mock()
        mock_config.table_tunings = {}

        # Should not raise exception
        adapter.apply_platform_optimizations(mock_config, mock_connection)

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_apply_constraint_configuration(self, mock_duckdb):
        """Test constraint configuration application."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter()

        # Mock tuning config
        mock_config = Mock()
        mock_config.primary_keys = Mock()
        mock_config.primary_keys.enabled = True
        mock_config.foreign_keys = Mock()
        mock_config.foreign_keys.enabled = False
        mock_config.unique_constraints = Mock()
        mock_config.unique_constraints.enabled = True
        mock_config.check_constraints = Mock()
        mock_config.check_constraints.enabled = False

        # Should not raise exception
        adapter.apply_constraint_configuration(mock_config, "test_table", mock_connection)

    def test_run_power_test(self):
        """Test power test execution without TPC method."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()
            mock_benchmark = Mock()

            # Mock benchmark without run_power_test method
            del mock_benchmark.run_power_test

            # Mock run_benchmark method
            class MockResult:
                def __init__(self):
                    self.status = "SUCCESS"
                    self.power_score = 100.0

                @property
                def __dict__(self):
                    return {"status": "SUCCESS", "power_score": 100.0}

            mock_result = MockResult()

            with patch.object(adapter, "run_benchmark") as mock_run:
                mock_run.return_value = mock_result

                result = adapter.run_power_test(mock_benchmark)

                assert result == {"status": "SUCCESS", "power_score": 100.0}
                mock_run.assert_called_once_with(mock_benchmark)

    def test_run_throughput_test(self):
        """Test throughput test execution without TPC method."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()
            mock_benchmark = Mock()

            # Mock benchmark without run_throughput_test method
            del mock_benchmark.run_throughput_test

            # Mock run_power_test method
            with patch.object(adapter, "run_power_test") as mock_power:
                mock_power.return_value = {"status": "SUCCESS"}

                result = adapter.run_throughput_test(mock_benchmark)

                assert result == {"status": "SUCCESS"}
                mock_power.assert_called_once_with(mock_benchmark)

    def test_run_maintenance_test_fallback(self):
        """Test maintenance test fallback when benchmark has no TPC maintenance method."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()
            mock_benchmark = Mock()

            # Mock benchmark without maintenance test method (triggers fallback)
            del mock_benchmark.run_maintenance_test

            # Mock run_benchmark method for fallback
            class MockResult:
                def __init__(self):
                    self.status = "SUCCESS"

                @property
                def __dict__(self):
                    return {"status": "SUCCESS"}

            mock_result = MockResult()

            with patch.object(adapter, "run_benchmark") as mock_run:
                mock_run.return_value = mock_result

                result = adapter.run_maintenance_test(mock_benchmark)

                assert result == {"status": "SUCCESS"}
                mock_run.assert_called_once_with(mock_benchmark)

    def test_get_target_dialect(self):
        """Test target dialect retrieval."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()

            dialect = adapter.get_target_dialect()
            assert dialect == "duckdb"

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_connection_optimization_settings(self, mock_duckdb):
        """Test that connection optimization settings are properly applied."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter(memory_limit="8GB", thread_limit=8, progress_bar=True)

        with patch.object(adapter, "handle_existing_database"):
            adapter.create_connection()

        # Verify optimization settings were applied
        expected_calls = [
            call("SET memory_limit = '8GB'"),
            call("SET threads TO 8"),
            call("SET enable_progress_bar = true"),
            call("SET default_order = 'ASC'"),
        ]

        for expected_call in expected_calls:
            mock_connection.execute.assert_any_call(expected_call.args[0])

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_table_loading_order(self, mock_duckdb):
        """Test table loading order optimization."""
        mock_connection = Mock()
        mock_connection.execute.return_value.fetchone.return_value = [50]
        mock_duckdb.connect.return_value = mock_connection

        mock_benchmark = Mock()
        # Mock get_table_loading_order method
        mock_benchmark.get_table_loading_order.return_value = ["table2", "table1"]

        # Create test files
        temp_files = {}
        try:
            for table in ["table1", "table2"]:
                with tempfile.NamedTemporaryFile(mode="w", suffix=".tbl", delete=False, encoding="utf-8") as f:
                    f.write("1|test|\n")
                    temp_files[table] = str(Path(f.name))

            mock_benchmark.tables = temp_files

            adapter = DuckDBAdapter()

            table_stats, load_time, _ = adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))

            # Should respect loading order from benchmark
            mock_benchmark.get_table_loading_order.assert_called_once()
            assert isinstance(table_stats, dict)

        finally:
            for file_path in temp_files.values():
                with contextlib.suppress(FileNotFoundError):
                    Path(file_path).unlink()

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_load_data_error_handling(self, mock_duckdb):
        """Test data loading error handling."""
        mock_connection = Mock()
        mock_connection.execute.side_effect = Exception("Load failed")
        mock_duckdb.connect.return_value = mock_connection

        mock_benchmark = Mock()

        # Create test file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tbl", delete=False, encoding="utf-8") as f:
            f.write("1|test|\n")
            temp_path = Path(f.name)

        try:
            mock_benchmark.tables = {"error_table": str(temp_path)}
            # Mock get_table_loading_order method
            mock_benchmark.get_table_loading_order.return_value = ["error_table"]

            adapter = DuckDBAdapter()

            table_stats, load_time, _ = adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))

            # Should handle error gracefully
            assert table_stats["error_table"] == 0
            assert isinstance(load_time, float)

        finally:
            temp_path.unlink()

    def test_run_power_test_with_connection_parameter(self):
        """Test power test execution with connection parameter in kwargs."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()
            mock_benchmark = Mock()
            mock_connection = Mock()

            # Mock benchmark that doesn't have run_power_test method
            del mock_benchmark.run_power_test

            # Mock run_benchmark method
            class MockResult:
                def __init__(self):
                    self.status = "SUCCESS"
                    self.power_score = 100.0

                @property
                def __dict__(self):
                    return {"status": "SUCCESS", "power_score": 100.0}

            mock_result = MockResult()

            with patch.object(adapter, "run_benchmark") as mock_run:
                mock_run.return_value = mock_result

                # Should not raise "multiple values for keyword argument 'connection'"
                result = adapter.run_power_test(mock_benchmark, connection=mock_connection, other_param="value")

                assert result == {"status": "SUCCESS", "power_score": 100.0}
                mock_run.assert_called_once_with(mock_benchmark, connection=mock_connection, other_param="value")

    def test_run_throughput_test_with_connection_parameter(self):
        """Test throughput test execution with connection parameter handling."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()
            mock_benchmark = Mock()
            mock_connection = Mock()

            # Mock benchmark without throughput test method (falls back to power test)
            del mock_benchmark.run_throughput_test

            with patch.object(adapter, "run_power_test") as mock_power:
                mock_power.return_value = {"status": "SUCCESS"}

                # Should not raise "multiple values for keyword argument 'connection'"
                result = adapter.run_throughput_test(mock_benchmark, connection=mock_connection, stream_count=4)

                assert result == {"status": "SUCCESS"}
                # Should pass all parameters to run_power_test
                mock_power.assert_called_once_with(mock_benchmark, connection=mock_connection, stream_count=4)

    def test_run_maintenance_test_with_connection_parameter(self):
        """Test maintenance test execution with connection parameter handling."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()
            mock_benchmark = Mock()
            mock_connection = Mock()

            # Mock benchmark without maintenance test method
            del mock_benchmark.run_maintenance_test

            # Mock run_benchmark method
            class MockResult:
                def __init__(self):
                    self.status = "SUCCESS"

                @property
                def __dict__(self):
                    return {"status": "SUCCESS"}

            mock_result = MockResult()

            with patch.object(adapter, "run_benchmark") as mock_run:
                mock_run.return_value = mock_result

                result = adapter.run_maintenance_test(
                    mock_benchmark,
                    connection=mock_connection,
                    maintenance_type="update",
                )

                assert result == {"status": "SUCCESS"}
                mock_run.assert_called_once_with(
                    mock_benchmark,
                    connection=mock_connection,
                    maintenance_type="update",
                )

    def test_tpcds_power_test_method_availability(self):
        """Test that _execute_tpcds_power_test method is available in DuckDBAdapter."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()

            # This method should be inherited from PlatformAdapter base class
            assert hasattr(adapter, "_execute_tpcds_power_test"), (
                "DuckDBAdapter should inherit _execute_tpcds_power_test method from PlatformAdapter"
            )

            # Method should be callable
            method = adapter._execute_tpcds_power_test
            assert callable(method), "_execute_tpcds_power_test should be callable"

    @patch("benchbox.platforms.duckdb.duckdb")
    def test_tpcds_power_test_execution(self, mock_duckdb):
        """Test that TPC-DS power test can be executed without errors."""
        mock_connection = Mock()
        mock_duckdb.connect.return_value = mock_connection

        adapter = DuckDBAdapter()

        # Create a mock benchmark
        mock_benchmark = Mock()
        mock_benchmark.scale_factor = 0.01  # Very small scale factor for testing

        # Create mock run configuration
        run_config = {
            "scale_factor": 0.01,
            "seed": 1,
            "stream_id": 0,
            "verbose": False,
            "timeout": 30,
        }

        # Mock the TPCDSPowerTest class to avoid full test execution
        with patch("benchbox.core.tpcds.power_test.TPCDSPowerTest") as mock_power_test_class:
            mock_power_test = Mock()
            mock_power_test_class.return_value = mock_power_test

            # Mock the power test result
            mock_result = Mock()
            mock_result.success = True
            mock_result.queries_executed = 99
            mock_result.queries_successful = 99
            mock_result.power_at_size = 100.0
            mock_result.total_time = 10.0
            mock_result.errors = []
            mock_result.query_results = [
                {
                    "query_id": 1,
                    "execution_time_seconds": 0.1,
                    "success": True,
                    "result_count": 1,
                    "stream_id": 0,
                    "position": 0,
                }
            ]
            mock_power_test.run.return_value = mock_result

            # Execute the TPC-DS power test method
            try:
                result = adapter._execute_tpcds_power_test(mock_benchmark, mock_connection, run_config)

                # Verify result structure
                assert isinstance(result, list), "Result should be a list of query results"
                assert len(result) > 0, "Should return at least one query result"

                # Check first result structure
                query_result = result[0]
                required_keys = [
                    "query_id",
                    "execution_time_seconds",
                    "status",
                    "rows_returned",
                    "test_type",
                ]
                for key in required_keys:
                    assert key in query_result, f"Query result should contain '{key}' key"

                assert query_result["test_type"] == "power", "Test type should be 'power'"
                assert query_result["status"] == "SUCCESS", "Status should be 'SUCCESS' for successful queries"

            except AttributeError as e:
                pytest.fail(f"_execute_tpcds_power_test method should be available: {e}")
            except Exception as e:
                pytest.fail(f"_execute_tpcds_power_test should not raise exceptions during normal execution: {e}")

    def test_create_external_tables_uses_iceberg_scan_for_iceberg_sources(self, tmp_path):
        """Iceberg directories (with metadata/) should be mapped to iceberg_scan() views."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()

        iceberg_table_dir = tmp_path / "lineitem_iceberg"
        (iceberg_table_dir / "metadata").mkdir(parents=True)

        benchmark = Mock()
        benchmark.tables = {"lineitem": iceberg_table_dir}
        benchmark.get_table_loading_order.return_value = ["lineitem"]

        executed_sql: list[str] = []
        connection = Mock()

        def _execute(sql, *args, **kwargs):
            executed_sql.append(str(sql))
            result = Mock()
            if str(sql).strip().upper().startswith("SELECT COUNT(*)"):
                result.fetchone.return_value = (42,)
            else:
                result.fetchone.return_value = None
            return result

        connection.execute.side_effect = _execute

        table_stats, _, _ = adapter.create_external_tables(benchmark, connection, tmp_path)

        assert table_stats == {"lineitem": 42}
        assert "INSTALL iceberg" in executed_sql
        assert "LOAD iceberg" in executed_sql
        assert any("iceberg_scan(" in sql for sql in executed_sql)
        assert any("CREATE VIEW lineitem AS SELECT * FROM iceberg_scan(" in sql for sql in executed_sql)
        assert adapter.external_format == "iceberg"

    def test_create_external_tables_iceberg_extension_loaded_once(self, tmp_path):
        """Iceberg extension should only be installed/loaded once for multiple tables."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()

        for name in ("lineitem", "orders"):
            table_dir = tmp_path / f"{name}_iceberg"
            (table_dir / "metadata").mkdir(parents=True)

        benchmark = Mock()
        benchmark.tables = {
            "lineitem": tmp_path / "lineitem_iceberg",
            "orders": tmp_path / "orders_iceberg",
        }
        benchmark.get_table_loading_order.return_value = ["lineitem", "orders"]

        executed_sql: list[str] = []
        connection = Mock()

        def _execute(sql, *args, **kwargs):
            executed_sql.append(str(sql))
            result = Mock()
            if str(sql).strip().upper().startswith("SELECT COUNT(*)"):
                result.fetchone.return_value = (1,)
            else:
                result.fetchone.return_value = None
            return result

        connection.execute.side_effect = _execute

        adapter.create_external_tables(benchmark, connection, tmp_path)

        assert executed_sql.count("INSTALL iceberg") == 1
        assert executed_sql.count("LOAD iceberg") == 1

    def test_create_external_tables_delta_not_confused_with_iceberg(self, tmp_path):
        """A directory with _delta_log/ should use delta_scan, not iceberg_scan."""
        with patch("benchbox.platforms.duckdb.duckdb"):
            adapter = DuckDBAdapter()

        # Directory has _delta_log - should be detected as Delta, not Iceberg
        delta_dir = tmp_path / "lineitem_delta"
        (delta_dir / "_delta_log").mkdir(parents=True)
        (delta_dir / "metadata").mkdir(parents=True)  # Also has metadata/ - Delta wins

        benchmark = Mock()
        benchmark.tables = {"lineitem": delta_dir}
        benchmark.get_table_loading_order.return_value = ["lineitem"]

        executed_sql: list[str] = []
        connection = Mock()

        def _execute(sql, *args, **kwargs):
            executed_sql.append(str(sql))
            result = Mock()
            if str(sql).strip().upper().startswith("SELECT COUNT(*)"):
                result.fetchone.return_value = (1,)
            else:
                result.fetchone.return_value = None
            return result

        connection.execute.side_effect = _execute

        adapter.create_external_tables(benchmark, connection, tmp_path)

        assert any("delta_scan(" in sql for sql in executed_sql)
        assert not any("iceberg_scan(" in sql for sql in executed_sql)
        assert adapter.external_format == "delta"
