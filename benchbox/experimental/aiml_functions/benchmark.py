"""AI/ML SQL Function Performance Testing benchmark implementation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.base import BaseBenchmark

from .data import AIMLDataGenerator
from .functions import AIMLFunctionCategory, AIMLFunctionRegistry
from .queries import AIMLQueryManager

if TYPE_CHECKING:
    from benchbox.core.connection import DatabaseConnection

logger = logging.getLogger(__name__)


@dataclass
class AIMLQueryResult:
    """Result of executing an AI/ML function query."""

    query_id: str
    function_id: str
    platform: str
    success: bool
    execution_time_ms: float
    row_count: int = 0
    error_message: str = ""
    tokens_estimated: int = 0
    cost_estimated: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query_id": self.query_id,
            "function_id": self.function_id,
            "platform": self.platform,
            "success": self.success,
            "execution_time_ms": self.execution_time_ms,
            "row_count": self.row_count,
            "error_message": self.error_message,
            "tokens_estimated": self.tokens_estimated,
            "cost_estimated": self.cost_estimated,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class AIMLBenchmarkResults:
    """Results from running the AI/ML functions benchmark."""

    platform: str
    started_at: datetime
    completed_at: datetime | None = None
    query_results: list[AIMLQueryResult] = field(default_factory=list)
    total_queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0
    total_execution_time_ms: float = 0.0
    total_cost_estimated: float = 0.0

    def add_result(self, result: AIMLQueryResult) -> None:
        """Add a query result."""
        self.query_results.append(result)
        self.total_queries += 1
        if result.success:
            self.successful_queries += 1
        else:
            self.failed_queries += 1
        self.total_execution_time_ms += result.execution_time_ms
        self.total_cost_estimated += result.cost_estimated

    def complete(self) -> None:
        """Mark the benchmark as complete."""
        self.completed_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "platform": self.platform,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "total_queries": self.total_queries,
            "successful_queries": self.successful_queries,
            "failed_queries": self.failed_queries,
            "success_rate": self.successful_queries / self.total_queries if self.total_queries > 0 else 0,
            "total_execution_time_ms": self.total_execution_time_ms,
            "avg_execution_time_ms": self.total_execution_time_ms / self.total_queries if self.total_queries > 0 else 0,
            "total_cost_estimated": self.total_cost_estimated,
            "query_results": [r.to_dict() for r in self.query_results],
        }


class AIMLFunctionsBenchmark(BaseBenchmark):
    """AI/ML SQL Function Performance Testing benchmark.

    Benchmarks AI/ML SQL functions across cloud data platforms:
    - Snowflake Cortex (sentiment, classification, summarization, completion)
    - BigQuery ML (ML.GENERATE_TEXT, ML.PREDICT, ML.UNDERSTAND_TEXT)
    - Databricks ML (ai_query, ai_classify, ai_summarize)

    Example:
        >>> benchmark = AIMLFunctionsBenchmark()
        >>> queries = benchmark.get_queries_for_platform("snowflake")
        >>> result = benchmark.execute_query(conn, "sentiment_single")
    """

    # Supported platforms for AI/ML functions
    SUPPORTED_PLATFORMS = {"snowflake", "bigquery", "databricks"}

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Path | str | None = None,
        seed: int = 42,
        **kwargs: Any,
    ) -> None:
        """Initialize the AI/ML Functions benchmark.

        Args:
            scale_factor: Scale factor (affects sample data size)
            output_dir: Output directory for generated data
            seed: Random seed for data generation
            **kwargs: Additional configuration
        """
        super().__init__(scale_factor, output_dir, **kwargs)

        self._name = "AI/ML SQL Function Performance Testing"
        self._version = "1.0"
        self._description = (
            "Benchmarks AI/ML SQL functions (sentiment analysis, classification, "
            "summarization, LLM completion) across Snowflake Cortex, BigQuery ML, "
            "and Databricks ML."
        )

        self.seed = seed
        self.function_registry = AIMLFunctionRegistry()
        self.query_manager = AIMLQueryManager()

        # Scale sample data based on scale_factor
        num_samples = int(100 * scale_factor)
        num_long_texts = int(20 * scale_factor)
        self.data_generator = AIMLDataGenerator(
            seed=seed,
            num_samples=max(10, num_samples),
            num_long_texts=max(5, num_long_texts),
        )

    @property
    def name(self) -> str:
        """Get benchmark name."""
        return self._name

    @property
    def version(self) -> str:
        """Get benchmark version."""
        return self._version

    @property
    def description(self) -> str:
        """Get benchmark description."""
        return self._description

    def get_queries(self) -> dict[str, str]:
        """Get all benchmark queries.

        Returns:
            Dictionary mapping query IDs to query strings.
            Note: For AI/ML functions, queries are platform-specific,
            so this returns Snowflake queries as the default.
        """
        return self.get_all_queries(platform="snowflake")

    def get_supported_platforms(self) -> set[str]:
        """Get platforms that support AI/ML SQL functions."""
        return self.SUPPORTED_PLATFORMS.copy()

    def get_functions(self) -> dict[str, Any]:
        """Get all registered AI/ML functions."""
        return {func_id: func.to_dict() for func_id, func in self.function_registry.get_all_functions().items()}

    def get_functions_for_platform(self, platform: str) -> list[dict[str, Any]]:
        """Get AI/ML functions supported on a specific platform."""
        functions = self.function_registry.get_functions_for_platform(platform)
        return [f.to_dict() for f in functions]

    def get_queries_for_platform(self, platform: str) -> list[str]:
        """Get query IDs available for a platform.

        Args:
            platform: Target platform (snowflake, bigquery, databricks)

        Returns:
            List of query IDs
        """
        queries = self.query_manager.get_queries_for_platform(platform)
        return [q.query_id for q in queries]

    def get_query(self, query_id: str, platform: str | None = None, **params: Any) -> str:
        """Get SQL for a specific query.

        Args:
            query_id: Query identifier
            platform: Target platform (required)
            **params: Not used, kept for API compatibility

        Returns:
            SQL query text

        Raises:
            ValueError: If query_id not found or platform not supported
        """
        query = self.query_manager.get_query(query_id)
        if query is None:
            available = ", ".join(self.query_manager.get_query_ids())
            raise ValueError(f"Unknown query ID: {query_id}. Available: {available}")

        if platform is None:
            raise ValueError("Platform must be specified for AI/ML queries")

        sql = query.get_query(platform)
        if sql is None:
            available = list(query.platform_queries.keys())
            raise ValueError(
                f"Query '{query_id}' not available for platform '{platform}'. Available platforms: {available}"
            )

        return sql.strip()

    def get_all_queries(self, platform: str | None = None) -> dict[str, str]:
        """Get all queries, optionally filtered by platform.

        Args:
            platform: Optional platform filter. If None, returns first available
                     SQL for each query.

        Returns:
            Dictionary mapping query IDs to SQL
        """
        if platform is None:
            # Return first available platform's SQL for each query
            result: dict[str, str] = {}
            for q in self.query_manager.get_all_queries().values():
                if q.platform_queries:
                    first_sql = next(iter(q.platform_queries.values()))
                    result[q.query_id] = first_sql
            return result

        queries = self.query_manager.get_queries_for_platform(platform)
        return {q.query_id: q.get_query(platform) or "" for q in queries}

    def generate_data(
        self,
        tables: list[str] | None = None,
        output_format: str = "csv",
    ) -> dict[str, str]:
        """Generate sample data for AI/ML function testing.

        Args:
            tables: Optional list of tables to generate
            output_format: Output format (only csv supported)

        Returns:
            Dictionary mapping table names to file paths
        """
        if output_format != "csv":
            raise ValueError(f"Unsupported output format: {output_format}")

        output_path = Path(self.output_dir)
        files = self.data_generator.generate_csv(output_path)

        if tables is not None:
            files = {k: v for k, v in files.items() if k in tables}

        return {name: str(path) for name, path in files.items()}

    def setup_tables(
        self,
        connection: DatabaseConnection,
        platform: str,
    ) -> dict[str, bool]:
        """Create tables and load sample data.

        Args:
            connection: Database connection
            platform: Target platform

        Returns:
            Dictionary mapping table names to success status
        """
        results: dict[str, bool] = {}
        create_statements = self.data_generator.get_create_table_sql(platform)

        # Create tables
        for table_name, create_sql in create_statements.items():
            try:
                connection.execute(create_sql)
                results[f"create_{table_name}"] = True
            except Exception as e:
                logger.error(f"Failed to create table {table_name}: {e}")
                results[f"create_{table_name}"] = False

        # Insert data
        insert_statements = self.data_generator.get_insert_sql(platform)
        for i, insert_sql in enumerate(insert_statements):
            try:
                connection.execute(insert_sql)
                results[f"insert_{i}"] = True
            except Exception as e:
                logger.error(f"Failed to insert data: {e}")
                results[f"insert_{i}"] = False

        return results

    def execute_query(
        self,
        connection: DatabaseConnection,
        query_id: str,
        platform: str | None = None,
        timeout_seconds: int | None = None,
    ) -> AIMLQueryResult:
        """Execute a single AI/ML function query.

        Args:
            connection: Database connection
            query_id: Query identifier
            platform: Target platform (will detect from connection if not provided)
            timeout_seconds: Query timeout

        Returns:
            Query execution result
        """
        if platform is None:
            platform = connection.platform if hasattr(connection, "platform") else "unknown"

        query = self.query_manager.get_query(query_id)
        if query is None:
            return AIMLQueryResult(
                query_id=query_id,
                function_id="",
                platform=platform,
                success=False,
                execution_time_ms=0,
                error_message=f"Unknown query ID: {query_id}",
            )

        sql = query.get_query(platform)
        if sql is None:
            return AIMLQueryResult(
                query_id=query_id,
                function_id=query.function_id,
                platform=platform,
                success=False,
                execution_time_ms=0,
                error_message=f"Query not available for platform: {platform}",
            )

        # Execute query
        start_time = time.perf_counter()
        try:
            result = connection.execute(sql.strip())
            execution_time_ms = (time.perf_counter() - start_time) * 1000

            # Get row count
            row_count = 0
            if hasattr(result, "fetchall"):
                rows = result.fetchall()
                row_count = len(rows)
            elif hasattr(result, "rowcount"):
                row_count = result.rowcount or 0

            # Estimate tokens and cost
            func = self.function_registry.get_function(query.function_id)
            tokens_estimated = query.batch_size * 100  # Rough estimate
            cost_estimated = 0.0
            if func:
                support = func.get_platform_support(platform)
                if support:
                    cost_estimated = (tokens_estimated / 1000) * support.cost_per_1k_tokens

            return AIMLQueryResult(
                query_id=query_id,
                function_id=query.function_id,
                platform=platform,
                success=True,
                execution_time_ms=execution_time_ms,
                row_count=row_count,
                tokens_estimated=tokens_estimated,
                cost_estimated=cost_estimated,
            )

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            return AIMLQueryResult(
                query_id=query_id,
                function_id=query.function_id,
                platform=platform,
                success=False,
                execution_time_ms=execution_time_ms,
                error_message=str(e),
            )

    def run_benchmark(
        self,
        connection: DatabaseConnection,
        platform: str | None = None,
        query_ids: list[str] | None = None,
        categories: list[AIMLFunctionCategory] | None = None,
        setup_data: bool = True,
    ) -> AIMLBenchmarkResults:
        """Run the AI/ML functions benchmark.

        Args:
            connection: Database connection
            platform: Target platform
            query_ids: Optional list of specific queries to run
            categories: Optional list of function categories to test
            setup_data: Whether to setup tables and data

        Returns:
            Benchmark results
        """
        if platform is None:
            platform = connection.platform if hasattr(connection, "platform") else "unknown"

        results = AIMLBenchmarkResults(
            platform=platform,
            started_at=datetime.now(timezone.utc),
        )

        # Setup data if requested
        if setup_data:
            logger.info("Setting up benchmark tables and data...")
            setup_results = self.setup_tables(connection, platform)
            if not all(setup_results.values()):
                logger.warning(f"Some setup steps failed: {setup_results}")

        # Get queries to run
        if query_ids is not None:
            queries_to_run = [
                self.query_manager.get_query(qid) for qid in query_ids if self.query_manager.get_query(qid) is not None
            ]
        elif categories is not None:
            queries_to_run = []
            for cat in categories:
                queries_to_run.extend(self.query_manager.get_queries_by_category(cat))
        else:
            queries_to_run = self.query_manager.get_queries_for_platform(platform)

        # Run queries
        for query in queries_to_run:
            if query is None:
                continue
            logger.info(f"Running query: {query.query_id}")
            result = self.execute_query(connection, query.query_id, platform)
            results.add_result(result)

            if result.success:
                logger.info(f"  ✓ {query.query_id}: {result.execution_time_ms:.2f}ms ({result.row_count} rows)")
            else:
                logger.warning(f"  ✗ {query.query_id}: {result.error_message}")

        results.complete()
        return results

    def get_categories(self) -> list[AIMLFunctionCategory]:
        """Get available function categories."""
        return list(AIMLFunctionCategory)

    def export_benchmark_spec(self) -> dict[str, Any]:
        """Export the benchmark specification."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "supported_platforms": list(self.SUPPORTED_PLATFORMS),
            "categories": [c.value for c in AIMLFunctionCategory],
            "functions": self.function_registry.export_registry(),
            "queries": self.query_manager.export_queries(),
            "data_manifest": self.data_generator.get_manifest(),
        }
