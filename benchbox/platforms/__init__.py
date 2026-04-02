"""Database platform adapters for optimized benchmark execution.

Provides database-specific optimizations for benchmark execution,
separating benchmark logic from platform-specific implementation details.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import importlib
from typing import Optional, Type

from benchbox.core.platform_registry import PlatformRegistry
from benchbox.utils.runtime_env import DriverResolution, DriverRuntimeStrategy, ensure_driver_version

from .base import BenchmarkResults, ConnectionConfig, DriverIsolationCapability, PlatformAdapter
from .base.adapter import check_isolation_capability

# ============================================================================
# Lazy Import System for Cloud Platform Adapters
# ============================================================================
# Cloud platform SDKs (databricks, snowflake, google-cloud-bigquery, etc.) have
# heavy import chains that add 300+ seconds to pytest collection time even when
# wrapped in try/except blocks. The import statement itself executes even if
# immediately caught.
#
# This lazy loading pattern defers the actual import until the adapter is first
# accessed, dramatically reducing test suite startup time.
#
# Adapters loaded lazily (heavy SDK dependencies):
#   - DatabricksAdapter (databricks-sql-connector, databricks-sdk)
#   - BigQueryAdapter (google-cloud-bigquery, google-cloud-storage)
#   - SnowflakeAdapter (snowflake-connector-python)
#   - RedshiftAdapter (redshift-connector, boto3)
#   - ClickHouseAdapter (clickhouse-driver or chdb)
#   - TrinoAdapter (trino)
#   - AthenaAdapter (pyathena, boto3)
#   - SparkAdapter (pyspark)
#   - PySparkSQLAdapter (pyspark)
#   - FireboltAdapter (firebolt-sdk)
#   - InfluxDBAdapter (influxdb3-python)
#   - PrestoAdapter (presto-python-client)
#   - AzureSynapseAdapter (pyodbc, azure-identity)
#   - FabricWarehouseAdapter (pyodbc, azure-identity)
#   - FabricLakehouseAdapter (pyodbc, azure-identity)
#   - FabricSparkAdapter (azure identity + storage SDK)
#
# Adapters loaded eagerly (light dependencies or core):
#   - DuckDBAdapter (duckdb - core dependency, always available)
#   - MotherDuckAdapter (duckdb - shares core dependency)
#   - SQLiteAdapter (stdlib sqlite3)
#   - DataFusionAdapter (datafusion - ~68 MB native lib, now lazy)
#   - PolarsAdapter (polars - ~142 MB native lib, now lazy)
#   - PostgreSQLAdapter (psycopg2 - core dependency)
#   - TimescaleDBAdapter (psycopg2 - shares core dependency)
# ============================================================================

# Cache for lazily loaded adapters and constants
_lazy_adapter_cache: dict[str, Optional[Type[PlatformAdapter]]] = {}
_lazy_constant_cache: dict[str, bool] = {}

# Mapping of lazy adapter names to their module paths
_LAZY_ADAPTERS = {
    # Cloud SQL platforms with heavy SDK dependencies
    "DatabricksAdapter": ".databricks",
    "BigQueryAdapter": ".bigquery",
    "SnowflakeAdapter": ".snowflake",
    "RedshiftAdapter": ".redshift",
    "ClickHouseAdapter": ".clickhouse",
    "ClickHouseCloudAdapter": ".clickhouse_cloud",
    "TrinoAdapter": ".trino",
    "AthenaAdapter": ".athena",
    "SparkAdapter": ".spark",
    "PySparkSQLAdapter": ".pyspark",
    "FireboltAdapter": ".firebolt",
    "DatabendAdapter": ".databend",
    "InfluxDBAdapter": ".influxdb",
    "PrestoAdapter": ".presto",
    "AzureSynapseAdapter": ".azure_synapse",
    "FabricWarehouseAdapter": ".fabric_warehouse",
    "FabricLakehouseAdapter": ".fabric_lakehouse",
    "FabricSparkAdapter": ".fabric_spark",
    "StarRocksAdapter": ".starrocks",
    "QuantonAdapter": ".onehouse",
    "LakeSailAdapter": ".lakesail",
    "DorisAdapter": ".doris",
    # Native-heavy adapters deferred to avoid ~210 MB of native library loading per process
    "DataFusionAdapter": ".datafusion",
    "PolarsAdapter": ".polars_platform",
    # DataFrame adapters (have their own lazy loading but need module-level deferral)
    "PolarsDataFrameAdapter": ".dataframe",
    "PandasDataFrameAdapter": ".dataframe",
    "ModinDataFrameAdapter": ".dataframe",
    "CuDFDataFrameAdapter": ".dataframe",
    "DaskDataFrameAdapter": ".dataframe",
    "DataFusionDataFrameAdapter": ".dataframe",
    "PySparkDataFrameAdapter": ".dataframe",
    "LakeSailDataFrameAdapter": ".dataframe",
    "DataFramePlatformChecker": ".dataframe",
}

# Mapping of lazy constants to their module paths and default values
_LAZY_CONSTANTS = {
    "POLARS_AVAILABLE": (".dataframe", False),
    "PANDAS_AVAILABLE": (".dataframe", False),
    "MODIN_AVAILABLE": (".dataframe", False),
    "CUDF_AVAILABLE": (".dataframe", False),
    "DASK_AVAILABLE": (".dataframe", False),
    "DATAFUSION_DF_AVAILABLE": (".dataframe", False),
    "PYSPARK_AVAILABLE": (".dataframe", False),
}

# Cache for clickhouse module (special case - needs module reference)
_clickhouse_module_cache = None


def _load_lazy_adapter(name: str) -> Optional[Type[PlatformAdapter]]:
    """Load a lazily-imported adapter class.

    Args:
        name: Adapter class name (e.g., 'DatabricksAdapter')

    Returns:
        Adapter class if available, None if import fails
    """
    if name in _lazy_adapter_cache:
        return _lazy_adapter_cache[name]

    module_path = _LAZY_ADAPTERS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    try:
        module = importlib.import_module(module_path, __package__)
        adapter_class = getattr(module, name, None)
        _lazy_adapter_cache[name] = adapter_class
        return adapter_class
    except ImportError:
        _lazy_adapter_cache[name] = None
        return None


def _load_lazy_constant(name: str) -> bool:
    """Load a lazily-imported availability constant.

    Args:
        name: Constant name (e.g., 'POLARS_AVAILABLE')

    Returns:
        Constant value (True/False), defaults to False on import failure
    """
    if name in _lazy_constant_cache:
        return _lazy_constant_cache[name]

    module_path, default = _LAZY_CONSTANTS.get(name, (None, False))
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    try:
        module = importlib.import_module(module_path, __package__)
        value = getattr(module, name, default)
        _lazy_constant_cache[name] = value
        return value
    except ImportError:
        _lazy_constant_cache[name] = default
        return default


def __getattr__(name: str):
    """Lazy load cloud platform adapters and DataFrame components on first access.

    This function is called when an attribute is not found in the module's namespace.
    It enables deferred loading of heavy cloud SDK dependencies until they're actually
    needed, dramatically reducing test collection time.
    """
    global _clickhouse_module_cache

    # Handle adapter classes
    if name in _LAZY_ADAPTERS:
        return _load_lazy_adapter(name)

    # Handle availability constants
    if name in _LAZY_CONSTANTS:
        return _load_lazy_constant(name)

    # Special case: clickhouse module reference (for legacy patches/tests)
    if name == "clickhouse":
        if _clickhouse_module_cache is None:
            try:
                _clickhouse_module_cache = importlib.import_module(".clickhouse", __package__)
            except ImportError:
                pass  # Keep as None
        return _clickhouse_module_cache

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ============================================================================
# Eagerly Loaded Adapters (light dependencies or core)
# ============================================================================
# These adapters have lightweight dependencies that don't impact startup time
# significantly, so they're loaded eagerly for simpler access patterns.

# Import local platform adapters (core/light dependencies)
try:
    from .duckdb import DuckDBAdapter
except ImportError:
    DuckDBAdapter: Optional[Type[PlatformAdapter]] = None  # type: ignore[assignment,misc]

try:
    from .motherduck import MotherDuckAdapter
except ImportError:
    MotherDuckAdapter: Optional[Type[PlatformAdapter]] = None  # type: ignore[assignment,misc]

try:
    from .sqlite import SQLiteAdapter
except ImportError:
    SQLiteAdapter: Optional[Type[PlatformAdapter]] = None  # type: ignore[assignment,misc]

# DataFusionAdapter and PolarsAdapter are loaded lazily via _LAZY_ADAPTERS
# because their native libraries are large (~68 MB and ~142 MB respectively).

try:
    from .postgresql import PostgreSQLAdapter
except ImportError:
    PostgreSQLAdapter: Optional[Type[PlatformAdapter]] = None  # type: ignore[assignment,misc]

try:
    from .timescaledb import TimescaleDBAdapter
except ImportError:
    TimescaleDBAdapter: Optional[Type[PlatformAdapter]] = None  # type: ignore[assignment,misc]

try:
    from .pg_duckdb import PgDuckDBAdapter
except ImportError:
    PgDuckDBAdapter: Optional[Type[PlatformAdapter]] = None  # type: ignore[assignment,misc]

try:
    from .pg_mooncake import PgMooncakeAdapter
except ImportError:
    PgMooncakeAdapter: Optional[Type[PlatformAdapter]] = None  # type: ignore[assignment,misc]

try:
    from .questdb import QuestDBAdapter
except ImportError:
    QuestDBAdapter: Optional[Type[PlatformAdapter]] = None  # type: ignore[assignment,misc]

__all__ = [
    "PlatformAdapter",
    "ConnectionConfig",
    "BenchmarkResults",
    "DuckDBAdapter",
    "MotherDuckAdapter",
    "DataFusionAdapter",
    "PolarsAdapter",
    "ClickHouseAdapter",
    "ClickHouseCloudAdapter",
    "DatabricksAdapter",
    "BigQueryAdapter",
    "RedshiftAdapter",
    "SnowflakeAdapter",
    "TrinoAdapter",
    "AthenaAdapter",
    "SparkAdapter",
    "PySparkSQLAdapter",
    "FireboltAdapter",
    "DatabendAdapter",
    "InfluxDBAdapter",
    "PrestoAdapter",
    "PostgreSQLAdapter",
    "PgDuckDBAdapter",
    "PgMooncakeAdapter",
    "QuestDBAdapter",
    "AzureSynapseAdapter",
    "FabricWarehouseAdapter",
    "FabricLakehouseAdapter",
    "FabricSparkAdapter",
    "StarRocksAdapter",
    "QuantonAdapter",
    "LakeSailAdapter",
    "DorisAdapter",
    # DataFrame adapters
    "PolarsDataFrameAdapter",
    "PandasDataFrameAdapter",
    "ModinDataFrameAdapter",
    "CuDFDataFrameAdapter",
    "DaskDataFrameAdapter",
    "DataFusionDataFrameAdapter",
    "PySparkDataFrameAdapter",
    "LakeSailDataFrameAdapter",
    "POLARS_AVAILABLE",
    "PANDAS_AVAILABLE",
    "MODIN_AVAILABLE",
    "CUDF_AVAILABLE",
    "DASK_AVAILABLE",
    "DATAFUSION_DF_AVAILABLE",
    "PYSPARK_AVAILABLE",
    "DataFramePlatformChecker",
    # Unified adapter factory (--mode and --deployment flag support)
    "get_adapter",
    "is_dataframe_mode",
    "get_available_modes",
    "get_available_deployments",
    "get_default_deployment",
    # Functions
    "get_platform_adapter",
    "get_dataframe_adapter",
    "list_available_platforms",
    "list_available_dataframe_platforms",
    "get_platform_requirements",
    "get_dataframe_requirements",
    "check_platform_connectivity",
    "is_dataframe_platform",
]


# Import unified adapter factory
from benchbox.platforms.adapter_factory import (
    get_adapter,
    get_available_deployments,
    get_available_modes,
    get_default_deployment,
    is_dataframe_mode,
)


def get_platform_adapter(platform_name: str, **config) -> PlatformAdapter:
    """Factory function to create platform adapters.

    This function delegates adapter lookup to PlatformRegistry (the single source
    of truth for platform definitions) while handling CLI-specific concerns like
    error messages and driver version resolution.

    Args:
        platform_name: Name of the platform (aliases like 'sqlite3' are resolved)
        **config: Platform-specific configuration

    Returns:
        Configured platform adapter instance

    Raises:
        ValueError: If platform is not supported
        ImportError: If platform dependencies are not installed
    """
    # Resolve aliases and normalize to canonical name via PlatformRegistry
    canonical_name = PlatformRegistry.resolve_platform_name(platform_name)

    # Get adapter class from registry (single source of truth)
    try:
        adapter_class = PlatformRegistry.get_adapter_class(canonical_name)
    except ValueError:
        # Platform not registered - provide helpful error with available platforms
        available = ", ".join(PlatformRegistry.get_available_platforms())
        raise ValueError(f"Unsupported platform: {platform_name}. Available: {available}")

    # Check if adapter class is actually available (deps installed)
    if adapter_class is None:
        platform_info = PlatformRegistry.get_platform_info(canonical_name)
        install_cmd = platform_info.installation_command if platform_info else "unknown"
        raise ImportError(f"Platform '{platform_name}' is not available. Install required dependencies: {install_cmd}")

    # Check for pre-resolved driver state from upstream (database.py) before popping keys.
    # driver_runtime_strategy is NOT popped, so its presence signals upstream already resolved.
    already_resolved = config.get("driver_runtime_strategy") is not None

    driver_package = config.pop("driver_package", None)
    driver_version = config.pop("driver_version", None)
    driver_version_requested = config.pop("driver_version_requested", None)
    driver_version_resolved = config.pop("driver_version_resolved", None)
    driver_version_actual = config.pop("driver_version_actual", None)
    driver_auto_install = bool(config.pop("driver_auto_install", False))
    driver_auto_install_used = bool(config.pop("driver_auto_install_used", False))

    # Get platform info for driver metadata (already resolved to canonical name)
    platform_info = PlatformRegistry.get_platform_info(canonical_name)
    install_hint = platform_info.installation_command if platform_info else "unknown"
    package_hint = driver_package or (platform_info.driver_package if platform_info else None)
    explicit_requested_version = driver_version_requested or driver_version
    requested_version = explicit_requested_version

    if already_resolved:
        # Upstream (database.py) already resolved the driver — reconstruct without re-resolving.
        resolution = DriverResolution(
            package=driver_package or package_hint or "",
            requested=explicit_requested_version,
            resolved=driver_version_resolved,
            actual=driver_version_actual,
            auto_install_used=driver_auto_install_used,
            runtime_strategy=config.get("driver_runtime_strategy"),
            runtime_path=config.get("driver_runtime_path"),
            runtime_python_executable=config.get("driver_runtime_python_executable"),
        )
    else:
        # No upstream resolution (e.g., direct API usage) — resolve now.
        resolution = ensure_driver_version(
            package_name=package_hint,
            requested_version=requested_version,
            auto_install=driver_auto_install,
            install_hint=install_hint,
        )

    check_isolation_capability(adapter_class, canonical_name, resolution.runtime_strategy)

    resolved_version = resolution.resolved or driver_version_resolved
    requested = explicit_requested_version or resolution.requested

    # Propagate driver runtime contract into adapter constructor config so
    # adapters that need runtime binding during initialization can apply it.
    config.setdefault("driver_package", resolution.package or package_hint)
    config.setdefault("driver_version_requested", requested)
    config.setdefault("driver_version_resolved", resolved_version)
    config.setdefault("driver_version_actual", resolution.actual)
    config.setdefault("driver_runtime_strategy", resolution.runtime_strategy)
    config.setdefault("driver_runtime_path", resolution.runtime_path)
    config.setdefault("driver_runtime_python_executable", resolution.runtime_python_executable)
    config.setdefault("driver_auto_install", resolution.auto_install_used or driver_auto_install)
    config.setdefault("driver_auto_install_used", resolution.auto_install_used)

    # Use from_config() if adapter supports config-aware initialization (e.g., Databricks, Snowflake)
    # This enables proper schema naming based on benchmark/scale/tuning configuration
    if hasattr(adapter_class, "from_config") and callable(adapter_class.from_config):
        adapter_instance = adapter_class.from_config(config)
    else:
        # Simple adapters use direct constructor (e.g., DuckDB, SQLite)
        adapter_instance = adapter_class(**config)

    # Attach driver metadata for downstream consumers (CLI summaries, exports).
    adapter_instance.driver_package = resolution.package or package_hint
    adapter_instance.driver_version_requested = requested
    adapter_instance.driver_version_resolved = resolved_version
    adapter_instance.driver_version_actual = resolution.actual or driver_version_actual
    adapter_instance.driver_runtime_strategy = resolution.runtime_strategy
    adapter_instance.driver_runtime_path = resolution.runtime_path
    adapter_instance.driver_runtime_python_executable = resolution.runtime_python_executable
    adapter_instance.driver_auto_install_used = resolution.auto_install_used

    return adapter_instance


def list_available_platforms() -> dict[str, bool]:
    """List all platforms and their availability status.

    Delegates to PlatformRegistry.get_platform_availability() which is
    the single source of truth for platform availability.

    Returns:
        Dictionary mapping platform names to availability boolean.
    """
    return PlatformRegistry.get_platform_availability()


def get_platform_requirements(platform_name: str) -> str:
    """Get installation requirements for a platform.

    Delegates to PlatformRegistry.get_platform_requirements() which is
    the single source of truth for platform metadata.

    Args:
        platform_name: Name of the platform (aliases are resolved automatically)

    Returns:
        Installation command string
    """
    return PlatformRegistry.get_platform_requirements(platform_name)


def check_platform_connectivity(platform_name: str, **config) -> bool:
    """Check connectivity to a platform using its adapter.

    Args:
        platform_name: Name of the platform to test
        **config: Platform configuration

    Returns:
        True if connection successful, False otherwise
    """
    try:
        adapter = get_platform_adapter(platform_name, **config)
        return adapter.test_connection()
    except Exception:
        return False


# ============================================================================
# DataFrame Platform Support
# ============================================================================


def get_dataframe_adapter(platform_name: str, **config):
    """Factory function to create DataFrame platform adapters.

    DataFrame adapters use native DataFrame APIs (e.g., Polars expressions,
    Pandas operations) instead of SQL for query execution.

    Args:
        platform_name: Name of the DataFrame platform ('polars-df', 'pandas-df', etc.)
        **config: Platform-specific configuration options

    Returns:
        DataFrame adapter instance

    Raises:
        ValueError: If platform is not a recognized DataFrame platform
        ImportError: If required dependencies are not installed
    """
    # Mapping uses lazy-loaded adapter names (resolved via __getattr__)
    dataframe_adapter_names = {
        "polars-df": "PolarsDataFrameAdapter",
        "pandas-df": "PandasDataFrameAdapter",
        "modin-df": "ModinDataFrameAdapter",
        "cudf-df": "CuDFDataFrameAdapter",
        "dask-df": "DaskDataFrameAdapter",
        "datafusion-df": "DataFusionDataFrameAdapter",
        "pyspark-df": "PySparkDataFrameAdapter",
        "lakesail-df": "LakeSailDataFrameAdapter",
    }

    platform_lower = platform_name.lower()

    if platform_lower not in dataframe_adapter_names:
        available = ", ".join(sorted(dataframe_adapter_names.keys()))
        raise ValueError(f"Unknown DataFrame platform: {platform_name}. Available: {available}")

    # Trigger lazy load via __getattr__
    adapter_name = dataframe_adapter_names[platform_lower]
    adapter_class = _load_lazy_adapter(adapter_name)

    if adapter_class is None:
        requirements = get_dataframe_requirements(platform_lower)
        raise ImportError(
            f"DataFrame platform '{platform_name}' is not available. Install required dependencies: {requirements}"
        )

    return adapter_class(**config)


def list_available_dataframe_platforms() -> dict[str, bool]:
    """List all DataFrame platforms and their availability status.

    Returns:
        Dictionary mapping platform name to availability boolean
    """
    # Mapping uses lazy-loaded constant names (resolved via __getattr__)
    availability_constants = {
        "polars-df": "POLARS_AVAILABLE",
        "pandas-df": "PANDAS_AVAILABLE",
        "modin-df": "MODIN_AVAILABLE",
        "cudf-df": "CUDF_AVAILABLE",
        "dask-df": "DASK_AVAILABLE",
        "datafusion-df": "DATAFUSION_DF_AVAILABLE",
        "pyspark-df": "PYSPARK_AVAILABLE",
        "lakesail-df": "PYSPARK_AVAILABLE",
    }
    # Trigger lazy load via __getattr__ for each constant
    return {platform: _load_lazy_constant(const_name) for platform, const_name in availability_constants.items()}


def get_dataframe_requirements(platform_name: str) -> str:
    """Get installation requirements for a DataFrame platform.

    Args:
        platform_name: Name of the DataFrame platform

    Returns:
        Installation command string
    """
    requirements = {
        "polars-df": "pip install polars (core dependency - should be installed)",
        "pandas-df": "pip install pandas  # standalone\n  uv add benchbox --extra pandas  # inside a project",
        "modin-df": "pip install modin[ray]  # standalone\n  uv add benchbox --extra modin  # inside a project",
        "cudf-df": "pip install cudf-cu12 (requires NVIDIA GPU with CUDA)",
        "dask-df": "pip install dask[distributed]  # standalone\n  uv add benchbox --extra dask  # inside a project",
        "datafusion-df": (
            "pip install datafusion  # standalone\n  uv add benchbox --extra datafusion  # inside a project"
        ),
        "pyspark-df": "pip install pyspark  # standalone\n  uv add benchbox --extra pyspark  # inside a project",
        "lakesail-df": "pip install pyspark  # standalone (LakeSail Sail uses PySpark Spark Connect client)",
    }

    return requirements.get(platform_name.lower(), "Unknown DataFrame platform")


def is_dataframe_platform(platform_name: str) -> bool:
    """Check if a platform name refers to a DataFrame platform.

    Args:
        platform_name: Platform name to check

    Returns:
        True if the platform is a DataFrame platform
    """
    return platform_name.lower() in {
        "polars-df",
        "pandas-df",
        "modin-df",
        "cudf-df",
        "dask-df",
        "datafusion-df",
        "pyspark-df",
        "lakesail-df",
    }


# ============================================================================
# Platform Hook Registration (Deferred)
# ============================================================================
# Platform hooks are registered lazily to avoid triggering SDK imports during
# module load. The option specs are registered unconditionally (they're just
# metadata), but config builders are wrapped in lazy loaders that only import
# the adapter module when the builder is actually called.
#
# This is critical for test performance - importing adapters like Databricks
# or Snowflake triggers heavy SDK imports (300+ seconds). By deferring these
# imports, pytest collection time is dramatically reduced.
# ============================================================================


def _make_lazy_config_builder(module_path: str, builder_name: str):
    """Create a lazy config builder that defers module import until called.

    Args:
        module_path: Relative module path (e.g., '.databricks')
        builder_name: Name of the config builder function in the module

    Returns:
        A wrapper function that lazily imports and calls the real builder
    """
    from typing import Any

    def lazy_builder(
        platform: str,
        options: dict[str, Any],
        overrides: dict[str, Any],
        info: Any,
    ):
        module = importlib.import_module(module_path, __package__)
        real_builder = getattr(module, builder_name)
        return real_builder(platform, options, overrides, info)

    return lazy_builder


try:
    from benchbox.cli.platform_hooks import PlatformHookRegistry, PlatformOptionSpec, parse_bool

    # ========================================================================
    # Cloud Platform Hooks (Lazy Config Builders)
    # ========================================================================
    # These platforms use lazy config builders to avoid importing heavy SDKs
    # at module load time. Option specs are registered unconditionally.

    # Databricks
    PlatformHookRegistry.register_config_builder(
        "databricks", _make_lazy_config_builder(".databricks", "_build_databricks_config")
    )
    PlatformHookRegistry.register_option_specs(
        "databricks",
        PlatformOptionSpec(
            name="uc_catalog",
            help="Unity Catalog catalog name for staging data",
        ),
        PlatformOptionSpec(
            name="uc_schema",
            help="Unity Catalog schema name for staging data",
        ),
        PlatformOptionSpec(
            name="uc_volume",
            help="Unity Catalog volume name for staging data",
        ),
        PlatformOptionSpec(
            name="staging_root",
            help="Cloud storage path for staging data (e.g., dbfs:/Volumes/..., s3://..., abfss://...)",
        ),
        PlatformOptionSpec(
            name="databricks_clustering_strategy",
            choices=("z_order", "liquid_clustering", "none"),
            help="Databricks SQL tuning strategy override (z_order, liquid_clustering, none)",
        ),
        PlatformOptionSpec(
            name="liquid_clustering_columns",
            help="Comma-separated Databricks liquid clustering columns",
        ),
    )

    # BigQuery
    PlatformHookRegistry.register_config_builder(
        "bigquery", _make_lazy_config_builder(".bigquery", "_build_bigquery_config")
    )
    PlatformHookRegistry.register_option_specs(
        "bigquery",
        PlatformOptionSpec(
            name="staging_root",
            help="GCS path for staging data (e.g., gs://bucket/path)",
        ),
        PlatformOptionSpec(
            name="storage_bucket",
            help="GCS bucket name for data staging (alternative to staging_root)",
        ),
        PlatformOptionSpec(
            name="storage_prefix",
            help="GCS path prefix within bucket for data staging",
        ),
    )

    # Trino
    PlatformHookRegistry.register_config_builder("trino", _make_lazy_config_builder(".trino", "_build_trino_config"))
    PlatformHookRegistry.register_option_specs(
        "trino",
        PlatformOptionSpec(
            name="catalog",
            help="Trino catalog to use (e.g., hive, iceberg, memory). Auto-discovered if not specified.",
        ),
        PlatformOptionSpec(
            name="staging_root",
            help="Cloud storage path for staging data (e.g., s3://..., gs://..., abfss://...)",
        ),
        PlatformOptionSpec(
            name="table_format",
            help="Table format for creating tables (memory, hive, iceberg, delta)",
            default="memory",
        ),
        PlatformOptionSpec(
            name="source_catalog",
            help="Source catalog for external data loading (e.g., hive connector)",
        ),
    )

    # Firebolt
    PlatformHookRegistry.register_config_builder(
        "firebolt", _make_lazy_config_builder(".firebolt", "_build_firebolt_config")
    )
    PlatformHookRegistry.register_option_specs(
        "firebolt",
        PlatformOptionSpec(
            name="firebolt_mode",
            help="Explicit Firebolt mode: 'core' for local Docker, 'cloud' for managed Firebolt",
        ),
        PlatformOptionSpec(
            name="url",
            help="Firebolt Core endpoint URL (default: http://localhost:3473)",
            default="http://localhost:3473",
        ),
        PlatformOptionSpec(
            name="client_id",
            help="Firebolt Cloud OAuth client ID",
        ),
        PlatformOptionSpec(
            name="client_secret",
            help="Firebolt Cloud OAuth client secret",
        ),
        PlatformOptionSpec(
            name="account_name",
            help="Firebolt Cloud account name",
        ),
        PlatformOptionSpec(
            name="engine_name",
            help="Firebolt Cloud engine name",
        ),
        PlatformOptionSpec(
            name="api_endpoint",
            help="Firebolt Cloud API endpoint",
            default="api.app.firebolt.io",
        ),
    )

    # Presto
    PlatformHookRegistry.register_config_builder("presto", _make_lazy_config_builder(".presto", "_build_presto_config"))
    PlatformHookRegistry.register_option_specs(
        "presto",
        PlatformOptionSpec(
            name="catalog",
            help="Presto catalog to use (e.g., hive, memory). Auto-discovered if not specified.",
        ),
        PlatformOptionSpec(
            name="staging_root",
            help="Cloud storage path for staging data (e.g., s3://..., gs://...)",
        ),
        PlatformOptionSpec(
            name="table_format",
            help="Table format for creating tables (memory, hive)",
            default="memory",
        ),
        PlatformOptionSpec(
            name="source_catalog",
            help="Source catalog for external data loading (e.g., hive connector)",
        ),
    )

    # ========================================================================
    # Eagerly-Loaded Platform Hooks (PostgreSQL, TimescaleDB)
    # ========================================================================
    # These platforms have lightweight dependencies that are already loaded
    # eagerly, so we can use direct imports for their config builders.

    # PostgreSQL (eagerly loaded - uses psycopg2 which is a core dependency)
    if PostgreSQLAdapter is not None:
        from benchbox.platforms.postgresql import _build_postgresql_config

        PlatformHookRegistry.register_config_builder("postgresql", _build_postgresql_config)

    PlatformHookRegistry.register_option_specs(
        "postgresql",
        PlatformOptionSpec(
            name="host",
            help="PostgreSQL server hostname",
            default="localhost",
        ),
        PlatformOptionSpec(
            name="port",
            help="PostgreSQL server port",
            default="5432",
        ),
        PlatformOptionSpec(
            name="database",
            help="PostgreSQL database name (auto-generated if not specified)",
        ),
        PlatformOptionSpec(
            name="username",
            help="PostgreSQL username",
            default="postgres",
        ),
        PlatformOptionSpec(
            name="password",
            help="PostgreSQL password",
        ),
        PlatformOptionSpec(
            name="schema",
            help="PostgreSQL schema name",
            default="public",
        ),
        PlatformOptionSpec(
            name="work_mem",
            help="PostgreSQL work_mem setting for queries",
            default="256MB",
        ),
        PlatformOptionSpec(
            name="enable_timescale",
            help="Enable TimescaleDB extensions if available",
            default="false",
        ),
    )

    # TimescaleDB (eagerly loaded - shares psycopg2 with PostgreSQL)
    if TimescaleDBAdapter is not None:
        from benchbox.platforms.timescaledb import _build_timescaledb_config

        PlatformHookRegistry.register_config_builder("timescaledb", _build_timescaledb_config)

    PlatformHookRegistry.register_option_specs(
        "timescaledb",
        PlatformOptionSpec(
            name="host",
            help="TimescaleDB server hostname",
            default="localhost",
        ),
        PlatformOptionSpec(
            name="port",
            help="TimescaleDB server port",
            default="5432",
        ),
        PlatformOptionSpec(
            name="database",
            help="TimescaleDB database name (auto-generated if not specified)",
        ),
        PlatformOptionSpec(
            name="username",
            help="TimescaleDB username",
            default="postgres",
        ),
        PlatformOptionSpec(
            name="password",
            help="TimescaleDB password",
        ),
        PlatformOptionSpec(
            name="schema",
            help="TimescaleDB schema name",
            default="public",
        ),
        PlatformOptionSpec(
            name="chunk_interval",
            help="Chunk time interval for hypertables (e.g., '1 day', '1 week')",
            default="1 day",
        ),
        PlatformOptionSpec(
            name="compression_enabled",
            help="Enable compression on hypertables",
            default="false",
        ),
        PlatformOptionSpec(
            name="compression_after",
            help="Compress chunks older than this interval (e.g., '7 days')",
            default="7 days",
        ),
    )

    # pg_duckdb (eagerly loaded - shares psycopg2 with PostgreSQL)
    if PgDuckDBAdapter is not None:
        from benchbox.platforms.pg_duckdb import _build_pg_duckdb_config

        PlatformHookRegistry.register_config_builder("pg-duckdb", _build_pg_duckdb_config)

    PlatformHookRegistry.register_option_specs(
        "pg-duckdb",
        PlatformOptionSpec(
            name="host",
            help="PostgreSQL server hostname (with pg_duckdb installed)",
            default="localhost",
        ),
        PlatformOptionSpec(
            name="port",
            help="PostgreSQL server port",
            default="5432",
        ),
        PlatformOptionSpec(
            name="database",
            help="PostgreSQL database name (auto-generated if not specified)",
        ),
        PlatformOptionSpec(
            name="username",
            help="PostgreSQL username",
            default="postgres",
        ),
        PlatformOptionSpec(
            name="password",
            help="PostgreSQL password",
        ),
        PlatformOptionSpec(
            name="schema",
            help="PostgreSQL schema name",
            default="public",
        ),
        PlatformOptionSpec(
            name="force_execution",
            help="Force DuckDB execution engine for all queries",
            parser=parse_bool,
            default="true",
        ),
        PlatformOptionSpec(
            name="postgres_scan_threads",
            help="Threads for parallel PostgreSQL table scanning (0 = auto)",
            parser=int,
            default="0",
        ),
    )

    # pg_mooncake (eagerly loaded - shares psycopg2 with PostgreSQL)
    if PgMooncakeAdapter is not None:
        from benchbox.platforms.pg_mooncake import _build_pg_mooncake_config

        PlatformHookRegistry.register_config_builder("pg-mooncake", _build_pg_mooncake_config)

    PlatformHookRegistry.register_option_specs(
        "pg-mooncake",
        PlatformOptionSpec(
            name="host",
            help="PostgreSQL server hostname (with pg_mooncake installed)",
            default="localhost",
        ),
        PlatformOptionSpec(
            name="port",
            help="PostgreSQL server port",
            default="5432",
        ),
        PlatformOptionSpec(
            name="database",
            help="PostgreSQL database name (auto-generated if not specified)",
        ),
        PlatformOptionSpec(
            name="username",
            help="PostgreSQL username",
            default="postgres",
        ),
        PlatformOptionSpec(
            name="password",
            help="PostgreSQL password",
        ),
        PlatformOptionSpec(
            name="schema",
            help="PostgreSQL schema name",
            default="public",
        ),
        PlatformOptionSpec(
            name="storage_mode",
            help="Storage backend: local (disk) or s3 (object storage)",
            choices=("local", "s3"),
            default="local",
        ),
        PlatformOptionSpec(
            name="mooncake_bucket",
            help="S3/GCS bucket URL for columnstore data (required when storage_mode=s3)",
        ),
    )

    # ========================================================================
    # Lazy Cloud Platform Hooks (Azure Synapse, Fabric)
    # ========================================================================

    # Azure Synapse (lazy - uses pyodbc and azure-identity)
    PlatformHookRegistry.register_config_builder(
        "synapse", _make_lazy_config_builder(".azure_synapse", "_build_synapse_config")
    )
    PlatformHookRegistry.register_option_specs(
        "synapse",
        PlatformOptionSpec(
            name="server",
            help="Azure Synapse server endpoint (e.g., myworkspace.sql.azuresynapse.net)",
        ),
        PlatformOptionSpec(
            name="database",
            help="Azure Synapse database name (auto-generated if not specified)",
        ),
        PlatformOptionSpec(
            name="username",
            help="Azure Synapse username",
        ),
        PlatformOptionSpec(
            name="password",
            help="Azure Synapse password",
        ),
        PlatformOptionSpec(
            name="auth_method",
            help="Authentication method: sql, aad_password, or aad_msi",
            default="sql",
        ),
        PlatformOptionSpec(
            name="storage_account",
            help="Azure storage account for data staging",
        ),
        PlatformOptionSpec(
            name="container",
            help="Azure blob container name",
        ),
        PlatformOptionSpec(
            name="storage_sas_token",
            help="SAS token for Azure storage access",
        ),
        PlatformOptionSpec(
            name="resource_class",
            help="Workload resource class (e.g., staticrc20, staticrc30)",
            default="staticrc20",
        ),
    )

    # Microsoft Fabric Warehouse (lazy - uses pyodbc and azure-identity)
    # Fabric uses from_config pattern, no separate config builder needed
    PlatformHookRegistry.register_option_specs(
        "fabric_dw",
        PlatformOptionSpec(
            name="server",
            help="Fabric warehouse endpoint (e.g., workspace-guid.datawarehouse.fabric.microsoft.com)",
        ),
        PlatformOptionSpec(
            name="workspace",
            help="Fabric workspace name or GUID",
        ),
        PlatformOptionSpec(
            name="warehouse",
            help="Fabric warehouse name",
        ),
        PlatformOptionSpec(
            name="database",
            help="Database/warehouse name (alias for --warehouse)",
        ),
        PlatformOptionSpec(
            name="auth_method",
            help="Authentication method: service_principal, default_credential, or interactive",
            default="default_credential",
        ),
        PlatformOptionSpec(
            name="tenant_id",
            help="Azure tenant ID for service principal auth",
        ),
        PlatformOptionSpec(
            name="client_id",
            help="Service principal client ID",
        ),
        PlatformOptionSpec(
            name="client_secret",
            help="Service principal client secret",
        ),
        PlatformOptionSpec(
            name="staging_path",
            help="OneLake staging path for data loading",
            default="benchbox-staging",
        ),
    )

    # Onehouse Quanton (lazy - uses requests and boto3)
    PlatformHookRegistry.register_config_builder(
        "quanton", _make_lazy_config_builder(".onehouse", "_build_quanton_config")
    )
    PlatformHookRegistry.register_option_specs(
        "quanton",
        PlatformOptionSpec(
            name="api_key",
            help="Onehouse API key (or set ONEHOUSE_API_KEY env var)",
        ),
        PlatformOptionSpec(
            name="s3_staging_dir",
            help="S3 path for data staging (e.g., s3://bucket/path)",
        ),
        PlatformOptionSpec(
            name="region",
            help="AWS region for cluster deployment",
            default="us-east-1",
        ),
        PlatformOptionSpec(
            name="database",
            help="Database name for benchmarks",
            default="benchbox",
        ),
        PlatformOptionSpec(
            name="table_format",
            help="Table format: iceberg, hudi, or delta",
            choices=("iceberg", "hudi", "delta"),
            default="iceberg",
        ),
        PlatformOptionSpec(
            name="cluster_size",
            help="Cluster size: small, medium, large, xlarge",
            choices=("small", "medium", "large", "xlarge"),
            default="small",
        ),
    )

    # ClickHouse Cloud (lazy - uses clickhouse-connect)
    PlatformHookRegistry.register_config_builder(
        "clickhouse-cloud", _make_lazy_config_builder(".clickhouse_cloud", "_build_clickhouse_cloud_config")
    )
    PlatformHookRegistry.register_option_specs(
        "clickhouse-cloud",
        PlatformOptionSpec(
            name="host",
            help="ClickHouse Cloud hostname (e.g., abc123.us-east-2.aws.clickhouse.cloud)",
        ),
        PlatformOptionSpec(
            name="password",
            help="ClickHouse Cloud password (or set CLICKHOUSE_CLOUD_PASSWORD env var)",
        ),
        PlatformOptionSpec(
            name="username",
            help="Username (default: 'default')",
            default="default",
        ),
        PlatformOptionSpec(
            name="database",
            help="Database name",
            default="default",
        ),
    )

    # StarRocks (lazy - uses pymysql)
    PlatformHookRegistry.register_option_specs(
        "starrocks",
        PlatformOptionSpec(
            name="host",
            help="StarRocks FE hostname",
            default="localhost",
        ),
        PlatformOptionSpec(
            name="port",
            help="StarRocks FE MySQL protocol port",
            default="9030",
        ),
        PlatformOptionSpec(
            name="username",
            help="StarRocks username",
            default="root",
        ),
        PlatformOptionSpec(
            name="password",
            help="StarRocks password",
        ),
        PlatformOptionSpec(
            name="database",
            help="StarRocks database name (auto-generated if not specified)",
        ),
        PlatformOptionSpec(
            name="http_port",
            help="StarRocks BE HTTP port for Stream Load",
            default="8040",
        ),
    )

    # Databend (lazy - uses databend-driver)
    PlatformHookRegistry.register_config_builder(
        "databend", _make_lazy_config_builder(".databend", "_build_databend_config")
    )
    PlatformHookRegistry.register_option_specs(
        "databend",
        PlatformOptionSpec(
            name="host",
            help="Databend host (or set DATABEND_HOST env var)",
        ),
        PlatformOptionSpec(
            name="port",
            help="Databend port (default: 443 for cloud, 8000 for self-hosted)",
        ),
        PlatformOptionSpec(
            name="username",
            help="Databend username (default: benchbox)",
            default="benchbox",
        ),
        PlatformOptionSpec(
            name="password",
            help="Databend password (or set DATABEND_PASSWORD env var)",
        ),
        PlatformOptionSpec(
            name="database",
            help="Database name (default: benchbox)",
            default="benchbox",
        ),
        PlatformOptionSpec(
            name="dsn",
            help="Full Databend DSN (overrides individual connection params)",
        ),
        PlatformOptionSpec(
            name="warehouse",
            help="Databend Cloud warehouse name",
        ),
    )

    # Doris (lazy - uses pymysql)
    PlatformHookRegistry.register_config_builder("doris", _make_lazy_config_builder(".doris", "_build_doris_config"))
    PlatformHookRegistry.register_option_specs(
        "doris",
        PlatformOptionSpec(
            name="host",
            help="Doris FE node hostname",
            default="localhost",
        ),
        PlatformOptionSpec(
            name="port",
            help="Doris MySQL protocol port",
            default="9030",
        ),
        PlatformOptionSpec(
            name="http_port",
            help="Doris Stream Load HTTP port",
            default="8030",
        ),
        PlatformOptionSpec(
            name="database",
            help="Doris database name (auto-generated if not specified)",
        ),
        PlatformOptionSpec(
            name="username",
            help="Doris username",
            default="root",
        ),
        PlatformOptionSpec(
            name="password",
            help="Doris password",
        ),
    )

    # ========================================================================
    # DataFrame Platform Hooks
    # ========================================================================
    # DataFrame platform option specs are registered unconditionally since
    # they're just metadata. The actual adapter availability is checked at
    # runtime when the adapter is instantiated.

    # Polars DataFrame
    PlatformHookRegistry.register_option_specs(
        "polars-df",
        PlatformOptionSpec(
            name="streaming",
            help="Enable streaming mode for large datasets",
            parser=parse_bool,
            default="false",
        ),
        PlatformOptionSpec(
            name="rechunk",
            help="Rechunk data for better memory layout",
            parser=parse_bool,
            default="true",
        ),
        PlatformOptionSpec(
            name="n_rows",
            help="Limit number of rows to read (for testing)",
            parser=int,
        ),
    )

    # Pandas DataFrame
    PlatformHookRegistry.register_option_specs(
        "pandas-df",
        PlatformOptionSpec(
            name="dtype_backend",
            help="Backend for nullable dtypes",
            choices=("numpy", "numpy_nullable", "pyarrow"),
            default="numpy_nullable",
        ),
    )

    # Modin DataFrame
    PlatformHookRegistry.register_option_specs(
        "modin-df",
        PlatformOptionSpec(
            name="engine",
            help="Modin execution engine",
            choices=("ray", "dask"),
            default="ray",
        ),
    )

    # cuDF DataFrame
    PlatformHookRegistry.register_option_specs(
        "cudf-df",
        PlatformOptionSpec(
            name="device_id",
            help="CUDA device ID to use",
            parser=int,
            default="0",
        ),
        PlatformOptionSpec(
            name="spill_to_host",
            help="Enable GPU memory spilling to host RAM",
            parser=parse_bool,
            default="true",
        ),
    )

    # Dask DataFrame
    PlatformHookRegistry.register_option_specs(
        "dask-df",
        PlatformOptionSpec(
            name="n_workers",
            help="Number of worker processes",
            parser=int,
        ),
        PlatformOptionSpec(
            name="threads_per_worker",
            help="Threads per worker process",
            parser=int,
            default="1",
        ),
        PlatformOptionSpec(
            name="use_distributed",
            help="Use distributed scheduler (enables dashboard)",
            parser=parse_bool,
            default="false",
        ),
        PlatformOptionSpec(
            name="scheduler_address",
            help="Connect to existing scheduler (e.g., 'tcp://...')",
        ),
    )

    # DataFusion DataFrame
    PlatformHookRegistry.register_option_specs(
        "datafusion-df",
        PlatformOptionSpec(
            name="target_partitions",
            help="Number of target partitions for parallelism (default: CPU count)",
            parser=int,
        ),
        PlatformOptionSpec(
            name="repartition_joins",
            help="Enable automatic repartitioning for joins",
            parser=parse_bool,
            default="true",
        ),
        PlatformOptionSpec(
            name="parquet_pushdown",
            help="Enable predicate/projection pushdown for Parquet files",
            parser=parse_bool,
            default="true",
        ),
        PlatformOptionSpec(
            name="batch_size",
            help="Batch size for query execution",
            parser=int,
            default="8192",
        ),
        PlatformOptionSpec(
            name="memory_limit",
            help="Memory limit for fair spill pool (e.g., '8G', '16GB')",
        ),
        PlatformOptionSpec(
            name="temp_dir",
            help="Temporary directory for disk spilling (default: system temp)",
        ),
    )
except ImportError:
    # Platform hooks may not be available in all contexts
    pass
