"""DataFusion platform adapter with data loading and query execution.

Provides Apache DataFusion-specific optimizations for in-memory OLAP workloads,
supporting both CSV and Parquet formats with automatic conversion options.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    from datafusion import SessionConfig, SessionContext

    try:
        from datafusion import RuntimeEnv
    except ImportError:
        # Newer versions use RuntimeEnvBuilder
        from datafusion import RuntimeEnvBuilder as RuntimeEnv
except ImportError:
    SessionContext = None  # type: ignore[assignment, misc]
    SessionConfig = None  # type: ignore[assignment, misc]
    RuntimeEnv = None  # type: ignore[assignment, misc]  # ty: ignore[conflicting-declarations]

from benchbox.core.dataframe.schema_utils import extract_schema_columns
from benchbox.platforms.base import DriverIsolationCapability, PlatformAdapter
from benchbox.platforms.base.data_loading import NO_BENCHMARK, DataSource, resolve_csv_dialect
from benchbox.platforms.base.no_constraint_mixin import NoConstraintEnforcementMixin
from benchbox.utils.clock import elapsed_seconds, mono_time

logger = logging.getLogger(__name__)

# Threshold for switching CSV→Parquet conversion from in-memory to streaming.
# Files larger than this are written in batches to avoid OOM on large inputs.
_CSV_TO_PARQUET_STREAM_THRESHOLD = 256 * 1024 * 1024  # 256 MB

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import TuningColumn


class DataFusionCursorCompat:
    """DB-API-like cursor wrapper for DataFusion SQL results."""

    def __init__(self, dataframe: Any):
        self._dataframe = dataframe
        self._rows: list[tuple[Any, ...]] | None = None
        self.rowcount = -1

    def _materialize(self) -> list[tuple[Any, ...]]:
        if self._rows is not None:
            return self._rows

        rows: list[tuple[Any, ...]] = []
        batches = self._dataframe.collect()

        for batch in batches:
            column_names = [str(name) for name in batch.schema.names]
            for row in batch.to_pylist():
                rows.append(tuple(row.get(name) for name in column_names))

        self.rowcount = len(rows)
        self._rows = rows
        return rows

    def fetchone(self) -> tuple[Any, ...] | None:
        rows = self._materialize()
        return rows[0] if rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._materialize()


class DataFusionConnectionCompat:
    """SessionContext wrapper exposing a DB-API-like execute() method."""

    def __init__(self, context: Any):
        self._context = context

    @staticmethod
    def _requires_eager_execution(query: str) -> bool:
        """Return True for SQL statements that must execute immediately for side effects."""
        statement = query.lstrip()
        while statement.startswith("--"):
            newline_pos = statement.find("\n")
            if newline_pos == -1:
                return False
            statement = statement[newline_pos + 1 :].lstrip()

        upper_statement = statement.upper()
        eager_prefixes = (
            "INSERT",
            "UPDATE",
            "DELETE",
            "MERGE",
            "CREATE",
            "DROP",
            "ALTER",
            "TRUNCATE",
            "COPY",
        )
        return upper_statement.startswith(eager_prefixes)

    def execute(self, query: str, parameters: Any = None) -> DataFusionCursorCompat:
        if parameters is not None:
            raise ValueError("DataFusion SQL execute() does not support bound parameters in this adapter path")
        cursor = DataFusionCursorCompat(self._context.sql(query))
        if self._requires_eager_execution(query):
            cursor.fetchall()
        return cursor

    def sql(self, query: str) -> Any:
        return self._context.sql(query)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._context, name)


class DataFusionAdapter(NoConstraintEnforcementMixin, PlatformAdapter):
    """Apache DataFusion platform adapter with optimized bulk loading and execution."""

    driver_isolation_capability = DriverIsolationCapability.SUPPORTED
    supports_external_tables = True

    # Process-wide lock bookkeeping keyed by working-dir lock file path.
    # This ensures ownership/reentrancy is shared across adapter instances.
    _process_working_dir_lock_depth: dict[str, int] = {}
    _process_working_dir_lock_guard = threading.Lock()

    @property
    def platform_name(self) -> str:
        return "DataFusion"

    def get_target_dialect(self) -> str:
        """Get the target SQL dialect for DataFusion.

        Returns platform dialect identifier so catalog variants can target DataFusion.
        SQL translation normalizes this to PostgreSQL semantics where needed.
        """
        return "datafusion"

    def preprocess_operation_sql(self, operation_id: str, operation: Any) -> str | None:
        """Preprocess write operation SQL for DataFusion compatibility.

        Rewrites COPY-based bulk load SQL to CREATE EXTERNAL TABLE pattern.
        Returns None for non-bulk_load operations (no preprocessing needed).

        Args:
            operation_id: Operation identifier
            operation: WriteOperation object with category, write_sql, file_dependencies

        Returns:
            Transformed SQL string, or None if no preprocessing needed
        """
        if operation.category.lower() == "bulk_load":
            from benchbox.platforms.datafusion_write_transformer import transform_write_sql

            return transform_write_sql(
                operation_id,
                operation.category,
                operation.write_sql,
                operation.file_dependencies,
            )
        return None

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add DataFusion-specific CLI arguments."""
        datafusion_group = parser.add_argument_group("DataFusion Arguments")
        datafusion_group.add_argument(
            "--datafusion-memory-limit",
            type=str,
            default="16G",
            help="DataFusion memory limit (e.g., '16G', '8GB', '4096MB')",
        )
        datafusion_group.add_argument(
            "--datafusion-partitions",
            type=int,
            default=None,
            help="Number of parallel partitions (default: CPU count)",
        )
        datafusion_group.add_argument(
            "--datafusion-format",
            type=str,
            choices=["csv", "parquet"],
            default="parquet",
            help="Data format to use (parquet recommended for performance)",
        )
        datafusion_group.add_argument(
            "--datafusion-temp-dir",
            type=str,
            default=None,
            help="Temporary directory for disk spilling",
        )
        datafusion_group.add_argument(
            "--datafusion-batch-size",
            type=int,
            default=8192,
            help="RecordBatch size for query execution",
        )
        datafusion_group.add_argument(
            "--datafusion-working-dir",
            type=str,
            help="Working directory for DataFusion tables and data",
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create DataFusion adapter from unified configuration."""
        from pathlib import Path

        from benchbox.utils.database_naming import generate_database_filename

        # Extract DataFusion-specific configuration
        adapter_config = {}

        # Working directory handling (similar to database path for file-based DBs)
        if config.get("working_dir"):
            adapter_config["working_dir"] = config["working_dir"]
        else:
            # Generate database directory path using standard naming convention
            # DataFusion stores data in Parquet format (.parquet extension determined by platform)
            from benchbox.utils.path_utils import get_benchmark_runs_databases_path

            if config.get("output_dir"):
                data_dir = get_benchmark_runs_databases_path(
                    config["benchmark"],
                    config["scale_factor"],
                    base_dir=Path(config["output_dir"]) / "databases",
                )
            else:
                data_dir = get_benchmark_runs_databases_path(config["benchmark"], config["scale_factor"])

            db_filename = generate_database_filename(
                benchmark_name=config["benchmark"],
                scale_factor=config["scale_factor"],
                platform="datafusion",
                tuning_config=config.get("tuning_config"),
            )

            # Full path to DataFusion working directory
            working_dir = data_dir / db_filename
            adapter_config["working_dir"] = str(working_dir)
            working_dir.mkdir(parents=True, exist_ok=True)

        # Memory limit
        adapter_config["memory_limit"] = config.get("memory_limit", "16G")

        # Parallelism (default to CPU count)
        adapter_config["target_partitions"] = config.get("partitions") or os.cpu_count()

        # Data format
        adapter_config["data_format"] = config.get("format", "parquet")

        # Temp directory for spilling
        adapter_config["temp_dir"] = config.get("temp_dir")

        # Batch size
        adapter_config["batch_size"] = config.get("batch_size", 8192)

        # Force recreate
        adapter_config["force_recreate"] = config.get("force", False)

        # Pass through other relevant config
        for key in ["tuning_config", "verbose_enabled", "very_verbose"]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

    def __init__(self, **config):
        super().__init__(**config)
        if SessionContext is None:
            raise ImportError("DataFusion not installed. Install with: pip install datafusion")

        # DataFusion configuration
        self.working_dir = Path(config.get("working_dir", "./datafusion_working"))
        self.memory_limit = config.get("memory_limit", "16G")
        self.target_partitions = config.get("target_partitions", os.cpu_count())
        self.data_format = config.get("data_format", "parquet")
        self.temp_dir = config.get("temp_dir")
        self.batch_size = config.get("batch_size", 8192)

        # Schema tracking (populated during create_schema)
        self._table_schemas = {}
        # Create working directory
        self.working_dir.mkdir(parents=True, exist_ok=True)

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get DataFusion platform information."""
        platform_info = {
            "platform_type": "datafusion",
            "platform_name": "DataFusion",
            "connection_mode": "in-memory",
            "configuration": {
                "working_dir": str(self.working_dir),
                "memory_limit": self.memory_limit,
                "target_partitions": self.target_partitions,
                "data_format": self.data_format,
                "temp_dir": self.temp_dir,
                "batch_size": self.batch_size,
                "result_cache_enabled": False,
            },
        }

        # Get DataFusion version from live module (coupled: driver == engine).
        try:
            import datafusion as df_module

            live_version = df_module.__version__
            platform_info["client_library_version"] = live_version
            platform_info["platform_version"] = live_version
            platform_info["driver_version_actual"] = live_version
            self.driver_version_actual = live_version
        except (ImportError, AttributeError):
            platform_info["client_library_version"] = None
            platform_info["platform_version"] = None

        # Propagate driver runtime contract metadata.
        if self.driver_runtime_strategy:
            platform_info["driver_runtime_strategy"] = self.driver_runtime_strategy
        if self.driver_version_requested:
            platform_info["driver_version_requested"] = self.driver_version_requested
        if self.driver_version_resolved:
            platform_info["driver_version_resolved"] = self.driver_version_resolved
        if self.driver_version_actual:
            platform_info["driver_version_actual"] = self.driver_version_actual

        return platform_info

    def create_connection(self, **connection_config) -> Any:
        """Create DataFusion SessionContext with optimized configuration."""
        self.log_operation_start("DataFusion connection")

        # Serialize database management on shared working dirs to avoid cleanup races.
        lock_acquired = self._acquire_working_dir_lock(timeout_seconds=10, **connection_config)
        if not lock_acquired:
            raise RuntimeError("Could not acquire DataFusion working directory lock after 10 seconds")

        try:
            # Handle existing database using base class method
            self.handle_existing_database(**connection_config)
        finally:
            self._release_working_dir_lock(**connection_config)

        # Configure runtime environment for disk spilling and memory management
        # Note: RuntimeEnv/RuntimeEnvBuilder API varies by version
        runtime = None
        if RuntimeEnv is not None:
            try:
                # Check if this is RuntimeEnvBuilder (newer API)
                if hasattr(RuntimeEnv, "build"):
                    # RuntimeEnvBuilder API
                    builder = RuntimeEnv()

                    # Configure memory pool using fair spill pool
                    # This replaces the invalid config.set("memory_pool_size") approach
                    if self.memory_limit:
                        memory_bytes = int(self._parse_memory_limit(self.memory_limit))
                        builder = builder.with_fair_spill_pool(memory_bytes)
                        self.log_very_verbose(
                            f"Configured fair spill pool: {self.memory_limit} ({memory_bytes:,} bytes)"
                        )

                    # Configure disk manager for spilling
                    builder = builder.with_disk_manager_os()
                    if self.temp_dir:
                        self.log_very_verbose(f"Enabled disk spilling (temp dir: {self.temp_dir})")
                    else:
                        self.log_very_verbose("Enabled disk spilling (using system temp dir)")

                    runtime = builder.build()
                else:
                    # Old RuntimeEnv API (fallback)
                    runtime = RuntimeEnv()
                    self.log_very_verbose("Using default RuntimeEnv (memory configuration not available in old API)")
            except Exception as e:
                self.log_very_verbose(f"Could not configure RuntimeEnv: {e}, using defaults")
                runtime = None

        # Create session configuration
        config = SessionConfig()

        # Set parallelism
        config = config.with_target_partitions(self.target_partitions)

        # Enable optimizations
        config = config.with_parquet_pruning(True)
        config = config.with_repartition_joins(True)
        config = config.with_repartition_aggregations(True)
        config = config.with_repartition_windows(True)
        config = config.with_information_schema(True)

        # Set batch size
        config = config.with_batch_size(self.batch_size)

        # Track applied configuration for logging
        config_applied = [
            f"target_partitions={self.target_partitions}",
            f"batch_size={self.batch_size}",
            "parquet_pruning=enabled",
            "repartitioning=enabled",
        ]

        # Add runtime configuration to tracking
        if runtime is not None:
            if self.memory_limit:
                config_applied.append(f"memory_pool={self.memory_limit}")
            config_applied.append("disk_spilling=enabled")

        # Note: Memory configuration now handled via RuntimeEnvBuilder above
        # The invalid config.set("memory_pool_size") approach has been removed

        # Note: Parquet optimizations already configured via with_parquet_pruning(True)
        # Redundant config.set() calls have been removed

        # Create SessionContext with runtime environment if available
        if runtime is not None:
            try:
                ctx = SessionContext(config, runtime)
                self.log_very_verbose("SessionContext created with RuntimeEnv")
            except TypeError:
                # Older versions may not accept runtime parameter
                ctx = SessionContext(config)
                self.log_very_verbose("SessionContext created without RuntimeEnv (not supported in this version)")
        else:
            ctx = SessionContext(config)

        self.log_operation_complete("DataFusion connection", details=f"Applied: {', '.join(config_applied)}")

        return DataFusionConnectionCompat(ctx)

    def _get_working_dir_lock_file(self, **connection_config) -> Path:
        """Get lock file path for working-dir lifecycle operations."""
        working_dir = Path(connection_config.get("working_dir", self.working_dir))
        return working_dir.parent / f".{working_dir.name}.db_manage.lock"

    def _is_pid_running(self, pid: int) -> bool:
        """Return True when process exists, False when definitely absent."""
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Process exists but may be owned by another user.
            return True
        except Exception:
            return False

    def _read_lock_pid(self, lock_file: Path) -> int | None:
        """Read PID from lock file content, returning None if unavailable."""
        try:
            content = lock_file.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.startswith("pid:"):
                    return int(line.split(":", 1)[1].strip())
        except Exception:
            return None
        return None

    def _acquire_working_dir_lock(self, timeout_seconds: int = 300, **connection_config) -> bool:
        """Acquire lock for DataFusion working-dir lifecycle operations."""
        lock_file = self._get_working_dir_lock_file(**connection_config)
        lock_key = str(lock_file.resolve())
        lock_file.parent.mkdir(parents=True, exist_ok=True)

        start_time = mono_time()
        lock_detected_logged = False
        wait_warning_emitted = False

        while elapsed_seconds(start_time) < timeout_seconds:
            try:
                with self._process_working_dir_lock_guard:
                    # Reentrant fast-path shared across all adapter instances.
                    existing_depth = self._process_working_dir_lock_depth.get(lock_key, 0)
                    if existing_depth > 0:
                        self._process_working_dir_lock_depth[lock_key] = existing_depth + 1
                        return True

                    fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(f"pid:{os.getpid()}\n")
                        f.write(f"time:{time.time()}\n")
                    self._process_working_dir_lock_depth[lock_key] = 1
                    return True
            except FileExistsError:
                try:
                    age_seconds = time.time() - lock_file.stat().st_mtime
                    lock_pid = self._read_lock_pid(lock_file)

                    # Recover interrupted self-owned lock files when no active owner is tracked.
                    if lock_pid == os.getpid():
                        with self._process_working_dir_lock_guard:
                            existing_depth = self._process_working_dir_lock_depth.get(lock_key, 0)
                        if existing_depth == 0:
                            self.log_verbose(
                                f"Removing stale self-owned DataFusion working-dir lock: {lock_file} "
                                f"(pid={lock_pid}, age={age_seconds:.1f}s)"
                            )
                            lock_file.unlink(missing_ok=True)
                            continue

                    # Verbose signal for immediate lock detection visibility.
                    if not lock_detected_logged:
                        self.log_verbose(
                            f"DataFusion working-dir lock detected: {lock_file} "
                            f"(pid={lock_pid}, age={age_seconds:.1f}s)"
                        )
                        lock_detected_logged = True

                    # Standard warning signal when we're blocked and waiting.
                    if not wait_warning_emitted:
                        self.logger.warning(
                            f"DataFusion working directory lock is held by another process "
                            f"(pid={lock_pid}). Waiting for release..."
                        )
                        wait_warning_emitted = True

                    owner_dead = lock_pid is not None and not self._is_pid_running(lock_pid)
                    # Treat lock as stale when owner is gone, or metadata is absent and lock is old enough.
                    if owner_dead or (lock_pid is None and age_seconds > 10):
                        self.log_verbose(
                            f"Removing stale DataFusion working-dir lock: {lock_file} "
                            f"(pid={lock_pid}, age={age_seconds:.1f}s)"
                        )
                        lock_file.unlink(missing_ok=True)
                        continue
                except Exception:
                    pass
                time.sleep(0.2)
            except Exception as e:
                self.log_verbose(f"Failed to acquire DataFusion working-dir lock: {e}")
                return False

        return False

    def _release_working_dir_lock(self, **connection_config) -> None:
        """Release lock for DataFusion working-dir lifecycle operations."""
        lock_file = self._get_working_dir_lock_file(**connection_config)
        lock_key = str(lock_file.resolve())

        should_unlink = False
        with self._process_working_dir_lock_guard:
            depth = self._process_working_dir_lock_depth.get(lock_key, 0)
            if depth > 1:
                self._process_working_dir_lock_depth[lock_key] = depth - 1
                return
            if depth == 1:
                self._process_working_dir_lock_depth.pop(lock_key, None)
                should_unlink = True
            else:
                # No tracked ownership in this process: do not unlink another owner's lock.
                return

        if should_unlink:
            try:
                lock_file.unlink(missing_ok=True)
            except Exception as e:
                self.log_verbose(f"Failed to release DataFusion working-dir lock: {e}")

    def _parse_memory_limit(self, memory_limit: str) -> str:
        """Parse memory limit string to bytes.

        Args:
            memory_limit: Memory limit string (e.g., "16G", "8GB", "4096MB")

        Returns:
            Memory limit in bytes as string
        """
        memory_str = memory_limit.upper().strip()

        # Remove 'B' suffix if present
        if memory_str.endswith("B"):
            memory_str = memory_str[:-1]

        # Parse numeric value and unit
        if memory_str.endswith("G"):
            return str(int(float(memory_str[:-1]) * 1024 * 1024 * 1024))
        elif memory_str.endswith("M"):
            return str(int(float(memory_str[:-1]) * 1024 * 1024))
        elif memory_str.endswith("K"):
            return str(int(float(memory_str[:-1]) * 1024))
        else:
            # Assume already in bytes
            return memory_str

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using DataFusion.

        Note: For DataFusion, actual table creation happens during load_data() via
        CREATE EXTERNAL TABLE. This method validates the schema is available.
        """
        start_time = mono_time()
        self.log_operation_start("Schema creation", f"benchmark: {benchmark.__class__.__name__}")

        # Get constraint settings from tuning configuration
        enable_primary_keys, enable_foreign_keys = self._get_constraint_configuration()
        self._log_constraint_configuration(enable_primary_keys, enable_foreign_keys)

        # Note: DataFusion doesn't enforce constraints, so we log but don't apply them
        if enable_primary_keys or enable_foreign_keys:
            self.log_verbose(
                "DataFusion does not enforce PRIMARY KEY or FOREIGN KEY constraints - schema will be created without constraints"
            )

        # Get structured schema directly from benchmark
        # This is cleaner than parsing SQL and provides type-safe access
        self._table_schemas = self._get_benchmark_schema(benchmark)

        duration = elapsed_seconds(start_time)
        self.log_operation_complete(
            "Schema creation", duration, f"Schema validated for {len(self._table_schemas)} tables"
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
            # Fallback: some benchmarks might not have get_schema()
            self.log_verbose(
                f"Benchmark {benchmark.__class__.__name__} does not provide get_schema() method, "
                "will rely on schema inference during data loading"
            )
            return {}

        if not benchmark_schema:
            self.log_verbose("Benchmark returned empty schema, will rely on schema inference")
            return {}

        for table_name, columns in extract_schema_columns(benchmark_schema).items():
            if columns:
                schemas[table_name] = {"columns": columns}
                self.log_very_verbose(f"Extracted schema for {table_name}: {len(columns)} columns")
            else:
                self.log_verbose(f"Warning: No valid columns found for table {table_name}")

        return schemas

    def _create_empty_schema_tables(self, connection: Any) -> dict[str, int]:
        """Create empty in-memory tables from self._table_schemas.

        Used when a benchmark has no data files (e.g. metadata_primitives) so
        that catalog-discovery queries can find the tables via INFORMATION_SCHEMA.
        DataFusion maps SQL types to Arrow types; unsupported DDL is skipped.
        """
        type_map = {
            "BIGINT": "BIGINT",
            "INTEGER": "INT",
            "INT": "INT",
            "SMALLINT": "SMALLINT",
            "FLOAT": "FLOAT",
            "DOUBLE": "DOUBLE",
            "BOOLEAN": "BOOLEAN",
            "DATE": "DATE",
            "TIMESTAMP": "TIMESTAMP",
        }
        for table_name, schema_info in self._table_schemas.items():
            columns = schema_info.get("columns", [])
            if not columns:
                continue
            col_defs = []
            for col in columns:
                col_name = col["name"].lower()
                if '"' in col_name:
                    raise ValueError(f"Column name contains illegal double-quote: {col_name!r}")
                col_type = col.get("type", "VARCHAR").upper()
                # Resolve parameterised types: DECIMAL(10,2) → DECIMAL, VARCHAR(100) → VARCHAR
                base_type = col_type.split("(")[0]
                arrow_type = type_map.get(base_type, "VARCHAR")
                if "(" in col_type and base_type in ("DECIMAL", "NUMERIC"):
                    arrow_type = f"DECIMAL{col_type[len(base_type) :]}"
                col_defs.append(f'"{col_name}" {arrow_type}')
            ddl = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(col_defs)})"
            try:
                connection.execute(ddl)
                self.log_very_verbose(f"Created empty table: {table_name}")
            except Exception as e:
                self.log_verbose(f"Could not create empty table {table_name}: {e}")
        # Return empty stats so row-count validation is skipped for empty-data benchmarks.
        # Schema-integrity validation will check that the tables exist in the catalog.
        return {}

    def load_data(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data into DataFusion.

        Supports CSV, Parquet, Delta Lake, and Iceberg formats.
        Directory-based formats (delta/iceberg) are auto-detected from the file path.
        """
        from benchbox.platforms.base.data_loading import DataSourceResolver

        start_time = mono_time()
        self.log_operation_start("Data loading", f"format: {self.data_format}")

        # Resolve data source (pass platform name for correct format preference)
        resolver = DataSourceResolver(
            platform_name=self.platform_name.lower(),
            table_mode=self.table_mode,
            platform_config=self.platform_config,
            requested_format=self.requested_table_format,
        )
        data_source = resolver.resolve(benchmark, data_dir)

        if not data_source or not data_source.tables:
            # Benchmark generates no data files (e.g. metadata_primitives creates schema in SQL).
            # Create empty in-memory tables from the schema so catalog queries can discover them.
            self.log_verbose(f"No data files found in {data_dir}; creating empty schema tables")
            table_stats = self._create_empty_schema_tables(connection)
            return table_stats, 0.0, None

        table_stats = {}
        per_table_timings = {}
        effective_tuning = self.unified_tuning_configuration if self.tuning_enabled else None

        # Load each table
        for table_name, file_paths in data_source.tables.items():
            table_start = mono_time()

            # Ensure file_paths is a list
            if not isinstance(file_paths, list):
                file_paths = [file_paths]

            # Normalize table name to lowercase
            table_name_lower = table_name.lower()

            # Detect directory-based table formats (delta/iceberg)
            dir_format = self._detect_directory_format(file_paths)

            # Resolver hint keys follow the data-source table names, which may
            # preserve benchmark casing (e.g. TPC-DI's DimCustomer).
            table_csv_format = data_source.table_formats.get(table_name)
            if table_csv_format is None:
                table_csv_format = data_source.table_formats.get(table_name_lower)

            if dir_format == "delta":
                row_count = self._load_table_delta(connection, table_name_lower, file_paths[0])
            elif dir_format == "iceberg":
                row_count = self._load_table_iceberg(connection, table_name_lower, file_paths[0])
            elif self.data_format == "parquet":
                row_count = self._load_table_parquet(
                    connection,
                    table_name_lower,
                    file_paths,
                    data_dir,
                    csv_format=table_csv_format,
                    data_source=data_source,
                    benchmark=benchmark,
                )
            else:
                # Load CSV directly
                row_count = self._load_table_csv(
                    connection,
                    table_name_lower,
                    file_paths,
                    data_dir,
                    csv_format=table_csv_format,
                    data_source=data_source,
                    benchmark=benchmark,
                )

            if effective_tuning:
                self.apply_ctas_sort(table_name_lower, effective_tuning, connection)

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
        """Alias external-table mode to DataFusion's existing external registration path."""
        return self.load_data(benchmark, connection, data_dir)

    def _build_ctas_sort_sql(self, table_name: str, sort_columns: list[TuningColumn]) -> str | None:
        """Build DataFusion CTAS SQL used by PlatformAdapter.apply_ctas_sort.

        ``sort_columns`` is pre-sorted by the caller; no internal sort needed.
        """
        order_by_clause = ", ".join(column.name for column in sort_columns)
        return f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM {table_name} ORDER BY {order_by_clause};"

    def _detect_csv_format(
        self,
        file_paths: list[Path],
        csv_format: str | None = None,
        data_source: DataSource | None = None,
        table_name: str = "",
        benchmark: Any = None,
    ) -> str:
        """Detect CSV delimiter from manifest metadata, format hint, or file extension.

        Args:
            file_paths: List of data file paths (used for extension-based fallback)
            csv_format: Explicit format name from the datagen manifest ("tbl" or "csv").
                        When provided, overrides file-extension detection.

        Returns:
            Delimiter string
        """
        if csv_format == "tbl":
            return "|"
        if csv_format == "csv":
            return ","
        if file_paths:
            ds = data_source or DataSource(source_type="datafusion_csv", tables={})
            bm = benchmark if benchmark is not None else NO_BENCHMARK
            return resolve_csv_dialect(ds, table_name, file_paths[0], bm).delimiter
        return ","

    def _load_table_csv(
        self,
        connection: Any,
        table_name: str,
        file_paths: list[Path],
        data_dir: Path,
        csv_format: str | None = None,
        data_source: DataSource | None = None,
        benchmark: Any = None,
    ) -> int:
        """Load table from CSV files using CREATE EXTERNAL TABLE.

        Handles TPC benchmark format with trailing pipe delimiters and
        uses glob patterns for multiple files.
        """
        # Detect delimiter (manifest metadata > format hint > file extension)
        delimiter = self._detect_csv_format(
            file_paths,
            csv_format=csv_format,
            data_source=data_source,
            table_name=table_name,
            benchmark=benchmark,
        )
        dialect = resolve_csv_dialect(
            data_source or DataSource(source_type="datafusion_csv", tables={}),
            table_name,
            file_paths[0],
            benchmark if benchmark is not None else NO_BENCHMARK,
        )
        delimiter = dialect.delimiter

        # Get schema information for proper column names
        schema_info = self._table_schemas.get(table_name, {})
        columns = schema_info.get("columns", [])

        # Build column schema for CREATE EXTERNAL TABLE
        if columns:
            # Use actual column names and types from schema
            schema_clause = ", ".join([f"{col['name']} {self._map_to_arrow_type(col['type'])}" for col in columns])
            schema_clause = f"({schema_clause})"
        else:
            # No schema available - let DataFusion infer
            schema_clause = ""
            self.log_verbose(f"Warning: No schema found for {table_name}, using schema inference")

        # Use glob pattern for multiple files or single file
        if len(file_paths) > 1:
            # Check if files are in same directory and can use glob
            parent_dir = file_paths[0].parent
            if all(f.parent == parent_dir for f in file_paths):
                common_prefix = os.path.commonprefix([f.name for f in file_paths])
                if common_prefix:
                    location = str(parent_dir / f"{common_prefix}*")
                    self.log_very_verbose(f"Using glob pattern for {table_name}: {location}")
                else:
                    # No shared filename prefix (e.g. UUID/hash-named shards):
                    # `parent/*` would register every file in the directory and
                    # silently pull in other tables' data. Register each shard
                    # by exact path via UNION ALL instead so row counts stay
                    # correct.
                    return self._create_external_table_union(
                        connection,
                        table_name,
                        file_paths,
                        schema_clause=schema_clause,
                        delimiter=delimiter,
                        has_header=dialect.has_header,
                    )
            else:
                # Files in different directories - fall back to first file with warning
                location = str(file_paths[0])
                self.log_verbose(
                    f"Warning: Multiple files in different directories for {table_name}, using first file only"
                )
        else:
            location = str(file_paths[0])

        # Build CREATE EXTERNAL TABLE statement
        # Note: DataFusion's CSV reader doesn't have a direct "ignore trailing delimiter" option
        # We need to handle this via schema definition with exact column count
        options = [
            f"'has_header' '{str(dialect.has_header).lower()}'",
            f"'delimiter' '{delimiter}'",
        ]

        options_clause = ", ".join(options)

        create_sql = f"""
            CREATE EXTERNAL TABLE {table_name} {schema_clause}
            STORED AS CSV
            LOCATION '{location}'
            OPTIONS ({options_clause})
        """

        try:
            connection.sql(create_sql)
            self.log_very_verbose(f"Created external table: {table_name}")
        except Exception as e:
            self.log_verbose(f"Error creating external table {table_name}: {e}")
            raise RuntimeError(f"Failed to create external table {table_name}: {e}") from e

        # Count rows
        try:
            result = connection.sql(f"SELECT COUNT(*) FROM {table_name}").collect()
            row_count = int(result[0].column(0)[0])
            return row_count
        except Exception as e:
            self.log_verbose(f"Error counting rows in {table_name}: {e}")
            raise RuntimeError(f"Failed to count rows in {table_name}: {e}") from e

    def _create_external_table_union(
        self,
        connection: Any,
        table_name: str,
        file_paths: list[Path],
        *,
        schema_clause: str,
        delimiter: str,
        has_header: bool,
    ) -> int:
        """Register a multi-shard CSV table by exact path then UNION ALL.

        Used when ``os.path.commonprefix`` returns ``""`` for the shard names.
        A bare ``parent/*`` glob would silently include unrelated files in the
        same directory; per-shard registration keeps row counts correct.
        """
        shard_options_clause = ", ".join(
            (
                f"'has_header' '{str(has_header).lower()}'",
                f"'delimiter' '{delimiter}'",
            )
        )
        shard_table_names: list[str] = []
        for index, shard_path in enumerate(file_paths):
            shard_table = f"{table_name}__shard_{index}"
            shard_sql = f"""
                CREATE EXTERNAL TABLE {shard_table} {schema_clause}
                STORED AS CSV
                LOCATION '{shard_path}'
                OPTIONS ({shard_options_clause})
            """
            try:
                connection.sql(shard_sql)
            except Exception as e:
                self.log_verbose(f"Error creating shard external table {shard_table}: {e}")
                raise RuntimeError(f"Failed to create shard external table {shard_table}: {e}") from e
            shard_table_names.append(shard_table)

        union_body = " UNION ALL ".join(f"SELECT * FROM {name}" for name in shard_table_names)
        view_sql = f"CREATE OR REPLACE VIEW {table_name} AS {union_body}"
        try:
            connection.sql(view_sql)
            self.log_very_verbose(
                f"Created external table view {table_name} unioning {len(shard_table_names)} shard(s) "
                "(no shared filename prefix; avoiding parent-glob to keep row counts correct)"
            )
        except Exception as e:
            self.log_verbose(f"Error creating union view {table_name}: {e}")
            raise RuntimeError(f"Failed to create union view {table_name}: {e}") from e

        try:
            result = connection.sql(f"SELECT COUNT(*) FROM {table_name}").collect()
            return int(result[0].column(0)[0])
        except Exception as e:
            self.log_verbose(f"Error counting rows in {table_name} (union view): {e}")
            raise RuntimeError(f"Failed to count rows in {table_name}: {e}") from e

    def _map_to_arrow_type(self, sql_type: str) -> str:
        """Map SQL types to Arrow/DataFusion types.

        This mapping is used when creating external CSV tables with explicit schemas.
        For Parquet tables, PyArrow infers types automatically during CSV parsing.
        """
        sql_type_upper = sql_type.upper()

        # Map common SQL types to DataFusion types
        type_mapping = {
            "INTEGER": "INT",
            "BIGINT": "BIGINT",
            "DECIMAL": "DECIMAL",
            "DOUBLE": "DOUBLE",
            "FLOAT": "FLOAT",
            "VARCHAR": "VARCHAR",
            "CHAR": "VARCHAR",
            "TEXT": "VARCHAR",
            "DATE": "DATE",
            "TIMESTAMP": "TIMESTAMP",
            "BOOLEAN": "BOOLEAN",
        }

        # Check for parameterized types like DECIMAL(10,2) or VARCHAR(100)
        base_type = sql_type_upper.split("(")[0]

        if base_type in type_mapping:
            # For parameterized types, preserve the parameters
            if "(" in sql_type_upper:
                return f"{type_mapping[base_type]}{sql_type_upper[len(base_type) :]}"
            return type_mapping[base_type]

        # Return as-is if not in mapping (assume it's already valid)
        return sql_type

    def _load_table_parquet(
        self,
        connection: Any,
        table_name: str,
        file_paths: list[Path],
        data_dir: Path,
        csv_format: str | None = None,
        data_source: DataSource | None = None,
        benchmark: Any = None,
    ) -> int:
        """Load table as Parquet, converting from CSV/TBL if needed.

        If the input files are already Parquet, registers them directly.
        Otherwise, converts CSV/TBL to Parquet first, preserving column names from schema.
        """
        import pyarrow as pa
        import pyarrow.parquet as pq

        # Check if input files are already Parquet
        input_is_parquet = all(self._is_parquet_file(fp) for fp in file_paths)

        if input_is_parquet:
            return self._register_parquet_files(connection, table_name, file_paths)

        return self._convert_and_register_parquet(
            connection,
            table_name,
            file_paths,
            pa,
            pq,
            csv_format=csv_format,
            data_source=data_source,
            benchmark=benchmark,
        )

    def _is_parquet_file(self, file_path: Path) -> bool:
        """Check if a file is Parquet by extension (stripping compression suffixes)."""
        name = file_path.name
        # Strip known compression suffixes
        for suffix in (".zst", ".gz", ".bz2", ".lz4", ".snappy"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        return name.endswith(".parquet")

    def _register_parquet_files(self, connection: Any, table_name: str, file_paths: list[Path]) -> int:
        """Register pre-existing Parquet files directly with DataFusion.

        DataFusion lowercases unquoted SQL identifiers at parse time, so any parquet
        file with mixed-case column names (e.g. ClickBench's AdvEngineID, UserID)
        must have its columns renamed to lowercase before registration.
        """
        import pyarrow.parquet as pq

        if len(file_paths) == 1:
            parquet_path = str(file_paths[0])
            self.log_very_verbose(f"Registering existing Parquet file for {table_name}: {parquet_path}")
            schema = pq.read_schema(file_paths[0])
            if any(name != name.lower() for name in schema.names):
                # Mixed-case columns: stream row-groups through a rename to avoid
                # loading the full file into memory (ClickBench SF1 is ~14 GB).
                import pyarrow as pa

                new_schema = pa.schema([field.with_name(field.name.lower()) for field in schema])
                self.working_dir.mkdir(exist_ok=True)
                norm_path = self.working_dir / f"{table_name}.parquet"
                row_count = 0
                pf = pq.ParquetFile(file_paths[0])
                with pq.ParquetWriter(norm_path, new_schema, compression="snappy") as writer:
                    for batch in pf.iter_batches():
                        renamed = batch.rename_columns([c.lower() for c in batch.schema.names])
                        writer.write_batch(renamed)
                        row_count += renamed.num_rows
                connection.register_parquet(table_name, str(norm_path))
                return row_count
            row_count = pq.read_metadata(file_paths[0]).num_rows
            connection.register_parquet(table_name, parquet_path)
            return row_count

        # Multiple parquet files: concatenate into single file in working directory
        import pyarrow as pa

        self.log_very_verbose(f"Concatenating {len(file_paths)} Parquet files for {table_name}")
        tables = []
        for fp in file_paths:
            tables.append(pq.read_table(fp))
        combined = pa.concat_tables(tables)
        if any(name != name.lower() for name in combined.schema.names):
            combined = combined.rename_columns([c.lower() for c in combined.schema.names])

        parquet_file = self.working_dir / f"{table_name}.parquet"
        self.working_dir.mkdir(exist_ok=True)
        pq.write_table(combined, parquet_file, compression="snappy")
        connection.register_parquet(table_name, str(parquet_file))
        return combined.num_rows

    @staticmethod
    def _detect_directory_format(file_paths: list[Path]) -> str | None:
        """Detect if file paths point to a directory-based table format.

        Returns 'delta', 'iceberg', or None for file-based formats.
        """
        if len(file_paths) != 1:
            return None
        path = file_paths[0]
        if not path.is_dir():
            return None
        if (path / "_delta_log").is_dir():
            return "delta"
        if (path / "metadata").is_dir():
            return "iceberg"
        return None

    def _load_table_delta(self, connection: Any, table_name: str, table_path: Path) -> int:
        """Load a Delta Lake table into DataFusion via deltalake + PyArrow."""
        try:
            from deltalake import DeltaTable
        except ImportError as e:
            raise RuntimeError(
                "Delta Lake support requires the 'deltalake' package. "
                "Install it with: uv add deltalake --optional table-formats"
            ) from e

        self.log_very_verbose(f"Loading Delta Lake table for {table_name}: {table_path}")
        delta_table = DeltaTable(str(table_path))
        arrow_table = delta_table.to_pyarrow_table()

        # Normalize column names to lowercase: DataFusion lowercases unquoted identifiers
        # at parse time, so any mixed-case column (e.g. SK_CustomerID) must be stored lowercase.
        if any(name != name.lower() for name in arrow_table.schema.names):
            arrow_table = arrow_table.rename_columns([c.lower() for c in arrow_table.schema.names])

        batches = arrow_table.to_batches()
        if batches:
            connection.register_record_batches(table_name, [batches])
        else:
            # Empty table - register with schema but no data
            import pyarrow as pa

            empty_batch = pa.RecordBatch.from_pydict(
                {name: [] for name in arrow_table.schema.names},
                schema=arrow_table.schema,
            )
            connection.register_record_batches(table_name, [[empty_batch]])

        self.log_very_verbose(f"Registered Delta table {table_name}: {arrow_table.num_rows:,} rows")
        return arrow_table.num_rows

    def _load_table_iceberg(self, connection: Any, table_name: str, table_path: Path) -> int:
        """Load an Iceberg table into DataFusion via pyiceberg + PyArrow."""
        try:
            from pyiceberg.catalog.sql import SqlCatalog
        except ImportError as e:
            raise RuntimeError(
                "Iceberg support requires the 'pyiceberg' package. "
                "Install it with: uv add pyiceberg --optional table-formats"
            ) from e

        self.log_very_verbose(f"Loading Iceberg table for {table_name}: {table_path}")

        # Use a file-based SQLite catalog pointing at the table's warehouse
        catalog = SqlCatalog(
            "benchbox",
            uri=f"sqlite:///{table_path}/catalog.db",
            warehouse=str(table_path.parent),
        )

        ice_table = catalog.load_table(f"default.{table_name}")
        arrow_table = ice_table.scan().to_arrow()

        # Normalize column names to lowercase: DataFusion lowercases unquoted identifiers
        # at parse time, so any mixed-case column must be stored lowercase.
        if any(name != name.lower() for name in arrow_table.schema.names):
            arrow_table = arrow_table.rename_columns([c.lower() for c in arrow_table.schema.names])

        batches = arrow_table.to_batches()
        if batches:
            connection.register_record_batches(table_name, [batches])
        else:
            import pyarrow as pa

            empty_batch = pa.RecordBatch.from_pydict(
                {name: [] for name in arrow_table.schema.names},
                schema=arrow_table.schema,
            )
            connection.register_record_batches(table_name, [[empty_batch]])

        self.log_very_verbose(f"Registered Iceberg table {table_name}: {arrow_table.num_rows:,} rows")
        return arrow_table.num_rows

    @staticmethod
    def _map_schema_type_to_pyarrow(col_type: str, pa: Any) -> Any | None:
        """Map a BenchBox schema type to a PyArrow type, or None for auto-inference."""
        if col_type.startswith(("CHAR", "VARCHAR", "TEXT", "STRING")):
            return pa.string()
        if col_type.startswith("DATE"):
            return pa.date32()
        if col_type.startswith(("DECIMAL", "NUMERIC", "FLOAT", "REAL", "DOUBLE")):
            # float64 avoids precision hassles for DECIMAL/NUMERIC in benchmarks
            return pa.float64()
        if col_type.startswith("BIGINT") or col_type.startswith("INT8"):
            return pa.int64()
        if col_type.startswith(("INTEGER", "INT4", "INT ")) or col_type in ("INT", "SMALLINT", "TINYINT"):
            return pa.int32()
        if col_type.startswith("BOOLEAN"):
            return pa.bool_()
        if col_type.startswith("TIMESTAMP"):
            return pa.timestamp("us")
        return None

    def _build_pyarrow_columns(self, table_name: str, pa: Any) -> tuple[list[str] | None, dict[str, Any] | None]:
        """Resolve (column_names, column_types) for a table's CSV → Parquet conversion."""
        schema_info = self._table_schemas.get(table_name, {})
        columns = schema_info.get("columns", [])
        if not columns:
            self.log_verbose(f"Warning: No schema found for {table_name}, using auto-generated column names")
            return None, None

        column_names = [col["name"].lower() for col in columns]
        column_types: dict[str, Any] = {}
        for col in columns:
            col_name = col["name"].lower()
            col_type = col.get("type", "VARCHAR").upper()
            pa_type = self._map_schema_type_to_pyarrow(col_type, pa)
            if pa_type is not None:
                column_types[col_name] = pa_type
        self.log_very_verbose(f"Using {len(column_names)} columns from schema for {table_name}: {column_names}")
        return column_names, column_types

    def _write_csv_file_to_parquet(
        self,
        file_path: Path,
        parquet_file: Path,
        writer_ref: list[Any],
        read_opts: Any,
        parse_opts: Any,
        conv_opts: Any,
        pq: Any,
        csv_mod: Any,
        table_name: str,
    ) -> int:
        """Convert a single CSV file to the shared Parquet writer; returns row count."""
        file_size = file_path.stat().st_size if file_path.exists() else 0
        try:
            if file_size > _CSV_TO_PARQUET_STREAM_THRESHOLD:
                self.log_verbose(
                    f"Streaming {file_path.name} ({file_size / (1024**3):.1f} GB) to Parquet for {table_name}"
                )
                reader = csv_mod.open_csv(
                    file_path, read_options=read_opts, parse_options=parse_opts, convert_options=conv_opts
                )
                rows = 0
                for batch in reader:
                    if writer_ref[0] is None:
                        writer_ref[0] = pq.ParquetWriter(parquet_file, batch.schema, compression="snappy")
                    writer_ref[0].write_batch(batch)
                    rows += batch.num_rows
                return rows

            table = csv_mod.read_csv(
                file_path, read_options=read_opts, parse_options=parse_opts, convert_options=conv_opts
            )
            if writer_ref[0] is None:
                writer_ref[0] = pq.ParquetWriter(parquet_file, table.schema, compression="snappy")
            writer_ref[0].write_table(table)
            return table.num_rows
        except Exception as e:
            self.log_verbose(f"Error processing CSV file {file_path}: {e}")
            raise RuntimeError(f"Failed to process CSV file {file_path}: {e}") from e

    def _register_parquet_or_cleanup(self, connection: Any, table_name: str, parquet_file: Path) -> None:
        """Register the parquet file in DataFusion; delete the file on failure."""
        try:
            connection.register_parquet(table_name, str(parquet_file))
        except Exception as e:
            try:
                if parquet_file.exists():
                    parquet_file.unlink()
                    self.log_very_verbose(f"Cleaned up orphaned Parquet file: {parquet_file}")
            except Exception as cleanup_error:
                self.log_very_verbose(f"Could not clean up Parquet file: {cleanup_error}")
            self.log_verbose(f"Error registering Parquet table {table_name}: {e}")
            raise RuntimeError(f"Failed to register Parquet table {table_name}: {e}") from e

    def _convert_and_register_parquet(
        self,
        connection: Any,
        table_name: str,
        file_paths: list[Path],
        pa: Any,
        pq: Any,
        csv_format: str | None = None,
        data_source: DataSource | None = None,
        benchmark: Any = None,
    ) -> int:
        """Convert CSV/TBL files to Parquet and register with DataFusion."""
        import pyarrow.csv as csv

        parquet_dir = self.working_dir
        parquet_dir.mkdir(exist_ok=True)
        parquet_file = parquet_dir / f"{table_name}.parquet"

        dialect = resolve_csv_dialect(
            data_source or DataSource(source_type="datafusion_csv", tables={}),
            table_name,
            file_paths[0],
            benchmark if benchmark is not None else NO_BENCHMARK,
        )
        delimiter = self._detect_csv_format(
            file_paths,
            csv_format=csv_format,
            data_source=data_source,
            table_name=table_name,
            benchmark=benchmark,
        )
        column_names, column_types = self._build_pyarrow_columns(table_name, pa)

        self.log_very_verbose(f"Converting {len(file_paths)} CSV file(s) to Parquet for {table_name}")

        read_opts = csv.ReadOptions(
            column_names=column_names,
            autogenerate_column_names=(column_names is None and not dialect.has_header),
            skip_rows=1 if column_names is not None and dialect.has_header else 0,
        )
        parse_opts = csv.ParseOptions(delimiter=delimiter, quote_char='"', escape_char="\\")
        conv_opts = csv.ConvertOptions(null_values=[""], strings_can_be_null=True, column_types=column_types)

        # writer_ref is a single-slot list so the helper can lazily open the shared writer
        writer_ref: list[Any] = [None]
        total_rows = 0
        try:
            for file_path in file_paths:
                total_rows += self._write_csv_file_to_parquet(
                    file_path, parquet_file, writer_ref, read_opts, parse_opts, conv_opts, pq, csv, table_name
                )
        finally:
            if writer_ref[0] is not None:
                writer_ref[0].close()

        self.log_very_verbose(f"Created Parquet file: {parquet_file} ({total_rows:,} rows)")

        self._register_parquet_or_cleanup(connection, table_name, parquet_file)
        return total_rows

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply DataFusion-specific optimizations based on benchmark type."""
        # DataFusion optimizations are set during connection creation
        # Additional benchmark-specific settings can be added here
        self.log_verbose(f"DataFusion configured for {benchmark_type} benchmark")

    def get_query_plan(self, connection: Any, query: str) -> str | None:
        """Get DataFusion query execution plan using EXPLAIN.

        DataFusion's EXPLAIN returns a DataFrame with columns (plan_type, plan).
        We reconstruct the pipe-delimited text format expected by DataFusionQueryPlanParser.
        """
        try:
            batches = connection.sql(f"EXPLAIN {query}").collect()
            if not batches:
                return None
            parts = []
            for batch in batches:
                for i in range(batch.num_rows):
                    plan_type = batch.column(0)[i].as_py()
                    plan_text = batch.column(1)[i].as_py()
                    if not plan_text:
                        continue
                    lines = plan_text.split("\n")
                    prefix = " " * len(plan_type)
                    parts.append(f"{plan_type} | {lines[0]}")
                    for line in lines[1:]:
                        parts.append(f"{prefix} | {line}")
            return "\n".join(parts) if parts else None
        except Exception as e:
            self.logger.debug(f"Failed to get DataFusion query plan: {e}")
            return None

    def get_query_plan_parser(self):
        """Get DataFusion query plan parser."""
        from benchbox.core.query_plans.parsers.datafusion import DataFusionQueryPlanParser

        return DataFusionQueryPlanParser()

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
        """Execute query with detailed timing and result collection."""
        self.log_verbose(f"Executing query {query_id}")
        self.log_very_verbose(f"Query SQL (first 200 chars): {query[:200]}{'...' if len(query) > 200 else ''}")

        # Apply DataFusion-specific query transformations for SQL compatibility
        from benchbox.platforms.datafusion_query_transformer import DataFusionQueryTransformer

        transformer = DataFusionQueryTransformer(verbose=getattr(self, "very_verbose", False))
        query = transformer.transform(query, query_id=query_id)
        if transformer.get_transformations_applied():
            self.log_verbose(
                f"Query {query_id}: Applied transformations: {', '.join(transformer.get_transformations_applied())}"
            )

        # In dry-run mode we intentionally capture transformed SQL so output
        # reflects what DataFusion would execute after compatibility rewrites.
        if self.dry_run_mode:
            self.capture_sql(query, "query", None)
            self.log_very_verbose(f"Captured query {query_id} for dry-run")

            return {
                "query_id": query_id,
                "status": "DRY_RUN",
                "execution_time_seconds": 0.0,
                "rows_returned": 0,
                "first_row": None,
                "error": None,
                "dry_run": True,
            }

        start_time = mono_time()

        try:
            # Execute the query
            df = connection.sql(query)

            # Collect results
            result_batches = df.collect()

            # Calculate total rows
            actual_row_count = sum(batch.num_rows for batch in result_batches)

            # Get first row if results exist
            first_row = None
            if result_batches and result_batches[0].num_rows > 0:
                # Convert first row to tuple
                first_batch = result_batches[0]
                first_row = tuple(
                    first_batch.column(i)[0].as_py()
                    if hasattr(first_batch.column(i)[0], "as_py")
                    else first_batch.column(i)[0]
                    for i in range(first_batch.num_columns)
                )

            execution_time = elapsed_seconds(start_time)
            logger.debug(f"Query {query_id} completed in {execution_time:.3f}s, returned {actual_row_count} rows")

            # Validate row count if enabled
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

            # Use centralized helper to build result with validation
            result = self._build_query_result_with_validation(
                query_id=query_id,
                execution_time=execution_time,
                actual_row_count=actual_row_count,
                first_row=first_row,
                validation_result=validation_result,
            )

            # Capture structured query plan if enabled
            if self.capture_plans:
                query_plan, plan_capture_time_ms = self.capture_query_plan(connection, query, query_id)
                if query_plan:
                    result["query_plan"] = query_plan
                    result["plan_fingerprint"] = query_plan.plan_fingerprint
                if plan_capture_time_ms is not None:
                    result["plan_capture_time_ms"] = plan_capture_time_ms

            return result

        except Exception as e:
            execution_time = elapsed_seconds(start_time)
            logger.error(
                f"Query {query_id} failed after {execution_time:.3f}s: {e}",
                exc_info=True,
            )

            return {
                "query_id": query_id,
                "status": "FAILED",
                "execution_time_seconds": execution_time,
                "rows_returned": 0,
                "error": str(e),
                "error_type": type(e).__name__,
            }

    def check_database_exists(self, **connection_config) -> bool:
        """Check if DataFusion working directory exists with data."""
        working_dir = Path(connection_config.get("working_dir", self.working_dir))

        if not working_dir.exists():
            return False

        # Check if working directory has parquet files
        if any(working_dir.glob("*.parquet")):
            return True

        return False

    def drop_database(self, **connection_config) -> None:
        """Drop DataFusion working directory and all data."""
        import shutil

        working_dir = Path(connection_config.get("working_dir", self.working_dir))

        if working_dir.exists():
            self.logger.warning(f"Removing DataFusion working directory: {working_dir}")
            shutil.rmtree(working_dir)
            self.logger.warning("DataFusion working directory removed")

    def validate_platform_capabilities(self, benchmark_type: str):
        """Validate DataFusion-specific capabilities for the benchmark."""
        from benchbox.core.validation import ValidationResult

        errors = []
        warnings = []

        # Check if DataFusion is available
        if SessionContext is None:
            errors.append("DataFusion library not available - install with 'pip install datafusion'")
        else:
            # Check DataFusion version
            try:
                import datafusion as df_module

                version = df_module.__version__
                self.log_very_verbose(f"DataFusion version: {version}")
            except (ImportError, AttributeError):
                warnings.append("Could not determine DataFusion version")

        # Warn about TPC-DS limitations
        if benchmark_type.lower() == "tpcds":
            warnings.append("Some TPC-DS queries may fail due to DataFusion SQL feature limitations")

        # Check memory configuration
        if self.memory_limit:
            try:
                memory_bytes = int(self._parse_memory_limit(self.memory_limit))
                memory_gb = memory_bytes / (1024**3)

                if memory_gb < 2.0:
                    warnings.append(f"Memory limit ({self.memory_limit}) may be insufficient for larger scale factors")
            except (ValueError, TypeError):
                warnings.append(f"Could not parse memory limit: {self.memory_limit}")

        platform_info = {
            "platform": self.platform_name,
            "benchmark_type": benchmark_type,
            "dry_run_mode": self.dry_run_mode,
            "datafusion_available": SessionContext is not None,
            "working_dir": str(self.working_dir),
            "memory_limit": self.memory_limit,
            "target_partitions": self.target_partitions,
            "data_format": self.data_format,
        }

        if SessionContext:
            try:
                import datafusion as df_module

                platform_info["datafusion_version"] = df_module.__version__
            except (ImportError, AttributeError):
                # Version attribute not available in this DataFusion version
                pass

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            details=platform_info,
        )

    def _get_existing_tables(self, connection) -> list[str]:
        """Get list of existing tables in DataFusion SessionContext.

        Override base class method to use DataFusion's catalog API instead of
        information_schema queries.
        """
        try:
            # DataFusion SessionContext has a catalog() method to list tables
            # Get all registered tables
            tables = []

            # DataFusion stores tables in a catalog structure
            # Use SHOW TABLES to get list of tables
            result = connection.sql("SHOW TABLES")
            rows = result.collect()

            # Extract table names from the result
            # SHOW TABLES returns a DataFrame with columns:
            # [table_catalog, table_schema, table_name, table_type]
            for batch in rows:
                # Convert to pydict to get table names
                data = batch.to_pydict()
                # Get the 'table_name' column specifically
                if data and "table_name" in data:
                    tables.extend([name.lower() for name in data["table_name"]])

            return tables
        except Exception as e:
            self.log_verbose(f"Error getting existing tables: {e}")
            # Fallback - return empty list if query fails
            return []

    def _validate_data_integrity(
        self, benchmark, connection, table_stats: dict[str, int]
    ) -> tuple[str, dict[str, Any]]:
        """Validate basic data integrity using DataFusion SessionContext API.

        Override base class method to use DataFusion's ctx.sql() instead of
        DB-API 2.0 cursor interface.
        """
        validation_details = {}

        try:
            # DataFusion connection is a SessionContext, not a DB-API 2.0 connection
            # Use ctx.sql() to validate table accessibility
            accessible_tables = []
            inaccessible_tables = []

            for table_name in table_stats:
                try:
                    # Try a simple SELECT to verify table is accessible
                    # Use SessionContext.sql() which returns a DataFrame
                    result = connection.sql(f"SELECT 1 FROM {table_name} LIMIT 1")
                    # Execute the query to verify it works
                    result.collect()
                    accessible_tables.append(table_name)
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
