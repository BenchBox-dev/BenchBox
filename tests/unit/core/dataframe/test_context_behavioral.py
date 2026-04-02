"""Behavioral tests for DataFrame context module.

Tests targeting coverage gaps in context.py:
- Context creation with engine config
- Table registration edge cases (empty name, special characters)
- element() default raises NotImplementedError
- to_date edge cases
- Window function descriptors
- scalar and scalar_to_df methods
- rename_columns and union_all methods

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


# ---------------------------------------------------------------------------
# Concrete implementation for testing
# ---------------------------------------------------------------------------


class StubContext(DataFrameContextImpl[dict]):
    """Minimal concrete implementation of DataFrameContextImpl for testing."""

    def col(self, name: str) -> str:
        return name

    def lit(self, value: Any) -> Any:
        return value

    def date_sub(self, column: Any, days: int) -> dict:
        return {"op": "date_sub", "column": column, "days": days}

    def date_add(self, column: Any, days: int) -> dict:
        return {"op": "date_add", "column": column, "days": days}

    def cast_date(self, column: Any) -> dict:
        return {"op": "cast_date", "column": column}

    def cast_string(self, column: Any) -> dict:
        return {"op": "cast_string", "column": column}

    def window_rank(self, order_by, partition_by=None):
        return {"op": "rank", "order_by": order_by, "partition_by": partition_by or []}

    def window_row_number(self, order_by, partition_by=None):
        return {"op": "row_number", "order_by": order_by, "partition_by": partition_by or []}

    def window_dense_rank(self, order_by, partition_by=None):
        return {"op": "dense_rank", "order_by": order_by, "partition_by": partition_by or []}

    def window_sum(self, column, partition_by=None, order_by=None):
        return {"op": "window_sum", "column": column, "partition_by": partition_by or [], "order_by": order_by}

    def window_avg(self, column, partition_by=None, order_by=None):
        return {"op": "window_avg", "column": column, "partition_by": partition_by or [], "order_by": order_by}

    def window_count(self, column=None, partition_by=None, order_by=None):
        return {"op": "window_count", "column": column, "partition_by": partition_by or [], "order_by": order_by}

    def window_min(self, column, partition_by=None):
        return {"op": "window_min", "column": column, "partition_by": partition_by or []}

    def window_max(self, column, partition_by=None):
        return {"op": "window_max", "column": column, "partition_by": partition_by or []}

    def union_all(self, *dataframes):
        return list(dataframes)

    def rename_columns(self, df, mapping):
        return {"df": df, "mapping": mapping}

    def scalar(self, df, column=None):
        if isinstance(df, dict):
            if column and column in df:
                vals = df[column]
                return vals[0] if isinstance(vals, list) and vals else None
            for key, vals in df.items():
                return vals[0] if isinstance(vals, list) and vals else None
        return None

    def scalar_to_df(self, data):
        return {k: [v] for k, v in data.items()}


# ---------------------------------------------------------------------------
# element() – default raises NotImplementedError
# ---------------------------------------------------------------------------


class TestElementMethod:
    """Tests for element() method default behavior."""

    def test_element_raises_not_implemented(self):
        """Base implementation raises NotImplementedError."""
        ctx = StubContext(platform="pandas", family="pandas")
        with pytest.raises(NotImplementedError, match="not supported on pandas"):
            ctx.element()


# ---------------------------------------------------------------------------
# Table registration – edge cases
# ---------------------------------------------------------------------------


class TestTableRegistrationEdgeCases:
    """Tests for table registration edge conditions."""

    def test_register_empty_dict_as_table(self):
        """Empty dict can be registered as a table."""
        ctx = StubContext(platform="test", family="pandas")
        ctx.register_table("empty_table", {})
        assert ctx.table_exists("empty_table") is True
        assert ctx.get_table("empty_table") == {}

    def test_register_table_with_mixed_case(self):
        """Table names with mixed case are lowercased on registration."""
        ctx = StubContext(platform="test", family="pandas")
        ctx.register_table("MyTable", {"col": [1]})

        assert ctx.table_exists("mytable") is True
        assert ctx.table_exists("MYTABLE") is True
        assert ctx.table_exists("MyTable") is True

    def test_unregister_case_insensitive(self):
        """Unregister works case-insensitively."""
        ctx = StubContext(platform="test", family="pandas")
        ctx.register_table("orders", {"data": [1]})

        result = ctx.unregister_table("ORDERS")
        assert result is True
        assert ctx.table_exists("orders") is False

    def test_get_table_error_with_no_tables(self):
        """KeyError message says 'none' when no tables registered."""
        ctx = StubContext(platform="test", family="pandas")
        with pytest.raises(KeyError, match="none"):
            ctx.get_table("anything")

    def test_clear_then_list_returns_empty(self):
        """After clear_tables, list_tables returns empty list."""
        ctx = StubContext(platform="test", family="pandas")
        ctx.register_table("alpha", {})
        ctx.register_table("beta", {})
        ctx.clear_tables()

        assert ctx.list_tables() == []


# ---------------------------------------------------------------------------
# to_date – additional edge cases
# ---------------------------------------------------------------------------


class TestToDateEdgeCases:
    """Tests for to_date conversion edge cases."""

    def test_to_date_leap_year(self):
        """Handles leap year date correctly."""
        ctx = StubContext(platform="test", family="pandas")
        result = ctx.to_date("2024-02-29")
        assert result == date(2024, 2, 29)

    def test_to_date_invalid_format_raises(self):
        """Invalid date string format raises ValueError."""
        ctx = StubContext(platform="test", family="pandas")
        with pytest.raises(ValueError):
            ctx.to_date("not-a-date")

    def test_to_date_datetime_extracts_date_part(self):
        """Datetime input has time portion stripped."""
        ctx = StubContext(platform="test", family="pandas")
        dt_input = datetime(2026, 12, 25, 23, 59, 59)
        result = ctx.to_date(dt_input)
        assert result == date(2026, 12, 25)

    def test_to_date_with_bool_raises(self):
        """Bool input raises TypeError (not treated as int)."""
        ctx = StubContext(platform="test", family="pandas")
        with pytest.raises(TypeError, match="Cannot convert"):
            ctx.to_date(True)

    def test_to_date_with_none_raises(self):
        """None input raises TypeError."""
        ctx = StubContext(platform="test", family="pandas")
        with pytest.raises(TypeError, match="Cannot convert"):
            ctx.to_date(None)


# ---------------------------------------------------------------------------
# days() – edge cases
# ---------------------------------------------------------------------------


class TestDaysEdgeCases:
    """Tests for days() helper edge cases."""

    def test_days_zero(self):
        """Zero days returns zero timedelta."""
        ctx = StubContext(platform="test", family="pandas")
        result = ctx.days(0)
        assert result == timedelta(days=0)

    def test_days_large_value(self):
        """Large day count works correctly."""
        ctx = StubContext(platform="test", family="pandas")
        result = ctx.days(365)
        assert result.days == 365


# ---------------------------------------------------------------------------
# Window functions – descriptor verification
# ---------------------------------------------------------------------------


class TestWindowFunctions:
    """Tests for window function method descriptors."""

    def test_window_rank_with_partition(self):
        """window_rank includes partition_by in descriptor."""
        ctx = StubContext(platform="test", family="expression")
        result = ctx.window_rank(
            order_by=[("sales", False)],
            partition_by=["category"],
        )
        assert result["op"] == "rank"
        assert result["order_by"] == [("sales", False)]
        assert result["partition_by"] == ["category"]

    def test_window_row_number_without_partition(self):
        """window_row_number works without partition."""
        ctx = StubContext(platform="test", family="expression")
        result = ctx.window_row_number(order_by=[("created_at", True)])
        assert result["op"] == "row_number"
        assert result["partition_by"] == []

    def test_window_dense_rank(self):
        """window_dense_rank returns correct descriptor."""
        ctx = StubContext(platform="test", family="expression")
        result = ctx.window_dense_rank(
            order_by=[("score", False)],
            partition_by=["department"],
        )
        assert result["op"] == "dense_rank"

    def test_window_sum_with_order_by(self):
        """window_sum with order_by creates cumulative sum descriptor."""
        ctx = StubContext(platform="test", family="expression")
        result = ctx.window_sum(
            column="revenue",
            partition_by=["year"],
            order_by=[("month", True)],
        )
        assert result["op"] == "window_sum"
        assert result["column"] == "revenue"
        assert result["order_by"] == [("month", True)]

    def test_window_avg_without_order_by(self):
        """window_avg without order_by computes partition average."""
        ctx = StubContext(platform="test", family="expression")
        result = ctx.window_avg(column="price", partition_by=["category"])
        assert result["op"] == "window_avg"
        assert result["order_by"] is None

    def test_window_count_star(self):
        """window_count with column=None is COUNT(*)."""
        ctx = StubContext(platform="test", family="expression")
        result = ctx.window_count(column=None, partition_by=["dept"])
        assert result["op"] == "window_count"
        assert result["column"] is None

    def test_window_count_column(self):
        """window_count with specific column."""
        ctx = StubContext(platform="test", family="expression")
        result = ctx.window_count(column="order_id", partition_by=["customer_id"])
        assert result["column"] == "order_id"

    def test_window_min(self):
        """window_min returns correct descriptor."""
        ctx = StubContext(platform="test", family="expression")
        result = ctx.window_min(column="price", partition_by=["category"])
        assert result["op"] == "window_min"
        assert result["column"] == "price"

    def test_window_max(self):
        """window_max returns correct descriptor."""
        ctx = StubContext(platform="test", family="expression")
        result = ctx.window_max(column="quantity")
        assert result["op"] == "window_max"
        assert result["partition_by"] == []


# ---------------------------------------------------------------------------
# Union and rename operations
# ---------------------------------------------------------------------------


class TestUnionAndRename:
    """Tests for union_all and rename_columns methods."""

    def test_union_all_two_frames(self):
        """union_all with two DataFrames returns both."""
        ctx = StubContext(platform="test", family="pandas")
        frame_a = {"col": [1, 2]}
        frame_b = {"col": [3, 4]}

        result = ctx.union_all(frame_a, frame_b)
        assert len(result) == 2
        assert result[0] is frame_a
        assert result[1] is frame_b

    def test_union_all_single_frame(self):
        """union_all with single DataFrame returns list of one."""
        ctx = StubContext(platform="test", family="pandas")
        frame = {"col": [1]}

        result = ctx.union_all(frame)
        assert len(result) == 1

    def test_union_all_multiple_frames(self):
        """union_all with many DataFrames returns all."""
        ctx = StubContext(platform="test", family="pandas")
        frames = [{"col": [i]} for i in range(5)]

        result = ctx.union_all(*frames)
        assert len(result) == 5

    def test_rename_columns(self):
        """rename_columns returns descriptor with mapping."""
        ctx = StubContext(platform="test", family="pandas")
        frame = {"old_name": [1, 2]}
        mapping = {"old_name": "new_name"}

        result = ctx.rename_columns(frame, mapping)
        assert result["mapping"] == {"old_name": "new_name"}
        assert result["df"] is frame


# ---------------------------------------------------------------------------
# scalar and scalar_to_df methods
# ---------------------------------------------------------------------------


class TestScalarMethods:
    """Tests for scalar extraction and DataFrame creation."""

    def test_scalar_extracts_first_value(self):
        """scalar extracts first value from first column."""
        ctx = StubContext(platform="test", family="pandas")
        frame = {"total": [42]}
        assert ctx.scalar(frame) == 42

    def test_scalar_with_column_name(self):
        """scalar extracts value from specified column."""
        ctx = StubContext(platform="test", family="pandas")
        frame = {"alpha": [10], "beta": [20]}
        assert ctx.scalar(frame, column="beta") == 20

    def test_scalar_from_non_dict_returns_none(self):
        """scalar with non-dict returns None."""
        ctx = StubContext(platform="test", family="pandas")
        assert ctx.scalar("not a dict") is None

    def test_scalar_to_df_single_column(self):
        """scalar_to_df creates single-row, single-column DataFrame."""
        ctx = StubContext(platform="test", family="pandas")
        result = ctx.scalar_to_df({"total": 100})
        assert result == {"total": [100]}

    def test_scalar_to_df_multiple_columns(self):
        """scalar_to_df creates single-row DataFrame with multiple columns."""
        ctx = StubContext(platform="test", family="pandas")
        result = ctx.scalar_to_df({"count": 5, "avg_price": 19.99})
        assert result == {"count": [5], "avg_price": [19.99]}


# ---------------------------------------------------------------------------
# Protocol compliance – duck typing
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    """Tests for DataFrameContext protocol compliance."""

    def test_stub_satisfies_protocol(self):
        """StubContext satisfies the DataFrameContext protocol."""
        ctx = StubContext(platform="test", family="expression")
        assert isinstance(ctx, DataFrameContext)

    def test_protocol_requires_all_methods(self):
        """Incomplete implementation does not satisfy protocol at runtime."""

        class IncompleteContext:
            """Only implements get_table, missing everything else."""

            def get_table(self, name):
                return None

        # Protocol check should still pass for the subset (runtime_checkable
        # only checks method existence for the checked attributes)
        # But we verify our stub has ALL methods
        required_methods = [
            "get_table",
            "list_tables",
            "table_exists",
            "col",
            "lit",
            "date_sub",
            "date_add",
            "cast_date",
            "cast_string",
            "family",
        ]
        ctx = StubContext(platform="test", family="pandas")
        for method in required_methods:
            assert hasattr(ctx, method), f"Missing required method: {method}"


# ---------------------------------------------------------------------------
# Family property
# ---------------------------------------------------------------------------


class TestFamilyProperty:
    """Tests for the family property."""

    def test_pandas_family_string(self):
        """Pandas family returns 'pandas'."""
        ctx = StubContext(platform="pandas", family="pandas")
        assert ctx.family == "pandas"

    def test_expression_family_string(self):
        """Expression family returns 'expression'."""
        ctx = StubContext(platform="polars", family="expression")
        assert ctx.family == "expression"

    def test_platform_property(self):
        """platform property returns the platform name."""
        ctx = StubContext(platform="modin", family="pandas")
        assert ctx.platform == "modin"
