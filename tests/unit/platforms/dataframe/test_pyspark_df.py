"""Unit tests for PySpark DataFrame adapter.

Tests for:
- PySparkDataFrameAdapter initialization
- Expression methods (col, lit, date operations)
- Data loading (CSV, Parquet)
- Query execution
- Window functions
- Session lifecycle

Note: PySpark 4.x requires Java 17 or 21. Tests use centralized Java version
detection that automatically switches to a compatible Java installation.

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory
from benchbox.core.dataframe.tuning import (
    DataFrameTuningConfiguration,
    ExecutionConfiguration,
    MemoryConfiguration,
    ParallelismConfiguration,
)
from benchbox.platforms.pyspark import (
    PYSPARK_AVAILABLE,
    ensure_compatible_java,
    get_java_skip_reason,
    is_java_compatible,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="PySpark tests skipped on Windows - Hadoop requires winutils.exe setup",
    ),
]


# Ensure compatible Java is configured at import time
# This allows skipif decorators to evaluate correctly
_java_version, _java_home = ensure_compatible_java()

# Skip conditions for PySpark tests
_SKIP_PYSPARK = not PYSPARK_AVAILABLE or not is_java_compatible(_java_version)
_SKIP_REASON = get_java_skip_reason() or "PySpark tests enabled"

# Check if PySpark is available and import adapter
if PYSPARK_AVAILABLE:
    from pyspark.sql import SparkSession

    from benchbox.platforms.dataframe.pyspark_df import PySparkDataFrameAdapter
else:
    SparkSession = None  # type: ignore[assignment,misc]
    PySparkDataFrameAdapter = None  # type: ignore[assignment,misc]


@pytest.mark.skipif(_SKIP_PYSPARK, reason=_SKIP_REASON)
class TestPySparkDataFrameAdapter:
    """Tests for PySparkDataFrameAdapter."""

    @pytest.fixture(scope="class")
    def adapter(self):
        """Create adapter fixture with shared SparkSession."""
        adapter = PySparkDataFrameAdapter(
            master="local[2]",
            app_name="BenchBox-Tests",
            driver_memory="1g",
            shuffle_partitions=2,
            verbose=False,
        )
        yield adapter
        adapter.close()

    def test_initialization(self, adapter):
        """Test adapter initialization."""
        assert adapter.platform_name == "PySpark"
        assert adapter.family == "expression"

    def test_initialization_with_options(self):
        """Test adapter initialization with custom options."""
        adapter = PySparkDataFrameAdapter(
            working_dir="/tmp/pyspark",
            verbose=True,
            master="local[4]",
            app_name="CustomApp",
            driver_memory="2g",
            shuffle_partitions=4,
            enable_aqe=False,
        )

        assert adapter.working_dir == Path("/tmp/pyspark")
        assert adapter.verbose is True
        assert adapter._master == "local[4]"
        assert adapter._app_name == "CustomApp"
        assert adapter._driver_memory == "2g"
        assert adapter._shuffle_partitions == 4
        assert adapter._enable_aqe is False

        adapter.close()

    def test_platform_info(self, adapter):
        """Test get_platform_info method."""
        info = adapter.get_platform_info()

        assert info["platform"] == "PySpark"
        assert info["family"] == "expression"
        assert "master" in info
        assert "driver_memory" in info
        assert "shuffle_partitions" in info

    def test_create_context(self, adapter):
        """Test context creation."""
        ctx = adapter.create_context()

        assert ctx.platform == "PySpark"
        assert ctx.family == "expression"

    def test_session_lifecycle(self):
        """Test SparkSession lifecycle management."""
        adapter = PySparkDataFrameAdapter(
            master="local[1]",
            driver_memory="512m",
        )

        # Session is created lazily
        assert adapter._spark is None

        # Access spark property to trigger creation
        session = adapter.spark
        assert hasattr(session, "sql"), "SparkSession should have sql method"
        assert adapter._spark is not None

        # Close should stop session
        adapter.close()
        assert adapter._spark is None

    def test_context_manager(self):
        """Test context manager protocol for automatic cleanup."""
        with PySparkDataFrameAdapter(
            master="local[1]",
            driver_memory="512m",
        ) as adapter:
            # Session should be available
            session = adapter.spark
            assert hasattr(session, "sql"), "SparkSession should have sql method"
            assert adapter._spark is not None

        # After context manager exit, session should be stopped
        assert adapter._spark is None

    def test_version_without_session(self):
        """Test that version is available without creating SparkSession."""
        adapter = PySparkDataFrameAdapter(
            master="local[1]",
            driver_memory="512m",
        )

        # Session should NOT be created yet
        assert adapter._spark is None

        # But version should be available
        info = adapter.get_platform_info()
        assert "version" in info
        assert isinstance(info["version"], str) and len(info["version"]) > 0

        # Session should still NOT be created (lazy)
        assert adapter._spark is None

        adapter.close()


@pytest.mark.skipif(_SKIP_PYSPARK, reason=_SKIP_REASON)
class TestPySparkDataFrameAdapterConfigAndLifecycle:
    """Targeted configuration and lifecycle tests for the adapter stub behavior."""

    def test_tuning_config_overrides_parallelism_and_memory(self):
        """Tuning config should adjust local master, partitions, and driver memory."""
        tuning = DataFrameTuningConfiguration(
            parallelism=ParallelismConfiguration(thread_count=6),
            memory=MemoryConfiguration(memory_limit="3GB"),
            execution=ExecutionConfiguration(streaming_mode=True),
        )

        adapter = PySparkDataFrameAdapter(
            master="local[2]",
            driver_memory="1g",
            shuffle_partitions=2,
            tuning_config=tuning,
            verbose=False,
        )

        assert adapter._master == "local[6]"
        assert adapter._shuffle_partitions == 6
        assert adapter._driver_memory == "3GB"

        summary = adapter.get_tuning_summary()
        assert summary["master"] == "local[6]"
        assert summary["driver_memory"] == "3GB"
        assert summary["shuffle_partitions"] == 6

        adapter.close()

    @patch("benchbox.platforms.dataframe.pyspark_df.SparkSessionManager.release")
    @patch("benchbox.platforms.dataframe.pyspark_df.SparkSessionManager.get_or_create")
    def test_lazy_session_creation_passes_expected_settings(self, mock_get_or_create, mock_release):
        """SparkSessionManager should be called once with the adapter's resolved settings."""
        mock_session = MagicMock()
        mock_session.sparkContext.master = "local[3]"
        mock_get_or_create.return_value = mock_session

        adapter = PySparkDataFrameAdapter(
            master="local[3]",
            app_name="BenchBox-PySpark-Stub",
            driver_memory="2g",
            executor_memory="1g",
            shuffle_partitions=5,
            enable_aqe=False,
            verbose=True,
            spark_sql_catalog_implementation="in-memory",
        )

        assert adapter._spark is None
        assert adapter._session_claimed is False

        session = adapter.spark

        assert session is mock_session
        assert adapter.spark is mock_session
        mock_get_or_create.assert_called_once_with(
            master="local[3]",
            app_name="BenchBox-PySpark-Stub",
            driver_memory="2g",
            executor_memory="1g",
            shuffle_partitions=5,
            enable_aqe=False,
            extra_configs={"spark_sql_catalog_implementation": "in-memory"},
            verbose=True,
        )
        assert adapter._session_claimed is True

        adapter.close()
        adapter.close()

        mock_release.assert_called_once_with()
        assert adapter._spark is None
        assert adapter._session_claimed is False

    @patch("benchbox.platforms.dataframe.pyspark_df.SparkSessionManager.get_or_create")
    def test_session_creation_failure_does_not_claim_session(self, mock_get_or_create):
        """Failed session creation should bubble up without mutating lifecycle state."""
        mock_get_or_create.side_effect = RuntimeError("spark init failed")

        adapter = PySparkDataFrameAdapter(master="local[1]", driver_memory="512m")

        with pytest.raises(RuntimeError, match="spark init failed"):
            _ = adapter.spark

        assert adapter._spark is None
        assert adapter._session_claimed is False

    def test_build_schema_uses_string_fields(self):
        """CSV schema helper should map every requested column to nullable strings."""
        adapter = PySparkDataFrameAdapter(master="local[1]", driver_memory="512m")

        schema = adapter._build_schema(["order_id", "customer_name"])

        assert schema.fieldNames() == ["order_id", "customer_name"]
        assert [field.dataType.simpleString() for field in schema.fields] == ["string", "string"]
        assert all(field.nullable for field in schema.fields)

        adapter.close()


@pytest.mark.skipif(_SKIP_PYSPARK, reason=_SKIP_REASON)
class TestPySparkExpressionMethods:
    """Tests for PySpark expression methods."""

    @pytest.fixture(scope="class")
    def adapter(self):
        """Create adapter fixture."""
        adapter = PySparkDataFrameAdapter(
            master="local[2]",
            driver_memory="1g",
        )
        yield adapter
        adapter.close()

    def test_col(self, adapter):
        """Test col() creates a PySpark column expression."""
        expr = adapter.col("amount")
        aliased = expr.alias("amt")
        assert aliased is not None
        assert str(aliased) != str(expr)  # alias changes repr

    def test_lit_integer(self, adapter):
        """Test lit() with integer value."""
        expr = adapter.lit(100)
        assert expr.alias("v") is not None

    def test_lit_string(self, adapter):
        """Test lit() with string value."""
        expr = adapter.lit("test")
        assert expr.alias("v") is not None

    def test_lit_float(self, adapter):
        """Test lit() with float value."""
        expr = adapter.lit(3.14)
        assert expr.alias("v") is not None

    def test_cast_date(self, adapter):
        """Test cast_date() method."""
        expr = adapter.cast_date(adapter.col("date_str"))
        assert expr.alias("d") is not None

    def test_cast_string(self, adapter):
        """Test cast_string() method."""
        expr = adapter.cast_string(adapter.col("number"))
        assert expr.alias("s") is not None

    def test_date_sub(self, adapter):
        """Test date_sub() method."""
        expr = adapter.date_sub(adapter.col("date"), 7)
        assert expr.alias("ds") is not None

    def test_date_add(self, adapter):
        """Test date_add() method."""
        expr = adapter.date_add(adapter.col("date"), 30)
        assert expr.alias("da") is not None


@pytest.mark.skipif(_SKIP_PYSPARK, reason=_SKIP_REASON)
class TestPySparkAggregationMethods:
    """Tests for PySpark aggregation helper methods."""

    @pytest.fixture(scope="class")
    def adapter(self):
        """Create adapter fixture."""
        adapter = PySparkDataFrameAdapter(
            master="local[2]",
            driver_memory="1g",
        )
        yield adapter
        adapter.close()

    def test_sum(self, adapter):
        """Test sum() method."""
        expr = adapter.sum("amount")
        assert expr.alias("total") is not None

    def test_mean(self, adapter):
        """Test mean() method."""
        expr = adapter.mean("amount")
        assert expr.alias("avg") is not None

    def test_count(self, adapter):
        """Test count() method."""
        expr = adapter.count("amount")
        assert expr.alias("cnt") is not None

    def test_count_star(self, adapter):
        """Test count() method without column (COUNT(*))."""
        expr = adapter.count()
        assert expr.alias("cnt") is not None

    def test_min(self, adapter):
        """Test min() method."""
        expr = adapter.min("amount")
        assert expr.alias("min_val") is not None

    def test_max(self, adapter):
        """Test max() method."""
        expr = adapter.max("amount")
        assert expr.alias("max_val") is not None

    def test_when(self, adapter):
        """Test when() conditional method."""
        when_expr = adapter.when(adapter.col("amount") > adapter.lit(100))
        assert when_expr.alias("flag") is not None

    def test_concat_str(self, adapter):
        """Test concat_str() method."""
        expr = adapter.concat_str("first", "last", separator=" ")
        assert expr.alias("full_name") is not None

    def test_concat_str_no_separator(self, adapter):
        """Test concat_str() method without separator."""
        expr = adapter.concat_str("first", "last")
        assert expr.alias("combined") is not None

    def test_aggregation_in_groupby(self, adapter):
        """Test aggregation methods work in group_by operations."""
        test_df = adapter.spark.createDataFrame(
            [("A", 10), ("A", 20), ("B", 30), ("B", 40)],
            ["category", "value"],
        )

        result = test_df.groupBy("category").agg(
            adapter.sum("value").alias("total"),
            adapter.mean("value").alias("avg"),
            adapter.count("value").alias("cnt"),
            adapter.min("value").alias("min_val"),
            adapter.max("value").alias("max_val"),
        )

        collected = result.collect()
        assert len(collected) == 2

        # Verify the aggregations
        results_dict = {row.category: row for row in collected}
        assert results_dict["A"].total == 30
        assert results_dict["B"].total == 70


@pytest.mark.skipif(_SKIP_PYSPARK, reason=_SKIP_REASON)
class TestPySparkDataLoading:
    """Tests for PySpark data loading methods."""

    @pytest.fixture(scope="class")
    def adapter(self):
        """Create adapter fixture."""
        adapter = PySparkDataFrameAdapter(
            master="local[2]",
            driver_memory="1g",
        )
        yield adapter
        adapter.close()

    def test_read_csv_basic(self, adapter, tmp_path):
        """Test reading a basic CSV file."""
        # Create a test CSV file
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("id,name,amount\n1,Alice,100\n2,Bob,200\n")

        df = adapter.read_csv(csv_path)

        # PySpark DataFrames are lazy - count triggers execution
        count = adapter.get_row_count(df)
        assert count == 2
        assert len(df.columns) == 3

    def test_read_csv_with_delimiter(self, adapter, tmp_path):
        """Test reading CSV with custom delimiter."""
        # Create a pipe-delimited file
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("id|name|amount\n1|Alice|100\n2|Bob|200\n")

        df = adapter.read_csv(csv_path, delimiter="|")

        count = adapter.get_row_count(df)
        assert count == 2

    def test_read_parquet(self, adapter, tmp_path):
        """Test reading a Parquet file."""
        # Create a test Parquet file using Spark itself
        parquet_path = tmp_path / "test.parquet"

        # Create a simple DataFrame and write to parquet
        test_df = adapter.spark.createDataFrame(
            [(1, "A", 100.0), (2, "B", 200.0), (3, "C", 300.0)],
            ["id", "name", "amount"],
        )
        test_df.write.mode("overwrite").parquet(str(parquet_path))

        df = adapter.read_parquet(parquet_path)

        count = adapter.get_row_count(df)
        assert count == 3

    def test_collect_dataframe(self, adapter):
        """Test collecting a DataFrame."""
        # Create a test DataFrame
        test_df = adapter.spark.createDataFrame(
            [(1, "A"), (2, "B"), (3, "C")],
            ["id", "name"],
        )

        result = adapter.collect(test_df)

        # collect() should return the same DataFrame (Spark is always lazy)
        assert adapter.get_row_count(result) == 3

    def test_get_row_count(self, adapter):
        """Test getting row count from DataFrame."""
        test_df = adapter.spark.createDataFrame(
            [(i,) for i in range(5)],
            ["value"],
        )

        count = adapter.get_row_count(test_df)

        assert count == 5


@pytest.mark.skipif(_SKIP_PYSPARK, reason=_SKIP_REASON)
class TestPySparkWindowFunctions:
    """Tests for PySpark window functions."""

    @pytest.fixture(scope="class")
    def adapter(self):
        """Create adapter fixture."""
        adapter = PySparkDataFrameAdapter(
            master="local[2]",
            driver_memory="1g",
        )
        yield adapter
        adapter.close()

    @pytest.fixture(scope="class")
    def test_df(self, adapter):
        """Create test DataFrame for window function tests."""
        return adapter.spark.createDataFrame(
            [
                ("A", 1, 10),
                ("A", 2, 20),
                ("B", 1, 30),
                ("B", 2, 40),
            ],
            ["category", "rank", "value"],
        )

    def test_window_row_number(self, adapter, test_df):
        """Test row_number window function returns valid expression."""
        expr = adapter.window_row_number(
            order_by=[("value", True)],
            partition_by=["category"],
        )
        assert hasattr(expr, "alias")

        # Apply the expression
        result = test_df.select(
            adapter.col("category"),
            adapter.col("value"),
            expr.alias("rn"),
        )
        collected = result.collect()
        assert len(collected) == 4
        assert "rn" in result.columns

    def test_window_rank(self, adapter, test_df):
        """Test rank window function returns valid expression."""
        expr = adapter.window_rank(
            order_by=[("value", True)],
            partition_by=["category"],
        )
        assert hasattr(expr, "alias")

        result = test_df.select(
            adapter.col("category"),
            expr.alias("rnk"),
        )
        assert "rnk" in result.columns

    def test_window_dense_rank(self, adapter, test_df):
        """Test dense_rank window function returns valid expression."""
        expr = adapter.window_dense_rank(
            order_by=[("value", True)],
            partition_by=["category"],
        )
        assert hasattr(expr, "alias")

        result = test_df.select(
            adapter.col("category"),
            expr.alias("drnk"),
        )
        assert "drnk" in result.columns

    def test_window_sum(self, adapter, test_df):
        """Test window sum function returns valid expression."""
        expr = adapter.window_sum(
            column="value",
            partition_by=["category"],
        )
        assert hasattr(expr, "alias")

        result = test_df.select(
            adapter.col("category"),
            expr.alias("total"),
        )
        assert "total" in result.columns
        # Check values: category A should have 30 (10+20), B should have 70 (30+40)
        collected = result.select("category", "total").distinct().collect()
        totals = {row.category: row.total for row in collected}
        assert totals["A"] == 30
        assert totals["B"] == 70

    def test_window_avg(self, adapter, test_df):
        """Test window avg function returns valid expression."""
        expr = adapter.window_avg(
            column="value",
            partition_by=["category"],
        )
        assert hasattr(expr, "alias")

        result = test_df.select(
            adapter.col("category"),
            expr.alias("avg_val"),
        )
        assert "avg_val" in result.columns

    def test_window_count(self, adapter, test_df):
        """Test window count function returns valid expression."""
        expr = adapter.window_count(
            column="value",
            partition_by=["category"],
        )
        assert hasattr(expr, "alias")

        result = test_df.select(
            adapter.col("category"),
            expr.alias("cnt"),
        )
        assert "cnt" in result.columns


@pytest.mark.skipif(_SKIP_PYSPARK, reason=_SKIP_REASON)
class TestPySparkDataFrameOperations:
    """Tests for PySpark DataFrame operations."""

    @pytest.fixture(scope="class")
    def adapter(self):
        """Create adapter fixture."""
        adapter = PySparkDataFrameAdapter(
            master="local[2]",
            driver_memory="1g",
        )
        yield adapter
        adapter.close()

    def test_union_all(self, adapter):
        """Test union_all operation."""
        df1 = adapter.spark.createDataFrame([(1,), (2,)], ["a"])
        df2 = adapter.spark.createDataFrame([(3,), (4,)], ["a"])

        combined = adapter.union_all(df1, df2)

        count = adapter.get_row_count(combined)
        assert count == 4

    def test_union_all_single(self, adapter):
        """Test union_all with single DataFrame."""
        df1 = adapter.spark.createDataFrame([(1,), (2,)], ["a"])

        result = adapter.union_all(df1)

        assert result is df1

    def test_union_all_empty_raises(self, adapter):
        """Test union_all with no DataFrames raises error."""
        with pytest.raises(ValueError, match="At least one DataFrame"):
            adapter.union_all()

    def test_rename_columns(self, adapter):
        """Test rename_columns operation."""
        df = adapter.spark.createDataFrame([(1, 2, 3)], ["old_a", "old_b", "old_c"])

        renamed = adapter.rename_columns(df, {"old_a": "new_a", "old_b": "new_b"})

        assert "new_a" in renamed.columns
        assert "new_b" in renamed.columns
        assert "old_a" not in renamed.columns
        assert "old_b" not in renamed.columns
        assert "old_c" in renamed.columns  # Unchanged


@pytest.mark.skipif(_SKIP_PYSPARK, reason=_SKIP_REASON)
class TestPySparkQueryExecution:
    """Tests for query execution with PySpark."""

    @pytest.fixture(scope="class")
    def adapter(self):
        """Create adapter fixture."""
        adapter = PySparkDataFrameAdapter(
            master="local[2]",
            driver_memory="1g",
        )
        yield adapter
        adapter.close()

    def test_simple_select_query(self, adapter):
        """Test executing a simple select query."""
        ctx = adapter.create_context()

        # Create and register test data
        test_df = adapter.spark.createDataFrame(
            [(1, "Alice", 100), (2, "Bob", 200), (3, "Charlie", 300)],
            ["id", "name", "amount"],
        )
        ctx.register_table("customers", test_df)

        def select_impl(ctx):
            customers = ctx.get_table("customers")
            return customers.select(ctx.col("id"), ctx.col("name"))

        query = DataFrameQuery(
            query_id="SELECT1",
            query_name="Select ID and Name",
            description="Select id and name columns",
            expression_impl=select_impl,
        )

        result = adapter.execute_query(ctx, query)

        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 3

    def test_filter_query(self, adapter):
        """Test executing a filter query."""
        ctx = adapter.create_context()

        test_df = adapter.spark.createDataFrame(
            [(1, 50), (2, 150), (3, 75), (4, 200), (5, 100)],
            ["id", "amount"],
        )
        ctx.register_table("orders", test_df)

        def filter_impl(ctx):
            orders = ctx.get_table("orders")
            return orders.filter(ctx.col("amount") > ctx.lit(100))

        query = DataFrameQuery(
            query_id="FILTER1",
            query_name="Filter by Amount",
            description="Filter orders over 100",
            categories=[QueryCategory.FILTER],
            expression_impl=filter_impl,
        )

        result = adapter.execute_query(ctx, query)

        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2  # 150 and 200


@pytest.mark.skipif(_SKIP_PYSPARK, reason=_SKIP_REASON)
class TestPySparkTableLoading:
    """Tests for table loading functionality."""

    @pytest.fixture(scope="class")
    def adapter(self):
        """Create adapter fixture."""
        adapter = PySparkDataFrameAdapter(
            master="local[2]",
            driver_memory="1g",
        )
        yield adapter
        adapter.close()

    def test_load_table_parquet(self, adapter, tmp_path):
        """Test loading a table from Parquet."""
        ctx = adapter.create_context()

        # Create test data using Spark
        parquet_path = tmp_path / "orders.parquet"
        test_df = adapter.spark.createDataFrame(
            [(1, 100), (2, 200), (3, 300)],
            ["id", "amount"],
        )
        test_df.write.mode("overwrite").parquet(str(parquet_path))

        row_count = adapter.load_table(ctx, "orders", [parquet_path])

        assert ctx.table_exists("orders")
        assert row_count == 3

    def test_load_table_csv(self, adapter, tmp_path):
        """Test loading a table from CSV."""
        ctx = adapter.create_context()

        # Create test data
        csv_path = tmp_path / "customers.csv"
        csv_path.write_text("id,name\n1,Alice\n2,Bob\n")

        row_count = adapter.load_table(ctx, "customers", [csv_path])

        assert ctx.table_exists("customers")
        assert row_count == 2


@pytest.mark.skipif(_SKIP_PYSPARK, reason=_SKIP_REASON)
class TestPySparkSpecificFeatures:
    """Tests for PySpark-specific features."""

    @pytest.fixture(scope="class")
    def adapter(self):
        """Create adapter fixture."""
        adapter = PySparkDataFrameAdapter(
            master="local[2]",
            driver_memory="1g",
        )
        yield adapter
        adapter.close()

    def test_sql_execution(self, adapter):
        """Test SQL execution via Spark."""
        # Create and register test data
        test_df = adapter.spark.createDataFrame(
            [(1, 10), (2, 20), (3, 30)],
            ["id", "value"],
        )
        adapter.register_table("test", test_df)

        df = adapter.sql("SELECT * FROM test WHERE value > 15")
        count = adapter.get_row_count(df)

        assert count == 2

    def test_register_table(self, adapter):
        """Test registering a DataFrame as temp view."""
        test_df = adapter.spark.createDataFrame([(1,), (2,), (3,)], ["x"])
        adapter.register_table("my_table", test_df)

        # Should be queryable via SQL
        result = adapter.spark.sql("SELECT * FROM my_table")
        count = adapter.get_row_count(result)

        assert count == 3

    def test_explain(self, adapter):
        """Test query plan explanation."""
        test_df = adapter.spark.createDataFrame(
            [(1, "A"), (2, "B")],
            ["id", "name"],
        )
        filtered = test_df.filter(adapter.col("id") > adapter.lit(1))

        plan = adapter.explain(filtered, mode="simple")

        assert len(plan) > 0
        # Plan should mention filter
        assert "Filter" in plan or "filter" in plan.lower()

    def test_get_query_plan(self, adapter):
        """Test getting both logical and physical plans."""
        test_df = adapter.spark.createDataFrame([(1,), (2,)], ["a"])

        plans = adapter.get_query_plan(test_df)

        assert "logical" in plans
        assert "physical" in plans
        assert len(plans["logical"]) > 0
        assert len(plans["physical"]) > 0

    def test_to_pandas(self, adapter):
        """Test conversion to pandas DataFrame."""
        test_df = adapter.spark.createDataFrame(
            [(1, "A"), (2, "B"), (3, "C")],
            ["id", "name"],
        )

        pandas_df = adapter.to_pandas(test_df)

        assert len(pandas_df) == 3
        assert "id" in pandas_df.columns
        assert "name" in pandas_df.columns

    def test_get_first_row(self, adapter):
        """Test getting first row."""
        test_df = adapter.spark.createDataFrame(
            [(1, "Alice"), (2, "Bob")],
            ["id", "name"],
        )

        first = adapter._get_first_row(test_df)

        assert len(first) == 2
        assert first[0] == 1

    def test_get_first_row_empty(self, adapter):
        """Test getting first row from empty DataFrame."""
        empty_df = adapter.spark.createDataFrame([], "id INT, name STRING")

        first = adapter._get_first_row(empty_df)

        assert first is None

    def test_to_polars(self, adapter):
        """Test conversion to Polars DataFrame."""
        try:
            import polars as pl
        except ImportError:
            pytest.skip("Polars not installed")

        test_df = adapter.spark.createDataFrame(
            [(1, "A"), (2, "B"), (3, "C")],
            ["id", "name"],
        )

        polars_df = adapter.to_polars(test_df)

        assert isinstance(polars_df, pl.DataFrame)
        assert len(polars_df) == 3
        assert "id" in polars_df.columns
        assert "name" in polars_df.columns

    def test_get_tuning_summary(self, adapter):
        """Test getting tuning summary."""
        summary = adapter.get_tuning_summary()

        assert "platform" in summary
        assert summary["platform"] == "PySpark"
        assert "family" in summary
        assert summary["family"] == "expression"
        assert "master" in summary
        assert "driver_memory" in summary
        assert "shuffle_partitions" in summary
        assert "aqe_enabled" in summary
        assert "spark_version" in summary
        assert isinstance(summary["spark_version"], str) and len(summary["spark_version"]) > 0


@pytest.mark.skipif(_SKIP_PYSPARK, reason=_SKIP_REASON)
class TestPySparkScalarExtraction:
    """Tests for PySpark scalar extraction optimization."""

    @pytest.fixture(scope="class")
    def spark_adapter(self):
        """Provide a shared adapter instance for scalar tests."""
        adapter = PySparkDataFrameAdapter(
            master="local[2]",
            driver_memory="1g",
        )
        yield adapter
        adapter.close()

    def test_scalar_single_value_dataframe(self, spark_adapter):
        """Test scalar extraction from single-value DataFrame."""
        spark = spark_adapter.spark
        df = spark.createDataFrame([(42,)], ["value"])
        result = spark_adapter.scalar(df)

        assert result == 42

    def test_scalar_with_column_name(self, spark_adapter):
        """Test scalar extraction with explicit column name."""
        spark = spark_adapter.spark
        df = spark.createDataFrame([(1, 2, 3)], ["a", "b", "c"])
        result = spark_adapter.scalar(df, column="b")

        assert result == 2

    def test_scalar_first_column_multicolumn_df(self, spark_adapter):
        """Test scalar extraction defaults to first column."""
        spark = spark_adapter.spark
        df = spark.createDataFrame([(10, 20)], ["first", "second"])
        result = spark_adapter.scalar(df)

        assert result == 10

    def test_scalar_empty_dataframe_raises(self, spark_adapter):
        """Test that scalar extraction on empty DataFrame raises ValueError."""
        spark = spark_adapter.spark
        # Create empty DataFrame with schema
        from pyspark.sql.types import IntegerType, StructField, StructType

        schema = StructType([StructField("value", IntegerType(), True)])
        df = spark.createDataFrame([], schema)

        with pytest.raises(ValueError, match="empty DataFrame"):
            spark_adapter.scalar(df)

    def test_scalar_float_value(self, spark_adapter):
        """Test scalar extraction with float value."""
        spark = spark_adapter.spark
        df = spark.createDataFrame([(3.14159,)], ["value"])
        result = spark_adapter.scalar(df)

        assert result == pytest.approx(3.14159)

    def test_scalar_string_value(self, spark_adapter):
        """Test scalar extraction with string value."""
        spark = spark_adapter.spark
        df = spark.createDataFrame([("hello",)], ["value"])
        result = spark_adapter.scalar(df)

        assert result == "hello"

    def test_scalar_via_context(self, spark_adapter):
        """Test scalar extraction via context (integration)."""
        ctx = spark_adapter.create_context()
        spark = spark_adapter.spark
        df = spark.createDataFrame([(999,)], ["total"])
        result = ctx.scalar(df)

        assert result == 999

    def test_scalar_multiple_rows_raises(self, spark_adapter):
        """Test that scalar extraction on multi-row DataFrame raises ValueError."""
        spark = spark_adapter.spark
        df = spark.createDataFrame([(1,), (2,), (3,)], ["value"])

        with pytest.raises(ValueError, match="exactly one row|multiple"):
            spark_adapter.scalar(df)

    def test_scalar_two_rows_raises(self, spark_adapter):
        """Test that scalar extraction on 2-row DataFrame raises ValueError."""
        spark = spark_adapter.spark
        df = spark.createDataFrame([(1, 3), (2, 4)], ["a", "b"])

        with pytest.raises(ValueError, match="exactly one row|multiple"):
            spark_adapter.scalar(df)


class TestPySparkNotAvailable:
    """Tests for behavior when PySpark is not installed."""

    def test_pyspark_available_flag(self):
        """Test that PYSPARK_AVAILABLE flag is set correctly."""
        from benchbox.platforms.dataframe.pyspark_df import PYSPARK_AVAILABLE

        # This just tests that the flag exists and is boolean
        assert isinstance(PYSPARK_AVAILABLE, bool)

    def test_pyspark_version_constant(self):
        """Test that PYSPARK_VERSION constant is exported."""
        from benchbox.platforms.dataframe.pyspark_df import PYSPARK_VERSION

        # If PySpark is installed, version should be a string
        # If not installed, it should be None
        if PYSPARK_AVAILABLE:
            assert isinstance(PYSPARK_VERSION, str)
            assert len(PYSPARK_VERSION) > 0
        else:
            assert PYSPARK_VERSION is None

    def test_adapter_import_error_when_not_available(self):
        """Test that adapter raises ImportError when PySpark not installed."""
        from benchbox.platforms.dataframe.pyspark_df import PySparkDataFrameAdapter

        if PYSPARK_AVAILABLE:
            # When PySpark is available, adapter should construct without import failures.
            adapter = PySparkDataFrameAdapter(master="local[1]", driver_memory="512m")
            adapter.close()
            return

        with pytest.raises(ImportError, match="PySpark not installed"):
            PySparkDataFrameAdapter()
