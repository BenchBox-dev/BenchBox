"""Database naming utilities with configuration-aware naming conventions.

This module provides utilities for generating distinct database names that reflect
their configuration characteristics, enabling users to understand configuration
details from the database name alone.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import hashlib
import re
from typing import Any, Optional

from benchbox.utils.scale_factor import format_scale_factor


def _tuning_config_to_dict(tuning_config: Optional[Any]) -> Optional[dict[str, Any]]:
    """Convert tuning configuration to dictionary format.

    Args:
        tuning_config: Tuning configuration (dict, dataclass, or object)

    Returns:
        Dictionary representation or None if not convertible
    """
    if not tuning_config:
        return None

    if isinstance(tuning_config, dict):
        return tuning_config

    if hasattr(tuning_config, "__dict__"):
        try:
            import dataclasses

            if dataclasses.is_dataclass(tuning_config):
                return dataclasses.asdict(tuning_config)
            else:
                return tuning_config.__dict__
        except (ImportError, AttributeError):
            return vars(tuning_config) if hasattr(tuning_config, "__dict__") else None

    return None


def _clean_name_component(name: str, max_length: Optional[int] = None) -> str:
    """Clean and validate a name component for database naming.

    Args:
        name: Component to clean
        max_length: Maximum length to enforce

    Returns:
        Cleaned name component safe for database names
    """
    # Convert to lowercase and replace invalid characters
    cleaned = re.sub(r"[^a-z0-9]", "", name.lower())

    if max_length and len(cleaned) > max_length:
        cleaned = cleaned[:max_length]

    return cleaned


def _get_tuning_mode(tuning_config: Optional[Any]) -> str:
    """Determine the tuning mode from configuration.

    Args:
        tuning_config: Unified tuning configuration (dict, dataclass, or object)

    Returns:
        String representing tuning mode (tuned, notuning, custom)
    """
    config_dict = _tuning_config_to_dict(tuning_config)
    if not config_dict:
        return "notuning"

    # Check for explicit configuration type in metadata first
    metadata = config_dict.get("_metadata", {})
    config_type = metadata.get("configuration_type", "")

    if config_type == "notuning":
        return "notuning"
    elif config_type in ("tuned", "optimized"):
        return "tuned"

    # If no explicit metadata, check the actual configuration
    primary_keys = config_dict.get("primary_keys", {})
    foreign_keys = config_dict.get("foreign_keys", {})
    platform_opts = config_dict.get("platform_optimizations", {})
    table_tunings = config_dict.get("table_tunings", {})

    # Standard no-tuning: all constraints disabled, no optimizations
    if (
        not primary_keys.get("enabled", False)
        and not foreign_keys.get("enabled", False)
        and not table_tunings
        and not any(platform_opts.get(key, False) for key in platform_opts if "enabled" in str(key))
    ):
        return "notuning"

    # Otherwise it's a custom configuration
    return "custom"


def _get_constraints_suffix(tuning_config: Optional[Any]) -> str:
    """Get constraints suffix based on configuration.

    Args:
        tuning_config: Unified tuning configuration (dict, dataclass, or object)

    Returns:
        String suffix describing constraint configuration
    """
    config_dict = _tuning_config_to_dict(tuning_config)
    if not config_dict:
        return "noconstraints"

    components = []

    # Primary keys
    primary_keys = config_dict.get("primary_keys", {})
    if primary_keys.get("enabled", False):
        components.append("pk")

    # Foreign keys
    foreign_keys = config_dict.get("foreign_keys", {})
    if foreign_keys.get("enabled", False):
        components.append("fk")

    # Unique constraints
    unique_constraints = config_dict.get("unique_constraints", {})
    if unique_constraints.get("enabled", False):
        components.append("uniq")

    # Check constraints
    check_constraints = config_dict.get("check_constraints", {})
    if check_constraints.get("enabled", False):
        components.append("check")

    if not components:
        return "noconstraints"

    return "_".join(components)


def _get_optimizations_suffix(tuning_config: Optional[Any]) -> str:
    """Get platform optimizations suffix based on configuration.

    Args:
        tuning_config: Unified tuning configuration (dict, dataclass, or object)

    Returns:
        String suffix describing platform optimizations
    """
    config_dict = _tuning_config_to_dict(tuning_config)
    if not config_dict:
        return ""

    components = []

    platform_opts = config_dict.get("platform_optimizations", {})
    table_tunings = config_dict.get("table_tunings", {})

    _PLATFORM_OPT_LABELS = [
        ("z_ordering_enabled", "zorder"),
        ("auto_optimize_enabled", "autoopt"),
        ("materialized_views_enabled", "matview"),
    ]
    components.extend(label for key, label in _PLATFORM_OPT_LABELS if platform_opts.get(key, False))

    _TABLE_TUNING_LABELS = [
        ("partitioning", "part"),
        ("clustering", "clust"),
        ("sorting", "sort"),
        ("distribution", "dist"),
    ]
    detected = {
        key for tc in table_tunings.values() if isinstance(tc, dict) for key, _ in _TABLE_TUNING_LABELS if tc.get(key)
    }
    components.extend(label for key, label in _TABLE_TUNING_LABELS if key in detected)

    return "_".join(components) if components else ""


def _get_config_hash(tuning_config: Optional[Any]) -> str:
    """Generate a short hash of the configuration for uniqueness.

    Args:
        tuning_config: Unified tuning configuration (dict, dataclass, or object)

    Returns:
        Short hash string (6 characters)
    """
    config_dict = _tuning_config_to_dict(tuning_config)
    if not config_dict:
        return "000000"

    # Create a stable string representation of the config
    # Exclude metadata that shouldn't affect the hash
    config_copy = config_dict.copy()
    config_copy.pop("_metadata", None)

    config_str = str(sorted(config_copy.items()))
    hash_obj = hashlib.md5(config_str.encode("utf-8"))
    return hash_obj.hexdigest()[:6]


def generate_database_name(
    benchmark_name: str,
    scale_factor: float,
    platform: str,
    tuning_config: Optional[Any] = None,
    custom_name: Optional[str] = None,
    template: str = "{benchmark}_{scale}_{tuning}_{constraints}_{optimizations}",
) -> str:
    """Generate a distinct database name based on configuration characteristics.

    Args:
        benchmark_name: Name of benchmark (e.g., 'tpch', 'tpcds')
        scale_factor: Scale factor value
        platform: Platform name (for validation/compatibility checks)
        tuning_config: Unified tuning configuration (dict, dataclass, or object)
        custom_name: Custom name override (if provided, validates and returns)
        template: Name template with placeholders

    Returns:
        Generated database name reflecting configuration

    Example names:
        - tpch_sf01_tuned_pk_fk_part_sort
        - tpcds_sf1_notuning_noconstraints
        - primitives_sf001_custom_pk_abc123
    """
    # If custom name provided, validate and return
    if custom_name:
        return _clean_name_component(custom_name, max_length=64)

    # Check for database name in tuning configuration metadata
    tuning_dict = _tuning_config_to_dict(tuning_config)
    if tuning_dict and "_metadata" in tuning_dict:
        metadata_db_name = tuning_dict["_metadata"].get("database_name")
        if metadata_db_name:
            return _clean_name_component(metadata_db_name, max_length=64)

    # Generate name components
    benchmark = _clean_name_component(benchmark_name)
    scale = format_scale_factor(scale_factor)
    tuning_mode = _get_tuning_mode(tuning_config)
    constraints = _get_constraints_suffix(tuning_config)
    optimizations = _get_optimizations_suffix(tuning_config)

    # Build name using template
    name_parts = {
        "benchmark": benchmark,
        "scale": scale,
        "tuning": tuning_mode,
        "constraints": constraints,
        "optimizations": optimizations,
        "platform": _clean_name_component(platform),
        "hash": _get_config_hash(tuning_config),
    }

    # Fill template
    try:
        name = template.format(**name_parts)
    except KeyError:
        # Fallback to default template if custom template has invalid placeholders
        name = f"{benchmark}_{scale}_{tuning_mode}_{constraints}"
        if optimizations:
            name += f"_{optimizations}"

    # Clean up the final name
    # Strip empty components and multiple underscores
    name = re.sub(r"_+", "_", name)  # Multiple underscores to single
    name = re.sub(r"_$", "", name)  # Trailing underscore
    name = re.sub(r"^_", "", name)  # Leading underscore

    # Ensure name is not too long (database-dependent limits)
    max_length = 63  # Conservative limit for most databases
    if len(name) > max_length:
        # If too long, use hash-based truncation
        hash_part = _get_config_hash(tuning_config)
        base_length = max_length - len(hash_part) - 1  # -1 for underscore
        name = f"{name[:base_length]}_{hash_part}"

    return name


def generate_database_filename(
    benchmark_name: str,
    scale_factor: float,
    platform: str,
    tuning_config: Optional[Any] = None,
    custom_name: Optional[str] = None,
    template: str = "{benchmark}_{scale}_{tuning}_{constraints}_{optimizations}",
) -> str:
    """Generate database filename with appropriate extension.

    Args:
        benchmark_name: Name of benchmark
        scale_factor: Scale factor value
        platform: Platform name (determines file extension)
        tuning_config: Unified tuning configuration (dict, dataclass, or object)
        custom_name: Custom name override
        template: Name template with placeholders

    Returns:
        Database filename with extension (e.g., 'tpch_sf01_tuned_pk_fk.duckdb')
    """
    name = generate_database_name(
        benchmark_name=benchmark_name,
        scale_factor=scale_factor,
        platform=platform,
        tuning_config=tuning_config,
        custom_name=custom_name,
        template=template,
    )

    # Get file extension based on platform
    # Each platform MUST have a unique extension to prevent collisions
    # when multiple platforms store data in the same directory
    extensions = {
        # SQL databases
        "duckdb": ".duckdb",
        "sqlite": ".sqlite",
        "sqlite3": ".sqlite",
        "clickhouse": ".chdb",
        # DataFrame platforms (SQL mode) - directory-based storage
        "datafusion": ".datafusion",
        "polars": ".polars",
        "pandas": ".pandas",
        # DataFrame platforms (native API mode)
        "polars-df": ".polars-df",
        "pandas-df": ".pandas-df",
        "cudf-df": ".cudf-df",
        "modin-df": ".modin-df",
        "dask-df": ".dask-df",
        # Additional platform-specific entries
        "cudf": ".cudf",
        "spark": ".spark",
    }
    # Use platform-specific extension; raise error for unknown platforms
    # to prevent accidental collisions with generic extensions
    platform_lower = platform.lower()
    if platform_lower not in extensions:
        # For unknown platforms, create a unique extension from the platform name
        # This prevents collisions while being flexible for new platforms
        ext = f".{platform_lower}"
    else:
        ext = extensions[platform_lower]

    return f"{name}{ext}"


_KNOWN_EXTENSIONS = [
    ".duckdb", ".sqlite", ".chdb", ".datafusion",
    ".polars-df", ".polars", ".pandas-df", ".pandas",
    ".cudf-df", ".cudf", ".modin-df", ".dask-df", ".spark",
]  # fmt: skip

_TUNING_KEYWORDS = {"notuning": "notuning", "tuned": "tuned", "custom": "custom"}
_CONSTRAINT_KEYWORDS = {"pk", "fk", "uniq", "check", "noconstraints"}
_OPTIMIZATION_KEYWORDS = {"part", "clust", "sort", "dist", "zorder", "autoopt", "matview"}


def _parse_scale_factor(part: str) -> float | None:
    """Parse a scale factor from a 'sfN' part, or return None."""
    if not part.startswith("sf"):
        return None
    scale_str = part[2:]
    try:
        if scale_str.startswith("0") and len(scale_str) > 1:
            return float("0." + scale_str[1:])
        return float(scale_str)
    except ValueError:
        return None


def parse_database_name(database_name: str) -> dict[str, Any]:
    """Parse a database name to extract configuration characteristics.

    Args:
        database_name: Database name to parse

    Returns:
        Dictionary with parsed characteristics
    """
    name = database_name
    for ext in _KNOWN_EXTENSIONS:
        if name.endswith(ext):
            name = name[: -len(ext)]
            break

    parts = name.split("_")
    parts_set = set(parts)

    result: dict[str, Any] = {
        "original_name": database_name,
        "parsed_parts": parts,
        "benchmark": parts[0] if parts else "",
        "scale_factor": None,
        "tuning_mode": "unknown",
        "has_constraints": False,
        "has_optimizations": False,
        "characteristics": [],
    }

    for part in parts:
        sf = _parse_scale_factor(part)
        if sf is not None:
            result["scale_factor"] = sf
            break

    for keyword, mode in _TUNING_KEYWORDS.items():
        if keyword in parts_set:
            result["tuning_mode"] = mode
            break

    for part in parts:
        if part in _CONSTRAINT_KEYWORDS:
            result["has_constraints"] = part != "noconstraints"
            result["characteristics"].append(part)

    matched_opts = parts_set & _OPTIMIZATION_KEYWORDS
    if matched_opts:
        result["has_optimizations"] = True
        result["characteristics"].extend(p for p in parts if p in matched_opts)

    return result


def validate_database_name(name: str, platform: str) -> bool:
    """Validate that a database name is compatible with the platform.

    Args:
        name: Database name to validate
        platform: Target platform name

    Returns:
        True if valid for the platform
    """
    if not name:
        return False

    # General validation rules
    if len(name) > 63:  # Conservative limit
        return False

    if not re.match(r"^[a-z][a-z0-9_]*$", name.lower()):
        return False

    # Platform-specific validation could be added here
    return True


def list_database_configurations(database_names: list[str]) -> list[dict[str, Any]]:
    """Parse and list configurations from multiple database names.

    Args:
        database_names: List of database names to parse

    Returns:
        List of parsed configuration dictionaries
    """
    return [parse_database_name(name) for name in database_names]
