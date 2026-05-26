"""DataFrame query definitions for dual-family benchmark support.

This module provides the DataFrameQuery dataclass that represents a single
benchmark query with implementations for both DataFrame families.

Each query can have:
- A Pandas-family implementation (for Pandas, Modin, cuDF, Vaex, Dask)
- An Expression-family implementation (for Polars, PySpark, DataFusion)
- An optional SQL equivalent for validation

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import TYPE_CHECKING, Any, Callable, Iterable, NamedTuple

if TYPE_CHECKING:
    from benchbox.core.dataframe.context import DataFrameContext


class QueryCategory(Enum):
    """Categories for DataFrame benchmark queries.

    Queries are categorized to enable selective execution and
    performance analysis by workload type.
    """

    # Basic operations
    SCAN = "scan"  # Full table scan
    PROJECTION = "projection"  # Column selection
    FILTER = "filter"  # Row filtering
    SORT = "sort"  # Sorting operations

    # Aggregation
    AGGREGATE = "aggregate"  # Basic aggregation (sum, count, etc.)
    GROUP_BY = "group_by"  # Grouped aggregation

    # Joins
    JOIN = "join"  # Two-table joins
    MULTI_JOIN = "multi_join"  # Multi-table joins

    # Complex operations
    SUBQUERY = "subquery"  # Nested operations
    WINDOW = "window"  # Window functions
    ANALYTICAL = "analytical"  # Complex analytical queries

    # Benchmark-specific
    TPCH = "tpch"  # TPC-H derived queries
    TPCDS = "tpcds"  # TPC-DS derived queries

    def __str__(self) -> str:
        """Return the string representation of the category."""
        return self.value


@dataclass
class DataFrameQuery:
    """A benchmark query with dual-family DataFrame implementations.

    This dataclass represents a single benchmark query that can be executed
    on any supported DataFrame platform. Each query has:

    - query_id: Unique identifier (e.g., "Q1", "tpch_01")
    - query_name: Human-readable name
    - description: Detailed description of what the query tests
    - pandas_impl: Implementation for Pandas-family platforms
    - expression_impl: Implementation for Expression-family platforms
    - sql_equivalent: Optional SQL for validation comparison

    The dual-implementation approach enables 95%+ code reuse while
    supporting the syntactic differences between families.

    Example:
        ```python
        def pandas_q1(ctx: DataFrameContext) -> Any:
            orders = ctx.get_table('orders')
            return orders.groupby('status').agg({'total': 'sum'})

        def expression_q1(ctx: DataFrameContext) -> Any:
            orders = ctx.get_table('orders')
            return orders.group_by('status').agg(col('total').sum())

        q1 = DataFrameQuery(
            query_id='Q1',
            query_name='Orders by Status',
            description='Aggregate order totals by status',
            categories=[QueryCategory.GROUP_BY, QueryCategory.AGGREGATE],
            pandas_impl=pandas_q1,
            expression_impl=expression_q1,
            sql_equivalent='SELECT status, SUM(total) FROM orders GROUP BY status',
        )
        ```

    Attributes:
        query_id: Unique identifier for the query
        query_name: Human-readable name
        description: Detailed description
        categories: List of query categories for classification
        pandas_impl: Callable implementing the query for Pandas family
        expression_impl: Callable implementing the query for Expression family
        sql_equivalent: Optional SQL query for validation
        expected_row_count: Optional expected row count for validation
        scale_factor_dependent: Whether row count depends on scale factor
        timeout_seconds: Optional query timeout
        skip_platforms: Platforms to skip (e.g., due to unsupported features)
    """

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
        """Validate the query configuration after initialization."""
        self._validate()

    def _validate(self) -> None:
        """Validate that the query is properly configured.

        Raises:
            ValueError: If query_id is empty or no implementations provided
        """
        if not self.query_id:
            raise ValueError("query_id cannot be empty")

        if not self.query_name:
            raise ValueError("query_name cannot be empty")

        if self.pandas_impl is None and self.expression_impl is None:
            raise ValueError(
                f"Query '{self.query_id}' must have at least one implementation (pandas_impl or expression_impl)"
            )

    def has_pandas_impl(self) -> bool:
        """Check if this query has a Pandas family implementation."""
        return self.pandas_impl is not None

    def has_expression_impl(self) -> bool:
        """Check if this query has an Expression family implementation."""
        return self.expression_impl is not None

    def has_sql_equivalent(self) -> bool:
        """Check if this query has a SQL equivalent for validation."""
        return self.sql_equivalent is not None

    def supports_platform(self, platform: str) -> bool:
        """Check if this query supports a specific platform.

        Args:
            platform: Platform name (e.g., 'pandas', 'polars', 'pyspark')

        Returns:
            True if the query supports the platform
        """
        if platform.lower() in [p.lower() for p in self.skip_platforms]:
            return False

        # Check if platform's family has an implementation
        pandas_family = {"pandas", "modin", "cudf", "vaex", "dask"}
        expression_family = {"polars", "pyspark", "datafusion", "spark"}

        platform_lower = platform.lower()
        if platform_lower in pandas_family:
            return self.has_pandas_impl()
        elif platform_lower in expression_family:
            return self.has_expression_impl()

        return False

    def get_impl_for_family(self, family: str) -> Callable[[DataFrameContext], Any] | None:
        """Get the implementation for a specific family.

        Args:
            family: Either 'pandas' or 'expression'

        Returns:
            The implementation callable, or None if not available

        Raises:
            ValueError: If family is not recognized
        """
        family_lower = family.lower()
        if family_lower == "pandas":
            return self.pandas_impl
        elif family_lower == "expression":
            return self.expression_impl
        else:
            raise ValueError(f"Unknown family: {family}. Must be 'pandas' or 'expression'")

    def execute(self, ctx: DataFrameContext, family: str) -> Any:
        """Execute the query using the specified family implementation.

        Args:
            ctx: DataFrameContext providing table access
            family: Either 'pandas' or 'expression'

        Returns:
            Query result (DataFrame or collected data)

        Raises:
            ValueError: If family is not recognized or not supported
        """
        impl = self.get_impl_for_family(family)
        if impl is None:
            raise ValueError(f"Query '{self.query_id}' has no {family} implementation")

        return impl(ctx)

    def in_category(self, category: QueryCategory) -> bool:
        """Check if this query belongs to a category.

        Args:
            category: The category to check

        Returns:
            True if the query is in the category
        """
        return category in self.categories

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Note: Callable implementations are not serialized.

        Returns:
            Dictionary representation of the query metadata
        """
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
    """Registry for managing DataFrame benchmark queries.

    The QueryRegistry provides centralized management of benchmark queries,
    supporting query lookup, filtering by category, and batch operations.

    Example:
        ```python
        registry = QueryRegistry(benchmark='TPC-H')
        registry.register(q1)
        registry.register(q2)

        # Get all queries
        all_queries = registry.get_all_queries()

        # Filter by category
        join_queries = registry.get_queries_by_category(QueryCategory.JOIN)

        # Filter by platform support
        polars_queries = registry.get_queries_for_platform('polars')
        ```
    """

    def __init__(self, benchmark: str, loader: Callable[[], Iterable[DataFrameQuery]] | None = None) -> None:
        """Initialize a new QueryRegistry.

        Args:
            benchmark: Name of the benchmark (e.g., 'TPC-H', 'TPC-DS')
        """
        self.benchmark = benchmark
        self._queries: dict[str, DataFrameQuery] = {}
        self._loader = loader
        self._load_lock = Lock()
        self._loaded = False
        self._load_hits = 0
        self._load_misses = 0

    def set_loader(self, loader: Callable[[], Iterable[DataFrameQuery]]) -> None:
        """Set the lazy loader before the registry has been populated."""
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
        """Register a query in the registry.

        Args:
            query: The DataFrameQuery to register

        Raises:
            ValueError: If a query with the same ID already exists
        """
        self._ensure_loaded()
        self._register_query(query)

    def register_many(self, queries: list[DataFrameQuery]) -> None:
        """Register multiple queries at once.

        Args:
            queries: List of queries to register
        """
        self._ensure_loaded()
        for query in queries:
            self._register_query(query)

    def get(self, query_id: str) -> DataFrameQuery | None:
        """Get a query by ID.

        Args:
            query_id: The query ID to look up

        Returns:
            The query, or None if not found
        """
        self._ensure_loaded()
        return self._queries.get(query_id)

    def get_or_raise(self, query_id: str) -> DataFrameQuery:
        """Get a query by ID, raising if not found.

        Args:
            query_id: The query ID to look up

        Returns:
            The query

        Raises:
            KeyError: If the query is not found
        """
        query = self.get(query_id)
        if query is None:
            raise KeyError(f"Query '{query_id}' not found in {self.benchmark} registry")
        return query

    def get_all_queries(self) -> list[DataFrameQuery]:
        """Get all registered queries.

        Returns:
            List of all queries, sorted by query_id
        """
        self._ensure_loaded()
        return sorted(self._queries.values(), key=lambda q: q.query_id)

    def get_query_ids(self) -> list[str]:
        """Get all registered query IDs.

        Returns:
            Sorted list of query IDs
        """
        self._ensure_loaded()
        return sorted(self._queries.keys())

    def get_queries_by_category(self, category: QueryCategory) -> list[DataFrameQuery]:
        """Get all queries in a specific category.

        Args:
            category: The category to filter by

        Returns:
            List of queries in the category
        """
        return [q for q in self.get_all_queries() if q.in_category(category)]

    def get_queries_for_platform(self, platform: str) -> list[DataFrameQuery]:
        """Get all queries that support a specific platform.

        Args:
            platform: Platform name (e.g., 'pandas', 'polars')

        Returns:
            List of queries supporting the platform
        """
        return [q for q in self.get_all_queries() if q.supports_platform(platform)]

    def get_queries_for_family(self, family: str) -> list[DataFrameQuery]:
        """Get all queries that have an implementation for a family.

        Args:
            family: Either 'pandas' or 'expression'

        Returns:
            List of queries with implementations for the family
        """
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
        """List queries with optional family and category filters.

        Args:
            family: Optional family filter ("pandas" or "expression")
            category: Optional category filter

        Returns:
            Filtered list of queries
        """
        queries = self.get_all_queries() if family is None else self.get_queries_for_family(family)
        if category is not None:
            queries = [query for query in queries if query.in_category(category)]
        return queries

    def __len__(self) -> int:
        """Return the number of registered queries."""
        self._ensure_loaded()
        return len(self._queries)

    def __contains__(self, query_id: str) -> bool:
        """Check if a query ID is registered."""
        self._ensure_loaded()
        return query_id in self._queries

    def __iter__(self):
        """Iterate over query IDs."""
        self._ensure_loaded()
        return iter(sorted(self._queries.keys()))

    def load_info(self) -> QueryRegistryLoadInfo:
        """Return lazy-load statistics."""
        with self._load_lock:
            return QueryRegistryLoadInfo(
                hits=self._load_hits,
                misses=self._load_misses,
                maxsize=1,
                currsize=1 if self._loaded else 0,
            )


class QueryRegistryLoadInfo(NamedTuple):
    """Lazy query-registry load statistics for import-path tests."""

    hits: int
    misses: int
    maxsize: int
    currsize: int
