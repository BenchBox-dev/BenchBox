"""TSBS DevOps DataFrame query parameters.

Default parameter values for TSBS DevOps queries. Uses static defaults
for DataFrame execution (time ranges, hostname, region).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

TSBS_DEVOPS_DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "Q1": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 12:00:00", "hostname": "host_0"},
    "Q2": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 01:00:00", "hostname": "host_0"},
    "Q3": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 01:00:00"},
    "Q4": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 08:00:00"},
    "Q5": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 01:00:00"},
    "Q6": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 00:05:00"},
    "Q7": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 01:00:00"},
    "Q8": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 12:00:00"},
    "Q9": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 01:00:00"},
    "Q10": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 01:00:00"},
    "Q11": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 01:00:00"},
    "Q12": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 01:00:00"},
    "Q13": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 01:00:00"},
    "Q14": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 01:00:00"},
    "Q15": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 01:00:00"},
    "Q16": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-02 00:00:00"},
    "Q17": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 01:00:00", "region": "us-east-1"},
    "Q18": {"start_time": "2024-01-01 00:00:00", "end_time": "2024-01-01 01:00:00"},
}

for _params in TSBS_DEVOPS_DEFAULT_PARAMS.values():
    _params["start_time"] = datetime.fromisoformat(_params["start_time"])
    _params["end_time"] = datetime.fromisoformat(_params["end_time"])


@dataclass
class TSBSDevOpsParameters:
    """Parameter container for a TSBS DevOps query."""

    query_id: str
    params: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        """Get a parameter value with optional default."""
        return self.params.get(key, default)


def get_parameters(query_id: str) -> TSBSDevOpsParameters:
    """Get parameters for a TSBS DevOps query."""
    params = TSBS_DEVOPS_DEFAULT_PARAMS.get(query_id, {}).copy()
    return TSBSDevOpsParameters(query_id=query_id, params=params)
