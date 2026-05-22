"""Shared utilities for BenchBox visualization."""

from __future__ import annotations

import re
from typing import Any

from benchbox.utils.scale_factor import format_scale_factor


def slugify(text: str) -> str:
    """Convert text to a URL/filename-safe slug.

    Replaces non-alphanumeric characters with hyphens, collapses multiple
    hyphens, and strips leading/trailing hyphens.

    Args:
        text: The text to slugify.

    Returns:
        A lowercase, hyphen-separated slug. Returns "untitled" if the result
        would be empty.
    """
    slug = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in text.strip().lower())
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "untitled"


def natural_query_sort_key(value: str) -> tuple[float, str]:
    """Sort key for natural ordering of query IDs such as Q1, Q2, Q10."""
    match = re.match(r"^(\D*)(\d+)(.*)$", value)
    if match:
        prefix, num, suffix = match.groups()
        return (float(num), prefix + suffix)
    return (float("inf"), value)


def build_chart_subtitle(
    benchmark: str | None = None,
    scale_factor: float | str | None = None,
    platform_version: str | None = None,
    tuning: str | None = None,
) -> str | None:
    """Build a pipe-separated subtitle from benchmark metadata.

    Args:
        benchmark: Benchmark name (e.g., "tpch"). Uppercased in output.
        scale_factor: Scale factor - formatted via format_scale_factor if numeric.
        platform_version: Platform name with version (e.g., "DuckDB 1.2.0").
        tuning: Tuning mode label (e.g., "tuned").

    Returns:
        Pipe-separated subtitle string, or None if no parts are available.
    """
    parts: list[str] = []
    if benchmark:
        parts.append(benchmark.upper())
    if scale_factor is not None:
        parts.append(f"SF={format_scale_factor(float(scale_factor))}")
    if platform_version:
        parts.append(str(platform_version))
    if tuning:
        parts.append(str(tuning))
    return " | ".join(parts) if parts else None


def extract_chart_subtitle(results: list[Any]) -> str | None:
    """Extract a subtitle string from normalized results for chart display."""
    if not results:
        return None

    r = results[0]
    benchmark = getattr(r, "benchmark", None)
    scale_factor = getattr(r, "scale_factor", None)

    # Extract platform version from raw result data
    platform_version: str | None = None
    raw = getattr(r, "raw", {}) or {}
    platform_block = raw.get("platform") or raw.get("platform_info") or {}
    version = platform_block.get("version")
    if version:
        # Avoid "DuckDB 1.0.0 1.0.0" when the label was already disambiguated
        if version in r.platform:
            platform_version = r.platform
        else:
            platform_version = f"{r.platform} {version}"

    # Extract tuning config
    tuning: str | None = None
    config_block = raw.get("config") or {}
    tuning_val = config_block.get("tuning") or config_block.get("tuning_config")
    if tuning_val:
        tuning = str(tuning_val)

    return build_chart_subtitle(
        benchmark=benchmark,
        scale_factor=scale_factor,
        platform_version=platform_version,
        tuning=tuning,
    )


def is_power_run_result(result: Any) -> bool:
    """Return whether a normalized result came from a power-run benchmark file."""
    raw = getattr(result, "raw", {}) or {}
    benchmark = raw.get("benchmark") or {}
    return isinstance(benchmark, dict) and benchmark.get("test_type") == "power"
