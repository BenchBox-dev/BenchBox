"""Read Primitives benchmark implementation.

Copyright 2026 Joe Harris / BenchBox Project

This benchmark combines queries from multiple sources:

1. Apache Impala targeted-perf workload
   (https://github.com/apache/impala/tree/master/testdata/workloads/targeted-perf)
   Apache License 2.0, Copyright Apache Software Foundation

2. Optimizer sniff test concepts by Justin Jaffray
   (https://buttondown.com/jaffray/archive/a-sniff-test-for-some-query-optimizers/)

Data generation uses the TPC-H schema (TPC Benchmark H, Copyright Transaction
Processing Performance Council).

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.benchmark_mixins import QueryCategoryFacadeMixin, QueryFacadeMixin
from benchbox.core.read_primitives.benchmark import ReadPrimitivesBenchmark


class ReadPrimitives(QueryCategoryFacadeMixin, QueryFacadeMixin, BaseBenchmark):
    """Read Primitives benchmark implementation.

    Provides Read Primitives benchmark implementation, including data generation and access to 80+ primitive read operation queries that test fundamental database capabilities using the TPC-H schema.

    The benchmark covers:
    - Aggregation, joins, filters, window functions
    - OLAP operations, statistical functions
    - JSON operations, full-text search
    - Time series analysis, array operations
    - Graph operations, temporal queries
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize Read Primitives benchmark instance.

        Args:
            scale_factor: Scale factor for the benchmark (1.0 = ~6M lineitem rows)
            output_dir: Directory to output generated data files
            **kwargs: Additional implementation-specific options
        """
        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        # Initialize the actual implementation
        verbose = kwargs.pop("verbose", False)
        self._impl = ReadPrimitivesBenchmark(
            scale_factor=scale_factor, output_dir=output_dir, verbose=verbose, **kwargs
        )

    def generate_data(self, tables: Optional[list[str]] = None) -> dict[str, str | list[str]]:
        """Generate Read Primitives benchmark data.

        Args:
            tables: Optional list of table names to generate. If None, generates all.

        Returns:
            A dictionary mapping table names to a file path or an ordered list of shard paths.
        """
        # Call the implementation to generate data
        self._impl.generate_data(tables)
        # Return the tables dictionary (mapping table names to file paths)
        return self._impl.tables

    def get_schema(self) -> dict[str, dict]:
        """Get the Read Primitives benchmark schema (TPC-H).

        Returns:
            A dictionary mapping table names to their schema definitions
        """
        return self._impl.get_schema()

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config=None) -> str:
        """Get SQL to create all Read Primitives benchmark tables.

        Args:
            dialect: SQL dialect to use
            tuning_config: Unified tuning configuration for constraint settings

        Returns:
            SQL script for creating all tables
        """
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)

    def load_data_to_database(self, connection: Any, tables: Optional[list[str]] = None) -> None:
        """Load generated data into a database.

        Args:
            connection: Database connection
            tables: Optional list of tables to load. If None, loads all.

        Raises:
            ValueError: If data hasn't been generated yet
        """
        return self._impl.load_data_to_database(connection, tables)

    def execute_query(self, query_id: str, connection: Any, params: Optional[dict[str, Any]] = None) -> Any:
        """Execute a Read Primitives query on the given database connection.

        Args:
            query_id: Query identifier (e.g., 'aggregation_simple')
            connection: Database connection to use for execution
            params: Optional parameters to use in the query

        Returns:
            Query results from the database

        Raises:
            ValueError: If the query_id is not valid
        """
        return self._impl.execute_query(query_id, connection, params)

    def run_benchmark(
        self,
        connection: Any,
        queries: Optional[list[str]] = None,
        iterations: int = 1,
        categories: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Run the complete Read Primitives benchmark.

        Args:
            connection: Database connection to use
            queries: Optional list of query IDs to run. If None, runs all.
            iterations: Number of times to run each query
            categories: Optional list of categories to run. If specified, overrides queries.

        Returns:
            Dictionary containing benchmark results
        """
        return self._impl.run_benchmark(connection, queries, iterations, categories)

    def run_category_benchmark(self, connection: Any, category: str, iterations: int = 1) -> dict[str, Any]:
        """Run benchmark for a specific query category.

        Args:
            connection: Database connection to use
            category: Category name to run (e.g., 'aggregation', 'window', 'join')
            iterations: Number of times to run each query

        Returns:
            Dictionary containing benchmark results for the category
        """
        return self._impl.run_category_benchmark(connection, category, iterations)

    def get_benchmark_info(self) -> dict[str, Any]:
        """Get information about the benchmark.

        Returns:
            Dictionary containing benchmark metadata
        """
        return self._impl.get_benchmark_info()
