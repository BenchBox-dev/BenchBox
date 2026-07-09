"""Vector search benchmark core implementation.

Implements the BaseBenchmark interface for benchmarking vector/embedding
similarity search across OLAP platforms that support array operations.

The benchmark covers:
  - kNN exact cosine similarity search
  - kNN exact L2-distance search
  - Filtered kNN search (metadata predicate + distance order)
  - Large-k recall-ground-truth generation
  - ANN search (same SQL; relies on HNSW index from load phase)
  - Multi-category filtered search

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from benchbox.base import BaseBenchmark, GeneratorOutputDirMixin
from benchbox.core.benchmark_mixins import DataGenerationMixin
from benchbox.core.query_catalog_base import QuerySkippedError, TranslatableQueryMixin
from benchbox.core.utils.tuning import extract_constraint_flags
from benchbox.core.vector_search.generator import VectorSearchDataGenerator
from benchbox.core.vector_search.queries import VectorSearchQueryManager
from benchbox.core.vector_search.schema import TABLES, get_all_create_table_sql
from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration

# Default embedding dimensionality; overridable via constructor kwarg.
DEFAULT_DIMENSIONS = 128


class VectorSearchBenchmark(GeneratorOutputDirMixin, TranslatableQueryMixin, DataGenerationMixin, BaseBenchmark):
    """Vector search benchmark implementation.

    Tests similarity-search performance across OLAP databases that support
    array/vector operations.  Primary target: DuckDB with built-in
    ``array_cosine_similarity`` / ``array_distance`` functions.  Dialect
    variants are available for pgvector, ClickHouse, and Snowflake.

    Attributes:
        scale_factor: Controls corpus size (SF=1 → ~1 M vectors).
        dimensions: Embedding dimensionality (default 128).
        query_manager: Manages all six benchmark queries.
        data_generator: Produces reproducible synthetic embedding data.
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        *,
        dimensions: int = DEFAULT_DIMENSIONS,
        **config: Any,
    ) -> None:
        """Initialise the vector search benchmark.

        Args:
            scale_factor: Data scale (SF=0.01 → ~10 K vectors, SF=1 → ~1 M).
            output_dir: Directory for generated data files.
            dimensions: Embedding vector dimension count (default 128).
            **config: Forwarded to BaseBenchmark / mixins.
        """
        config = dict(config)
        quiet = config.pop("quiet", False)

        super().__init__(scale_factor, output_dir=output_dir, quiet=quiet, **config)

        self._name = "Vector Search Benchmark"
        self._version = "1.0"
        self._description = (
            "Benchmarks similarity search (kNN, ANN, filtered) across OLAP databases with vector/embedding support."
        )

        self.dimensions = dimensions

        self.query_manager = VectorSearchQueryManager()
        self.data_generator = VectorSearchDataGenerator(
            scale_factor,
            self.output_dir,
            dimensions=dimensions,
            **config,
        )

        self.tables: dict[str, Path] = {}
        # _csv_delimiter backs the BaseBenchmark.csv_delimiter read-only property
        self._csv_delimiter: str = "|"
        self.csv_has_header: bool = True

    # ------------------------------------------------------------------
    # Schema / DDL
    # ------------------------------------------------------------------

    def _get_table_schema(self) -> dict[str, dict]:
        return TABLES

    def get_schema(self, dialect: str = "duckdb") -> dict[str, dict]:
        """Return the table schema dictionary."""
        return TABLES

    def get_create_tables_sql(
        self,
        dialect: str = "duckdb",
        tuning_config: Optional[UnifiedTuningConfiguration] = None,
    ) -> str:
        """Return CREATE TABLE SQL for both vector search tables.

        Args:
            dialect: Target SQL dialect (duckdb, postgresql, snowflake, …).
            tuning_config: Unified tuning config (used for constraint flags).

        Returns:
            DDL script as a single string.
        """
        enable_primary_keys, _ = extract_constraint_flags(tuning_config)
        return get_all_create_table_sql(
            dialect=dialect,
            dimensions=self.dimensions,
            enable_primary_keys=enable_primary_keys,
        )

    # ------------------------------------------------------------------
    # Query access
    # ------------------------------------------------------------------

    def get_query(
        self,
        query_id: Union[int, str],
        *,
        params: Optional[dict[str, Any]] = None,
        dialect: Optional[str] = None,
        platform_version: str | None = None,
    ) -> str:
        """Return SQL for *query_id*.

        Args:
            query_id: Q1-Q6.
            params: Not supported - vector search queries are static.
            dialect: SQL dialect override (postgresql, clickhouse, snowflake).
                     Returns DuckDB SQL when *None*.
            platform_version: Optional engine version string used by
                version-gated compat rules.

        Returns:
            SQL string.

        Raises:
            ValueError: If *query_id* is not valid or params are provided.
        """
        if params is not None:
            raise ValueError(
                "Vector search queries are static and do not accept parameters. "
                "To use a different dialect pass dialect= to get_query()."
            )
        return self.query_manager.get_query(str(query_id), dialect=dialect, platform_version=platform_version)

    def get_queries(self, dialect: Optional[str] = None, platform_version: str | None = None) -> dict[str, str]:
        """Return all queries, optionally in a platform-specific dialect.

        Vector search queries use platform-specific functions (e.g.
        ``array_cosine_similarity`` vs ``<=>`` vs ``cosineDistance``) that
        sqlglot cannot translate.  This method therefore uses the query
        manager's built-in dialect variants rather than sqlglot translation.

        Args:
            dialect: SQL dialect override (postgresql, clickhouse, snowflake).
                     Returns DuckDB SQL when *None* or when the dialect has
                     no explicit variant defined.
            platform_version: Optional engine version string used by
                version-gated compat rules.

        Returns:
            Dict mapping Q1-Q6 to SQL strings.
        """
        return self.query_manager.get_all_queries(dialect=dialect, platform_version=platform_version)

    def get_all_queries(
        self,
        dialect: Optional[str] = None,
        platform_version: str | None = None,
    ) -> dict[str, str]:
        """Return all queries, optionally applying compat-gated dialect variants."""
        return self.query_manager.get_all_queries(dialect=dialect, platform_version=platform_version)

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    def execute_query(
        self,
        query_id: Union[int, str],
        connection: Any,
        params: Optional[dict[str, Any]] = None,
        *,
        dialect: Optional[str] = None,
        platform_version: str | None = None,
    ) -> Any:
        """Execute a vector search query on *connection*.

        Args:
            query_id: Q1-Q6.
            connection: Database connection (must support ``.execute()`` or
                        ``.cursor()``).
            params: Not supported - vector search queries are static.
            dialect: SQL dialect override (postgresql, clickhouse, snowflake).
                     Returns DuckDB SQL when *None*.
            platform_version: Optional engine version string used by
                version-gated compat rules.

        Returns:
            Query result rows.

        Raises:
            ValueError: If *query_id* is not recognised or params are provided.
        """
        sql = self.get_query(query_id, dialect=dialect, params=params, platform_version=platform_version)

        if hasattr(connection, "execute"):
            cursor = connection.execute(sql)
            return cursor.fetchall()
        elif hasattr(connection, "cursor"):
            cursor = connection.cursor()
            cursor.execute(sql)
            return cursor.fetchall()
        else:
            raise ValueError(f"Unsupported connection type: {type(connection)}")

    # ------------------------------------------------------------------
    # Benchmark runner
    # ------------------------------------------------------------------

    def run_benchmark(
        self,
        connection: Any,
        queries: Optional[list[str]] = None,
        iterations: int = 1,
        *,
        dialect: Optional[str] = None,
        platform_version: str | None = None,
    ) -> dict[str, Any]:
        """Run the complete vector search benchmark.

        Args:
            connection: Database connection.
            queries: Optional subset of query IDs.  Runs all six if *None*.
            iterations: How many times each query is executed.
            dialect: SQL dialect override (postgresql, clickhouse, snowflake).
                     Uses DuckDB SQL when *None*.
            platform_version: Optional engine version string used by
                version-gated compat rules.

        Returns:
            Dict with timing and metadata for each query.
        """
        if queries is None:
            queries = list(self.query_manager.ALL_QUERY_IDS)

        results: dict[str, Any] = {
            "benchmark": "Vector Search Benchmark",
            "scale_factor": self.scale_factor,
            "dimensions": self.dimensions,
            "iterations": iterations,
            "queries": {},
        }

        for query_id in queries:
            description = self.query_manager.get_description(query_id)
            try:
                sql_text = self.get_query(query_id, dialect=dialect, platform_version=platform_version)
            except QuerySkippedError as exc:
                results["queries"][query_id] = {
                    "query_id": query_id,
                    "description": description,
                    "iterations": [],
                    "avg_time": 0.0,
                    "min_time": 0.0,
                    "max_time": 0.0,
                    "sql_text": None,
                    "rows_returned": 0,
                    "status": "SKIPPED",
                    "skip_reason": str(exc),
                }
                continue

            query_results: dict[str, Any] = {
                "query_id": query_id,
                "description": description,
                "iterations": [],
                "avg_time": 0.0,
                "min_time": float("inf"),
                "max_time": 0.0,
                "sql_text": sql_text,
            }

            for i in range(iterations):
                start = mono_time()
                try:
                    result = self.execute_query(
                        query_id,
                        connection,
                        dialect=dialect,
                        platform_version=platform_version,
                    )
                    duration = elapsed_seconds(start)
                    query_results["iterations"].append(
                        {
                            "iteration": i + 1,
                            "time": duration,
                            "rows": len(result) if result else 0,
                            "success": True,
                        }
                    )
                    query_results["min_time"] = min(query_results["min_time"], duration)
                    query_results["max_time"] = max(query_results["max_time"], duration)
                except Exception as exc:
                    query_results["iterations"].append(
                        {
                            "iteration": i + 1,
                            "time": 0.0,
                            "error": str(exc),
                            "success": False,
                        }
                    )

            successful = [it for it in query_results["iterations"] if it["success"]]
            if successful:
                times = [it["time"] for it in successful]
                rows = [it.get("rows", 0) for it in successful]
                query_results["avg_time"] = sum(times) / len(times)
                query_results["rows_returned"] = int(sum(rows) / len(rows))

            results["queries"][query_id] = query_results

        return results


# ---------------------------------------------------------------------------
# Register benchmark-specific CLI option specs
# ---------------------------------------------------------------------------

from benchbox.core.hooks.benchmark_hooks import (  # noqa: E402
    BenchmarkHookRegistry,
    BenchmarkOptionSpec,
    parse_int,
)

BenchmarkHookRegistry.register_option_specs(
    "vector_search",
    BenchmarkOptionSpec(
        name="dimensions",
        parser=parse_int,
        default=DEFAULT_DIMENSIONS,
        help="Embedding vector dimensions",
    ),
)
