"""CoffeeShop DataFrame query parameters.

Default parameter values for CoffeeShop queries.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

COFFEESHOP_DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "SA1": {"start_date": "2023-01-01", "end_date": "2023-01-31"},
    "SA2": {"year": 2023, "limit": 15},
    "SA3": {"year": 2023},
    "SA4": {"start_date": "2023-01-01", "end_date": "2024-12-31"},
    "SA5": {"start_date": "2023-01-01", "end_date": "2024-12-31", "limit": 20},
    "PR1": {"start_date": "2023-01-01", "end_date": "2023-12-31"},
    "PR2": {"start_date": "2023-01-01", "end_date": "2024-12-31"},
    "TR1": {"start_year": 2023, "end_year": 2024},
    "TM1": {"region": "South", "start_date": "2023-01-01", "end_date": "2024-12-31"},
    "QC1": {"start_date": "2023-01-01", "end_date": "2024-12-31"},
    "QC2": {"start_year": 2023, "end_year": 2024},
}


@dataclass
class CoffeeShopParameters:
    query_id: str
    params: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:

        return self.params.get(key, default)


def get_parameters(query_id: str) -> CoffeeShopParameters:

    params = COFFEESHOP_DEFAULT_PARAMS.get(query_id, {}).copy()
    return CoffeeShopParameters(query_id=query_id, params=params)
