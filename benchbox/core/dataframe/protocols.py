# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence


DF = TypeVar("DF", covariant=True)
Expr = TypeVar("Expr")


class JoinType(Enum):
    INNER = "inner"
    LEFT = "left"
    RIGHT = "right"
    OUTER = "outer"
    CROSS = "cross"
    SEMI = "semi"
    ANTI = "anti"

    def __str__(self) -> str:

        return self.value

    @classmethod
    def from_string(cls, value: str) -> JoinType:

        value_lower = value.lower()
        for join_type in cls:
            if join_type.value == value_lower:
                return join_type
        raise ValueError(f"Invalid join type: {value}. Valid types: {[j.value for j in cls]}")


class AggregateFunction(Enum):
    SUM = "sum"
    MEAN = "mean"
    AVG = "avg"
    COUNT = "count"
    MIN = "min"
    MAX = "max"
    FIRST = "first"
    LAST = "last"
    STD = "std"
    VAR = "var"
    MEDIAN = "median"
    COUNT_DISTINCT = "count_distinct"

    def __str__(self) -> str:

        return self.value

    @classmethod
    def from_string(cls, value: str) -> AggregateFunction:

        value_lower = value.lower()
        for agg_func in cls:
            if agg_func.value == value_lower:
                return agg_func
        raise ValueError(f"Invalid aggregate function: {value}. Valid functions: {[a.value for a in cls]}")


class SortOrder(Enum):
    ASC = "asc"
    DESC = "desc"

    def __str__(self) -> str:

        return self.value

    @property
    def ascending(self) -> bool:

        return self == SortOrder.ASC


@runtime_checkable
class DataFrameOps(Protocol[DF]):
    def select(self, *columns: str) -> DataFrameOps[DF]: ...

    def filter(self, condition: Any) -> DataFrameOps[DF]: ...

    def group_by(self, *columns: str) -> DataFrameGroupBy[DF]: ...

    def join(
        self,
        other: DataFrameOps[DF],
        on: str | Sequence[str] | None = None,
        left_on: str | Sequence[str] | None = None,
        right_on: str | Sequence[str] | None = None,
        how: JoinType | str = JoinType.INNER,
    ) -> DataFrameOps[DF]: ...

    def sort(
        self,
        *columns: str,
        ascending: bool | Sequence[bool] = True,
    ) -> DataFrameOps[DF]: ...

    def with_column(self, name: str, expr: Any) -> DataFrameOps[DF]: ...

    def distinct(self) -> DataFrameOps[DF]: ...

    def limit(self, n: int) -> DataFrameOps[DF]: ...

    def collect(self) -> Any: ...

    def count(self) -> int: ...

    @property
    def columns(self) -> list[str]: ...

    @property
    def shape(self) -> tuple[int, int]: ...


@runtime_checkable
class DataFrameGroupBy(Protocol[DF]):
    def agg(self, *_aggregations: Any, **_named_aggregations: Any) -> DataFrameOps[DF]: ...

    def sum(self, *columns: str) -> DataFrameOps[DF]: ...

    def mean(self, *columns: str) -> DataFrameOps[DF]: ...

    def count(self) -> DataFrameOps[DF]: ...

    def min(self, *columns: str) -> DataFrameOps[DF]: ...

    def max(self, *columns: str) -> DataFrameOps[DF]: ...

    def first(self, *columns: str) -> DataFrameOps[DF]: ...
