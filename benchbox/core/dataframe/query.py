# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import TYPE_CHECKING, Any, Callable, Iterable, NamedTuple

if TYPE_CHECKING:
    from benchbox.core.dataframe.context import DataFrameContext


class QueryCategory(Enum):
    SCAN = "scan"
    PROJECTION = "projection"
    FILTER = "filter"
    SORT = "sort"

    AGGREGATE = "aggregate"
    GROUP_BY = "group_by"

    JOIN = "join"
    MULTI_JOIN = "multi_join"

    SUBQUERY = "subquery"
    WINDOW = "window"
    ANALYTICAL = "analytical"

    TPCH = "tpch"
    TPCDS = "tpcds"

    def __str__(self) -> str:

        return self.value


@dataclass
class DataFrameQuery:
    query_id: str
    query_name: str
    description: str
    categories: list[QueryCategory] = field(default_factory=list)
    pandas_impl: Callable[[DataFrameContext], Any] | None = None
    expression_impl: Callable[[DataFrameContext], Any] | None = None
    sql_equivalent: str | None = None
    expected_row_count: int | None = None
    scale_factor_dependent: bool = False
    timeout_seconds: float | None = None
    skip_platforms: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:

        self._validate()

    def _validate(self) -> None:

        if not self.query_id:
            raise ValueError("query_id cannot be empty")

        if not self.query_name:
            raise ValueError("query_name cannot be empty")

        if self.pandas_impl is None and self.expression_impl is None:
            raise ValueError(
                f"Query '{self.query_id}' must have at least one implementation (pandas_impl or expression_impl)"
            )

    def has_pandas_impl(self) -> bool:

        return self.pandas_impl is not None

    def has_expression_impl(self) -> bool:

        return self.expression_impl is not None

    def has_sql_equivalent(self) -> bool:

        return self.sql_equivalent is not None

    def supports_platform(self, platform: str) -> bool:

        if platform.lower() in [p.lower() for p in self.skip_platforms]:
            return False

        pandas_family = {"pandas", "cudf", "vaex", "dask"}
        expression_family = {"polars", "pyspark", "datafusion", "spark"}

        platform_lower = platform.lower()
        if platform_lower in pandas_family:
            return self.has_pandas_impl()
        elif platform_lower in expression_family:
            return self.has_expression_impl()

        return False

    def get_impl_for_family(self, family: str) -> Callable[[DataFrameContext], Any] | None:

        family_lower = family.lower()
        if family_lower == "pandas":
            return self.pandas_impl
        elif family_lower == "expression":
            return self.expression_impl
        else:
            raise ValueError(f"Unknown family: {family}. Must be 'pandas' or 'expression'")

    def execute(self, ctx: DataFrameContext, family: str) -> Any:

        impl = self.get_impl_for_family(family)
        if impl is None:
            raise ValueError(f"Query '{self.query_id}' has no {family} implementation")

        return impl(ctx)

    def in_category(self, category: QueryCategory) -> bool:

        return category in self.categories

    def to_dict(self) -> dict[str, Any]:

        return {
            "query_id": self.query_id,
            "query_name": self.query_name,
            "description": self.description,
            "categories": [c.value for c in self.categories],
            "has_pandas_impl": self.has_pandas_impl(),
            "has_expression_impl": self.has_expression_impl(),
            "sql_equivalent": self.sql_equivalent,
            "expected_row_count": self.expected_row_count,
            "scale_factor_dependent": self.scale_factor_dependent,
            "timeout_seconds": self.timeout_seconds,
            "skip_platforms": self.skip_platforms,
        }


class QueryRegistry:
    def __init__(self, benchmark: str, loader: Callable[[], Iterable[DataFrameQuery]] | None = None) -> None:

        self.benchmark = benchmark
        self._queries: dict[str, DataFrameQuery] = {}
        self._loader = loader
        self._load_lock = Lock()
        self._loaded = False
        self._load_hits = 0
        self._load_misses = 0

    def set_loader(self, loader: Callable[[], Iterable[DataFrameQuery]]) -> None:

        with self._load_lock:
            if self._loaded or self._queries:
                raise RuntimeError(f"{self.benchmark} registry loader cannot be changed after loading")
            self._loader = loader

    def _register_query(self, query: DataFrameQuery) -> None:
        if query.query_id in self._queries:
            raise ValueError(f"Query '{query.query_id}' already registered in {self.benchmark} registry")
        self._queries[query.query_id] = query

    def _ensure_loaded(self) -> None:
        if self._loader is None:
            return
        with self._load_lock:
            if self._loaded:
                self._load_hits += 1
                return
            if self._loader is None:
                return

            self._load_misses += 1
            for query in self._loader():
                self._register_query(query)
            self._loaded = True

    def register(self, query: DataFrameQuery) -> None:

        self._ensure_loaded()
        self._register_query(query)

    def register_many(self, queries: list[DataFrameQuery]) -> None:

        self._ensure_loaded()
        for query in queries:
            self._register_query(query)

    def get(self, query_id: str) -> DataFrameQuery | None:

        self._ensure_loaded()
        return self._queries.get(query_id)

    def get_or_raise(self, query_id: str) -> DataFrameQuery:

        query = self.get(query_id)
        if query is None:
            raise KeyError(f"Query '{query_id}' not found in {self.benchmark} registry")
        return query

    def get_all_queries(self) -> list[DataFrameQuery]:

        self._ensure_loaded()
        return sorted(self._queries.values(), key=lambda q: q.query_id)

    def get_query_ids(self) -> list[str]:

        self._ensure_loaded()
        return sorted(self._queries.keys())

    def get_queries_by_category(self, category: QueryCategory) -> list[DataFrameQuery]:

        return [q for q in self.get_all_queries() if q.in_category(category)]

    def get_queries_for_platform(self, platform: str) -> list[DataFrameQuery]:

        return [q for q in self.get_all_queries() if q.supports_platform(platform)]

    def get_queries_for_family(self, family: str) -> list[DataFrameQuery]:

        if family.lower() == "pandas":
            return [q for q in self.get_all_queries() if q.has_pandas_impl()]
        elif family.lower() == "expression":
            return [q for q in self.get_all_queries() if q.has_expression_impl()]
        else:
            raise ValueError(f"Unknown family: {family}. Must be 'pandas' or 'expression'")

    def list_queries(
        self,
        family: str | None = None,
        category: QueryCategory | None = None,
    ) -> list[DataFrameQuery]:

        queries = self.get_all_queries() if family is None else self.get_queries_for_family(family)
        if category is not None:
            queries = [query for query in queries if query.in_category(category)]
        return queries

    def __len__(self) -> int:

        self._ensure_loaded()
        return len(self._queries)

    def __contains__(self, query_id: str) -> bool:

        self._ensure_loaded()
        return query_id in self._queries

    def __iter__(self):

        self._ensure_loaded()
        return iter(sorted(self._queries.keys()))

    def load_info(self) -> QueryRegistryLoadInfo:

        with self._load_lock:
            return QueryRegistryLoadInfo(
                hits=self._load_hits,
                misses=self._load_misses,
                maxsize=1,
                currsize=1 if self._loaded else 0,
            )


class QueryRegistryLoadInfo(NamedTuple):
    hits: int
    misses: int
    maxsize: int
    currsize: int
