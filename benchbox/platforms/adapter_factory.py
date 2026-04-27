"""Unified adapter factory for SQL and DataFrame execution modes.

This module provides a single entry point for getting platform adapters,
abstracting the difference between SQL and DataFrame execution modes,
and routing to appropriate deployment modes (local, self-hosted, managed).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import warnings
from typing import Any, Literal, Optional

from benchbox.core.platform_registry import PlatformRegistry
from benchbox.platforms.base.adapter import check_isolation_capability
from benchbox.platforms.clickhouse.deployment_mode import (
    CLICKHOUSE_CANONICAL_PLATFORM_NAMES,
    CLICKHOUSE_DEFAULT_CANONICAL_PLATFORM,
    CLICKHOUSE_LEGACY_SELECTOR_MAP,
    clickhouse_legacy_selector_warning,
)
from benchbox.utils.runtime_env import ensure_driver_version


def _resolve_clickhouse_legacy(
    platform: str,
    deployment: Optional[str] = None,
    config: Optional[dict] = None,
) -> tuple[str, Optional[str]]:
    """Translate legacy ClickHouse selectors to first-class platform names.

    Handles the migration from the old mixed-mode ``clickhouse`` platform to the
    explicit first-class names ``clickhouse-local``, ``clickhouse-server``, and
    ``clickhouse-cloud``.

    Args:
        platform: Raw platform name from the caller.
        deployment: Explicit deployment argument (e.g. from ``get_adapter(..., deployment=...)``)
        config: Keyword config dict (may contain ``deployment_mode`` or ``mode`` keys).

    Returns:
        Tuple of (resolved_platform_name, deprecation_message | None).
        The message is non-None only when a legacy selector was used.
    """
    lp = platform.lower().strip()

    # First-class canonical names: pass through unchanged
    if lp in CLICKHOUSE_CANONICAL_PLATFORM_NAMES:
        return platform, None

    # Explicit colon-suffix legacy selectors
    if lp in CLICKHOUSE_LEGACY_SELECTOR_MAP:
        target = CLICKHOUSE_LEGACY_SELECTOR_MAP[lp]
        return target, clickhouse_legacy_selector_warning(platform, target)

    # Bare 'clickhouse': resolve to first-class name based on explicit deployment context
    if lp == "clickhouse":
        explicit_mode = deployment
        if not explicit_mode and config:
            explicit_mode = config.get("deployment_mode") or config.get("mode")
        if isinstance(explicit_mode, str) and explicit_mode.strip().lower() in ("server", "self-hosted"):
            target = "clickhouse-server"
        else:
            target = CLICKHOUSE_DEFAULT_CANONICAL_PLATFORM  # clickhouse-local
        return target, clickhouse_legacy_selector_warning(platform, target)

    return platform, None


def _normalize_platform_name(platform: str) -> tuple[str, bool, Optional[str]]:
    """Normalize platform name, detect DataFrame mode, and extract deployment mode.

    Handles two suffix conventions:
    1. `-df` suffix for DataFrame platforms
    2. `:deployment` suffix for deployment modes

    These can be combined: `databricks-df:serverless`

    Examples:
        - `polars-df` -> (`polars`, True, None)       - DataFrame mode implied
        - `clickhouse:cloud` -> (`clickhouse`, False, 'cloud')  - Deployment implied
        - `clickhouse:local` -> (`clickhouse`, False, 'local')  - Deployment implied
        - `firebolt:core` -> (`firebolt`, False, 'core')        - Deployment implied
        - `databricks-df:serverless` -> (`databricks`, True, 'serverless')  - Both
        - `polars` -> (`polars`, False, None)         - Use platform defaults
        - `duckdb` -> (`duckdb`, False, None)         - Use platform defaults

    Args:
        platform: Raw platform name from CLI or config

    Returns:
        Tuple of (base_platform_name, is_df_mode_implied, deployment_mode)
    """
    platform_lower = platform.lower()
    deployment_mode: Optional[str] = None
    df_mode_implied = False

    # First, check for :deployment suffix (must check before -df to handle combined case)
    if ":" in platform_lower:
        base_part, deployment_mode = platform_lower.rsplit(":", 1)
        platform_lower = base_part

    # Then check for -df suffix
    if platform_lower.endswith("-df"):
        # Strip -df suffix and indicate DataFrame mode is implied
        platform_lower = platform_lower[:-3]
        df_mode_implied = True

    return platform_lower, df_mode_implied, deployment_mode


def get_adapter(
    platform: str,
    mode: Optional[Literal["sql", "dataframe"]] = None,
    deployment: Optional[str] = None,
    **config: Any,
) -> Any:
    """Get adapter for platform, execution mode, and deployment mode.

    This is the unified entry point for obtaining platform adapters. It validates
    that the platform supports the requested mode and deployment, and routes to
    the appropriate adapter factory.

    Args:
        platform: Platform name with optional suffixes:
            - `-df` suffix for DataFrame mode (e.g., 'polars-df', 'pandas-df')
            - `:deployment` suffix for deployment mode (e.g., 'clickhouse:cloud')
            - Combined (e.g., 'databricks-df:serverless')
        mode: Execution mode ('sql' or 'dataframe'). If None, uses platform default
              (or 'dataframe' if platform has -df suffix).
        deployment: Deployment mode ('local', 'server', 'cloud', etc.). If None,
            uses deployment from platform name suffix or platform default.
        **config: Platform-specific configuration options

    Returns:
        Platform adapter instance (either SQL PlatformAdapter or DataFrame adapter)

    Raises:
        ValueError: If platform does not support the requested mode or deployment
        ImportError: If required dependencies are not installed

    Examples:
        >>> adapter = get_adapter("duckdb")  # Local DuckDB (default)
        >>> adapter = get_adapter("clickhouse-local")  # chDB (explicit first-class name)
        >>> adapter = get_adapter("clickhouse-server")  # Self-hosted ClickHouse
        >>> adapter = get_adapter("polars-df")  # Polars DataFrame mode
    """
    # ClickHouse migration: translate legacy selectors to first-class platform names.
    # Must happen before _normalize_platform_name so colon-suffix parsing is bypassed.
    resolved_platform, migration_warning = _resolve_clickhouse_legacy(platform, deployment, config)
    if migration_warning:
        warnings.warn(migration_warning, DeprecationWarning, stacklevel=2)
    if resolved_platform != platform:
        # Migration consumed the deployment selector; reset to avoid double-processing.
        platform = resolved_platform
        deployment = None

    # Normalize platform name (strip -df suffix, extract :deployment suffix)
    base_platform, df_mode_implied, deployment_from_name = _normalize_platform_name(platform)

    # Get capabilities and resolve mode
    caps = PlatformRegistry.get_platform_capabilities(base_platform)
    if caps is None:
        raise ValueError(f"Unknown platform: {platform}")

    # Resolve execution mode: explicit mode > df suffix implied > platform default
    if mode is not None:
        resolved_mode = mode
    elif df_mode_implied:
        resolved_mode = "dataframe"
    else:
        resolved_mode = caps.default_mode

    # Validate execution mode support
    if not PlatformRegistry.supports_mode(base_platform, resolved_mode):
        mode_support = []
        if caps.supports_sql:
            mode_support.append("sql")
        if caps.supports_dataframe:
            mode_support.append("dataframe")
        supported = ", ".join(mode_support) if mode_support else "none"
        raise ValueError(f"Platform '{platform}' does not support {resolved_mode} mode. Supported modes: {supported}")

    # Resolve deployment mode: explicit > from name suffix > platform default
    resolved_deployment = _resolve_deployment_mode(base_platform, deployment, deployment_from_name, caps)

    # Validate deployment mode support
    if resolved_deployment is not None:
        if not PlatformRegistry.supports_deployment_mode(base_platform, resolved_deployment):
            available = PlatformRegistry.get_available_deployment_modes(base_platform)
            if available:
                available_str = ", ".join(available)
                raise ValueError(
                    f"Platform '{base_platform}' does not support deployment mode '{resolved_deployment}'. "
                    f"Available: {available_str}"
                )
            else:
                raise ValueError(
                    f"Platform '{base_platform}' does not support deployment modes. "
                    f"Remove the ':{resolved_deployment}' suffix."
                )

    # Pass deployment_mode to adapters via config if resolved
    if resolved_deployment is not None:
        config["deployment_mode"] = resolved_deployment

    # Route to appropriate adapter factory
    if resolved_mode == "sql":
        return _get_sql_adapter(base_platform, **config)
    else:
        return _get_dataframe_adapter(base_platform, **config)


def _resolve_deployment_mode(
    platform: str,
    explicit_deployment: Optional[str],
    deployment_from_name: Optional[str],
    caps: Any,
) -> Optional[str]:
    """Resolve deployment mode with priority: explicit > name suffix > platform default.

    Args:
        platform: Base platform name
        explicit_deployment: Explicitly requested deployment mode (highest priority)
        deployment_from_name: Deployment mode extracted from platform name suffix
        caps: Platform capabilities

    Returns:
        Resolved deployment mode, or None if platform has no deployment modes
    """
    # If platform has no deployment modes, return None
    if not caps.deployment_modes:
        # If user explicitly requested a deployment, that's an error
        # (will be caught by validation in caller)
        if explicit_deployment or deployment_from_name:
            return explicit_deployment or deployment_from_name
        return None

    # Priority 1: Explicit deployment parameter
    if explicit_deployment is not None:
        return explicit_deployment

    # Priority 2: Deployment from platform name suffix
    if deployment_from_name is not None:
        return deployment_from_name

    # Priority 3: Platform default deployment
    return caps.default_deployment


def _get_sql_adapter(platform: str, **config: Any) -> Any:
    """Get SQL adapter for platform.

    Args:
        platform: Platform name
        **config: Platform configuration

    Returns:
        SQL PlatformAdapter instance
    """
    # Import here to avoid circular imports
    from benchbox.platforms import get_platform_adapter

    return get_platform_adapter(platform, **config)


def _get_dataframe_adapter(platform: str, **config: Any) -> Any:
    """Get DataFrame adapter for platform.

    Args:
        platform: Platform name (without -df suffix)
        **config: Platform configuration

    Returns:
        DataFrame adapter instance
    """
    # Import the module (not names) to avoid circular imports and to ensure
    # monkeypatch/test stubs are visible via live attribute access.
    import benchbox.platforms.dataframe as _df

    driver_package = config.pop("driver_package", None)
    driver_version = config.pop("driver_version", None) or config.pop("driver_version_requested", None)
    driver_version_resolved = config.pop("driver_version_resolved", None)
    driver_auto_install = bool(config.pop("driver_auto_install", False))
    config.pop("driver_auto_install_used", None)  # consumed; resolution tracks this

    platform_info = PlatformRegistry.get_platform_info(platform)
    package_hint = driver_package or (platform_info.driver_package if platform_info else None)
    requested_version = driver_version
    resolution = ensure_driver_version(
        package_name=package_hint,
        requested_version=requested_version,
        auto_install=driver_auto_install,
        install_hint=platform_info.installation_command if platform_info else None,
    )
    resolved_version = resolution.resolved or driver_version_resolved
    requested = driver_version or resolution.requested

    adapter_mapping = {
        "polars": (_df.PolarsDataFrameAdapter, _df.POLARS_AVAILABLE, "pip install polars"),
        "pandas": (_df.PandasDataFrameAdapter, _df.PANDAS_AVAILABLE, "pip install pandas"),
        "modin": (_df.ModinDataFrameAdapter, _df.MODIN_AVAILABLE, "pip install modin[ray]"),
        "cudf": (_df.CuDFDataFrameAdapter, _df.CUDF_AVAILABLE, "pip install cudf-cu12"),
        "dask": (_df.DaskDataFrameAdapter, _df.DASK_AVAILABLE, "pip install dask[distributed]"),
        "pyspark": (_df.PySparkDataFrameAdapter, _df.PYSPARK_AVAILABLE, "pip install pyspark"),
        "lakesail": (_df.LakeSailDataFrameAdapter, _df.PYSPARK_AVAILABLE, "pip install pyspark"),
        "datafusion": (_df.DataFusionDataFrameAdapter, _df.DATAFUSION_DF_AVAILABLE, "pip install datafusion"),
    }

    if platform not in adapter_mapping:
        available = ", ".join(sorted(adapter_mapping.keys()))
        raise ValueError(f"Unknown DataFrame platform: {platform}. Available: {available}")

    adapter_class, is_available, install_cmd = adapter_mapping[platform]

    if not is_available or adapter_class is None:
        raise ImportError(
            f"DataFrame platform '{platform}' is not available. Install required dependencies: {install_cmd}"
        )

    check_isolation_capability(adapter_class, platform, resolution.runtime_strategy)

    adapter = adapter_class(**config)
    adapter.driver_package = resolution.package or package_hint
    adapter.driver_version_requested = requested
    adapter.driver_version_resolved = resolved_version
    adapter.driver_version_actual = resolution.actual
    adapter.driver_runtime_strategy = resolution.runtime_strategy
    adapter.driver_runtime_path = resolution.runtime_path
    adapter.driver_runtime_python_executable = resolution.runtime_python_executable
    adapter.driver_auto_install_used = resolution.auto_install_used

    return adapter


def is_dataframe_mode(platform: str, mode: Optional[str] = None) -> bool:
    """Check if the effective execution mode is dataframe.

    Args:
        platform: Platform name (may include -df suffix or :deployment suffix)
        mode: Explicit mode or None for default

    Returns:
        True if effective mode is dataframe
    """
    if mode is not None:
        return mode == "dataframe"

    # Check if -df suffix implies DataFrame mode
    base_platform, df_mode_implied, _ = _normalize_platform_name(platform)
    if df_mode_implied:
        return True

    return PlatformRegistry.get_default_mode(base_platform) == "dataframe"


def get_available_modes(platform: str) -> list[str]:
    """Get available execution modes for a platform.

    Args:
        platform: Platform name (may include -df suffix or :deployment suffix)

    Returns:
        List of supported modes ('sql', 'dataframe', or both)
    """
    base_platform, _, _ = _normalize_platform_name(platform)
    caps = PlatformRegistry.get_platform_capabilities(base_platform)
    if caps is None:
        return []

    modes = []
    if caps.supports_sql:
        modes.append("sql")
    if caps.supports_dataframe:
        modes.append("dataframe")
    return modes


def get_available_deployments(platform: str) -> list[str]:
    """Get available deployment modes for a platform.

    Args:
        platform: Platform name (may include -df suffix or :deployment suffix)

    Returns:
        List of supported deployment modes (e.g., ['local', 'server', 'cloud'])
    """
    base_platform, _, _ = _normalize_platform_name(platform)
    return PlatformRegistry.get_available_deployment_modes(base_platform)


def get_default_deployment(platform: str) -> Optional[str]:
    """Get the default deployment mode for a platform.

    Args:
        platform: Platform name (may include -df suffix or :deployment suffix)

    Returns:
        Default deployment mode or None if platform has no deployment modes
    """
    base_platform, _, _ = _normalize_platform_name(platform)
    return PlatformRegistry.get_default_deployment(base_platform)
