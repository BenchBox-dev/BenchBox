"""Synthetic Join Order Benchmark implementation.

This module preserves BenchBox's previous uniformly-random Join Order data
generator as an internal smoke-test benchmark. The public ``joinorder`` module
uses the canonical IMDb 2013 JOB dataset.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

from benchbox.base import BaseBenchmark, GeneratorOutputDirMixin
from benchbox.core.joinorder.schema import JoinOrderSchema
from benchbox.utils.clock import elapsed_seconds, mono_time

from .generator import JoinOrderGenerator
from .queries import JoinOrderQueryManager

if TYPE_CHECKING:
    from benchbox.core.dataframe.query import QueryRegistry
    from benchbox.core.tuning import UnifiedTuningConfiguration


class JoinOrderSyntheticBenchmark(GeneratorOutputDirMixin, BaseBenchmark):
    """Synthetic Join Order Benchmark implementation.

    This internal surface is for fast schema and loader smoke tests only.
    It is not a cardinality-estimation substitute for canonical JOB.
    """

    # CSV dialect for resolve_csv_dialect path (b) — used when manifest metadata is absent
    # (e.g. data cached before the generator wrote manifests).  Manifest-annotated data
    # (path a) will carry the same values; this class attribute is the safe fallback so
    # existing cached datasets load correctly without regeneration.
    # csv_null_marker="" tells SingleStore/PostgreSQL that empty CSV fields mean NULL,
    # which is required for nullable integer columns (imdb_id, episode_of_id, etc.)
    # that produce lines like "1,Comedy Adventure,,4,1957,,,,,,,".
    csv_delimiter = ","
    csv_null_marker = ""

    # Nested generator that must track output_dir reassignment.
    OUTPUT_DIR_GENERATOR_ATTRS = ("_generator",)

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Union[str, Path] | None = None,
        queries_dir: str | None = None,
        verbose: int | bool = 0,
        *,
        parallel: int = 1,
        force_regenerate: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize the Join Order benchmark.

        Args:
            scale_factor: Scale factor for synthetic data generation.
            output_dir: Directory for generated data files
                (defaults to benchmark_runs/datagen/joinorder_synthetic_sf{X})
            queries_dir: Directory containing Join Order Benchmark query files (optional)
            verbose: Verbosity level (-v=1, -vv=2; bool True treated as 1)
            parallel: Number of parallel workers for data generation
            force_regenerate: Force regeneration even if data exists
            **kwargs: Additional options (compression settings, etc.) passed to generator
        """
        if not isinstance(parallel, int) or parallel < 1:
            raise ValueError(f"parallel must be a positive integer, got {parallel}")

        # Extract quiet from kwargs to avoid duplicate parameter
        quiet = kwargs.pop("quiet", False)

        if output_dir is None:
            # Honor BENCHBOX_OUTPUT_DIR at construction; falls back to
            # Path.cwd()/benchmark_runs/datagen when no override is set.
            from benchbox.utils.path_utils import get_benchmark_runs_datagen_path

            output_dir = get_benchmark_runs_datagen_path("joinorder_synthetic", scale_factor)

        super().__init__(
            scale_factor=scale_factor,
            output_dir=output_dir,
            verbose=verbose,
            quiet=quiet,
        )

        self.parallel = parallel
        self.force_regenerate = force_regenerate

        self.queries_dir = queries_dir
        self._schema = JoinOrderSchema()
        self._query_manager = JoinOrderQueryManager(queries_dir)

        # Pass all kwargs through to generator (includes compression params)
        generator_kwargs: dict[str, Any] = {
            "force_regenerate": force_regenerate,
            **kwargs,
        }

        self._generator = JoinOrderGenerator(
            scale_factor=scale_factor,
            output_dir=self.output_dir,
            verbose=verbose,
            quiet=quiet,
            **generator_kwargs,
        )

    def generate_data(self) -> list[Path]:
        """Generate Join Order Benchmark dataset.

        Returns:
            List of generated data file paths
        """
        self.log_verbose(f"Generating synthetic Join Order data at scale factor {self.scale_factor}...")

        start_time = mono_time()
        data_files = self._generator.generate_data()
        generation_time = elapsed_seconds(start_time)

        self.log_verbose(f"Generated {len(data_files)} data files in {generation_time:.2f}s")

        return data_files

    def get_schema(self) -> dict[str, dict]:
        """Get the Join Order Benchmark schema definitions.

        Returns:
            Dictionary mapping table names to their schema definitions.
        """
        return self._schema._tables

    def get_create_tables_sql(
        self,
        dialect: str = "sqlite",
        tuning_config: UnifiedTuningConfiguration | None = None,
    ) -> str:
        """Get CREATE TABLE statements for all tables.

        Args:
            dialect: Target SQL dialect
            tuning_config: Unified tuning configuration (accepted for interface
                compatibility; join order schema does not currently use it)

        Returns:
            SQL CREATE TABLE statements
        """
        return self._schema.get_create_tables_sql(dialect)

    def get_table_names(self) -> list[str]:
        """Get list of all table names.

        Returns:
            List of table names in the schema
        """
        return self._schema.get_table_names()

    def get_query(self, query_id: str, *, params: dict[str, Any] | None = None) -> str:
        """Get a specific query by ID.

        Args:
            query_id: Query identifier (e.g., '1a', '2b', etc.)
            params: Optional parameter values (not supported for JoinOrder)

        Returns:
            SQL query text

        Raises:
            ValueError: If params are provided
        """
        if params is not None:
            raise ValueError("JoinOrder queries are static and don't accept parameters")
        return self._query_manager.get_query(query_id)

    def get_queries(self) -> dict[str, str]:
        """Get all queries.

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        return self._query_manager.get_all_queries()

    def get_query_ids(self) -> list[str]:
        """Get list of all query IDs.

        Returns:
            List of query IDs
        """
        return self._query_manager.get_query_ids()

    def get_query_count(self) -> int:
        """Get total number of queries.

        Returns:
            Number of queries available
        """
        return self._query_manager.get_query_count()

    def get_queries_by_complexity(self) -> dict[str, list[str]]:
        """Get queries categorized by complexity.

        Returns:
            Dictionary mapping complexity levels to query IDs
        """
        return self._query_manager.get_queries_by_complexity()

    def get_queries_by_pattern(self) -> dict[str, list[str]]:
        """Get queries categorized by join pattern.

        Returns:
            Dictionary mapping join patterns to query IDs
        """
        return self._query_manager.get_queries_by_pattern()

    def load_queries_from_directory(self, queries_dir: str) -> None:
        """Load queries from original Join Order Benchmark query files.

        Args:
            queries_dir: Path to directory containing Join Order Benchmark .sql files
        """
        self._query_manager = JoinOrderQueryManager(queries_dir)

    def get_table_info(self, table_name: str) -> dict[str, Any]:
        """Get information about a specific table.

        Args:
            table_name: Name of the table

        Returns:
            Dictionary with table schema information
        """
        return self._schema.get_table_info(table_name)

    def get_relationship_tables(self) -> list[str]:
        """Get list of relationship/junction tables.

        Returns:
            List of relationship table names
        """
        return self._schema.get_relationship_tables()

    def get_dimension_tables(self) -> list[str]:
        """Get list of main dimension tables.

        Returns:
            List of dimension table names
        """
        return self._schema.get_dimension_tables()

    def get_estimated_data_size(self) -> int:
        """Get estimated data size in bytes.

        Returns:
            Estimated total data size in bytes
        """
        return self._generator.get_total_size_estimate()

    def get_table_row_count(self, table_name: str) -> int:
        """Get expected row count for a table.

        Args:
            table_name: Name of the table

        Returns:
            Expected number of rows at current scale factor
        """
        return self._generator.get_table_row_count(table_name)

    def validate_query(self, query_id: str) -> bool:
        """Validate that a query is syntactically correct.

        Args:
            query_id: Query identifier

        Returns:
            True if query is valid, False otherwise
        """
        try:
            query = self.get_query(query_id)
            # Basic validation - check for SQL keywords
            query_upper = query.upper()
            required_keywords = ["SELECT", "FROM"]
            return all(keyword in query_upper for keyword in required_keywords)
        except Exception:
            return False

    def get_benchmark_info(self) -> dict[str, Any]:
        """Get comprehensive benchmark information.

        Returns:
            Dictionary with benchmark metadata
        """
        return {
            "benchmark_name": "Synthetic Join Order Benchmark",
            "description": "Uniformly-random Join Order schema smoke-test benchmark",
            "scale_factor": self.scale_factor,
            "output_dir": str(self.output_dir),
            "queries_dir": self.queries_dir,
            "total_queries": self.get_query_count(),
            "total_tables": len(self.get_table_names()),
            "relationship_tables": len(self.get_relationship_tables()),
            "dimension_tables": len(self.get_dimension_tables()),
            "estimated_size_bytes": self.get_estimated_data_size(),
            "query_complexity_distribution": self.get_queries_by_complexity(),
            "join_pattern_distribution": self.get_queries_by_pattern(),
            "reference_paper": "How Good Are Query Optimizers, Really? (VLDB 2015)",
            "authors": "Viktor Leis, Andrey Gubichev, Atanas Mirchev, Peter Boncz, Alfons Kemper, Thomas Neumann",
        }

    def get_dataframe_queries(self) -> QueryRegistry:
        """Get DataFrame query implementations for JoinOrder.

        Returns the QueryRegistry containing DataFrame implementations of all
        13 JoinOrder queries for both expression-family and pandas-family platforms.

        Returns:
            QueryRegistry with all 13 JoinOrder DataFrame queries
        """
        from benchbox.core.joinorder_synthetic.dataframe_queries import get_dataframe_queries

        return get_dataframe_queries()

    def __repr__(self) -> str:
        """String representation of the benchmark.

        Returns:
            String representation
        """
        return f"JoinOrderSyntheticBenchmark(scale_factor={self.scale_factor}, queries={self.get_query_count()})"


# ---------------------------------------------------------------------------
# Register benchmark-specific CLI option specs
# ---------------------------------------------------------------------------

from benchbox.cli.benchmark_hooks import (  # noqa: E402
    BenchmarkHookRegistry,
    BenchmarkOptionSpec,
)

BenchmarkHookRegistry.register_option_specs(
    "joinorder_synthetic",
    BenchmarkOptionSpec(
        name="queries_dir",
        help="Directory containing custom query files",
        aliases=("queries-dir",),
    ),
    BenchmarkOptionSpec(
        name="force_regenerate",
        parser=lambda v: v.strip().lower() in ("true", "1", "yes"),
        help="Force data regeneration",
        aliases=("force-regenerate",),
    ),
)


# Backward-compatible alias for callers that import the class from this module
# before going through the registry.
JoinOrderBenchmark = JoinOrderSyntheticBenchmark
