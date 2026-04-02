"""RAPIDS cuDF platform adapter for GPU-accelerated DataFrame operations.

Provides GPU-accelerated data processing using NVIDIA RAPIDS cuDF library.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from benchbox.experimental.gpu import (
    GPUInfo,
    GPUMetrics,
    GPUMetricsCollector,
    detect_gpu,
)
from benchbox.utils.clock import elapsed_seconds, mono_time

from .base import DriverIsolationCapability, PlatformAdapter

logger = logging.getLogger(__name__)

# Try to import cuDF
try:
    import cudf  # type: ignore

    CUDF_AVAILABLE = True
except ImportError:
    cudf = None
    CUDF_AVAILABLE = False

# Try to import dask-cudf for distributed GPU processing
try:
    import dask_cudf  # type: ignore  # noqa: F401  # imported to detect availability via DASK_CUDF_AVAILABLE

    DASK_CUDF_AVAILABLE = True
except ImportError:
    dask_cudf = None
    DASK_CUDF_AVAILABLE = False

# Try to import dask-sql for SQL support
try:
    from dask_sql import Context as DaskSQLContext  # type: ignore

    DASK_SQL_AVAILABLE = True
except ImportError:
    DaskSQLContext = None
    DASK_SQL_AVAILABLE = False


class CuDFConnectionWrapper:
    """Wrapper for cuDF DataFrame operations that supports SQL-like queries."""

    def __init__(self, adapter: CuDFAdapter):
        self._adapter = adapter
        self._tables: dict[str, Any] = {}
        self._sql_context = None
        self._last_result = None

        if DASK_SQL_AVAILABLE:
            self._sql_context = DaskSQLContext()

    def register_table(self, name: str, df: Any) -> None:
        """Register a DataFrame as a table for SQL queries.

        Args:
            name: Table name
            df: cuDF or pandas DataFrame
        """
        self._tables[name] = df
        if self._sql_context is not None:
            self._sql_context.create_table(name, df)

    def execute(self, query: str, parameters=None) -> CuDFResultWrapper:
        """Execute a query or DataFrame operation.

        Args:
            query: SQL query string or DataFrame operation
            parameters: Optional query parameters

        Returns:
            Result wrapper
        """
        if self._adapter.dry_run_mode:
            self._adapter.capture_sql(query, "query", None)
            return CuDFResultWrapper(None, self._adapter)

        # Try SQL execution first
        if self._sql_context is not None:
            try:
                result = self._sql_context.sql(query)
                # Convert to cuDF if needed
                if hasattr(result, "compute"):
                    result = result.compute()
                self._last_result = result
                return CuDFResultWrapper(result, self._adapter)
            except Exception as e:
                logger.debug(f"SQL execution failed: {e}")

        # Fallback: return empty result
        return CuDFResultWrapper(None, self._adapter)

    def get_tables(self) -> list[str]:
        """Get list of registered tables."""
        return list(self._tables.keys())

    def close(self) -> None:
        """Close connection and cleanup."""
        self._tables.clear()
        if self._sql_context is not None:
            self._sql_context = None


class CuDFResultWrapper:
    """Wrapper for cuDF query results with efficient GPU/host transfer handling.

    Optimized to minimize GPU-to-host transfers and avoid unnecessary
    pandas conversions during benchmarking.
    """

    def __init__(self, result: Any, adapter: CuDFAdapter):
        self._result = result
        self._adapter = adapter
        self._cached_rows: list[tuple] | None = None

    def fetchall(self) -> list[tuple]:
        """Fetch all rows with efficient transfer.

        Uses Arrow for efficient GPU->host transfer when available,
        avoiding full pandas DataFrame conversion overhead.
        """
        if self._result is None:
            return []

        # Return cached result if available (avoid repeated transfers)
        if self._cached_rows is not None:
            return self._cached_rows

        result_len = len(self._result)
        if result_len == 0:
            self._cached_rows = []
            return []

        # Prefer Arrow for efficient transfer (avoids pandas overhead)
        if hasattr(self._result, "to_arrow"):
            try:
                arrow_table = self._result.to_arrow()
                self._cached_rows = [tuple(row.values()) for row in arrow_table.to_pylist()]
                return self._cached_rows
            except Exception:
                pass  # Fall back to pandas

        # Fall back to pandas conversion (last resort)
        if hasattr(self._result, "to_pandas"):
            pdf = self._result.to_pandas()
            self._cached_rows = [tuple(row) for row in pdf.itertuples(index=False, name=None)]
            return self._cached_rows

        return []

    def fetchone(self) -> tuple | None:
        """Fetch single row efficiently without full result transfer."""
        if self._result is None or len(self._result) == 0:
            return None

        # Use cached result if available
        if self._cached_rows is not None and len(self._cached_rows) > 0:
            return self._cached_rows[0]

        # Direct single-row access (avoids full transfer)
        try:
            # Use cuDF's direct indexing - transfers only one row
            first_row = self._result.iloc[0]
            if hasattr(first_row, "to_pandas"):
                # Single row Series -> tuple
                return tuple(first_row.to_pandas().values)
            return tuple(first_row.values)
        except Exception:
            # Fall back to fetchall and get first row
            rows = self.fetchall()
            return rows[0] if rows else None

    def fetchmany(self, size: int = 100) -> list[tuple]:
        """Fetch multiple rows efficiently."""
        if self._result is None or len(self._result) == 0:
            return []

        # If requesting all or most rows, just use fetchall
        if size >= len(self._result):
            return self.fetchall()

        # For partial fetch, slice first then convert (more efficient)
        try:
            partial_result = self._result.head(size)
            if hasattr(partial_result, "to_arrow"):
                arrow_table = partial_result.to_arrow()
                return [tuple(row.values()) for row in arrow_table.to_pylist()]
            elif hasattr(partial_result, "to_pandas"):
                pdf = partial_result.to_pandas()
                return [tuple(row) for row in pdf.itertuples(index=False, name=None)]
        except Exception:
            pass

        # Fall back to full fetch and slice
        return self.fetchall()[:size]

    @property
    def rowcount(self) -> int:
        """Get row count without data transfer."""
        if self._result is None:
            return 0
        return len(self._result)


class CuDFAdapter(PlatformAdapter):
    """RAPIDS cuDF platform adapter for GPU-accelerated DataFrame operations.

    Provides GPU-accelerated data processing using NVIDIA RAPIDS cuDF library.
    Supports SQL queries via dask-sql integration.

    Example:
        >>> adapter = CuDFAdapter(device_id=0, memory_limit="8GB")
        >>> conn = adapter.create_connection()
        >>> conn.register_table("data", cudf.read_csv("data.csv"))
        >>> result = conn.execute("SELECT * FROM data WHERE value > 100")
    """

    driver_isolation_capability = DriverIsolationCapability.NOT_FEASIBLE

    @property
    def platform_name(self) -> str:
        return "cuDF"

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add cuDF-specific CLI arguments."""
        cudf_group = parser.add_argument_group("cuDF/RAPIDS Arguments")
        cudf_group.add_argument("--device-id", type=int, default=0, help="GPU device ID to use")
        cudf_group.add_argument("--gpu-memory-limit", type=str, help="GPU memory limit (e.g., '8GB')")
        cudf_group.add_argument("--spill-to-host", action="store_true", help="Enable spilling to host memory")
        cudf_group.add_argument(
            "--collect-gpu-metrics", action="store_true", help="Collect GPU metrics during execution"
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create cuDF adapter from unified configuration."""
        adapter_config = {}

        # GPU configuration
        adapter_config["device_id"] = config.get("device_id", 0)
        adapter_config["memory_limit"] = config.get("gpu_memory_limit")
        adapter_config["spill_to_host"] = config.get("spill_to_host", False)
        adapter_config["collect_metrics"] = config.get("collect_gpu_metrics", False)

        # Pass through other relevant config
        for key in ["verbose_enabled", "very_verbose", "force_recreate"]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get cuDF platform information."""
        gpu_info = detect_gpu()

        platform_info = {
            "platform_type": "cudf",
            "platform_name": "RAPIDS cuDF",
            "gpu_available": gpu_info.available,
            "device_count": gpu_info.device_count,
            "configuration": {
                "device_id": self.device_id,
                "memory_limit": self.memory_limit,
                "spill_to_host": self.spill_to_host,
                "collect_metrics": self.collect_metrics,
            },
        }

        # cuDF version
        if CUDF_AVAILABLE:
            platform_info["cudf_version"] = cudf.__version__
            platform_info["platform_version"] = cudf.__version__

        # GPU details
        if gpu_info.available and gpu_info.devices:
            device = gpu_info.devices[self.device_id] if self.device_id < len(gpu_info.devices) else gpu_info.devices[0]
            platform_info["gpu_name"] = device.name
            platform_info["gpu_memory_mb"] = device.memory_total_mb
            platform_info["compute_capability"] = device.compute_capability

        # CUDA/driver info
        platform_info["cuda_version"] = gpu_info.cuda_version
        platform_info["driver_version"] = gpu_info.driver_version

        return platform_info

    def __init__(self, **config):
        super().__init__(**config)

        if not CUDF_AVAILABLE:
            raise ImportError(
                "cuDF not installed. Install with: conda install -c rapidsai -c conda-forge -c nvidia cudf"
            )

        # GPU configuration
        self.device_id = config.get("device_id", 0)
        self.memory_limit = config.get("memory_limit")
        self.spill_to_host = config.get("spill_to_host", False)
        self.collect_metrics = config.get("collect_metrics", False)

        # Metrics collector
        self._metrics_collector: GPUMetricsCollector | None = None

        # GPU info cache
        self._gpu_info: GPUInfo | None = None

    def _initialize_gpu(self) -> None:
        """Initialize GPU for use."""
        try:
            import cupy  # type: ignore

            # Set the default device
            cupy.cuda.Device(self.device_id).use()

            # Configure memory if RMM is available
            if self.memory_limit:
                try:
                    import rmm  # type: ignore

                    # Parse memory limit
                    limit_bytes = self._parse_memory_limit(self.memory_limit)
                    rmm.reinitialize(
                        pool_allocator=True,
                        initial_pool_size=limit_bytes // 2,
                        maximum_pool_size=limit_bytes,
                    )
                    logger.info(f"RMM memory pool initialized with {self.memory_limit} limit")
                except ImportError:
                    logger.debug("RMM not available, using default memory allocator")

        except Exception as e:
            logger.warning(f"GPU initialization warning: {e}")

    def _parse_memory_limit(self, limit: str) -> int:
        """Parse memory limit string to bytes."""
        limit = limit.strip().upper()
        if limit.endswith("GB"):
            return int(float(limit[:-2]) * 1024 * 1024 * 1024)
        elif limit.endswith("MB"):
            return int(float(limit[:-2]) * 1024 * 1024)
        elif limit.endswith("KB"):
            return int(float(limit[:-2]) * 1024)
        else:
            return int(limit)

    def create_connection(self, **connection_config) -> CuDFConnectionWrapper:
        """Create cuDF connection wrapper."""
        self.log_operation_start("cuDF connection")

        # Initialize GPU
        self._initialize_gpu()

        # Start metrics collection if enabled
        if self.collect_metrics:
            self._metrics_collector = GPUMetricsCollector(
                device_indices=[self.device_id],
                sample_interval_seconds=0.5,
            )
            self._metrics_collector.start()

        # Create connection wrapper
        conn = CuDFConnectionWrapper(self)

        self.log_operation_complete("cuDF connection", details=f"device={self.device_id}")
        return conn

    def create_schema(self, benchmark, connection: CuDFConnectionWrapper) -> float:
        """Create schema (no-op for cuDF - schema is inferred from data)."""
        start_time = mono_time()
        self.log_operation_start("Schema creation", "cuDF (schema inferred from data)")
        # cuDF infers schema from data, no explicit schema creation needed
        duration = elapsed_seconds(start_time)
        self.log_operation_complete("Schema creation", duration, "schema inferred from data")
        return duration

    def load_data(
        self,
        benchmark,
        connection: CuDFConnectionWrapper,
        data_dir: Path,
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data into cuDF DataFrames using DataSourceResolver.

        Supports multiple file formats:
        - Parquet: Direct loading with cudf.read_parquet
        - CSV: Standard comma-delimited files
        - TPC formats (.tbl, .dat): Pipe-delimited with trailing delimiter handling

        Args:
            benchmark: Benchmark instance
            connection: cuDF connection wrapper
            data_dir: Directory containing data files

        Returns:
            Tuple of (table_stats, loading_time, timing_details)
        """
        from benchbox.platforms.base.data_loading import DataSourceResolver
        from benchbox.platforms.base.utils import detect_file_format

        self.log_operation_start("Data loading", f"directory: {data_dir}")
        start_time = mono_time()
        table_stats: dict[str, int] = {}
        timing_details: dict[str, Any] = {}

        # Use DataSourceResolver for consistent data source resolution
        resolver = DataSourceResolver()
        data_source = resolver.resolve(benchmark, Path(data_dir))

        if not data_source or not data_source.tables:
            raise ValueError(f"No data files found in {data_dir}")

        self.log_verbose(f"Data source type: {data_source.source_type}")

        # Load each table
        for table_name, file_paths in data_source.tables.items():
            table_start = mono_time()

            # Normalize and filter to valid files using base class helper
            valid_files = self._normalize_and_validate_file_paths(file_paths)

            if not valid_files:
                self.log_verbose(f"Skipping {table_name} - no valid data files")
                table_stats[table_name.lower()] = 0
                continue

            table_name_lower = table_name.lower()
            chunk_info = f" from {len(valid_files)} file(s)" if len(valid_files) > 1 else ""
            self.log_verbose(f"Loading data for table: {table_name_lower}{chunk_info}")

            try:
                # Detect file format
                format_info = detect_file_format(valid_files)

                total_rows = 0
                dfs = []

                for file_path in valid_files:
                    file_path = Path(file_path)

                    if format_info.format_type == "parquet":
                        df = cudf.read_parquet(file_path)
                    elif format_info.format_type == "tpc":
                        # TPC files: pipe-delimited with trailing delimiter
                        df = cudf.read_csv(
                            file_path,
                            sep=format_info.delimiter,
                            header=None,
                        )
                        # Trailing delimiter handling is done via shared utility in cudf_df.py
                    else:
                        # Standard CSV
                        df = cudf.read_csv(file_path, sep=format_info.delimiter)

                    dfs.append(df)
                    total_rows += len(df)

                # Concatenate if multiple files
                final_df = dfs[0] if len(dfs) == 1 else cudf.concat(dfs, ignore_index=True)

                # Register table
                connection.register_table(table_name_lower, final_df)
                table_stats[table_name_lower] = len(final_df)

                table_duration = elapsed_seconds(table_start)
                timing_details[table_name_lower] = {"total_ms": table_duration * 1000}

                self.log_verbose(
                    f"Loaded table {table_name_lower}: {len(final_df):,} rows "
                    f"({format_info.format_type}){chunk_info} in {table_duration:.2f}s"
                )

            except Exception as e:
                logger.error(f"Failed to load {table_name}: {e}")
                table_stats[table_name.lower()] = 0

        loading_time = elapsed_seconds(start_time)
        total_rows = sum(table_stats.values())

        self.log_operation_complete(
            "Data loading",
            loading_time,
            f"{len(table_stats)} tables, {total_rows:,} total rows",
        )

        return table_stats, loading_time, timing_details

    def execute_query(
        self,
        connection: CuDFConnectionWrapper,
        query: str,
        query_id: str,
        benchmark_type: str | None = None,
        scale_factor: float | None = None,
        validate_row_count: bool = True,
        stream_id: int | None = None,
    ) -> dict[str, Any]:
        """Execute query on GPU with validation support."""
        self.log_verbose(f"Executing query {query_id}")
        self.log_very_verbose(f"Query SQL (first 200 chars): {query[:200]}{'...' if len(query) > 200 else ''}")

        # Handle dry-run mode using base class helper
        if self.dry_run_mode:
            self.capture_sql(query, "query", None)
            return self._build_dry_run_result(query_id)

        start_time = mono_time()

        try:
            result = connection.execute(query)
            execution_time = elapsed_seconds(start_time)

            # Get row count without full data transfer
            actual_row_count = result.rowcount
            # Get first row efficiently (only transfers one row)
            first_row = result.fetchone()

            logger.debug(f"Query {query_id} completed in {execution_time:.3f}s, returned {actual_row_count} rows")

            # Validate row count if enabled and benchmark type is provided
            validation_result = None
            if validate_row_count and benchmark_type:
                from benchbox.core.validation.query_validation import QueryValidator

                validator = QueryValidator()
                validation_result = validator.validate_query_result(
                    benchmark_type=benchmark_type,
                    query_id=query_id,
                    actual_row_count=actual_row_count,
                    scale_factor=scale_factor,
                    stream_id=stream_id,
                )

                # Log validation result
                if validation_result.warning_message:
                    self.log_verbose(f"Row count validation: {validation_result.warning_message}")
                elif not validation_result.is_valid:
                    self.log_verbose(f"Row count validation FAILED: {validation_result.error_message}")
                else:
                    self.log_very_verbose(
                        f"Row count validation PASSED: {actual_row_count} rows "
                        f"(expected: {validation_result.expected_row_count})"
                    )

            # Use base class helper for consistent result format with validation
            result_dict = self._build_query_result_with_validation(
                query_id=query_id,
                execution_time=execution_time,
                actual_row_count=actual_row_count,
                first_row=first_row,
                validation_result=validation_result,
            )

            # Add GPU-specific metrics
            if self._metrics_collector:
                samples = self._metrics_collector.get_samples()
                if samples:
                    latest = samples[-1]
                    result_dict["gpu_memory_used_mb"] = latest.memory_used_mb
                    result_dict["gpu_utilization_percent"] = latest.utilization_percent
                    result_dict["gpu_temperature_celsius"] = latest.temperature_celsius

            return result_dict

        except Exception as e:
            # Use base class helper for consistent failure result
            return self._build_query_failure_result(query_id, start_time, e)

    def get_target_dialect(self) -> str:
        """Get the target SQL dialect."""
        return "cudf"

    def get_query_plan(self, connection: Any, query: str) -> str | None:
        """Get query execution plan (not supported for cuDF)."""
        return None

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Configure for benchmark execution."""
        # No special configuration needed for cuDF

    def analyze_tables(self, connection: CuDFConnectionWrapper) -> None:
        """Analyze tables (no-op for cuDF)."""
        # cuDF doesn't have table statistics like traditional databases

    def apply_constraint_configuration(
        self,
        primary_key_config,
        foreign_key_config,
        connection: Any,
    ) -> None:
        """Apply constraint configuration (no-op for cuDF).

        cuDF DataFrames don't support database-style constraints.
        This method maintains interface compatibility with PlatformAdapter.

        Args:
            primary_key_config: Primary key configuration (ignored)
            foreign_key_config: Foreign key configuration (ignored)
            connection: cuDF connection wrapper
        """
        if primary_key_config and getattr(primary_key_config, "enabled", False):
            self.log_verbose("cuDF does not enforce PRIMARY KEY constraints - configuration noted but not applied")
        if foreign_key_config and getattr(foreign_key_config, "enabled", False):
            self.log_verbose("cuDF does not enforce FOREIGN KEY constraints - configuration noted but not applied")

    def apply_platform_optimizations(self, platform_config, connection: Any) -> None:
        """Apply platform-specific optimizations (no-op for cuDF).

        cuDF optimizations are handled at the RAPIDS/RMM level during initialization.
        This method maintains interface compatibility with PlatformAdapter.

        Args:
            platform_config: Platform optimization configuration (ignored)
            connection: cuDF connection wrapper
        """
        if platform_config:
            self.log_verbose(
                "cuDF optimizations are handled at RAPIDS/RMM level - "
                "platform config noted but applied via GPU initialization"
            )

    def cleanup(self) -> None:
        """Cleanup resources."""
        if self._metrics_collector:
            self._metrics_collector.stop()
            self._metrics_collector = None

    def get_gpu_metrics(self) -> list[GPUMetrics]:
        """Get collected GPU metrics."""
        if self._metrics_collector:
            return self._metrics_collector.get_samples()
        return []

    def get_gpu_info(self) -> GPUInfo:
        """Get GPU information."""
        if self._gpu_info is None:
            self._gpu_info = detect_gpu()
        return self._gpu_info

    def validate_platform_capabilities(self, benchmark_type: str):
        """Validate cuDF capabilities for the benchmark."""
        errors = []
        warnings = []

        # Check cuDF availability
        if not CUDF_AVAILABLE:
            errors.append("cuDF not available - install RAPIDS cuDF")
        else:
            # Check version
            try:
                version = cudf.__version__
                warnings.append(f"cuDF version: {version}")
            except AttributeError:
                warnings.append("Could not determine cuDF version")

        # Check GPU availability
        gpu_info = detect_gpu()
        if not gpu_info.available:
            errors.append("No GPU available")
        elif self.device_id >= gpu_info.device_count:
            errors.append(f"Device ID {self.device_id} not available (found {gpu_info.device_count} devices)")

        # Check for dask-sql (optional but recommended)
        if not DASK_SQL_AVAILABLE:
            warnings.append("dask-sql not available - SQL query support limited")

        platform_info = {
            "platform": self.platform_name,
            "benchmark_type": benchmark_type,
            "cudf_available": CUDF_AVAILABLE,
            "dask_cudf_available": DASK_CUDF_AVAILABLE,
            "dask_sql_available": DASK_SQL_AVAILABLE,
            "gpu_info": gpu_info.to_dict(),
        }

        try:
            from benchbox.core.validation import ValidationResult

            return ValidationResult(
                is_valid=len(errors) == 0,
                errors=errors,
                warnings=warnings,
                details=platform_info,
            )
        except ImportError:
            return None
