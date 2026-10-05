"""Metadata Primitives benchmark implementation.

Tests database metadata introspection operations using INFORMATION_SCHEMA views
and platform-specific catalog commands (SHOW, DESCRIBE, PRAGMA).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.benchmark_mixins import QueryCategoryFacadeMixin, QueryFacadeMixin
from benchbox.core.metadata_primitives.benchmark import (
    ComplexityBenchmarkResult,
    MetadataBenchmarkResult,
    MetadataPrimitivesBenchmark,
    MetadataQueryResult,
)
from benchbox.core.metadata_primitives.complexity import (
    GeneratedMetadata,
    MetadataComplexityConfig,
)


class MetadataPrimitives(QueryCategoryFacadeMixin, QueryFacadeMixin, BaseBenchmark):
    """Metadata Primitives benchmark implementation.

    Tests metadata introspection operations across database platforms:
    - Schema discovery (list databases, schemas, tables, views)
    - Column introspection (column metadata, types, constraints)
    - Table statistics (row counts, sizes, storage info)
    - Query introspection (execution plans)

    Supports complexity stress testing with:
    - Wide tables (100-1000+ columns)
    - Nested view hierarchies
    - Complex data types (ARRAY, STRUCT, MAP)
    - Large catalogs (100-500+ tables)
    """

    SKIP_DATA_LOADING = True

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize Metadata Primitives benchmark instance.

        Args:
            scale_factor: Not used for metadata primitives (API compatibility)
            output_dir: Not used for metadata primitives (API compatibility)
            **kwargs: Additional options (quiet, etc.)
        """
        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        self._impl = MetadataPrimitivesBenchmark(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

    def generate_data(self, tables: Optional[list[str]] = None) -> dict[str, str]:
        """No data generation needed for Metadata Primitives.

        Returns:
            Empty dictionary (no data files to generate)
        """
        return self._impl.generate_data(tables)

    def get_schema(self) -> dict[str, dict[str, Any]]:
        """Get the Metadata Primitives benchmark schema (TPC-H).

        Returns:
            Dictionary mapping table names to their schema definitions
        """
        return self._impl.get_schema()

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config: Any = None) -> str:
        """Get SQL to create all Metadata Primitives benchmark tables.

        Creates TPC-H schema for metadata introspection testing.

        Args:
            dialect: SQL dialect to use
            tuning_config: Tuning configuration for constraint settings

        Returns:
            SQL script for creating all tables
        """
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)

    def get_table_names(self) -> list[str]:
        """Get all table names in the Metadata Primitives schema.

        Returns:
            List of table names (TPC-H tables)
        """
        return self._impl.get_table_names()

    def execute_query(
        self,
        query_id: str,
        connection: Any,
        dialect: Optional[str] = None,
    ) -> MetadataQueryResult:
        """Execute a single metadata query and return timing results.

        Args:
            query_id: Query identifier
            connection: Database connection to execute against
            dialect: Target dialect for query variants

        Returns:
            MetadataQueryResult with execution timing and status
        """
        return self._impl.execute_query(query_id, connection, dialect=dialect)

    def run_benchmark(
        self,
        connection: Any,
        dialect: Optional[str] = None,
        categories: Optional[list[str]] = None,
        query_ids: Optional[list[str]] = None,
        iterations: int = 1,
    ) -> MetadataBenchmarkResult:
        """Run the Metadata Primitives benchmark.

        Args:
            connection: Database connection to execute against
            dialect: Target dialect for query variants
            categories: Optional list of categories to run (default: all)
            query_ids: Optional specific query IDs to run (overrides categories)
            iterations: Number of times to run each query (default: 1)

        Returns:
            MetadataBenchmarkResult with all query timings and summary
        """
        return self._impl.run_benchmark(
            connection, dialect=dialect, categories=categories, query_ids=query_ids, iterations=iterations
        )

    # Complexity testing methods
    def setup_complexity(
        self,
        connection: Any,
        dialect: str,
        config: Union[MetadataComplexityConfig, str],
    ) -> GeneratedMetadata:
        """Set up metadata structures for complexity testing.

        Args:
            connection: Database connection
            dialect: Target SQL dialect
            config: Complexity configuration or preset name

        Returns:
            GeneratedMetadata tracking all created objects
        """
        return self._impl.setup_complexity(connection, dialect, config)

    def teardown_complexity(
        self,
        connection: Any,
        dialect: str,
        generated: GeneratedMetadata,
    ) -> None:
        """Tear down metadata structures created for complexity testing."""
        return self._impl.teardown_complexity(connection, dialect, generated)

    def run_complexity_benchmark(
        self,
        connection: Any,
        dialect: str,
        config: Union[MetadataComplexityConfig, str],
        iterations: int = 1,
        categories: Optional[list[str]] = None,
    ) -> ComplexityBenchmarkResult:
        """Run a full complexity benchmark with setup and teardown.

        Args:
            connection: Database connection
            dialect: Target SQL dialect
            config: Complexity configuration or preset name
            iterations: Number of times to run each query
            categories: Optional list of categories to run

        Returns:
            ComplexityBenchmarkResult with timing and results
        """
        return self._impl.run_complexity_benchmark(
            connection, dialect, config, iterations=iterations, categories=categories
        )

    def get_complexity_categories(self) -> list[str]:
        """Get list of complexity-specific query categories.

        Returns:
            List of complexity category names
        """
        return self._impl.get_complexity_categories()

    def get_benchmark_info(self) -> dict[str, Any]:
        """Get information about the benchmark.

        Returns:
            Dictionary containing benchmark metadata
        """
        return {
            "name": "Metadata Primitives Benchmark",
            "version": "1.0",
            "description": "Tests database catalog introspection performance",
            "query_count": len(self._impl.get_queries()),
            "categories": self._impl.get_query_categories(),
            "complexity_categories": self._impl.get_complexity_categories(),
        }
