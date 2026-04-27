"""TPC-H benchmark implementation module.

Provides main TPC-H benchmark implementation.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration

from benchbox.base import BaseBenchmark
from benchbox.core.tpch.generator import TPCHDataGenerator
from benchbox.core.tpch.maintenance_test import TPCHMaintenanceTest
from benchbox.core.tpch.queries import TPCHQueries
from benchbox.core.tpch.schema import TABLES
from benchbox.core.tpch.streams import TPCHStreams

# TPC-H Reference Seeds for Validation
# The official TPC-H answer files at SF=1.0 were generated using seed 0o0101000000 (17039360 decimal)
# This seed must be used when performing exact validation against official answer files
TPCH_SF1_REFERENCE_SEED = 0o0101000000  # 17039360 decimal


def get_reference_seed(scale_factor: float) -> int | None:
    """Get the reference seed for exact validation at a given scale factor.

    Args:
        scale_factor: Scale factor for the benchmark

    Returns:
        Reference seed for exact validation, or None if no reference exists
    """
    if scale_factor == 1.0:
        return TPCH_SF1_REFERENCE_SEED
    return None


# Data structures for test results
@dataclass
class TPCHThroughputTestConfig:
    """Configuration for TPC-H Throughput Test."""

    num_streams: int = 2
    scale_factor: float = 1.0
    base_seed: int = 42
    query_timeout: int = 300
    stream_timeout: int = 3600
    max_retries: int = 3
    enable_validation: bool = True
    output_dir: Path | None = None


@dataclass
class TPCHThroughputTestResult:
    """Result of TPC-H Throughput Test."""

    config: TPCHThroughputTestConfig
    start_time: float
    end_time: float
    total_duration: float
    streams_executed: int
    streams_successful: int
    stream_results: list[dict[str, Any]]
    throughput_at_size: float
    success: bool
    error: str | None = None


@dataclass
class TPCHMaintenanceTestConfig:
    """Configuration for TPC-H Maintenance Test."""

    scale_factor: float = 1.0
    num_concurrent_streams: int = 2
    maintenance_interval: float = 30.0
    enable_rf1: bool = True
    enable_rf2: bool = True
    verbose: bool = False
    output_dir: Path | None = None


def _validate_tpch_get_query_args(query_id: int, scale_factor: float | None, seed: int | None) -> None:
    """Validate common arguments for get_query."""
    if not isinstance(query_id, int):
        raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
    if not (1 <= query_id <= 22):
        raise ValueError(f"Query ID must be 1-22, got {query_id}")
    if scale_factor is not None:
        if not isinstance(scale_factor, (int, float)):
            raise TypeError(f"scale_factor must be a number, got {type(scale_factor).__name__}")
        if scale_factor <= 0:
            raise ValueError(f"scale_factor must be positive, got {scale_factor}")
    if seed is not None and not isinstance(seed, int):
        raise TypeError(f"seed must be an integer, got {type(seed).__name__}")


def _resolve_tpch_seed(
    actual_seed: int | None, query_id: int, stream_id: int | None, permutation: list | None
) -> int | None:
    """Resolve seed from stream_id or explicit permutation for TPC-H queries."""
    if stream_id is not None:
        if not (0 <= stream_id < len(TPCHStreams.PERMUTATION_MATRIX)):
            raise ValueError(f"stream_id must be 0-{len(TPCHStreams.PERMUTATION_MATRIX) - 1}")

        stream_permutation = TPCHStreams.PERMUTATION_MATRIX[stream_id]
        try:
            position = stream_permutation.index(query_id)
            if actual_seed is None:
                return stream_id * 1000 + position
        except ValueError:
            raise ValueError(f"Query {query_id} not found in stream {stream_id} permutation") from None

    elif permutation is not None:
        if query_id not in permutation:
            raise ValueError(f"Query {query_id} not found in provided permutation")
        if actual_seed is None:
            try:
                return permutation.index(query_id)
            except ValueError:
                pass

    return actual_seed


def _expand_sqlite_named_column_aliases(query: str) -> str:
    """Move TPC-H named table-alias columns into SELECT aliases for SQLite translation."""
    if ") as c_orders (c_custkey, c_count)" in query:
        query = query.replace(
            "count(o_orderkey)\nfrom",
            "count(o_orderkey) as c_count\nfrom",
            1,
        ).replace(
            ") as c_orders (c_custkey, c_count)",
            ") as c_orders",
            1,
        )
    return query.replace(
        "with revenue (supplier_no, total_revenue) as (\nselect\nl_suppkey,\nsum(l_extendedprice * (1-l_discount))",
        "with revenue as (\nselect\nl_suppkey as supplier_no,\nsum(l_extendedprice * (1-l_discount)) as total_revenue",
        1,
    )


class TPCHBenchmark(BaseBenchmark):
    """TPC-H benchmark implementation.

    This class provides a complete implementation of the TPC-H benchmark,
    including data generation, query execution, and result validation.

    Attributes:
        scale_factor: The scale factor for the benchmark (1.0 = ~1GB)
        output_dir: Directory to output generated data and results
        query_manager: The TPC-H query manager
        data_generator: The TPC-H data generator
        tables: Dictionary mapping table names to paths of generated data files
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Union[str, Path] | None = None,
        verbose: int | bool = 0,
        parallel: int = 1,
        force_regenerate: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize a TPC-H benchmark instance.

        Args:
            scale_factor: Scale factor for the benchmark (1.0 = ~1GB)
            output_dir: Directory to output generated data files
            verbose: Whether to print verbose output during operations
            parallel: Number of parallel processes for data generation
            force_regenerate: Force data regeneration even if valid data exists
            **kwargs: Additional implementation-specific options

        Raises:
            ValueError: If scale_factor is not positive or parallel is not positive
            TypeError: If scale_factor is not a number or parallel is not an integer
        """
        # Validate scale_factor to match TPC-DS patterns
        if not isinstance(scale_factor, (int, float)):
            raise TypeError(f"scale_factor must be a number, got {type(scale_factor).__name__}")
        if scale_factor <= 0:
            raise ValueError(f"scale_factor must be positive, got {scale_factor}")

        # Validate parallel parameter
        if not isinstance(parallel, int):
            raise TypeError(f"parallel must be an integer, got {type(parallel).__name__}")
        if parallel < 1:
            raise ValueError(f"parallel must be positive, got {parallel}")

        # Extract quiet from kwargs to prevent duplicate kwarg error
        kwargs = dict(kwargs)
        quiet = kwargs.pop("quiet", False)

        super().__init__(scale_factor=scale_factor, output_dir=output_dir, verbose=verbose, quiet=quiet, **kwargs)
        self._name = "TPC-H Benchmark"
        self.parallel = parallel
        self.query_manager = TPCHQueries()
        self.data_generator = TPCHDataGenerator(
            scale_factor=scale_factor,
            parallel=parallel,
            output_dir=self.output_dir,
            verbose=verbose,
            quiet=quiet,
            force_regenerate=force_regenerate,
            **kwargs,  # Pass through compression parameters
        )
        self.tables: dict[str, Path | list[Path]] = {}

        # Initialize streams manager
        self.streams_manager: TPCHStreams | None = None

        # Initialize maintenance test manager
        self.maintenance_test: TPCHMaintenanceTest | None = None

    def generate_data(self) -> list[Union[str, Path]]:
        """Generate TPC-H benchmark data.

        Returns:
            A list of paths to the generated data files
        """
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.log_verbose(f"Generating TPC-H data at scale factor {self.scale_factor}...")
        self.log_verbose(f"Output directory: {self.output_dir}")

        # Use the data generator to create TPC-H tables
        self.tables = self.data_generator.generate()

        if self.verbose_enabled:
            self.logger.info(f"Generated {len(self.tables)} TPC-H tables:")
            for table_name, file_path in self.tables.items():
                self.logger.info(f"  - {table_name}: {file_path}")

        return list(self.tables.values())

    def get_queries(self, dialect: str | None = None, base_dialect: str | None = None) -> dict[str, str]:
        """Get all TPC-H benchmark queries.

        Args:
            dialect: Target SQL dialect for translation (e.g., 'duckdb', 'bigquery', 'snowflake')
                    If None, returns queries in their original format.

        Returns:
            A dictionary mapping query IDs (1-22) to query strings
        """
        src = (base_dialect or "netezza").lower()
        tgt = (dialect or src).lower()
        int_queries = self.query_manager.get_all_queries()
        base_queries = {str(k): v for k, v in int_queries.items()}
        translated_queries = {}
        for query_id, query in base_queries.items():
            translated_queries[query_id] = self.translate_query_text(query, src, tgt)
        return translated_queries

    def translate_query_text(self, query: str, source_dialect: str, target_dialect: str) -> str:
        """Translate a query from TPC-H's source dialect to target dialect.

        Uses the centralized translation function with proper dialect handling
        and identifier quoting to prevent reserved keyword conflicts.

        Args:
            query: SQL query text to translate
            source_dialect: Source SQL dialect (default: 'netezza')
            target_dialect: Target SQL dialect (e.g., 'duckdb', 'bigquery')

        Returns:
            Translated SQL query text
        """
        from benchbox.utils.dialect_utils import translate_sql_query

        src = (source_dialect or "netezza").lower()
        tgt = (target_dialect or src).lower()
        if tgt in ("sqlite", "mysql"):
            query = _expand_sqlite_named_column_aliases(query)

        return translate_sql_query(
            query=query,
            target_dialect=tgt,
            source_dialect=src,
            identify=True,
        )

    def get_query(
        self,
        query_id: int,
        *,
        params: dict[str, Any] | None = None,
        seed: int | None = None,
        scale_factor: float | None = None,
        dialect: str | None = None,
        base_dialect: str | None = None,
        **kwargs,
    ) -> str:
        """Get a specific TPC-H benchmark query.

        Args:
            query_id: The ID of the query to retrieve (1-22)
            params: Optional parameters to customize the query (legacy parameter, mostly ignored)
            seed: Random number generator seed for parameter generation
            scale_factor: Scale factor for parameter calculations
            dialect: Target SQL dialect (handled by translate_query)
            **kwargs: Additional parameters for future extensibility

        Returns:
            The fully prepared query string

        Raises:
            ValueError: If the query_id is invalid
            TypeError: If query_id is not an integer
        """
        _validate_tpch_get_query_args(query_id, scale_factor, seed)

        if params is None:
            params = {}

        actual_seed = seed if seed is not None else params.get("seed")
        actual_scale_factor = (
            scale_factor if scale_factor is not None else params.get("scale_factor", self.scale_factor)
        )

        actual_seed = _resolve_tpch_seed(actual_seed, query_id, params.get("stream_id"), params.get("permutation"))

        src = (base_dialect or "netezza").lower()
        tgt = (dialect or src).lower()
        query = self.query_manager.get_query(query_id, seed=actual_seed, scale_factor=actual_scale_factor)
        return self.translate_query_text(query, src, tgt)

    # (Removed duplicate translate_query_text definition; consolidated above.)

    def get_schema(self) -> dict[str, dict[str, Any]]:
        """Get the TPC-H schema.

        Returns:
            Dictionary mapping table names (lowercase) to table definitions.
            Each table definition contains 'name' and 'columns' keys.
        """
        schema = {}
        for table in TABLES:
            table_schema = {
                "name": table.name,
                "columns": [
                    {
                        "name": col.name,
                        "type": col.get_sql_type(),
                        "nullable": col.nullable,
                        "primary_key": col.primary_key,
                        "foreign_key": col.foreign_key,
                    }
                    for col in table.columns
                ],
            }
            schema[table.name.lower()] = table_schema
        return schema

    def get_create_tables_sql(
        self,
        dialect: str = "standard",
        tuning_config: UnifiedTuningConfiguration | None = None,
    ) -> str:
        """Get SQL to create all TPC-H tables.

        Args:
            dialect: SQL dialect to use (currently ignored, TPC-H uses standard SQL)
            tuning_config: Unified tuning configuration for constraint settings

        Returns:
            SQL script for creating all tables
        """
        from benchbox.core.tpch.schema import get_create_all_tables_sql

        # Extract constraint settings from tuning configuration
        self.log_very_verbose(
            f"TPC-H get_create_tables_sql called: dialect={dialect}, tuning_config={tuning_config is not None}"
        )

        enable_primary_keys = False
        enable_foreign_keys = False

        if tuning_config:
            try:
                enable_primary_keys = tuning_config.primary_keys.enabled
                enable_foreign_keys = tuning_config.foreign_keys.enabled
                self.log_very_verbose(
                    f"Extracted constraints from tuning_config: primary_keys={enable_primary_keys}, "
                    f"foreign_keys={enable_foreign_keys}"
                )
            except AttributeError as e:
                self.logger.error(
                    f"Failed to extract constraint settings from tuning_config: {e}. "
                    f"tuning_config type: {type(tuning_config)}"
                )
                raise RuntimeError(
                    f"Invalid tuning_config object (missing primary_keys or foreign_keys attributes): {e}"
                ) from e

        result = get_create_all_tables_sql(
            enable_primary_keys=enable_primary_keys,
            enable_foreign_keys=enable_foreign_keys,
        )
        self.log_very_verbose(f"Generated SQL: {len(result)} characters")
        return result

    @property
    def generator(self) -> TPCHDataGenerator:
        """Access to the data generator.

        Returns:
            The data generator instance
        """
        return self.data_generator
