# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

AMPLAB_DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "Q1": {"pagerank_threshold": 1000},
    "Q1a": {"pagerank_threshold": 1000},
    "Q2": {"start_date": date(2000, 1, 1), "end_date": date(2000, 1, 3), "limit_rows": 100},
    "Q2a": {"pagerank_threshold": 1000, "start_date": date(2000, 1, 1), "limit_rows": 100},
    "Q3": {
        "start_date": date(2000, 1, 1),
        "end_date": date(2000, 1, 3),
        "search_term": "database",
        "min_visits": 10,
        "limit_rows": 100,
    },
    "Q3a": {"keyword1": "web", "keyword2": "data", "min_content_length": 1000, "limit_rows": 100},
    "Q4": {"start_date": date(2000, 1, 1), "min_revenue": 1.0, "min_visits": 10, "limit_rows": 100},
    "Q5": {"start_date": date(2000, 1, 1), "pagerank_threshold": 1000, "min_visits": 10, "limit_rows": 100},
}


@dataclass
class AMPLabParameters:
    query_id: str
    params: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:

        return self.params.get(key, default)


def get_parameters(query_id: str) -> AMPLabParameters:

    params = AMPLAB_DEFAULT_PARAMS.get(query_id, {}).copy()
    return AMPLabParameters(query_id=query_id, params=params)
