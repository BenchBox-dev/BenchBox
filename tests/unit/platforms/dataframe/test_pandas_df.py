"""Unit tests for Pandas DataFrame adapter.

Tests for:
- PandasDataFrameAdapter initialization
- Data loading (CSV, Parquet)
- Query execution
- Helper methods

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# Check if Pandas is available
try:
    import pandas as pd

    from benchbox.platforms.dataframe.pandas_df import (
        PANDAS_AVAILABLE,
        PandasDataFrameAdapter,
    )
except ImportError:
    PANDAS_AVAILABLE = False
    pd = None  # type: ignore[assignment]


@pytest.mark.skipif(not PANDAS_AVAILABLE, reason="Pandas not installed")
class TestPandasDataFrameAdapter:
    """Tests for PandasDataFrameAdapter."""

    def test_initialization(self):
        """Test adapter initialization."""
        adapter = PandasDataFrameAdapter()

        assert adapter.platform_name == "Pandas"
        assert adapter.family == "pandas"
        assert adapter.dtype_backend == "numpy_nullable"

    def test_initialization_with_options(self):
        """Test adapter initialization with custom options."""
        adapter = PandasDataFrameAdapter(
            working_dir="/tmp/pandas",
            verbose=True,
            dtype_backend="pyarrow",
        )

        assert adapter.working_dir == Path("/tmp/pandas")
        assert adapter.verbose is True
        assert adapter.dtype_backend == "pyarrow"

    def test_initialization_with_copy_on_write(self):
        """Test adapter initialization with copy-on-write option."""
        # Get Pandas version
        pandas_version = tuple(int(x) for x in pd.__version__.split(".")[:2])

        adapter = PandasDataFrameAdapter(copy_on_write=True)

        if pandas_version >= (2, 0):
            # CoW should be enabled for Pandas 2.0+
            assert adapter.copy_on_write is True
            assert pd.options.mode.copy_on_write is True
        else:
            # CoW not available before Pandas 2.0
            assert adapter.copy_on_write is False

    def test_initialization_with_copy_on_write_disabled(self):
        """Test adapter initialization with copy-on-write explicitly disabled."""
        pandas_version = tuple(int(x) for x in pd.__version__.split(".")[:2])

        adapter = PandasDataFrameAdapter(copy_on_write=False)

        if pandas_version >= (2, 0):
            assert adapter.copy_on_write is False
            assert pd.options.mode.copy_on_write is False

    def test_platform_info(self):
        """Test get_platform_info method."""
        adapter = PandasDataFrameAdapter()

        info = adapter.get_platform_info()

        assert info["platform"] == "Pandas"
        assert info["family"] == "pandas"
        assert "version" in info
        assert "copy_on_write" in info  # Should include CoW status

    def test_create_context(self):
        """Test context creation."""
        adapter = PandasDataFrameAdapter()
        ctx = adapter.create_context()

        assert ctx is not None
        assert ctx.platform == "Pandas"
        assert ctx.family == "pandas"


@pytest.mark.skipif(not PANDAS_AVAILABLE, reason="Pandas not installed")
class TestPandasDataLoading:
    """Tests for Pandas data loading methods."""

    def test_read_csv_basic(self, tmp_path):
        """Test reading a basic CSV file."""
        adapter = PandasDataFrameAdapter()

        # Create a test CSV file
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("id,name,amount\n1,Alice,100\n2,Bob,200\n")

        df = adapter.read_csv(csv_path)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert list(df.columns) == ["id", "name", "amount"]

    def test_read_csv_with_delimiter(self, tmp_path):
        """Test reading CSV with custom delimiter."""
        adapter = PandasDataFrameAdapter()

        # Create a pipe-delimited file
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("id|name|amount\n1|Alice|100\n2|Bob|200\n")

        df = adapter.read_csv(csv_path, delimiter="|")

        assert len(df) == 2

    def test_read_csv_with_column_names(self, tmp_path):
        """Test reading CSV with explicit column names."""
        adapter = PandasDataFrameAdapter()

        # Create a headerless CSV
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("1,Alice,100\n2,Bob,200\n")

        df = adapter.read_csv(
            csv_path,
            header=None,
            names=["id", "name", "amount"],
        )

        assert list(df.columns) == ["id", "name", "amount"]

    def test_read_csv_with_column_names_parses_dates(self, tmp_path):
        """Explicit-schema raw CSV loads parse date columns without date surrogate keys."""
        adapter = PandasDataFrameAdapter()

        csv_path = tmp_path / "orders.tbl"
        csv_path.write_text("1|1998-01-02|2450815|2013-07-01 12:34:56|\n")

        df = adapter.read_csv(
            csv_path,
            delimiter="|",
            header=None,
            names=["o_orderkey", "o_orderdate", "d_date_sk", "EventTime"],
            null_marker="",
        )

        assert df["o_orderdate"].iloc[0] == date(1998, 1, 2)
        assert df["o_orderdate"].dt.year.iloc[0] == 1998
        assert not pd.api.types.is_datetime64_any_dtype(df["d_date_sk"])
        assert pd.api.types.is_datetime64_any_dtype(df["EventTime"])

    def test_read_csv_type_aware_date_parsing_by_declared_type(self, tmp_path):
        """A declared TIMESTAMP column parses even when its name misses the suffix heuristic (w9).

        ClickBench's ClientEventTime is TIMESTAMP but does not end in
        date/timestamp, so the name-only heuristic read it as a raw string while
        the SQL surface returned a datetime. Declared types are now authoritative.
        """
        adapter = PandasDataFrameAdapter()
        csv_path = tmp_path / "hits.csv"
        csv_path.write_text("1|2013-07-01 00:01:34\n")

        df = adapter.read_csv(
            csv_path,
            delimiter="|",
            header=None,
            names=["id", "ClientEventTime"],
            null_marker=None,
            column_types=["INTEGER", "TIMESTAMP"],
        )
        assert pd.api.types.is_datetime64_any_dtype(df["ClientEventTime"])

    def test_read_csv_declared_text_column_not_inferred_numeric(self, tmp_path):
        """A declared TEXT column with numeric-looking values stays string (w9).

        join-order movie_info_idx.info holds rating strings like "8.0"; pandas
        would infer float64 and diverge from the VARCHAR SQL surface.
        """
        adapter = PandasDataFrameAdapter()
        csv_path = tmp_path / "info.csv"
        csv_path.write_text("1|8.0\n2|10.0\n")

        df = adapter.read_csv(
            csv_path,
            delimiter="|",
            header=None,
            names=["id", "info"],
            null_marker="",
            column_types=["INTEGER", "TEXT"],
        )
        assert not pd.api.types.is_numeric_dtype(df["info"])
        assert df["info"].iloc[0] == "8.0"

    def test_read_csv_empty_string_handling_follows_null_marker(self, tmp_path):
        """Empty text fields stay "" when null_marker is None, NaN when "" (w9).

        Matches the SQL surface per the benchmark's resolved CSV dialect:
        ClickBench (null_marker=None) keeps ""; JoinOrder (null_marker="") nulls.
        """
        adapter = PandasDataFrameAdapter()
        csv_path = tmp_path / "t.csv"
        csv_path.write_text("1|\n2|hello\n")

        kept = adapter.read_csv(
            csv_path,
            delimiter="|",
            header=None,
            names=["id", "note"],
            null_marker=None,
            column_types=["INTEGER", "TEXT"],
        )
        assert kept["note"].iloc[0] == ""

        nulled = adapter.read_csv(
            csv_path,
            delimiter="|",
            header=None,
            names=["id", "note"],
            null_marker="",
            column_types=["INTEGER", "TEXT"],
        )
        assert pd.isna(nulled["note"].iloc[0])

    def test_load_headered_csv_with_column_names_parses_dates(self, tmp_path):
        """Headered CSV loads still use schema names for pandas date converters."""
        adapter = PandasDataFrameAdapter()
        ctx = adapter.create_context()

        csv_path = tmp_path / "flights.csv"
        csv_path.write_text("flight_id,flight_date,EventTime\n1,2018-01-02,2018-01-02 12:34:56\n")

        adapter.load_table(
            ctx,
            "flights",
            [csv_path],
            column_names=["flight_id", "flight_date", "EventTime"],
            format_hint="csv",
        )

        df = ctx.get_table("flights")._df
        assert df["flight_date"].iloc[0] == date(2018, 1, 2)
        assert df["flight_date"].dt.year.iloc[0] == 2018
        assert pd.api.types.is_datetime64_any_dtype(df["EventTime"])

    def test_read_parquet(self, tmp_path):
        """Test reading a Parquet file."""
        adapter = PandasDataFrameAdapter()

        # Create a test Parquet file
        parquet_path = tmp_path / "test.parquet"
        test_df = pd.DataFrame(
            {
                "id": [1, 2, 3],
                "name": ["A", "B", "C"],
                "amount": [100.0, 200.0, 300.0],
            }
        )
        test_df.to_parquet(parquet_path)

        df = adapter.read_parquet(parquet_path)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3

    def test_concat_dataframes(self):
        """Test concatenating DataFrames."""
        adapter = PandasDataFrameAdapter()

        df1 = pd.DataFrame({"a": [1, 2]})
        df2 = pd.DataFrame({"a": [3, 4]})

        combined = adapter.concat([df1, df2])

        assert len(combined) == 4

    def test_concat_single_dataframe(self):
        """Test concat with single DataFrame."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"a": [1, 2, 3]})
        result = adapter.concat([df])

        assert result is df

    def test_get_row_count(self):
        """Test getting row count."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"a": [1, 2, 3, 4, 5]})
        count = adapter.get_row_count(df)

        assert count == 5

    def test_get_first_row(self):
        """Test getting first row."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        first = adapter._get_first_row(df)

        assert first == (1, "x")

    def test_get_first_row_empty(self):
        """Test getting first row from empty DataFrame."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"a": [], "b": []})
        first = adapter._get_first_row(df)

        assert first is None


@pytest.mark.skipif(not PANDAS_AVAILABLE, reason="Pandas not installed")
class TestPandasHelperMethods:
    """Tests for Pandas helper methods."""

    def test_to_datetime(self):
        """Test to_datetime conversion."""
        adapter = PandasDataFrameAdapter()

        series = pd.Series(["2024-01-01", "2024-02-01"])
        result = adapter.to_datetime(series)

        assert pd.api.types.is_datetime64_any_dtype(result)

    def test_timedelta_days(self):
        """Test timedelta creation."""
        adapter = PandasDataFrameAdapter()

        td = adapter.timedelta_days(7)

        assert td == pd.Timedelta(days=7)

    def test_merge(self):
        """Test merge operation."""
        adapter = PandasDataFrameAdapter()

        left = pd.DataFrame({"id": [1, 2, 3], "name": ["A", "B", "C"]})
        right = pd.DataFrame({"id": [1, 2], "value": [100, 200]})

        merged = adapter.merge(left, right, on="id")

        assert len(merged) == 2
        assert "name" in merged.columns
        assert "value" in merged.columns

    def test_merge_left_join(self):
        """Test left merge operation."""
        adapter = PandasDataFrameAdapter()

        left = pd.DataFrame({"id": [1, 2, 3], "name": ["A", "B", "C"]})
        right = pd.DataFrame({"id": [1, 2], "value": [100, 200]})

        merged = adapter.merge(left, right, on="id", how="left")

        assert len(merged) == 3  # All left rows preserved

    def test_groupby_agg(self):
        """Test grouped aggregation."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame(
            {
                "category": ["A", "B", "A", "B"],
                "amount": [100, 200, 150, 250],
            }
        )

        result = adapter.groupby_agg(df, "category", {"amount": "sum"})

        assert len(result) == 2
        assert "category" in result.columns
        assert "amount" in result.columns

    def test_filter_rows_greater_than(self):
        """Test row filtering with > operator."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"value": [1, 5, 10, 15, 20]})
        filtered = adapter.filter_rows(df, "value", ">", 10)

        assert len(filtered) == 2

    def test_filter_rows_less_than(self):
        """Test row filtering with < operator."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"value": [1, 5, 10, 15, 20]})
        filtered = adapter.filter_rows(df, "value", "<", 10)

        assert len(filtered) == 2

    def test_filter_rows_equal(self):
        """Test row filtering with == operator."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"value": [1, 5, 10, 15, 20]})
        filtered = adapter.filter_rows(df, "value", "==", 10)

        assert len(filtered) == 1

    def test_filter_rows_invalid_operator(self):
        """Test row filtering with invalid operator."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"value": [1, 2, 3]})

        with pytest.raises(ValueError, match="Unknown operator"):
            adapter.filter_rows(df, "value", "invalid", 10)

    def test_sort_values(self):
        """Test sorting values."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"value": [3, 1, 2]})
        sorted_df = adapter.sort_values(df, "value")

        assert list(sorted_df["value"]) == [1, 2, 3]

    def test_sort_values_descending(self):
        """Test sorting values descending."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"value": [1, 3, 2]})
        sorted_df = adapter.sort_values(df, "value", ascending=False)

        assert list(sorted_df["value"]) == [3, 2, 1]

    def test_select_columns(self):
        """Test column selection."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
        selected = adapter.select_columns(df, ["a", "c"])

        assert list(selected.columns) == ["a", "c"]

    def test_with_column(self):
        """Test adding a column."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"a": [1, 2, 3]})
        result = adapter.with_column(df, "b", [10, 20, 30])

        assert "b" in result.columns
        assert list(result["b"]) == [10, 20, 30]


@pytest.mark.skipif(not PANDAS_AVAILABLE, reason="Pandas not installed")
class TestPandasQueryExecution:
    """Tests for query execution with Pandas."""

    def test_simple_select_query(self):
        """Test executing a simple select query."""
        adapter = PandasDataFrameAdapter()
        ctx = adapter.create_context()

        # Register test data
        test_df = pd.DataFrame(
            {
                "id": [1, 2, 3],
                "name": ["Alice", "Bob", "Charlie"],
                "amount": [100, 200, 300],
            }
        )
        ctx.register_table("customers", test_df)

        def select_impl(ctx):
            customers = ctx.get_table("customers")
            return customers[["id", "name"]]

        query = DataFrameQuery(
            query_id="SELECT1",
            query_name="Select ID and Name",
            description="Select id and name columns",
            pandas_impl=select_impl,
        )

        result = adapter.execute_query(ctx, query)

        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 3

    def test_filter_query(self):
        """Test executing a filter query."""
        adapter = PandasDataFrameAdapter()
        ctx = adapter.create_context()

        test_df = pd.DataFrame(
            {
                "id": [1, 2, 3, 4, 5],
                "amount": [50, 150, 75, 200, 100],
            }
        )
        ctx.register_table("orders", test_df)

        def filter_impl(ctx):
            orders = ctx.get_table("orders")
            return orders[orders["amount"] > 100]

        query = DataFrameQuery(
            query_id="FILTER1",
            query_name="Filter by Amount",
            description="Filter orders over 100",
            categories=[QueryCategory.FILTER],
            pandas_impl=filter_impl,
        )

        result = adapter.execute_query(ctx, query)

        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2  # 150 and 200

    def test_groupby_query(self):
        """Test executing a group by query."""
        adapter = PandasDataFrameAdapter()
        ctx = adapter.create_context()

        test_df = pd.DataFrame(
            {
                "category": ["A", "B", "A", "B", "A"],
                "amount": [100, 200, 150, 250, 50],
            }
        )
        ctx.register_table("sales", test_df)

        def groupby_impl(ctx):
            sales = ctx.get_table("sales")
            return sales.groupby("category", as_index=False).agg({"amount": "sum"})

        query = DataFrameQuery(
            query_id="GROUP1",
            query_name="Group by Category",
            description="Sum amount by category",
            categories=[QueryCategory.GROUP_BY, QueryCategory.AGGREGATE],
            pandas_impl=groupby_impl,
        )

        result = adapter.execute_query(ctx, query)

        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2  # Two categories

    def test_join_query(self):
        """Test executing a join query."""
        adapter = PandasDataFrameAdapter()
        ctx = adapter.create_context()

        orders_df = pd.DataFrame(
            {
                "order_id": [1, 2, 3],
                "customer_id": [101, 102, 101],
                "amount": [100, 200, 150],
            }
        )
        customers_df = pd.DataFrame(
            {
                "customer_id": [101, 102],
                "name": ["Alice", "Bob"],
            }
        )

        ctx.register_table("orders", orders_df)
        ctx.register_table("customers", customers_df)

        def join_impl(ctx):
            orders = ctx.get_table("orders")
            customers = ctx.get_table("customers")
            # Use UnifiedPandasFrame's merge method instead of pd.merge
            return orders.merge(customers, on="customer_id", how="left")

        query = DataFrameQuery(
            query_id="JOIN1",
            query_name="Join Orders and Customers",
            description="Left join orders with customers",
            categories=[QueryCategory.JOIN],
            pandas_impl=join_impl,
        )

        result = adapter.execute_query(ctx, query)

        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 3

    def test_query_with_context_helpers(self):
        """Test query using context helpers."""
        adapter = PandasDataFrameAdapter()
        ctx = adapter.create_context()

        test_df = pd.DataFrame(
            {
                "value": [10, 20, 30],
            }
        )
        ctx.register_table("data", test_df)

        def helper_impl(ctx):
            data = ctx.get_table("data")
            # Use context helpers (col returns string, lit returns value)
            col_name = ctx.col("value")
            threshold = ctx.lit(15)
            return data[data[col_name] > threshold]

        query = DataFrameQuery(
            query_id="HELPER1",
            query_name="Query with Helpers",
            description="Use context helpers",
            pandas_impl=helper_impl,
        )

        result = adapter.execute_query(ctx, query)

        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2  # 20 and 30


@pytest.mark.skipif(not PANDAS_AVAILABLE, reason="Pandas not installed")
class TestPandasTableLoading:
    """Tests for table loading functionality."""

    def test_load_table_parquet(self, tmp_path):
        """Test loading a table from Parquet."""
        adapter = PandasDataFrameAdapter()
        ctx = adapter.create_context()

        # Create test data
        parquet_path = tmp_path / "orders.parquet"
        pd.DataFrame(
            {
                "id": [1, 2, 3],
                "amount": [100, 200, 300],
            }
        ).to_parquet(parquet_path)

        row_count = adapter.load_table(ctx, "orders", [parquet_path])

        assert ctx.table_exists("orders")
        assert row_count == 3

    def test_load_table_csv(self, tmp_path):
        """Test loading a table from CSV."""
        adapter = PandasDataFrameAdapter()
        ctx = adapter.create_context()

        # Create test data
        csv_path = tmp_path / "customers.csv"
        csv_path.write_text("id,name\n1,Alice\n2,Bob\n")

        row_count = adapter.load_table(ctx, "customers", [csv_path])

        assert ctx.table_exists("customers")
        assert row_count == 2

    def test_load_multiple_tables(self, tmp_path):
        """Test loading multiple tables."""
        adapter = PandasDataFrameAdapter()
        ctx = adapter.create_context()

        # Create test data
        for name, rows in [("orders", 5), ("customers", 3), ("products", 10)]:
            path = tmp_path / f"{name}.parquet"
            pd.DataFrame({"id": list(range(rows))}).to_parquet(path)
            adapter.load_table(ctx, name, [path])

        tables = ctx.list_tables()

        assert len(tables) == 3
        assert all(t in tables for t in ["orders", "customers", "products"])


@pytest.mark.skipif(not PANDAS_AVAILABLE, reason="Pandas not installed")
class TestPandasScalarExtraction:
    """Tests for Pandas scalar extraction optimization."""

    def test_scalar_single_value_dataframe(self):
        """Test scalar extraction from single-value DataFrame."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"value": [42]})
        result = adapter.scalar(df)

        assert result == 42

    def test_scalar_with_column_name(self):
        """Test scalar extraction with explicit column name."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
        result = adapter.scalar(df, column="b")

        assert result == 2

    def test_scalar_first_column_multicolumn_df(self):
        """Test scalar extraction defaults to first column."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"first": [10], "second": [20]})
        result = adapter.scalar(df)

        assert result == 10

    def test_scalar_empty_dataframe_raises(self):
        """Test that scalar extraction on empty DataFrame raises ValueError."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"value": []})

        with pytest.raises(ValueError, match="empty DataFrame"):
            adapter.scalar(df)

    def test_scalar_float_value(self):
        """Test scalar extraction with float value."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"value": [3.14159]})
        result = adapter.scalar(df)

        assert result == pytest.approx(3.14159)

    def test_scalar_string_value(self):
        """Test scalar extraction with string value."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"value": ["hello"]})
        result = adapter.scalar(df)

        assert result == "hello"

    def test_scalar_via_context(self):
        """Test scalar extraction via context (integration)."""
        adapter = PandasDataFrameAdapter()
        ctx = adapter.create_context()

        df = pd.DataFrame({"total": [999]})
        result = ctx.scalar(df)

        assert result == 999

    def test_scalar_multiple_rows_raises(self):
        """Test that scalar extraction on multi-row DataFrame raises ValueError."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"value": [1, 2, 3]})

        with pytest.raises(ValueError, match="exactly one row"):
            adapter.scalar(df)

    def test_scalar_two_rows_raises(self):
        """Test that scalar extraction on 2-row DataFrame raises ValueError."""
        adapter = PandasDataFrameAdapter()

        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})

        with pytest.raises(ValueError, match="exactly one row"):
            adapter.scalar(df)


class TestPandasNotAvailable:
    """Tests for behavior when Pandas is not installed."""

    def test_pandas_available_flag(self):
        """Test that PANDAS_AVAILABLE flag is set correctly."""
        from benchbox.platforms.dataframe.pandas_df import PANDAS_AVAILABLE

        # This just tests that the flag exists and is boolean
        assert isinstance(PANDAS_AVAILABLE, bool)


class TestTypeAwareDateColumnInference:
    """The CSV date heuristic must use schema types, not just column names.

    Regression for SSB: ``lo_orderdate`` / ``lo_commitdate`` are INTEGER YYYYMMDD
    datekeys whose names end in ``date``; the name-only heuristic tried to
    date-parse them and crashed the pandas loader.
    """

    def test_numeric_date_named_column_is_not_a_date(self):
        from benchbox.platforms.dataframe.pandas_df import _pandas_parse_date_columns

        names = ["lo_orderkey", "lo_orderdate", "lo_commitdate", "lo_revenue"]
        types = ["INTEGER", "INTEGER", "INTEGER", "INTEGER"]
        date_cols, datetime_cols = _pandas_parse_date_columns(names, types)
        assert date_cols == []
        assert datetime_cols == []

    def test_string_date_named_column_is_still_a_date(self):
        from benchbox.platforms.dataframe.pandas_df import _pandas_parse_date_columns

        # SSB d_date is VARCHAR; a real string date must still be parsed.
        names = ["d_datekey", "d_date"]
        types = ["INTEGER", "VARCHAR(18)"]
        date_cols, _ = _pandas_parse_date_columns(names, types)
        assert date_cols == ["d_date"]

    def test_without_types_falls_back_to_name_heuristic(self):
        from benchbox.platforms.dataframe.pandas_df import _pandas_parse_date_columns

        # No types supplied -> unchanged legacy behavior (name-only).
        names = ["o_orderdate", "o_custkey"]
        date_cols, _ = _pandas_parse_date_columns(names, None)
        assert date_cols == ["o_orderdate"]

    def test_mismatched_types_length_is_ignored(self):
        from benchbox.platforms.dataframe.pandas_df import _pandas_parse_date_columns

        # A types list that does not align with names is ignored (safe fallback).
        names = ["o_orderdate", "o_custkey"]
        date_cols, _ = _pandas_parse_date_columns(names, ["INTEGER"])  # wrong length
        assert date_cols == ["o_orderdate"]

    def test_is_numeric_sql_type(self):
        from benchbox.platforms.dataframe.pandas_df import _is_numeric_sql_type

        assert _is_numeric_sql_type("INTEGER")
        assert _is_numeric_sql_type("integer")
        assert _is_numeric_sql_type("BIGINT")
        assert _is_numeric_sql_type("DECIMAL(15,2)")
        assert not _is_numeric_sql_type("VARCHAR(18)")
        assert not _is_numeric_sql_type("DATE")
        assert not _is_numeric_sql_type(None)

    def test_read_csv_does_not_date_parse_integer_datekeys(self, tmp_path):
        """End-to-end: read_csv with an integer datekey column must not crash or coerce."""
        from benchbox.platforms.dataframe.pandas_df import PandasDataFrameAdapter

        csv = tmp_path / "lineorder.tbl"
        csv.write_text("1|19920101|100\n2|19980815|200\n")
        adapter = PandasDataFrameAdapter()
        df = adapter.read_csv(
            csv,
            delimiter="|",
            header=None,
            names=["lo_orderkey", "lo_orderdate", "lo_revenue"],
            column_types=["INTEGER", "INTEGER", "INTEGER"],
        )
        # lo_orderdate stays an integer datekey (not a date) and loads cleanly.
        assert df["lo_orderdate"].tolist() == [19920101, 19980815]
