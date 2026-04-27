"""NYC Taxi DataFrame query parameters.

Default parameter values for NYC Taxi queries. Uses static defaults
for DataFrame execution (date ranges and zone IDs).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Default parameters - representative date range from the NYC Taxi dataset
NYCTAXI_DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "Q1": {"start_date": "2019-01-01", "end_date": "2019-01-31"},
    "Q2": {"start_date": "2019-01-01", "end_date": "2019-12-31"},
    "Q3": {"start_date": "2019-01-01", "end_date": "2019-12-31"},
    "Q4": {"start_date": "2019-01-01", "end_date": "2019-03-31"},
    "Q5": {"start_date": "2019-01-01", "end_date": "2019-01-31"},
    "Q6": {"start_date": "2019-01-01", "end_date": "2019-01-31"},
    "Q7": {"start_date": "2019-01-01", "end_date": "2019-01-31"},
    "Q8": {"start_date": "2019-01-01", "end_date": "2019-03-31"},
    "Q9": {"start_date": "2019-01-01", "end_date": "2019-01-31"},
    "Q10": {"start_date": "2019-01-01", "end_date": "2019-01-31"},
    "Q11": {"start_date": "2019-01-01", "end_date": "2019-01-31"},
    "Q12": {"start_date": "2019-01-01", "end_date": "2019-12-31"},
    "Q13": {"start_date": "2019-01-01", "end_date": "2019-01-31"},
    "Q14": {"start_date": "2019-01-01", "end_date": "2019-01-31"},
    "Q15": {"start_date": "2019-01-01", "end_date": "2019-01-31"},
    "Q16": {"start_date": "2019-01-01", "end_date": "2019-03-31"},
    "Q17": {"start_date": "2019-01-01", "end_date": "2019-03-31"},
    "Q18": {"start_date": "2019-01-01", "end_date": "2019-01-31"},
    "Q19": {"start_date": "2019-01-01", "end_date": "2019-01-07"},
    "Q20": {"start_date": "2019-01-01", "end_date": "2019-01-31"},
    "Q21": {"start_date": "2019-01-01", "end_date": "2019-01-31"},
    "Q22": {"start_date": "2019-01-01", "end_date": "2019-12-31"},
    "Q23": {"start_date": "2019-06-15", "end_date": "2019-06-16"},
    "Q24": {"start_date": "2019-01-01", "end_date": "2019-01-31", "zone_id": 132},
    "Q25": {},
}


@dataclass
class NYCTaxiParameters:
    """Parameter container for a NYC Taxi query."""

    query_id: str
    params: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        """Get a parameter value with optional default."""
        return self.params.get(key, default)


def get_parameters(query_id: str) -> NYCTaxiParameters:
    """Get parameters for a NYC Taxi query.

    Args:
        query_id: Query identifier (e.g., "Q1", "Q25")

    Returns:
        NYCTaxiParameters with default values for the query.
    """
    params = NYCTAXI_DEFAULT_PARAMS.get(query_id, {}).copy()
    return NYCTaxiParameters(query_id=query_id, params=params)
