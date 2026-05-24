"""Database platform adapters for optimized benchmark execution.

Provides database-specific optimizations for benchmark execution,
separating benchmark logic from platform-specific implementation details.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import ast
import importlib
import importlib.util
from collections.abc import Iterable
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
_lazy_adapter_diagnostics: dict[str, dict[str, object]] = {}

# Mapping of lazy adapter names to their module paths.
_LAZY_ADAPTER_ROWS = """\
DatabricksAdapter|.databricks
BigQueryAdapter|.bigquery
SnowflakeAdapter|.snowflake
RedshiftAdapter|.redshift
ClickHouseAdapter|.clickhouse
ClickHouseLocalAdapter|.clickhouse_local
ClickHouseServerAdapter|.clickhouse_server
ClickHouseCloudAdapter|.clickhouse_cloud
TrinoAdapter|.trino
AthenaAdapter|.athena
SparkAdapter|.spark
PySparkSQLAdapter|.pyspark
FireboltAdapter|.firebolt
DatabendAdapter|.databend
InfluxDBAdapter|.influxdb
PrestoAdapter|.presto
AzureSynapseAdapter|.azure_synapse
FabricWarehouseAdapter|.fabric_warehouse
FabricLakehouseAdapter|.fabric_lakehouse
FabricSparkAdapter|.fabric_spark
StarRocksAdapter|.starrocks
SingleStoreAdapter|.singlestore
QuantonAdapter|.onehouse
LakeSailAdapter|.lakesail
VeloxAdapter|.velox
DorisAdapter|.doris
DataFusionAdapter|.datafusion
PolarsAdapter|.polars_platform
PolarsDataFrameAdapter|.dataframe
PandasDataFrameAdapter|.dataframe
ModinDataFrameAdapter|.dataframe
CuDFDataFrameAdapter|.dataframe
DaskDataFrameAdapter|.dataframe
DataFusionDataFrameAdapter|.dataframe
PySparkDataFrameAdapter|.dataframe
LakeSailDataFrameAdapter|.dataframe
DataFramePlatformChecker|.dataframe
"""
_LAZY_ADAPTERS = dict(row.split("|", 1) for row in _LAZY_ADAPTER_ROWS.splitlines())

_LAZY_CONSTANT_ROWS = """\
POLARS_AVAILABLE|.dataframe
PANDAS_AVAILABLE|.dataframe
MODIN_AVAILABLE|.dataframe
CUDF_AVAILABLE|.dataframe
DASK_AVAILABLE|.dataframe
DATAFUSION_DF_AVAILABLE|.dataframe
PYSPARK_AVAILABLE|.dataframe
"""
_LAZY_CONSTANTS = {
    name: (module_path, False) for name, module_path in (row.split("|", 1) for row in _LAZY_CONSTANT_ROWS.splitlines())
}

# Cache for clickhouse module (special case - needs module reference)
_clickhouse_module_cache = None


def _resolve_lazy_module_path(module_path: str) -> str:
    """Return the absolute module path used for import diagnostics."""
    if module_path.startswith(".") and __package__ is not None:
        return importlib.util.resolve_name(module_path, __package__)
    return module_path


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
    diagnostic_module_path = _resolve_lazy_module_path(module_path)

    try:
        module = importlib.import_module(module_path, __package__)
        adapter_class = getattr(module, name, None)
        _lazy_adapter_cache[name] = adapter_class
        if adapter_class is None:
            _lazy_adapter_diagnostics[name] = {
                "adapter": name,
                "module_path": module_path,
                "status": "broken_adapter_import",
                "error_type": "AttributeError",
                "error_message": f"{module_path} does not expose {name}",
            }
        else:
            _lazy_adapter_diagnostics.pop(name, None)
        return adapter_class
    except (ImportError, OSError) as exc:
        _lazy_adapter_diagnostics[name] = {
            "adapter": name,
            "module_path": module_path,
            "status": PlatformRegistry.classify_optional_import_error(exc, module_path=diagnostic_module_path),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
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


def get_lazy_adapter_diagnostics() -> dict[str, dict[str, object]]:
    """Return diagnostics captured by lazy adapter loading."""
    return {name: diagnostic.copy() for name, diagnostic in _lazy_adapter_diagnostics.items()}


def diagnose_optional_adapter_imports(platform_names: Optional[Iterable[str]] = None) -> dict[str, dict[str, object]]:
    """Run registry-level optional adapter diagnostics on demand."""
    return PlatformRegistry.diagnose_optional_adapter_imports(platform_names)


# ============================================================================
# Eagerly Loaded Adapters (light dependencies or core)
# ============================================================================
# These adapters have lightweight dependencies that don't impact startup time
# significantly, so they're loaded eagerly for simpler access patterns.


# Import local platform adapters (core/light dependencies).
def _load_optional_adapter(module_path: str, class_name: str) -> Optional[Type[PlatformAdapter]]:
    try:
        module = importlib.import_module(module_path, __package__)
    except ImportError:
        return None
    return getattr(module, class_name, None)


DuckDBAdapter = _load_optional_adapter(".duckdb", "DuckDBAdapter")
MotherDuckAdapter = _load_optional_adapter(".motherduck", "MotherDuckAdapter")
SQLiteAdapter = _load_optional_adapter(".sqlite", "SQLiteAdapter")
PostgreSQLAdapter = _load_optional_adapter(".postgresql", "PostgreSQLAdapter")
TimescaleDBAdapter = _load_optional_adapter(".timescaledb", "TimescaleDBAdapter")
PgDuckDBAdapter = _load_optional_adapter(".pg_duckdb", "PgDuckDBAdapter")
PgMooncakeAdapter = _load_optional_adapter(".pg_mooncake", "PgMooncakeAdapter")
CedarDBAdapter = _load_optional_adapter(".cedardb", "CedarDBAdapter")
QuestDBAdapter = _load_optional_adapter(".questdb", "QuestDBAdapter")

_EXPORT_NAMES = """\
PlatformAdapter ConnectionConfig BenchmarkResults DuckDBAdapter MotherDuckAdapter DataFusionAdapter PolarsAdapter
ClickHouseAdapter ClickHouseCloudAdapter DatabricksAdapter BigQueryAdapter RedshiftAdapter SnowflakeAdapter
TrinoAdapter AthenaAdapter SparkAdapter PySparkSQLAdapter FireboltAdapter DatabendAdapter InfluxDBAdapter
PrestoAdapter PostgreSQLAdapter PgDuckDBAdapter PgMooncakeAdapter CedarDBAdapter QuestDBAdapter AzureSynapseAdapter
FabricWarehouseAdapter FabricLakehouseAdapter FabricSparkAdapter StarRocksAdapter SingleStoreAdapter QuantonAdapter
LakeSailAdapter DorisAdapter PolarsDataFrameAdapter PandasDataFrameAdapter ModinDataFrameAdapter CuDFDataFrameAdapter
DaskDataFrameAdapter DataFusionDataFrameAdapter PySparkDataFrameAdapter LakeSailDataFrameAdapter POLARS_AVAILABLE
PANDAS_AVAILABLE MODIN_AVAILABLE CUDF_AVAILABLE DASK_AVAILABLE DATAFUSION_DF_AVAILABLE PYSPARK_AVAILABLE
DataFramePlatformChecker get_adapter is_dataframe_mode get_available_modes get_available_deployments
get_default_deployment get_platform_adapter get_dataframe_adapter list_available_platforms
list_available_dataframe_platforms get_platform_requirements get_dataframe_requirements check_platform_connectivity
is_dataframe_platform diagnose_optional_adapter_imports get_lazy_adapter_diagnostics
"""
__all__ = _EXPORT_NAMES.split()


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
        raise ValueError(f"Unsupported platform: {platform_name}. Available: {available}") from None

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
        # Upstream (database.py) already resolved the driver - reconstruct without re-resolving.
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
        # No upstream resolution (e.g., direct API usage) - resolve now.
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

_DATAFRAME_PLATFORM_ROWS = """\
polars-df|PolarsDataFrameAdapter|POLARS_AVAILABLE|pip install polars (core dependency - should be installed)
pandas-df|PandasDataFrameAdapter|PANDAS_AVAILABLE|pip install pandas  # standalone\\n  uv add benchbox --extra pandas  # inside a project
modin-df|ModinDataFrameAdapter|MODIN_AVAILABLE|pip install modin[ray]  # standalone\\n  uv add benchbox --extra modin  # inside a project
cudf-df|CuDFDataFrameAdapter|CUDF_AVAILABLE|pip install cudf-cu12 (requires NVIDIA GPU with CUDA)
dask-df|DaskDataFrameAdapter|DASK_AVAILABLE|pip install dask[distributed]  # standalone\\n  uv add benchbox --extra dask  # inside a project
datafusion-df|DataFusionDataFrameAdapter|DATAFUSION_DF_AVAILABLE|pip install datafusion  # standalone\\n  uv add benchbox --extra datafusion  # inside a project
pyspark-df|PySparkDataFrameAdapter|PYSPARK_AVAILABLE|pip install pyspark  # standalone\\n  uv add benchbox --extra pyspark  # inside a project
lakesail-df|LakeSailDataFrameAdapter|PYSPARK_AVAILABLE|pip install pyspark  # standalone (LakeSail Sail uses PySpark Spark Connect client)
"""
_DATAFRAME_PLATFORM_INFO = {
    platform: (adapter, availability, requirements.replace("\\n", "\n"))
    for platform, adapter, availability, requirements in (
        row.split("|", 3) for row in _DATAFRAME_PLATFORM_ROWS.splitlines()
    )
}


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
    platform_lower = platform_name.lower()

    if platform_lower not in _DATAFRAME_PLATFORM_INFO:
        available = ", ".join(sorted(_DATAFRAME_PLATFORM_INFO))
        raise ValueError(f"Unknown DataFrame platform: {platform_name}. Available: {available}")

    # Trigger lazy load via __getattr__
    adapter_name = _DATAFRAME_PLATFORM_INFO[platform_lower][0]
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
    # Trigger lazy load via __getattr__ for each constant
    return {platform: _load_lazy_constant(info[1]) for platform, info in _DATAFRAME_PLATFORM_INFO.items()}


def get_dataframe_requirements(platform_name: str) -> str:
    """Get installation requirements for a DataFrame platform.

    Args:
        platform_name: Name of the DataFrame platform

    Returns:
        Installation command string
    """
    info = _DATAFRAME_PLATFORM_INFO.get(platform_name.lower())
    return info[2] if info is not None else "Unknown DataFrame platform"


def is_dataframe_platform(platform_name: str) -> bool:
    """Check if a platform name refers to a DataFrame platform.

    Args:
        platform_name: Platform name to check

    Returns:
        True if the platform is a DataFrame platform
    """
    return platform_name.lower() in _DATAFRAME_PLATFORM_INFO


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

    def _spec(name: str, help_text: str, **kwargs) -> PlatformOptionSpec:
        return PlatformOptionSpec(name=name, help=help_text, **kwargs)

    def _register_specs(platform: str, *specs) -> None:
        PlatformHookRegistry.register_option_specs(
            platform,
            *(_spec(spec[0], spec[1], **(spec[2] if len(spec) > 2 else {})) for spec in specs),
        )

    _OPTION_SPEC_ROWS = """\
databricks|uc_catalog|Unity Catalog catalog name for staging data|{}
databricks|uc_schema|Unity Catalog schema name for staging data|{}
databricks|uc_volume|Unity Catalog volume name for staging data|{}
databricks|staging_root|Cloud storage path for staging data (e.g., dbfs:/Volumes/..., s3://..., abfss://...)|{}
databricks|databricks_clustering_strategy|Databricks SQL tuning strategy override (z_order, liquid_clustering, none)|{'choices': ('z_order', 'liquid_clustering', 'none')}
databricks|liquid_clustering_columns|Comma-separated Databricks liquid clustering columns|{}
bigquery|staging_root|GCS path for staging data (e.g., gs://bucket/path)|{}
bigquery|storage_bucket|GCS bucket name for data staging (alternative to staging_root)|{}
bigquery|storage_prefix|GCS path prefix within bucket for data staging|{}
trino|catalog|Trino catalog to use (e.g., hive, iceberg, memory). Auto-discovered if not specified.|{}
trino|staging_root|Cloud storage path for staging data (e.g., s3://..., gs://..., abfss://...)|{}
trino|table_format|Table format for creating tables (memory, hive, iceberg, delta)|{'default': 'memory'}
trino|source_catalog|Source catalog for external data loading (e.g., hive connector)|{}
firebolt|deployment_mode|Explicit Firebolt mode: 'core' for local Docker, 'cloud' for managed Firebolt|{'aliases': ('firebolt_mode',), 'choices': ('core', 'cloud')}
firebolt|url|Firebolt Core endpoint URL (default: http://localhost:3473)|{'default': 'http://localhost:3473'}
firebolt|client_id|Firebolt Cloud OAuth client ID|{}
firebolt|client_secret|Firebolt Cloud OAuth client secret|{}
firebolt|account_name|Firebolt Cloud account name|{}
firebolt|engine_name|Firebolt Cloud engine name|{}
firebolt|api_endpoint|Firebolt Cloud API endpoint|{'default': 'api.app.firebolt.io'}
firebolt|database|Firebolt database name|{}
firebolt|region|Firebolt Cloud region when known|{'aliases': ('cloud_region',)}
firebolt|cloud_provider|Firebolt Cloud provider when known|{}
firebolt|engine_type|Firebolt Cloud engine type when known|{}
firebolt|engine_size|Firebolt Cloud requested engine size when known|{}
firebolt|compute_size|Firebolt Cloud requested compute size alias for engine size|{}
firebolt|s3_staging_url|S3 URL for Firebolt Cloud data staging|{}
firebolt|s3_region|AWS region for Firebolt S3 staging|{}
firebolt|disable_result_cache|Disable Firebolt Cloud result cache during benchmark execution|{'parser': 'parse_bool', 'default': True}
firebolt|strict_validation|Fail when Firebolt cache-control validation cannot prove expected state|{'parser': 'parse_bool', 'default': False}
presto|catalog|Presto catalog to use (e.g., hive, memory). Auto-discovered if not specified.|{}
presto|staging_root|Cloud storage path for staging data (e.g., s3://..., gs://...)|{}
presto|table_format|Table format for creating tables (memory, hive)|{'default': 'memory'}
presto|source_catalog|Source catalog for external data loading (e.g., hive connector)|{}
postgresql|host|PostgreSQL server hostname|{'default': 'localhost'}
postgresql|port|PostgreSQL server port|{'parser': 'int', 'default': 5432}
postgresql|database|PostgreSQL database name (auto-generated if not specified)|{}
postgresql|username|PostgreSQL username|{'default': 'postgres'}
postgresql|password|PostgreSQL password|{}
postgresql|schema|PostgreSQL schema name|{'default': 'public'}
postgresql|work_mem|PostgreSQL work_mem setting for queries|{'default': '256MB'}
postgresql|enable_timescale|Enable TimescaleDB extensions if available|{'default': 'false'}
timescaledb|host|TimescaleDB server hostname|{'default': 'localhost'}
timescaledb|port|TimescaleDB server port|{'parser': 'int', 'default': 5432}
timescaledb|database|TimescaleDB database name (auto-generated if not specified)|{}
timescaledb|username|TimescaleDB username|{'default': 'postgres'}
timescaledb|password|TimescaleDB password|{}
timescaledb|schema|TimescaleDB schema name|{'default': 'public'}
timescaledb|admin_database|Database used for CREATE/DROP DATABASE operations|{'default': 'postgres'}
timescaledb|sslmode|PostgreSQL SSL mode|{'default': 'prefer'}
timescaledb|work_mem|TimescaleDB work_mem setting for queries|{'default': '256MB'}
timescaledb|maintenance_work_mem|TimescaleDB maintenance_work_mem for VACUUM/CREATE INDEX|{'default': '512MB'}
timescaledb|effective_cache_size|TimescaleDB effective_cache_size planner hint|{'default': '1GB'}
timescaledb|max_parallel_workers_per_gather|TimescaleDB max_parallel_workers_per_gather setting|{'parser': 'int', 'default': 2}
timescaledb|chunk_interval|Chunk time interval for hypertables (e.g., '1 day', '1 week')|{'default': '1 day'}
timescaledb|compression_enabled|Enable compression on hypertables|{'default': 'false'}
timescaledb|compression_after|Compress chunks older than this interval (e.g., '7 days')|{'default': '7 days'}
pg-duckdb|host|PostgreSQL server hostname (with pg_duckdb installed)|{'default': 'localhost'}
pg-duckdb|port|PostgreSQL server port|{'parser': 'int', 'default': 5432}
pg-duckdb|database|PostgreSQL database name (auto-generated if not specified)|{}
pg-duckdb|username|PostgreSQL username|{'default': 'postgres'}
pg-duckdb|password|PostgreSQL password|{}
pg-duckdb|schema|PostgreSQL schema name|{'default': 'public'}
pg-duckdb|admin_database|Database used for CREATE/DROP DATABASE operations|{'default': 'postgres'}
pg-duckdb|sslmode|PostgreSQL SSL mode|{'default': 'prefer'}
pg-duckdb|work_mem|PostgreSQL work_mem setting for queries|{'default': '256MB'}
pg-duckdb|maintenance_work_mem|PostgreSQL maintenance_work_mem for VACUUM/CREATE INDEX|{'default': '512MB'}
pg-duckdb|effective_cache_size|PostgreSQL effective_cache_size planner hint|{'default': '1GB'}
pg-duckdb|max_parallel_workers_per_gather|PostgreSQL max_parallel_workers_per_gather setting|{'parser': 'int', 'default': 2}
pg-duckdb|force_execution|Force DuckDB execution engine for all queries|{'parser': 'parse_bool', 'default': True}
pg-duckdb|postgres_scan_threads|Threads for parallel PostgreSQL table scanning (0 = auto)|{'parser': 'int', 'default': 0}
pg-duckdb|compare_native|Run native DuckDB comparison for matched queries|{'parser': 'parse_bool', 'default': False}
pg-mooncake|host|PostgreSQL server hostname (with pg_mooncake installed)|{'default': 'localhost'}
pg-mooncake|port|PostgreSQL server port|{'parser': 'int', 'default': 5432}
pg-mooncake|database|PostgreSQL database name (auto-generated if not specified)|{}
pg-mooncake|username|PostgreSQL username|{'default': 'postgres'}
pg-mooncake|password|PostgreSQL password|{}
pg-mooncake|schema|PostgreSQL schema name|{'default': 'public'}
pg-mooncake|admin_database|Database used for CREATE/DROP DATABASE operations|{'default': 'postgres'}
pg-mooncake|sslmode|PostgreSQL SSL mode|{'default': 'prefer'}
pg-mooncake|work_mem|PostgreSQL work_mem setting for queries|{'default': '256MB'}
pg-mooncake|maintenance_work_mem|PostgreSQL maintenance_work_mem for VACUUM/CREATE INDEX|{'default': '512MB'}
pg-mooncake|effective_cache_size|PostgreSQL effective_cache_size planner hint|{'default': '1GB'}
pg-mooncake|max_parallel_workers_per_gather|PostgreSQL max_parallel_workers_per_gather setting|{'parser': 'int', 'default': 2}
pg-mooncake|storage_mode|Storage backend: local (disk) or s3 (object storage)|{'choices': ('local', 's3'), 'default': 'local'}
pg-mooncake|mooncake_bucket|S3/GCS bucket URL for columnstore data (required when storage_mode=s3)|{}
questdb|host|QuestDB server hostname|{'default': 'localhost'}
questdb|pg_port|QuestDB PostgreSQL wire protocol port|{'default': '8812'}
questdb|http_port|QuestDB REST API HTTP port (BenchBox Docker uses 19000; native default is 9000)|{'default': '9000'}
questdb|ilp_port|QuestDB InfluxDB Line Protocol port|{'default': '9009'}
questdb|username|QuestDB username|{'default': 'admin'}
questdb|password|QuestDB password|{'default': 'quest'}
questdb|database|QuestDB database name|{'default': 'qdb'}
questdb|loading_method|Data loading method: 'rest' (CSV import, default) or 'ilp' (InfluxDB Line Protocol)|{'default': 'rest'}
cedardb|host|CedarDB server hostname|{'default': 'localhost'}
cedardb|port|CedarDB server port|{'default': '5432'}
cedardb|database|CedarDB database name (auto-generated if not specified)|{}
cedardb|username|CedarDB username|{'default': 'postgres'}
cedardb|password|CedarDB password|{}
cedardb|schema|CedarDB schema name|{'default': 'public'}
synapse|server|Azure Synapse server endpoint (e.g., myworkspace.sql.azuresynapse.net)|{}
synapse|database|Azure Synapse database name (auto-generated if not specified)|{}
synapse|username|Azure Synapse username|{}
synapse|password|Azure Synapse password|{}
synapse|auth_method|Authentication method: sql, aad_password, or aad_msi|{'default': 'sql'}
synapse|storage_account|Azure storage account for data staging|{}
synapse|container|Azure blob container name|{}
synapse|storage_sas_token|SAS token for Azure storage access|{}
synapse|resource_class|Workload resource class (e.g., staticrc20, staticrc30)|{'default': 'staticrc20'}
fabric_dw|server|Fabric warehouse endpoint (e.g., workspace-guid.datawarehouse.fabric.microsoft.com)|{}
fabric_dw|workspace|Fabric workspace name or GUID|{}
fabric_dw|warehouse|Fabric warehouse name|{}
fabric_dw|database|Database/warehouse name (alias for --warehouse)|{}
fabric_dw|auth_method|Authentication method: service_principal, default_credential, or interactive|{'default': 'default_credential'}
fabric_dw|tenant_id|Azure tenant ID for service principal auth|{}
fabric_dw|client_id|Service principal client ID|{}
fabric_dw|client_secret|Service principal client secret|{}
fabric_dw|staging_path|OneLake staging path for data loading|{'default': 'benchbox-staging'}
quanton|api_key|Onehouse API key (or set ONEHOUSE_API_KEY env var)|{}
quanton|s3_staging_dir|S3 path for data staging (e.g., s3://bucket/path)|{}
quanton|region|AWS region for cluster deployment|{'default': 'us-east-1'}
quanton|database|Database name for benchmarks|{'default': 'benchbox'}
quanton|table_format|Table format: iceberg, hudi, or delta|{'choices': ('iceberg', 'hudi', 'delta'), 'default': 'iceberg'}
quanton|cluster_size|Cluster size: small, medium, large, xlarge|{'choices': ('small', 'medium', 'large', 'xlarge'), 'default': 'small'}
clickhouse-cloud|host|ClickHouse Cloud hostname (e.g., abc123.us-east-2.aws.clickhouse.cloud)|{}
clickhouse-cloud|password|ClickHouse Cloud password (or set CLICKHOUSE_CLOUD_PASSWORD env var)|{}
clickhouse-cloud|username|Username (default: 'default')|{'default': 'default'}
clickhouse-cloud|database|Database name|{'default': 'default'}
clickhouse-cloud|region|ClickHouse Cloud service region when it cannot be inferred from the host|{}
clickhouse-cloud|cloud_provider|ClickHouse Cloud provider when it cannot be inferred from the host|{}
clickhouse-cloud|service_id|ClickHouse Cloud service identifier for result metadata|{}
clickhouse-cloud|service_name|ClickHouse Cloud service display name for result metadata|{}
clickhouse-cloud|service_tier|ClickHouse Cloud service tier for result metadata|{}
clickhouse-cloud|compute_size|ClickHouse Cloud requested compute size for result metadata|{}
clickhouse-cloud|oauth_token|OAuth token for keyless authentication (alternative to password)|{}
clickhouse-cloud|s3_staging_url|S3 URL for bulk data loading (e.g., s3://my-bucket/benchbox-staging/)|{}
clickhouse-cloud|s3_region|AWS region for the S3 staging bucket|{'default': 'us-east-1'}
clickhouse-cloud|gcs_staging_url|GCS URL for bulk data loading (e.g., gs://my-bucket/benchbox-staging/)|{}
starrocks|host|StarRocks FE hostname|{'default': 'localhost'}
starrocks|port|StarRocks FE MySQL protocol port|{'default': '9030'}
starrocks|username|StarRocks username|{'default': 'root'}
starrocks|password|StarRocks password|{}
starrocks|database|StarRocks database name (auto-generated if not specified)|{}
starrocks|http_port|StarRocks BE HTTP port for Stream Load|{'default': '8040'}
databend|host|Databend host (or set DATABEND_HOST env var)|{}
databend|port|Databend port (default: 443 for cloud, 8000 for self-hosted)|{}
databend|username|Databend username (default: benchbox)|{'default': 'benchbox'}
databend|password|Databend password (or set DATABEND_PASSWORD env var)|{}
databend|database|Database name (default: benchbox)|{'default': 'benchbox'}
databend|dsn|Full Databend DSN (overrides individual connection params)|{}
databend|warehouse|Databend Cloud warehouse name|{}
doris|host|Doris FE node hostname|{'default': 'localhost'}
doris|port|Doris MySQL protocol port|{'parser': 'int', 'default': 9030}
doris|http_port|Doris Stream Load HTTP port (FE)|{'parser': 'int', 'default': 8030}
doris|be_http_port|Doris BE HTTP port for stream load redirects|{'parser': 'int', 'default': 8040}
doris|database|Doris database name (auto-generated if not specified)|{}
doris|username|Doris username|{'default': 'root'}
doris|password|Doris password|{}
singlestore|host|SingleStore server hostname or Helios endpoint|{'default': 'localhost'}
singlestore|port|SingleStore MySQL protocol port|{'default': '3306'}
singlestore|database|SingleStore database name (auto-generated if not specified)|{}
singlestore|username|SingleStore username|{'default': 'root'}
singlestore|password|SingleStore password|{}
polars-df|streaming|Enable streaming mode for large datasets|{'parser': 'parse_bool', 'default': 'false'}
polars-df|rechunk|Rechunk data for better memory layout|{'parser': 'parse_bool', 'default': 'true'}
polars-df|n_rows|Limit number of rows to read (for testing)|{'parser': 'int'}
pandas-df|dtype_backend|Backend for nullable dtypes|{'choices': ('numpy', 'numpy_nullable', 'pyarrow'), 'default': 'numpy_nullable'}
modin-df|engine|Modin execution engine|{'choices': ('ray', 'dask'), 'default': 'ray'}
cudf-df|device_id|CUDA device ID to use|{'parser': 'int', 'default': '0'}
cudf-df|spill_to_host|Enable GPU memory spilling to host RAM|{'parser': 'parse_bool', 'default': 'true'}
dask-df|n_workers|Number of worker processes|{'parser': 'int'}
dask-df|threads_per_worker|Threads per worker process|{'parser': 'int'}
dask-df|use_distributed|Use distributed scheduler (enables dashboard)|{'parser': 'parse_bool', 'default': True}
dask-df|scheduler_address|Connect to existing scheduler (e.g., 'tcp://...')|{}
dask-df|memory_limit|Memory limit per local Dask worker (e.g., '4GB')|{}
dask-df|spill_directory|Directory for Dask spill files; explicit directories are not deleted by close()|{}
datafusion-df|target_partitions|Number of target partitions for parallelism (default: CPU count)|{'parser': 'int'}
datafusion-df|repartition_joins|Enable automatic repartitioning for joins|{'parser': 'parse_bool', 'default': 'true'}
datafusion-df|parquet_pushdown|Enable predicate/projection pushdown for Parquet files|{'parser': 'parse_bool', 'default': 'true'}
datafusion-df|batch_size|Batch size for query execution|{'parser': 'int', 'default': '8192'}
datafusion-df|memory_limit|Memory limit for fair spill pool (e.g., '8G', '16GB')|{}
datafusion-df|temp_dir|Temporary directory for disk spilling (default: system temp)|{}
sqlite|database_path|Path to the SQLite database file (auto-generated from --benchmark/--scale when omitted)|{}
sqlite|timeout|SQLite connection timeout in seconds|{'parser': 'float', 'default': '30.0'}
sqlite|check_same_thread|Enforce that connections are used on the creating thread only|{'parser': 'parse_bool', 'default': 'false'}
velox|deployment|Deployment mode: 'local' (in-process SparkSession, Linux only) or 'remote' (Spark-Connect server)|{'choices': ('local', 'remote'), 'default': 'local'}
velox|endpoint|Spark-Connect endpoint for remote mode (e.g., sc://localhost:50051)|{'default': 'sc://localhost:50051'}
velox|gluten_jar_path|Absolute path to the Gluten Velox bundle jar (required for local mode)|{'aliases': ('jar',)}
velox|offheap_size|Off-heap memory for Velox native engine (e.g., '8g', '16g')|{'default': '8g'}
velox|driver_memory|Spark driver JVM heap memory (e.g., '4g')|{'default': '4g'}
velox|shuffle_partitions|Number of shuffle partitions|{'parser': 'int', 'default': '200'}
velox|adaptive_enabled|Enable Spark Adaptive Query Execution|{'parser': 'parse_bool', 'default': 'true'}
"""

    _SPEC_PARSERS = {"int": int, "float": float, "parse_bool": parse_bool}

    def _spec_kwargs(text: str) -> dict[str, object]:
        kwargs = ast.literal_eval(text)
        parser = kwargs.get("parser")
        if isinstance(parser, str):
            kwargs["parser"] = _SPEC_PARSERS[parser]
        return kwargs

    def _register_spec_rows(rows: str) -> None:
        for row in rows.splitlines():
            platform, name, help_text, kwargs_text = row.split("|", 3)
            _register_specs(platform, (name, help_text, _spec_kwargs(kwargs_text)))

    _register_spec_rows(_OPTION_SPEC_ROWS)

    # ========================================================================
    # Cloud Platform Hooks (Lazy Config Builders)
    # ========================================================================
    # These platforms use lazy config builders to avoid importing heavy SDKs
    # at module load time. Option specs are registered unconditionally.

    # MotherDuck — the credential wizard saves a `database` field, but the
    # default builder did not call CredentialManager, so the configured
    # database was silently dropped at run time. Routing through a lazy
    # config builder pulls the wizard-saved database into runtime config.
    PlatformHookRegistry.register_config_builder(
        "motherduck", _make_lazy_config_builder(".motherduck", "_build_motherduck_config")
    )

    # Databricks
    PlatformHookRegistry.register_config_builder(
        "databricks", _make_lazy_config_builder(".databricks", "_build_databricks_config")
    )

    # BigQuery
    PlatformHookRegistry.register_config_builder(
        "bigquery", _make_lazy_config_builder(".bigquery", "_build_bigquery_config")
    )

    # Trino
    PlatformHookRegistry.register_config_builder("trino", _make_lazy_config_builder(".trino", "_build_trino_config"))

    # Firebolt
    PlatformHookRegistry.register_config_builder(
        "firebolt", _make_lazy_config_builder(".firebolt", "_build_firebolt_config")
    )

    # Presto
    PlatformHookRegistry.register_config_builder("presto", _make_lazy_config_builder(".presto", "_build_presto_config"))

    # ========================================================================
    # Eagerly-Loaded Platform Hooks (PostgreSQL, TimescaleDB)
    # ========================================================================
    # These platforms have lightweight dependencies that are already loaded
    # eagerly, so we can use direct imports for their config builders.

    # PostgreSQL (eagerly loaded - uses psycopg2 which is a core dependency)
    if PostgreSQLAdapter is not None:
        from benchbox.platforms.postgresql import _build_postgresql_config

        PlatformHookRegistry.register_config_builder("postgresql", _build_postgresql_config)

    # TimescaleDB (eagerly loaded - shares psycopg2 with PostgreSQL)
    if TimescaleDBAdapter is not None:
        from benchbox.platforms.timescaledb import _build_timescaledb_config

        PlatformHookRegistry.register_config_builder("timescaledb", _build_timescaledb_config)

    # pg_duckdb (eagerly loaded - shares psycopg2 with PostgreSQL)
    if PgDuckDBAdapter is not None:
        from benchbox.platforms.pg_duckdb import _build_pg_duckdb_config

        PlatformHookRegistry.register_config_builder("pg-duckdb", _build_pg_duckdb_config)

    # pg_mooncake (eagerly loaded - shares psycopg2 with PostgreSQL)
    if PgMooncakeAdapter is not None:
        from benchbox.platforms.pg_mooncake import _build_pg_mooncake_config

        PlatformHookRegistry.register_config_builder("pg-mooncake", _build_pg_mooncake_config)

    # QuestDB (eagerly loaded - shares psycopg2 with PostgreSQL)
    if QuestDBAdapter is not None:
        from benchbox.platforms.questdb import _build_questdb_config

        PlatformHookRegistry.register_config_builder("questdb", _build_questdb_config)

    # CedarDB (eagerly loaded - shares psycopg2 with PostgreSQL)
    if CedarDBAdapter is not None:
        from benchbox.platforms.cedardb import _build_cedardb_config

        PlatformHookRegistry.register_config_builder("cedardb", _build_cedardb_config)

    # ========================================================================
    # Lazy Cloud Platform Hooks (Azure Synapse, Fabric)
    # ========================================================================

    # Azure Synapse (lazy - uses pyodbc and azure-identity)
    PlatformHookRegistry.register_config_builder(
        "synapse", _make_lazy_config_builder(".azure_synapse", "_build_synapse_config")
    )

    # Microsoft Fabric Warehouse (lazy - uses pyodbc and azure-identity)
    # Fabric uses from_config pattern, no separate config builder needed

    # Onehouse Quanton (lazy - uses requests and boto3)
    PlatformHookRegistry.register_config_builder(
        "quanton", _make_lazy_config_builder(".onehouse", "_build_quanton_config")
    )

    # ClickHouse Cloud (lazy - uses clickhouse-connect)
    PlatformHookRegistry.register_config_builder(
        "clickhouse-cloud", _make_lazy_config_builder(".clickhouse_cloud", "_build_clickhouse_cloud_config")
    )

    # StarRocks (lazy - uses pymysql)
    PlatformHookRegistry.register_config_builder(
        "starrocks", _make_lazy_config_builder(".starrocks.setup", "_build_starrocks_config")
    )

    # Databend (lazy - uses databend-driver)
    PlatformHookRegistry.register_config_builder(
        "databend", _make_lazy_config_builder(".databend", "_build_databend_config")
    )

    # Doris (lazy - uses pymysql)
    PlatformHookRegistry.register_config_builder("doris", _make_lazy_config_builder(".doris", "_build_doris_config"))

    # SingleStore (lazy - uses singlestoredb SDK)
    PlatformHookRegistry.register_config_builder(
        "singlestore", _make_lazy_config_builder(".singlestore", "_build_singlestore_config")
    )

    # ========================================================================
    # DataFrame Platform Hooks
    # ========================================================================
    # DataFrame platform option specs are registered unconditionally since
    # they're just metadata. The actual adapter availability is checked at
    # runtime when the adapter is instantiated.

    # Polars DataFrame

    # Pandas DataFrame

    # Modin DataFrame

    # cuDF DataFrame

    # Dask DataFrame

    # DataFusion DataFrame
    # SQLite (embedded — stdlib sqlite3, no heavy SDK imports)

    # Apache Gluten + Velox (lazy - uses pyspark + Gluten bundle jar)

except ImportError:
    # Platform hooks may not be available in all contexts
    pass
