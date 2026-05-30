"""Dependency management utilities for BenchBox platform adapters.

Provides centralized dependency checking, error messages, and installation guidance
for optional platform dependencies.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sys
from collections.abc import Sequence
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Optional

import yaml


@lru_cache(maxsize=1)
def is_development_install() -> bool:
    """Detect if BenchBox is running from a development install.

    Returns True if running from source (editable install), False if installed as a package.
    """
    import benchbox

    # Get the package location
    package_path = Path(benchbox.__file__).parent

    # Check if pyproject.toml exists in parent (development install)
    project_root = package_path.parent
    if (project_root / "pyproject.toml").exists():
        # Verify it's actually the benchbox project
        try:
            content = (project_root / "pyproject.toml").read_text()
            if 'name = "benchbox"' in content:
                return True
        except Exception:
            pass

    # Check if we're in site-packages (package install)
    # Default to dev install if uncertain
    return "site-packages" not in str(package_path)


@lru_cache(maxsize=1)
def is_uv_tool_environment() -> bool:
    """Detect whether BenchBox is running inside a uv tool virtual environment."""
    normalized_executable = str(Path(sys.executable)).replace("\\", "/").lower()
    return "/uv/tools/" in normalized_executable


# Dependency catalog data is loaded after the lightweight value classes below.
PLATFORM_TO_EXTRA: dict[str, str]


def get_install_command(extra: str) -> str:
    """Get the appropriate install command for an extra based on install type.

    Args:
        extra: The extra name or platform name (e.g., 'athena', 'modin', 'cloud')

    Returns:
        The appropriate install command string
    """
    # Map platform names to their actual extra names
    resolved_extra = PLATFORM_TO_EXTRA.get(extra.lower(), extra)

    if is_development_install():
        if is_uv_tool_environment():
            # uv tool environments are isolated from project .venv state.
            # Target the running interpreter explicitly so users install
            # into the same environment that executes `benchbox`.
            return f'uv pip install --python "{sys.executable}" "benchbox[{resolved_extra}]"'
        return f"uv sync --extra {resolved_extra}"
    else:
        return f'uv pip install "benchbox[{resolved_extra}]"'


def get_package_install_message(packages: str, description: str = "") -> str:
    """Generate a user-friendly install message for raw Python packages.

    Provides both standalone (pip) and project (uv add) installation options.

    Args:
        packages: Space-separated package names (e.g., 'boto3' or 'azure-storage-blob azure-identity')
        description: Optional description of what the packages are for

    Returns:
        Multi-line install message with both options
    """
    prefix = f"{description} " if description else ""
    return (
        f"{prefix}Install with:\n  pip install {packages}  # standalone\n  uv add {packages}       # inside a project"
    )


def get_extra_install_message(extra_name: str, description: str = "") -> str:
    """Generate a user-friendly install message for BenchBox extras.

    Provides both standalone (pip install) and project (uv add) installation options.

    Args:
        extra_name: The BenchBox extra name (e.g., 'cloud', 'mcp', 'databricks')
        description: Optional description prefix

    Returns:
        Multi-line install message with both options
    """
    prefix = f"{description}\n" if description else ""
    return (
        f"{prefix}Install with:\n"
        f"  pip install 'benchbox[{extra_name}]'  # pip/venv\n"
        f"  uv add benchbox --extra {extra_name}  # uv project"
    )


class DependencyInfo:
    """Information about a platform dependency group."""

    def __init__(
        self,
        name: str,
        description: str,
        packages: list[str],
        install_command: str,
        use_cases: list[str],
        platforms: list[str],
    ):
        self.name = name
        self.description = description
        self.packages = packages
        self.install_command = install_command
        self.use_cases = use_cases
        self.platforms = platforms

    def get_install_message(self) -> str:
        """Get a context-aware install message with both standalone and project options.

        Returns:
            Multi-line install message showing both installation options.
        """
        return get_extra_install_message(self.name)


# Structured installation guidance for documentation and CLI matrix output
class InstallationScenario:
    """Represents a documented installation path for BenchBox."""

    def __init__(
        self,
        name: str,
        description: str,
        platforms: Sequence[str],
        dependency_groups: Sequence[str],
        notes: Optional[str] = None,
    ):
        self.name = name
        self.description = description
        self.platforms = list(platforms)
        self.dependency_groups = list(dependency_groups)
        self.notes = notes or ""

    def _extras_spec(self) -> str:
        if not self.dependency_groups:
            return ""
        return ",".join(self.dependency_groups)

    @property
    def extras_label(self) -> str:
        return self._extras_spec() or "core"

    @property
    def uv_command(self) -> str:
        """Modern uv add command (recommended)."""
        extras = self._extras_spec()
        if extras:
            extra_flags = " ".join(f"--extra {e}" for e in extras.split(","))
            return f"uv add benchbox {extra_flags}"
        return "uv add benchbox"

    @property
    def uv_pip_command(self) -> str:
        """Alternative pip-compatible uv command."""
        extras = self._extras_spec()
        if extras:
            return f'uv pip install "benchbox[{extras}]"'
        return "uv pip install benchbox"

    @property
    def pip_command(self) -> str:
        extras = self._extras_spec()
        if extras:
            return f'python -m pip install "benchbox[{extras}]"'
        return "python -m pip install benchbox"

    @property
    def pipx_command(self) -> str:
        extras = self._extras_spec()
        if extras:
            return f'pipx install "benchbox[{extras}]"'
        return "pipx install benchbox"


# Dependency catalog data is package metadata; Python keeps behavior and typed value objects.


def _load_dependency_payload() -> dict[str, Any]:
    with resources.files(__package__).joinpath("dependencies.yaml").open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError("dependencies.yaml must contain a mapping")
    return payload


def _dependency_info_from_payload(entry: dict[str, Any]) -> DependencyInfo:
    return DependencyInfo(
        name=str(entry["name"]),
        description=str(entry["description"]),
        packages=list(entry["packages"]),
        install_command=str(entry["install_command"]),
        use_cases=list(entry["use_cases"]),
        platforms=list(entry["platforms"]),
    )


def _scenario_from_payload(entry: dict[str, Any]) -> InstallationScenario:
    return InstallationScenario(
        name=str(entry["name"]),
        description=str(entry["description"]),
        platforms=list(entry["platforms"]),
        dependency_groups=list(entry["dependency_groups"]),
        notes=str(entry.get("notes") or ""),
    )


_DEPENDENCY_PAYLOAD = _load_dependency_payload()
PLATFORM_TO_EXTRA = dict(_DEPENDENCY_PAYLOAD["platform_to_extra"])
DATAFRAME_DEPENDENCY_GROUPS: dict[str, DependencyInfo] = {
    name: _dependency_info_from_payload(entry)
    for name, entry in _DEPENDENCY_PAYLOAD["dataframe_dependency_groups"].items()
}
DEPENDENCY_GROUPS: dict[str, DependencyInfo] = {
    name: _dependency_info_from_payload(entry) for name, entry in _DEPENDENCY_PAYLOAD["dependency_groups"].items()
}
INSTALLATION_SCENARIOS: tuple[InstallationScenario, ...] = tuple(
    _scenario_from_payload(entry) for entry in _DEPENDENCY_PAYLOAD["installation_scenarios"]
)
PACKAGE_IMPORT_NAMES: dict[str, str] = dict(_DEPENDENCY_PAYLOAD["package_import_names"])


def check_platform_dependencies(platform: str, packages: Optional[Sequence[str]] = None) -> tuple[bool, list[str]]:
    """Check if required packages are available for a platform.

    Args:
        platform: Platform name (e.g., 'databricks', 'clickhouse')
        packages: Optional explicit list of required package names

    Returns:
        Tuple of (all_available, missing_packages)
    """
    if packages is None:
        dep_info = DEPENDENCY_GROUPS.get(platform.lower())
        platforms_packages: Sequence[str] = dep_info.packages if dep_info else ()
    else:
        platforms_packages = packages

    missing: list[str] = []
    for package in platforms_packages:
        try:
            # Use mapping if available, otherwise fall back to simple hyphen-to-underscore replacement
            import_name = PACKAGE_IMPORT_NAMES.get(package, package.replace("-", "_"))
            __import__(import_name)
        except ImportError:
            missing.append(package)

    return len(missing) == 0, missing


def get_dependency_error_message(platform: str, missing_packages: list[str]) -> str:
    """Generate a helpful error message for missing platform dependencies.

    Args:
        platform: Platform name
        missing_packages: List of missing package names

    Returns:
        Formatted error message with installation instructions
    """
    platform_lower = platform.lower()
    dep_info = DEPENDENCY_GROUPS.get(platform_lower)

    if not dep_info:
        # Fallback for unknown platforms
        packages_str = ", ".join(missing_packages)
        return (
            f"Missing required dependencies for {platform}: {packages_str}\n"
            f"Install with: uv pip install {' '.join(missing_packages)}"
        )

    message_parts = [
        f"Missing dependencies for {platform} platform:",
        f"  Extra: benchbox[{dep_info.name}]",
        f"  Required packages: {', '.join(missing_packages)}",
        "",
        dep_info.get_install_message(),
        "",
        "This extra provides:",
        f"  • {dep_info.description}",
    ]

    if dep_info.use_cases:
        message_parts.extend(
            [
                f"  • Use cases: {', '.join(dep_info.use_cases)}",
            ]
        )

    if dep_info.platforms:
        message_parts.extend(
            [
                f"  • Supports: {', '.join(dep_info.platforms)}",
            ]
        )

    # Add alternative installation suggestions
    message_parts.extend(
        [
            "",
            "Bundle installations (recommended):",
            "  • For all cloud platforms: uv add benchbox --extra cloud",
            "  • For everything: uv add benchbox --extra all",
            "",
            "Alternative (pip-compatible):",
            '  • For all cloud platforms: uv pip install "benchbox[cloud]"',
            '  • For everything: uv pip install "benchbox[all]"',
            "",
            f"Need more guidance? Run: benchbox check-deps --platform {platform_lower}",
        ]
    )

    return "\n".join(message_parts)


def get_installation_recommendations(use_case: Optional[str] = None) -> list[str]:
    """Get installation recommendations based on use case.

    Args:
        use_case: Optional use case description

    Returns:
        List of recommended installation commands
    """
    recommendations = []

    if use_case:
        use_case_lower = use_case.lower()
        if "cloud" in use_case_lower or "multi" in use_case_lower:
            recommendations.append("uv add benchbox --extra cloud  # All major cloud platforms")
        elif "databricks" in use_case_lower or "delta" in use_case_lower:
            recommendations.append("uv add benchbox --extra databricks  # Databricks + Unity Catalog")
        elif "bigquery" in use_case_lower or "google" in use_case_lower:
            recommendations.append("uv add benchbox --extra bigquery  # Google BigQuery + Cloud Storage")
        elif "redshift" in use_case_lower or "aws" in use_case_lower:
            recommendations.append("uv add benchbox --extra redshift  # Amazon Redshift + S3")
        elif "snowflake" in use_case_lower:
            recommendations.append("uv add benchbox --extra snowflake  # Snowflake cloud DW")
        elif "clickhouse" in use_case_lower:
            recommendations.append("uv add benchbox --extra clickhouse  # ClickHouse analytics")
        elif "presto" in use_case_lower:
            recommendations.append("uv add benchbox --extra presto  # PrestoDB distributed SQL")
        elif "trino" in use_case_lower:
            recommendations.append("uv add benchbox --extra trino  # Trino/Starburst distributed SQL")

    # Always include general recommendations
    if not recommendations:
        recommendations.extend(
            [
                "uv add benchbox --extra cloud          # Major cloud platforms (recommended)",
                "uv add benchbox --extra all            # All platforms + features",
                "uv add benchbox --extra cloudstorage   # Cloud storage helpers only",
                "uv add benchbox --extra databricks     # Databricks only",
                "uv add benchbox --extra bigquery       # BigQuery only",
                "uv add benchbox --extra redshift       # Redshift only",
                "uv add benchbox --extra snowflake      # Snowflake only",
                "uv add benchbox --extra clickhouse     # ClickHouse only",
            ]
        )

    return recommendations


def list_available_dependency_groups() -> dict[str, DependencyInfo]:
    """Get all available dependency groups with their information."""
    return DEPENDENCY_GROUPS.copy()


def get_dependency_group_packages(platform: str) -> list[str]:
    """Return package names associated with a dependency group."""

    dep_info = DEPENDENCY_GROUPS.get(platform.lower())
    return list(dep_info.packages) if dep_info else []


def get_installation_scenarios() -> tuple[InstallationScenario, ...]:
    """Return curated installation scenarios."""
    return INSTALLATION_SCENARIOS


def get_installation_matrix_rows() -> list[tuple[str, str, str, str, str, str]]:
    """Build rows for installation matrix presentation.

    Returns:
        List of tuples: (scenario, platforms, extras, uv, pip, pipx)
    """

    rows: list[tuple[str, str, str, str, str, str]] = []
    for scenario in INSTALLATION_SCENARIOS:
        platforms = ", ".join(scenario.platforms)
        rows.append(
            (
                scenario.name,
                platforms,
                scenario.extras_label,
                scenario.uv_command,
                scenario.pip_command,
                scenario.pipx_command,
            )
        )
    return rows


def validate_dependency_group(group_name: str) -> bool:
    """Check if a dependency group name is valid."""
    return group_name.lower() in DEPENDENCY_GROUPS


def get_dependency_decision_tree() -> str:
    """Generate a decision tree for choosing dependency groups."""
    return """
BenchBox Dependency Installation Guide
=====================================

Choose your installation based on your needs:

Quick Start (Recommended)
   └── uv add benchbox --extra cloud
       • Includes: Databricks, BigQuery, Redshift, Snowflake
       • Best for: Most users, cloud platform comparison
       • Excludes: ClickHouse (add [all] if needed)
       Alternative: uv pip install "benchbox[cloud]"

Cloud Storage Paths
   └── uv add benchbox --extra cloudstorage
       • Enables: AWS S3, Google Cloud Storage, Azure Data Lake paths
       • Best for: Remote output directories or data staging without new adapters
       Alternative: uv pip install "benchbox[cloudstorage]"

Cloud Platform Specific
   ├── Databricks/Spark  → uv add benchbox --extra databricks
   ├── Google BigQuery   → uv add benchbox --extra bigquery
   ├── Amazon Redshift   → uv add benchbox --extra redshift
   └── Snowflake        → uv add benchbox --extra snowflake

Analytics Database
   └── ClickHouse       → uv add benchbox --extra clickhouse

Development/Testing
   ├── Everything       → uv add benchbox --extra all
   └── Core only        → uv add benchbox

Scenarios:
   • Multi-cloud comparison     → [cloud]
   • Single platform focus     → [platform-name]
   • Local development         → [all]
   • Minimal footprint        → benchbox (core only)
   • Maximum compatibility     → [all]

ℹ️  Core installation (just 'benchbox') includes DuckDB and works for:
   • Local benchmarking and testing
   • Data generation and query development
   • SQLite-based workflows

💡 Note: Add 'Alternative: uv pip install "benchbox[...]"' for pip-compatible syntax
"""
