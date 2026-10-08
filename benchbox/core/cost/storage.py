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

    platform_lower = platform.lower()

    bytes_per_tb = 1024**4
    tb = total_bytes / bytes_per_tb

    region_tier = _map_region_to_tier(region)

    if platform_lower in STORAGE_PRICES_PER_TB_MONTH:
        price_per_tb_month = STORAGE_PRICES_PER_TB_MONTH[platform_lower].get(
            region_tier, STORAGE_PRICES_PER_TB_MONTH[platform_lower].get("us", 23.00)
        )
    else:
        price_per_tb_month = 23.00

    hours_per_month = 730
    storage_cost = tb * price_per_tb_month * (storage_duration_hours / hours_per_month)

    return {
        "storage_cost": storage_cost,
        "storage_tb": tb,
        "price_per_tb_month": price_per_tb_month,
        "duration_hours": storage_duration_hours,
        "note": STORAGE_NOTES.get(platform_lower, "Storage cost estimate based on standard cloud pricing."),
    }
