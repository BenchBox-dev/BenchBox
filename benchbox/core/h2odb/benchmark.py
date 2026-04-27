"""H2O DB benchmark implementation.

Provides H2O DB benchmark implementation that tests analytical database performance using taxi trip data.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.benchmark_mixins import DataGenerationMixin
from benchbox.core.h2odb.generator import H2ODataGenerator
from benchbox.core.h2odb.queries import H2OQueryManager
from benchbox.core.h2odb.schema import TABLES, get_all_create_table_sql
from benchbox.core.query_catalog_base import TranslatableQueryMixin
from benchbox.core.query_utils import get_queries_with_translation
from benchbox.core.utils.tuning import extract_constraint_flags
from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration


class H2OBenchmark(TranslatableQueryMixin, DataGenerationMixin, BaseBenchmark):
    """H2O DB benchmark implementation.

    Tests analytical database performance using synthetic taxi trip data
    similar to NYC Taxi & Limousine Commission Trip Record Data.

    The benchmark consists of:
    - A single large table with trip records
    - 10 analytical queries testing various aspects of performance
    - Focus on aggregations, grouping, and analytical functions

    Attributes:
        scale_factor: Scale factor for the benchmark (1.0 = ~1M trips)
        output_dir: Directory to output generated data and results
        query_manager: H2O DB query manager
        data_generator: H2O DB data generator
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **config: Any,
    ):
        """Initialize H2O DB benchmark.

        Args:
            scale_factor: Scale factor for data generation (1.0 = ~1M trips)
            output_dir: Directory for generated data files
            **config: Additional configuration options
        """
        # Extract quiet from config to prevent duplicate kwarg error
        config = dict(config)
        quiet = config.pop("quiet", False)

        super().__init__(scale_factor, output_dir=output_dir, quiet=quiet, **config)

        self._name = "H2O Database Benchmark"
        self._version = "1.0"
        self._description = "H2O DB Benchmark - Analytical database performance benchmark using taxi trip data"

        # Initialize components
        self.query_manager: H2OQueryManager = H2OQueryManager()
        self.data_generator = H2ODataGenerator(
            scale_factor,
            self.output_dir,
            **config,
        )

        # Data files mapping
        self.tables: dict[str, Path] = {}

    def _get_table_schema(self) -> dict[str, dict]:
        """Provide schema mapping for shared data generation/loading mixin."""
        return TABLES

    def _get_data_loading_batch_size(self) -> int | None:
        """Load larger H2O DB tables in chunks for better memory behavior."""
        return 10000

    def get_query(self, query_id: Union[int, str], *, params: Optional[dict[str, Any]] = None) -> str:
        """Get the SQL text for a specific H2O DB query.

        Args:
            query_id: Query identifier (e.g., "Q1", "Q2", etc.)
            params: Optional parameter values (not supported for H2O DB)

        Returns:
            The SQL text of the query

        Raises:
            ValueError: If the query_id is not valid or params are provided
        """
        if params is not None:
            raise ValueError("H2O DB queries are static and don't accept parameters")
        return self.query_manager.get_query(str(query_id))

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        """Get all available H2O DB queries.

        Args:
            dialect: Target SQL dialect for query translation. If None, returns original queries.

        Returns:
            A dictionary mapping query identifiers to their SQL text
        """
        import benchbox.sql_compat.rules.query_source.h2odb_variants  # noqa: F401
        from benchbox.sql_compat.actions import CompatAction
        from benchbox.sql_compat.context import CompatibilityContext, Phase
        from benchbox.sql_compat.registry import REGISTRY
        from benchbox.sql_compat.rules.query_source.h2odb_variants import (
            CLICKHOUSE_Q9_SQL,
            STARROCKS_Q9_SQL,
        )

        queries = get_queries_with_translation(self.query_manager, dialect, self.translate_query_text)
        if not dialect:
            return queries

        d = dialect.lower()
        # Q9 variant platforms: map platform substring → legacy SQL
        _q9_variants: dict[str, str] = {
            "clickhouse": CLICKHOUSE_Q9_SQL,
            "starrocks": STARROCKS_Q9_SQL,
        }
        for platform, legacy_sql in _q9_variants.items():
            if platform not in d:
                continue
            ctx = CompatibilityContext(
                platform=platform,
                platform_version=None,
                benchmark="h2odb",
                query_id="Q9",
                phase=Phase.QUERY_SOURCE,
                mode="sql",
                dialect=dialect,
            )
            registry_decision = REGISTRY.resolve(ctx)
            if registry_decision is not None:
                if registry_decision.action is CompatAction.SELECT_VARIANT:
                    queries["Q9"] = registry_decision.payload.variant_sql  # type: ignore[union-attr]
            else:
                queries["Q9"] = legacy_sql  # no rule: use legacy SQL

        return queries

    # translate_query_text() is inherited from TranslatableQueryMixin

    def get_all_queries(self) -> dict[str, str]:
        """Get all available H2O DB queries.

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
        """Execute an H2O DB query on the given database connection.

        Args:
            query_id: Query identifier (e.g., "Q1", "Q2", etc.)
            connection: Database connection to use for execution
            params: Optional parameters (unused for H2O DB)

        Returns:
            Query results from the database

        Raises:
            ValueError: If the query_id is not valid
        """
        sql = self.get_query(query_id)

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
        """Get the H2O DB schema definitions.

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
        """Get CREATE TABLE SQL for all H2O DB tables.

        Args:
            dialect: SQL dialect to use
            tuning_config: Unified tuning configuration for constraint settings

        Returns:
            Complete SQL schema creation script
        """
        enable_primary_keys, enable_foreign_keys = extract_constraint_flags(tuning_config)
        return get_all_create_table_sql(dialect, enable_primary_keys, enable_foreign_keys)

    def run_benchmark(
        self, connection: Any, queries: Optional[list[str]] = None, iterations: int = 1
    ) -> dict[str, Any]:
        """Run the complete H2O DB benchmark.

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
            "benchmark": "H2O Database Benchmark",
            "scale_factor": self.scale_factor,
            "iterations": iterations,
            "queries": {},
        }

        for query_id in queries:
            query_results = {
                "query_id": query_id,
                "iterations": [],
                "avg_time": 0,
                "min_time": float("inf"),
                "max_time": 0,
                "sql_text": self.get_query(query_id),  # Add actual SQL text
            }

            for i in range(iterations):
                start_time = mono_time()
                try:
                    result = self.execute_query(query_id, connection)
                    execution_time = elapsed_seconds(start_time)

                    query_results["iterations"].append(
                        {
                            "iteration": i + 1,
                            "time": execution_time,
                            "rows": len(result) if result else 0,
                            "success": True,
                        }
                    )

                    query_results["min_time"] = min(query_results["min_time"], execution_time)
                    query_results["max_time"] = max(query_results["max_time"], execution_time)

                except Exception as e:
                    query_results["iterations"].append(
                        {
                            "iteration": i + 1,
                            "time": 0,
                            "error": str(e),
                            "success": False,
                        }
                    )

            # Calculate average time for successful iterations
            iterations_list: list[dict[str, Any]] = query_results["iterations"]  # type: ignore[assignment]
            successful_iterations = [iter_result for iter_result in iterations_list if iter_result["success"]]
            if successful_iterations:
                successful_times = [iter_result["time"] for iter_result in successful_iterations]
                successful_rows = [iter_result.get("rows", 0) for iter_result in successful_iterations]
                query_results["avg_time"] = sum(successful_times) / len(successful_times)
                query_results["rows_returned"] = (
                    int(sum(successful_rows) / len(successful_rows)) if successful_rows else 0
                )

            results["queries"][query_id] = query_results

        return results
