"""Tests for Databricks DataFrame platform adapter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import MagicMock, patch

import pytest

from benchbox.platforms.databricks.dataframe_adapter import (
    DATABRICKS_CONNECT_AVAILABLE,
    DatabricksDataFrameAdapter,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.cloud_import,
]


@pytest.fixture(autouse=True)
def databricks_dependencies():
    """Mock Databricks dependency check to simulate installed extras."""
    with patch(
        "benchbox.platforms.databricks.adapter.check_platform_dependencies",
        return_value=(True, []),
    ):
        yield


@pytest.fixture
def mock_databricks_sql():
    """Mock databricks.sql module."""
    with patch("benchbox.platforms.databricks.adapter.databricks_sql") as mock:
        yield mock


@pytest.fixture
def mock_databricks_connect():
    """Mock databricks.connect module."""
    mock_session = MagicMock()
    mock_session.version = "14.3.0"
    mock_session.catalog = MagicMock()

    mock_builder = MagicMock()
    mock_builder.host.return_value = mock_builder
    mock_builder.token.return_value = mock_builder
    mock_builder.clusterId.return_value = mock_builder
    mock_builder.getOrCreate.return_value = mock_session

    mock_db_session = MagicMock()
    mock_db_session.builder = mock_builder

    with (
        patch.dict(
            "sys.modules",
            {"databricks.connect": MagicMock(DatabricksSession=mock_db_session)},
        ),
        patch(
            "benchbox.platforms.databricks.dataframe_adapter.DATABRICKS_CONNECT_AVAILABLE",
            True,
        ),
        patch(
            "benchbox.platforms.databricks.dataframe_adapter.DatabricksSession",
            mock_db_session,
        ),
    ):
        yield mock_db_session, mock_session


class TestDatabricksDataFrameAdapterInitialization:
    """Test DatabricksDataFrameAdapter initialization."""

    def test_initialization_success(self, mock_databricks_sql):
        """Test successful adapter initialization."""
        adapter = DatabricksDataFrameAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
            catalog="test_catalog",
            schema="test_schema",
        )

        assert "Databricks" in adapter.platform_name
        assert adapter.server_hostname == "test.cloud.databricks.com"
        assert adapter.catalog == "test_catalog"
        assert adapter.schema == "test_schema"

    def test_initialization_with_cluster_id(self, mock_databricks_sql):
        """Test initialization with cluster ID for Databricks Connect."""
        adapter = DatabricksDataFrameAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
            cluster_id="0101-123456-abc123",
        )

        assert adapter.cluster_id == "0101-123456-abc123"

    def test_initialization_with_execution_mode(self, mock_databricks_sql):
        """Test initialization with different execution modes."""
        # SQL mode
        adapter_sql = DatabricksDataFrameAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
            execution_mode="sql",
        )
        assert adapter_sql.execution_mode == "sql"

        # DataFrame mode falls back to SQL when Databricks Connect not available
        adapter_df = DatabricksDataFrameAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
            execution_mode="dataframe",
        )
        # Falls back to SQL when Databricks Connect not installed
        if not DATABRICKS_CONNECT_AVAILABLE:
            assert adapter_df.execution_mode == "sql"

    def test_inheritance_from_databricks_adapter(self, mock_databricks_sql):
        """Test that DatabricksDataFrameAdapter inherits from DatabricksAdapter."""
        from benchbox.platforms.databricks import DatabricksAdapter

        adapter = DatabricksDataFrameAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        assert isinstance(adapter, DatabricksAdapter)
        assert hasattr(adapter, "create_connection")
        assert hasattr(adapter, "create_schema")
        assert hasattr(adapter, "load_data")


class TestDatabricksDataFrameAdapterFromConfig:
    """Test DatabricksDataFrameAdapter.from_config() method."""

    def test_from_config_basic(self, mock_databricks_sql):
        """Test from_config() with basic configuration."""
        config = {
            "server_hostname": "test.cloud.databricks.com",
            "http_path": "/sql/1.0/warehouses/test",
            "access_token": "test_token",
            "catalog": "test_catalog",
            "schema": "test_schema",
        }

        adapter = DatabricksDataFrameAdapter.from_config(config)

        assert adapter.server_hostname == "test.cloud.databricks.com"
        assert adapter.catalog == "test_catalog"
        assert adapter.schema == "test_schema"

    def test_from_config_with_execution_mode(self, mock_databricks_sql):
        """Test from_config() respects execution_mode setting."""
        config = {
            "server_hostname": "test.cloud.databricks.com",
            "http_path": "/sql/1.0/warehouses/test",
            "access_token": "test_token",
            "execution_mode": "sql",
        }

        adapter = DatabricksDataFrameAdapter.from_config(config)

        assert adapter.execution_mode == "sql"

    def test_from_config_with_cluster_id(self, mock_databricks_sql):
        """Test from_config() with cluster_id for Databricks Connect."""
        config = {
            "server_hostname": "test.cloud.databricks.com",
            "http_path": "/sql/1.0/warehouses/test",
            "access_token": "test_token",
            "cluster_id": "0101-123456-abc123",
        }

        adapter = DatabricksDataFrameAdapter.from_config(config)

        assert adapter.cluster_id == "0101-123456-abc123"


class TestDatabricksDataFrameAdapterPlatformInfo:
    """Test DatabricksDataFrameAdapter platform info methods."""

    def test_platform_name_sql_mode(self, mock_databricks_sql):
        """Test platform_name in SQL mode."""
        adapter = DatabricksDataFrameAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
            execution_mode="sql",
        )

        assert adapter.platform_name == "Databricks"

    def test_get_platform_info_includes_execution_mode(self, mock_databricks_sql):
        """Test get_platform_info() includes execution mode."""
        adapter = DatabricksDataFrameAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
            cluster_id="test-cluster",
        )

        with patch.dict("sys.modules", {"databricks.sdk": MagicMock()}):
            info = adapter.get_platform_info()

        assert "execution_mode" in info
        assert "cluster_id" in info
        assert info["cluster_id"] == "test-cluster"
        assert "databricks_connect_available" in info


class TestDatabricksDataFrameAdapterExpressionHelpers:
    """Test expression helper methods for DataFrame API compatibility."""

    def test_col_expression(self, mock_databricks_sql):
        """Test col() creates column expression."""
        adapter = DatabricksDataFrameAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        # Mock PySpark functions
        with patch(
            "benchbox.platforms.databricks.dataframe_adapter.PYSPARK_AVAILABLE",
            True,
        ):
            mock_col = MagicMock()
            with patch("benchbox.platforms.databricks.dataframe_adapter.F") as mock_f:
                mock_f.col = mock_col
                adapter.col("test_column")
                mock_col.assert_called_once_with("test_column")

    def test_lit_expression(self, mock_databricks_sql):
        """Test lit() creates literal expression."""
        adapter = DatabricksDataFrameAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        with patch(
            "benchbox.platforms.databricks.dataframe_adapter.PYSPARK_AVAILABLE",
            True,
        ):
            mock_lit = MagicMock()
            with patch("benchbox.platforms.databricks.dataframe_adapter.F") as mock_f:
                mock_f.lit = mock_lit
                adapter.lit(42)
                mock_lit.assert_called_once_with(42)

    def test_aggregation_expressions(self, mock_databricks_sql):
        """Test aggregation expression helpers."""
        adapter = DatabricksDataFrameAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        with patch(
            "benchbox.platforms.databricks.dataframe_adapter.PYSPARK_AVAILABLE",
            True,
        ):
            mock_sum = MagicMock()
            mock_avg = MagicMock()
            mock_count = MagicMock()
            mock_min = MagicMock()
            mock_max = MagicMock()
            mock_col = MagicMock(return_value="col_expr")

            with patch("benchbox.platforms.databricks.dataframe_adapter.F") as mock_f:
                mock_f.col = mock_col
                mock_f.sum = mock_sum
                mock_f.avg = mock_avg
                mock_f.count = mock_count
                mock_f.min = mock_min
                mock_f.max = mock_max

                adapter.sum_col("amount")
                mock_sum.assert_called_once()

                adapter.avg_col("price")
                mock_avg.assert_called_once()

                adapter.count_col("id")
                mock_count.assert_called()

                adapter.min_col("date")
                mock_min.assert_called_once()

                adapter.max_col("value")
                mock_max.assert_called_once()


class TestDatabricksDataFrameAdapterQueryExecution:
    """Test query execution methods."""

    def test_execute_query_with_sql_string(self, mock_databricks_sql):
        """Test execute_query() with SQL string uses parent implementation."""
        adapter = DatabricksDataFrameAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        # Mock connection and cursor
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(1, "test")]
        mock_connection = MagicMock()
        mock_connection.cursor.return_value = mock_cursor

        result = adapter.execute_query(
            connection=mock_connection,
            query="SELECT 1, 'test'",
            query_id="TEST1",
        )

        assert result["query_id"] == "TEST1"
        mock_cursor.execute.assert_called_once()

    def test_execute_query_with_callable_uses_dataframe_mode(self, mock_databricks_sql):
        """Test execute_query() with callable dispatches to DataFrame mode."""
        adapter = DatabricksDataFrameAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        # Mock the execute_dataframe_query method
        with patch.object(adapter, "execute_dataframe_query", return_value={"query_id": "Q1"}) as mock_df_exec:
            # Create a callable query builder
            def query_builder(spark, tables):
                return spark.table("test")

            result = adapter.execute_query(
                connection=MagicMock(),
                query=query_builder,
                query_id="Q1",
            )

            mock_df_exec.assert_called_once()
            assert result["query_id"] == "Q1"


class TestDatabricksDataFrameAdapterSparkSession:
    """Test Spark session management."""

    def test_spark_session_created_lazily(self, mock_databricks_sql):
        """Test Spark session is created lazily."""
        adapter = DatabricksDataFrameAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        # Session should not be created until accessed
        assert adapter._spark is None
        assert adapter._spark_initialized is False

    def test_close_connection_stops_spark_session(self, mock_databricks_sql):
        """Test close_connection() stops Spark session."""
        adapter = DatabricksDataFrameAdapter(
            server_hostname="test.cloud.databricks.com",
            http_path="/sql/1.0/warehouses/test",
            access_token="test_token",
        )

        # Simulate initialized session
        mock_spark = MagicMock()
        adapter._spark = mock_spark
        adapter._spark_initialized = True

        mock_connection = MagicMock()
        adapter.close_connection(mock_connection)

        mock_spark.stop.assert_called_once()
        assert adapter._spark is None
        assert adapter._spark_initialized is False


class TestDatabricksDataFrameAdapterRegistry:
    """Test platform registry integration."""

    def test_databricks_df_registered_in_platform_registry(self):
        """Test databricks-df is registered in platform registry."""
        from benchbox.core.platform_registry import PlatformRegistry

        available = PlatformRegistry.get_available_platforms()
        assert "databricks-df" in available

    def test_databricks_df_metadata_correct(self):
        """Test databricks-df metadata is correct."""
        from benchbox.core.platform_registry import PlatformRegistry

        info = PlatformRegistry.get_platform_info("databricks-df")

        assert info is not None
        assert info.display_name == "Databricks DataFrame"
        assert info.category == "cloud"
        assert "dataframe" in info.supports

    def test_databricks_df_capabilities_correct(self):
        """Test databricks-df capabilities are correct."""
        from benchbox.core.platform_registry import PlatformRegistry

        caps = PlatformRegistry.get_platform_capabilities("databricks-df")

        assert caps is not None
        assert caps.supports_sql is True
        assert caps.supports_dataframe is True
        assert caps.default_mode == "dataframe"

    def test_databricks_original_now_supports_dataframe(self):
        """Test original databricks adapter metadata updated for DataFrame support."""
        from benchbox.core.platform_registry import PlatformRegistry

        caps = PlatformRegistry.get_platform_capabilities("databricks")

        assert caps is not None
        assert caps.supports_sql is True
        assert caps.supports_dataframe is True
        assert caps.default_mode == "sql"


class TestDatabricksDataFrameAdapterIntegration:
    """Integration tests for DatabricksDataFrameAdapter."""

    def test_adapter_creates_with_from_config_factory(self, mock_databricks_sql):
        """Test adapter can be created via platform registry factory."""
        from benchbox.core.platform_registry import PlatformRegistry

        config = {
            "server_hostname": "test.cloud.databricks.com",
            "http_path": "/sql/1.0/warehouses/test",
            "access_token": "test_token",
            "catalog": "test_catalog",
            "schema": "test_schema",
        }

        adapter = PlatformRegistry.create_adapter("databricks-df", config)

        assert isinstance(adapter, DatabricksDataFrameAdapter)
        assert adapter.catalog == "test_catalog"
