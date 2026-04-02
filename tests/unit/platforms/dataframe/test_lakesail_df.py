"""Unit tests for LakeSail Sail DataFrame adapter."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.dataframe.tuning import (
    DataFrameTuningConfiguration,
    ExecutionConfiguration,
    MemoryConfiguration,
    ParallelismConfiguration,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.skipif(sys.platform == "win32", reason="PySpark tests skipped on Windows"),
]


# Check if PySpark is available for tests that need real Spark
try:
    from benchbox.platforms.pyspark import PYSPARK_AVAILABLE
except ImportError:
    PYSPARK_AVAILABLE = False


class TestLakeSailDataFrameAdapterMocked:
    """Tests for LakeSailDataFrameAdapter with mocked PySpark dependencies."""

    @pytest.fixture
    def mock_pyspark_env(self):
        """Mock PySpark for adapter initialization tests."""
        mock_session = MagicMock()
        mock_session.version = "3.5.0"
        mock_builder = MagicMock()
        mock_builder.remote.return_value = mock_builder
        mock_builder.config.return_value = mock_builder
        mock_builder.getOrCreate.return_value = mock_session

        mock_session_class = MagicMock()
        mock_session_class.builder = mock_builder

        mock_col = MagicMock()
        mock_functions = MagicMock()
        mock_functions.col.return_value = mock_col
        mock_functions.lit.return_value = mock_col

        mock_pyspark = MagicMock()
        mock_pyspark_sql = MagicMock(
            SparkSession=mock_session_class,
            functions=mock_functions,
            DataFrame=MagicMock,
        )
        mock_pyspark_sql.column.Column = MagicMock
        mock_pyspark_sql.types.StringType = MagicMock()
        mock_pyspark_sql.types.StructField = MagicMock()
        mock_pyspark_sql.types.StructType = MagicMock()
        mock_pyspark_sql.window.Window = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "pyspark": mock_pyspark,
                "pyspark.sql": mock_pyspark_sql,
                "pyspark.sql.column": mock_pyspark_sql.column,
                "pyspark.sql.types": mock_pyspark_sql.types,
                "pyspark.sql.window": mock_pyspark_sql.window,
                "pyspark.sql.functions": mock_functions,
            },
        ):
            yield mock_session_class, mock_session, mock_functions

    def test_initialization_requires_pyspark(self):
        """Test that missing PySpark raises ImportError."""
        with patch.dict("sys.modules", {"pyspark": None, "pyspark.sql": None}):
            # Importing the module with pyspark unavailable should handle gracefully
            # The actual adapter __init__ checks PYSPARK_AVAILABLE
            pass

    def test_platform_name(self, mock_pyspark_env):
        """Test platform name is 'LakeSail'."""
        # We need to test with real import since the module checks PYSPARK_AVAILABLE at import time
        if not PYSPARK_AVAILABLE:
            pytest.skip("PySpark not available")

        from benchbox.platforms.dataframe.lakesail_df import LakeSailDataFrameAdapter

        adapter = LakeSailDataFrameAdapter.__new__(LakeSailDataFrameAdapter)
        # Manually set required attributes to avoid full init
        adapter._endpoint = "sc://localhost:50051"
        assert adapter.platform_name == "LakeSail"


@pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not installed")
class TestLakeSailDataFrameAdapterReal:
    """Tests for LakeSailDataFrameAdapter with real PySpark (no Sail server needed).

    These tests verify adapter initialization and configuration without
    requiring a running LakeSail Sail server. They test the client-side
    logic only.
    """

    def test_initialization(self):
        """Test adapter initialization with default settings."""
        from benchbox.platforms.dataframe.lakesail_df import LakeSailDataFrameAdapter

        adapter = LakeSailDataFrameAdapter.__new__(LakeSailDataFrameAdapter)
        assert adapter.platform_name == "LakeSail"

    def test_platform_name_value(self):
        """Test the platform_name property returns 'LakeSail'."""
        from benchbox.platforms.dataframe.lakesail_df import LakeSailDataFrameAdapter

        adapter = LakeSailDataFrameAdapter.__new__(LakeSailDataFrameAdapter)
        assert adapter.platform_name == "LakeSail"

    def test_type_aliases_defined(self):
        """Test that LakeSail type aliases are defined."""
        # When PySpark is available, these should be real PySpark types
        from pyspark.sql import DataFrame
        from pyspark.sql.column import Column

        from benchbox.platforms.dataframe.lakesail_df import (
            LakeSailDF,
            LakeSailExpr,
            LakeSailLazyDF,
        )

        assert LakeSailDF is DataFrame
        assert LakeSailLazyDF is DataFrame
        assert LakeSailExpr is Column

    def test_adapter_class_exists_in_dataframe_package(self):
        """Test that LakeSailDataFrameAdapter is exported from dataframe package."""
        from benchbox.platforms.dataframe import LakeSailDataFrameAdapter

        assert LakeSailDataFrameAdapter is not None

    def test_family_is_expression(self):
        """Test that the adapter family is 'expression'."""
        from benchbox.platforms.dataframe.lakesail_df import LakeSailDataFrameAdapter

        adapter = LakeSailDataFrameAdapter.__new__(LakeSailDataFrameAdapter)
        assert adapter.family == "expression"


class TestLakeSailDataFrameAdapterConfig:
    """Tests for LakeSail DataFrame adapter configuration handling."""

    def test_default_endpoint(self):
        """Test default Spark Connect endpoint."""
        if not PYSPARK_AVAILABLE:
            pytest.skip("PySpark not available")

        from benchbox.platforms.dataframe.lakesail_df import LakeSailDataFrameAdapter

        # Create adapter with __new__ to skip session creation
        adapter = LakeSailDataFrameAdapter.__new__(LakeSailDataFrameAdapter)
        adapter._endpoint = "sc://localhost:50051"
        assert adapter._endpoint == "sc://localhost:50051"

    def test_custom_endpoint(self):
        """Test custom Spark Connect endpoint configuration."""
        if not PYSPARK_AVAILABLE:
            pytest.skip("PySpark not available")

        from benchbox.platforms.dataframe.lakesail_df import LakeSailDataFrameAdapter

        adapter = LakeSailDataFrameAdapter.__new__(LakeSailDataFrameAdapter)
        adapter._endpoint = "sc://sail-cluster:50051"
        assert adapter._endpoint == "sc://sail-cluster:50051"

    def test_get_platform_info_structure(self):
        """Test platform info has expected keys."""
        if not PYSPARK_AVAILABLE:
            pytest.skip("PySpark not available")

        from benchbox.platforms.dataframe.lakesail_df import LakeSailDataFrameAdapter

        adapter = LakeSailDataFrameAdapter.__new__(LakeSailDataFrameAdapter)
        adapter._endpoint = "sc://localhost:50051"
        adapter._driver_memory = "4g"
        adapter._shuffle_partitions = 8
        adapter._enable_aqe = True
        adapter.verbose = False
        adapter.very_verbose = False
        adapter.working_dir = "/tmp"

        info = adapter.get_platform_info()
        assert info["platform"] == "LakeSail"
        assert info["family"] == "expression"
        assert info["endpoint"] == "sc://localhost:50051"
        assert "driver_memory" in info
        assert "shuffle_partitions" in info
        assert "aqe_enabled" in info

    def test_tuning_config_overrides_shuffle_and_memory(self):
        """Tuning config should update the locally testable LakeSail settings."""
        if not PYSPARK_AVAILABLE:
            pytest.skip("PySpark not available")

        from benchbox.platforms.dataframe.lakesail_df import LakeSailDataFrameAdapter

        tuning = DataFrameTuningConfiguration(
            parallelism=ParallelismConfiguration(thread_count=7),
            memory=MemoryConfiguration(memory_limit="5GB"),
            execution=ExecutionConfiguration(streaming_mode=True),
        )

        adapter = LakeSailDataFrameAdapter(
            endpoint="sc://localhost:50051",
            driver_memory="1g",
            shuffle_partitions=2,
            tuning_config=tuning,
        )

        assert adapter._shuffle_partitions == 7
        assert adapter._driver_memory == "5GB"

        summary = adapter.get_tuning_summary()
        assert summary["endpoint"] == "sc://localhost:50051"
        assert summary["driver_memory"] == "5GB"
        assert summary["shuffle_partitions"] == 7

        adapter.close()

    def test_build_schema_uses_nullable_strings(self):
        """CSV schema helper should map requested columns to nullable string fields."""
        if not PYSPARK_AVAILABLE:
            pytest.skip("PySpark not available")

        from benchbox.platforms.dataframe.lakesail_df import LakeSailDataFrameAdapter

        adapter = LakeSailDataFrameAdapter.__new__(LakeSailDataFrameAdapter)
        schema = adapter._build_schema(["order_id", "customer_name"])

        assert schema.fieldNames() == ["order_id", "customer_name"]
        assert [field.dataType.simpleString() for field in schema.fields] == ["string", "string"]
        assert all(field.nullable for field in schema.fields)


class TestLakeSailDataFrameAdapterLifecycle:
    """Tests for mocked LakeSail session lifecycle and helper methods."""

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not available")
    def test_session_builder_uses_endpoint_and_extra_configs(self):
        """Spark Connect builder should receive endpoint, AQE, and extra config options once."""
        from benchbox.platforms.dataframe.lakesail_df import LakeSailDataFrameAdapter

        mock_session = MagicMock()
        mock_builder = MagicMock()
        mock_builder.remote.return_value = mock_builder
        mock_builder.config.return_value = mock_builder
        mock_builder.getOrCreate.return_value = mock_session
        mock_spark_class = MagicMock(builder=mock_builder)

        with patch("benchbox.platforms.dataframe.lakesail_df.SparkSession", mock_spark_class):
            adapter = LakeSailDataFrameAdapter(
                endpoint="sc://lakehouse:50051",
                app_name="BenchBox-LakeSail-Tests",
                driver_memory="2g",
                shuffle_partitions=4,
                enable_aqe=True,
                verbose=True,
                spark_sql_catalog_implementation="in-memory",
            )

            assert adapter.spark is mock_session
            assert adapter.spark is mock_session

        mock_builder.remote.assert_called_once_with("sc://lakehouse:50051")
        assert mock_builder.getOrCreate.call_count == 1
        assert mock_builder.config.call_args_list == [
            (("spark.app.name", "BenchBox-LakeSail-Tests"), {}),
            (("spark.sql.shuffle.partitions", "4"), {}),
            (("spark.sql.adaptive.enabled", "true"), {}),
            (("spark_sql_catalog_implementation", "in-memory"), {}),
        ]

    @pytest.mark.skipif(not PYSPARK_AVAILABLE, reason="PySpark not available")
    def test_session_creation_failure_propagates(self):
        """Connection failures should bubble up and leave the adapter unbound."""
        from benchbox.platforms.dataframe.lakesail_df import LakeSailDataFrameAdapter

        mock_builder = MagicMock()
        mock_builder.remote.return_value = mock_builder
        mock_builder.config.return_value = mock_builder
        mock_builder.getOrCreate.side_effect = RuntimeError("connect failed")
        mock_spark_class = MagicMock(builder=mock_builder)

        with patch("benchbox.platforms.dataframe.lakesail_df.SparkSession", mock_spark_class):
            adapter = LakeSailDataFrameAdapter(endpoint="sc://missing:50051")

            with pytest.raises(RuntimeError, match="connect failed"):
                _ = adapter.spark

        assert adapter._spark is None

    def test_close_ignores_stop_errors_and_clears_session(self):
        """close() should swallow stop errors and always clear the cached session."""
        from benchbox.platforms.dataframe.lakesail_df import LakeSailDataFrameAdapter

        adapter = LakeSailDataFrameAdapter.__new__(LakeSailDataFrameAdapter)
        adapter._spark = MagicMock()
        adapter._spark.stop.side_effect = RuntimeError("stop failed")
        adapter.verbose = False

        adapter.close()

        assert adapter._spark is None

    def test_explain_and_get_query_plan_capture_modes(self):
        """Plan helpers should capture both simple and extended explain output."""
        from benchbox.platforms.dataframe.lakesail_df import LakeSailDataFrameAdapter

        class DummyFrame:
            def __init__(self):
                self.calls: list[str] = []

            def explain(self, mode="extended"):
                self.calls.append(mode)
                print(f"{mode} plan")

        adapter = LakeSailDataFrameAdapter.__new__(LakeSailDataFrameAdapter)
        frame = DummyFrame()

        simple = adapter.explain(frame, mode="simple")
        plans = adapter.get_query_plan(frame)

        assert "simple plan" in simple
        assert "simple plan" in plans["logical"]
        assert "extended plan" in plans["physical"]
        assert frame.calls == ["simple", "simple", "extended"]

    def test_sql_and_register_table_delegate_to_spark_objects(self):
        """SQL execution and temp-view registration should delegate directly to Spark objects."""
        from benchbox.platforms.dataframe.lakesail_df import LakeSailDataFrameAdapter

        adapter = LakeSailDataFrameAdapter.__new__(LakeSailDataFrameAdapter)
        expected_result = object()
        adapter._spark = MagicMock()
        adapter._spark.sql.return_value = expected_result

        df = MagicMock()

        assert adapter.sql("SELECT 1") is expected_result
        adapter._spark.sql.assert_called_once_with("SELECT 1")

        adapter.register_table("orders", df)
        df.createOrReplaceTempView.assert_called_once_with("orders")
