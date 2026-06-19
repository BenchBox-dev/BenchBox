"""Unit tests for Pandas Family adapter base class.

Tests for:
- PandasFamilyContext
- PandasFamilyAdapter abstract class
- Common functionality

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory
from benchbox.platforms.dataframe.pandas_family import (
    PandasFamilyAdapter,
    PandasFamilyContext,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class MockPandasAdapter(PandasFamilyAdapter[dict]):
    """Mock adapter for testing the abstract base class."""

    @property
    def platform_name(self) -> str:
        return "MockPandas"

    def read_csv(
        self,
        path: Path,
        *,
        delimiter: str = ",",
        header: int | None = 0,
        names: list[str] | None = None,
        null_marker: str | None = None,
        column_types: list[str] | None = None,
    ) -> dict:
        return {"type": "csv", "path": str(path), "delimiter": delimiter}

    def read_parquet(self, path: Path) -> dict:
        return {"type": "parquet", "path": str(path)}

    def to_datetime(self, series: Any) -> Any:
        return series

    def timedelta_days(self, days: int) -> timedelta:
        return timedelta(days=days)

    def concat(self, dfs: list[dict]) -> dict:
        return {"type": "concat", "count": len(dfs)}

    def get_row_count(self, df: dict) -> int:
        return df.get("rows", 10)

    def _get_first_row(self, df: dict) -> tuple | None:
        return (1, "test", 100.0)


class TestPandasFamilyContext:
    """Tests for PandasFamilyContext."""

    def test_context_creation(self):
        """Test creating a context from an adapter."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        assert isinstance(ctx, PandasFamilyContext)
        assert ctx.platform == "MockPandas"
        assert ctx.family == "pandas"

    def test_context_col_returns_string(self):
        """Test that col() returns the column name as string."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        result = ctx.col("amount")
        assert result == "amount"

    def test_context_lit_returns_value(self):
        """Test that lit() returns the value unchanged."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        assert ctx.lit(100) == 100
        assert ctx.lit("hello") == "hello"
        assert ctx.lit(3.14) == 3.14

    def test_context_date_sub_returns_descriptor(self):
        """Test that date_sub() returns an operation descriptor."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        result = ctx.date_sub("date_col", 7)
        assert result["op"] == "date_sub"
        assert result["column"] == "date_col"
        assert result["days"] == 7

    def test_context_date_add_returns_descriptor(self):
        """Test that date_add() returns an operation descriptor."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        result = ctx.date_add("date_col", 30)
        assert result["op"] == "date_add"
        assert result["column"] == "date_col"
        assert result["days"] == 30

    def test_context_cast_date_returns_descriptor(self):
        """Test that cast_date() returns an operation descriptor."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        result = ctx.cast_date("string_col")
        assert result["op"] == "cast_date"
        assert result["column"] == "string_col"

    def test_context_cast_string_returns_descriptor(self):
        """Test that cast_string() returns an operation descriptor."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        result = ctx.cast_string("int_col")
        assert result["op"] == "cast_string"
        assert result["column"] == "int_col"

    def test_context_table_registration(self):
        """Test table registration in context."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        test_df = {"data": [1, 2, 3]}
        ctx.register_table("orders", test_df)

        assert ctx.table_exists("orders")
        # get_table now returns UnifiedPandasFrame wrapper
        result = ctx.get_table("orders")
        assert result.native == test_df

    def test_context_list_tables(self):
        """Test listing tables in context."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        ctx.register_table("orders", {})
        ctx.register_table("customers", {})

        tables = ctx.list_tables()
        assert "orders" in tables
        assert "customers" in tables


class TestPandasFamilyAdapter:
    """Tests for PandasFamilyAdapter abstract class."""

    def test_adapter_initialization(self):
        """Test adapter initialization."""
        adapter = MockPandasAdapter()

        assert adapter.platform_name == "MockPandas"
        assert adapter.family == "pandas"
        assert adapter.verbose is False
        assert adapter.table_mode == "native"
        assert adapter.platform_config == {}

    def test_adapter_initialization_with_options(self):
        """Test adapter initialization with options."""
        adapter = MockPandasAdapter(
            working_dir="/tmp/test",
            verbose=True,
            very_verbose=True,
        )

        assert adapter.working_dir == Path("/tmp/test")
        assert adapter.verbose is True
        assert adapter.very_verbose is True

    def test_create_context(self):
        """Test context creation."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        assert isinstance(ctx, PandasFamilyContext)

    def test_get_context_creates_if_missing(self):
        """Test that get_context creates context if missing."""
        adapter = MockPandasAdapter()

        ctx = adapter.get_context()

        assert ctx is not None
        assert adapter._context == ctx

    def test_get_context_returns_existing(self):
        """Test that get_context returns existing context."""
        adapter = MockPandasAdapter()

        ctx1 = adapter.create_context()
        ctx2 = adapter.get_context()

        assert ctx1 is ctx2

    def test_detect_format_parquet(self):
        """Test format detection for Parquet files."""
        adapter = MockPandasAdapter()

        assert adapter._detect_format(Path("data.parquet")) == "parquet"

    def test_detect_format_tbl(self):
        """Test format detection for TBL files."""
        adapter = MockPandasAdapter()

        assert adapter._detect_format(Path("lineitem.tbl")) == "tbl"

    def test_detect_format_csv(self):
        """Test format detection for CSV files."""
        adapter = MockPandasAdapter()

        assert adapter._detect_format(Path("data.csv")) == "csv"
        assert adapter._detect_format(Path("file.txt")) == "csv"  # default

    def test_date_sub_returns_descriptor(self):
        """Test date_sub operation descriptor."""
        adapter = MockPandasAdapter()

        result = adapter.date_sub("date", 7)

        assert result == {"op": "date_sub", "column": "date", "days": 7}

    def test_date_add_returns_descriptor(self):
        """Test date_add operation descriptor."""
        adapter = MockPandasAdapter()

        result = adapter.date_add("date", 30)

        assert result == {"op": "date_add", "column": "date", "days": 30}

    def test_timedelta_days(self):
        """Test timedelta creation."""
        adapter = MockPandasAdapter()

        td = adapter.timedelta_days(7)

        assert td == timedelta(days=7)

    def test_execute_query_success(self):
        """Test successful query execution."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        # Register a test table
        ctx.register_table("orders", {"rows": 100})

        def pandas_impl(ctx):
            return ctx.get_table("orders")

        query = DataFrameQuery(
            query_id="Q1",
            query_name="Test Query",
            description="A test query",
            categories=[QueryCategory.SCAN],
            pandas_impl=pandas_impl,
        )

        result = adapter.execute_query(ctx, query)

        assert result["query_id"] == "Q1"
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 100
        assert "execution_time_seconds" in result

    def test_execute_query_timing_key_matches_schema_contract(self):
        """Test that timing key matches what result schema expects.

        Runtime producers should emit canonical `execution_time_seconds`.
        """
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        # Register a test table directly (not via load_table)
        ctx.register_table("orders", {"rows": 100})

        def pandas_impl(ctx):
            return ctx.get_table("orders")

        query = DataFrameQuery(
            query_id="Q1",
            query_name="Timing Contract Test",
            description="Verify timing key contract",
            pandas_impl=pandas_impl,
        )

        result = adapter.execute_query(ctx, query)

        assert "execution_time_seconds" in result
        assert "execution_time" not in result
        assert "execution_time_ms" not in result
        assert result["execution_time_seconds"] >= 0.0

    def test_execute_query_failure(self):
        """Test query execution failure handling."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        def failing_impl(ctx):
            raise ValueError("Test error")

        query = DataFrameQuery(
            query_id="Q2",
            query_name="Failing Query",
            description="A failing query",
            pandas_impl=failing_impl,
        )

        result = adapter.execute_query(ctx, query)

        assert result["query_id"] == "Q2"
        assert result["status"] == "FAILED"
        assert "Test error" in result["error"]

    def test_execute_query_no_impl(self):
        """Test error when query has no pandas implementation."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        def expression_impl(ctx):
            return ctx.get_table("orders")

        query = DataFrameQuery(
            query_id="Q3",
            query_name="Expression Only",
            description="Expression-only query",
            expression_impl=expression_impl,
        )

        result = adapter.execute_query(ctx, query)

        assert result["status"] == "FAILED"
        assert "no pandas implementation" in result["error"]

    def test_load_table_with_parquet(self, tmp_path):
        """Test loading table from Parquet file."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        # Create a mock parquet file path
        parquet_file = tmp_path / "orders.parquet"
        parquet_file.touch()

        row_count = adapter.load_table(ctx, "orders", [parquet_file])

        assert ctx.table_exists("orders")
        assert row_count == 10  # Mock returns 10

    def test_load_table_no_files_raises(self):
        """Test that loading with no files raises error."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        with pytest.raises(ValueError, match="No files provided"):
            adapter.load_table(ctx, "orders", [])

    def test_load_tables_from_data_source_uses_default_loading_contract(self, tmp_path):
        """Shared loading should work for plain pandas-family subclasses."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()
        data_file = tmp_path / "orders.tbl"
        data_file.write_text("1|2|\n")

        with patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_cls:
            mock_resolver = MagicMock()
            mock_cls.return_value = mock_resolver
            mock_resolver.resolve.return_value = SimpleNamespace(tables={"orders": [data_file]}, table_formats={})

            stats = adapter.load_tables_from_data_source(ctx, tmp_path)

        assert stats == {"orders": 10}
        assert mock_cls.call_args.kwargs == {
            "platform_name": "MockPandas",
            "table_mode": "native",
            "platform_config": {},
            "requested_format": None,
        }


class TestPandasFamilyAdapterAbstract:
    """Tests verifying abstract method requirements."""

    def test_abstract_methods_required(self):
        """Test that abstract methods must be implemented."""

        class IncompleteAdapter(PandasFamilyAdapter):
            @property
            def platform_name(self) -> str:
                return "Incomplete"

        with pytest.raises(TypeError, match="abstract"):
            IncompleteAdapter()  # type: ignore[abstract]


class TestQueryIntegration:
    """Integration tests for query execution."""

    def test_query_with_table_access(self):
        """Test query that accesses registered tables."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        # Register test data
        ctx.register_table("orders", {"rows": 50, "data": "test"})
        ctx.register_table("customers", {"rows": 10, "data": "cust"})

        def join_impl(ctx):
            orders = ctx.get_table("orders")
            _ = ctx.get_table("customers")  # Access to verify registration
            return {"rows": orders["rows"], "joined": True}

        query = DataFrameQuery(
            query_id="JOIN1",
            query_name="Join Query",
            description="Join orders and customers",
            categories=[QueryCategory.JOIN],
            pandas_impl=join_impl,
        )

        result = adapter.execute_query(ctx, query)

        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 50

    def test_query_with_column_access(self):
        """Test query that uses column access helpers."""
        adapter = MockPandasAdapter()
        ctx = adapter.create_context()

        ctx.register_table("orders", {"rows": 100})

        def filter_impl(ctx):
            # Use column access pattern (returns string)
            col = ctx.col("amount")
            threshold = ctx.lit(100)
            # In real implementation, this would filter
            return {"rows": 75, "filter": f"{col} > {threshold}"}

        query = DataFrameQuery(
            query_id="FILTER1",
            query_name="Filter Query",
            description="Filter by amount",
            categories=[QueryCategory.FILTER],
            pandas_impl=filter_impl,
        )

        result = adapter.execute_query(ctx, query)

        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 75


class TestPandasFamilyContextHelpers:
    """Tests for PandasFamilyContext helper methods.

    These methods provide platform-agnostic DataFrame operations
    that work across Pandas, Dask, Modin, and cuDF.
    """

    @pytest.fixture
    def adapter(self):
        """Create a Pandas adapter for testing context helpers."""
        try:
            from benchbox.platforms.dataframe.pandas_df import PandasDataFrameAdapter

            return PandasDataFrameAdapter()
        except ImportError:
            pytest.skip("Pandas not installed")

    @pytest.fixture
    def sample_df(self):
        """Create a sample DataFrame for testing."""
        import pandas as pd

        return pd.DataFrame(
            {
                "category": ["A", "B", "A", "B", "A"],
                "value": [10, 20, 30, 40, 50],
                "name": ["x", "y", "z", "w", "v"],
            }
        )

    def test_concat_multiple_dataframes(self, adapter):
        """Test ctx.concat() combines DataFrames correctly."""
        import pandas as pd

        ctx = adapter.create_context()

        df1 = pd.DataFrame({"a": [1, 2]})
        df2 = pd.DataFrame({"a": [3, 4]})
        df3 = pd.DataFrame({"a": [5, 6]})

        result = ctx.concat([df1, df2, df3])

        # Result should be a UnifiedPandasFrame
        assert hasattr(result, "native")
        assert len(result.native) == 6
        assert list(result.native["a"]) == [1, 2, 3, 4, 5, 6]

    def test_concat_unwraps_unified_frames(self, adapter, sample_df):
        """Test ctx.concat() unwraps UnifiedPandasFrame instances."""
        import pandas as pd

        from benchbox.platforms.dataframe.unified_pandas_frame import UnifiedPandasFrame

        ctx = adapter.create_context()

        # Wrap one DataFrame as UnifiedPandasFrame
        df1 = pd.DataFrame({"a": [1, 2]})
        df2 = pd.DataFrame({"a": [3, 4]})
        wrapped = UnifiedPandasFrame(df1, adapter)

        result = ctx.concat([wrapped, df2])

        assert len(result.native) == 4

    def test_groupby_size_single_column(self, adapter, sample_df):
        """Test ctx.groupby_size() counts rows per group."""
        ctx = adapter.create_context()

        result = ctx.groupby_size(sample_df, "category", name="count")

        assert hasattr(result, "native")
        df = result.native
        assert len(df) == 2  # Two categories: A, B
        assert "category" in df.columns
        assert "count" in df.columns
        # Category A has 3 rows, B has 2 rows
        a_count = df[df["category"] == "A"]["count"].iloc[0]
        b_count = df[df["category"] == "B"]["count"].iloc[0]
        assert a_count == 3
        assert b_count == 2

    def test_groupby_size_multiple_columns(self, adapter):
        """Test ctx.groupby_size() with multiple grouping columns."""
        import pandas as pd

        ctx = adapter.create_context()

        df = pd.DataFrame(
            {
                "region": ["East", "East", "West", "West"],
                "category": ["A", "B", "A", "A"],
                "value": [1, 2, 3, 4],
            }
        )

        result = ctx.groupby_size(df, ["region", "category"], name="n")

        assert "region" in result.native.columns
        assert "category" in result.native.columns
        assert "n" in result.native.columns
        assert len(result.native) == 3  # (East,A), (East,B), (West,A)

    def test_groupby_agg_named_aggregation(self, adapter, sample_df):
        """Test ctx.groupby_agg() with named aggregation style."""
        ctx = adapter.create_context()

        result = ctx.groupby_agg(
            sample_df,
            "category",
            {"total": ("value", "sum"), "avg": ("value", "mean")},
            as_index=False,
        )

        df = result.native
        assert "category" in df.columns
        assert "total" in df.columns
        assert "avg" in df.columns
        assert len(df) == 2

    def test_groupby_agg_direct_style(self, adapter, sample_df):
        """Test ctx.groupby_agg() with direct dict style."""
        ctx = adapter.create_context()

        result = ctx.groupby_agg(sample_df, "category", {"value": "sum"}, as_index=False)

        df = result.native
        assert "category" in df.columns
        assert "value" in df.columns
        # A: 10+30+50=90, B: 20+40=60
        a_sum = df[df["category"] == "A"]["value"].iloc[0]
        b_sum = df[df["category"] == "B"]["value"].iloc[0]
        assert a_sum == 90
        assert b_sum == 60

    def test_to_set_from_series(self, adapter):
        """Test ctx.to_set() converts Series to set."""
        import pandas as pd

        ctx = adapter.create_context()

        series = pd.Series([1, 2, 2, 3, 3, 3])
        result = ctx.to_set(series)

        assert isinstance(result, set)
        assert result == {1, 2, 3}

    def test_to_set_from_dataframe(self, adapter):
        """Test ctx.to_set() extracts first column from DataFrame."""
        import pandas as pd

        ctx = adapter.create_context()

        df = pd.DataFrame({"id": [1, 2, 2, 3], "other": ["a", "b", "c", "d"]})
        result = ctx.to_set(df)

        assert isinstance(result, set)
        assert result == {1, 2, 3}

    def test_to_set_unwraps_unified_frame(self, adapter):
        """Test ctx.to_set() unwraps UnifiedPandasFrame."""
        import pandas as pd

        from benchbox.platforms.dataframe.unified_pandas_frame import UnifiedPandasFrame

        ctx = adapter.create_context()

        df = pd.DataFrame({"id": [1, 2, 3]})
        wrapped = UnifiedPandasFrame(df, adapter)

        result = ctx.to_set(wrapped)

        assert result == {1, 2, 3}

    def test_filter_gt_basic(self, adapter, sample_df):
        """Test ctx.filter_gt() filters rows where column > threshold."""
        ctx = adapter.create_context()

        result = ctx.filter_gt(sample_df, "value", 25)

        df = result.native
        assert len(df) == 3  # values 30, 40, 50 are > 25
        assert all(df["value"] > 25)

    def test_filter_gt_with_float_threshold(self, adapter):
        """Test ctx.filter_gt() with float threshold."""
        import pandas as pd

        ctx = adapter.create_context()

        df = pd.DataFrame({"price": [9.99, 10.00, 10.01, 15.50]})
        result = ctx.filter_gt(df, "price", 10.00)

        assert len(result.native) == 2  # 10.01 and 15.50

    def test_filter_gt_unwraps_unified_frame(self, adapter, sample_df):
        """Test ctx.filter_gt() unwraps UnifiedPandasFrame."""
        from benchbox.platforms.dataframe.unified_pandas_frame import UnifiedPandasFrame

        ctx = adapter.create_context()

        wrapped = UnifiedPandasFrame(sample_df, adapter)
        result = ctx.filter_gt(wrapped, "value", 30)

        assert len(result.native) == 2  # 40 and 50

    def test_filter_gt_returns_unified_frame(self, adapter, sample_df):
        """Test ctx.filter_gt() returns UnifiedPandasFrame."""
        from benchbox.platforms.dataframe.unified_pandas_frame import UnifiedPandasFrame

        ctx = adapter.create_context()

        result = ctx.filter_gt(sample_df, "value", 0)

        assert isinstance(result, UnifiedPandasFrame)


class TestLoadBenchmarkIntoContextGuard:
    """load_benchmark_into_context must refuse benchmark-managed loading.

    A benchmark that owns its DataFrame loading (skip_dataframe_data_loading)
    interleaves loading with execution and has no discrete preloaded context;
    the helper must fail loudly rather than invoke the generic loader and return
    a wrong/empty context (regression for PR #826 review feedback).
    """

    def test_raises_for_benchmark_managed_loading(self, tmp_path):
        class ManagedBenchmark:
            name = "managed"

            def skip_dataframe_data_loading(self) -> bool:
                return True

        adapter = MockPandasAdapter()
        with pytest.raises(ValueError, match="manages its own DataFrame loading"):
            adapter.load_benchmark_into_context(ManagedBenchmark(), tmp_path)
