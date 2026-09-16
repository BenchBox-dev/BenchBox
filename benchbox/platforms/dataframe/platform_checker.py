"""DataFrame Platform Availability Detection and Error Handling.

Provides runtime platform availability detection with graceful error handling
when platforms are not installed. Offers helpful error messages with
installation instructions.

Features:
- Detect which DataFrame platforms are installed
- Provide version information for installed platforms
- Generate helpful installation guidance
- Validate platform compatibility

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from benchbox.utils.dependencies import get_extra_install_message

logger = logging.getLogger(__name__)


class DataFrameFamily(Enum):
    """DataFrame library family classification."""

    PANDAS = "pandas"
    EXPRESSION = "expression"


@dataclass
class PlatformInfo:
    """Information about a DataFrame platform."""

    name: str
    family: DataFrameFamily
    import_name: str
    version_attr: str
    extra_name: str
    description: str
    min_version: str | None = None
    max_version: str | None = None


# Registry of DataFrame platforms
DATAFRAME_PLATFORMS: dict[str, PlatformInfo] = {
    "pandas": PlatformInfo(
        name="Pandas",
        family=DataFrameFamily.PANDAS,
        import_name="pandas",
        version_attr="__version__",
        extra_name="pandas",
        description="Reference Pandas implementation",
        min_version="2.0.0",
    ),
    "polars": PlatformInfo(
        name="Polars",
        family=DataFrameFamily.EXPRESSION,
        import_name="polars",
        version_attr="__version__",
        extra_name="",  # Core dependency
        description="Fast expression-based DataFrame library",
        min_version="1.0.0",
    ),
    "dask": PlatformInfo(
        name="Dask",
        family=DataFrameFamily.PANDAS,
        import_name="dask",
        version_attr="__version__",
        extra_name="dask",
        description="Parallel computing library with DataFrame support",
        min_version="2024.1.0",
    ),
    "cudf": PlatformInfo(
        name="cuDF",
        family=DataFrameFamily.PANDAS,
        import_name="cudf",
        version_attr="__version__",
        extra_name="cudf",
        description="GPU-accelerated DataFrame library (NVIDIA RAPIDS)",
        min_version="25.02.0",
    ),
    "pyspark": PlatformInfo(
        name="PySpark",
        family=DataFrameFamily.EXPRESSION,
        import_name="pyspark",
        version_attr="__version__",
        extra_name="pyspark",
        description="Apache Spark Python API",
        min_version="3.5.0",
    ),
    "datafusion": PlatformInfo(
        name="DataFusion",
        family=DataFrameFamily.EXPRESSION,
        import_name="datafusion",
        version_attr="__version__",
        extra_name="datafusion",
        description="Apache DataFusion query engine",
        min_version="54.0.0",
    ),
}


@dataclass
class PlatformStatus:
    """Status of a DataFrame platform."""

    platform: str
    available: bool
    version: str | None
    info: PlatformInfo
    error: str | None = None
    version_warning: str | None = None


class DataFramePlatformChecker:
    """Check availability and status of DataFrame platforms."""

    @staticmethod
    def is_available(platform: str) -> bool:
        """Check if a DataFrame platform is available.

        Args:
            platform: Platform name (e.g., 'pandas', 'polars')

        Returns:
            True if the platform can be imported
        """
        platform_lower = platform.lower()
        if platform_lower not in DATAFRAME_PLATFORMS:
            return False

        info = DATAFRAME_PLATFORMS[platform_lower]
        return importlib.util.find_spec(info.import_name) is not None

    @staticmethod
    def get_version(platform: str) -> str | None:
        """Get the installed version of a DataFrame platform.

        Args:
            platform: Platform name

        Returns:
            Version string or None if not installed
        """
        platform_lower = platform.lower()
        if platform_lower not in DATAFRAME_PLATFORMS:
            return None

        info = DATAFRAME_PLATFORMS[platform_lower]

        try:
            module = importlib.import_module(info.import_name)
            return getattr(module, info.version_attr, None)
        except ImportError:
            return None

    @staticmethod
    def check_platform(platform: str) -> PlatformStatus:
        """Check the status of a DataFrame platform.

        Args:
            platform: Platform name

        Returns:
            PlatformStatus with availability and version information
        """
        platform_lower = platform.lower()

        if platform_lower not in DATAFRAME_PLATFORMS:
            return PlatformStatus(
                platform=platform,
                available=False,
                version=None,
                info=PlatformInfo(
                    name=platform,
                    family=DataFrameFamily.PANDAS,
                    import_name=platform,
                    version_attr="__version__",
                    extra_name="",
                    description="Unknown platform",
                ),
                error=f"Unknown DataFrame platform: {platform}",
            )

        info = DATAFRAME_PLATFORMS[platform_lower]
        version = DataFramePlatformChecker.get_version(platform)
        available = version is not None

        # Check version compatibility: below-minimum installs report
        # unavailable so callers fail fast instead of crashing on
        # version-gated API calls later.
        version_warning = None
        error = None
        if available and version and info.min_version:
            from packaging import version as pkg_version

            try:
                installed = pkg_version.parse(version)
                minimum = pkg_version.parse(info.min_version)
                if installed < minimum:
                    available = False
                    error = (
                        f"{info.name} {version} is installed but >={info.min_version} "
                        f"is required; upgrade the '{info.extra_name}' extra."
                    )
            except Exception:
                pass

        return PlatformStatus(
            platform=platform_lower,
            available=available,
            version=version,
            info=info,
            error=error,
            version_warning=version_warning,
        )

    @staticmethod
    def get_available_platforms() -> list[str]:
        """Get list of all available DataFrame platforms.

        Returns:
            List of platform names that are installed
        """
        return [name for name in DATAFRAME_PLATFORMS if DataFramePlatformChecker.is_available(name)]

    @staticmethod
    def get_available_by_family(family: DataFrameFamily) -> list[str]:
        """Get available platforms for a specific family.

        Args:
            family: The DataFrame family

        Returns:
            List of available platform names in that family
        """
        return [
            name
            for name, info in DATAFRAME_PLATFORMS.items()
            if info.family == family and DataFramePlatformChecker.is_available(name)
        ]

    @staticmethod
    def get_all_platforms() -> dict[str, PlatformInfo]:
        """Get information about all DataFrame platforms.

        Returns:
            Dictionary mapping platform name to PlatformInfo
        """
        return DATAFRAME_PLATFORMS.copy()

    @staticmethod
    def check_all_platforms() -> dict[str, PlatformStatus]:
        """Check status of all DataFrame platforms.

        Returns:
            Dictionary mapping platform name to PlatformStatus
        """
        return {name: DataFramePlatformChecker.check_platform(name) for name in DATAFRAME_PLATFORMS}


def get_installation_suggestion(platform: str) -> str:
    """Generate installation suggestion for a DataFrame platform.

    Args:
        platform: Platform name

    Returns:
        Formatted installation instructions
    """
    platform_lower = platform.lower()

    if platform_lower not in DATAFRAME_PLATFORMS:
        return f"Unknown DataFrame platform: {platform}"

    info = DATAFRAME_PLATFORMS[platform_lower]

    if not info.extra_name:
        # Core dependency (polars)
        return f"{info.name} is a core dependency and should already be installed."

    message = f"Platform '{info.name}' is not available.\n\n{get_extra_install_message(info.extra_name)}"

    if info.min_version:
        message += (
            f"\n\nOr install directly (minimum version {info.min_version}):\n"
            f'  pip install "{info.import_name}>={info.min_version}"'
        )

    return message


def get_platform_error_message(platform: str, error: Exception | None = None) -> str:
    """Generate a helpful error message when a platform is unavailable.

    Args:
        platform: Platform name
        error: Optional exception that occurred

    Returns:
        Formatted error message with installation guidance
    """
    platform_lower = platform.lower()

    if platform_lower not in DATAFRAME_PLATFORMS:
        return f"Unknown DataFrame platform: {platform}"

    info = DATAFRAME_PLATFORMS[platform_lower]
    status = DataFramePlatformChecker.check_platform(platform)

    if status.available:
        if error:
            return f"Platform '{info.name}' is available (version {status.version}) but encountered an error:\n{error}"
        return f"Platform '{info.name}' is available (version {status.version})."

    lines = [
        f"DataFrame platform '{info.name}' is not available.",
        "",
        f"Description: {info.description}",
        f"Family: {info.family.value}",
    ]
    if status.error:
        lines += ["", f"Reason: {status.error}"]

    if info.extra_name:
        lines.append("")
        lines.append(get_extra_install_message(info.extra_name))
    else:
        lines.extend(
            [
                "",
                f"{info.name} is a core dependency and should be installed automatically.",
                "Try reinstalling benchbox:",
                "  uv sync  # inside a project\n  uv tool install benchbox --force  # standalone tool",
            ]
        )

    # Add family group suggestions
    if info.family == DataFrameFamily.PANDAS:
        lines.append("")
        lines.append(get_extra_install_message("dataframe-pandas-family", "For all Pandas-family platforms:"))
    else:
        lines.append("")
        lines.append(get_extra_install_message("dataframe-expression-family", "For all expression-family platforms:"))

    lines.append("")
    lines.append(get_extra_install_message("dataframe-all", "For all DataFrame platforms:"))

    return "\n".join(lines)


def require_platform(platform: str) -> Any:
    """Import and return a DataFrame platform module, raising helpful error if unavailable.

    Args:
        platform: Platform name

    Returns:
        The imported module

    Raises:
        ImportError: If the platform is not available, with helpful message
    """
    platform_lower = platform.lower()

    if platform_lower not in DATAFRAME_PLATFORMS:
        raise ImportError(f"Unknown DataFrame platform: {platform}")

    info = DATAFRAME_PLATFORMS[platform_lower]

    try:
        return importlib.import_module(info.import_name)
    except ImportError as e:
        raise ImportError(get_platform_error_message(platform, e)) from e


def format_platform_status_table() -> str:
    """Format a table showing all platform statuses.

    Returns:
        Formatted table string
    """
    statuses = DataFramePlatformChecker.check_all_platforms()

    lines = [
        "DataFrame Platform Status",
        "=" * 60,
        f"{'Platform':<15} {'Family':<12} {'Available':<10} {'Version':<15}",
        "-" * 60,
    ]

    for _name, status in sorted(statuses.items()):
        avail = "✓" if status.available else "✗"
        version = status.version or "N/A"
        family = status.info.family.value
        lines.append(f"{status.info.name:<15} {family:<12} {avail:<10} {version:<15}")

    lines.append("-" * 60)

    # Count available
    available_count = sum(1 for s in statuses.values() if s.available)
    lines.append(f"Available: {available_count}/{len(statuses)} platforms")

    return "\n".join(lines)
