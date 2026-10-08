from __future__ import annotations

import re
from typing import Any

from benchbox.utils.scale_factor import format_scale_factor


def slugify(text: str) -> str:
    slug = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in text.strip().lower())
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "untitled"


def natural_query_sort_key(value: str) -> tuple[float, str]:
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
    if not results:
        return None

    r = results[0]
    benchmark = getattr(r, "benchmark", None)
    scale_factor = getattr(r, "scale_factor", None)

    platform_version: str | None = None
    raw = getattr(r, "raw", {}) or {}
    platform_block = raw.get("platform") or raw.get("platform_info") or {}
    version = platform_block.get("version")
    if version:
        if version in r.platform:
            platform_version = r.platform
        else:
            platform_version = f"{r.platform} {version}"

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
    raw = getattr(result, "raw", {}) or {}
    benchmark = raw.get("benchmark") or {}
    return isinstance(benchmark, dict) and benchmark.get("test_type") == "power"
