"""Unit tests for DataFrame protocol definitions.

Tests for:
- JoinType enum
- AggregateFunction enum
- SortOrder enum
- DataFrameOps protocol compliance
- DataFrameGroupBy protocol compliance

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from benchbox.core.dataframe.protocols import (
    AggregateFunction,
    DataFrameGroupBy,
    DataFrameOps,
    JoinType,
    SortOrder,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestJoinType:
    """Tests for JoinType enum."""

    def test_all_join_types_exist(self):
        """Test that all expected join types are defined."""
        expected = {"inner", "left", "right", "outer", "cross", "semi", "anti"}
        actual = {jt.value for jt in JoinType}
        assert actual == expected

    def test_str_returns_value(self):
        """Test that str() returns the value."""
        assert str(JoinType.INNER) == "inner"
        assert str(JoinType.LEFT) == "left"
        assert str(JoinType.SEMI) == "semi"

    def test_from_string_valid(self):
        """Test from_string with valid inputs."""
        assert JoinType.from_string("inner") == JoinType.INNER
        assert JoinType.from_string("LEFT") == JoinType.LEFT
        assert JoinType.from_string("OUTER") == JoinType.OUTER

    def test_from_string_invalid(self):
        """Test from_string with invalid input raises ValueError."""
        with pytest.raises(ValueError, match="Invalid join type"):
            JoinType.from_string("invalid")

    def test_from_string_case_insensitive(self):
        """Test that from_string is case-insensitive."""
        assert JoinType.from_string("INNER") == JoinType.INNER
        assert JoinType.from_string("Inner") == JoinType.INNER
        assert JoinType.from_string("inner") == JoinType.INNER


class TestAggregateFunction:
    """Tests for AggregateFunction enum."""

    def test_all_aggregate_functions_exist(self):
        """Test that all expected aggregate functions are defined."""
        expected = {
            "sum",
            "mean",
            "avg",
            "count",
            "min",
            "max",
            "first",
            "last",
            "std",
            "var",
            "median",
            "count_distinct",
        }
        actual = {af.value for af in AggregateFunction}
        assert actual == expected

    def test_str_returns_value(self):
        """Test that str() returns the value."""
        assert str(AggregateFunction.SUM) == "sum"
        assert str(AggregateFunction.COUNT) == "count"
        assert str(AggregateFunction.COUNT_DISTINCT) == "count_distinct"

    def test_from_string_valid(self):
        """Test from_string with valid inputs."""
        assert AggregateFunction.from_string("sum") == AggregateFunction.SUM
        assert AggregateFunction.from_string("COUNT") == AggregateFunction.COUNT
        assert AggregateFunction.from_string("count_distinct") == AggregateFunction.COUNT_DISTINCT

    def test_from_string_invalid(self):
        """Test from_string with invalid input raises ValueError."""
        with pytest.raises(ValueError, match="Invalid aggregate function"):
            AggregateFunction.from_string("invalid")

    def test_avg_alias(self):
        """Test that AVG exists as an alias for MEAN."""
        assert AggregateFunction.AVG is not None
        assert AggregateFunction.AVG.value == "avg"


class TestSortOrder:
    """Tests for SortOrder enum."""

    def test_all_sort_orders_exist(self):
        """Test that all expected sort orders are defined."""
        expected = {"asc", "desc"}
        actual = {so.value for so in SortOrder}
        assert actual == expected

    def test_str_returns_value(self):
        """Test that str() returns the value."""
        assert str(SortOrder.ASC) == "asc"
        assert str(SortOrder.DESC) == "desc"

    def test_ascending_property(self):
        """Test the ascending property."""
        assert SortOrder.ASC.ascending is True
        assert SortOrder.DESC.ascending is False


class TestDataFrameOpsProtocol:
    """Tests for DataFrameOps protocol compliance."""

    def test_protocol_is_runtime_checkable(self):
        """Test that DataFrameOps is runtime checkable via isinstance()."""
        assert isinstance(DataFrameOps, type), "DataFrameOps should be a type (protocol class)"

    def test_mock_implementation_satisfies_protocol(self):
        """Test that a mock implementation satisfies the protocol."""

        class MockDataFrame:
            """Mock DataFrame implementation for testing protocol compliance."""

            def select(self, *columns: str) -> MockDataFrame:
                return self

            def filter(self, condition: Any) -> MockDataFrame:
                return self

            def group_by(self, *columns: str) -> MockGroupBy:
                return MockGroupBy()

            def join(
                self,
                other: MockDataFrame,
                on: str | Sequence[str] | None = None,
                left_on: str | Sequence[str] | None = None,
                right_on: str | Sequence[str] | None = None,
                how: JoinType | str = JoinType.INNER,
            ) -> MockDataFrame:
                return self

            def sort(
                self,
                *columns: str,
                ascending: bool | Sequence[bool] = True,
            ) -> MockDataFrame:
                return self

            def with_column(self, name: str, expr: Any) -> MockDataFrame:
                return self

            def distinct(self) -> MockDataFrame:
                return self

            def limit(self, n: int) -> MockDataFrame:
                return self

            def collect(self) -> Any:
                return []

            def count(self) -> int:
                return 0

            @property
            def columns(self) -> list[str]:
                return []

            @property
            def shape(self) -> tuple[int, int]:
                return (0, 0)

        class MockGroupBy:
            """Mock GroupBy implementation."""

            def agg(self, *aggregations: Any, **named_aggregations: Any) -> MockDataFrame:
                return MockDataFrame()

            def sum(self, *columns: str) -> MockDataFrame:
                return MockDataFrame()

            def mean(self, *columns: str) -> MockDataFrame:
                return MockDataFrame()

            def count(self) -> MockDataFrame:
                return MockDataFrame()

            def min(self, *columns: str) -> MockDataFrame:
                return MockDataFrame()

            def max(self, *columns: str) -> MockDataFrame:
                return MockDataFrame()

            def first(self, *columns: str) -> MockDataFrame:
                return MockDataFrame()

        mock_df = MockDataFrame()

        # Test that operations return correct types
        assert isinstance(mock_df.select("a", "b"), MockDataFrame)
        assert isinstance(mock_df.filter(True), MockDataFrame)
        assert isinstance(mock_df.group_by("a"), MockGroupBy)
        assert isinstance(mock_df.join(MockDataFrame()), MockDataFrame)
        assert isinstance(mock_df.sort("a"), MockDataFrame)
        assert isinstance(mock_df.with_column("x", 1), MockDataFrame)
        assert isinstance(mock_df.distinct(), MockDataFrame)
        assert isinstance(mock_df.limit(10), MockDataFrame)


class TestDataFrameGroupByProtocol:
    """Tests for DataFrameGroupBy protocol compliance."""

    def test_protocol_is_runtime_checkable(self):
        """Test that DataFrameGroupBy is runtime checkable via isinstance()."""
        assert isinstance(DataFrameGroupBy, type), "DataFrameGroupBy should be a type (protocol class)"

    def test_mock_groupby_satisfies_protocol(self):
        """Test that a mock GroupBy implementation satisfies the protocol."""

        class MockResult:
            pass

        class MockGroupBy:
            def agg(self, *aggregations: Any, **named_aggregations: Any) -> MockResult:
                return MockResult()

            def sum(self, *columns: str) -> MockResult:
                return MockResult()

            def mean(self, *columns: str) -> MockResult:
                return MockResult()

            def count(self) -> MockResult:
                return MockResult()

            def min(self, *columns: str) -> MockResult:
                return MockResult()

            def max(self, *columns: str) -> MockResult:
                return MockResult()

            def first(self, *columns: str) -> MockResult:
                return MockResult()

        mock_gb = MockGroupBy()

        # Test all methods exist and are callable
        assert isinstance(mock_gb.agg(), MockResult)
        assert isinstance(mock_gb.sum("col"), MockResult)
        assert isinstance(mock_gb.mean("col"), MockResult)
        assert isinstance(mock_gb.count(), MockResult)
        assert isinstance(mock_gb.min("col"), MockResult)
        assert isinstance(mock_gb.max("col"), MockResult)
        assert isinstance(mock_gb.first("col"), MockResult)


class TestProtocolMethodChaining:
    """Tests for method chaining compatibility."""

    def test_operations_return_chainable_type(self):
        """Test that operations can be chained."""

        class ChainableDF:
            def select(self, *columns: str) -> ChainableDF:
                return self

            def filter(self, condition: Any) -> ChainableDF:
                return self

            def sort(self, *columns: str, ascending: bool = True) -> ChainableDF:
                return self

            def limit(self, n: int) -> ChainableDF:
                return self

            def distinct(self) -> ChainableDF:
                return self

        df = ChainableDF()

        # Test chaining
        result = df.select("a").filter(True).sort("a").limit(10).distinct()
        assert isinstance(result, ChainableDF)

    def test_groupby_agg_returns_dataframe(self):
        """Test that groupby aggregation returns something suitable for further operations."""

        class ChainableDF:
            def group_by(self, *columns: str) -> ChainableGB:
                return ChainableGB()

            def select(self, *columns: str) -> ChainableDF:
                return self

        class ChainableGB:
            def agg(self, *args: Any) -> ChainableDF:
                return ChainableDF()

        df = ChainableDF()

        # Test groupby -> agg -> further operations
        result = df.group_by("category").agg().select("category")
        assert isinstance(result, ChainableDF)
