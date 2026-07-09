"""DuckDB platform adapter with data loading and query execution.

Provides DuckDB-specific optimizations including fast bulk data loading
using DuckDB's native CSV reading capabilities.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.runtime_env import DriverResolution, DriverRuntimeStrategy, load_driver_module

try:
    import duckdb
except ImportError:
    duckdb = None

from benchbox.core.errors import PlanCaptureError
from benchbox.utils.cloud_storage import get_cloud_path_info, is_cloud_path
from benchbox.utils.printing import emit

from .base import DriverIsolationCapability, PlatformAdapter
from .base.ddl_helpers import strip_foreign_keys

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import TuningColumn

logger = logging.getLogger(__name__)


def _normalize_duckdb_version(raw_version: Any) -> str | None:
    """Normalize DuckDB version strings (e.g., 'v1.2.2' -> '1.2.2')."""
    if raw_version is None:
        return None
    version = str(raw_version).strip()
    if not version:
        return None
    if version.startswith("v") and len(version) > 1 and version[1].isdigit():
        version = version[1:]
    return version


class DuckDBConnectionWrapper:
    """Wrapper for DuckDB connection that supports dry-run mode."""

    def __init__(self, connection, platform_adapter):
        self._connection = connection
        self._platform_adapter = platform_adapter

    def execute(self, query: str, parameters=None):
        """Execute query, capturing SQL in dry-run mode."""
        if self._platform_adapter.dry_run_mode:
            # Capture SQL instead of executing
            self._platform_adapter.capture_sql(query, "query", None)
            # Return a lightweight cursor wrapper for dry-run flows.
            return DuckDBCursorWrapper([], self._platform_adapter)
        else:
            # Normal execution
            return self._connection.execute(query, parameters)

    def commit(self):
        """Commit transaction (no-op in dry-run mode)."""
        if not self._platform_adapter.dry_run_mode and hasattr(self._connection, "commit"):
            self._connection.commit()

    def close(self):
        """Close connection (no-op in dry-run mode)."""
        if not self._platform_adapter.dry_run_mode:
            self._connection.close()

    def __getattr__(self, name):
        """Delegate other attributes to the real connection."""
        return getattr(self._connection, name)


class DuckDBCursorWrapper:
    """Cursor wrapper used in dry-run mode."""

    def __init__(self, rows, platform_adapter):
        self._rows = rows
        self._platform_adapter = platform_adapter

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return None if not self._rows else self._rows[0]

    def fetchmany(self, size=None):
        return self._rows[:size] if size else self._rows


def _build_duckdb_ctas_sort_sql(table_name: str, sort_columns) -> str:
    """Build DuckDB-compatible CTAS sort SQL shared by DuckDB and MotherDuck adapters.

    ``sort_columns`` must be pre-sorted by the caller (ascending by ``column.order``).
    """
    order_by_clause = ", ".join(column.name for column in sort_columns)
    return f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM {table_name} ORDER BY {order_by_clause};"


def _resolve_external_data_source(benchmark: Any, data_dir: Path, adapter: Any = None) -> Any:
    """Resolve the DataSource for external table/view registration."""
    from benchbox.platforms.base.data_loading import DataSourceResolver

    return DataSourceResolver(
        platform_name="duckdb",
        table_mode=getattr(adapter, "table_mode", "native") if adapter else "native",
        platform_config=getattr(adapter, "config", None) if adapter else None,
        requested_format=getattr(adapter, "requested_table_format", None) if adapter else None,
    ).resolve(benchmark, data_dir)


def _external_table_sources_from_data_source(source: Any) -> dict[str, list[Path]]:
    """Normalize a resolved DataSource into table->existing paths for external views."""
    if source is None:
        return {}

    table_sources: dict[str, list[Path]] = {}
    for table_name, raw_paths in source.tables.items():
        candidates = raw_paths if isinstance(raw_paths, list) else [raw_paths]
        normalized_paths = [Path(path) for path in candidates if Path(path).exists()]
        if normalized_paths:
            table_sources[table_name] = normalized_paths

    return table_sources


def _try_delta_scan(
    connection: Any,
    source_paths: list[Path],
    ext_loaded: bool,
) -> tuple[str, bool] | None:
    """Try Delta scan if source is a single directory with _delta_log."""
    from benchbox.platforms.base.data_loading import escape_sql_string_literal

    if len(source_paths) != 1 or not source_paths[0].is_dir() or not (source_paths[0] / "_delta_log").is_dir():
        return None
    if not ext_loaded:
        connection.execute("INSTALL delta")
        connection.execute("LOAD delta")
    escaped = escape_sql_string_literal(str(source_paths[0]))
    return f"delta_scan('{escaped}')", True


def _try_iceberg_scan(
    connection: Any,
    source_paths: list[Path],
    ext_loaded: bool,
) -> tuple[str, bool] | None:
    """Try Iceberg scan if source is a single directory with metadata/."""
    from benchbox.platforms.base.data_loading import escape_sql_string_literal

    if len(source_paths) != 1 or not source_paths[0].is_dir() or not (source_paths[0] / "metadata").is_dir():
        return None
    if not ext_loaded:
        connection.execute("INSTALL iceberg")
        connection.execute("LOAD iceberg")
    escaped = escape_sql_string_literal(str(source_paths[0]))
    return f"iceberg_scan('{escaped}')", True


def _try_vortex_scan(
    connection: Any,
    source_paths: list[Path],
    ext_loaded: bool,
) -> tuple[str, bool] | None:
    """Try Vortex scan if any source paths are .vortex files."""
    from benchbox.platforms.base.data_loading import escape_sql_string_literal

    vortex_paths: list[Path] = []
    for path in source_paths:
        if path.is_dir():
            vortex_paths.extend(sorted(path.glob("*.vortex")))
        elif path.suffix.lower() == ".vortex":
            vortex_paths.append(path)
    if not vortex_paths:
        return None

    if not ext_loaded:
        try:
            connection.execute("INSTALL vortex")
            connection.execute("LOAD vortex")
        except Exception as e:
            raise RuntimeError(
                "DuckDB external table mode for Vortex files requires the DuckDB vortex extension. "
                "Install/load failed. Ensure your DuckDB runtime supports the extension, "
                "or use --table-mode native."
            ) from e

    escaped_paths = [escape_sql_string_literal(str(p)) for p in vortex_paths]
    if len(escaped_paths) == 1:
        scan_expr = f"read_vortex('{escaped_paths[0]}')"
    else:
        union_terms = [f"SELECT * FROM read_vortex('{p}')" for p in escaped_paths]
        scan_expr = "(" + " UNION ALL ".join(union_terms) + ")"

    try:
        connection.execute(f"SELECT * FROM {scan_expr} LIMIT 1").fetchall()
    except Exception as probe_error:
        raise RuntimeError(
            "DuckDB cannot read these Vortex files. This typically occurs when files were "
            "written by Python Vortex bindings instead of the DuckDB vortex extension. "
            "Re-run with --force datagen to regenerate files using the DuckDB extension writer, "
            "or use --table-mode native to load data into DuckDB tables directly."
        ) from probe_error

    return scan_expr, True


def _try_parquet_scan(source_paths: list[Path]) -> str | None:
    """Try Parquet scan if any source paths are .parquet files."""
    from benchbox.platforms.base.data_loading import escape_sql_string_literal

    parquet_paths: list[Path] = []
    for path in source_paths:
        if path.is_dir():
            parquet_paths.extend(sorted(path.glob("*.parquet")))
        elif path.suffix.lower() == ".parquet":
            parquet_paths.append(path)
    if not parquet_paths:
        return None

    escaped = [escape_sql_string_literal(str(p)) for p in parquet_paths]
    if len(escaped) == 1:
        return f"read_parquet('{escaped[0]}')"
    path_array = "[" + ", ".join(f"'{p}'" for p in escaped) + "]"
    return f"read_parquet({path_array})"


def _try_text_scan(
    source_paths: list[Path],
    column_names: list[str] | None,
    *,
    data_source: Any | None = None,
    table_name: str | None = None,
    benchmark: Any | None = None,
) -> tuple[str, str] | None:
    """Try text file scan (TBL/CSV/DAT) if any source paths match."""
    from benchbox.utils.file_format import detect_data_format

    text_paths: list[Path] = []
    detected_fmt = "csv"
    for path in source_paths:
        if not path.is_dir():
            fmt = detect_data_format(path)
            if fmt in ("tbl", "csv"):
                text_paths.append(path)
                detected_fmt = fmt
    if not text_paths:
        return None

    return (
        _build_csv_scan_expression(
            text_paths,
            column_names,
            data_source=data_source,
            table_name=table_name,
            benchmark=benchmark,
        ),
        detected_fmt,
    )


def _build_duckdb_external_scan_expression(
    connection: Any,
    source_paths: list[Path],
    *,
    delta_extension_loaded: bool,
    vortex_extension_loaded: bool,
    iceberg_extension_loaded: bool = False,
    column_names: list[str] | None = None,
    data_source: Any | None = None,
    table_name: str | None = None,
    benchmark: Any | None = None,
) -> tuple[str, bool, bool, bool, str]:
    """Build DuckDB scan expression for external table/view creation.

    Supports Parquet, Vortex, Delta, Iceberg, and delimited text files (TBL/CSV/DAT).
    For text files, ``column_names`` should be provided so the VIEW has
    correct column names (text files have no embedded schema).

    Returns:
        Tuple of (scan_expression, delta_ext_loaded, vortex_ext_loaded, iceberg_ext_loaded, format_name)
        where format_name is one of "parquet", "vortex", "delta", "iceberg", "tbl", or "csv".
    """
    result = _try_delta_scan(connection, source_paths, delta_extension_loaded)
    if result:
        return result[0], True, vortex_extension_loaded, iceberg_extension_loaded, "delta"

    result = _try_iceberg_scan(connection, source_paths, iceberg_extension_loaded)
    if result:
        return result[0], delta_extension_loaded, vortex_extension_loaded, True, "iceberg"

    result = _try_vortex_scan(connection, source_paths, vortex_extension_loaded)
    if result:
        return result[0], delta_extension_loaded, True, iceberg_extension_loaded, "vortex"

    parquet_expr = _try_parquet_scan(source_paths)
    if parquet_expr:
        return parquet_expr, delta_extension_loaded, vortex_extension_loaded, iceberg_extension_loaded, "parquet"

    text_result = _try_text_scan(
        source_paths,
        column_names,
        data_source=data_source,
        table_name=table_name,
        benchmark=benchmark,
    )
    if text_result:
        return text_result[0], delta_extension_loaded, vortex_extension_loaded, iceberg_extension_loaded, text_result[1]

    formatted_sources = ", ".join(str(path) for path in source_paths)
    raise RuntimeError(
        "DuckDB external table mode requires Parquet, Vortex, Delta, Iceberg, "
        f"or delimited text files (TBL/CSV/DAT). Received: {formatted_sources}"
    )


def _build_csv_scan_expression(
    text_paths: list[Path],
    column_names: list[str] | None,
    *,
    data_source: Any | None = None,
    table_name: str | None = None,
    benchmark: Any | None = None,
) -> str:
    """Build a ``read_csv()`` scan expression for DuckDB external views."""
    from benchbox.platforms.base.data_loading import (
        DUCKDB_NO_NULL_CONVERSION_SENTINEL,
        NO_BENCHMARK,
        DataSource,
        escape_sql_string_literal,
        resolve_csv_dialect,
    )
    from benchbox.utils.file_format import (
        get_column_names_with_trailing,
        has_trailing_delimiter,
    )

    dialect_source = data_source or DataSource(source_type="external_scan", tables={})
    dialect = resolve_csv_dialect(
        dialect_source,
        table_name or text_paths[0].stem,
        text_paths[0],
        benchmark if benchmark is not None else NO_BENCHMARK,
    )
    delimiter = dialect.delimiter
    escaped_paths = [escape_sql_string_literal(str(p)) for p in text_paths]
    if len(escaped_paths) == 1:
        path_expr = f"'{escaped_paths[0]}'"
    else:
        path_expr = "[" + ", ".join(f"'{p}'" for p in escaped_paths) + "]"

    csv_params = [
        f"delim='{escape_sql_string_literal(delimiter)}'",
        f"header={str(dialect.has_header).lower()}",
        "ignore_errors=true",
    ]
    null_marker = dialect.null_marker
    if null_marker is None:
        null_marker = DUCKDB_NO_NULL_CONVERSION_SENTINEL
    csv_params.append(f"nullstr='{escape_sql_string_literal(null_marker)}'")

    if column_names and not dialect.has_header:
        # Trailing-delimiter probing is only relevant for TPC-style sources where
        # rows look like `1|foo|` and need an absorbing dummy column. CSV dialects
        # without a null marker (e.g. ClickBench) never have trailing delimiters,
        # so we skip the disk read.
        trailing = dialect.null_marker is not None and has_trailing_delimiter(text_paths[0], delimiter, column_names)
        all_names = get_column_names_with_trailing(column_names, trailing)
        names_param = ", ".join(f"'{col}'" for col in all_names)
        csv_params.extend([f"names=[{names_param}]", "null_padding=true"])
        scan_expr = f"read_csv({path_expr}, {', '.join(csv_params)})"
        if trailing:
            select_cols = ", ".join(f'"{col}"' for col in column_names)
            return f"(SELECT {select_cols} FROM {scan_expr})"
        return scan_expr

    # No column names - fall back to auto_detect (columns will be column0, column1, …).
    csv_params.append("auto_detect=true")
    return f"read_csv({path_expr}, {', '.join(csv_params)})"


def _get_benchmark_column_names(benchmark: Any, table_name: str) -> list[str] | None:
    """Extract column names for *table_name* from benchmark schema, if available."""
    schema: dict | None = None
    if hasattr(benchmark, "_impl") and hasattr(benchmark._impl, "get_schema"):
        raw = benchmark._impl.get_schema()
        if isinstance(raw, dict):
            schema = raw
    if schema is None and hasattr(benchmark, "get_schema"):
        raw = benchmark.get_schema()
        if isinstance(raw, dict):
            schema = raw
    if not schema:
        return None
    table_def = schema.get(table_name)
    if not table_def or "columns" not in table_def:
        return None
    return [col["name"] for col in table_def["columns"]]


def _create_duckdb_external_views(
    adapter: Any,
    benchmark: Any,
    connection: Any,
    data_dir: Path,
) -> tuple[dict[str, int], float, dict[str, Any] | None]:
    """Create external DuckDB views over Parquet/Delta/text sources and return table stats."""
    from benchbox.platforms.base.data_loading import validate_sql_identifier

    start_time = mono_time()
    data_dir = Path(data_dir)
    source = _resolve_external_data_source(benchmark, data_dir, adapter=adapter)
    table_sources = _external_table_sources_from_data_source(source)
    if not table_sources:
        raise RuntimeError(f"No external source files found under {data_dir}")

    if hasattr(benchmark, "get_table_loading_order"):
        ordered_tables = benchmark.get_table_loading_order(list(table_sources.keys()))
    else:
        ordered_tables = sorted(table_sources.keys())

    table_stats: dict[str, int] = {}
    delta_loaded = False
    vortex_loaded = False
    iceberg_loaded = False
    detected_format: str | None = None
    for table_name in ordered_tables:
        if table_name not in table_sources:
            continue

        validated_table = validate_sql_identifier(table_name, "table name")
        col_names = _get_benchmark_column_names(benchmark, table_name)
        scan_expr, delta_loaded, vortex_loaded, iceberg_loaded, fmt = _build_duckdb_external_scan_expression(
            connection,
            table_sources[table_name],
            delta_extension_loaded=delta_loaded,
            vortex_extension_loaded=vortex_loaded,
            iceberg_extension_loaded=iceberg_loaded,
            column_names=col_names,
            data_source=source,
            table_name=table_name,
            benchmark=benchmark,
        )
        if detected_format is None:
            detected_format = fmt

        # DuckDB cannot CREATE OR REPLACE VIEW when a TABLE with the same name exists
        # (and vice-versa). Drop whichever object type currently occupies the name.
        existing = connection.execute(
            f"SELECT table_type FROM information_schema.tables "
            f"WHERE table_schema = 'main' AND table_name = '{validated_table}'"
        ).fetchone()
        if existing:
            if existing[0] == "BASE TABLE":
                connection.execute(f"DROP TABLE {validated_table}")
            else:
                connection.execute(f"DROP VIEW {validated_table}")
        connection.execute(f"CREATE VIEW {validated_table} AS SELECT * FROM {scan_expr}")
        row = connection.execute(f"SELECT COUNT(*) FROM {scan_expr}").fetchone()
        table_stats[table_name] = int(row[0]) if row else 0

    if detected_format is not None:
        adapter.external_format = detected_format
    loading_time = elapsed_seconds(start_time)
    return table_stats, loading_time, None


class DuckDBAdapter(PlatformAdapter):
    """DuckDB platform adapter with optimized bulk loading and execution."""

    driver_isolation_capability = DriverIsolationCapability.SUPPORTED
    supports_external_tables = True
    plan_capture_phase_eligible = True

    @property
    def platform_name(self) -> str:
        return "DuckDB"

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add DuckDB-specific CLI arguments."""
        duckdb_group = parser.add_argument_group("DuckDB Arguments")
        duckdb_group.add_argument("--duckdb-database-path", type=str, help="Path to DuckDB database file")
        duckdb_group.add_argument("--memory-limit", type=str, default="4GB", help="DuckDB memory limit")

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create DuckDB adapter from unified configuration."""
        from pathlib import Path

        from benchbox.utils.database_naming import generate_database_filename

        # Extract DuckDB-specific configuration
        adapter_config = {}

        # Database path handling
        if config.get("database_path"):
            adapter_config["database_path"] = config["database_path"]
        else:
            # Generate database path using naming utilities
            from benchbox.utils.path_utils import get_benchmark_runs_databases_path

            # Place local database artifacts in canonical benchmark_runs/databases.
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
                platform="duckdb",
                tuning_config=config.get("tuning_config"),
            )
            adapter_config["database_path"] = str(data_dir / db_filename)
            data_dir.mkdir(parents=True, exist_ok=True)

        # Memory limit
        adapter_config["memory_limit"] = config.get("memory_limit", "4GB")

        # Force recreate
        adapter_config["force_recreate"] = config.get("force", False)

        # Pass through other relevant config
        for key in ["tuning_config", "verbose_enabled", "very_verbose"]:
            if key in config:
                adapter_config[key] = config[key]
        for key in [
            "driver_package",
            "driver_version",
            "driver_version_requested",
            "driver_version_resolved",
            "driver_version_actual",
            "driver_runtime_strategy",
            "driver_runtime_path",
            "driver_runtime_python_executable",
            "driver_auto_install",
            "driver_auto_install_used",
        ]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get DuckDB platform information."""
        platform_info = {
            "platform_type": "duckdb",
            "platform_name": "DuckDB",
            "connection_mode": "memory" if self.database_path == ":memory:" else "file",
            "configuration": {
                "database_path": self.database_path,
                "memory_limit": self.memory_limit,
                "thread_limit": self.thread_limit,
                "max_temp_directory_size": self.max_temp_directory_size,
                "enable_progress_bar": self.enable_progress_bar,
                "result_cache_enabled": False,  # DuckDB has no persistent query result cache
            },
        }

        # Get DuckDB version and client library version from active runtime module.
        module_version = None
        if self._duckdb_module is not None:
            module_version = _normalize_duckdb_version(getattr(self._duckdb_module, "__version__", None))
            platform_info["client_library_version"] = module_version
            platform_info["platform_version"] = module_version
        else:
            platform_info["client_library_version"] = None
            platform_info["platform_version"] = None

        live_version = self._detect_connection_version(connection)
        if live_version:
            platform_info["platform_version"] = live_version
            platform_info["driver_version_actual"] = live_version
            self.driver_version_actual = live_version
        elif self.driver_version_actual:
            platform_info["driver_version_actual"] = self.driver_version_actual
        elif module_version:
            platform_info["driver_version_actual"] = module_version

        if self.driver_runtime_strategy:
            platform_info["driver_runtime_strategy"] = self.driver_runtime_strategy
        if self.driver_version_requested:
            platform_info["driver_version_requested"] = self.driver_version_requested
        if self.driver_version_resolved:
            platform_info["driver_version_resolved"] = self.driver_version_resolved
        if self.driver_version_actual:
            platform_info["driver_version_actual"] = self.driver_version_actual

        return platform_info

    def __init__(self, **config):
        super().__init__(**config)
        self._duckdb_module = self._initialize_duckdb_runtime(config)
        # DuckDB configuration
        self.database_path = config.get("database_path", ":memory:")
        self.memory_limit = config.get("memory_limit", "4GB")
        self.max_temp_directory_size = config.get("max_temp_directory_size")
        self.thread_limit = config.get("thread_limit")
        self.enable_progress_bar = config.get("progress_bar", False)

    def _initialize_duckdb_runtime(self, config: dict[str, Any]):
        """Resolve DuckDB module from the selected runtime contract."""
        global duckdb

        requested = config.get("driver_version_requested") or config.get("driver_version")
        has_runtime_contract = any(
            config.get(key) is not None
            for key in (
                "driver_runtime_strategy",
                "driver_runtime_path",
                "driver_version_requested",
                "driver_version_resolved",
                "driver_version",
            )
        )

        # Backward-compatible fast path: use already-imported module when no
        # runtime contract was requested.
        if not has_runtime_contract:
            if duckdb is not None:
                return duckdb
            raise ImportError("DuckDB not installed. Install with: pip install duckdb")

        resolution = DriverResolution(
            package=(config.get("driver_package") or "duckdb"),
            requested=requested,
            resolved=config.get("driver_version_resolved") or requested,
            actual=config.get("driver_version_actual"),
            auto_install_used=bool(config.get("driver_auto_install_used", False)),
            runtime_strategy=config.get("driver_runtime_strategy") or DriverRuntimeStrategy.CURRENT_PROCESS.value,
            runtime_path=config.get("driver_runtime_path"),
            runtime_python_executable=config.get("driver_runtime_python_executable"),
        )

        try:
            module = load_driver_module(
                import_name="duckdb",
                resolution=resolution,
                strict_version_check=bool(requested),
            )
        except Exception as exc:
            raise ImportError(
                "DuckDB runtime initialization failed. "
                "Install duckdb or provide a valid isolated runtime for the requested version."
            ) from exc

        # Keep legacy module-level alias aligned for compatibility with older paths.
        duckdb = module

        module_version = getattr(module, "__version__", None)
        if module_version:
            self.driver_version_actual = str(module_version)

        return module

    def _detect_connection_version(self, connection: Any) -> str | None:
        """Detect runtime version from a live DuckDB connection."""
        if connection is None:
            return None
        try:
            row = connection.execute("SELECT version()").fetchone()
        except Exception:
            return None
        if not row:
            return None
        if isinstance(row, (tuple, list)):
            if not row:
                return None
            candidate = row[0]
        elif isinstance(row, (str, bytes)):
            candidate = row
        else:
            return None
        return _normalize_duckdb_version(candidate)

    def get_database_path(self, **connection_config) -> str:
        """Get the database file path for DuckDB.

        Priority:
        1. connection_config["database_path"] if provided and not None
        2. self.database_path (set during from_config)
        3. ":memory:" as final fallback
        """
        # Use connection_config path if explicitly provided and not None
        db_path = connection_config.get("database_path")
        if db_path is not None:
            return db_path
        # Fall back to instance database_path (set during from_config)
        if self.database_path is not None:
            return self.database_path
        # Final fallback to in-memory database
        return ":memory:"

    def create_connection(self, **connection_config) -> Any:
        """Create optimized DuckDB connection."""
        self.log_operation_start("DuckDB connection")

        # Handle existing database using base class method
        self.handle_existing_database(**connection_config)

        db_path = self.get_database_path(**connection_config)
        self.log_very_verbose(f"DuckDB database path: {db_path}")

        # Create connection
        conn = self._duckdb_module.connect(db_path)
        self.log_very_verbose("DuckDB connection established")

        # Validate requested runtime against live execution context.
        live_version = self._detect_connection_version(conn)
        if live_version:
            self.driver_version_actual = live_version

        if self.driver_version_requested and live_version and self.driver_version_requested != live_version:
            raise RuntimeError(
                f"DuckDB runtime version mismatch: requested {self.driver_version_requested}, but live connection reports {live_version}."
            )

        # Apply DuckDB settings
        config_applied = []
        if self.memory_limit:
            conn.execute(f"SET memory_limit = '{self.memory_limit}'")
            config_applied.append(f"memory_limit={self.memory_limit}")
            self.log_very_verbose(f"DuckDB memory limit set to: {self.memory_limit}")

        if self.max_temp_directory_size:
            conn.execute(f"SET max_temp_directory_size = '{self.max_temp_directory_size}'")
            config_applied.append(f"max_temp_directory_size={self.max_temp_directory_size}")
            self.log_very_verbose(f"DuckDB max temp directory size set to: {self.max_temp_directory_size}")

        if self.thread_limit:
            conn.execute(f"SET threads TO {self.thread_limit}")
            config_applied.append(f"threads={self.thread_limit}")
            self.log_very_verbose(f"DuckDB thread limit set to: {self.thread_limit}")

        if self.enable_progress_bar:
            conn.execute("SET enable_progress_bar = true")
            config_applied.append("progress_bar=enabled")
            self.log_very_verbose("DuckDB progress bar enabled")

        # Optimize for OLAP workloads
        conn.execute("SET default_order = 'ASC'")
        config_applied.append("OLAP optimizations")
        self.log_very_verbose("DuckDB OLAP optimizations applied")
        # Note: enable_optimizer setting not available in current DuckDB versions

        # Enable profiling only when displaying plans; skip when capture_plans is active
        # (EXPLAIN ANALYZE handles plan capture separately without requiring profiling).
        if self.show_query_plans and not self.capture_plans:
            conn.execute("SET enable_profiling = 'query_tree_optimizer'")
            config_applied.append("query profiling")
            self.log_very_verbose("DuckDB query profiling enabled")

        self.log_operation_complete("DuckDB connection", details=f"Applied: {', '.join(config_applied)}")

        # Return wrapped connection for dry-run interception only when enabled
        if self.dry_run_mode:
            return DuckDBConnectionWrapper(conn, self)
        return conn

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using benchmark's SQL definitions."""
        start_time = mono_time()
        self.log_operation_start("Schema creation", f"benchmark: {benchmark.__class__.__name__}")

        # Get constraint settings from tuning configuration
        enable_primary_keys, enable_foreign_keys = self._get_constraint_configuration()
        self._log_constraint_configuration(enable_primary_keys, enable_foreign_keys)
        self.log_verbose(
            f"Schema constraints - Primary keys: {enable_primary_keys}, Foreign keys: {enable_foreign_keys}"
        )

        # Use common schema creation helper (no translation needed for DuckDB)
        schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")

        # For TPC-DS, remove foreign key constraints to avoid constraint violations during parallel loading
        benchmark_name = getattr(benchmark, "_name", "") or benchmark.__class__.__name__
        if "TPC-DS" in str(benchmark_name) or "TPCDS" in str(benchmark_name):
            schema_sql = strip_foreign_keys(schema_sql)

        # Split schema into individual CREATE TABLE statements for better compatibility
        # This handles foreign key constraints and complex multi-table schemas
        statements = []
        current_statement = []

        for line in schema_sql.split("\n"):
            if line.strip().startswith("CREATE TABLE") and current_statement:
                statements.append("\n".join(current_statement))
                current_statement = [line]
            else:
                current_statement.append(line)

        # Include the last statement
        if current_statement:
            statements.append("\n".join(current_statement))

        # Execute each CREATE TABLE statement separately
        tables_created = 0
        for statement in statements:
            if statement.strip():
                # Extract table name
                import re

                table_name = "unknown"
                match = re.search(r"CREATE TABLE\s+(\w+)", statement, re.IGNORECASE)
                if match:
                    table_name = match.group(1)

                if self.dry_run_mode:
                    self.capture_sql(statement, "create_table", table_name)
                    self.log_very_verbose(f"Captured CREATE TABLE statement for {table_name}")
                else:
                    try:
                        connection.execute(statement)
                        tables_created += 1
                        self.log_very_verbose(f"Created table: {table_name}")
                    except Exception as e:
                        raise Exception(f"Failed to create table {table_name}: {e}") from e

        duration = elapsed_seconds(start_time)
        self.log_operation_complete("Schema creation", duration, f"{tables_created} tables created")
        return duration

    def load_data(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data using DuckDB's optimized CSV reading capabilities."""
        from benchbox.platforms.base.data_loading import DataLoader

        # Check if using cloud storage and log
        if is_cloud_path(str(data_dir)):
            path_info = get_cloud_path_info(str(data_dir))
            self.log_verbose(f"Loading data from cloud storage: {path_info['provider']} bucket '{path_info['bucket']}'")
            emit(f"  Loading data from {path_info['provider']} cloud storage")

        # Create DuckDB-specific handler factory
        def duckdb_handler_factory(file_path, adapter, benchmark_instance, table_name=None, data_source=None):
            from benchbox.platforms.base.data_loading import (
                DuckDBDeltaHandler,
                DuckDBNativeHandler,
                DuckDBParquetHandler,
                FileFormatRegistry,
                resolve_csv_dialect,
            )

            # Check if this is a Delta Lake table directory
            if file_path.is_dir():
                delta_log_dir = file_path / "_delta_log"
                if delta_log_dir.exists() and delta_log_dir.is_dir():
                    return DuckDBDeltaHandler(adapter)

            # Determine the true base extension (handles names like *.tbl.1.zst)
            base_ext = FileFormatRegistry.get_base_data_extension(file_path)

            # Create DuckDB native handler for supported formats
            if base_ext in (".tbl", ".dat", ".csv"):
                from benchbox.platforms.base.data_loading import DataSource

                dialect_source = data_source or DataSource(source_type="duckdb_handler", tables={})
                dialect = resolve_csv_dialect(
                    dialect_source, table_name or file_path.stem, file_path, benchmark_instance
                )
                return DuckDBNativeHandler(
                    dialect.delimiter,
                    adapter,
                    benchmark_instance,
                    null_marker=dialect.null_marker,
                )
            elif base_ext == ".parquet":
                return DuckDBParquetHandler(adapter)
            return None  # Fall back to generic handler

        # Use DataLoader with DuckDB-specific handler.
        # Pass tuning_config so sorted tables are reordered via CTAS after loading.
        loader = DataLoader(
            adapter=self,
            benchmark=benchmark,
            connection=connection,
            data_dir=data_dir,
            handler_factory=duckdb_handler_factory,
            tuning_config=self.unified_tuning_configuration if self.tuning_enabled else None,
        )
        table_stats, loading_time = loader.load()
        # DataLoader doesn't provide per-table timings yet
        return table_stats, loading_time, None

    def create_external_tables(
        self, benchmark: Any, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Create DuckDB external views over Parquet/Delta sources."""
        return _create_duckdb_external_views(self, benchmark, connection, data_dir)

    def _build_ctas_sort_sql(self, table_name: str, sort_columns: list[TuningColumn]) -> str | None:
        """Build DuckDB CTAS SQL used by PlatformAdapter.apply_ctas_sort."""
        return _build_duckdb_ctas_sort_sql(table_name, sort_columns)

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply DuckDB-specific optimizations based on benchmark type."""
        # Enable profiling only when displaying plans; skip when capture_plans is active.
        if self.show_query_plans and not self.capture_plans:
            connection.execute("SET enable_profiling = 'query_tree'")

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
        """Execute query with detailed timing and profiling."""
        self.log_verbose(f"Executing query {query_id}")
        self.log_very_verbose(f"Query SQL (first 200 chars): {query[:200]}{'...' if len(query) > 200 else ''}")

        # In dry-run mode, capture SQL instead of executing
        if self.dry_run_mode:
            self.capture_sql(query, "query", None)
            self.log_very_verbose(f"Captured query {query_id} for dry-run")

            # Return a synthetic result payload for dry-run execution.
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
            # Enable profiling only if display is active (not when capture suppresses display)
            if self.show_query_plans and not self.capture_plans:
                connection.execute("PRAGMA enable_profiling = 'query_tree'")
                logger.debug("DuckDB query profiling enabled for this query")

            # Execute the query
            result = connection.execute(query)
            rows = result.fetchall()

            execution_time = elapsed_seconds(start_time)
            actual_row_count = len(rows)
            logger.debug(f"Query {query_id} completed in {execution_time:.3f}s, returned {actual_row_count} rows")

            # Display query plan if enabled; skip when capture_plans is also active
            # to avoid issuing EXPLAIN twice (display + capture would both call get_query_plan).
            if not self.capture_plans:
                self.display_query_plan_if_enabled(connection, query, query_id)

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

            # Gate-only value oracle: compute a digest of the FULL result set here,
            # where the rows are materialized (the power-test seam only sees
            # first_row + count). Behind BENCHBOX_EMIT_RESULT_DIGEST and stream 0 (the
            # only stream with a stored reference digest), so a normal run is unchanged.
            from benchbox.core.results.result_digest import compute_result_digest, result_digest_enabled

            result_digest = compute_result_digest(rows) if result_digest_enabled() and stream_id in (None, 0) else None

            # Use centralized helper to build result with consistent validation field mapping
            result = self._build_query_result_with_validation(
                query_id=query_id,
                execution_time=execution_time,
                actual_row_count=actual_row_count,
                first_row=rows[0] if rows else None,
                validation_result=validation_result,
                result_digest=result_digest,
            )

            # Capture and merge structured query plan (SUCCESS-guarded in the helper)
            self._merge_plan_capture_into_result(result, connection, query, query_id)

            return result

        except PlanCaptureError:
            raise
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
        finally:
            # Disable profiling if it was enabled (mirrors the enable condition)
            if self.show_query_plans and not self.capture_plans:
                connection.execute("PRAGMA disable_profiling")

    def get_query_plan(self, connection: Any, query: str) -> str | None:
        """Get DuckDB query execution plan using EXPLAIN (FORMAT JSON).

        Uses plain EXPLAIN (FORMAT JSON) by default (self.analyze_plans=False) to
        capture the estimated plan with no re-execution overhead: plan fingerprints
        are structure-only, so estimated plans lose nothing for structural comparison.

        When self.analyze_plans is True (opt-in), uses EXPLAIN (ANALYZE, FORMAT JSON)
        (PostgreSQL-style combined syntax) to capture actual per-operator timing and
        cardinality from real query execution. The ANALYZE format uses different field
        names than plain EXPLAIN (FORMAT JSON): operator_timing/operator_cardinality/
        operator_name vs timing/cardinality/name. DuckDBQueryPlanParser handles both
        schemas transparently. capture_query_plan() prints a one-time run-level notice
        the first time this opt-in actually captures a plan, since it roughly doubles
        wall-clock cost for a --capture-plans run and perturbs cache state.

        Note: EXPLAIN (ANALYZE, ...) re-executes the query, adding ~1× query cost to the
        capture step. Plan fingerprints are unaffected - compute_plan_fingerprint()
        excludes timing/cardinality by design.

        DML queries (INSERT/UPDATE/DELETE/MERGE/COPY) are explained without ANALYZE
        to prevent double-execution, even when analyze_plans=True: DuckDB's
        EXPLAIN ANALYZE physically runs the statement, which would mutate data a
        second time. The plan structure is still captured (FORMAT JSON only);
        execution statistics are absent for these statements.
        """
        from benchbox.platforms.base.result_capture import is_dml_query

        analyze = self.analyze_plans
        # EXPLAIN ANALYZE re-executes the statement; for DML that would double-mutate
        # data, so downgrade to FORMAT JSON (estimated plan, no execution stats).
        if analyze and is_dml_query(query):
            analyze = False
        # EXPLAIN (ANALYZE, FORMAT JSON) is the PostgreSQL-style combined syntax supported by DuckDB.
        # Plain EXPLAIN (FORMAT JSON) produces estimated plans only (no timing/cardinality data).
        explain_options = "ANALYZE, FORMAT JSON" if analyze else "FORMAT JSON"
        try:
            rows = connection.execute(f"EXPLAIN ({explain_options}) {query}").fetchall()
            # DuckDB returns rows of (explain_key, explain_value); the JSON payload is in column 1
            parts = [str(row[1]) for row in rows if len(row) > 1]
            if parts:
                return "\n".join(parts)
        except Exception:
            pass
        return None

    def get_query_plan_parser(self):
        """Get DuckDB query plan parser."""
        from benchbox.core.query_plans.parsers.duckdb import DuckDBQueryPlanParser

        return DuckDBQueryPlanParser()

    def _get_platform_metadata(self, connection: Any) -> dict[str, Any]:
        """Get DuckDB-specific metadata and system information."""
        metadata = {
            "platform": self.platform_name,
            "duckdb_version": getattr(self._duckdb_module, "__version__", "unknown"),
            "result_cache_enabled": False,  # DuckDB has no persistent query result cache
        }

        try:
            # Get DuckDB settings
            settings = connection.execute("PRAGMA show_all_settings").fetchall()
            metadata["settings"] = {setting[0]: setting[1] for setting in settings}

            # Get memory usage
            memory_info = connection.execute("PRAGMA database_size").fetchall()
            metadata["database_size"] = memory_info

        except Exception as e:
            metadata["metadata_error"] = str(e)

        return metadata

    def analyze_tables(self, connection: Any) -> None:
        """Run ANALYZE on all tables for better query optimization."""
        try:
            # Get all table names
            tables = connection.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'main' AND table_type = 'BASE TABLE'
            """).fetchall()

            for (table_name,) in tables:
                connection.execute(f"ANALYZE {table_name}")

            emit(f"✅ Analyzed {len(tables)} tables for query optimization")

        except Exception as e:
            emit(f"⚠️️  Could not analyze tables: {e}")

    def get_target_dialect(self) -> str:
        """Get the target SQL dialect for this platform."""
        return "duckdb"

    def supports_tuning_type(self, tuning_type) -> bool:
        """Check if DuckDB supports a specific tuning type.

        DuckDB supports:
        - SORTING: Via ORDER BY in table definition (DuckDB 0.10+)
        - PARTITIONING: Limited support, mainly through file-based partitions

        Args:
            tuning_type: The type of tuning to check support for

        Returns:
            True if the tuning type is supported by DuckDB
        """
        # Import here to avoid circular imports
        try:
            from benchbox.core.tuning.interface import TuningType

            return tuning_type in {TuningType.SORTING, TuningType.PARTITIONING}
        except ImportError:
            return False

    def generate_tuning_clause(self, table_tuning) -> str:
        """Generate DuckDB-specific tuning clauses for CREATE TABLE statements.

        DuckDB supports:
        - Sorting optimization hints (no explicit syntax in CREATE TABLE)
        - Partitioning through file organization (handled at data loading level)

        Args:
            table_tuning: The tuning configuration for the table

        Returns:
            SQL clause string to be appended to CREATE TABLE statement
        """
        if not table_tuning:
            return ""

        clauses = []

        # DuckDB doesn't have explicit CREATE TABLE tuning clauses
        # Sorting and partitioning are handled at query/loading time
        # We'll return empty string and handle optimization in apply_table_tunings

        return " ".join(clauses) if clauses else ""

    def apply_table_tunings(self, table_name: str, table_tuning, connection: Any) -> None:
        """Apply tuning configurations to a DuckDB table.

        DuckDB tuning approach:
        - SORTING: Create indexes on sort columns for query optimization
        - PARTITIONING: Log partitioning strategy (handled at data loading level)
        - CLUSTERING: Treat as secondary sorting for optimization hints
        - DISTRIBUTION: Not applicable for single-node DuckDB

        Args:
            table_tuning: The tuning configuration to apply
            connection: DuckDB connection

        Raises:
            ValueError: If the tuning configuration is invalid for DuckDB
        """
        if not table_tuning or not table_tuning.has_any_tuning():
            return

        table_name_upper = table_name.upper()
        self.logger.info(f"Applying DuckDB tunings for table: {table_name_upper}")

        try:
            # Import here to avoid circular imports
            from benchbox.core.tuning.interface import TuningType

            # Handle sorting optimization through indexes
            sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
            if sort_columns:
                # Sort columns by their order and create index
                sorted_cols = sorted(sort_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]

                # Create index for sort optimization
                index_name = f"idx_{table_name_upper.lower()}_sort"
                index_sql = f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name_upper} ({', '.join(column_names)})"

                try:
                    connection.execute(index_sql)
                    self.logger.info(f"Created sort index on {table_name_upper}: {', '.join(column_names)}")
                except Exception as e:
                    self.logger.warning(f"Failed to create sort index on {table_name_upper}: {e}")

            # Handle clustering as additional index optimization
            cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
            if cluster_columns:
                # Sort columns by their order and create secondary index
                sorted_cols = sorted(cluster_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]

                # Create index for clustering optimization
                index_name = f"idx_{table_name_upper.lower()}_cluster"
                index_sql = f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name_upper} ({', '.join(column_names)})"

                try:
                    connection.execute(index_sql)
                    self.logger.info(f"Created cluster index on {table_name_upper}: {', '.join(column_names)}")
                except Exception as e:
                    self.logger.warning(f"Failed to create cluster index on {table_name_upper}: {e}")

            # Handle partitioning - log strategy but implementation depends on data loading
            partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
            if partition_columns:
                sorted_cols = sorted(partition_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]
                self.logger.info(
                    f"Partitioning strategy for {table_name_upper}: {', '.join(column_names)} (handled at data loading level)"
                )

            # Distribution not applicable for DuckDB
            distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
            if distribution_columns:
                self.logger.warning(
                    f"Distribution tuning not applicable for single-node DuckDB on table: {table_name_upper}"
                )

        except ImportError:
            self.logger.warning("Tuning interface not available - skipping tuning application")
        except Exception as e:
            raise ValueError(f"Failed to apply tunings to DuckDB table {table_name_upper}: {e}") from e

    def apply_unified_tuning(self, tuning_config, connection) -> None:
        """Apply unified tuning configuration to DuckDB.

        Args:
            tuning_config: UnifiedTuningConfiguration instance
            connection: DuckDB connection
        """
        try:
            # Apply table-level tunings for each table configuration
            for table_name, table_tuning in tuning_config.table_tunings.items():
                self.logger.info(f"Applying unified tuning to table: {table_name}")
                self.apply_table_tunings(table_name, table_tuning, connection)

            # Apply platform-specific optimizations
            self.apply_platform_optimizations(tuning_config, connection)

            # Apply constraint configurations (already handled in schema creation)
            self.logger.info("Constraint configuration applied during schema creation")

        except Exception as e:
            self.logger.error(f"Failed to apply unified tuning configuration: {e}")
            raise

    def apply_platform_optimizations(self, tuning_config, connection) -> None:
        """Apply DuckDB-specific platform optimizations.

        Args:
            tuning_config: UnifiedTuningConfiguration instance
            connection: DuckDB connection
        """
        try:
            from benchbox.core.tuning.interface import TuningType

            # Check if platform optimizations are configured
            if not tuning_config.platform_optimizations:
                self.logger.info("No platform optimizations configured")
                return

            # DuckDB-specific optimizations can be applied through platform_optimizations
            # For now, just log that platform optimization validation was completed
            self.logger.info("Platform optimization validation completed for DuckDB")

            # Note: DuckDB doesn't support platform-specific tunings like Z_ORDERING, AUTO_OPTIMIZE
            # These are Databricks/cloud-specific features that don't apply to DuckDB
            unsupported_types = {
                TuningType.Z_ORDERING,
                TuningType.AUTO_OPTIMIZE,
                TuningType.BLOOM_FILTERS,
                TuningType.AUTO_COMPACT,
                TuningType.MATERIALIZED_VIEWS,
            }

            for table_name, table_tuning in tuning_config.table_tunings.items():
                # Check all tuning types for unsupported configurations
                all_tuning_types = [
                    TuningType.PARTITIONING,
                    TuningType.CLUSTERING,
                    TuningType.DISTRIBUTION,
                    TuningType.SORTING,
                ]
                for tuning_type in all_tuning_types:
                    if tuning_type in unsupported_types:
                        columns = table_tuning.get_columns_by_type(tuning_type)
                        if columns:
                            self.logger.warning(
                                f"Tuning type {tuning_type.value} not supported on DuckDB for table {table_name}"
                            )

        except Exception as e:
            self.logger.error(f"Failed to apply platform optimizations: {e}")
            raise

    def apply_constraint_configuration(self, tuning_config, table_name: str, connection) -> None:
        """Apply constraint configuration for a specific table.

        Note: Constraints are applied during schema creation in DuckDB,
        so this method primarily validates the configuration.

        Args:
            tuning_config: UnifiedTuningConfiguration instance
            table_name: Name of the table
            connection: DuckDB connection
        """
        try:
            # Primary keys - validate configuration
            if not tuning_config.primary_keys.enabled:
                self.logger.info(f"Primary keys disabled for table {table_name}")

            # Foreign keys - validate configuration
            if not tuning_config.foreign_keys.enabled:
                self.logger.info(f"Foreign keys disabled for table {table_name}")

            # Unique constraints
            if not tuning_config.unique_constraints.enabled:
                self.logger.info(f"Unique constraints disabled for table {table_name}")

            # Check constraints
            if not tuning_config.check_constraints.enabled:
                self.logger.info(f"Check constraints disabled for table {table_name}")

        except Exception as e:
            self.logger.error(f"Failed to apply constraint configuration for table {table_name}: {e}")
            raise

    def _get_existing_tables(self, connection) -> list[str]:
        """Get list of existing tables in the DuckDB database.

        Override the base class implementation with DuckDB-specific query.
        DuckDB doesn't support the standard information_schema query used in base class.

        Args:
            connection: DuckDB connection

        Returns:
            List of table names (lowercase)
        """
        try:
            # Use DuckDB's SHOW TABLES command which is more reliable
            result = connection.execute("SHOW TABLES").fetchall()
            # Convert to lowercase for consistent comparison
            return [row[0].lower() for row in result]
        except Exception as e:
            self.logger.debug(f"Failed to get existing tables: {e}")
            return []

    def validate_platform_capabilities(self, benchmark_type: str):
        """Validate DuckDB-specific capabilities for the benchmark.

        Args:
            benchmark_type: Type of benchmark (e.g., 'tpcds', 'tpch')

        Returns:
            ValidationResult with DuckDB capability validation status
        """
        errors = []
        warnings = []

        # Check if DuckDB is available
        if self._duckdb_module is None:
            errors.append("DuckDB library not available - install with 'pip install duckdb'")
        else:
            # Check DuckDB version compatibility
            try:
                version = self._duckdb_module.__version__
                # Warn if using very old versions
                if version.startswith(("0.8", "0.9")):
                    warnings.append(f"DuckDB version {version} is older - consider upgrading for better performance")
            except AttributeError:
                warnings.append("Could not determine DuckDB version")

        # Check memory configuration
        if hasattr(self, "memory_limit") and self.memory_limit:
            try:
                # Parse memory limit if it's a string (e.g., "4GB")
                if isinstance(self.memory_limit, str):
                    if self.memory_limit.lower().endswith("gb"):
                        memory_gb = float(self.memory_limit[:-2])
                    elif self.memory_limit.lower().endswith("mb"):
                        memory_gb = float(self.memory_limit[:-2]) / 1024
                    else:
                        memory_gb = float(self.memory_limit) / (1024**3)  # Assume bytes
                else:
                    memory_gb = float(self.memory_limit) / (1024**3)  # Assume bytes

                if memory_gb < 1.0:
                    warnings.append(f"Memory limit ({self.memory_limit}) may be insufficient for larger scale factors")
            except (ValueError, TypeError):
                warnings.append(f"Could not parse memory limit: {self.memory_limit}")

        # Platform-specific details
        platform_info = {
            "platform": self.platform_name,
            "benchmark_type": benchmark_type,
            "dry_run_mode": self.dry_run_mode,
            "duckdb_available": self._duckdb_module is not None,
            "database_path": getattr(self, "database_path", None),
            "memory_limit": getattr(self, "memory_limit", None),
            "thread_limit": getattr(self, "thread_limit", None),
        }

        if self._duckdb_module:
            platform_info["duckdb_version"] = getattr(self._duckdb_module, "__version__", "unknown")

        # Import ValidationResult here to avoid circular imports
        try:
            from benchbox.core.validation import ValidationResult

            return ValidationResult(
                is_valid=len(errors) == 0,
                errors=errors,
                warnings=warnings,
                details=platform_info,
            )
        except ImportError:
            # Fallback if validation module not available
            return None

    def validate_connection_health(self, connection: Any):
        """Validate DuckDB connection health and capabilities.

        Args:
            connection: DuckDB connection object

        Returns:
            ValidationResult with connection health status
        """
        errors = []
        warnings = []
        connection_info = {}

        try:
            # Test basic query execution
            result = connection.execute("SELECT 1 as test_value").fetchone()
            if result[0] != 1:
                errors.append("Basic query execution test failed")
            else:
                connection_info["basic_query_test"] = "passed"

            # Check available memory settings
            try:
                memory_result = connection.execute("PRAGMA memory_limit").fetchone()
                if memory_result:
                    connection_info["memory_limit_setting"] = memory_result[0]
            except Exception:
                warnings.append("Could not query memory limit setting")

            # Check available threads
            try:
                threads_result = connection.execute("PRAGMA threads").fetchone()
                if threads_result:
                    connection_info["threads_setting"] = threads_result[0]
            except Exception:
                warnings.append("Could not query threads setting")

        except Exception as e:
            errors.append(f"Connection health check failed: {str(e)}")

        # Import ValidationResult here to avoid circular imports
        try:
            from benchbox.core.validation import ValidationResult

            return ValidationResult(
                is_valid=len(errors) == 0,
                errors=errors,
                warnings=warnings,
                details={
                    "platform": self.platform_name,
                    "connection_type": type(connection).__name__,
                    **connection_info,
                },
            )
        except ImportError:
            # Fallback if validation module not available
            return None
