"""Tests for Databricks platform adapter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest

from benchbox.platforms.base.data_loading import DataSource
from benchbox.platforms.databricks import DatabricksAdapter
from benchbox.platforms.databricks.adapter import _select_databricks_warehouse

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.cloud_import,
]


@pytest.fixture(autouse=True)
def databricks_dependencies():
    """Mock Databricks dependency check to simulate installed extras."""

    # Patch where check_platform_dependencies is actually called (in the adapter module)
    with patch("benchbox.platforms.databricks.adapter.check_platform_dependencies", return_value=(True, [])):
        yield


class TestDatabricksAdapter:
    """Test Databricks platform adapter functionality."""

    def test_initialization_success(self):
        """Test successful adapter initialization."""
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
                catalog="test_catalog",
                schema="test_schema",
                staging_root="dbfs:/Volumes/workspace/tmp",
            )
            assert adapter.platform_name == "Databricks"
            assert adapter.get_target_dialect() == "databricks"
            assert adapter.server_hostname == "test.cloud.databricks.com"
            assert adapter.http_path == "/sql/1.0/warehouses/test"
            assert adapter.catalog == "test_catalog"
            assert adapter.schema == "test_schema"

    def test_initialization_with_defaults(self):
        """Test initialization with default configuration."""
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
            )
            assert adapter.catalog == "main"
            assert adapter.schema == "benchbox"
            assert adapter.enable_delta_optimization is True
            assert adapter.delta_auto_optimize is True
            assert adapter.delta_auto_compact is True

    def test_initialization_missing_driver(self):
        """Test initialization when Databricks dependencies are missing."""
        with (
            patch(
                "benchbox.platforms.databricks.adapter.check_platform_dependencies",
                return_value=(False, ["databricks-sql-connector"]),
            ),
            pytest.raises(ImportError) as excinfo,
        ):
            DatabricksAdapter()

        assert "Missing dependencies for databricks platform" in str(excinfo.value)

    def test_initialization_missing_required_config(self):
        """Test initialization with missing required configuration."""
        from benchbox.core.exceptions import ConfigurationError

        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            with pytest.raises(ConfigurationError, match="Databricks configuration is incomplete"):
                DatabricksAdapter()  # Missing required fields

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_get_connection_params(self, mock_databricks_sql):
        """Test connection parameter configuration."""
        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
            catalog="test_catalog",
        )

        params = adapter._get_connection_params()

        assert params["server_hostname"] == "test.cloud.databricks.com"
        assert params["http_path"] == "/sql/1.0/warehouses/test"
        assert params["access_token"] == "test_token"

        # Test with overrides
        override_params = adapter._get_connection_params(
            server_hostname="override.databricks.com", access_token="override_token"
        )
        assert override_params["server_hostname"] == "override.databricks.com"
        assert override_params["access_token"] == "override_token"
        assert override_params["http_path"] == "/sql/1.0/warehouses/test"  # Should keep original

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_from_config_with_explicit_schema(self, mock_databricks_sql):
        """Test from_config() with explicitly provided schema name."""
        config = {
            "server_hostname": "test.cloud.databricks.com",
            "http_path": "/sql/1.0/warehouses/test",
            "access_token": "test_token",
            "catalog": "test_catalog",
            "schema": "my_explicit_schema",
            "benchmark": "tpcds",
            "scale_factor": 1,
        }

        adapter = DatabricksAdapter.from_config(config)

        # Should use the explicitly provided schema name
        assert adapter.schema == "my_explicit_schema"
        assert adapter.catalog == "test_catalog"

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_from_config_with_none_schema_generates_name(self, mock_databricks_sql):
        """Test from_config() with None schema auto-generates schema name.

        This is a regression test for the Databricks harmonization fix.
        When --schema is not provided (default=None), the adapter should
        auto-generate an intelligent schema name based on benchmark, scale,
        and tuning configuration, NOT fall back to 'benchbox'.

        See: databricks_harmonization_summary.md
        """
        config = {
            "server_hostname": "test.cloud.databricks.com",
            "http_path": "/sql/1.0/warehouses/test",
            "access_token": "test_token",
            "catalog": "test_catalog",
            "schema": None,  # This is what CLI provides when --schema is not specified
            "benchmark": "tpcds",
            "scale_factor": 1,
        }

        adapter = DatabricksAdapter.from_config(config)

        # Should auto-generate schema name, NOT use 'benchbox' fallback
        assert adapter.schema != "benchbox", (
            "Schema should be auto-generated, not fall back to 'benchbox'. "
            "This indicates a regression in the schema name generation logic."
        )
        # Should contain benchmark name
        assert "tpcds" in adapter.schema, (
            f"Generated schema name '{adapter.schema}' should contain benchmark name 'tpcds'"
        )
        # Should contain scale factor
        assert "sf1" in adapter.schema, f"Generated schema name '{adapter.schema}' should contain scale factor 'sf1'"

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_from_config_without_schema_key_generates_name(self, mock_databricks_sql):
        """Test from_config() without schema key auto-generates schema name."""
        config = {
            "server_hostname": "test.cloud.databricks.com",
            "http_path": "/sql/1.0/warehouses/test",
            "access_token": "test_token",
            "catalog": "test_catalog",
            # schema key not provided at all
            "benchmark": "tpch",
            "scale_factor": 10,
        }

        adapter = DatabricksAdapter.from_config(config)

        # Should auto-generate schema name, NOT use 'benchbox' fallback
        assert adapter.schema != "benchbox"
        assert "tpch" in adapter.schema
        assert "sf10" in adapter.schema

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_from_config_schema_generation_with_tuning(self, mock_databricks_sql):
        """Test schema name generation includes tuning configuration."""
        config = {
            "server_hostname": "test.cloud.databricks.com",
            "http_path": "/sql/1.0/warehouses/test",
            "access_token": "test_token",
            "schema": None,
            "benchmark": "tpcds",
            "scale_factor": 1,
            "tuning_config": {
                "name": "optimized",
                "indexes": True,
            },
        }

        adapter = DatabricksAdapter.from_config(config)

        # Should include tuning config name in generated schema
        assert adapter.schema != "benchbox"
        assert "tpcds" in adapter.schema
        assert "optimized" in adapter.schema or "tuning" in adapter.schema

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_from_config_with_benchbox_default_generates_name(self, mock_databricks_sql):
        """Test from_config() with 'benchbox' default schema auto-generates.

        This is a regression test for credentials file containing schema: benchbox.
        When schema is 'benchbox' (the default from credentials), and benchmark
        context is available, the adapter should auto-generate a proper schema name
        instead of using the default.

        Previously, the credentials default was incorrectly treated as an explicit
        override, causing all tables to be created in the 'benchbox' schema instead
        of properly named schemas like 'tpcds_sf1_notuning_uniq_check'.
        """
        config = {
            "server_hostname": "test.cloud.databricks.com",
            "http_path": "/sql/1.0/warehouses/test",
            "access_token": "test_token",
            "catalog": "workspace",
            "schema": "benchbox",  # This is the default from credentials file
            "benchmark": "tpcds",
            "scale_factor": 1,
        }

        adapter = DatabricksAdapter.from_config(config)

        # Should auto-generate schema name, NOT use 'benchbox' default
        assert adapter.schema != "benchbox", (
            "Schema should be auto-generated, not use 'benchbox' default from credentials"
        )
        assert adapter.schema.startswith("tpcds_sf1"), f"Schema should start with benchmark and scale: {adapter.schema}"

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_create_admin_connection(self, mock_databricks_sql):
        """Test admin connection creation."""
        mock_connection = Mock()
        mock_databricks_sql.connect.return_value = mock_connection

        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        admin_conn = adapter._create_admin_connection()

        assert admin_conn == mock_connection
        mock_databricks_sql.connect.assert_called_once()
        call_kwargs = mock_databricks_sql.connect.call_args[1]
        assert call_kwargs["server_hostname"] == "test.cloud.databricks.com"
        assert call_kwargs["http_path"] == "/sql/1.0/warehouses/test"
        assert call_kwargs["access_token"] == "test_token"

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_check_server_database_exists_true(self, mock_databricks_sql):
        """Test database existence check when catalog/schema exists."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        # Mock SHOW CATALOGS and SHOW SCHEMAS responses
        mock_cursor.fetchall.side_effect = [
            [["test_catalog"], ["other_catalog"]],  # SHOW CATALOGS
            [["benchbox"], ["other_schema"]],  # SHOW SCHEMAS IN test_catalog
        ]
        mock_databricks_sql.connect.return_value = mock_connection

        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
            catalog="test_catalog",
        )

        exists = adapter.check_server_database_exists()

        assert exists is True
        # Should call both SHOW CATALOGS and SHOW SCHEMAS
        mock_cursor.execute.assert_any_call("SHOW CATALOGS")
        mock_cursor.execute.assert_any_call("SHOW SCHEMAS IN test_catalog")
        # Connection is closed in finally block
        mock_connection.close.assert_called_once()

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_check_server_database_exists_false(self, mock_databricks_sql):
        """Test database existence check when catalog doesn't exist."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [["other_catalog"]]
        mock_databricks_sql.connect.return_value = mock_connection

        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
            catalog="test_catalog",
        )

        exists = adapter.check_server_database_exists()

        assert exists is False
        mock_connection.close.assert_called_once()

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_check_server_database_exists_connection_error(self, mock_databricks_sql):
        """Test database existence check with connection error."""
        mock_databricks_sql.connect.side_effect = Exception("Connection failed")

        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        exists = adapter.check_server_database_exists()

        assert exists is False

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_drop_database(self, mock_databricks_sql):
        """Test catalog/schema dropping."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_databricks_sql.connect.return_value = mock_connection

        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
            catalog="test_catalog",
        )

        adapter.drop_database()

        # Should drop schema (Databricks doesn't drop catalogs, only schemas)
        mock_cursor.execute.assert_called_with("DROP SCHEMA IF EXISTS test_catalog.benchbox CASCADE")
        # Connection is closed in finally block
        mock_connection.close.assert_called_once()

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_create_connection_success(self, mock_databricks_sql):
        """Test successful connection creation."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_databricks_sql.connect.return_value = mock_connection

        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
            catalog="test_catalog",
            schema="test_schema",
        )

        # Mock handle_existing_database
        with patch.object(adapter, "handle_existing_database"):
            connection = adapter.create_connection()

        assert connection == mock_connection
        mock_databricks_sql.connect.assert_called_once()

        # Check catalog was set (schema is set in create_schema(), not here)
        expected_calls = [
            call("USE CATALOG test_catalog"),
            call("SELECT 1"),  # Connection test
        ]
        for expected_call in expected_calls:
            mock_cursor.execute.assert_any_call(expected_call.args[0])

        # Note: cursor is not closed in create_connection - connection stays open

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_create_connection_failure(self, mock_databricks_sql):
        """Test connection creation failure."""
        mock_databricks_sql.connect.side_effect = Exception("Connection failed")

        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        with patch.object(adapter, "handle_existing_database"):
            with pytest.raises(Exception, match="Connection failed"):
                adapter.create_connection()

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_create_schema(self, mock_databricks_sql):
        """Test schema creation with Unity Catalog."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        mock_benchmark = Mock()
        mock_benchmark.get_create_tables_sql.return_value = """
            CREATE TABLE table1 (id BIGINT, name STRING);
            CREATE TABLE table2 (id BIGINT, data STRING);
        """

        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
            catalog="test_catalog",
            schema="test_schema",
            create_catalog=True,  # Enable catalog creation for this test
        )

        # Mock translate_sql method
        with patch.object(adapter, "translate_sql") as mock_translate:
            mock_translate.return_value = (
                "CREATE TABLE table1 (id BIGINT, name STRING);\nCREATE TABLE table2 (id BIGINT, data STRING);"
            )

            schema_time = adapter.create_schema(mock_benchmark, mock_connection)

        assert isinstance(schema_time, float)
        assert schema_time >= 0

        # Should execute catalog and schema setup
        setup_calls = list(mock_cursor.execute.call_args_list)
        setup_sqls = [str(call) for call in setup_calls]

        # Should include catalog creation, schema creation, and table creation
        assert any("CREATE CATALOG" in sql for sql in setup_sqls)
        assert any("CREATE SCHEMA" in sql for sql in setup_sqls)

        mock_cursor.close.assert_called_once()

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_load_data_with_delta_tables(self, mock_databricks_sql):
        """Test data loading using Delta Lake format."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Mock SHOW TABLES query (returns test_table)
        mock_cursor.fetchall.return_value = [("test_schema", "test_table", False)]
        # Mock row count query
        mock_cursor.fetchone.return_value = (100,)

        mock_benchmark = Mock()

        # Create temporary test file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("id,name\n1,test1\n2,test2\n")
            temp_path = Path(f.name)

        try:
            mock_benchmark.tables = {"test_table": str(temp_path)}

            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
                catalog="test_catalog",
                schema="test_schema",
                staging_root="dbfs:/Volumes/workspace/tmp",
            )

            table_stats, load_time, _ = adapter.load_data(mock_benchmark, mock_connection, Path("/tmp"))

            assert isinstance(table_stats, dict)
            assert isinstance(load_time, float)
            assert load_time >= 0
            assert "TEST_TABLE" in table_stats
            assert table_stats["TEST_TABLE"] == 100

            # Should execute COPY INTO statements without temporary views or insert-select
            execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
            assert any("COPY INTO TEST_TABLE" in call for call in execute_calls)
            assert all("CREATE OR REPLACE TEMPORARY VIEW" not in call for call in execute_calls)
            assert all("INSERT INTO" not in call for call in execute_calls)

        finally:
            temp_path.unlink()

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_create_external_tables_uses_parquet_location(self, mock_databricks_sql):
        """External mode should register LOCATION-based Parquet tables."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [("test_schema", "orders", False)]
        mock_cursor.fetchone.return_value = (123,)

        with tempfile.NamedTemporaryFile(mode="wb", suffix=".parquet", delete=False) as f:
            f.write(b"PAR1")
            parquet_path = Path(f.name)

        benchmark = Mock()
        benchmark.tables = {"orders": str(parquet_path)}

        try:
            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
                catalog="test_catalog",
                schema="test_schema",
                staging_root="dbfs:/Volumes/workspace/tmp",
            )

            assert adapter.supports_external_tables is True

            stats, load_time, _ = adapter.create_external_tables(benchmark, mock_connection, Path("dbfs:/tmp/data"))

            assert stats["ORDERS"] == 123
            assert load_time >= 0

            execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
            assert any("CREATE TABLE ORDERS USING PARQUET LOCATION" in call for call in execute_calls)
            assert all("COPY INTO" not in call for call in execute_calls)
        finally:
            parquet_path.unlink()

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_external_table_mode_requires_staging_configuration(self, mock_databricks_sql):
        """External mode should require explicit staging configuration."""
        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
            catalog="test_catalog",
            schema="test_schema",
        )

        with pytest.raises(ValueError, match="requires cloud staging"):
            adapter.validate_external_table_requirements()

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_configure_for_benchmark_olap(self, mock_databricks_sql):
        """Test OLAP benchmark configuration without default Spark optimizations."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        adapter.configure_for_benchmark(mock_connection, "olap")

        # Should execute cache control setting by default
        execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
        assert len(execute_calls) == 1, "Should set cache control"
        assert "use_cached_result = false" in execute_calls[0]

        # Should create cursor to apply cache control
        mock_connection.cursor.assert_called_once()

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_configure_for_benchmark_with_delta_optimization(self, mock_databricks_sql):
        """Test benchmark configuration with user-provided Spark configs."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Create adapter with custom Spark configs
        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
            enable_delta_optimization=True,
            delta_auto_optimize=True,
            delta_auto_compact=True,
        )

        # Manually provide spark_configs to test user-provided config path
        adapter.spark_configs = {
            "spark.databricks.delta.optimizeWrite.enabled": "true",
            "spark.databricks.delta.autoCompact.enabled": "true",
        }

        adapter.configure_for_benchmark(mock_connection, "tpch")

        # Should execute user-provided Spark configs
        execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
        assert any("spark.databricks.delta.optimizeWrite.enabled" in call for call in execute_calls)
        assert any("spark.databricks.delta.autoCompact.enabled" in call for call in execute_calls)

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_execute_query_success(self, mock_databricks_sql):
        """Test successful query execution."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [(1, "test"), (2, "test2")]

        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        result = adapter.execute_query(mock_connection, "SELECT * FROM test", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2
        assert result["first_row"] == (1, "test")
        assert isinstance(result["execution_time_seconds"], float)
        # Note: query_statistics not returned by actual implementation

        mock_cursor.execute.assert_called_with("SELECT * FROM test")
        mock_cursor.close.assert_called_once()

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_execute_query_failure(self, mock_databricks_sql):
        """Test query execution failure."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("Query failed")

        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        result = adapter.execute_query(mock_connection, "INVALID SQL", "q1")

        assert result["query_id"] == "q1"
        assert result["status"] == "FAILED"
        assert result["rows_returned"] == 0
        assert result["error"] == "Query failed"
        assert result["error_type"] == "Exception"
        assert isinstance(result["execution_time_seconds"], float)

        mock_cursor.close.assert_called_once()

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_get_query_statistics(self, mock_databricks_sql):
        """Test query statistics retrieval (method not implemented)."""
        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        # Method doesn't exist in actual implementation
        assert not hasattr(adapter, "_get_query_statistics")

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_get_platform_metadata(self, mock_databricks_sql):
        """Test platform metadata collection."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Mock query responses
        mock_cursor.fetchone.side_effect = [
            ["Spark 3.4.1"],  # Spark version
            ["test_catalog", "test_schema"],  # Current catalog and schema
        ]

        mock_cursor.fetchall.side_effect = [
            [["TABLE1", 1000, 1024000, "DELTA", "2024-01-01"]],  # Table info
            [["memory: 8GB", "cores: 4", "cluster_type: sql_warehouse"]],  # Cluster info
        ]

        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
            catalog="test_catalog",
            schema="test_schema",
        )

        metadata = adapter._get_platform_metadata(mock_connection)

        assert metadata["platform"] == "Databricks"
        assert metadata["server_hostname"] == "test.cloud.databricks.com"
        assert metadata["catalog"] == "test_catalog"
        assert metadata["schema"] == "test_schema"
        assert "spark_version" in metadata
        assert "current_catalog" in metadata
        assert "current_schema" in metadata
        assert "available_functions" in metadata

        mock_cursor.close.assert_called()

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_optimize_table_delta(self, mock_databricks_sql):
        """Test Delta table optimization."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        adapter.optimize_table(mock_connection, "test_table")

        # Should execute OPTIMIZE command for Delta tables
        execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
        assert any("OPTIMIZE TEST_TABLE" in call for call in execute_calls)
        # Note: VACUUM is handled by separate vacuum_table method

        mock_cursor.close.assert_called_once()

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_close_connection(self, mock_databricks_sql):
        """Test connection closing."""
        mock_connection = Mock()

        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        adapter.close_connection(mock_connection)

        mock_connection.close.assert_called_once()

    def test_supports_tuning_type(self):
        """Test tuning type support checking."""
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
            )

            # Mock TuningType
            with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
                mock_tuning_type.PARTITIONING = "partitioning"
                mock_tuning_type.CLUSTERING = "clustering"
                mock_tuning_type.DISTRIBUTION = "distribution"
                mock_tuning_type.SORTING = "sorting"

                assert adapter.supports_tuning_type(mock_tuning_type.PARTITIONING) is True
                assert adapter.supports_tuning_type(mock_tuning_type.CLUSTERING) is True
                assert adapter.supports_tuning_type(mock_tuning_type.DISTRIBUTION) is True
                assert adapter.supports_tuning_type(mock_tuning_type.SORTING) is False

    def test_generate_tuning_clause_with_partitioning(self):
        """Test tuning clause generation with partitioning."""
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
            )

            # Mock table tuning with partitioning
            mock_tuning = Mock()
            mock_tuning.has_any_tuning.return_value = True

            # Mock partitioning column
            mock_column = Mock()
            mock_column.name = "partition_key"
            mock_column.order = 1

            with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
                mock_tuning_type.PARTITIONING = "partitioning"
                mock_tuning_type.CLUSTERING = "clustering"
                mock_tuning_type.Z_ORDERING = "z_ordering"

                def mock_get_columns_by_type(tuning_type):
                    if tuning_type == mock_tuning_type.PARTITIONING:
                        return [mock_column]
                    return []

                mock_tuning.get_columns_by_type.side_effect = mock_get_columns_by_type

                clause = adapter.generate_tuning_clause(mock_tuning)

                assert "PARTITIONED BY (partition_key)" in clause

    def test_generate_tuning_clause_with_clustering(self):
        """Test tuning clause generation with clustering."""
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
            )

            # Mock table tuning with clustering
            mock_tuning = Mock()
            mock_tuning.has_any_tuning.return_value = True

            # Mock clustering column
            mock_column = Mock()
            mock_column.name = "cluster_key"
            mock_column.order = 1

            with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
                mock_tuning_type.PARTITIONING = "partitioning"
                mock_tuning_type.CLUSTERING = "clustering"
                mock_tuning_type.DISTRIBUTION = "distribution"

                def mock_get_columns_by_type(tuning_type):
                    if tuning_type == mock_tuning_type.CLUSTERING:
                        return [mock_column]
                    return []

                mock_tuning.get_columns_by_type.side_effect = mock_get_columns_by_type

                clause = adapter.generate_tuning_clause(mock_tuning)

                assert "CLUSTER BY (cluster_key)" in clause

    def test_generate_tuning_clause_none(self):
        """Test tuning clause generation with None input."""
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
            )

            clause = adapter.generate_tuning_clause(None)
            assert clause == ""

    @patch("benchbox.platforms.databricks.adapter.databricks_sql")
    def test_apply_table_tunings_with_clustering(self, mock_databricks_sql):
        """Test applying table tunings with clustering."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Mock DESCRIBE EXTENDED response
        mock_cursor.fetchall.return_value = [
            ["col_name", "data_type", "comment"],
            ["Provider", "DELTA", None],
            ["Type", "MANAGED", None],
        ]

        adapter = DatabricksAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        # Mock table tuning
        mock_tuning = Mock()
        mock_tuning.table_name = "test_table"
        mock_tuning.has_any_tuning.return_value = True

        # Mock clustering column
        mock_column = Mock()
        mock_column.name = "cluster_key"
        mock_column.order = 1

        with patch("benchbox.core.tuning.interface.TuningType") as mock_tuning_type:
            mock_tuning_type.PARTITIONING = "partitioning"
            mock_tuning_type.CLUSTERING = "clustering"
            mock_tuning_type.DISTRIBUTION = "distribution"
            mock_tuning_type.SORTING = "sorting"

            def mock_get_columns_by_type(tuning_type):
                if tuning_type == mock_tuning_type.CLUSTERING:
                    return [mock_column]
                return []

            mock_tuning.get_columns_by_type.side_effect = mock_get_columns_by_type

            adapter.apply_table_tunings(mock_tuning, mock_connection)

            # Should execute clustering optimization via Z-ORDER
            execute_calls = [str(call) for call in mock_cursor.execute.call_args_list]
            assert any("OPTIMIZE TEST_TABLE ZORDER BY" in call for call in execute_calls)

        mock_cursor.close.assert_called()

    def test_apply_unified_tuning(self):
        """Test unified tuning configuration application."""
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
            )

            mock_connection = Mock()
            mock_unified_config = Mock()
            mock_unified_config.primary_keys = Mock()
            mock_unified_config.foreign_keys = Mock()
            mock_unified_config.platform_optimizations = Mock()
            mock_unified_config.table_tunings = {}

            # Should not raise exception
            with patch.object(adapter, "apply_constraint_configuration"):
                with patch.object(adapter, "apply_platform_optimizations"):
                    adapter.apply_unified_tuning(mock_unified_config, mock_connection)

    def test_apply_platform_optimizations_with_delta_features(self):
        """Test platform optimizations with Delta Lake features."""
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
                enable_delta_optimization=True,
                auto_optimize=True,
            )

            mock_connection = Mock()
            mock_platform_config = Mock()

            # Should not raise exception - Delta optimizations handled in configure_for_benchmark
            adapter.apply_platform_optimizations(mock_platform_config, mock_connection)

    def test_apply_constraint_configuration(self):
        """Test constraint configuration application."""
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
            )

            mock_connection = Mock()
            mock_primary_key_config = Mock()
            mock_primary_key_config.enabled = True
            mock_foreign_key_config = Mock()
            mock_foreign_key_config.enabled = False

            # Should not raise exception - constraints are informational in Databricks
            adapter.apply_constraint_configuration(mock_primary_key_config, mock_foreign_key_config, mock_connection)

    def test_authentication_methods(self):
        """Test different authentication methods."""
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            # Test access token authentication
            adapter1 = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
            )
            assert adapter1.access_token == "test_token"
            assert adapter1.server_hostname == "test.cloud.databricks.com"
            assert adapter1.http_path == "/sql/1.0/warehouses/test"

    def test_unity_catalog_configuration(self):
        """Test Unity Catalog configuration options."""
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
                catalog="my_catalog",
                schema="my_schema",
            )

            assert adapter.catalog == "my_catalog"
            assert adapter.schema == "my_schema"
            assert adapter.enable_delta_optimization is True
            assert adapter.delta_auto_optimize is True


class TestDatabricksSqlGenerationHelpers:
    """Exercise helper-heavy SQL generation and staging behavior."""

    def test_select_databricks_warehouse_prefers_running_then_available(self):
        logger = Mock()
        running = Mock()
        running.name = "running-wh"
        running.state = "RUNNING"
        pending = Mock()
        pending.name = "pending-wh"
        pending.state = "STARTING"
        deleted = Mock()
        deleted.name = "deleted-wh"
        deleted.state = "DELETED"

        selected_running = _select_databricks_warehouse([pending, running], very_verbose=True, logger=logger)
        selected_available = _select_databricks_warehouse([deleted, pending], very_verbose=True, logger=logger)

        assert selected_running is running
        assert selected_available is pending
        assert _select_databricks_warehouse([], very_verbose=False, logger=logger) is None

    def test_resolve_stage_root_prefers_explicit_staging_root_and_uc_volume(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            explicit_adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
                staging_root="dbfs:/Volumes/workspace/tmp/",
            )
            uc_volume_adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
                uc_catalog="main",
                uc_schema="benchbox",
                uc_volume="data",
            )
            invalid_adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
            )

        assert explicit_adapter._resolve_stage_root(Path("/tmp/data")) == "dbfs:/Volumes/workspace/tmp"
        assert uc_volume_adapter._resolve_stage_root(Path("/tmp/data")) == "dbfs:/Volumes/main/benchbox/data"
        with pytest.raises(ValueError, match="requires a cloud/UC Volume staging location"):
            invalid_adapter._resolve_stage_root(Path("/tmp/data"))

    def test_resolve_file_uri_and_delimiter_handles_uc_volume_and_local_paths(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
            )

        volume_uri, volume_filename, volume_delimiter = adapter._resolve_file_uri_and_delimiter(
            "dbfs:/Volumes/main/benchbox/data/lineitem.tbl.1",
            "dbfs:/Volumes/main/benchbox/data",
        )
        local_uri, local_filename, local_delimiter = adapter._resolve_file_uri_and_delimiter(
            Path("/tmp/orders.csv"),
            "dbfs:/Volumes/main/benchbox/data",
        )

        assert volume_uri == "dbfs:/Volumes/main/benchbox/data/lineitem.tbl.1"
        assert volume_filename == "lineitem.tbl.1"
        assert volume_delimiter == "|"
        assert local_uri == "dbfs:/Volumes/main/benchbox/data/orders.csv"
        assert local_filename == "orders.csv"
        assert local_delimiter == ","

    def test_get_column_list_for_table_uses_schema_metadata(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
            )

        benchmark = Mock()
        benchmark.get_schema.return_value = {
            "orders": {
                "columns": [
                    {"name": "o_orderkey"},
                    {"name": "o_orderdate"},
                ]
            }
        }

        assert adapter._get_column_list_for_table(benchmark, "orders") == " (o_orderkey, o_orderdate)"
        assert adapter._get_column_list_for_table(Mock(spec=[]), "orders") == ""

    def test_external_location_from_file_uri_normalizes_wildcard_and_rejects_non_parquet(self):
        assert (
            DatabricksAdapter._external_location_from_file_uri("dbfs:/Volumes/main/benchbox/orders/part-*.parquet")
            == "dbfs:/Volumes/main/benchbox/orders"
        )
        assert (
            DatabricksAdapter._external_location_from_file_uri("dbfs:/Volumes/main/benchbox/orders/part-000.parquet")
            == "dbfs:/Volumes/main/benchbox/orders"
        )
        assert (
            DatabricksAdapter._external_location_from_file_uri("dbfs:/Volumes/main/benchbox/orders")
            == "dbfs:/Volumes/main/benchbox/orders"
        )
        with pytest.raises(ValueError, match="requires Parquet sources"):
            DatabricksAdapter._external_location_from_file_uri("dbfs:/Volumes/main/benchbox/orders/orders.csv")

    def test_load_single_table_builds_copy_into_with_column_mapping_and_optimize(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
                catalog="main",
                schema="benchbox",
            )

        benchmark = Mock()
        benchmark.get_schema.return_value = {
            "orders": {
                "columns": [
                    {"name": "o_orderkey"},
                    {"name": "o_orderdate"},
                ]
            }
        }
        cursor = Mock()
        cursor.fetchone.return_value = (7,)
        connection = Mock()

        with patch.object(adapter, "get_effective_tuning_configuration", return_value=None):
            row_count, copy_time, optimize_time = adapter._load_single_table(
                cursor,
                connection,
                benchmark,
                "orders",
                Path("orders.tbl.1"),
                "dbfs:/Volumes/main/benchbox/data",
                {"orders"},
            )

        assert row_count == 7
        assert copy_time >= 0.0
        assert optimize_time >= 0.0
        assert cursor.execute.call_args_list[0].args[0] == (
            "COPY INTO ORDERS (o_orderkey, o_orderdate) FROM "
            "'dbfs:/Volumes/main/benchbox/data/orders.tbl.1' "
            "FILEFORMAT = CSV FORMAT_OPTIONS('delimiter'='|', 'header'='false')"
        )
        assert cursor.execute.call_args_list[1].args[0] == "SELECT COUNT(*) FROM ORDERS"
        assert cursor.execute.call_args_list[2].args[0] == "OPTIMIZE ORDERS"

    def test_vacuum_table_executes_delta_maintenance(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
                enable_delta_optimization=True,
            )

        connection = Mock()
        cursor = Mock()
        connection.cursor.return_value = cursor

        adapter.vacuum_table(connection, "orders", hours=24)

        cursor.execute.assert_called_once_with("VACUUM ORDERS RETAIN 24 HOURS")
        cursor.close.assert_called_once()

    def test_validate_external_table_requirements_accepts_uc_volume(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="test_token",
                uc_catalog="main",
                uc_schema="benchbox",
                uc_volume="data",
            )

        adapter.validate_external_table_requirements()


class TestConvertToDeltaTable:
    """Test _convert_to_delta_table SQL transformation."""

    def _make_adapter(self, **kwargs):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            defaults = {
                "server_hostname": "test.cloud.databricks.com",
                "http_path": "/sql/1.0/warehouses/test",
                "access_token": "tok",
            }
            defaults.update(kwargs)
            return DatabricksAdapter(**defaults)

    def test_adds_or_replace_to_create_table(self):
        adapter = self._make_adapter()
        result = adapter._convert_to_delta_table("CREATE TABLE foo (id BIGINT)")
        assert result.startswith("CREATE OR REPLACE TABLE foo")

    def test_preserves_existing_or_replace(self):
        adapter = self._make_adapter()
        result = adapter._convert_to_delta_table("CREATE OR REPLACE TABLE foo (id BIGINT)")
        assert result.count("OR REPLACE") == 1

    def test_adds_using_delta_after_column_defs(self):
        adapter = self._make_adapter()
        result = adapter._convert_to_delta_table("CREATE TABLE t (a INT, b STRING)")
        assert "USING DELTA" in result
        # USING DELTA should appear after the closing paren
        paren_idx = result.index(")")
        delta_idx = result.index("USING DELTA")
        assert delta_idx > paren_idx

    def test_does_not_add_using_delta_when_already_present(self):
        adapter = self._make_adapter()
        result = adapter._convert_to_delta_table("CREATE TABLE t (a INT) USING DELTA")
        assert result.count("USING DELTA") == 1

    def test_adds_tblproperties_for_auto_optimize(self):
        adapter = self._make_adapter(delta_auto_optimize=True)
        result = adapter._convert_to_delta_table("CREATE TABLE t (a INT)")
        assert "TBLPROPERTIES" in result
        assert "'delta.autoOptimize.optimizeWrite' = 'true'" in result
        assert "'delta.autoOptimize.autoCompact' = 'true'" in result

    def test_no_tblproperties_when_auto_optimize_disabled(self):
        adapter = self._make_adapter(delta_auto_optimize=False)
        result = adapter._convert_to_delta_table("CREATE TABLE t (a INT)")
        assert "TBLPROPERTIES ()" in result

    def test_preserves_existing_tblproperties(self):
        adapter = self._make_adapter()
        sql = "CREATE TABLE t (a INT) TBLPROPERTIES ('x'='y')"
        result = adapter._convert_to_delta_table(sql)
        # Should NOT add a second TBLPROPERTIES block
        assert result.count("TBLPROPERTIES") == 1

    def test_non_create_table_passthrough(self):
        adapter = self._make_adapter()
        sql = "INSERT INTO foo VALUES (1)"
        assert adapter._convert_to_delta_table(sql) == sql

    def test_nested_parens_in_column_defs(self):
        adapter = self._make_adapter()
        sql = "CREATE TABLE t (a DECIMAL(10,2), b VARCHAR(100))"
        result = adapter._convert_to_delta_table(sql)
        # Should still find the right closing paren
        assert "USING DELTA" in result
        assert "DECIMAL(10,2)" in result
        assert "VARCHAR(100)" in result


class TestFixDatabricksSqlSyntax:
    """Test _fix_databricks_sql_syntax NULLS FIRST/LAST removal."""

    def _make_adapter(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            return DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="tok",
            )

    def test_removes_nulls_last_from_pk(self):
        adapter = self._make_adapter()
        sql = "CREATE TABLE t (id INT, PRIMARY KEY (id NULLS LAST))"
        result = adapter._fix_databricks_sql_syntax(sql)
        assert "NULLS LAST" not in result
        assert "PRIMARY KEY" in result

    def test_removes_nulls_first_from_pk(self):
        adapter = self._make_adapter()
        sql = "CREATE TABLE t (id INT, PRIMARY KEY (id NULLS FIRST))"
        result = adapter._fix_databricks_sql_syntax(sql)
        assert "NULLS FIRST" not in result
        assert "PRIMARY KEY" in result

    def test_removes_multiple_nulls_clauses(self):
        adapter = self._make_adapter()
        sql = "CREATE TABLE t (a INT, b INT, PRIMARY KEY (a NULLS LAST, b NULLS FIRST))"
        result = adapter._fix_databricks_sql_syntax(sql)
        assert "NULLS LAST" not in result
        assert "NULLS FIRST" not in result
        assert "PRIMARY KEY" in result

    def test_no_change_without_nulls(self):
        adapter = self._make_adapter()
        sql = "CREATE TABLE t (id INT, PRIMARY KEY (id))"
        result = adapter._fix_databricks_sql_syntax(sql)
        assert result == sql

    def test_no_change_without_pk(self):
        adapter = self._make_adapter()
        sql = "CREATE TABLE t (id INT) ORDER BY id NULLS LAST"
        result = adapter._fix_databricks_sql_syntax(sql)
        # NULLS LAST outside a PRIMARY KEY should be preserved
        assert result == sql


class TestBuildCtasSortSql:
    """Test _build_ctas_sort_sql for various sorted ingestion methods."""

    def _make_adapter(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            return DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="tok",
            )

    def _mock_column(self, name):
        col = Mock()
        col.name = name
        return col

    def test_ctas_method_generates_create_or_replace(self):
        adapter = self._make_adapter()
        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("on", "ctas")):
            result = adapter._build_ctas_sort_sql("LINEITEM", [self._mock_column("l_orderkey")])
        assert result == "CREATE OR REPLACE TABLE LINEITEM AS SELECT * FROM LINEITEM ORDER BY l_orderkey"

    def test_z_order_method_generates_optimize_zorder(self):
        adapter = self._make_adapter()
        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("on", "z_order")):
            result = adapter._build_ctas_sort_sql("ORDERS", [self._mock_column("o_orderkey")])
        assert result == "OPTIMIZE ORDERS ZORDER BY (o_orderkey)"

    def test_liquid_clustering_method_generates_alter_table(self):
        adapter = self._make_adapter()
        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("on", "liquid_clustering")):
            result = adapter._build_ctas_sort_sql("PART", [self._mock_column("p_partkey")])
        assert result == "ALTER TABLE PART CLUSTER BY (p_partkey)"

    def test_off_mode_returns_none(self):
        adapter = self._make_adapter()
        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("off", "ctas")):
            result = adapter._build_ctas_sort_sql("T", [self._mock_column("x")])
        assert result is None

    def test_multiple_columns_joined(self):
        adapter = self._make_adapter()
        cols = [self._mock_column("a"), self._mock_column("b")]
        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("on", "z_order")):
            result = adapter._build_ctas_sort_sql("T", cols)
        assert result == "OPTIMIZE T ZORDER BY (a, b)"

    def test_unsupported_method_raises(self):
        adapter = self._make_adapter()
        with patch.object(adapter, "resolve_sorted_ingestion_strategy", return_value=("on", "exotic_method")):
            with pytest.raises(ValueError, match="not supported"):
                adapter._build_ctas_sort_sql("T", [self._mock_column("x")])


class TestResolveClusteringStrategy:
    """Test _resolve_databricks_clustering_strategy precedence logic."""

    def _make_adapter(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            return DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="tok",
            )

    def test_default_is_z_order(self):
        adapter = self._make_adapter()
        with patch.object(adapter, "get_effective_tuning_configuration", return_value=None):
            assert adapter._resolve_databricks_clustering_strategy() == "z_order"

    def test_no_platform_opts_returns_z_order(self):
        adapter = self._make_adapter()
        mock_config = Mock()
        mock_config.platform_optimizations = None
        with patch.object(adapter, "get_effective_tuning_configuration", return_value=mock_config):
            assert adapter._resolve_databricks_clustering_strategy() == "z_order"

    def test_liquid_enabled_overrides_z_order(self):
        adapter = self._make_adapter()
        mock_config = Mock()
        mock_opts = Mock()
        mock_opts.databricks_clustering_strategy = "z_order"
        mock_opts.liquid_clustering_enabled = True
        mock_opts.liquid_clustering_columns = []
        mock_opts.z_ordering_enabled = True
        mock_config.platform_optimizations = mock_opts
        with patch.object(adapter, "get_effective_tuning_configuration", return_value=mock_config):
            assert adapter._resolve_databricks_clustering_strategy() == "liquid_clustering"

    def test_liquid_columns_set_selects_liquid(self):
        adapter = self._make_adapter()
        mock_config = Mock()
        mock_opts = Mock()
        mock_opts.databricks_clustering_strategy = "z_order"
        mock_opts.liquid_clustering_enabled = False
        mock_opts.liquid_clustering_columns = ["col1", "col2"]
        mock_opts.z_ordering_enabled = False
        mock_config.platform_optimizations = mock_opts
        with patch.object(adapter, "get_effective_tuning_configuration", return_value=mock_config):
            assert adapter._resolve_databricks_clustering_strategy() == "liquid_clustering"

    def test_explicit_strategy_none_returns_none(self):
        adapter = self._make_adapter()
        mock_config = Mock()
        mock_opts = Mock()
        mock_opts.databricks_clustering_strategy = "none"
        mock_opts.liquid_clustering_enabled = False
        mock_opts.liquid_clustering_columns = []
        mock_opts.z_ordering_enabled = False
        mock_config.platform_optimizations = mock_opts
        with patch.object(adapter, "get_effective_tuning_configuration", return_value=mock_config):
            assert adapter._resolve_databricks_clustering_strategy() == "none"

    def test_z_ordering_enabled_returns_z_order(self):
        adapter = self._make_adapter()
        mock_config = Mock()
        mock_opts = Mock()
        mock_opts.databricks_clustering_strategy = "auto"
        mock_opts.liquid_clustering_enabled = False
        mock_opts.liquid_clustering_columns = []
        mock_opts.z_ordering_enabled = True
        mock_config.platform_optimizations = mock_opts
        with patch.object(adapter, "get_effective_tuning_configuration", return_value=mock_config):
            assert adapter._resolve_databricks_clustering_strategy() == "z_order"


class TestDeltaOperationsSql:
    """Test Delta table operations SQL generation (OPTIMIZE, VACUUM, ANALYZE)."""

    def _make_adapter(self, **kwargs):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            defaults = {
                "server_hostname": "test.cloud.databricks.com",
                "http_path": "/sql/1.0/warehouses/test",
                "access_token": "tok",
            }
            defaults.update(kwargs)
            return DatabricksAdapter(**defaults)

    def test_optimize_table_generates_correct_sql(self):
        adapter = self._make_adapter(enable_delta_optimization=True)
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        adapter.optimize_table(conn, "lineitem")
        cursor.execute.assert_called_once_with("OPTIMIZE LINEITEM")

    def test_optimize_table_skips_when_disabled(self):
        adapter = self._make_adapter(enable_delta_optimization=False)
        conn = Mock()
        adapter.optimize_table(conn, "orders")
        conn.cursor.assert_not_called()

    def test_vacuum_table_default_retention(self):
        adapter = self._make_adapter(enable_delta_optimization=True)
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        adapter.vacuum_table(conn, "part")
        cursor.execute.assert_called_once_with("VACUUM PART RETAIN 168 HOURS")

    def test_vacuum_table_custom_retention(self):
        adapter = self._make_adapter(enable_delta_optimization=True)
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        adapter.vacuum_table(conn, "supplier", hours=48)
        cursor.execute.assert_called_once_with("VACUUM SUPPLIER RETAIN 48 HOURS")

    def test_vacuum_table_skips_when_disabled(self):
        adapter = self._make_adapter(enable_delta_optimization=False)
        conn = Mock()
        adapter.vacuum_table(conn, "orders")
        conn.cursor.assert_not_called()

    def test_analyze_table_generates_compute_statistics(self):
        adapter = self._make_adapter()
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        adapter.analyze_table(conn, "nation")
        cursor.execute.assert_called_once_with("ANALYZE TABLE NATION COMPUTE STATISTICS")

    def test_analyze_table_handles_error_gracefully(self):
        adapter = self._make_adapter()
        conn = Mock()
        cursor = Mock()
        cursor.execute.side_effect = Exception("access denied")
        conn.cursor.return_value = cursor
        # Should not raise - just log warning
        adapter.analyze_table(conn, "region")
        cursor.execute.assert_called_once_with("ANALYZE TABLE REGION COMPUTE STATISTICS")


class TestConfigValidation:
    """Test configuration validation and initialization edge cases."""

    def test_missing_only_server_hostname(self):
        from benchbox.core.exceptions import ConfigurationError

        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            with pytest.raises(ConfigurationError, match="server_hostname") as exc_info:
                DatabricksAdapter(
                    http_path="/sql/1.0/warehouses/test",
                    access_token="test_token",
                )
            assert "server_hostname" in str(exc_info.value)

    def test_missing_only_http_path(self):
        from benchbox.core.exceptions import ConfigurationError

        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            with pytest.raises(ConfigurationError, match="http_path") as exc_info:
                DatabricksAdapter(
                    server_hostname="host.databricks.com",
                    access_token="test_token",
                )
            assert "http_path" in str(exc_info.value)

    def test_missing_only_access_token(self):
        from benchbox.core.exceptions import ConfigurationError

        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            with pytest.raises(ConfigurationError, match="access_token") as exc_info:
                DatabricksAdapter(
                    server_hostname="host.databricks.com",
                    http_path="/sql/1.0/warehouses/test",
                )
            assert "access_token" in str(exc_info.value)

    def test_missing_all_required_fields(self):
        from benchbox.core.exceptions import ConfigurationError

        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            with pytest.raises(ConfigurationError, match="Databricks configuration is incomplete"):
                DatabricksAdapter()

    def test_alternative_config_keys_host_and_token(self):
        """Test 'host' and 'token' alternative keys for server_hostname and access_token."""
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                host="alt.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                token="alt_token",
            )
            assert adapter.server_hostname == "alt.cloud.databricks.com"
            assert adapter.access_token == "alt_token"

    def test_delta_settings_explicit_false(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="host.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="tok",
                enable_delta_optimization=False,
                delta_auto_optimize=False,
                delta_auto_compact=False,
            )
            assert adapter.enable_delta_optimization is False
            assert adapter.delta_auto_optimize is False
            assert adapter.delta_auto_compact is False

    def test_cluster_settings(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="host.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="tok",
                cluster_size="Large",
                auto_terminate_minutes=60,
            )
            assert adapter.cluster_size == "Large"
            assert adapter.auto_terminate_minutes == 60

    def test_disable_result_cache_default(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="host.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="tok",
            )
            assert adapter.disable_result_cache is True

    def test_create_catalog_default_false(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="host.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="tok",
            )
            assert adapter.create_catalog is False

    def test_uc_volume_configuration(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="host.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="tok",
                uc_catalog="my_catalog",
                uc_schema="my_schema",
                uc_volume="my_volume",
            )
            assert adapter.uc_catalog == "my_catalog"
            assert adapter.uc_schema == "my_schema"
            assert adapter.uc_volume == "my_volume"


class TestIsCloudUri:
    """Test _is_cloud_uri static method."""

    def test_s3_uri(self):
        assert DatabricksAdapter._is_cloud_uri("s3://bucket/path") is True

    def test_gs_uri(self):
        assert DatabricksAdapter._is_cloud_uri("gs://bucket/path") is True

    def test_abfss_uri(self):
        assert DatabricksAdapter._is_cloud_uri("abfss://container@account.dfs.core.windows.net/path") is True

    def test_dbfs_uri(self):
        assert DatabricksAdapter._is_cloud_uri("dbfs:/Volumes/cat/schema/vol") is True

    def test_local_path_not_cloud(self):
        assert DatabricksAdapter._is_cloud_uri("/tmp/data") is False

    def test_relative_path_not_cloud(self):
        assert DatabricksAdapter._is_cloud_uri("data/files") is False


class TestDetectShardedFiles:
    """Test _detect_sharded_files logic for multi-part file detection."""

    def _make_adapter(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            return DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="tok",
            )

    def test_detects_compressed_sharded_file(self, tmp_path):
        # Create sharded files: lineitem.tbl.1.zst, lineitem.tbl.2.zst
        (tmp_path / "lineitem.tbl.1.zst").write_bytes(b"data1")
        (tmp_path / "lineitem.tbl.2.zst").write_bytes(b"data2")

        adapter = self._make_adapter()
        is_sharded, pattern, chunk_files = adapter._detect_sharded_files(tmp_path / "lineitem.tbl.1.zst", "lineitem")
        assert is_sharded is True
        assert pattern == "lineitem.tbl.*.zst"
        assert len(chunk_files) == 2

    def test_detects_uncompressed_sharded_file(self, tmp_path):
        (tmp_path / "orders.tbl.1").write_bytes(b"data1")
        (tmp_path / "orders.tbl.2").write_bytes(b"data2")
        (tmp_path / "orders.tbl.3").write_bytes(b"data3")

        adapter = self._make_adapter()
        is_sharded, pattern, chunk_files = adapter._detect_sharded_files(tmp_path / "orders.tbl.1", "orders")
        assert is_sharded is True
        assert pattern == "orders.tbl.*"
        assert len(chunk_files) == 3

    def test_single_file_not_sharded(self, tmp_path):
        (tmp_path / "nation.csv").write_bytes(b"data")

        adapter = self._make_adapter()
        is_sharded, pattern, chunk_files = adapter._detect_sharded_files(tmp_path / "nation.csv", "nation")
        assert is_sharded is False


class TestManifestPatternForName:
    """Test _manifest_pattern_for_name static method."""

    def test_compressed_sharded_name(self):
        base, ext = DatabricksAdapter._manifest_pattern_for_name("lineitem.tbl.1.zst")
        assert base == "lineitem.tbl"
        assert ext == ".zst"

    def test_uncompressed_sharded_name(self):
        base, ext = DatabricksAdapter._manifest_pattern_for_name("orders.tbl.3")
        assert base == "orders.tbl"
        assert ext == ""

    def test_simple_filename(self):
        base, ext = DatabricksAdapter._manifest_pattern_for_name("nation.csv")
        assert base == "nation"
        assert ext == ".csv"


class TestDetectManifestWildcard:
    """Test _detect_manifest_wildcard for wildcard pattern generation."""

    def _make_adapter(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            return DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="tok",
            )

    def test_consistent_sharded_names_produce_wildcard(self):
        adapter = self._make_adapter()
        names = ["lineitem.tbl.1.zst", "lineitem.tbl.2.zst", "lineitem.tbl.3.zst"]
        result = adapter._detect_manifest_wildcard(names)
        assert result == "lineitem.tbl.*.zst"

    def test_inconsistent_names_return_none(self):
        adapter = self._make_adapter()
        names = ["lineitem.tbl.1.zst", "orders.tbl.2.zst"]
        result = adapter._detect_manifest_wildcard(names)
        assert result is None

    def test_uncompressed_sharded_wildcard(self):
        adapter = self._make_adapter()
        names = ["orders.tbl.1", "orders.tbl.2"]
        result = adapter._detect_manifest_wildcard(names)
        assert result == "orders.tbl.*"

    def test_non_sharded_part_files_do_not_produce_wildcard(self):
        adapter = self._make_adapter()
        names = ["part-00000.parquet", "part-00000.parquet"]
        result = adapter._detect_manifest_wildcard(names)
        assert result is None


class TestEnsureUcVolumeExists:
    """Test _ensure_uc_volume_exists SQL generation and error handling."""

    def _make_adapter(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            return DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="tok",
            )

    def test_creates_schema_and_volume(self):
        adapter = self._make_adapter()
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor

        adapter._ensure_uc_volume_exists("dbfs:/Volumes/my_cat/my_schema/my_vol", conn)

        calls = [c.args[0] for c in cursor.execute.call_args_list]
        assert calls[0] == "CREATE SCHEMA IF NOT EXISTS my_cat.my_schema"
        assert calls[1] == "CREATE VOLUME IF NOT EXISTS my_cat.my_schema.my_vol"

    def test_creates_volume_with_subpath(self):
        adapter = self._make_adapter()
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor

        adapter._ensure_uc_volume_exists("dbfs:/Volumes/cat/sch/vol/subdir/data", conn)

        calls = [c.args[0] for c in cursor.execute.call_args_list]
        assert calls[0] == "CREATE SCHEMA IF NOT EXISTS cat.sch"
        assert calls[1] == "CREATE VOLUME IF NOT EXISTS cat.sch.vol"

    def test_invalid_path_not_starting_with_volumes(self):
        adapter = self._make_adapter()
        conn = Mock()
        with pytest.raises(ValueError, match="Must start with dbfs:/Volumes/"):
            adapter._ensure_uc_volume_exists("dbfs:/some/other/path", conn)

    def test_incomplete_path_too_few_parts(self):
        adapter = self._make_adapter()
        conn = Mock()
        with pytest.raises(ValueError, match="Expected dbfs:/Volumes/catalog/schema/volume"):
            adapter._ensure_uc_volume_exists("dbfs:/Volumes/cat/sch", conn)

    def test_permission_denied_on_schema_creation(self):
        adapter = self._make_adapter()
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        cursor.execute.side_effect = Exception("permission denied")

        with pytest.raises(ValueError, match="Permission denied creating schema"):
            adapter._ensure_uc_volume_exists("dbfs:/Volumes/cat/sch/vol", conn)

    def test_permission_denied_on_volume_creation(self):
        adapter = self._make_adapter()
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor

        call_count = 0

        def side_effect(sql):
            nonlocal call_count
            call_count += 1
            if call_count == 2:  # Volume creation
                raise Exception("access denied to create volume")

        cursor.execute.side_effect = side_effect

        with pytest.raises(ValueError, match="Permission denied creating UC Volume"):
            adapter._ensure_uc_volume_exists("dbfs:/Volumes/cat/sch/vol", conn)


class TestGetExistingTables:
    """Test _get_existing_tables SQL generation."""

    def _make_adapter(self, catalog="test_catalog", schema="test_schema"):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            return DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="tok",
                catalog=catalog,
                schema=schema,
            )

    def test_returns_non_temporary_tables(self):
        adapter = self._make_adapter()
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        cursor.fetchall.return_value = [
            ("test_schema", "orders", False),
            ("test_schema", "lineitem", False),
            ("test_schema", "tmp_view", True),
        ]

        tables = adapter._get_existing_tables(conn)

        cursor.execute.assert_called_once_with("SHOW TABLES IN test_catalog.test_schema")
        assert tables == ["orders", "lineitem"]
        assert "tmp_view" not in tables

    def test_handles_error_returns_empty(self):
        adapter = self._make_adapter()
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        cursor.execute.side_effect = Exception("connection lost")

        tables = adapter._get_existing_tables(conn)

        assert tables == []


class TestUnityCatalogNaming:
    """Test three-level naming: catalog.schema.table in generated SQL."""

    def _make_adapter(self, catalog="analytics", schema="benchmarks"):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            return DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="tok",
                catalog=catalog,
                schema=schema,
            )

    def test_drop_database_uses_catalog_dot_schema(self):
        adapter = self._make_adapter(catalog="prod", schema="tpch_sf10")
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        with patch("benchbox.platforms.databricks.adapter.databricks_sql") as mock_sql:
            mock_sql.connect.return_value = conn
            adapter.drop_database()
        cursor.execute.assert_called_with("DROP SCHEMA IF EXISTS prod.tpch_sf10 CASCADE")

    def test_check_server_database_queries_catalog_then_schema(self):
        adapter = self._make_adapter(catalog="dev", schema="test_schema")
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        cursor.fetchall.side_effect = [
            [["dev"], ["other"]],
            [["test_schema"], ["default"]],
        ]
        with patch("benchbox.platforms.databricks.adapter.databricks_sql") as mock_sql:
            mock_sql.connect.return_value = conn
            result = adapter.check_server_database_exists()

        assert result is True
        calls = [c.args[0] for c in cursor.execute.call_args_list]
        assert calls[0] == "SHOW CATALOGS"
        assert calls[1] == "SHOW SCHEMAS IN dev"

    def test_create_schema_without_catalog_creation(self):
        """Schema creation SQL should use catalog.schema pattern."""
        adapter = self._make_adapter(catalog="workspace", schema="tpch_sf1")
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor

        mock_benchmark = Mock()

        with patch.object(adapter, "_create_schema_with_tuning", return_value="CREATE TABLE t (id INT)"):
            with patch.object(adapter, "_fix_databricks_sql_syntax", side_effect=lambda x: x):
                with patch.object(adapter, "_execute_schema_statements", return_value=(1, [])):
                    adapter.create_schema(mock_benchmark, conn)

        calls = [c.args[0] for c in cursor.execute.call_args_list]
        assert "CREATE SCHEMA IF NOT EXISTS workspace.tpch_sf1" in calls
        assert "USE CATALOG workspace" in calls
        assert "USE SCHEMA tpch_sf1" in calls

    def test_create_schema_with_catalog_creation(self):
        """When create_catalog=True, both catalog and schema creation SQL."""
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="tok",
                catalog="new_catalog",
                schema="new_schema",
                create_catalog=True,
            )

        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        mock_benchmark = Mock()

        with patch.object(adapter, "_create_schema_with_tuning", return_value="CREATE TABLE t (id INT)"):
            with patch.object(adapter, "_fix_databricks_sql_syntax", side_effect=lambda x: x):
                with patch.object(adapter, "_execute_schema_statements", return_value=(1, [])):
                    adapter.create_schema(mock_benchmark, conn)

        calls = [c.args[0] for c in cursor.execute.call_args_list]
        assert "CREATE CATALOG IF NOT EXISTS new_catalog" in calls
        assert "CREATE SCHEMA IF NOT EXISTS new_catalog.new_schema" in calls


class TestCopyIntoSqlGeneration:
    """Test COPY INTO SQL generation for various data formats."""

    def _make_adapter(self, **kwargs):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            defaults = {
                "server_hostname": "test.cloud.databricks.com",
                "http_path": "/sql/1.0/warehouses/test",
                "access_token": "tok",
                "catalog": "main",
                "schema": "bench",
            }
            defaults.update(kwargs)
            return DatabricksAdapter(**defaults)

    def test_copy_into_tbl_format_uses_pipe_delimiter(self):
        """TPC .tbl files should use pipe delimiter."""
        adapter = self._make_adapter()
        benchmark = Mock()
        benchmark.get_schema.return_value = {"lineitem": {"columns": [{"name": "l_orderkey"}, {"name": "l_partkey"}]}}
        cursor = Mock()
        cursor.fetchone.return_value = (1000,)
        conn = Mock()

        with patch.object(adapter, "get_effective_tuning_configuration", return_value=None):
            adapter._load_single_table(
                cursor,
                conn,
                benchmark,
                "lineitem",
                Path("lineitem.tbl"),
                "dbfs:/Volumes/main/bench/data",
                {"lineitem"},
            )

        copy_sql = cursor.execute.call_args_list[0].args[0]
        assert "COPY INTO LINEITEM" in copy_sql
        assert "'delimiter'='|'" in copy_sql
        assert "'header'='false'" in copy_sql

    def test_copy_into_csv_format_uses_comma_delimiter(self):
        """CSV files should use comma delimiter."""
        adapter = self._make_adapter()
        benchmark = Mock(spec=[])  # No get_schema
        cursor = Mock()
        cursor.fetchone.return_value = (500,)
        conn = Mock()

        with patch.object(adapter, "get_effective_tuning_configuration", return_value=None):
            adapter._load_single_table(
                cursor,
                conn,
                benchmark,
                "customers",
                Path("customers.csv"),
                "dbfs:/Volumes/main/bench/data",
                {"customers"},
            )

        copy_sql = cursor.execute.call_args_list[0].args[0]
        assert "COPY INTO CUSTOMERS" in copy_sql
        assert "'delimiter'=','" in copy_sql

    def test_copy_into_with_uc_volume_uri(self):
        """COPY INTO should use the UC Volume URI directly."""
        adapter = self._make_adapter()
        benchmark = Mock(spec=[])
        cursor = Mock()
        cursor.fetchone.return_value = (42,)
        conn = Mock()

        with patch.object(adapter, "get_effective_tuning_configuration", return_value=None):
            adapter._load_single_table(
                cursor,
                conn,
                benchmark,
                "region",
                "dbfs:/Volumes/main/bench/data/region.tbl",
                "dbfs:/Volumes/main/bench/data",
                {"region"},
            )

        copy_sql = cursor.execute.call_args_list[0].args[0]
        assert "'dbfs:/Volumes/main/bench/data/region.tbl'" in copy_sql

    def test_copy_into_with_wildcard_for_sharded(self):
        """Wildcard patterns should be passed through to COPY INTO."""
        adapter = self._make_adapter()
        benchmark = Mock(spec=[])
        cursor = Mock()
        cursor.fetchone.return_value = (9999,)
        conn = Mock()

        with patch.object(adapter, "get_effective_tuning_configuration", return_value=None):
            adapter._load_single_table(
                cursor,
                conn,
                benchmark,
                "lineitem",
                "dbfs:/Volumes/main/bench/data/lineitem.tbl.*",
                "dbfs:/Volumes/main/bench/data",
                {"lineitem"},
            )

        copy_sql = cursor.execute.call_args_list[0].args[0]
        assert "lineitem.tbl.*" in copy_sql

    def test_load_single_table_raises_when_table_missing(self):
        adapter = self._make_adapter()
        cursor = Mock()
        conn = Mock()
        benchmark = Mock(spec=[])

        with pytest.raises(RuntimeError, match="does not exist"):
            adapter._load_single_table(
                cursor,
                conn,
                benchmark,
                "nonexistent",
                Path("nonexistent.tbl"),
                "dbfs:/data",
                {"orders", "lineitem"},
            )

    def test_load_single_table_runs_optimize_when_delta_enabled(self):
        adapter = self._make_adapter(enable_delta_optimization=True)
        benchmark = Mock(spec=[])
        cursor = Mock()
        cursor.fetchone.return_value = (10,)
        conn = Mock()

        with patch.object(adapter, "get_effective_tuning_configuration", return_value=None):
            row_count, copy_time, optimize_time = adapter._load_single_table(
                cursor,
                conn,
                benchmark,
                "nation",
                Path("nation.tbl"),
                "dbfs:/data",
                {"nation"},
            )

        assert row_count == 10
        calls = [c.args[0] for c in cursor.execute.call_args_list]
        assert "OPTIMIZE NATION" in calls

    def test_load_single_table_skips_optimize_when_delta_disabled(self):
        adapter = self._make_adapter(enable_delta_optimization=False)
        benchmark = Mock(spec=[])
        cursor = Mock()
        cursor.fetchone.return_value = (10,)
        conn = Mock()

        with patch.object(adapter, "get_effective_tuning_configuration", return_value=None):
            row_count, copy_time, optimize_time = adapter._load_single_table(
                cursor,
                conn,
                benchmark,
                "nation",
                Path("nation.tbl"),
                "dbfs:/data",
                {"nation"},
            )

        assert row_count == 10
        assert optimize_time == 0.0
        calls = [c.args[0] for c in cursor.execute.call_args_list]
        assert "OPTIMIZE NATION" not in calls


class TestGetPlatformInfo:
    """Test get_platform_info metadata collection."""

    def _make_adapter(self, **kwargs):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            defaults = {
                "server_hostname": "test.cloud.databricks.com",
                "http_path": "/sql/1.0/warehouses/test",
                "access_token": "tok",
                "catalog": "main",
                "schema": "benchbox",
            }
            defaults.update(kwargs)
            return DatabricksAdapter(**defaults)

    def test_platform_info_without_connection(self):
        adapter = self._make_adapter()
        with patch.object(adapter, "get_effective_tuning_configuration", return_value=None):
            with patch.dict("sys.modules", {"databricks.sdk": None}):
                info = adapter.get_platform_info(connection=None)

        assert info["platform_type"] == "databricks"
        assert info["platform_name"] == "Databricks"
        assert info["connection_mode"] == "remote"
        assert info["host"] == "test.cloud.databricks.com"
        assert info["configuration"]["catalog"] == "main"
        assert info["configuration"]["schema"] == "benchbox"
        assert info["configuration"]["result_cache_enabled"] is False
        assert info["platform_version"] is None

    def test_platform_info_includes_delta_settings(self):
        adapter = self._make_adapter(
            enable_delta_optimization=True,
            delta_auto_optimize=True,
            delta_auto_compact=True,
        )
        with patch.object(adapter, "get_effective_tuning_configuration", return_value=None):
            with patch.dict("sys.modules", {"databricks.sdk": None}):
                info = adapter.get_platform_info(connection=None)

        config = info["configuration"]
        assert config["enable_delta_optimization"] is True
        assert config["delta_auto_optimize"] is True
        assert config["delta_auto_compact"] is True

    def test_platform_info_with_connection_queries_version(self):
        adapter = self._make_adapter()
        conn = Mock()
        cursor = Mock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = ["Runtime 14.3 LTS"]

        with patch.object(adapter, "get_effective_tuning_configuration", return_value=None):
            # Patch out the SDK import to avoid ImportError in warehouse metadata section
            with patch.dict("sys.modules", {"databricks.sdk": None}):
                info = adapter.get_platform_info(connection=conn)

        assert info["platform_version"] == "Runtime 14.3 LTS"
        assert info["engine_version"] == "Runtime 14.3 LTS"


class TestResolveDataFiles:
    """Test _resolve_databricks_data_files resolution logic."""

    def _make_adapter(self):
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            return DatabricksAdapter(
                server_hostname="test.cloud.databricks.com",
                http_path="/sql/1.0/warehouses/test",
                access_token="tok",
            )

    def test_delegates_to_resolver_and_normalizes_single_file_tables(self):
        adapter = self._make_adapter()
        benchmark = Mock()
        data_source = DataSource(
            source_type="manifest_v2",
            tables={"orders": [Path("/data/orders.tbl")], "lineitem": [Path("/data/lineitem.tbl")]},
            table_metadata={"orders": {"csv_delimiter": "|"}},
        )

        with patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_resolver_cls:
            mock_resolver = mock_resolver_cls.return_value
            mock_resolver.resolve.return_value = data_source

            result = adapter._resolve_databricks_data_files(benchmark, Path("/data"))

        mock_resolver_cls.assert_called_once_with(
            platform_name=adapter.platform_name,
            table_mode=adapter.table_mode,
            platform_config=adapter.platform_config,
            requested_format=None,
        )
        mock_resolver.resolve.assert_called_once_with(benchmark, Path("/data"))
        assert result.tables == {
            "orders": Path("/data/orders.tbl"),
            "lineitem": Path("/data/lineitem.tbl"),
        }
        # Manifest metadata must survive the normalization step so the COPY INTO
        # delimiter resolver still sees it downstream.
        assert result.table_metadata == {"orders": {"csv_delimiter": "|"}}
        # Resolver-owned object must not be mutated by the normalization step.
        assert data_source.tables == {
            "orders": [Path("/data/orders.tbl")],
            "lineitem": [Path("/data/lineitem.tbl")],
        }

    def test_preserves_multi_file_tables(self):
        adapter = self._make_adapter()
        benchmark = Mock()
        data_source = DataSource(
            source_type="manifest_v2",
            tables={
                "lineitem": [Path("/data/lineitem.tbl.1"), Path("/data/lineitem.tbl.2")],
            },
        )

        with patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_resolver_cls:
            mock_resolver_cls.return_value.resolve.return_value = data_source

            result = adapter._resolve_databricks_data_files(benchmark, Path("/data"))

        assert result.tables == {
            "lineitem": [Path("/data/lineitem.tbl.1"), Path("/data/lineitem.tbl.2")],
        }

    def test_raises_when_no_data_found(self, tmp_path):
        adapter = self._make_adapter()
        benchmark = Mock(spec=[])

        with patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_resolver_cls:
            mock_resolver_cls.return_value.resolve.return_value = None

            with pytest.raises(ValueError, match="No data files found"):
                adapter._resolve_databricks_data_files(benchmark, tmp_path)


class TestSelectDatabricksWarehouseEdgeCases:
    """Additional edge cases for _select_databricks_warehouse."""

    def test_all_deleted_returns_none(self):
        logger = Mock()
        d1 = Mock(name="del1", state="DELETED")
        d2 = Mock(name="del2", state="DELETING")
        result = _select_databricks_warehouse([d1, d2], very_verbose=False, logger=logger)
        assert result is None

    def test_verbose_logging_on_running_selection(self):
        logger = Mock()
        wh = Mock()
        wh.name = "prod-wh"
        wh.state = "RUNNING"
        result = _select_databricks_warehouse([wh], very_verbose=True, logger=logger)
        assert result is wh
        logger.info.assert_any_call("Selected running warehouse: prod-wh")


class TestFromConfigEdgeCases:
    """Test from_config placeholder detection and auto-detection paths."""

    def test_placeholder_hostname_triggers_auto_detect(self):
        """Config with placeholder hostname should trigger auto-detection."""
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            with patch.object(DatabricksAdapter, "_auto_detect_databricks_config", return_value=None):
                # Should fail because auto-detect returns None and credentials are placeholders
                from benchbox.core.exceptions import ConfigurationError

                with pytest.raises(ConfigurationError):
                    DatabricksAdapter.from_config(
                        {
                            "server_hostname": "your-workspace.cloud.databricks.com",
                            "http_path": "/sql/1.0/warehouses/your-warehouse-id",
                            "access_token": "test_token",
                        }
                    )

    def test_from_config_with_explicit_schema_override(self):
        """Explicit non-default schema should be preserved even with benchmark context."""
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter.from_config(
                {
                    "server_hostname": "test.cloud.databricks.com",
                    "http_path": "/sql/1.0/warehouses/test",
                    "access_token": "test_token",
                    "schema": "my_custom_schema",
                    "benchmark": "tpch",
                    "scale_factor": 1,
                }
            )
        assert adapter.schema == "my_custom_schema"

    def test_from_config_without_benchmark_context_uses_default(self):
        """Without benchmark context, schema falls back to provided or 'benchbox'."""
        with patch("benchbox.platforms.databricks.adapter.databricks_sql"):
            adapter = DatabricksAdapter.from_config(
                {
                    "server_hostname": "test.cloud.databricks.com",
                    "http_path": "/sql/1.0/warehouses/test",
                    "access_token": "test_token",
                }
            )
        assert adapter.schema == "benchbox"
