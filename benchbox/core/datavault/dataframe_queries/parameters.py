# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

DATAVAULT_DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "Q1": {"delta": 90},
    "Q2": {"size": 15, "type_suffix": "BRASS", "region": "EUROPE"},
    "Q3": {"segment": "BUILDING", "order_date": date(1995, 3, 15)},
    "Q4": {"start_date": date(1993, 7, 1), "end_date": date(1993, 10, 1)},
    "Q5": {"region": "ASIA", "start_date": date(1994, 1, 1), "end_date": date(1995, 1, 1)},
    "Q6": {
        "start_date": date(1994, 1, 1),
        "end_date": date(1995, 1, 1),
        "discount_low": 0.05,
        "discount_high": 0.07,
        "quantity": 24,
    },
    "Q7": {"nation1": "FRANCE", "nation2": "GERMANY"},
    "Q8": {"nation": "BRAZIL", "region": "AMERICA", "part_type": "ECONOMY ANODIZED STEEL"},
    "Q9": {"color": "green"},
    "Q10": {"start_date": date(1993, 10, 1), "end_date": date(1994, 1, 1)},
    "Q11": {"nation": "GERMANY", "fraction": 0.0001},
    "Q12": {"shipmode1": "MAIL", "shipmode2": "SHIP", "start_date": date(1994, 1, 1), "end_date": date(1995, 1, 1)},
    "Q13": {"word1": "special", "word2": "requests"},
    "Q14": {"start_date": date(1995, 9, 1), "end_date": date(1995, 10, 1)},
    "Q15": {"start_date": date(1996, 1, 1), "end_date": date(1996, 4, 1)},
    "Q16": {"brand": "Brand#45", "type_prefix": "MEDIUM POLISHED", "sizes": [49, 14, 23, 45, 19, 3, 36, 9]},
    "Q17": {"brand": "Brand#23", "container": "MED BOX"},
    "Q18": {"quantity": 300},
    "Q19": {
        "brand1": "Brand#12",
        "brand2": "Brand#23",
        "brand3": "Brand#34",
        "quantity1": 1,
        "quantity2": 10,
        "quantity3": 20,
    },
    "Q20": {"color": "forest", "start_date": date(1994, 1, 1), "end_date": date(1995, 1, 1), "nation": "CANADA"},
    "Q21": {"nation": "SAUDI ARABIA"},
    "Q22": {"country_codes": ["13", "31", "23", "29", "30", "18", "17"]},
}


@dataclass
class DataVaultParameters:
    query_id: str
    params: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)


def get_parameters(query_id: str) -> DataVaultParameters:
    params = DATAVAULT_DEFAULT_PARAMS.get(query_id, {}).copy()
    return DataVaultParameters(query_id=query_id, params=params)
