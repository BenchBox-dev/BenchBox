"""Star Schema Benchmark (SSB) implementation.

Provides Star Schema Benchmark implementation,
a simplified TPC-H version for testing OLAP systems.

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.benchmark_mixins import DataGenerationMixin
from benchbox.core.query_catalog_base import TranslatableQueryMixin
from benchbox.core.query_utils import get_queries_with_translation
from benchbox.core.simple_benchmark_mixin import SimpleBenchmarkMixin
from benchbox.core.ssb.generator import SSBDataGenerator
from benchbox.core.ssb.queries import SSBQueryManager
from benchbox.core.ssb.schema import TABLES, get_all_create_table_sql
from benchbox.core.utils.tuning import extract_constraint_flags
from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration


class SSBBenchmark(TranslatableQueryMixin, SimpleBenchmarkMixin, DataGenerationMixin, BaseBenchmark):
    """Star Schema Benchmark implementation.

    This class provides a complete implementation of the Star Schema Benchmark,
    including data generation, query execution, and schema management.

    The SSB is based on TPC-H but uses a denormalized star schema with:
    - 1 fact table (LINEORDER)
    - 4 dimension tables (DATE, CUSTOMER, SUPPLIER, PART)
    - 13 standard queries in 4 flights

    Attributes:
        scale_factor: The scale factor for the benchmark (1.0 = ~6M lineorder rows)
        output_dir: Directory to output generated data and results
        query_manager: The SSB query manager
        data_generator: The SSB data generator
    """

    _benchmark_label = "Star Schema Benchmark"
    _table_load_order = ["date", "customer", "supplier", "part", "lineorder"]

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **config: Any,
    ):
        """Initialize the SSB benchmark.

        Args:
            scale_factor: Scale factor for data generation (1.0 = standard size)
            output_dir: Directory for generated data files
            **config: Additional configuration options
        """
        # Extract quiet from config to prevent duplicate kwarg error
        config = dict(config)
        quiet = config.pop("quiet", False)

        super().__init__(scale_factor, output_dir=output_dir, quiet=quiet, **config)

        self._name = "Star Schema Benchmark"
        self._version = "1.0"
        self._description = "Star Schema Benchmark (SSB) - A simplified OLAP benchmark based on TPC-H"

        # Initialize components
        self.query_manager: SSBQueryManager = SSBQueryManager()
        # Pass through compression configuration to data generator
        self.data_generator = SSBDataGenerator(
            scale_factor=scale_factor,
            output_dir=self.output_dir,
            verbose=self.verbose_level if hasattr(self, "verbose_level") else 0,
            quiet=quiet,
            compress_data=config.get("compress_data", False),
            compression_type=config.get("compression_type", "zstd"),
            compression_level=config.get("compression_level"),
        )

        # Data files mapping
        self.tables = {}

    def _get_table_schema(self) -> dict[str, dict]:
        """Provide schema mapping for shared data generation/loading mixin."""
        return TABLES

    def get_query(self, query_id: Union[int, str], *, params: Optional[dict[str, Any]] = None) -> str:
        """Get the SQL text for a specific SSB query.

        Args:
            query_id: Query identifier (e.g., "Q1.1", "Q2.3", etc.)
            params: Optional parameter values to use in the query

        Returns:
            The SQL text of the query with parameters substituted

        Raises:
            ValueError: If the query_id is not valid
        """
        return self.query_manager.get_query(str(query_id), params)

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        """Get all available SSB queries.

        Args:
            dialect: Target SQL dialect for query translation. If None, returns original queries.

        Returns:
            A dictionary mapping query identifiers to their SQL text
        """
        return get_queries_with_translation(self.query_manager, dialect, self.translate_query_text)

    # translate_query_text() is inherited from TranslatableQueryMixin

    def get_all_queries(self) -> dict[str, str]:
        """Get all available SSB queries.

        Returns:
            A dictionary mapping query identifiers to their SQL text
        """
        return self.query_manager.get_all_queries()

    def execute_query(
        self,
        query_id: Union[int, str],
        connection: Any,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Execute an SSB query on the given database connection.

        Args:
            query_id: Query identifier (e.g., "Q1.1", "Q2.3", etc.)
            connection: Database connection to use for execution
            params: Optional parameters to use in the query

        Returns:
            Query results from the database

        Raises:
            ValueError: If the query_id is not valid
        """
        sql = self.get_query(query_id, params=params)

        # Execute query using connection
        if hasattr(connection, "execute"):
            # Direct database connection
            cursor = connection.execute(sql)
            return cursor.fetchall()
        elif hasattr(connection, "cursor"):
            # Connection with cursor method
            cursor = connection.cursor()
            cursor.execute(sql)
            return cursor.fetchall()
        else:
            raise ValueError("Unsupported connection type")

    def get_schema(self, dialect: str = "standard") -> dict[str, dict]:
        """Get the SSB schema definitions.

        Args:
            dialect: SQL dialect to use for data types

        Returns:
            Dictionary mapping table names to their schema definitions
        """
        return TABLES

    def get_create_tables_sql(
        self,
        dialect: str = "standard",
        tuning_config: Optional["UnifiedTuningConfiguration"] = None,
    ) -> str:
        """Get CREATE TABLE SQL for all SSB tables.

        Args:
            dialect: SQL dialect to use
            tuning_config: Unified tuning configuration for constraint settings

        Returns:
            Complete SQL schema creation script
        """
        enable_primary_keys, enable_foreign_keys = extract_constraint_flags(tuning_config)
        return get_all_create_table_sql(
            dialect=dialect,
            enable_primary_keys=enable_primary_keys,
            enable_foreign_keys=enable_foreign_keys,
        )

    def run_benchmark(
        self, connection: Any, queries: Optional[list[str]] = None, iterations: int = 1
    ) -> dict[str, Any]:
        """Run the complete SSB benchmark.

        Args:
            connection: Database connection to use
            queries: Optional list of query IDs to run. If None, runs all.
            iterations: Number of times to run each query

        Returns:
            Dictionary containing benchmark results
        """
        if queries is None:
            queries = list(self.query_manager.get_all_queries().keys())

        results = {
            "benchmark": "Star Schema Benchmark",
            "scale_factor": self.scale_factor,
            "iterations": iterations,
            "query_results": [],
        }

        for query_id in queries:
            query_iterations = []
            min_time = float("inf")
            max_time = 0
            total_successful_time = 0
            successful_count = 0
            total_rows = 0
            last_error = None

            for i in range(iterations):
                start_time = mono_time()
                try:
                    result = self.execute_query(query_id, connection)
                    execution_time = elapsed_seconds(start_time)
                    rows_returned = len(result) if result else 0

                    query_iterations.append(
                        {
                            "iteration": i + 1,
                            "time": execution_time,
                            "rows": rows_returned,
                            "success": True,
                        }
                    )

                    # Configure statistics
                    min_time = min(min_time, execution_time)
                    max_time = max(max_time, execution_time)
                    total_successful_time += execution_time
                    successful_count += 1
                    total_rows += rows_returned

                except Exception as e:
                    query_iterations.append(
                        {
                            "iteration": i + 1,
                            "time": 0,
                            "error": str(e),
                            "success": False,
                        }
                    )
                    last_error = str(e)

            # Create query result in expected format
            avg_time = total_successful_time / successful_count if successful_count > 0 else 0
            avg_rows = total_rows // successful_count if successful_count > 0 else 0

            query_result = {
                "query_id": query_id,
                "execution_time_seconds": avg_time,
                "success": successful_count > 0,
                "rows_returned": avg_rows,
                "iterations": query_iterations,
                "min_time": min_time if min_time != float("inf") else 0,
                "max_time": max_time,
                "sql_text": self.get_query(query_id),  # Add actual SQL text
            }

            if last_error:
                query_result["error"] = last_error

            results["query_results"].append(query_result)

        return results

    def get_csv_loading_config(self, table_name: str) -> list[str]:
        """Get CSV loading configuration for SSB tables.

        SSB uses pipe-delimited CSV files without headers.

        Args:
            table_name: Name of the table being loaded

        Returns:
            List of CSV loading configuration parameters
        """
        return [
            "delim='|'",  # SSB uses pipe delimiter
            "header=false",  # No header row
            "nullstr=''",  # Empty strings for NULLs (SSB allows NULLs unlike ClickBench)
            "ignore_errors=false",  # Don't ignore errors - we want strict parsing
            "auto_detect=true",  # Auto-detect types
        ]
