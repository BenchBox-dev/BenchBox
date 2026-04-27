"""Tests for DataFusion platform adapter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from benchbox.platforms.datafusion import DataFusionAdapter, DataFusionConnectionCompat

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDataFusionAdapter:
    """Test DataFusion platform adapter functionality."""

    def test_initialization_success(self):
        """Test successful adapter initialization."""
        with patch("benchbox.platforms.datafusion.SessionContext"), tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(
                working_dir=tmpdir,
                memory_limit="8G",
                target_partitions=4,
                data_format="parquet",
                batch_size=16384,
            )
            assert adapter.platform_name == "DataFusion"
            assert adapter.get_target_dialect() == "datafusion"
            assert str(adapter.working_dir) == tmpdir
            assert adapter.memory_limit == "8G"
            assert adapter.target_partitions == 4
            assert adapter.data_format == "parquet"
            assert adapter.batch_size == 16384

    def test_initialization_with_defaults(self):
        """Test initialization with default configuration."""
        with patch("benchbox.platforms.datafusion.SessionContext"), tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)
            assert adapter.working_dir == Path(tmpdir)
            assert adapter.memory_limit == "16G"
            assert adapter.target_partitions > 0  # Should default to CPU count
            assert adapter.data_format == "parquet"
            assert adapter.batch_size == 8192

    def test_external_table_capability_declared(self):
        """DataFusion should explicitly declare external table support."""
        with patch("benchbox.platforms.datafusion.SessionContext"), tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)
            assert adapter.supports_external_tables is True

    def test_create_external_tables_delegates_to_load_data(self):
        """External mode should reuse existing load_data implementation."""
        with patch("benchbox.platforms.datafusion.SessionContext"), tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)
            benchmark = Mock()
            connection = Mock()
            expected = ({"customer": 42}, 0.12, {"customer": {"total_ms": 120.0}})

            with patch.object(adapter, "load_data", return_value=expected) as mock_load_data:
                result = adapter.create_external_tables(benchmark, connection, Path(tmpdir))

            assert result == expected
            mock_load_data.assert_called_once_with(benchmark, connection, Path(tmpdir))

    def test_initialization_missing_driver(self):
        """Test initialization when DataFusion driver is not available."""
        with patch("benchbox.platforms.datafusion.SessionContext", None):
            with pytest.raises(ImportError, match="DataFusion not installed"):
                DataFusionAdapter()

    def test_get_platform_info(self):
        """Test platform information retrieval."""
        with patch("benchbox.platforms.datafusion.SessionContext"), tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir, memory_limit="8G")

            # Mock the datafusion module import inside get_platform_info
            mock_df_module = Mock()
            mock_df_module.__version__ = "50.1.0"

            with patch(
                "builtins.__import__",
                side_effect=lambda name, *args: mock_df_module if name == "datafusion" else __import__(name, *args),
            ):
                info = adapter.get_platform_info()

            assert info["platform_type"] == "datafusion"
            assert info["platform_name"] == "DataFusion"
            assert info["connection_mode"] == "in-memory"
            assert info["configuration"]["memory_limit"] == "8G"
            assert info["client_library_version"] == "50.1.0"

    def test_create_connection(self):
        """Test connection creation with SessionContext."""

        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup comprehensive mocking - mock the entire datafusion module
            mock_config = Mock()
            mock_config.with_target_partitions.return_value = mock_config
            mock_config.with_parquet_pruning.return_value = mock_config
            mock_config.with_repartition_joins.return_value = mock_config
            mock_config.with_repartition_aggregations.return_value = mock_config
            mock_config.with_repartition_windows.return_value = mock_config
            mock_config.with_information_schema.return_value = mock_config
            mock_config.with_batch_size.return_value = mock_config
            # Make set() raise an exception to simulate Rust panic - we catch this in the code
            mock_config.set.side_effect = Exception("Config not supported")

            mock_ctx = Mock()

            # Mock RuntimeEnv with build method
            mock_runtime_builder = Mock()
            mock_runtime_builder.build.return_value = Mock()

            with patch("benchbox.platforms.datafusion.SessionConfig", return_value=mock_config):
                with patch("benchbox.platforms.datafusion.SessionContext", return_value=mock_ctx):
                    with patch("benchbox.platforms.datafusion.RuntimeEnv", return_value=mock_runtime_builder):
                        adapter = DataFusionAdapter(
                            working_dir=tmpdir,
                            memory_limit="8G",
                            target_partitions=4,
                            batch_size=16384,
                        )

                        with patch.object(adapter, "handle_existing_database"):
                            connection = adapter.create_connection()

                        assert isinstance(connection, DataFusionConnectionCompat)
                        assert connection._context == mock_ctx

                        # Verify configuration was applied
                        mock_config.with_target_partitions.assert_called_once_with(4)
                        mock_config.with_parquet_pruning.assert_called_once_with(True)
                        mock_config.with_repartition_joins.assert_called_once_with(True)
                        mock_config.with_batch_size.assert_called_once_with(16384)

    def test_parse_memory_limit(self):
        """Test memory limit parsing."""
        with patch("benchbox.platforms.datafusion.SessionContext"), tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)

            # Test GB parsing
            assert adapter._parse_memory_limit("16G") == str(16 * 1024 * 1024 * 1024)
            assert adapter._parse_memory_limit("16GB") == str(16 * 1024 * 1024 * 1024)

            # Test MB parsing
            assert adapter._parse_memory_limit("4096M") == str(4096 * 1024 * 1024)
            assert adapter._parse_memory_limit("4096MB") == str(4096 * 1024 * 1024)

            # Test KB parsing
            assert adapter._parse_memory_limit("1024K") == str(1024 * 1024)
            assert adapter._parse_memory_limit("1024KB") == str(1024 * 1024)

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_create_schema(self, mock_session_context):
        """Test schema creation."""
        mock_benchmark = Mock()
        mock_benchmark.__class__.__name__ = "TPCHBenchmark"
        mock_benchmark.get_schema.return_value = {
            "test": {
                "name": "test",
                "columns": [{"name": "id", "type": "INTEGER"}, {"name": "name", "type": "VARCHAR(100)"}],
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)

            # Mock the constraint configuration
            with patch.object(adapter, "_get_constraint_configuration") as mock_constraints:
                with patch.object(adapter, "_log_constraint_configuration"):
                    mock_constraints.return_value = (False, False)

                    mock_connection = Mock()
                    duration = adapter.create_schema(mock_benchmark, mock_connection)

                    assert duration >= 0
                    assert hasattr(adapter, "_table_schemas")
                    assert isinstance(adapter._table_schemas, dict)
                    assert "test" in adapter._table_schemas
                    assert len(adapter._table_schemas["test"]["columns"]) == 2

    def test_get_benchmark_schema(self):
        """Test getting structured schema from benchmark."""
        with patch("benchbox.platforms.datafusion.SessionContext"), tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)

            # Mock benchmark with get_schema() method
            mock_benchmark = Mock()
            mock_benchmark.get_schema.return_value = {
                "customer": {
                    "name": "customer",
                    "columns": [{"name": "id", "type": "INTEGER"}, {"name": "name", "type": "VARCHAR(100)"}],
                },
                "orders": {
                    "name": "orders",
                    "columns": [{"name": "id", "type": "INTEGER"}, {"name": "customer_id", "type": "INTEGER"}],
                },
            }

            table_schemas = adapter._get_benchmark_schema(mock_benchmark)
            assert len(table_schemas) == 2
            assert "customer" in table_schemas
            assert "orders" in table_schemas
            assert len(table_schemas["customer"]["columns"]) == 2
            assert table_schemas["customer"]["columns"][0]["name"] == "id"

    def test_get_benchmark_schema_fallback(self):
        """Test fallback when benchmark doesn't have get_schema()."""
        with patch("benchbox.platforms.datafusion.SessionContext"), tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)

            # Mock benchmark without get_schema() method
            mock_benchmark = Mock(spec=[])  # Empty spec means no methods
            mock_benchmark.__class__.__name__ = "CustomBenchmark"

            table_schemas = adapter._get_benchmark_schema(mock_benchmark)
            # Should return empty dict when get_schema() is not available
            assert table_schemas == {}

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_load_table_csv(self, mock_session_context):
        """Test loading table from CSV files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test CSV file
            csv_file = Path(tmpdir) / "test.csv"
            csv_file.write_text("1,test\n2,data\n")

            adapter = DataFusionAdapter(working_dir=tmpdir, data_format="csv")

            # Mock connection
            mock_conn = Mock()
            mock_result = Mock()
            mock_batch = Mock()
            mock_batch.column.return_value = [2]  # Row count
            mock_result.collect.return_value = [mock_batch]
            mock_conn.sql.return_value = mock_result

            row_count = adapter._load_table_csv(mock_conn, "test_table", [csv_file], Path(tmpdir))

            assert row_count == 2
            # Verify CREATE EXTERNAL TABLE was called
            assert mock_conn.sql.called

    @patch("benchbox.platforms.datafusion.SessionContext")
    @patch("pyarrow.csv.read_csv")
    @patch("pyarrow.parquet.ParquetWriter")
    def test_load_table_parquet(self, mock_parquet_writer, mock_read_csv, mock_session_context):
        """Test loading table by converting CSV to Parquet."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test CSV file
            csv_file = Path(tmpdir) / "test.csv"
            csv_file.write_text("1,test\n2,data\n")

            adapter = DataFusionAdapter(working_dir=tmpdir, data_format="parquet")

            # Mock PyArrow objects
            mock_table = Mock()
            mock_table.num_rows = 2
            mock_read_csv.return_value = mock_table

            # Mock connection
            mock_conn = Mock()

            row_count = adapter._load_table_parquet(mock_conn, "test_table", [csv_file], Path(tmpdir))

            assert row_count == 2
            # Verify ParquetWriter was opened
            mock_parquet_writer.assert_called_once()
            # Verify table was registered
            mock_conn.register_parquet.assert_called_once()

    def test_is_parquet_file(self):
        """Test Parquet file detection by extension."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("benchbox.platforms.datafusion.SessionContext"):
                adapter = DataFusionAdapter(working_dir=tmpdir)

            assert adapter._is_parquet_file(Path("customer.parquet")) is True
            assert adapter._is_parquet_file(Path("customer.parquet.zst")) is True
            assert adapter._is_parquet_file(Path("customer.parquet.gz")) is True
            assert adapter._is_parquet_file(Path("customer.parquet.lz4")) is True
            assert adapter._is_parquet_file(Path("customer.parquet.snappy")) is True
            assert adapter._is_parquet_file(Path("customer.csv")) is False
            assert adapter._is_parquet_file(Path("customer.tbl")) is False
            assert adapter._is_parquet_file(Path("customer.tbl.zst")) is False

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_load_table_parquet_with_parquet_input(self, mock_session_context):
        """Test that pre-existing Parquet files are registered directly without CSV conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a real Parquet file
            import pyarrow as pa
            import pyarrow.parquet as pq

            parquet_file = Path(tmpdir) / "test_table.parquet"
            table = pa.table({"id": [1, 2, 3], "name": ["a", "b", "c"]})
            pq.write_table(table, parquet_file)

            adapter = DataFusionAdapter(working_dir=tmpdir, data_format="parquet")
            mock_conn = Mock()

            row_count = adapter._load_table_parquet(mock_conn, "test_table", [parquet_file], Path(tmpdir))

            assert row_count == 3
            # Should register directly, not go through CSV conversion
            mock_conn.register_parquet.assert_called_once_with("test_table", str(parquet_file))

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_load_table_parquet_with_multiple_parquet_files(self, mock_session_context):
        """Test that multiple Parquet files are concatenated and registered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import pyarrow as pa
            import pyarrow.parquet as pq

            # Create two Parquet files
            pq.write_table(pa.table({"id": [1, 2]}), Path(tmpdir) / "part1.parquet")
            pq.write_table(pa.table({"id": [3, 4]}), Path(tmpdir) / "part2.parquet")

            working_dir = Path(tmpdir) / "work"
            working_dir.mkdir()
            adapter = DataFusionAdapter(working_dir=str(working_dir), data_format="parquet")
            mock_conn = Mock()

            file_paths = [Path(tmpdir) / "part1.parquet", Path(tmpdir) / "part2.parquet"]
            row_count = adapter._load_table_parquet(mock_conn, "test_table", file_paths, Path(tmpdir))

            assert row_count == 4
            mock_conn.register_parquet.assert_called_once()
            # Should have written a combined file in working_dir
            registered_path = mock_conn.register_parquet.call_args[0][1]
            assert "test_table.parquet" in registered_path

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_load_data_passes_platform_name_to_resolver(self, mock_session_context):
        """Test that load_data passes platform name to DataSourceResolver for correct format selection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir, data_format="parquet")

            mock_benchmark = Mock()
            mock_benchmark.tables = {}

            with patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_resolver_cls:
                mock_resolver = Mock()
                mock_resolver.resolve.return_value = None
                mock_resolver_cls.return_value = mock_resolver

                result = adapter.load_data(mock_benchmark, Mock(), Path(tmpdir))

                # Verify platform_name was passed (lowercase)
                assert mock_resolver_cls.call_args.kwargs.get("platform_name") == "datafusion"
                # When resolver returns None (no data files), load_data returns empty stats
                assert result == ({}, 0.0, None)

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_load_data_uses_mixed_case_table_format_hint(self, mock_session_context):
        """Format hints keyed by either benchmark casing or normalized casing should reach CSV loading."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_file = Path(tmpdir) / "DimCustomer.csv"
            csv_file.write_text("1,test\n")

            adapter = DataFusionAdapter(working_dir=tmpdir, data_format="csv")
            mock_conn = Mock()
            mock_benchmark = Mock()
            for table_formats in ({"DimCustomer": "csv"}, {"dimcustomer": "csv"}):
                mock_data_source = Mock()
                mock_data_source.tables = {"DimCustomer": [csv_file]}
                mock_data_source.table_formats = table_formats

                with (
                    patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_resolver_cls,
                    patch.object(adapter, "_load_table_csv", return_value=1) as mock_load_csv,
                ):
                    mock_resolver = Mock()
                    mock_resolver.resolve.return_value = mock_data_source
                    mock_resolver_cls.return_value = mock_resolver

                    result = adapter.load_data(mock_benchmark, mock_conn, Path(tmpdir))

                assert result[0] == {"dimcustomer": 1}
                assert mock_load_csv.call_args.kwargs["csv_format"] == "csv"

    @patch("benchbox.platforms.datafusion.SessionContext")
    @patch("pyarrow.csv.read_csv")
    @patch("pyarrow.parquet.ParquetWriter")
    def test_load_table_parquet_with_csv_input(self, mock_parquet_writer, mock_read_csv, mock_session_context):
        """Test that CSV files still go through conversion when data_format is parquet."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_file = Path(tmpdir) / "test.csv"
            csv_file.write_text("1,test\n2,data\n")

            adapter = DataFusionAdapter(working_dir=tmpdir, data_format="parquet")

            mock_table = Mock()
            mock_table.num_rows = 2
            mock_read_csv.return_value = mock_table
            mock_conn = Mock()

            row_count = adapter._load_table_parquet(mock_conn, "test_table", [csv_file], Path(tmpdir))

            assert row_count == 2
            # Should have gone through CSV→Parquet conversion
            mock_read_csv.assert_called_once()
            mock_parquet_writer.assert_called_once()
            mock_conn.register_parquet.assert_called_once()

    def test_detect_directory_format_delta(self, tmp_path):
        """Test detection of Delta Lake directory format."""
        delta_dir = tmp_path / "customer"
        delta_dir.mkdir()
        (delta_dir / "_delta_log").mkdir()

        assert DataFusionAdapter._detect_directory_format([delta_dir]) == "delta"

    def test_detect_directory_format_iceberg(self, tmp_path):
        """Test detection of Iceberg directory format."""
        ice_dir = tmp_path / "customer"
        ice_dir.mkdir()
        (ice_dir / "metadata").mkdir()

        assert DataFusionAdapter._detect_directory_format([ice_dir]) == "iceberg"

    def test_detect_directory_format_regular_file(self, tmp_path):
        """Test that regular files are not detected as directory formats."""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("a,b\n1,2\n")

        assert DataFusionAdapter._detect_directory_format([csv_file]) is None

    def test_detect_directory_format_multiple_files(self, tmp_path):
        """Test that multiple files are not detected as directory formats."""
        f1 = tmp_path / "part1.parquet"
        f2 = tmp_path / "part2.parquet"
        f1.touch()
        f2.touch()

        assert DataFusionAdapter._detect_directory_format([f1, f2]) is None

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_load_table_delta(self, mock_session_context, tmp_path):
        """Test loading a Delta Lake table registers record batches."""
        import pyarrow as pa

        adapter = DataFusionAdapter(working_dir=str(tmp_path))
        mock_conn = Mock()

        mock_arrow_table = pa.table({"id": [1, 2, 3], "name": ["a", "b", "c"]})

        with patch("benchbox.platforms.datafusion.DataFusionAdapter._load_table_delta") as original:
            # Test the actual method by calling it with mocked deltalake
            original.side_effect = None  # don't use the side_effect

        # Test via mock
        with patch("deltalake.DeltaTable") as mock_delta_cls:
            mock_delta = Mock()
            mock_delta.to_pyarrow_table.return_value = mock_arrow_table
            mock_delta_cls.return_value = mock_delta

            row_count = adapter._load_table_delta(mock_conn, "customer", tmp_path / "customer")

            assert row_count == 3
            mock_conn.register_record_batches.assert_called_once()
            call_args = mock_conn.register_record_batches.call_args
            assert call_args[0][0] == "customer"

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_load_table_delta_missing_package(self, mock_session_context, tmp_path):
        """Test that missing deltalake package raises clear error."""
        adapter = DataFusionAdapter(working_dir=str(tmp_path))
        mock_conn = Mock()

        with patch.dict("sys.modules", {"deltalake": None}):
            with pytest.raises(RuntimeError, match="deltalake"):
                adapter._load_table_delta(mock_conn, "customer", tmp_path / "customer")

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_execute_query_success(self, mock_session_context):
        """Test successful query execution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)

            # Mock connection and result
            mock_conn = Mock()
            mock_df = Mock()
            mock_batch = Mock()
            mock_batch.num_rows = 10
            mock_batch.num_columns = 2
            mock_batch.column.side_effect = lambda i: [f"value_{i}"]
            mock_df.collect.return_value = [mock_batch]
            mock_conn.sql.return_value = mock_df

            result = adapter.execute_query(
                mock_conn,
                "SELECT * FROM test",
                "query_1",
                benchmark_type="tpch",
                scale_factor=1.0,
                validate_row_count=False,
            )

            assert result["query_id"] == "query_1"
            assert result["status"] == "SUCCESS"
            assert result["rows_returned"] == 10
            assert result["execution_time_seconds"] >= 0

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_execute_query_failure(self, mock_session_context):
        """Test query execution failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)

            # Mock connection to raise error
            mock_conn = Mock()
            mock_conn.sql.side_effect = Exception("Query failed")

            result = adapter.execute_query(
                mock_conn,
                "SELECT * FROM nonexistent",
                "query_1",
            )

            assert result["query_id"] == "query_1"
            assert result["status"] == "FAILED"
            assert "Query failed" in result["error"]

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_execute_query_dry_run(self, mock_session_context):
        """Test query execution in dry-run mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)
            adapter.dry_run_mode = True

            mock_conn = Mock()

            with patch.object(adapter, "capture_sql"):
                result = adapter.execute_query(
                    mock_conn,
                    "SELECT * FROM test",
                    "query_1",
                )

            assert result["query_id"] == "query_1"
            assert result["status"] == "DRY_RUN"
            assert result["dry_run"] is True

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_configure_for_benchmark(self, mock_session_context):
        """Test benchmark-specific configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)

            mock_conn = Mock()
            # Should not raise
            adapter.configure_for_benchmark(mock_conn, "tpch")

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_apply_platform_optimizations(self, mock_session_context):
        """Test platform optimization application."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)

            mock_config = Mock()
            mock_conn = Mock()

            # Should not raise
            adapter.apply_platform_optimizations(mock_config, mock_conn)

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_apply_constraint_configuration(self, mock_session_context):
        """Test constraint configuration application."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)

            mock_pk_config = Mock()
            mock_pk_config.enabled = True
            mock_fk_config = Mock()
            mock_fk_config.enabled = True
            mock_conn = Mock()

            # Should not raise (DataFusion doesn't enforce constraints)
            adapter.apply_constraint_configuration(mock_pk_config, mock_fk_config, mock_conn)

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_check_database_exists(self, mock_session_context):
        """Test database existence checking."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)

            # Should not exist initially (no parquet files)
            assert not adapter.check_database_exists()

            # Create a parquet file in the working directory
            (Path(tmpdir) / "test.parquet").touch()

            # Should exist now
            assert adapter.check_database_exists()

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_drop_database(self, mock_session_context):
        """Test database dropping."""
        with tempfile.TemporaryDirectory() as tmpdir:
            working_dir = Path(tmpdir) / "datafusion_working"
            working_dir.mkdir()
            (working_dir / "test.txt").touch()

            adapter = DataFusionAdapter(working_dir=str(working_dir))

            assert working_dir.exists()
            adapter.drop_database()
            assert not working_dir.exists()

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_connection_compat_execute_fetchall(self, mock_session_context):
        """Test DataFusion compatibility wrapper exposes execute/fetch methods."""
        mock_batch = Mock()
        mock_batch.schema.names = ["a", "b"]
        mock_batch.to_pylist.return_value = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]

        mock_df = Mock()
        mock_df.collect.return_value = [mock_batch]

        mock_ctx = Mock()
        mock_ctx.sql.return_value = mock_df

        compat = DataFusionConnectionCompat(mock_ctx)
        cursor = compat.execute("SELECT * FROM t")
        rows = cursor.fetchall()

        assert rows == [(1, "x"), (2, "y")]
        assert cursor.rowcount == 2

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_connection_compat_execute_is_lazy_for_select(self, mock_session_context):
        """SELECT statements should stay lazy until fetch is requested."""
        mock_batch = Mock()
        mock_batch.schema.names = ["a"]
        mock_batch.to_pylist.return_value = [{"a": 1}]

        mock_df = Mock()
        mock_df.collect.return_value = [mock_batch]

        mock_ctx = Mock()
        mock_ctx.sql.return_value = mock_df

        compat = DataFusionConnectionCompat(mock_ctx)
        cursor = compat.execute("SELECT a FROM t")
        mock_df.collect.assert_not_called()

        assert cursor.fetchall() == [(1,)]
        mock_df.collect.assert_called_once()

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_connection_compat_execute_is_eager_for_insert(self, mock_session_context):
        """INSERT statements should execute immediately for side effects."""
        mock_df = Mock()
        mock_df.collect.return_value = []

        mock_ctx = Mock()
        mock_ctx.sql.return_value = mock_df

        compat = DataFusionConnectionCompat(mock_ctx)
        compat.execute("INSERT INTO t VALUES (1)")

        mock_df.collect.assert_called_once()

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_working_dir_lock_lifecycle(self, mock_session_context):
        """Test working-dir lock supports reentrant acquire/release in one process."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)
            lock_file = adapter._get_working_dir_lock_file()

            assert adapter._acquire_working_dir_lock(timeout_seconds=1)
            assert adapter._acquire_working_dir_lock(timeout_seconds=1)
            assert lock_file.exists()
            adapter._release_working_dir_lock()
            # First release should only decrement reentrant depth.
            assert lock_file.exists()
            adapter._release_working_dir_lock()
            assert not lock_file.exists()

            assert adapter._acquire_working_dir_lock(timeout_seconds=1)
            adapter._release_working_dir_lock()

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_working_dir_lock_reentrant_does_not_warn(self, mock_session_context):
        """Nested acquire in same process should not emit lock-wait warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)
            with patch.object(adapter.logger, "warning") as mock_warning:
                assert adapter._acquire_working_dir_lock(timeout_seconds=1)
                assert adapter._acquire_working_dir_lock(timeout_seconds=1)
                adapter._release_working_dir_lock()
                adapter._release_working_dir_lock()
            assert mock_warning.call_count == 0

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_working_dir_lock_is_owner_safe_across_instances(self, mock_session_context):
        """A second adapter instance in the same process must not steal/release another instance's lock."""
        with tempfile.TemporaryDirectory() as tmpdir:
            owner = DataFusionAdapter(working_dir=tmpdir)
            contender = DataFusionAdapter(working_dir=tmpdir)
            lock_file = owner._get_working_dir_lock_file()

            assert owner._acquire_working_dir_lock(timeout_seconds=1)
            assert lock_file.exists()

            # Same-process contender should reenter process-wide ownership, not rewrite lock ownership.
            assert contender._acquire_working_dir_lock(timeout_seconds=1)
            assert lock_file.exists()

            # Contender release should only decrement depth, not remove owner's lock.
            contender._release_working_dir_lock()
            assert lock_file.exists()

            owner._release_working_dir_lock()
            assert not lock_file.exists()

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_working_dir_lock_recovers_stale_dead_owner(self, mock_session_context):
        """Test stale lock is removed when lock owner PID is no longer running."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)
            lock_file = adapter._get_working_dir_lock_file()
            lock_file.parent.mkdir(parents=True, exist_ok=True)
            lock_file.write_text("pid:999999\ntime:0\n", encoding="utf-8")

            with patch.object(adapter, "_is_pid_running", return_value=False):
                assert adapter._acquire_working_dir_lock(timeout_seconds=1)
            adapter._release_working_dir_lock()

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_working_dir_lock_logs_verbose_on_detection(self, mock_session_context):
        """Test verbose log is emitted immediately when an existing lock is found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)
            lock_file = adapter._get_working_dir_lock_file()
            lock_file.parent.mkdir(parents=True, exist_ok=True)
            lock_file.write_text("pid:123\ntime:0\n", encoding="utf-8")

            with patch.object(adapter, "log_verbose") as mock_verbose:
                with patch.object(adapter, "_is_pid_running", return_value=False):
                    assert adapter._acquire_working_dir_lock(timeout_seconds=1)

            assert any("lock detected" in str(call.args[0]).lower() for call in mock_verbose.call_args_list)
            adapter._release_working_dir_lock()

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_working_dir_lock_logs_warning_when_waiting(self, mock_session_context):
        """Test standard warning log is emitted when waiting on lock."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)
            lock_file = adapter._get_working_dir_lock_file()
            lock_file.parent.mkdir(parents=True, exist_ok=True)
            lock_file.write_text("pid:123\ntime:0\n", encoding="utf-8")

            # Simulate lock owner still alive so we wait, then timeout quickly.
            with patch.object(adapter, "_is_pid_running", return_value=True):
                with patch.object(adapter.logger, "warning") as mock_warning:
                    acquired = adapter._acquire_working_dir_lock(timeout_seconds=0.2)
            assert acquired is False
            assert mock_warning.call_count >= 1
            assert "waiting for release" in str(mock_warning.call_args_list[0].args[0]).lower()

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_validate_platform_capabilities(self, mock_session_context):
        """Test platform capability validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)

            result = adapter.validate_platform_capabilities("tpch")

            assert result.is_valid
            assert len(result.errors) == 0
            # Just verify it doesn't crash and validates successfully when mocked

    @patch("benchbox.platforms.datafusion.SessionContext", None)
    def test_validate_platform_capabilities_missing_driver(self):
        """Test platform validation when driver is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Can't create adapter without driver
            with pytest.raises(ImportError):
                DataFusionAdapter(working_dir=tmpdir)

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_from_config(self, mock_session_context):
        """Test adapter creation from configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "benchmark": "tpch",
                "scale_factor": 1.0,
                "output_dir": tmpdir,
                "memory_limit": "8G",
                "partitions": 8,
                "format": "parquet",
                "batch_size": 16384,
            }

            adapter = DataFusionAdapter.from_config(config)

            assert adapter.memory_limit == "8G"
            assert adapter.target_partitions == 8
            assert adapter.data_format == "parquet"
            assert adapter.batch_size == 16384
            assert str(Path(tmpdir) / "databases") in str(adapter.working_dir)

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_add_cli_arguments(self, mock_session_context):
        """Test CLI argument addition."""
        import argparse

        parser = argparse.ArgumentParser()
        DataFusionAdapter.add_cli_arguments(parser)

        # Verify datafusion arguments were added
        args = parser.parse_args(
            [
                "--datafusion-memory-limit",
                "8G",
                "--datafusion-partitions",
                "4",
                "--datafusion-format",
                "parquet",
            ]
        )

        assert args.datafusion_memory_limit == "8G"
        assert args.datafusion_partitions == 4
        assert args.datafusion_format == "parquet"


class TestDataFusionColumnTypeMapping:
    """Test column type mapping for CSV to Parquet conversion.

    These tests verify that the fix for TPC-DS queries Q8, Q15, Q19, Q45
    correctly maps schema column types to PyArrow types to prevent incorrect
    type inference (e.g., ca_zip being inferred as int64 instead of string).
    """

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_load_table_parquet_with_schema_types(self, mock_session_context):
        """Test that schema types are correctly passed to PyArrow ConvertOptions."""
        import pyarrow as pa

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test CSV file with numeric-looking string data
            csv_file = Path(tmpdir) / "customer_address.csv"
            csv_file.write_text("1|89436|123 Main St\n2|07001|456 Oak Ave\n")

            adapter = DataFusionAdapter(working_dir=tmpdir, data_format="parquet")

            # Set up schema with VARCHAR type for ca_zip
            adapter._table_schemas = {
                "customer_address": {
                    "name": "customer_address",
                    "columns": [
                        {"name": "ca_address_sk", "type": "INTEGER"},
                        {"name": "ca_zip", "type": "CHAR(10)"},
                        {"name": "ca_street", "type": "VARCHAR(60)"},
                    ],
                }
            }

            # Mock PyArrow functions to capture column_types
            captured_convert_options = {}

            def capture_read_csv(file_path, read_options=None, parse_options=None, convert_options=None):
                # Capture the convert_options for verification
                if convert_options:
                    captured_convert_options["column_types"] = convert_options.column_types
                # Return a mock table
                mock_table = Mock()
                mock_table.num_rows = 2
                return mock_table

            mock_conn = Mock()

            with patch("pyarrow.csv.read_csv", side_effect=capture_read_csv):
                with patch("pyarrow.parquet.ParquetWriter"):
                    adapter._load_table_parquet(mock_conn, "customer_address", [csv_file], Path(tmpdir))

            # Verify column types were correctly mapped
            assert "column_types" in captured_convert_options
            col_types = captured_convert_options["column_types"]

            # ca_zip should be string (CHAR type)
            assert "ca_zip" in col_types
            assert col_types["ca_zip"] == pa.string()

            # ca_street should be string (VARCHAR type)
            assert "ca_street" in col_types
            assert col_types["ca_street"] == pa.string()

            # ca_address_sk (INTEGER) is explicitly mapped to int32 to prevent
            # streaming inference errors (all-null early batches → pa.null() type)
            assert "ca_address_sk" in col_types
            assert col_types["ca_address_sk"] == pa.int32()

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_column_type_mapping_char_variants(self, mock_session_context):
        """Test that all CHAR/VARCHAR variants map to PyArrow string."""
        import pyarrow as pa

        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir, data_format="parquet")

            # Test various string type declarations
            adapter._table_schemas = {
                "test_table": {
                    "name": "test_table",
                    "columns": [
                        {"name": "col_char", "type": "CHAR(5)"},
                        {"name": "col_char_no_len", "type": "CHAR"},
                        {"name": "col_varchar", "type": "VARCHAR(100)"},
                        {"name": "col_varchar_no_len", "type": "VARCHAR"},
                        {"name": "col_text", "type": "TEXT"},
                        {"name": "col_string", "type": "STRING"},
                    ],
                }
            }

            captured_types = {}

            def capture_read_csv(file_path, read_options=None, parse_options=None, convert_options=None):
                if convert_options and convert_options.column_types:
                    captured_types.update(convert_options.column_types)
                mock_table = Mock()
                mock_table.num_rows = 1
                return mock_table

            mock_conn = Mock()
            csv_file = Path(tmpdir) / "test.csv"
            csv_file.write_text("a|b|c|d|e|f\n")

            with patch("pyarrow.csv.read_csv", side_effect=capture_read_csv):
                with patch("pyarrow.parquet.ParquetWriter"):
                    adapter._load_table_parquet(mock_conn, "test_table", [csv_file], Path(tmpdir))

            # All string-type columns should map to pa.string()
            for col_name in [
                "col_char",
                "col_char_no_len",
                "col_varchar",
                "col_varchar_no_len",
                "col_text",
                "col_string",
            ]:
                assert col_name in captured_types, f"{col_name} should be in column_types"
                assert captured_types[col_name] == pa.string(), f"{col_name} should be pa.string()"

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_column_type_mapping_date(self, mock_session_context):
        """Test that DATE types map to PyArrow date32."""
        import pyarrow as pa

        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir, data_format="parquet")

            adapter._table_schemas = {
                "test_table": {
                    "name": "test_table",
                    "columns": [
                        {"name": "order_date", "type": "DATE"},
                        {"name": "ship_date", "type": "DATE"},
                    ],
                }
            }

            captured_types = {}

            def capture_read_csv(file_path, read_options=None, parse_options=None, convert_options=None):
                if convert_options and convert_options.column_types:
                    captured_types.update(convert_options.column_types)
                mock_table = Mock()
                mock_table.num_rows = 1
                return mock_table

            mock_conn = Mock()
            csv_file = Path(tmpdir) / "test.csv"
            csv_file.write_text("2024-01-01|2024-01-05\n")

            with patch("pyarrow.csv.read_csv", side_effect=capture_read_csv):
                with patch("pyarrow.parquet.ParquetWriter"):
                    adapter._load_table_parquet(mock_conn, "test_table", [csv_file], Path(tmpdir))

            assert "order_date" in captured_types
            assert captured_types["order_date"] == pa.date32()
            assert "ship_date" in captured_types
            assert captured_types["ship_date"] == pa.date32()

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_column_type_mapping_decimal(self, mock_session_context):
        """Test that DECIMAL types map to PyArrow float64."""
        import pyarrow as pa

        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir, data_format="parquet")

            adapter._table_schemas = {
                "test_table": {
                    "name": "test_table",
                    "columns": [
                        {"name": "price", "type": "DECIMAL(10,2)"},
                        {"name": "tax", "type": "DECIMAL"},
                    ],
                }
            }

            captured_types = {}

            def capture_read_csv(file_path, read_options=None, parse_options=None, convert_options=None):
                if convert_options and convert_options.column_types:
                    captured_types.update(convert_options.column_types)
                mock_table = Mock()
                mock_table.num_rows = 1
                return mock_table

            mock_conn = Mock()
            csv_file = Path(tmpdir) / "test.csv"
            csv_file.write_text("99.99|5.50\n")

            with patch("pyarrow.csv.read_csv", side_effect=capture_read_csv):
                with patch("pyarrow.parquet.ParquetWriter"):
                    adapter._load_table_parquet(mock_conn, "test_table", [csv_file], Path(tmpdir))

            assert "price" in captured_types
            assert captured_types["price"] == pa.float64()
            assert "tax" in captured_types
            assert captured_types["tax"] == pa.float64()

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_column_type_mapping_integer_uses_inference(self, mock_session_context):
        """Test that INTEGER/BIGINT/SMALLINT types are explicitly mapped to prevent streaming inference errors."""
        import pyarrow as pa

        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir, data_format="parquet")

            adapter._table_schemas = {
                "test_table": {
                    "name": "test_table",
                    "columns": [
                        {"name": "id", "type": "INTEGER"},
                        {"name": "quantity", "type": "BIGINT"},
                        {"name": "small_num", "type": "SMALLINT"},
                    ],
                }
            }

            captured_types = {}

            def capture_read_csv(file_path, read_options=None, parse_options=None, convert_options=None):
                if convert_options and convert_options.column_types:
                    captured_types.update(convert_options.column_types)
                mock_table = Mock()
                mock_table.num_rows = 1
                return mock_table

            mock_conn = Mock()
            csv_file = Path(tmpdir) / "test.csv"
            csv_file.write_text("1|100|5\n")

            with patch("pyarrow.csv.read_csv", side_effect=capture_read_csv):
                with patch("pyarrow.parquet.ParquetWriter"):
                    adapter._load_table_parquet(mock_conn, "test_table", [csv_file], Path(tmpdir))

            # Integer types ARE explicitly mapped to prevent streaming inference
            # errors where early all-null batches cause a column to be typed as pa.null()
            assert "id" in captured_types
            assert captured_types["id"] == pa.int32()
            assert "quantity" in captured_types
            assert captured_types["quantity"] == pa.int64()
            assert "small_num" in captured_types
            assert captured_types["small_num"] == pa.int32()

    @patch("benchbox.platforms.datafusion.SessionContext")
    def test_no_schema_uses_no_column_types(self, mock_session_context):
        """Test that missing schema means no explicit column types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir, data_format="parquet")

            # No schema set
            adapter._table_schemas = {}

            captured_types = {"called": False}

            def capture_read_csv(file_path, read_options=None, parse_options=None, convert_options=None):
                captured_types["called"] = True
                if convert_options:
                    captured_types["column_types"] = convert_options.column_types
                mock_table = Mock()
                mock_table.num_rows = 1
                return mock_table

            mock_conn = Mock()
            csv_file = Path(tmpdir) / "test.csv"
            csv_file.write_text("1|test|2024-01-01\n")

            with patch("pyarrow.csv.read_csv", side_effect=capture_read_csv):
                with patch("pyarrow.parquet.ParquetWriter"):
                    adapter._load_table_parquet(mock_conn, "unknown_table", [csv_file], Path(tmpdir))

            assert captured_types["called"]
            # column_types should be None or empty when no schema
            col_types = captured_types.get("column_types")
            assert col_types is None or len(col_types) == 0


# ---------------------------------------------------------------------------
# _detect_csv_format - manifest format hint parameter
# ---------------------------------------------------------------------------
class TestDetectCsvFormatHint:
    """_detect_csv_format uses csv_format hint before falling back to extension."""

    @pytest.fixture()
    def adapter(self):
        with patch("benchbox.platforms.datafusion.SessionContext"), tempfile.TemporaryDirectory() as tmpdir:
            yield DataFusionAdapter(working_dir=tmpdir)

    def test_tbl_hint_returns_pipe(self, adapter):
        assert adapter._detect_csv_format([], csv_format="tbl") == "|"

    def test_csv_hint_returns_comma(self, adapter):
        assert adapter._detect_csv_format([], csv_format="csv") == ","

    def test_none_hint_falls_back_to_extension(self, adapter, tmp_path):
        tbl_file = tmp_path / "data.tbl"
        tbl_file.write_text("1|hello\n")
        delimiter = adapter._detect_csv_format([tbl_file], csv_format=None)
        assert delimiter == "|"

    def test_none_hint_no_files_defaults_comma(self, adapter):
        delimiter = adapter._detect_csv_format([], csv_format=None)
        assert delimiter == ","

    def test_tbl_hint_overrides_csv_extension(self, adapter, tmp_path):
        """A .csv file with tbl format hint should return pipe, not comma."""
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("1,hello\n")
        delimiter = adapter._detect_csv_format([csv_file], csv_format="tbl")
        assert delimiter == "|"

    def test_csv_hint_overrides_tbl_extension(self, adapter, tmp_path):
        """A .tbl file with csv format hint should return comma, not pipe."""
        tbl_file = tmp_path / "data.tbl"
        tbl_file.write_text("1|hello\n")
        delimiter = adapter._detect_csv_format([tbl_file], csv_format="csv")
        assert delimiter == ","


# ---------------------------------------------------------------------------
# _create_empty_schema_tables
# ---------------------------------------------------------------------------
class TestCreateEmptySchema:
    """_create_empty_schema_tables creates DDL from _table_schemas and returns {}."""

    @pytest.fixture()
    def adapter(self):
        with patch("benchbox.platforms.datafusion.SessionContext"), tempfile.TemporaryDirectory() as tmpdir:
            a = DataFusionAdapter(working_dir=tmpdir)
            yield a

    def test_returns_empty_dict(self, adapter):
        adapter._table_schemas = {"orders": {"columns": [{"name": "id", "type": "INTEGER"}]}}
        conn = MagicMock()
        result = adapter._create_empty_schema_tables(conn)
        assert result == {}

    def test_executes_create_table_for_each_schema(self, adapter):
        adapter._table_schemas = {
            "orders": {"columns": [{"name": "id", "type": "INTEGER"}]},
            "customers": {"columns": [{"name": "name", "type": "VARCHAR"}]},
        }
        conn = MagicMock()
        adapter._create_empty_schema_tables(conn)
        assert conn.execute.call_count == 2

    def test_ddl_contains_table_name(self, adapter):
        adapter._table_schemas = {"my_table": {"columns": [{"name": "col", "type": "BIGINT"}]}}
        conn = MagicMock()
        adapter._create_empty_schema_tables(conn)
        ddl = conn.execute.call_args[0][0]
        assert "my_table" in ddl

    def test_ddl_maps_integer_to_int(self, adapter):
        adapter._table_schemas = {"t": {"columns": [{"name": "n", "type": "INTEGER"}]}}
        conn = MagicMock()
        adapter._create_empty_schema_tables(conn)
        ddl = conn.execute.call_args[0][0]
        assert '"n" INT' in ddl

    def test_ddl_maps_bigint(self, adapter):
        adapter._table_schemas = {"t": {"columns": [{"name": "n", "type": "BIGINT"}]}}
        conn = MagicMock()
        adapter._create_empty_schema_tables(conn)
        ddl = conn.execute.call_args[0][0]
        assert '"n" BIGINT' in ddl

    def test_ddl_maps_varchar_as_default(self, adapter):
        adapter._table_schemas = {
            "t": {"columns": [{"name": "s", "type": "TEXT"}]}  # TEXT not in type_map → VARCHAR
        }
        conn = MagicMock()
        adapter._create_empty_schema_tables(conn)
        ddl = conn.execute.call_args[0][0]
        assert '"s" VARCHAR' in ddl

    def test_ddl_handles_parameterised_decimal(self, adapter):
        adapter._table_schemas = {"t": {"columns": [{"name": "price", "type": "DECIMAL(10,2)"}]}}
        conn = MagicMock()
        adapter._create_empty_schema_tables(conn)
        ddl = conn.execute.call_args[0][0]
        assert '"price" DECIMAL(10,2)' in ddl

    def test_skips_tables_with_no_columns(self, adapter):
        adapter._table_schemas = {
            "empty_table": {"columns": []},
            "real_table": {"columns": [{"name": "id", "type": "INTEGER"}]},
        }
        conn = MagicMock()
        adapter._create_empty_schema_tables(conn)
        # Only real_table should generate DDL
        assert conn.execute.call_count == 1

    def test_tolerates_execute_exception(self, adapter):
        """Individual table DDL failures are swallowed - method doesn't raise."""
        adapter._table_schemas = {"t": {"columns": [{"name": "id", "type": "INTEGER"}]}}
        conn = MagicMock()
        conn.execute.side_effect = Exception("DDL error")
        # Should not raise
        result = adapter._create_empty_schema_tables(conn)
        assert result == {}


# ---------------------------------------------------------------------------
# _get_benchmark_schema - OBTTable dataclass-style schema
# ---------------------------------------------------------------------------
class TestGetBenchmarkSchemaOBTTable:
    """_get_benchmark_schema handles OBTTable dataclass objects (no 'columns' dict key)."""

    @pytest.fixture()
    def adapter(self):
        with patch("benchbox.platforms.datafusion.SessionContext"), tempfile.TemporaryDirectory() as tmpdir:
            yield DataFusionAdapter(working_dir=tmpdir)

    def test_extracts_columns_from_dataclass_style_table(self, adapter):
        """Table def has .columns attribute with .name and .sql_type() per column."""
        col1 = Mock()
        col1.name = "sale_id"
        col1.sql_type = Mock(return_value="BIGINT")

        col2 = Mock()
        col2.name = "amount"
        col2.sql_type = Mock(return_value="DECIMAL(18,2)")

        table_def = Mock()
        table_def.columns = [col1, col2]
        # Mock is not a dict, so isinstance(table_def, dict) is False → hits hasattr branch

        mock_benchmark = Mock()
        mock_benchmark.get_schema.return_value = {"sales": table_def}

        schemas = adapter._get_benchmark_schema(mock_benchmark)

        assert "sales" in schemas
        assert len(schemas["sales"]["columns"]) == 2
        assert schemas["sales"]["columns"][0] == {"name": "sale_id", "type": "BIGINT"}
        assert schemas["sales"]["columns"][1] == {"name": "amount", "type": "DECIMAL(18,2)"}

    def test_dataclass_column_without_sql_type_defaults_to_varchar(self, adapter):
        col = Mock(spec=["name"])  # no sql_type method
        col.name = "notes"

        table_def = Mock()
        table_def.columns = [col]

        mock_benchmark = Mock()
        mock_benchmark.get_schema.return_value = {"info": table_def}

        schemas = adapter._get_benchmark_schema(mock_benchmark)

        assert schemas["info"]["columns"][0] == {"name": "notes", "type": "VARCHAR"}

    def test_table_name_normalized_to_lowercase(self, adapter):
        col = Mock()
        col.name = "id"
        col.sql_type = Mock(return_value="INTEGER")

        table_def = Mock()
        table_def.columns = [col]

        mock_benchmark = Mock()
        mock_benchmark.get_schema.return_value = {"DimCustomer": table_def}

        schemas = adapter._get_benchmark_schema(mock_benchmark)

        assert "dimcustomer" in schemas
        assert "DimCustomer" not in schemas
