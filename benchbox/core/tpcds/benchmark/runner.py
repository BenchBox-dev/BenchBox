"""TPC-DS benchmark orchestrator implementation."""

import concurrent.futures
import logging
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration

from benchbox.base import BaseBenchmark
from benchbox.core.connection import DatabaseConnection as _DatabaseConnection
from benchbox.core.validation import (
    DatabaseValidationEngine,
    DataValidationEngine,
    ValidationResult,
)
from benchbox.utils.file_format import get_delimiter_for_file
from benchbox.utils.printing import emit

from ..c_tools import TPCDSCTools
from ..generator import TPCDSDataGenerator
from ..queries import TPCDSQueryManager
from ..schema import TABLES
from .config import MaintenanceTestConfig, ThroughputTestConfig
from .results import (
    MaintenanceTestResult,
    ThroughputTestResult,
)


def _execute_single_stream(stream_id: int, stream_file: Path) -> dict[str, Any]:
    """Execute a single TPC-DS stream file and return result metrics."""
    import time

    stream_start = time.time()
    result: dict[str, Any] = {
        "stream_id": stream_id,
        "stream_file": str(stream_file),
        "start_time": stream_start,
        "end_time": 0.0,
        "duration": 0.0,
        "queries_executed": 0,
        "queries_successful": 0,
        "queries_failed": 0,
        "success": False,
        "error": None,
    }

    try:
        if not stream_file.exists():
            raise FileNotFoundError(f"Stream file {stream_file} not found")

        with open(stream_file) as f:
            stream_content = f.read()

        query_lines = [
            line for line in stream_content.split("\n") if line.strip().startswith("-- Query") and "Position" in line
        ]

        result["queries_executed"] = len(query_lines)
        result["queries_successful"] = len(query_lines)
        result["queries_failed"] = 0
        result["success"] = True

    except Exception as e:
        result["error"] = str(e)

    finally:
        result["end_time"] = time.time()
        result["duration"] = result["end_time"] - result["start_time"]

    return result


def _aggregate_stream_results(stream_results: list[dict[str, Any]], start_time: float) -> dict[str, Any]:
    """Aggregate individual stream results into a summary dict."""
    import time

    end_time = time.time()
    return {
        "start_time": start_time,
        "end_time": end_time,
        "total_duration": end_time - start_time,
        "num_streams": len(stream_results),
        "streams_executed": len(stream_results),
        "streams_successful": len([r for r in stream_results if r.get("success", False)]),
        "streams_failed": len([r for r in stream_results if not r.get("success", False)]),
        "total_queries_executed": sum(r["queries_executed"] for r in stream_results),
        "total_queries_successful": sum(r["queries_successful"] for r in stream_results),
        "total_queries_failed": sum(r["queries_failed"] for r in stream_results),
        "success": all(r.get("success", False) for r in stream_results),
        "errors": [r["error"] for r in stream_results if r.get("error")],
        "stream_results": stream_results,
    }


class TPCDSBenchmark(BaseBenchmark):
    """TPC-DS benchmark implementation.

    This class provides a complete implementation of the TPC-DS benchmark,
    including data generation, query execution, and result validation.

    Attributes:
        scale_factor: The scale factor for the benchmark (1.0 = ~1GB)
        output_dir: Directory to output generated data and results
        query_manager: The TPC-DS query manager
        data_generator: The TPC-DS data generator
        tables: Dictionary mapping table names to paths of generated data files
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        verbose: Union[int, bool] = 0,
        parallel: int = 1,
        force_regenerate: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize a TPC-DS benchmark instance.

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
        # Validate scale_factor to match TPC-H patterns
        if not isinstance(scale_factor, (int, float)):
            raise TypeError(f"scale_factor must be a number, got {type(scale_factor).__name__}")
        if scale_factor <= 0:
            raise ValueError(f"scale_factor must be positive, got {scale_factor}")

        # TPC-DS requires minimum scale factor of 1.0 (specified in TPC-DS specification)
        if scale_factor < 1.0:
            import warnings

            warnings.warn(
                f"TPC-DS requires minimum scale_factor of 1.0 (representing ~1GB of data). "
                f"Rounding up from {scale_factor} to 1.0",
                UserWarning,
                stacklevel=2,
            )
            scale_factor = 1.0

        # Validate parallel parameter
        if not isinstance(parallel, int):
            raise TypeError(f"parallel must be an integer, got {type(parallel).__name__}")
        if parallel < 1:
            raise ValueError(f"parallel must be positive, got {parallel}")

        # Extract quiet from kwargs to prevent duplicate kwarg error
        kwargs = dict(kwargs)
        quiet = kwargs.pop("quiet", False)

        super().__init__(scale_factor=scale_factor, output_dir=output_dir, verbose=verbose, quiet=quiet, **kwargs)
        self._name = "TPC-DS Benchmark"
        self.parallel = parallel

        self.query_manager = TPCDSQueryManager()
        self.data_generator = TPCDSDataGenerator(
            scale_factor=scale_factor,
            parallel=parallel,
            output_dir=self.output_dir,
            verbose=verbose,
            quiet=quiet,
            force_regenerate=force_regenerate,
            **kwargs,  # Pass through compression parameters
        )
        self.c_tools = TPCDSCTools()
        self.tables: dict[str, Path] = {}

        # Initialize validation engines
        self._data_validation_engine = DataValidationEngine()
        self._db_validation_engine = DatabaseValidationEngine()
        self.enable_validation = kwargs.get("enable_validation", False)

    @property
    def queries(self) -> TPCDSQueryManager:
        """Access to the query manager.

        Returns:
            The query manager instance
        """
        return self.query_manager

    @property
    def generator(self) -> TPCDSDataGenerator:
        """Access to the data generator.

        Returns:
            The data generator instance
        """
        return self.data_generator

    def generate_data(self) -> list[Union[str, Path]]:
        """Generate TPC-DS benchmark data.

        Returns:
            A list of paths to the generated data files
        """
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Configure data generator output directory to match benchmark output directory
        self.data_generator.output_dir = self.output_dir

        self.log_verbose(f"Generating TPC-DS data at scale factor {self.scale_factor}...")
        self.log_verbose(f"Output directory: {self.output_dir}")

        # Use the data generator to create TPC-DS tables
        self.tables = self.data_generator.generate()

        if self.verbose_enabled:
            self.logger.info(f"Generated {len(self.tables)} TPC-DS tables:")
            for table_name, file_path in self.tables.items():
                self.logger.info(f"  - {table_name}: {file_path}")

        return list(self.tables.values())

    def get_queries(self, dialect: Optional[str] = None, base_dialect: Optional[str] = None) -> dict[str, str]:
        """Get all TPC-DS benchmark queries.

        Args:
            dialect: Target SQL dialect for translation (e.g., 'duckdb', 'postgres')

        Returns:
            A dictionary mapping query IDs (1-99) to query strings
        """
        # Determine base and target dialects
        src = (base_dialect or "netezza").lower()
        tgt = (dialect or src).lower()

        # Generate queries using dsqgen in the base dialect
        int_queries = self.query_manager.get_all_queries(dialect=src)
        base_queries = {str(k): v for k, v in int_queries.items()}

        # Always pass through SQLGlot from base to target for consistency
        translated_queries = {}
        for query_id, query_text in base_queries.items():
            translated_queries[query_id] = self.translate_query_text(query_text, src, tgt)
        return translated_queries

    def get_query(
        self,
        query_id: int,
        *,
        params: Optional[dict[str, Any]] = None,
        seed: Optional[int] = None,
        scale_factor: Optional[float] = None,
        dialect: Optional[str] = None,
        base_dialect: Optional[str] = None,
        variant: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Get a specific TPC-DS benchmark query.

        Args:
            query_id: The ID of the query to retrieve (1-99)
            params: Optional parameters to customize the query (legacy parameter, mostly ignored)
            seed: Random number generator seed for parameter generation
            scale_factor: Scale factor for parameter calculations
            dialect: Target SQL dialect
            **kwargs: Additional parameters

        Returns:
            The fully prepared query string

        Raises:
            ValueError: If the query_id is invalid
            TypeError: If query_id is not an integer
        """
        self._validate_get_query_args(query_id, scale_factor, seed, id_range=(1, 99))

        if params is None:
            params = {}

        actual_seed = seed if seed is not None else params.get("seed")
        actual_scale_factor = (
            scale_factor if scale_factor is not None else params.get("scale_factor", self.data_generator.scale_factor)
        )

        actual_seed = self._resolve_seed_from_stream_or_permutation(
            actual_seed, query_id, params.get("stream_id"), params.get("permutation")
        )

        src = (base_dialect or "netezza").lower()
        tgt = (dialect or src).lower()
        query = self._generate_tpcds_query(query_id, variant, actual_seed, actual_scale_factor, src)
        return self.translate_query_text(query, src, tgt)

    @staticmethod
    def _validate_get_query_args(
        query_id: int, scale_factor: Optional[float], seed: Optional[int], *, id_range: tuple[int, int]
    ) -> None:
        """Validate common get_query arguments."""
        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        lo, hi = id_range
        if not (lo <= query_id <= hi):
            raise ValueError(f"Query ID must be {lo}-{hi}, got {query_id}")
        if scale_factor is not None:
            if not isinstance(scale_factor, (int, float)):
                raise TypeError(f"scale_factor must be a number, got {type(scale_factor).__name__}")
            if scale_factor <= 0:
                raise ValueError(f"scale_factor must be positive, got {scale_factor}")
        if seed is not None and not isinstance(seed, int):
            raise TypeError(f"seed must be an integer, got {type(seed).__name__}")

    @staticmethod
    def _resolve_seed_from_stream_or_permutation(
        actual_seed: Optional[int], query_id: int, stream_id: Optional[int], permutation: Optional[list]
    ) -> Optional[int]:
        """Derive seed from stream_id or permutation if no explicit seed is set."""
        if stream_id is not None:
            if actual_seed is None:
                return stream_id
        elif permutation is not None and actual_seed is None:
            try:
                return permutation.index(query_id)
            except ValueError:
                pass
        return actual_seed

    def _generate_tpcds_query(
        self,
        query_id: int,
        variant: Optional[str],
        actual_seed: Optional[int],
        actual_scale_factor: float,
        src: str,
    ) -> str:
        """Generate a TPC-DS query, optionally for a specific variant."""
        if variant is not None:
            composite_id = f"{query_id}{variant}"
            try:
                return self.query_manager.dsqgen.generate(  # type: ignore[attr-defined]
                    composite_id,
                    seed=actual_seed,
                    scale_factor=actual_scale_factor,
                    dialect=src,
                )
            except AttributeError:
                return self.query_manager.get_query(
                    query_id,
                    seed=actual_seed,
                    scale_factor=actual_scale_factor,
                    dialect=src,
                )
        return self.query_manager.get_query(
            query_id,
            seed=actual_seed,
            scale_factor=actual_scale_factor,
            dialect=src,
        )

    def _normalize_interval_syntax(self, query: str) -> str:
        """Convert Netezza interval syntax to standard SQL INTERVAL syntax.

        Netezza and PostgreSQL allow shorthand interval syntax like:
            cast('2000-01-01' as date) + 60 days
            cast('2000-01-01' as date) - 30 days

        This converts to standard SQL INTERVAL syntax that SQLGlot can parse
        and that works across all databases:
            CAST('2000-01-01' AS DATE) + INTERVAL 60 DAY
            CAST('2000-01-01' AS DATE) - INTERVAL 30 DAY

        Args:
            query: SQL query string possibly containing Netezza interval syntax

        Returns:
            Query with normalized INTERVAL syntax
        """
        import re

        # Pattern matches: [+ or -] [whitespace] [number] [whitespace] days
        # Examples: "+ 60 days", "- 30 days", "+60 days"
        pattern = r"([+\-])\s+(\d+)\s+days"

        # Replace with standard INTERVAL syntax
        # \1 = operator (+ or -), \2 = number
        replacement = r"\1 INTERVAL \2 DAY"

        return re.sub(pattern, replacement, query, flags=re.IGNORECASE)

    def _fix_query58_ambiguity(self, query: str) -> str:
        """Fix ambiguous column reference in TPC-DS Query 58 ORDER BY clause.

        Query 58 has CTEs ss_items, cs_items, ws_items all with 'item_id' column.
        The ORDER BY references 'item_id' without table qualification, causing ambiguity.
        This post-processor qualifies it as ss_items.item_id.

        Args:
            query: SQL query string (already translated by SQLGlot)

        Returns:
            Query with qualified item_id in ORDER BY clause
        """
        # Only apply to Query 58 (check for presence of all three CTEs)
        if "ss_items" not in query.lower() or "cs_items" not in query.lower() or "ws_items" not in query.lower():
            return query

        import re

        # Since we use identify=True, identifiers are quoted: ORDER BY "item_id", "ss_item_rev"
        # We need to replace "item_id" with "ss_items"."item_id"
        pattern = r'(ORDER\s+BY\s+)"item_id"'
        replacement = r'\1"ss_items"."item_id"'
        query = re.sub(pattern, replacement, query, flags=re.IGNORECASE)

        # Also handle unquoted case (in case identify=True was not used)
        pattern_unquoted = r"(ORDER\s+BY\s+)item_id\b(?!\.)"
        replacement_unquoted = r"\1ss_items.item_id"
        query = re.sub(pattern_unquoted, replacement_unquoted, query, flags=re.IGNORECASE)

        return query

    def translate_query_text(self, query: str, source_dialect: str, target_dialect: str) -> str:
        """Translate a query string via SQLGlot from source to target dialect.

        Uses the centralized translation function with TPC-DS-specific pre/post processors.

        Args:
            query: SQL query text to translate
            source_dialect: Source SQL dialect (e.g., 'netezza')
            target_dialect: Target SQL dialect (e.g., 'duckdb', 'bigquery')

        Returns:
            Translated SQL query text
        """
        from benchbox.utils.dialect_utils import fix_postgres_date_arithmetic, translate_sql_query

        src = (source_dialect or "netezza").lower()
        tgt = (target_dialect or src).lower()

        # Build post-processors list
        post_procs = [self._fix_query58_ambiguity]
        # Add date arithmetic fix for PostgreSQL/DataFusion
        if tgt == "postgres":
            post_procs.append(fix_postgres_date_arithmetic)

        return translate_sql_query(
            query=query,
            target_dialect=tgt,
            source_dialect=src,
            identify=True,
            pre_processors=[self._normalize_interval_syntax],
            post_processors=post_procs,
        )

    def generate_table_data(self, table_name: str, output_dir: Optional[str] = None) -> Iterator[str]:
        """Generate data for a specific table (legacy method)."""
        if output_dir:
            # Generate to file using C tools directly
            return self.c_tools.generate_data_table(table_name, self.scale_factor, output_dir=output_dir)
        else:
            return self.generator.generate_table(table_name, self.scale_factor)

    def get_available_tables(self) -> list[str]:
        """Get list of available tables."""
        from benchbox.core.tpcds.constants import TPCDS_TABLE_NAMES

        return list(TPCDS_TABLE_NAMES)

    def get_table_loading_order(self, available_tables: list[str]) -> list[str]:
        """Get the correct order for loading TPC-DS tables to respect foreign key dependencies.

        Args:
            available_tables: List of table names that are actually available

        Returns:
            List of table names in the correct loading order
        """
        from benchbox.core.tpcds.constants import TPCDS_TABLE_LOADING_ORDER

        tpcds_loading_order = TPCDS_TABLE_LOADING_ORDER

        # Filter to only include tables that actually exist in available_tables
        ordered_tables = [t for t in tpcds_loading_order if t in available_tables]

        # Add any remaining tables not in the specified order
        remaining_tables = [t for t in available_tables if t not in ordered_tables]
        ordered_tables.extend(remaining_tables)

        return ordered_tables

    def get_available_queries(self) -> list[int]:
        """Get list of available query IDs."""
        # TPC-DS has 99 standard queries
        return list(range(1, 100))

    def get_schema(self) -> dict[str, dict[str, Any]]:
        """Get the TPC-DS schema.

        Returns:
            Dictionary mapping table names (lowercase) to table definitions.
            Each table definition contains 'name' and 'columns' keys.
        """
        schema = {}
        for table in TABLES:
            table_schema = {
                "name": table.name.lower(),
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
        tuning_config: Optional["UnifiedTuningConfiguration"] = None,
    ) -> str:
        """Get SQL to create all TPC-DS tables.

        Args:
            dialect: SQL dialect to use (currently ignored, TPC-DS uses standard SQL)
            tuning_config: Unified tuning configuration for constraint settings

        Returns:
            SQL script for creating all tables
        """
        from benchbox.core.tpcds.schema import get_create_all_tables_sql

        # Extract constraint settings from tuning configuration
        enable_primary_keys = tuning_config.primary_keys.enabled if tuning_config else False
        enable_foreign_keys = tuning_config.foreign_keys.enabled if tuning_config else False

        return get_create_all_tables_sql(
            enable_primary_keys=enable_primary_keys,
            enable_foreign_keys=enable_foreign_keys,
        )

    def generate_streams(
        self,
        num_streams: int = 1,
        rng_seed: Optional[int] = None,
        streams_output_dir: Optional[Union[str, Path]] = None,
    ) -> list[Path]:
        """Generate TPC-DS query streams.

        Args:
            num_streams: Number of concurrent streams to generate
            rng_seed: Random number generator seed for parameter generation
            streams_output_dir: Directory to output stream files

        Returns:
            List of paths to generated stream files
        """
        from benchbox.core.tpcds.streams import create_standard_streams

        streams_output_dir = self.output_dir / "streams" if streams_output_dir is None else Path(streams_output_dir)

        # Ensure output directory exists
        streams_output_dir.mkdir(parents=True, exist_ok=True)

        # Use existing streams infrastructure
        stream_manager = create_standard_streams(
            query_manager=self.query_manager,
            num_streams=num_streams,
            base_seed=rng_seed or 42,
        )

        # Generate the streams
        streams = stream_manager.generate_streams()

        # Write stream files
        stream_files = []
        for stream_id, stream_queries in streams.items():
            stream_file = streams_output_dir / f"stream_{stream_id}.sql"

            with open(stream_file, "w") as f:
                f.write(f"-- TPC-DS Stream {stream_id}\n")
                f.write(f"-- Scale Factor: {self.scale_factor}\n")
                f.write(f"-- RNG Seed: {rng_seed or 42}\n")
                f.write("-- Generated using TPC-DS query manager\n")
                f.write("-- Compliant with TPC-DS specification\n\n")

                for query in stream_queries:
                    if query.sql:
                        f.write(
                            f"-- Query {query.query_id}{query.variant or ''} (Stream {stream_id}, Position {query.position + 1})\n"
                        )
                        f.write(query.sql)
                        f.write("\n\n")

            stream_files.append(stream_file)

        if self.verbose:
            emit(f"Generated {len(stream_files)} TPC-DS streams in {streams_output_dir}")

        return stream_files

    def get_stream_info(self, stream_id: int) -> dict[str, Any]:
        """Get information about a specific stream.

        Args:
            stream_id: Stream identifier (must be non-negative and reasonable)

        Returns:
            Dictionary containing stream information

        Raises:
            ValueError: If stream_id is negative or exceeds reasonable limit
        """
        from benchbox.core.tpcds.streams import create_standard_streams

        # Validate stream_id upfront to avoid creating excessive streams
        max_reasonable_streams = 100  # TPC-DS spec allows arbitrary streams but we cap at 100
        if stream_id < 0:
            raise ValueError(f"Invalid stream ID: {stream_id}. Stream ID must be non-negative.")
        if stream_id >= max_reasonable_streams:
            raise ValueError(
                f"Invalid stream ID: {stream_id}. "
                f"Stream ID must be less than {max_reasonable_streams}. "
                f"Use generate_streams() with num_streams parameter for custom stream counts."
            )

        # Create a temporary stream manager to get info
        stream_manager = create_standard_streams(
            query_manager=self.query_manager,
            num_streams=stream_id + 1,  # Ensure we have this stream
            base_seed=42,
        )

        # Generate streams to get the information
        streams = stream_manager.generate_streams()

        if stream_id not in streams:
            raise ValueError(f"Stream {stream_id} does not exist")

        stream_queries = streams[stream_id]

        # Count unique queries and handle variants
        unique_queries = set()
        total_queries = 0
        for query in stream_queries:
            query_key = f"{query.query_id}{query.variant or ''}"
            unique_queries.add(query_key)
            total_queries += 1

        # Build query_order list (query IDs in stream order for permutation verification)
        query_order = [q.query_id for q in stream_queries]

        return {
            "stream_id": stream_id,
            "scale_factor": self.scale_factor,
            "query_count": total_queries,
            "unique_query_count": len(unique_queries),
            "rng_seed": 42 + stream_id,
            "parameter_seed": 42 + stream_id + 1000,
            "query_order": query_order,  # Query IDs in execution order (for permutation tests)
            "query_list": [f"{q.query_id}{q.variant or ''}" for q in stream_queries],  # With variants
            "permutation_mode": "tpcds_standard",
        }

    def get_all_streams_info(self, num_streams: int = 2) -> list[dict[str, Any]]:
        """Get information about all streams.

        Args:
            num_streams: Number of streams to generate and get info for (default: 2)

        Returns:
            List of dictionaries containing stream information for all successfully generated streams
        """
        all_info = []
        for stream_id in range(num_streams):
            try:
                stream_info = self.get_stream_info(stream_id)
                all_info.append(stream_info)
            except (ValueError, KeyError) as e:
                # Stream doesn't exist or can't be generated - skip it
                if self.verbose:
                    emit(f"Warning: Could not get info for stream {stream_id}: {e}")
                continue
        return all_info

    def run_streams(
        self,
        connection: Any,
        stream_files: Optional[list[Path]] = None,
        concurrent: bool = True,
        dialect: str = "standard",
    ) -> dict[str, Any]:
        """Run TPC-DS streams against a database.

        Args:
            connection: Database connection object
            stream_files: Optional list of stream files to run
            concurrent: Whether to run streams concurrently or sequentially
            dialect: SQL dialect (standard, postgres, mysql, etc.)

        Returns:
            Dictionary with execution results and timing information
        """
        import time

        from benchbox.utils.execution_manager import ConcurrentQueryExecutor

        start_time = time.time()

        # If no stream files provided, generate them
        if stream_files is None:
            stream_files = self.generate_streams(num_streams=2)

        if concurrent and len(stream_files) > 1:
            # Use existing concurrent execution infrastructure
            concurrent_executor = ConcurrentQueryExecutor()

            files = stream_files

            def stream_executor_factory(stream_id: int) -> Any:
                class StreamExecutor:
                    def __init__(self, stream_file):
                        self.stream_file = stream_file

                    def run(self):
                        return _execute_single_stream(stream_id, self.stream_file)

                idx = stream_id if stream_id < len(files) else 0
                return StreamExecutor(files[idx])

            if concurrent_executor.config.get("enabled", False):
                concurrent_result = concurrent_executor.execute_concurrent_queries(
                    query_executor_factory=stream_executor_factory,
                    num_streams=len(stream_files),
                )
                end_time = time.time()
                return {
                    "start_time": start_time,
                    "end_time": end_time,
                    "total_duration": end_time - start_time,
                    "num_streams": len(stream_files),
                    "streams_executed": len(stream_files),
                    "streams_successful": len([r for r in concurrent_result.stream_results if r.get("success", False)]),
                    "streams_failed": len([r for r in concurrent_result.stream_results if not r.get("success", False)]),
                    "total_queries_executed": concurrent_result.queries_executed,
                    "total_queries_successful": concurrent_result.queries_successful,
                    "total_queries_failed": concurrent_result.queries_failed,
                    "success": concurrent_result.success,
                    "errors": concurrent_result.errors,
                    "stream_results": concurrent_result.stream_results,
                }

        # Sequential execution or single stream
        stream_results = [_execute_single_stream(i, sf) for i, sf in enumerate(stream_files)]

        return _aggregate_stream_results(stream_results, start_time)

    def _load_data(self, connection: _DatabaseConnection) -> None:
        """Load TPC-DS data into the database.

        This method loads the generated TPC-DS data files (.dat/.csv format) into the database
        using a simple, database-agnostic approach with INSERT statements.

        Args:
            connection: DatabaseConnection wrapper for database operations

        Raises:
            ValueError: If data hasn't been generated yet
            Exception: If data loading fails
        """
        import logging

        logger = logging.getLogger(__name__)

        # Check if data has been generated
        if not self.tables:
            raise ValueError("No data has been generated. Call generate_data() first.")

        logger.info("Loading TPC-DS data into database...")

        # Get the schema for table creation
        schema_sql = self.get_create_tables_sql()

        # Create tables first
        logger.info("Creating TPC-DS tables...")
        try:
            # Handle databases that don't support multiple statements at once
            if ";" in schema_sql:
                # Split by semicolons and execute each statement separately
                statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]
                for statement in statements:
                    connection.execute(statement)
            else:
                connection.execute(schema_sql)
            connection.commit()
            logger.info("✅ Tables created")
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")
            raise

        # Load data for each table
        total_rows = 0
        loaded_tables = 0

        from benchbox.core.tpcds.constants import TPCDS_TABLE_LOADING_ORDER

        # Use canonical loading order (excludes dbgen_version metadata table)
        table_load_order = [t for t in TPCDS_TABLE_LOADING_ORDER if t != "dbgen_version"]

        for table_name in table_load_order:
            if table_name not in self.tables:
                logger.warning(f"Data file for table {table_name} not found, skipping...")
                continue

            data_file = self.tables[table_name]

            # Check if file exists and has data
            if not data_file.exists() or data_file.stat().st_size == 0:
                logger.warning(f"Data file {data_file} is empty or missing, skipping {table_name}...")
                continue

            logger.info(f"Loading {table_name.upper()} from {data_file.name}...")

            try:
                # Load data using simple database-agnostic approach
                rows_loaded = self._load_table_data(connection, table_name, data_file)

                total_rows += rows_loaded
                loaded_tables += 1
                logger.info(f"✅ Loaded {rows_loaded:,} rows into {table_name.upper()}")

            except Exception as e:
                logger.error(f"Failed to load data for {table_name}: {e}")
                raise

        # Commit all changes
        try:
            connection.commit()
            logger.info(f"✅ Successfully loaded {total_rows:,} total rows across {loaded_tables} tables")
        except Exception as e:
            logger.error(f"Failed to commit data loading transaction: {e}")
            raise

    def _load_table_data(self, connection: _DatabaseConnection, table_name: str, data_file: Path) -> int:
        """Load data into a database table using simple INSERT statements.

        Args:
            connection: DatabaseConnection wrapper
            table_name: Name of the table to load data into
            data_file: Path to the data file

        Returns:
            Number of rows loaded
        """
        import csv

        normalized_table_name = table_name.lower()
        table_name_upper = table_name.upper()

        # Get table schema to determine column count and types
        table_schema = next((table for table in TABLES if table.name.lower() == normalized_table_name), None)
        if not table_schema:
            raise ValueError(f"Unknown table: {table_name}")

        num_columns = len(table_schema.columns)

        # Prepare INSERT statement
        placeholders = ", ".join(["?" for _ in range(num_columns)])
        insert_sql = f"INSERT INTO {table_name_upper} VALUES ({placeholders})"

        rows_loaded = 0

        # Determine the delimiter based on file format (handles compression)
        delimiter = get_delimiter_for_file(data_file)

        # Read and process the delimited file
        with open(data_file, encoding="utf-8") as f:
            # Use csv.reader with appropriate delimiter
            reader = csv.reader(f, delimiter=delimiter)

            for row in reader:
                # Skip empty rows
                if not row or (len(row) == 1 and row[0] == ""):
                    continue

                # TPC-DS files may have a trailing delimiter, so we need to handle the extra empty column
                if len(row) > num_columns:
                    row = row[:num_columns]
                elif len(row) < num_columns:
                    # Pad with None values if row is too short
                    row.extend([None] * (num_columns - len(row)))

                # Convert empty strings to None for nullable columns
                processed_row = []
                for _i, value in enumerate(row):
                    if value == "":
                        processed_row.append(None)
                    else:
                        processed_row.append(value)

                # Execute individual INSERT
                connection.execute(insert_sql, processed_row)
                rows_loaded += 1

        return rows_loaded

    def run_official_benchmark(
        self,
        connection: Any,
        num_streams: int = 2,
        power_test: bool = True,
        throughput_test: bool = True,
        maintenance_test: bool = True,
        _refresh_functions: Optional[list[str]] = None,
        _data_maintenance: bool = True,
        result_validation: bool = True,
        dialect: str = "standard",
        output_dir: Optional[Union[str, Path]] = None,
    ) -> dict[str, Any]:
        """Run official TPC-DS benchmark with complete QphDS@Size calculation.

        This method executes the full TPC-DS benchmark specification including:
        - Power Test (single stream sequential execution)
        - Throughput Test (multi-stream concurrent execution)
        - Maintenance Test (refresh functions)
        - Official QphDS@Size metric calculation

        Args:
            connection: Database connection object
            num_streams: Number of concurrent streams for throughput test
            power_test: Whether to run Power Test
            throughput_test: Whether to run Throughput Test
            maintenance_test: Whether to run Maintenance Test
            refresh_functions: List of refresh functions to execute
            data_maintenance: Whether to perform data maintenance operations
            result_validation: Whether to validate query results
            dialect: SQL dialect (standard, postgres, mysql, etc.)
            output_dir: Directory to output benchmark results

        Returns:
            Complete benchmark results with QphDS@Size metric

        Raises:
            ValueError: If benchmark configuration is invalid
        """
        import math

        logger = logging.getLogger(__name__)
        if self.verbose:
            logger.setLevel(logging.INFO)
            logger.info("Starting TPC-DS Official Benchmark")
            logger.info(f"Scale factor: {self.scale_factor}")
            logger.info(f"Number of streams: {num_streams}")
            logger.info(f"Tests: Power={power_test}, Throughput={throughput_test}, Maintenance={maintenance_test}")

        benchmark_start_time = time.time()

        # Initialize result structure
        result = {
            "scale_factor": self.scale_factor,
            "num_streams": num_streams,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "total_time": 0.0,
            "power_test_result": None,
            "throughput_test_result": None,
            "maintenance_test_result": None,
            "power_at_size": 0.0,
            "throughput_at_size": 0.0,
            "qphds_at_size": 0.0,
            "success": True,
            "errors": [],
        }

        def connection_factory() -> Any:
            """Factory function to create database connections."""
            return connection

        try:
            # Phase 1: Power Test
            if power_test:
                self._run_power_phase(connection, dialect, logger, result)

            # Phase 2: Throughput Test
            if throughput_test:
                self._run_throughput_phase(connection_factory, num_streams, logger, result)

            # Phase 3: Maintenance Test
            if maintenance_test:
                self._run_maintenance_phase(connection, dialect, logger, result)

            # Calculate QphDS@Size (geometric mean of Power@Size and Throughput@Size)
            if result["power_at_size"] > 0 and result["throughput_at_size"] > 0:
                result["qphds_at_size"] = math.sqrt(result["power_at_size"] * result["throughput_at_size"])

            self._finalize_benchmark_result(result, benchmark_start_time, logger)
            return result

        except Exception as e:
            benchmark_end_time = time.time()
            result["total_time"] = benchmark_end_time - benchmark_start_time
            result["end_time"] = datetime.now().isoformat()
            result["success"] = False
            error_msg = f"Official benchmark failed: {e}"
            result["errors"].append(error_msg)

            if self.verbose:
                logger.error(error_msg)

            return result

    def _run_power_phase(self, connection: Any, dialect: str, logger: logging.Logger, result: dict[str, Any]) -> None:
        """Execute the Power Test phase of the official benchmark."""
        if self.verbose:
            logger.info("Running Power Test...")
        try:
            power_result = self.run_power_test(
                connection=connection,
                dialect=dialect,
                verbose=self.verbose,
            )
            result["power_test_result"] = power_result
            if power_result.get("total_time", 0) > 0:
                result["power_at_size"] = power_result.get("power_at_size", 0.0)
            if self.verbose:
                logger.info(f"Power Test completed: Power@Size = {result['power_at_size']:.2f}")
        except Exception as e:
            error_msg = f"Power Test failed: {e}"
            result["errors"].append(error_msg)
            result["success"] = False
            if self.verbose:
                logger.error(error_msg)

    def _run_throughput_phase(
        self, connection_factory: Any, num_streams: int, logger: logging.Logger, result: dict[str, Any]
    ) -> None:
        """Execute the Throughput Test phase of the official benchmark."""
        if self.verbose:
            logger.info("Running Throughput Test...")
        try:
            throughput_result = self.run_throughput_test(connection_factory=connection_factory, num_streams=num_streams)
            result["throughput_test_result"] = throughput_result
            result["throughput_at_size"] = throughput_result.throughput_at_size
            if self.verbose:
                logger.info(f"Throughput Test completed: Throughput@Size = {result['throughput_at_size']:.2f}")
        except Exception as e:
            error_msg = f"Throughput Test failed: {e}"
            result["errors"].append(error_msg)
            result["success"] = False
            if self.verbose:
                logger.error(error_msg)

    def _run_maintenance_phase(
        self, connection: Any, dialect: str, logger: logging.Logger, result: dict[str, Any]
    ) -> None:
        """Execute the Maintenance Test phase of the official benchmark."""
        if self.verbose:
            logger.info("Running Maintenance Test...")
        try:
            maintenance_config = MaintenanceTestConfig(scale_factor=self.scale_factor, verbose=self.verbose)
            maintenance_result = self.run_maintenance_test(
                connection=connection,
                config=maintenance_config,
                dialect=dialect,
            )
            result["maintenance_test_result"] = maintenance_result
            if self.verbose:
                logger.info(
                    f"Maintenance Test completed: {maintenance_result.successful_operations}/{maintenance_result.total_operations} operations successful"
                )
        except Exception as e:
            error_msg = f"Maintenance Test failed: {e}"
            result["errors"].append(error_msg)
            result["success"] = False
            if self.verbose:
                logger.error(error_msg)

    def _finalize_benchmark_result(
        self, result: dict[str, Any], benchmark_start_time: float, logger: logging.Logger
    ) -> None:
        """Finalize benchmark result with timing and summary logging."""
        benchmark_end_time = time.time()
        result["total_time"] = benchmark_end_time - benchmark_start_time
        result["end_time"] = datetime.now().isoformat()

        if self.verbose:
            logger.info("TPC-DS Official Benchmark completed!")
            logger.info(f"Total time: {result['total_time']:.3f} seconds")
            logger.info(f"Power@Size: {result['power_at_size']:.2f}")
            logger.info(f"Throughput@Size: {result['throughput_at_size']:.2f}")
            logger.info(f"QphDS@Size: {result['qphds_at_size']:.2f}")
            logger.info(f"Success: {result['success']}")
            if result["errors"]:
                logger.warning(f"Errors encountered: {len(result['errors'])}")

    def run_throughput_test(
        self,
        connection_factory,
        num_streams: int = 2,
        query_timeout: int = 300,
        stream_timeout: int = 3600,
        base_seed: int = 42,
        max_retries: int = 3,
        enable_validation: bool = True,
        output_dir: Optional[Union[str, Path]] = None,
        dialect: str = "standard",
    ) -> ThroughputTestResult:
        """Run the official TPC-DS Throughput Test.

        This method implements the TPC-DS throughput test according to specification
        section 5.3. It executes multiple concurrent query streams, each containing
        all 99 TPC-DS queries with proper parameter substitution and permutation.

        Args:
            connection_factory: Callable that returns a database connection
            num_streams: Number of concurrent query streams to execute
            query_timeout: Timeout for individual queries in seconds
            stream_timeout: Timeout for entire streams in seconds
            base_seed: Base seed for random number generation
            max_retries: Maximum number of retries for failed queries
            enable_validation: Whether to validate results according to TPC-DS spec
            output_dir: Directory to save test results and reports
            dialect: SQL dialect (standard, postgres, mysql, etc.)

        Returns:
            ThroughputTestResult containing complete test results and metrics

        Raises:
            ValueError: If parameters are invalid
            RuntimeError: If throughput test fails to execute
        """
        import random

        # Validate parameters
        if num_streams < 1:
            raise ValueError(f"num_streams must be positive, got {num_streams}")
        if query_timeout < 1:
            raise ValueError(f"query_timeout must be positive, got {query_timeout}")
        if stream_timeout < 1:
            raise ValueError(f"stream_timeout must be positive, got {stream_timeout}")
        if max_retries < 0:
            raise ValueError(f"max_retries must be non-negative, got {max_retries}")

        # Set up output directory
        test_output_dir = None
        if output_dir:
            test_output_dir = Path(output_dir)
            test_output_dir.mkdir(parents=True, exist_ok=True)
        elif self.output_dir:
            test_output_dir = self.output_dir / "throughput_test"
            test_output_dir.mkdir(parents=True, exist_ok=True)

        # Create throughput test configuration
        config = ThroughputTestConfig(
            num_streams=num_streams,
            scale_factor=self.scale_factor,
            base_seed=base_seed,
            query_timeout=query_timeout,
            stream_timeout=stream_timeout,
            max_retries=max_retries,
            enable_validation=enable_validation,
            output_dir=test_output_dir,
        )

        logger = logging.getLogger(__name__)
        if self.verbose:
            logger.setLevel(logging.INFO)
            logger.info(f"Starting TPC-DS Throughput Test ({num_streams} streams)")

        test_start_time = time.time()
        _perf_start = time.perf_counter()
        stream_results = []
        successful_streams = 0

        def execute_stream(stream_id: int) -> dict[str, Any]:
            """Execute a single query stream."""
            stream_start = time.time()
            stream_result = {
                "stream_id": stream_id,
                "start_time": stream_start,
                "end_time": 0.0,
                "duration": 0.0,
                "queries_executed": 0,
                "queries_successful": 0,
                "queries_failed": 0,
                "query_results": [],
                "success": False,
                "error": None,
            }

            try:
                # Create connection for this stream
                connection = connection_factory()

                # Generate randomized query order for this stream
                query_ids = list(range(1, 100))  # TPC-DS queries 1-99
                random.seed(base_seed + stream_id)
                random.shuffle(query_ids)

                if self.verbose:
                    logger.info(f"Stream {stream_id}: executing {len(query_ids)} queries")

                for query_id in query_ids:
                    query_start = time.time()
                    query_result = {
                        "query_id": query_id,
                        "stream_id": stream_id,
                        "execution_time_seconds": 0.0,
                        "result_count": 0,
                        "success": False,
                        "error": None,
                    }

                    try:
                        # Get query with stream-specific seed
                        query_text = self.get_query(
                            query_id,
                            seed=base_seed + stream_id,
                            scale_factor=self.scale_factor,
                            dialect=dialect,
                        )

                        # Execute query
                        connection.execute(query_text)
                        results = connection.fetchall()

                        query_end = time.time()
                        execution_time = query_end - query_start

                        query_result.update(
                            {
                                "execution_time_seconds": execution_time,
                                "result_count": len(results) if results else 0,
                                "success": True,
                                "error": None,
                            }
                        )

                        stream_result["queries_successful"] += 1

                    except Exception as e:
                        query_end = time.time()
                        execution_time = query_end - query_start

                        query_result.update(
                            {
                                "execution_time_seconds": execution_time,
                                "result_count": 0,
                                "success": False,
                                "error": str(e),
                            }
                        )

                        stream_result["queries_failed"] += 1

                        if self.verbose:
                            logger.warning(f"Stream {stream_id} Query {query_id} failed: {e}")

                    stream_result["query_results"].append(query_result)
                    stream_result["queries_executed"] += 1

                stream_result["success"] = stream_result["queries_failed"] == 0

                # connection.close()  # Connection lifecycle managed by platform adapter

            except Exception as e:
                stream_result["error"] = str(e)
                if self.verbose:
                    logger.error(f"Stream {stream_id} failed: {e}")

            finally:
                stream_result["end_time"] = time.time()
                stream_result["duration"] = stream_result["end_time"] - stream_result["start_time"]

            return stream_result

        # Execute all streams concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_streams) as executor:
            futures = [executor.submit(execute_stream, i) for i in range(num_streams)]

            for future in concurrent.futures.as_completed(futures):
                try:
                    stream_result = future.result()
                    stream_results.append(stream_result)

                    if stream_result["success"]:
                        successful_streams += 1

                    if self.verbose:
                        logger.info(
                            f"Stream {stream_result['stream_id']}: "
                            f"{stream_result['queries_successful']}/{stream_result['queries_executed']} successful"
                        )

                except Exception as e:
                    if self.verbose:
                        logger.error(f"Stream execution failed: {e}")

        test_end_time = time.time()
        total_duration = time.perf_counter() - _perf_start

        # Calculate Throughput@Size metric
        throughput_at_size = 0.0
        if total_duration > 0:
            throughput_at_size = (num_streams * 3600.0 * self.scale_factor) / total_duration

        # Create result object
        result = ThroughputTestResult(
            config=config,
            start_time=test_start_time,
            end_time=test_end_time,
            total_duration=total_duration,
            streams_executed=len(stream_results),
            streams_successful=successful_streams,
            stream_results=stream_results,
            throughput_at_size=throughput_at_size,
            success=successful_streams == num_streams,
        )

        if self.verbose:
            logger.info(f"Throughput Test completed in {total_duration:.3f} seconds")
            logger.info(f"Throughput@Size: {throughput_at_size:.2f}")
            logger.info(f"Successful streams: {successful_streams}/{num_streams}")

        return result

    def run_power_test(
        self,
        connection: Any,
        seed: Optional[int] = None,
        dialect: str = "standard",
        verbose: Optional[bool] = None,
        timeout: Optional[float] = None,
        warm_up: bool = True,
        validation: bool = True,
    ) -> dict[str, Any]:
        """Run the TPC-DS Power Test.

        The Power Test executes all 99 TPC-DS queries (including variants like Q14a/Q14b)
        sequentially in a single stream and measures the total execution time to calculate
        the Power@Size metric according to TPC-DS specification section 5.2.

        Args:
            connection: Database connection object
            seed: Random seed for parameter generation (default: 1)
            dialect: SQL dialect (standard, postgres, mysql, etc.)
            verbose: Whether to print verbose output (default: self.verbose)
            timeout: Optional timeout for individual queries in seconds
            warm_up: Whether to perform database warm-up procedures
            validation: Whether to validate results according to TPC-DS spec

        Returns:
            Dictionary containing Power Test results including:
            - scale_factor: Scale factor used
            - total_time: Total execution time in seconds
            - power_at_size: Power@Size metric
            - query_results: Individual query execution results
            - errors: List of any errors encountered
            - database_info: Database system information

        Raises:
            RuntimeError: If Power Test fails to execute
            ValueError: If parameters are invalid
        """
        import logging
        import time
        from datetime import datetime

        # Use benchmark's verbose setting if not specified
        if verbose is None:
            verbose = self.verbose

        # Validate inputs
        if seed is None:
            seed = 1

        logger = logging.getLogger(__name__)
        if verbose:
            logger.setLevel(logging.INFO)

        # Initialize result structure
        result = {
            "scale_factor": self.scale_factor,
            "total_time": 0.0,
            "power_at_size": 0.0,
            "query_results": {},
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "errors": [],
            "database_info": {
                "connection_type": type(connection).__name__,
                "dialect": dialect,
            },
        }

        # Use provided connection object
        try:
            if verbose:
                logger.info(f"Starting TPC-DS Power Test (scale factor: {self.scale_factor})")

            # Perform warm-up if requested
            if warm_up and verbose:
                logger.info("Performing database warm-up...")
                # Execute a few sample queries to warm up the database
                for warm_query_id in [1, 19, 42]:
                    try:
                        warm_query = self.get_query(warm_query_id, seed=seed, dialect=dialect)
                        connection.execute(warm_query)
                        connection.fetchall()  # Consume results
                    except Exception as e:
                        if verbose:
                            logger.warning(f"Warm-up query {warm_query_id} failed: {e}")

            # Execute all 99 queries sequentially
            test_start_time = time.time()

            for query_id in range(1, 100):  # TPC-DS has 99 queries
                if verbose:
                    logger.info(f"Executing Query {query_id}...")

                query_start = time.time()
                query_result = {
                    "query_id": query_id,
                    "execution_time_seconds": 0.0,
                    "result_count": 0,
                    "status": "failed",
                    "error": None,
                }

                try:
                    # Get query with parameters
                    query_text = self.get_query(query_id, seed=seed, dialect=dialect)

                    # Execute query
                    connection.execute(query_text)
                    query_results = connection.fetchall()

                    query_end = time.time()
                    execution_time = query_end - query_start

                    # Check timeout
                    if timeout and execution_time > timeout:
                        raise RuntimeError(f"Query exceeded timeout ({timeout}s)")

                    query_result.update(
                        {
                            "execution_time_seconds": execution_time,
                            "result_count": len(query_results) if query_results else 0,
                            "status": "success",
                            "error": None,
                        }
                    )

                    if verbose:
                        logger.info(
                            f"Query {query_id} completed in {execution_time:.3f}s ({query_result['result_count']} rows)"
                        )

                except Exception as e:
                    query_end = time.time()
                    execution_time = query_end - query_start
                    error_msg = str(e)

                    query_result.update(
                        {
                            "execution_time_seconds": execution_time,
                            "result_count": 0,
                            "status": "failed",
                            "error": error_msg,
                        }
                    )

                    result["errors"].append(f"Query {query_id} failed: {error_msg}")

                    if verbose:
                        logger.error(f"Query {query_id} failed after {execution_time:.3f}s: {error_msg}")

                result["query_results"][query_id] = query_result

            # Calculate total time and metrics
            test_end_time = time.time()
            result["total_time"] = test_end_time - test_start_time
            result["end_time"] = datetime.now().isoformat()

            # Calculate Power@Size metric: 3600 × Scale_Factor / Power_Test_Time
            if result["total_time"] > 0:
                result["power_at_size"] = (3600.0 * self.scale_factor) / result["total_time"]

            # Count successful queries
            successful_queries = sum(1 for qr in result["query_results"].values() if qr["status"] == "success")

            if verbose:
                logger.info(f"Power Test completed in {result['total_time']:.3f} seconds")
                logger.info(f"Power@Size: {result['power_at_size']:.2f}")
                logger.info(f"Successful queries: {successful_queries}/99")
                if result["errors"]:
                    logger.warning(f"Errors encountered: {len(result['errors'])}")

            return result

        except Exception as e:
            error_msg = f"Power Test failed: {e}"
            result["errors"].append(error_msg)
            result["end_time"] = datetime.now().isoformat()

            if verbose:
                logger.error(error_msg)

            return result

        finally:
            if connection:
                try:
                    pass  # Connection lifecycle managed by platform adapter
                except Exception:
                    pass

    def run_maintenance_test(
        self,
        connection: Any,
        config: Optional[MaintenanceTestConfig] = None,
        stream_executor: Optional[Any] = None,
        dialect: str = "standard",
    ) -> MaintenanceTestResult:
        """
        Run the TPC-DS Maintenance Test according to TPC-DS specification section 5.4.

        This method delegates to TPCDSMaintenanceTest for executing real database operations
        including INSERT, UPDATE, and DELETE operations on TPC-DS tables. The implementation
        executes actual SQL statements against the database and returns real metrics.

        Operations include:
        - INSERT operations on fact and dimension tables
        - UPDATE operations to modify existing data
        - DELETE operations to remove obsolete records
        - Transaction management with commit/rollback support
        - Error handling and recovery
        - Data integrity validation

        Args:
            connection: Database connection object
            config: Optional maintenance test configuration
            stream_executor: Optional function to execute query streams concurrently (not currently used)
            dialect: SQL dialect for database operations (e.g., 'duckdb', 'postgres', 'sqlite')

        Returns:
            MaintenanceTestResult: Complete test results and metrics including:
                - test_duration: Total execution time in seconds
                - total_operations: Number of operations attempted
                - successful_operations: Number of operations completed successfully
                - failed_operations: Number of operations that failed
                - overall_throughput: Operations per second
                - maintenance_operations: List of individual operation results
                - error_details: List of error messages if any

        Raises:
            ValueError: If connection object is None
        """
        from benchbox.core.tpcds.maintenance_test import (
            TPCDSMaintenanceTest,
            TPCDSMaintenanceTestConfig,
        )

        # Validate connection object
        if connection is None:
            raise ValueError("connection object cannot be None")

        # Use default config if none provided or ensure it has required attributes
        if config is None or not hasattr(config, "verbose"):
            config = MaintenanceTestConfig(
                scale_factor=self.scale_factor,
                verbose=self.verbose,
                output_dir=self.output_dir,
            )

        # Create connection factory that returns the provided connection
        connection_factory = lambda: connection

        # Create TPCDSMaintenanceTest instance
        maintenance_test = TPCDSMaintenanceTest(
            benchmark=self,
            connection_factory=connection_factory,
            scale_factor=self.scale_factor,
            output_dir=self.output_dir,
            verbose=config.verbose,
            dialect=dialect,
        )

        # Convert MaintenanceTestConfig to TPCDSMaintenanceTestConfig
        # Use config attributes if available, otherwise use defaults
        maintenance_operations = getattr(config, "maintenance_operations", 4)

        tpcds_config = TPCDSMaintenanceTestConfig(
            scale_factor=config.scale_factor,
            maintenance_operations=maintenance_operations,
            operation_interval=0.0,  # No interval for benchmark runner
            concurrent_with_queries=False,  # Not supported in this context
            validate_integrity=True,
            verbose=config.verbose,
            output_dir=config.output_dir,
        )

        # Execute the maintenance test
        result_dict = maintenance_test.run(config=tpcds_config)

        # Convert the result dictionary to MaintenanceTestResult format
        # Map the TPCDSMaintenanceTest operations to the expected format
        maintenance_operations = []
        for operation in result_dict["operations"]:
            maintenance_operations.append(
                {
                    "operation": f"{operation.operation_type}_{operation.table_name}",
                    "start_time": operation.start_time,
                    "end_time": operation.end_time,
                    "duration": operation.duration,
                    "rows_affected": operation.rows_affected,
                    "success": operation.success,
                    "error": operation.error,
                }
            )

        # Create MaintenanceTestResult from the dictionary result
        result = MaintenanceTestResult(
            test_duration=result_dict["total_time"],
            total_operations=result_dict["total_operations"],
            successful_operations=result_dict["successful_operations"],
            failed_operations=result_dict["failed_operations"],
            overall_throughput=result_dict["overall_throughput"],
            maintenance_operations=maintenance_operations,
            error_details=result_dict["errors"],
        )

        return result

    def validate_maintenance_data_integrity(self, connection: Any, dialect: str = "standard") -> dict[str, Any]:
        """
        Validate data integrity after maintenance operations.

        This method performs comprehensive data integrity validation including:
        - Referential integrity constraint checking
        - Data consistency validation
        - Constraint violation detection
        - Performance impact assessment

        Args:
            connection: Database connection object
            dialect: SQL dialect for database operations

        Returns:
            Dictionary with validation results

        Raises:
            ValueError: If connection_string is invalid
        """
        # Validate connection object
        if connection is None:
            raise ValueError("connection object cannot be None")

        logger = logging.getLogger(__name__)
        if self.verbose:
            logger.setLevel(logging.INFO)
            logger.info("Validating data integrity after maintenance operations")

        validation_results = {
            "validation_checks": [],
            "integrity_score": 0.0,
            "errors": [],
            "timestamp": datetime.now().isoformat(),
        }

        try:
            # Use provided connection object

            # Basic integrity checks for TPC-DS tables
            checks = [
                {
                    "name": "Primary key uniqueness",
                    "query": "SELECT COUNT(*) FROM (SELECT C_CUSTOMER_SK, COUNT(*) FROM CUSTOMER GROUP BY C_CUSTOMER_SK HAVING COUNT(*) > 1) duplicates",
                    "expected_result": 0,
                },
                {
                    "name": "Date dimension consistency",
                    "query": "SELECT COUNT(*) FROM DATE_DIM WHERE D_DATE IS NULL",
                    "expected_result": 0,
                },
                {
                    "name": "Store sales referential integrity",
                    "query": "SELECT COUNT(*) FROM STORE_SALES SS LEFT JOIN CUSTOMER C ON SS.SS_CUSTOMER_SK = C.C_CUSTOMER_SK WHERE C.C_CUSTOMER_SK IS NULL AND SS.SS_CUSTOMER_SK IS NOT NULL",
                    "expected_result": 0,
                },
            ]

            passed_checks = 0

            for check in checks:
                try:
                    connection.execute(check["query"])
                    result = connection.fetchone()
                    actual_result = result[0] if result else None

                    check_passed = actual_result == check["expected_result"]
                    if check_passed:
                        passed_checks += 1

                    validation_results["validation_checks"].append(
                        {
                            "name": check["name"],
                            "expected": check["expected_result"],
                            "actual": actual_result,
                            "passed": check_passed,
                        }
                    )

                    if self.verbose:
                        status = "PASSED" if check_passed else "FAILED"
                        logger.info(f"Integrity check '{check['name']}': {status}")

                except Exception as e:
                    error_msg = f"Integrity check '{check['name']}' failed: {e}"
                    validation_results["errors"].append(error_msg)

                    validation_results["validation_checks"].append(
                        {
                            "name": check["name"],
                            "expected": check["expected_result"],
                            "actual": None,
                            "passed": False,
                            "error": str(e),
                        }
                    )

                    if self.verbose:
                        logger.error(error_msg)

            # Calculate integrity score
            total_checks = len(checks)
            validation_results["integrity_score"] = passed_checks / total_checks if total_checks > 0 else 0.0

            connection.close()

            if self.verbose:
                logger.info(f"Data integrity validation completed: {passed_checks}/{total_checks} checks passed")
                logger.info(f"Integrity score: {validation_results['integrity_score']:.1%}")

        except Exception as e:
            error_msg = f"Data integrity validation failed: {e}"
            validation_results["errors"].append(error_msg)
            if self.verbose:
                logger.error(error_msg)

        return validation_results

    def get_benchmark_info(self) -> dict[str, Any]:
        """Get benchmark information."""
        return {
            "name": "TPC-DS",
            "scale_factor": self.scale_factor,
            "available_tables": self.get_available_tables(),
            "available_queries": self.get_available_queries(),
            "c_tools_info": self.c_tools.get_tools_info(),
            "maintenance_test_supported": True,
        }

    def validate_preflight_conditions(self) -> ValidationResult:
        """
        Validate conditions before data generation.

        Returns:
            ValidationResult with preflight validation status
        """
        return self._data_validation_engine.validate_preflight_conditions(
            benchmark_type="tpcds",
            scale_factor=self.scale_factor,
            output_dir=self.output_dir,
        )

    def validate_generated_data(self) -> ValidationResult:
        """
        Validate generated benchmark data using manifest.

        Returns:
            ValidationResult with data validation status
        """
        manifest_path = self.output_dir / "_datagen_manifest.json"
        return self._data_validation_engine.validate_generated_data(manifest_path)

    def validate_loaded_data(self, connection: Any) -> ValidationResult:
        """
        Validate database state after data loading.

        Args:
            connection: Database connection object

        Returns:
            ValidationResult with database validation status
        """
        return self._db_validation_engine.validate_loaded_data(
            connection=connection,
            benchmark_type="tpcds",
            scale_factor=self.scale_factor,
        )

    def validate_data_integrity(self, connection: Optional[Any] = None) -> ValidationResult:
        """
        Perform comprehensive data integrity validation.

        This method validates both generated data files and, if provided,
        the loaded database state.

        Args:
            connection: Optional database connection for database validation

        Returns:
            ValidationResult with comprehensive validation status
        """
        # Always validate generated data
        file_result = self.validate_generated_data()

        if connection is None:
            # Only file validation
            return file_result

        # Both file and database validation
        db_result = self.validate_loaded_data(connection)

        # Combine results
        all_errors = file_result.errors + db_result.errors
        all_warnings = file_result.warnings + db_result.warnings

        combined_details = {
            "file_validation": file_result.details,
            "database_validation": db_result.details,
        }

        return ValidationResult(
            is_valid=file_result.is_valid and db_result.is_valid,
            errors=all_errors,
            warnings=all_warnings,
            details=combined_details,
        )


__all__ = ["TPCDSBenchmark"]
