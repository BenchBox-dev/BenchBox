"""Unit tests for DataFrameContext protocol and implementation.

Tests for:
- DataFrameContext protocol compliance
- DataFrameContextImpl base functionality
- Table registration and retrieval
- Expression helper methods

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest

from benchbox.core.dataframe.context import (
    DataFrameContext,
    DataFrameContextImpl,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class ConcreteContext(DataFrameContextImpl[dict]):
    """Concrete implementation of DataFrameContextImpl for testing.

    Uses plain dictionaries as the DataFrame type for simplicity.
    """

    def col(self, name: str) -> str:
        """Return column name as string (Pandas-like behavior)."""
        return name

    def lit(self, value: Any) -> Any:
        """Return literal value directly."""
        return value

    def date_sub(self, column: Any, days: int) -> dict[str, Any]:
        """Return a dict representing date subtraction."""
        return {"op": "date_sub", "column": column, "days": days}

    def date_add(self, column: Any, days: int) -> dict[str, Any]:
        """Return a dict representing date addition."""
        return {"op": "date_add", "column": column, "days": days}

    def cast_date(self, column: Any) -> dict[str, Any]:
        """Return a dict representing date cast."""
        return {"op": "cast_date", "column": column}

    def cast_string(self, column: Any) -> dict[str, Any]:
        """Return a dict representing string cast."""
        return {"op": "cast_string", "column": column}

    def _window_descriptor(self, op: str, **kwargs: Any) -> dict[str, Any]:
        """Helper to describe window operations for tests."""
        return {"op": op, **kwargs}

    def window_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> dict[str, Any]:
        """Describe a window RANK operation."""
        return self._window_descriptor(
            "window_rank",
            order_by=order_by,
            partition_by=partition_by or [],
        )

    def window_row_number(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> dict[str, Any]:
        """Describe a window ROW_NUMBER operation."""
        return self._window_descriptor(
            "window_row_number",
            order_by=order_by,
            partition_by=partition_by or [],
        )

    def window_dense_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> dict[str, Any]:
        """Describe a window DENSE_RANK operation."""
        return self._window_descriptor(
            "window_dense_rank",
            order_by=order_by,
            partition_by=partition_by or [],
        )

    def window_sum(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> dict[str, Any]:
        """Describe a window SUM operation."""
        return self._window_descriptor(
            "window_sum",
            column=column,
            partition_by=partition_by or [],
            order_by=order_by,
        )

    def window_avg(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> dict[str, Any]:
        """Describe a window AVG operation."""
        return self._window_descriptor(
            "window_avg",
            column=column,
            partition_by=partition_by or [],
            order_by=order_by,
        )

    def window_count(
        self,
        column: str | None = None,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> dict[str, Any]:
        """Describe a window COUNT operation."""
        return self._window_descriptor(
            "window_count",
            column=column,
            partition_by=partition_by or [],
            order_by=order_by,
        )

    def window_min(self, column: str, partition_by: list[str] | None = None) -> dict[str, Any]:
        """Describe a window MIN operation."""
        return self._window_descriptor(
            "window_min",
            column=column,
            partition_by=partition_by or [],
        )

    def window_max(self, column: str, partition_by: list[str] | None = None) -> dict[str, Any]:
        """Describe a window MAX operation."""
        return self._window_descriptor(
            "window_max",
            column=column,
            partition_by=partition_by or [],
        )

    def union_all(self, *dataframes: Any) -> list[Any]:
        """Return all frames (union descriptor)."""
        return list(dataframes)

    def rename_columns(self, df: Any, mapping: dict[str, str]) -> dict[str, Any]:
        """Return a descriptor describing renamed columns."""
        return {"df": df, "mapping": mapping}

    def scalar(self, df: Any, column: str | None = None) -> Any:
        """Extract a single scalar value from a DataFrame.

        For testing, assumes df is a dict with data, returns first value.
        """
        if isinstance(df, dict):
            if column is not None and column in df:
                values = df[column]
                if isinstance(values, list) and len(values) > 0:
                    return values[0]
            # Return first value from first column
            for key, values in df.items():
                if isinstance(values, list) and len(values) > 0:
                    return values[0]
        return None

    def scalar_to_df(self, data: dict[str, Any]) -> dict[str, list[Any]]:
        """Create a single-row DataFrame (dict) from scalar values.

        For testing, returns a dict with lists containing the scalar values.
        """
        return {k: [v] for k, v in data.items()}


class TestDataFrameContextProtocol:
    """Tests for DataFrameContext protocol."""

    def test_protocol_is_runtime_checkable(self):
        """Test that DataFrameContext is runtime checkable."""
        ctx = ConcreteContext(platform="test", family="pandas")
        assert isinstance(ctx, DataFrameContext)

    def test_concrete_implementation_satisfies_protocol(self):
        """Test that ConcreteContext satisfies the protocol."""
        ctx = ConcreteContext(platform="test", family="pandas")

        # Check all required methods exist and are callable
        assert hasattr(ctx, "get_table")
        assert hasattr(ctx, "list_tables")
        assert hasattr(ctx, "table_exists")
        assert hasattr(ctx, "col")
        assert hasattr(ctx, "lit")
        assert hasattr(ctx, "date_sub")
        assert hasattr(ctx, "date_add")
        assert hasattr(ctx, "cast_date")
        assert hasattr(ctx, "cast_string")
        assert hasattr(ctx, "family")


class TestDataFrameContextImpl:
    """Tests for DataFrameContextImpl base class."""

    def test_initialization(self):
        """Test context initialization."""
        ctx = ConcreteContext(platform="pandas", family="pandas")

        assert ctx.platform == "pandas"
        assert ctx.family == "pandas"
        assert ctx.list_tables() == []

    def test_register_table(self):
        """Test table registration."""
        ctx = ConcreteContext(platform="test", family="pandas")

        table_data = {"id": [1, 2, 3], "name": ["a", "b", "c"]}
        ctx.register_table("users", table_data)

        assert ctx.table_exists("users")
        assert ctx.get_table("users") == table_data

    def test_register_table_lowercase(self):
        """Test that table names are lowercased."""
        ctx = ConcreteContext(platform="test", family="pandas")

        table_data = {"id": [1, 2, 3]}
        ctx.register_table("USERS", table_data)

        assert ctx.table_exists("users")
        assert ctx.table_exists("USERS")
        assert ctx.table_exists("Users")

    def test_get_table_case_insensitive(self):
        """Test that get_table is case-insensitive."""
        ctx = ConcreteContext(platform="test", family="pandas")

        table_data = {"id": [1, 2, 3]}
        ctx.register_table("orders", table_data)

        assert ctx.get_table("orders") == table_data
        assert ctx.get_table("ORDERS") == table_data
        assert ctx.get_table("Orders") == table_data

    def test_get_table_not_found(self):
        """Test get_table raises KeyError for missing table."""
        ctx = ConcreteContext(platform="test", family="pandas")

        with pytest.raises(KeyError, match="not found"):
            ctx.get_table("missing")

    def test_get_table_error_shows_available(self):
        """Test that KeyError message shows available tables."""
        ctx = ConcreteContext(platform="test", family="pandas")
        ctx.register_table("users", {})
        ctx.register_table("orders", {})

        with pytest.raises(KeyError, match="Available tables:.*orders.*users"):
            ctx.get_table("products")

    def test_list_tables_sorted(self):
        """Test that list_tables returns sorted list."""
        ctx = ConcreteContext(platform="test", family="pandas")

        ctx.register_table("orders", {})
        ctx.register_table("users", {})
        ctx.register_table("products", {})

        tables = ctx.list_tables()
        assert tables == ["orders", "products", "users"]

    def test_table_exists(self):
        """Test table_exists method."""
        ctx = ConcreteContext(platform="test", family="pandas")

        ctx.register_table("users", {})

        assert ctx.table_exists("users") is True
        assert ctx.table_exists("orders") is False

    def test_unregister_table(self):
        """Test table unregistration."""
        ctx = ConcreteContext(platform="test", family="pandas")

        ctx.register_table("users", {})
        assert ctx.table_exists("users")

        result = ctx.unregister_table("users")
        assert result is True
        assert not ctx.table_exists("users")

    def test_unregister_table_not_found(self):
        """Test unregister returns False for missing table."""
        ctx = ConcreteContext(platform="test", family="pandas")

        result = ctx.unregister_table("missing")
        assert result is False

    def test_clear_tables(self):
        """Test clearing all tables."""
        ctx = ConcreteContext(platform="test", family="pandas")

        ctx.register_table("users", {})
        ctx.register_table("orders", {})

        assert len(ctx.list_tables()) == 2

        ctx.clear_tables()

        assert len(ctx.list_tables()) == 0

    def test_col_method(self):
        """Test col method."""
        ctx = ConcreteContext(platform="test", family="pandas")

        result = ctx.col("amount")
        assert result == "amount"

    def test_lit_method(self):
        """Test lit method."""
        ctx = ConcreteContext(platform="test", family="pandas")

        assert ctx.lit(100) == 100
        assert ctx.lit("hello") == "hello"
        assert ctx.lit(3.14) == 3.14

    def test_date_sub_method(self):
        """Test date_sub method."""
        ctx = ConcreteContext(platform="test", family="pandas")

        result = ctx.date_sub("date_col", 7)

        assert result["op"] == "date_sub"
        assert result["column"] == "date_col"
        assert result["days"] == 7

    def test_date_add_method(self):
        """Test date_add method."""
        ctx = ConcreteContext(platform="test", family="pandas")

        result = ctx.date_add("date_col", 30)

        assert result["op"] == "date_add"
        assert result["column"] == "date_col"
        assert result["days"] == 30

    def test_cast_date_method(self):
        """Test cast_date method."""
        ctx = ConcreteContext(platform="test", family="pandas")

        result = ctx.cast_date("string_col")

        assert result["op"] == "cast_date"
        assert result["column"] == "string_col"

    def test_cast_string_method(self):
        """Test cast_string method."""
        ctx = ConcreteContext(platform="test", family="pandas")

        result = ctx.cast_string("int_col")

        assert result["op"] == "cast_string"
        assert result["column"] == "int_col"

    def test_to_date_from_string(self):
        """Test to_date with string input."""
        ctx = ConcreteContext(platform="test", family="pandas")

        result = ctx.to_date("2024-03-15")

        assert isinstance(result, date)
        assert result.year == 2024
        assert result.month == 3
        assert result.day == 15

    def test_to_date_from_date(self):
        """Test to_date with date input."""
        ctx = ConcreteContext(platform="test", family="pandas")

        input_date = date(2024, 3, 15)
        result = ctx.to_date(input_date)

        assert result == input_date

    def test_to_date_from_datetime(self):
        """Test to_date with datetime input."""
        ctx = ConcreteContext(platform="test", family="pandas")

        input_dt = datetime(2024, 3, 15, 12, 30, 45)
        result = ctx.to_date(input_dt)

        assert isinstance(result, date)
        assert result == date(2024, 3, 15)

    def test_to_date_invalid_type(self):
        """Test to_date with invalid input type."""
        ctx = ConcreteContext(platform="test", family="pandas")

        with pytest.raises(TypeError, match="Cannot convert"):
            ctx.to_date(12345)

    def test_days_method(self):
        """Test days helper method."""
        ctx = ConcreteContext(platform="test", family="pandas")

        result = ctx.days(7)

        assert isinstance(result, timedelta)
        assert result.days == 7

    def test_days_negative(self):
        """Test days with negative value."""
        ctx = ConcreteContext(platform="test", family="pandas")

        result = ctx.days(-5)

        assert result.days == -5


class TestDataFrameContextMultipleRegistrations:
    """Tests for complex table registration scenarios."""

    def test_overwrite_table(self):
        """Test that re-registering a table overwrites it."""
        ctx = ConcreteContext(platform="test", family="pandas")

        ctx.register_table("users", {"version": 1})
        assert ctx.get_table("users") == {"version": 1}

        ctx.register_table("users", {"version": 2})
        assert ctx.get_table("users") == {"version": 2}

    def test_register_multiple_tables(self):
        """Test registering many tables."""
        ctx = ConcreteContext(platform="test", family="pandas")

        tables = {
            "customer": {"c_id": [1, 2]},
            "orders": {"o_id": [1, 2, 3]},
            "lineitem": {"l_id": [1, 2, 3, 4]},
            "part": {"p_id": [1]},
            "supplier": {"s_id": [1, 2]},
            "partsupp": {"ps_id": [1, 2, 3]},
            "nation": {"n_id": [1, 2, 3, 4, 5]},
            "region": {"r_id": [1]},
        }

        for name, data in tables.items():
            ctx.register_table(name, data)

        assert len(ctx.list_tables()) == 8

        for name, data in tables.items():
            assert ctx.get_table(name) == data


class TestDataFrameContextFamily:
    """Tests for family-specific behavior."""

    def test_pandas_family(self):
        """Test context with pandas family."""
        ctx = ConcreteContext(platform="pandas", family="pandas")

        assert ctx.family == "pandas"
        assert ctx.platform == "pandas"

    def test_expression_family(self):
        """Test context with expression family."""
        ctx = ConcreteContext(platform="polars", family="expression")

        assert ctx.family == "expression"
        assert ctx.platform == "polars"

    def test_different_platforms_same_family(self):
        """Test different platforms in same family."""
        pandas_ctx = ConcreteContext(platform="pandas", family="pandas")
        modin_ctx = ConcreteContext(platform="modin", family="pandas")

        assert pandas_ctx.family == modin_ctx.family
        assert pandas_ctx.platform != modin_ctx.platform
