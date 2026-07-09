"""Polars platform adapter with DataFrame API support.

Provides Polars-specific optimizations for in-memory OLAP workloads
using the native DataFrame API execution.

Note: SQL mode has been removed due to fundamental limitations in Polars'
SQL implementation (no implicit joins, limited subquery support, etc.)
that make it incompatible with standard TPC benchmarks.

Polars is a blazingly fast DataFrame library implemented in Rust and Python.
It provides both lazy and eager execution modes for optimal performance.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, cast

from benchbox.utils.clock import elapsed_seconds, mono_time

try:
    import polars as pl
except ImportError:
    pl = None

from benchbox.platforms.base import DriverIsolationCapability, PlatformAdapter
from benchbox.platforms.base.no_constraint_mixin import NoConstraintEnforcementMixin

logger = logging.getLogger(__name__)


class PolarsDataFrameContext:
    """Context for Polars DataFrame operations.

    This provides a storage mechanism for loaded tables that can be accessed
    by DataFrame queries. SQL execution is not supported.
    """

    def __init__(self, adapter: PolarsAdapter):
        self._adapter = adapter
        self._tables: dict[str, pl.LazyFrame] = {}

    def register_table(self, name: str, df: pl.LazyFrame | pl.DataFrame) -> None:
        """Register a table in the context.

        Args:
            name: Table name
            df: Polars DataFrame or LazyFrame
        """
        # Convert to LazyFrame if needed for lazy execution
        lf = df.lazy() if isinstance(df, pl.DataFrame) else df
        self._tables[name] = lf

    def unregister_table(self, name: str) -> None:
        """Unregister a table from the context."""
        if name in self._tables:
            del self._tables[name]

    def get_table(self, name: str) -> pl.LazyFrame | None:
        """Get a table by name.

        Args:
            name: Table name

        Returns:
            The LazyFrame if found, None otherwise
        """
        return self._tables.get(name)

    def get_tables(self) -> list[str]:
        """Get list of registered tables."""
        return list(self._tables.keys())


class PolarsAdapter(NoConstraintEnforcementMixin, PlatformAdapter):
    """Polars platform adapter with DataFrame API support.

    Executes benchmarks using the native Polars DataFrame API with lazy/eager
    evaluation. SQL mode has been removed due to fundamental limitations in
    Polars' SQL implementation that make it incompatible with TPC benchmarks.

    Polars advantages:
    - Blazingly fast (Rust-based)
    - Memory efficient with lazy execution
    - Excellent parallel execution
    - Native support for many file formats
    """

    plan_capture_phase_eligible = True

    driver_isolation_capability = DriverIsolationCapability.NOT_APPLICABLE
    supports_external_tables = True

    @property
    def platform_name(self) -> str:
        return "Polars"

    def get_target_dialect(self) -> str:
        """Get the target dialect for Polars.

        Note: Polars uses DataFrame API, not SQL. This returns 'dataframe'
        to indicate the platform mode.
        """
        return "dataframe"

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add Polars-specific CLI arguments."""
        polars_group = parser.add_argument_group("Polars Arguments")
        polars_group.add_argument(
            "--polars-execution-mode",
            type=str,
            choices=["lazy", "eager"],
            default="lazy",
            help="Execution mode: lazy (recommended) or eager",
        )
        polars_group.add_argument(
            "--polars-streaming",
            action="store_true",
            default=False,
            help="Enable streaming mode for large datasets",
        )
        polars_group.add_argument(
            "--polars-n-rows",
            type=int,
            default=None,
            help="Limit number of rows to read (for testing)",
        )
        polars_group.add_argument(
            "--polars-working-dir",
            type=str,
            help="Working directory for Polars data files",
        )
        polars_group.add_argument(
            "--polars-rechunk",
            action="store_true",
            default=True,
            help="Rechunk data for better memory layout (default: True)",
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create Polars adapter from unified configuration."""
        from pathlib import Path

        from benchbox.utils.database_naming import generate_database_filename
        from benchbox.utils.scale_factor import format_benchmark_name

        # Extract Polars-specific configuration
        adapter_config = {}

        # Working directory handling
        if config.get("working_dir"):
            adapter_config["working_dir"] = config["working_dir"]
        else:
            from benchbox.utils.path_utils import get_benchmark_runs_datagen_path

            # Use output_dir if provided, otherwise use canonical benchmark_runs/datagen path
            if config.get("output_dir"):
                data_dir = Path(config["output_dir"]) / format_benchmark_name(
                    config["benchmark"], config["scale_factor"]
                )
            else:
                data_dir = get_benchmark_runs_datagen_path(config["benchmark"], config["scale_factor"])

            db_filename = generate_database_filename(
                benchmark_name=config["benchmark"],
                scale_factor=config["scale_factor"],
                platform="polars",
                tuning_config=config.get("tuning_config"),
            )

            # Full path to Polars working directory
            working_dir = data_dir / db_filename
            adapter_config["working_dir"] = str(working_dir)
            working_dir.mkdir(parents=True, exist_ok=True)

        # Execution mode
        adapter_config["execution_mode"] = config.get("execution_mode", "lazy")

        # Streaming mode
        adapter_config["streaming"] = config.get("streaming", False)

        # Row limit (for testing)
        adapter_config["n_rows"] = config.get("n_rows")

        # Rechunking
        adapter_config["rechunk"] = config.get("rechunk", True)

        # Force recreate
        adapter_config["force_recreate"] = config.get("force", False)

        # Pass through other relevant config
        for key in ["tuning_config", "verbose_enabled", "very_verbose"]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

    def __init__(self, **config):
        super().__init__(**config)
        if pl is None:
            raise ImportError("Polars not installed. Install with: pip install polars")

        # Polars configuration
        self.working_dir = Path(config.get("working_dir", "./polars_working"))
        self.execution_mode = config.get("execution_mode", "lazy")
        self.streaming = config.get("streaming", False)
        self.n_rows = config.get("n_rows")
        self.rechunk = config.get("rechunk", True)

        # Schema tracking (populated during create_schema)
        self._table_schemas: dict[str, dict] = {}

        # Create working directory
        self.working_dir.mkdir(parents=True, exist_ok=True)

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get Polars platform information."""
        platform_info = {
            "platform_type": "polars",
            "platform_name": "Polars",
            "connection_mode": "in-memory",
            "configuration": {
                "working_dir": str(self.working_dir),
                "execution_mode": self.execution_mode,
                "streaming": self.streaming,
                "n_rows_limit": self.n_rows,
                "rechunk": self.rechunk,
                "result_cache_enabled": False,
            },
        }

        # Get Polars version
        try:
            platform_info["client_library_version"] = pl.__version__
            platform_info["platform_version"] = pl.__version__
        except AttributeError:
            platform_info["client_library_version"] = None
            platform_info["platform_version"] = None

        return platform_info

    def create_connection(self, **connection_config) -> Any:
        """Create Polars DataFrame context for DataFrame operations."""
        self.log_operation_start("Polars connection")

        # Handle existing database using base class method
        self.handle_existing_database(**connection_config)

        # Configure Polars global settings
        config_applied = []

        # Set string cache for consistent string handling
        pl.enable_string_cache()
        config_applied.append("string_cache=enabled")

        # Configure thread pool size
        n_threads = os.cpu_count() or 4
        config_applied.append(f"threads={n_threads}")

        # Log configuration
        config_applied.append(f"execution_mode={self.execution_mode}")
        if self.streaming:
            config_applied.append("streaming=enabled")

        self.log_very_verbose(f"Polars configuration: {', '.join(config_applied)}")

        # Create DataFrame context
        ctx = PolarsDataFrameContext(self)

        self.log_operation_complete("Polars connection", details=f"Applied: {', '.join(config_applied)}")

        return ctx

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema for Polars execution.

        Note: For Polars, actual table registration happens during load_data().
        This method validates and extracts schema information.
        """
        start_time = mono_time()
        self.log_operation_start("Schema creation", f"benchmark: {benchmark.__class__.__name__}")

        # Get constraint settings from tuning configuration
        enable_primary_keys, enable_foreign_keys = self._get_constraint_configuration()
        self._log_constraint_configuration(enable_primary_keys, enable_foreign_keys)

        # Note: Polars doesn't enforce constraints
        if enable_primary_keys or enable_foreign_keys:
            self.log_verbose(
                "Polars does not enforce PRIMARY KEY or FOREIGN KEY constraints - "
                "schema will be created without constraints"
            )

        # Get structured schema directly from benchmark
        self._table_schemas = self._get_benchmark_schema(benchmark)

        duration = elapsed_seconds(start_time)
        self.log_operation_complete(
            "Schema creation",
            duration,
            f"Schema validated for {len(self._table_schemas)} tables",
        )
        return duration

    def _get_benchmark_schema(self, benchmark) -> dict[str, dict]:
        """Get structured schema directly from benchmark.

        Returns:
            Dict mapping table_name -> {'columns': [...]}
            where each column is {'name': str, 'type': str}
        """
        schemas = {}

        # Try to get schema from benchmark's get_schema() method
        try:
            benchmark_schema = benchmark.get_schema()
        except (AttributeError, TypeError):
            self.log_verbose(
                f"Benchmark {benchmark.__class__.__name__} does not provide get_schema() method, "
                "will rely on schema inference during data loading"
            )
            return {}

        if not benchmark_schema:
            self.log_verbose("Benchmark returned empty schema, will rely on schema inference")
            return {}

        # Convert benchmark schema format to our internal format
        for table_name_key, table_def in benchmark_schema.items():
            table_name = table_name_key.lower()

            columns = []
            if isinstance(table_def, dict) and "columns" in table_def:
                for col in table_def["columns"]:
                    if isinstance(col, dict) and "name" in col:
                        col_type = col.get("type", "VARCHAR")
                        if not isinstance(col_type, str):
                            col_type = "VARCHAR"

                        columns.append(
                            {
                                "name": col["name"],
                                "type": col_type,
                            }
                        )

            if columns:
                schemas[table_name] = {"columns": columns}
                self.log_very_verbose(f"Extracted schema for {table_name}: {len(columns)} columns")

        return schemas

    def load_data(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data into Polars using lazy scanning for optimal memory usage.

        Polars supports two loading strategies:
        1. CSV/TBL mode: Uses scan_csv with lazy evaluation
        2. Parquet mode: Uses scan_parquet for optimal performance
        """
        from benchbox.platforms.base.data_loading import DataSourceResolver

        start_time = mono_time()
        self.log_operation_start("Data loading", f"mode: {self.execution_mode}")

        # Resolve data source
        resolver = DataSourceResolver(
            platform_name=self.platform_name,
            table_mode=self.table_mode,
            platform_config=self.platform_config,
            requested_format=self.requested_table_format,
        )
        data_source = resolver.resolve(benchmark, data_dir)

        if not data_source or not data_source.tables:
            raise ValueError(f"No data files found in {data_dir}")

        table_stats = {}
        per_table_timings = {}

        # Load each table
        for table_name, file_paths in data_source.tables.items():
            table_start = mono_time()

            # Normalize and filter to valid files using base class helper
            valid_files = self._normalize_and_validate_file_paths(file_paths)

            if not valid_files:
                self.log_verbose(f"Skipping {table_name} - no valid data files")
                continue

            # Normalize table name to lowercase
            table_name_lower = table_name.lower()

            # Load the table data, passing any manifest-provided format hint
            format_hint = data_source.table_formats.get(table_name) or data_source.table_formats.get(table_name_lower)
            row_count = self._load_table(connection, table_name_lower, valid_files, data_dir, format_hint=format_hint)

            table_duration = elapsed_seconds(table_start)
            table_stats[table_name_lower] = row_count
            per_table_timings[table_name_lower] = {"total_ms": table_duration * 1000}

            self.log_verbose(f"Loaded table {table_name_lower}: {row_count:,} rows in {table_duration:.2f}s")

        total_duration = elapsed_seconds(start_time)
        total_rows = sum(table_stats.values())

        self.log_operation_complete(
            "Data loading",
            total_duration,
            f"{total_rows:,} rows across {len(table_stats)} tables",
        )

        return table_stats, total_duration, per_table_timings

    def create_external_tables(
        self, benchmark: Any, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Alias external-table mode to Polars' existing lazy scan registration path."""
        return self.load_data(benchmark, connection, data_dir)

    def _detect_file_format(self, file_paths: list[Path]) -> tuple[str, str]:
        """Detect file format and delimiter from file paths.

        This is a wrapper around the shared detect_file_format utility.

        Returns:
            Tuple of (format, delimiter)
        """
        from benchbox.platforms.base.utils import detect_file_format

        format_info = detect_file_format(file_paths)
        # Map format_type to the expected format string
        format_type = "parquet" if format_info.format_type == "parquet" else "csv"
        return format_type, format_info.delimiter

    def _load_table(
        self,
        connection: PolarsDataFrameContext,
        table_name: str,
        file_paths: list[Path],
        data_dir: Path,
        format_hint: str | None = None,
    ) -> int:
        """Load table from data files into Polars.

        Args:
            connection: PolarsDataFrameContext
            table_name: Name of the table
            file_paths: List of file paths to load
            data_dir: Base data directory
            format_hint: Optional format hint from manifest (e.g. "parquet", "csv", "tbl")

        Returns:
            Number of rows loaded
        """
        if format_hint == "parquet":
            format_type, delimiter = "parquet", ","
        elif format_hint == "tbl":
            format_type, delimiter = "csv", "|"
        elif format_hint == "csv":
            format_type, delimiter = "csv", ","
        else:
            format_type, delimiter = self._detect_file_format(file_paths)

        # Get schema information for column names
        schema_info = self._table_schemas.get(table_name, {})
        columns = schema_info.get("columns", [])
        column_names = [col["name"] for col in columns] if columns else None

        self.log_very_verbose(f"Loading {table_name} from {len(file_paths)} file(s), format: {format_type}")

        if format_type == "parquet":
            # Load Parquet files
            lf = self._load_parquet(file_paths)
        else:
            # Load CSV/TBL files
            lf = self._load_csv(file_paths, delimiter, column_names)

        # Register table in context
        connection.register_table(table_name, lf)

        # Count rows (requires materialization)
        row_count = lf.select(pl.len()).collect().item()

        return row_count

    def _load_parquet(self, file_paths: list[Path]) -> pl.LazyFrame:
        """Load Parquet files into LazyFrame."""
        if len(file_paths) == 1:
            return pl.scan_parquet(file_paths[0], rechunk=self.rechunk)

        # Multiple files - use glob or concat
        # Check if files are in the same directory
        parent_dir = file_paths[0].parent
        if all(f.parent == parent_dir for f in file_paths):
            # Use glob pattern
            pattern = str(parent_dir / "*.parquet")
            return pl.scan_parquet(pattern, rechunk=self.rechunk)

        # Different directories - concatenate
        lfs = [pl.scan_parquet(f, rechunk=self.rechunk) for f in file_paths]
        return cast(pl.LazyFrame, pl.concat(lfs))

    def _load_csv(
        self,
        file_paths: list[Path],
        delimiter: str,
        column_names: list[str] | None,
    ) -> pl.LazyFrame:
        """Load CSV/TBL files into LazyFrame.

        Args:
            file_paths: List of file paths
            delimiter: Field delimiter
            column_names: Optional column names from schema

        Returns:
            Polars LazyFrame
        """
        from benchbox.utils.file_format import (
            TRAILING_DUMMY_COLUMN,
            has_trailing_delimiter,
        )

        has_trailing = (
            bool(column_names) and bool(file_paths) and has_trailing_delimiter(file_paths[0], delimiter, column_names)
        )

        # Build scan options
        scan_kwargs: dict[str, Any] = {
            "separator": delimiter,
            "has_header": False,
            "rechunk": self.rechunk,
            "ignore_errors": True,  # Be lenient with malformed data
        }

        # Add row limit if specified
        if self.n_rows:
            scan_kwargs["n_rows"] = self.n_rows

        # Handle column names
        if column_names:
            if has_trailing:
                # Add a dummy column name for the trailing delimiter
                extended_names = column_names + [TRAILING_DUMMY_COLUMN]
                scan_kwargs["new_columns"] = extended_names
            else:
                scan_kwargs["new_columns"] = column_names

        # Load files
        if len(file_paths) == 1:
            lf = pl.scan_csv(file_paths[0], **scan_kwargs)
        else:
            # Multiple files - check if we can use glob
            parent_dir = file_paths[0].parent
            if all(f.parent == parent_dir for f in file_paths):
                # Determine extension pattern
                ext = file_paths[0].suffix
                if ext.isdigit():
                    # Numbered files like .1, .2 - use base pattern
                    base_name = file_paths[0].stem.rsplit(".", 1)[0]
                    pattern = str(parent_dir / f"{base_name}*")
                else:
                    pattern = str(parent_dir / f"*{ext}")
                lf = pl.scan_csv(pattern, **scan_kwargs)
            else:
                # Different directories - concatenate
                lfs = [pl.scan_csv(f, **scan_kwargs) for f in file_paths]
                lf = pl.concat(lfs)

        # Drop trailing column if present
        if has_trailing and column_names:
            lf = lf.drop(TRAILING_DUMMY_COLUMN)

        return cast(pl.LazyFrame, lf)

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply Polars-specific optimizations based on benchmark type."""
        self.log_verbose(f"Polars configured for {benchmark_type} benchmark")
        # Polars optimizations are mostly automatic via the query optimizer

    def execute_query(
        self,
        connection: Any,
        query: str,
        query_id: str,
        benchmark_type: str | None = None,
        scale_factor: float | None = None,
        validate_row_count: bool = True,
        stream_id: int | None = None,
    ) -> dict[str, Any]:
        """Execute query - SQL mode not supported.

        Polars SQL mode has been removed due to fundamental limitations that make
        it incompatible with standard TPC benchmarks (no implicit joins, limited
        subquery support, etc.).

        For SQL benchmarks, use a SQL-native platform like DuckDB or PostgreSQL.
        For Polars benchmarks, use the DataFrame API via polars-df platform.

        Raises:
            NotImplementedError: Always, as SQL mode is not supported
        """
        raise NotImplementedError(
            "Polars SQL mode is not supported. Polars' SQL implementation has fundamental limitations "
            "(no implicit joins, limited subquery support) that make it incompatible with TPC benchmarks. "
            "Use 'polars-df' platform for DataFrame API execution, or use a SQL-native platform like "
            "'duckdb' or 'postgresql' for SQL benchmarks."
        )

    def check_database_exists(self, **connection_config) -> bool:
        """Check if Polars working directory exists with data."""
        working_dir = Path(connection_config.get("working_dir", self.working_dir))

        if not working_dir.exists():
            return False

        # Check if working directory has data files
        return any(working_dir.glob("*.parquet")) or any(working_dir.glob("*.csv"))

    def drop_database(self, **connection_config) -> None:
        """Drop Polars working directory and all data."""
        import shutil

        working_dir = Path(connection_config.get("working_dir", self.working_dir))

        if working_dir.exists():
            self.logger.warning(f"Removing Polars working directory: {working_dir}")
            shutil.rmtree(working_dir)
            self.logger.warning("Polars working directory removed")

    def validate_platform_capabilities(self, benchmark_type: str):
        """Validate Polars-specific capabilities for the benchmark."""
        from benchbox.core.validation import ValidationResult

        errors = []
        warnings = []

        # Check if Polars is available
        if pl is None:
            errors.append("Polars library not available - install with 'pip install polars'")
        else:
            # Check Polars version
            try:
                version = pl.__version__
                self.log_very_verbose(f"Polars version: {version}")

                # Parse version for compatibility checks
                version_parts = version.split(".")
                if len(version_parts) >= 2:
                    major = int(version_parts[0])
                    minor = int(version_parts[1])
                    # Warn about older versions
                    if major == 0 and minor < 20:
                        warnings.append(
                            f"Polars version {version} is older - consider upgrading for better performance"
                        )
            except (ValueError, AttributeError):
                warnings.append("Could not determine Polars version")

        # Note: SQL mode has been removed. For SQL benchmarks, users should use
        # a SQL-native platform. This adapter is for DataFrame API usage only.
        warnings.append(
            "Polars SQL mode is not available. Use 'polars-df' platform for DataFrame API execution, "
            "or use a SQL-native platform like 'duckdb' for SQL benchmarks."
        )

        platform_info = {
            "platform": self.platform_name,
            "benchmark_type": benchmark_type,
            "dry_run_mode": self.dry_run_mode,
            "polars_available": pl is not None,
            "working_dir": str(self.working_dir),
            "execution_mode": self.execution_mode,
            "streaming": self.streaming,
            "sql_mode": False,
        }

        if pl is not None:
            platform_info["polars_version"] = pl.__version__

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            details=platform_info,
        )

    def _get_existing_tables(self, connection) -> list[str]:
        """Get list of existing tables in Polars DataFrame context.

        Override base class method to use Polars-specific API.
        """
        try:
            if isinstance(connection, PolarsDataFrameContext):
                return [name.lower() for name in connection.get_tables()]
            return []
        except Exception as e:
            self.log_verbose(f"Error getting existing tables: {e}")
            return []

    def _validate_data_integrity(
        self, benchmark, connection, table_stats: dict[str, int]
    ) -> tuple[str, dict[str, Any]]:
        """Validate basic data integrity using Polars.

        Override base class method for Polars-specific validation.
        """
        validation_details = {}

        try:
            accessible_tables = []
            inaccessible_tables = []

            for table_name in table_stats:
                try:
                    # Verify table is accessible by checking if it exists in context
                    table = connection.get_table(table_name)
                    if table is not None:
                        accessible_tables.append(table_name)
                    else:
                        inaccessible_tables.append(table_name)
                except Exception as e:
                    self.log_verbose(f"Table {table_name} inaccessible: {e}")
                    inaccessible_tables.append(table_name)

            if inaccessible_tables:
                validation_details["inaccessible_tables"] = inaccessible_tables
                validation_details["constraints_enabled"] = False
                return "FAILED", validation_details
            else:
                validation_details["accessible_tables"] = accessible_tables
                validation_details["constraints_enabled"] = True
                return "PASSED", validation_details

        except Exception as e:
            validation_details["error"] = str(e)
            return "FAILED", validation_details
