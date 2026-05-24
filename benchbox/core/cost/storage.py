"""Storage cost estimation for benchmark data.

This module provides rough storage cost estimates based on data size and duration.
Storage pricing varies by platform, region, and storage tier.
"""

from pathlib import Path
from typing import Any

import yaml

from benchbox.core.cost.pricing import _map_region_to_tier


def _load_storage_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("storage_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_STORAGE_SPECS = _load_storage_specs()
STORAGE_PRICES_PER_TB_MONTH = _STORAGE_SPECS["prices_per_tb_month"]
STORAGE_NOTES = _STORAGE_SPECS["notes"]


def estimate_storage_cost(
    platform: str,
    total_bytes: int,
    storage_duration_hours: float,
    region: str = "us-east-1",
) -> dict[str, Any]:
    """Estimate storage cost based on data size and duration.

    This provides a rough estimate for planning purposes. Actual storage costs
    depend on many factors including:
    - Compression ratios
    - Storage tier (active vs long-term)
    - Time Travel / Fail-safe settings
    - Data replication
    - Snapshots and backups

    Args:
        platform: Platform name (snowflake, bigquery, redshift, databricks, etc.)
        total_bytes: Total data size in bytes
        storage_duration_hours: How long data is stored (hours)
        region: Cloud region

    Returns:
        Dictionary with storage cost estimate and metadata:
        - storage_cost: Estimated cost in USD
        - storage_tb: Data size in TB
        - price_per_tb_month: Monthly storage price per TB
        - duration_hours: Storage duration in hours
        - note: Platform-specific storage notes
    """
    platform_lower = platform.lower()

    # Convert bytes to TB
    bytes_per_tb = 1024**4
    tb = total_bytes / bytes_per_tb

    # Get region tier
    region_tier = _map_region_to_tier(region)

    # Get price per TB per month
    if platform_lower in STORAGE_PRICES_PER_TB_MONTH:
        price_per_tb_month = STORAGE_PRICES_PER_TB_MONTH[platform_lower].get(
            region_tier, STORAGE_PRICES_PER_TB_MONTH[platform_lower].get("us", 23.00)
        )
    else:
        # Default fallback for unknown platforms
        price_per_tb_month = 23.00

    # Prorate for actual duration
    hours_per_month = 730  # Average hours per month (365 days / 12 months * 24 hours)
    storage_cost = tb * price_per_tb_month * (storage_duration_hours / hours_per_month)

    return {
        "storage_cost": storage_cost,
        "storage_tb": tb,
        "price_per_tb_month": price_per_tb_month,
        "duration_hours": storage_duration_hours,
        "note": STORAGE_NOTES.get(platform_lower, "Storage cost estimate based on standard cloud pricing."),
    }
