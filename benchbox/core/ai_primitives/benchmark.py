"""AI/ML Primitives benchmark implementation.

Tests SQL-based AI/ML functions across cloud data platforms including
Snowflake Cortex, BigQuery ML, and Databricks AI Functions.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Union

import yaml

from benchbox.base import BaseBenchmark
from benchbox.core.ai_primitives.cost import (
    CostEstimate,
    CostTracker,
    estimate_query_cost,
    format_cost_warning,
)
from benchbox.core.ai_primitives.queries import AIQueryManager
from benchbox.utils.path_utils import get_benchmark_runs_datagen_path

logger = logging.getLogger(__name__)


def _load_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_SPECS = _load_specs()

# Platforms that support AI functions
SUPPORTED_PLATFORMS = set(_SPECS["supported_platforms"])

# Platforms where AI queries should be skipped
UNSUPPORTED_PLATFORMS = set(_SPECS["unsupported_platforms"])


@dataclass
class AIQueryResult:
    """Result of a single AI query execution.

    Attributes:
        query_id: Query identifier
        category: Query category
        execution_time_ms: Execution time in milliseconds
        success: Whether execution succeeded
        rows_processed: Number of rows processed
        tokens_estimated: Estimated tokens used
        cost_estimated_usd: Estimated cost in USD
        error: Error message if failed
        result_sample: Sample of result data (first few rows)
    """

    query_id: str
    category: str
    execution_time_ms: float = 0.0
    success: bool = True
    rows_processed: int = 0
    tokens_estimated: int = 0
    cost_estimated_usd: float = 0.0
    error: str | None = None
    result_sample: list[Any] = field(default_factory=list)


@dataclass
class AIBenchmarkResult:
    """Complete result of an AI Primitives benchmark run.

    Attributes:
        benchmark: Benchmark name
        platform: Target platform
        scale_factor: TPC-H scale factor used for data
        dry_run: Whether this was a dry run (no actual AI calls)
        total_queries: Total number of queries
        successful_queries: Number of successful queries
        failed_queries: Number of failed queries
        skipped_queries: Number of skipped queries (unsupported)
        total_execution_time_ms: Total execution time
        total_cost_estimated_usd: Total estimated cost
        cost_tracker: Detailed cost tracking
        query_results: Individual query results
    """

    benchmark: str = "AI Primitives"
    platform: str = ""
    scale_factor: float = 1.0
    dry_run: bool = False
    total_queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0
    skipped_queries: int = 0
    total_execution_time_ms: float = 0.0
    total_cost_estimated_usd: float = 0.0
    cost_tracker: CostTracker | None = None
    query_results: list[AIQueryResult] = field(default_factory=list)


class AIPrimitivesBenchmark(BaseBenchmark):
    """AI/ML Primitives benchmark implementation.

    Tests SQL-based AI functions across platforms:
    - Snowflake: Cortex functions (COMPLETE, SUMMARIZE, SENTIMENT, etc.)
    - BigQuery: ML functions (ML.GENERATE_TEXT, ML.UNDERSTAND_TEXT, etc.)
    - Databricks: AI functions (ai_query, ai_summarize, etc.)

    Uses TPC-H data for consistent test data across platforms.

    Attributes:
        scale_factor: TPC-H scale factor (affects data volume)
        output_dir: Data output directory
        query_manager: AI query manager
        max_cost_usd: Maximum allowed cost (0 = unlimited)
        dry_run: If True, estimate costs without executing
    """

    def __init__(
        self,
        scale_factor: float = 0.01,
        output_dir: Union[str, Path] | None = None,
        max_cost_usd: float = 0.0,
        dry_run: bool = False,
        **config: Any,
    ):
        """Initialize AI Primitives benchmark.

        Args:
            scale_factor: TPC-H scale factor (0.01 = minimal for AI testing)
            output_dir: Data output directory
            max_cost_usd: Maximum allowed cost in USD (0 = unlimited)
            dry_run: If True, only estimate costs without executing
            **config: Additional configuration
        """
        config = dict(config)
        quiet = config.pop("quiet", False)

        super().__init__(scale_factor, quiet=quiet, **config)

        self._name = "AI/ML Primitives Benchmark"
        self._version = "1.0"
        self._description = "AI/ML Primitives benchmark - Testing SQL-based AI functions using TPC-H data"

        # Setup directories (reuse TPC-H data)
        if output_dir is None:
            output_dir = get_benchmark_runs_datagen_path("tpch", scale_factor)
        self.output_dir = Path(output_dir)

        # Initialize components
        self.query_manager: AIQueryManager = AIQueryManager()
        self.max_cost_usd = max_cost_usd
        self.dry_run = dry_run
        self.cost_tracker = CostTracker(budget_usd=max_cost_usd)

        # Data file mapping (reuses TPC-H). Values may be sharded file lists.
        self.tables: dict[str, Any] = {}

    def get_data_source_benchmark(self) -> str | None:
        """AI Primitives benchmark shares TPC-H data."""
        return "tpch"

    def generate_data(self) -> list[Union[str, Path]]:
        """Generate benchmark data.

        AI Primitives reuses TPC-H data, so this delegates to the TPC-H benchmark
        data generation when needed.

        Returns:
            List of data file paths
        """
        # AI Primitives uses TPC-H data - delegate to TPC-H generator
        from benchbox.core.tpch.benchmark import TPCHBenchmark

        tpch = TPCHBenchmark(scale_factor=self.scale_factor, output_dir=self.output_dir)
        tpch.generate_data()

        # Preserve TPC-H's table-name mapping so loaders can handle sharded files.
        self.tables = dict(tpch.tables)

        flattened: list[Union[str, Path]] = []
        for table_files in self.tables.values():
            if isinstance(table_files, (list, tuple)):
                flattened.extend(table_files)
            else:
                flattened.append(table_files)
        return flattened

    def is_platform_supported(self, platform: str) -> bool:
        """Check if a platform supports AI functions.

        Args:
            platform: Platform name

        Returns:
            True if platform supports AI functions
        """
        return platform.lower() in SUPPORTED_PLATFORMS

    def get_supported_queries(self, platform: str) -> dict[str, str]:
        """Get queries supported on a specific platform.

        Args:
            platform: Target platform

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        if not self.is_platform_supported(platform):
            return {}
        return self.query_manager.get_supported_queries(platform)

    def get_query(self, query_id: Union[int, str], *, params: dict[str, Any] | None = None) -> str:
        """Get SQL text for a specific AI query.

        Args:
            query_id: Query identifier
            params: Optional parameters (not supported for AI queries)

        Returns:
            SQL text of the query

        Raises:
            ValueError: If query_id is not valid or params are provided
        """
        if params is not None:
            raise ValueError("AI Primitives queries are static and don't accept parameters")
        return self.query_manager.get_query(str(query_id))

    def get_queries(self, dialect: str | None = None) -> dict[str, str]:
        """Get all available AI queries.

        Args:
            dialect: Target SQL dialect for query variants

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        if dialect:
            return self.query_manager.get_supported_queries(dialect)
        return self.query_manager.get_all_queries()

    def get_all_queries(self) -> dict[str, str]:
        """Get all available AI queries.

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        return self.query_manager.get_all_queries()

    def get_queries_by_category(self, category: str) -> dict[str, str]:
        """Get queries filtered by category.

        Args:
            category: Category name (generative, nlp, transform, embedding)

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        return self.query_manager.get_queries_by_category(category)

    def get_query_categories(self) -> list[str]:
        """Get list of available query categories.

        Returns:
            List of category names
        """
        return self.query_manager.get_query_categories()

    def estimate_cost(
        self,
        platform: str,
        queries: list[str] | None = None,
        categories: list[str] | None = None,
    ) -> tuple[float, list[CostEstimate]]:
        """Estimate cost for running AI queries.

        Args:
            platform: Target platform
            queries: Optional list of query IDs (None = all supported)
            categories: Optional categories to filter

        Returns:
            Tuple of (total_estimated_cost, list_of_estimates)
        """
        estimates: list[CostEstimate] = []
        total_cost = 0.0

        # Determine queries to estimate
        if queries is not None:
            query_ids = queries
        elif categories:
            query_ids = []
            for category in categories:
                cat_queries = self.query_manager.get_queries_by_category(category)
                query_ids.extend(cat_queries.keys())
        else:
            query_ids = list(self.query_manager.get_all_queries().keys())

        for query_id in query_ids:
            try:
                entry = self.query_manager.get_query_entry(query_id)

                # Skip if not supported on platform
                if entry.skip_on and platform.lower() in entry.skip_on:
                    continue

                estimate = estimate_query_cost(
                    query_id=query_id,
                    platform=platform,
                    model=entry.model,
                    estimated_tokens=entry.estimated_tokens,
                    num_rows=entry.batch_size,
                    cost_per_1k_tokens=entry.cost_per_1k_tokens,
                )
                estimates.append(estimate)
                total_cost += estimate.estimated_cost_usd

            except ValueError:
                continue

        return total_cost, estimates

    def execute_query(
        self,
        query_id: Union[int, str],
        connection: Any,
        platform: str,
        params: dict[str, Any] | None = None,
    ) -> AIQueryResult:
        """Execute a single AI query.

        Args:
            query_id: Query identifier
            connection: Database connection
            platform: Target platform
            params: Optional query parameters (not used)

        Returns:
            AIQueryResult with execution details
        """
        query_id_str = str(query_id)
        entry = self.query_manager.get_query_entry(query_id_str)

        result = AIQueryResult(
            query_id=query_id_str,
            category=entry.category,
            tokens_estimated=entry.estimated_tokens * entry.batch_size,
            cost_estimated_usd=(entry.estimated_tokens * entry.batch_size / 1000) * entry.cost_per_1k_tokens,
        )

        # Check if platform supports this query
        if entry.skip_on and platform.lower() in entry.skip_on:
            result.success = False
            result.error = f"Query not supported on platform '{platform}'"
            return result

        # Get platform-specific SQL
        try:
            sql = self.query_manager.get_query(query_id_str, dialect=platform)
        except ValueError as e:
            result.success = False
            result.error = str(e)
            return result

        # Execute query
        start_time = time.perf_counter()
        try:
            if hasattr(connection, "execute"):
                cursor = connection.execute(sql)
                rows = cursor.fetchall() if hasattr(cursor, "fetchall") else []
            elif hasattr(connection, "cursor"):
                cursor = connection.cursor()
                cursor.execute(sql)
                rows = cursor.fetchall()
            else:
                raise ValueError("Unsupported connection type")

            end_time = time.perf_counter()
            result.execution_time_ms = (end_time - start_time) * 1000
            result.rows_processed = len(rows)
            result.success = True

            # Store sample of results (first 3 rows)
            if rows:
                result.result_sample = [list(row) if hasattr(row, "__iter__") else [row] for row in rows[:3]]

        except Exception as e:
            end_time = time.perf_counter()
            result.execution_time_ms = (end_time - start_time) * 1000
            result.success = False
            result.error = str(e)
            logger.warning(f"Query {query_id_str} failed: {e}")

        return result

    def run_benchmark(
        self,
        connection: Any,
        platform: str,
        queries: list[str] | None = None,
        categories: list[str] | None = None,
        dry_run: bool = False,
    ) -> AIBenchmarkResult:
        """Run the AI Primitives benchmark.

        Args:
            connection: Database connection
            platform: Target platform (snowflake, bigquery, databricks)
            queries: Optional list of specific query IDs
            categories: Optional categories to run
            dry_run: If True, only estimate costs

        Returns:
            AIBenchmarkResult with benchmark results
        """
        if not dry_run:
            dry_run = self.dry_run

        result = AIBenchmarkResult(
            platform=platform,
            scale_factor=self.scale_factor,
            dry_run=dry_run,
        )

        if not self.is_platform_supported(platform):
            logger.warning(f"Platform '{platform}' does not support AI functions")
            result.skipped_queries = len(self.query_manager.get_all_queries())
            return result

        query_ids = self._resolve_query_ids(queries, categories, platform)
        result.total_queries = len(query_ids)

        total_cost, estimates = self._prepare_cost_tracking(platform, query_ids, dry_run)
        result.total_cost_estimated_usd = total_cost

        if dry_run:
            return self._build_dry_run_result(result, estimates)

        self._execute_ai_queries(result, query_ids, connection, platform)
        result.cost_tracker = self.cost_tracker
        return result

    def _resolve_query_ids(self, queries: list[str] | None, categories: list[str] | None, platform: str) -> list[str]:
        """Determine which query IDs to run based on explicit list, categories, or platform defaults."""
        if queries is not None:
            return queries
        if categories:
            query_ids: list[str] = []
            for category in categories:
                cat_queries = self.query_manager.get_queries_by_category(category)
                query_ids.extend(cat_queries.keys())
            return query_ids
        return list(self.query_manager.get_supported_queries(platform).keys())

    def _prepare_cost_tracking(
        self, platform: str, query_ids: list[str], dry_run: bool
    ) -> tuple[float, list[CostEstimate]]:
        """Estimate costs, initialize tracker, and enforce budget limits."""
        total_cost, estimates = self.estimate_cost(platform, query_ids)

        self.cost_tracker = CostTracker(platform=platform, budget_usd=self.max_cost_usd)
        for estimate in estimates:
            self.cost_tracker.add_estimate(estimate)

        if total_cost > 0:
            warning = format_cost_warning(total_cost, self.max_cost_usd or None, platform)
            logger.info(warning)

        if self.max_cost_usd > 0 and total_cost > self.max_cost_usd:
            logger.error(f"Estimated cost ${total_cost:.4f} exceeds budget ${self.max_cost_usd:.4f}")
            if not dry_run:
                raise ValueError(
                    f"Estimated cost ${total_cost:.4f} exceeds budget ${self.max_cost_usd:.4f}. "
                    "Use --dry-run to preview costs or increase --max-ai-cost."
                )

        return total_cost, estimates

    def _build_dry_run_result(self, result: AIBenchmarkResult, estimates: list[CostEstimate]) -> AIBenchmarkResult:
        """Build result containing cost estimates only (dry run mode)."""
        logger.info("Dry run mode - returning cost estimates only")
        for estimate in estimates:
            query_result = AIQueryResult(
                query_id=estimate.query_id,
                category=self.query_manager.get_query_entry(estimate.query_id).category,
                tokens_estimated=estimate.estimated_tokens,
                cost_estimated_usd=estimate.estimated_cost_usd,
                success=True,
            )
            result.query_results.append(query_result)
        return result

    def _execute_ai_queries(
        self, result: AIBenchmarkResult, query_ids: list[str], connection: Any, platform: str
    ) -> None:
        """Execute AI queries with budget checking and cost tracking."""
        start_time = time.perf_counter()

        for query_id in query_ids:
            try:
                entry = self.query_manager.get_query_entry(query_id)

                if entry.skip_on and platform.lower() in entry.skip_on:
                    result.skipped_queries += 1
                    continue

                estimated_cost = (entry.estimated_tokens * entry.batch_size / 1000) * entry.cost_per_1k_tokens
                if not self.cost_tracker.check_budget(estimated_cost):
                    logger.warning(f"Skipping {query_id} - would exceed budget")
                    result.skipped_queries += 1
                    continue

                query_result = self.execute_query(query_id, connection, platform)
                result.query_results.append(query_result)

                if query_result.success:
                    result.successful_queries += 1
                    self.cost_tracker.record_execution(
                        query_id, query_result.tokens_estimated, query_result.cost_estimated_usd, success=True
                    )
                else:
                    result.failed_queries += 1
                    self.cost_tracker.record_execution(query_id, 0, 0, success=False)

            except Exception as e:
                logger.error(f"Error executing query {query_id}: {e}")
                result.failed_queries += 1

        end_time = time.perf_counter()
        result.total_execution_time_ms = (end_time - start_time) * 1000

    def get_benchmark_info(self) -> dict[str, Any]:
        """Get information about the benchmark.

        Returns:
            Dictionary containing benchmark metadata
        """
        return {
            "name": self._name,
            "version": self._version,
            "description": self._description,
            "scale_factor": self.scale_factor,
            "total_queries": len(self.query_manager.get_all_queries()),
            "categories": self.get_query_categories(),
            "supported_platforms": list(SUPPORTED_PLATFORMS),
            "unsupported_platforms": list(UNSUPPORTED_PLATFORMS),
            "max_cost_usd": self.max_cost_usd,
            "dry_run": self.dry_run,
            "data_source": "tpch",
        }

    def _get_default_benchmark_type(self) -> str:
        """AI Primitives uses analytical workload type."""
        return "analytical"

    # =========================================================================
    # DataFrame Support Methods
    # =========================================================================

    def supports_dataframe_mode(self) -> bool:
        """Check if this benchmark supports DataFrame execution mode.

        AI Primitives supports DataFrame mode for 8 of 16 queries that can
        run with local ML models (sentence-transformers, TextBlob, spaCy).

        Returns:
            True - AI Primitives supports DataFrame mode
        """
        return True

    def get_dataframe_operations(self) -> Any:
        """Get the DataFrame AI operations manager.

        Returns:
            DataFrameAIOperationsManager for AI operations
        """
        from benchbox.core.ai_primitives.dataframe_operations import (
            DataFrameAIOperationsManager,
        )

        return DataFrameAIOperationsManager("generic")

    def get_dataframe_skip_queries(self) -> list[str]:
        """Get query IDs that should be skipped for DataFrame execution.

        These are generative/transform queries that require LLM API integration.

        Returns:
            List of query IDs to skip (8 queries)
        """
        from benchbox.core.ai_primitives.dataframe_operations import (
            get_skip_for_dataframe,
        )

        return get_skip_for_dataframe()

    def get_dataframe_supported_queries(self) -> list[str]:
        """Get query IDs that are supported for DataFrame execution.

        These are embedding and NLP queries that can run with local models.

        Returns:
            List of query IDs supported for DataFrame mode (8 queries)
        """
        all_query_ids = list(self.query_manager.get_all_queries().keys())
        skip_ids = set(self.get_dataframe_skip_queries())
        return [qid for qid in all_query_ids if qid not in skip_ids]


__all__ = [
    "AIPrimitivesBenchmark",
    "AIQueryResult",
    "AIBenchmarkResult",
    "SUPPORTED_PLATFORMS",
    "UNSUPPORTED_PLATFORMS",
]
