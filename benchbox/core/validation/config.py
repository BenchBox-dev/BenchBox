"""Core benchmark configuration validation — platform, mode, benchmark checks.

Previously in ``benchbox.mcp.tools.benchmark._validate_*`` helpers.
Moved to core so CLI, MCP, and the run service share one validation path.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any


def validate_platform_config(
    platform: str, platform_lower: str, base_platform: str, errors: list[str], warnings: list[str]
) -> Any:
    """Validate platform availability and return platform info."""
    from benchbox.core.platform_registry import PlatformRegistry

    info = PlatformRegistry.get_platform_info(base_platform)
    if info is None:
        errors.append(f"Unknown platform: {platform}")
    elif not info.available:
        errors.append(f"Platform '{platform}' dependencies not installed: {info.installation_command}")

    cloud_platforms = ["snowflake", "bigquery", "databricks", "redshift"]
    if base_platform in cloud_platforms:
        warnings.append(f"Cloud platform '{platform}' requires credential configuration")

    return info


def validate_mode_config(
    mode: str | None, platform: str, base_platform: str, info: Any, errors: list[str]
) -> str | None:
    """Validate and resolve execution mode."""
    from benchbox.core.platform_registry import PlatformRegistry

    if mode is None:
        return PlatformRegistry.get_default_mode(base_platform)

    mode_lower = mode.lower()
    if mode_lower in ("datagen", "generate"):
        mode_lower = "data_only"

    if mode_lower not in ("sql", "dataframe", "data_only"):
        errors.append(f"Invalid mode: {mode}. Must be 'sql', 'dataframe', or 'data_only'")
        return None

    if mode_lower == "data_only":
        return "data_only"

    if info is not None and not PlatformRegistry.supports_mode(base_platform, mode_lower):
        supported = [m for m in ["sql", "dataframe"] if PlatformRegistry.supports_mode(base_platform, m)]
        supported.append("data_only")
        errors.append(f"Platform '{platform}' doesn't support {mode_lower} mode. Supported: {', '.join(supported)}")
        return None

    return mode_lower


def validate_benchmark_config(
    benchmark: str,
    benchmark_lower: str,
    scale_factor: float,
    platform_lower: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Validate benchmark name, scale factor, and dataframe compatibility."""
    from benchbox.core.benchmark_registry import get_all_benchmarks

    all_benchmarks = get_all_benchmarks()

    if benchmark_lower not in all_benchmarks:
        errors.append(f"Unknown benchmark: {benchmark}. Available: {', '.join(all_benchmarks.keys())}")
    else:
        meta = all_benchmarks[benchmark_lower]
        min_scale = meta.get("min_scale", 0.01)
        if scale_factor < min_scale:
            warnings.append(f"{benchmark} requires scale factor >= {min_scale}")
        if platform_lower.endswith("-df") and not meta.get("supports_dataframe", False):
            errors.append(f"DataFrame mode does not support {benchmark} benchmark")

    if scale_factor <= 0:
        errors.append(f"Scale factor must be positive, got: {scale_factor}")
    elif scale_factor < 0.01:
        warnings.append(f"Scale factor {scale_factor} is very small")


def validate_config(
    platform: str,
    benchmark: str,
    scale_factor: float,
    mode: str | None,
) -> dict[str, Any]:
    """Validate a benchmark configuration before running (core-owned)."""
    errors: list[str] = []
    warnings: list[str] = []

    platform_lower = platform.lower()
    base_platform = platform_lower.replace("-df", "")

    info = validate_platform_config(platform, platform_lower, base_platform, errors, warnings)
    resolved_mode = validate_mode_config(mode, platform, base_platform, info, errors)

    benchmark_lower = benchmark.lower()
    validate_benchmark_config(benchmark, benchmark_lower, scale_factor, platform_lower, errors, warnings)

    return {
        "valid": len(errors) == 0,
        "platform": platform,
        "benchmark": benchmark,
        "scale_factor": scale_factor,
        "execution_mode": resolved_mode,
        "errors": errors,
        "warnings": warnings,
    }
