"""AMPLab DataFrame query parameters.

Default parameter values for AMPLab queries.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

# Date parameters are typed ``datetime.date`` objects (not ISO strings) so they
# compare correctly against the production loader's date32-typed ``visitDate``
# column - mirroring the TPC-H DataFrame queries, whose date params are also
# ``date`` objects. Comparing a date column to a string literal raises under both
# the Polars expression backend and the Pandas (pyarrow date32) backend.
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
    """Parameter container for an AMPLab query."""

    query_id: str
    params: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        """Get a parameter value with optional default."""
        return self.params.get(key, default)


def get_parameters(query_id: str) -> AMPLabParameters:
    """Get parameters for an AMPLab query."""
    params = AMPLAB_DEFAULT_PARAMS.get(query_id, {}).copy()
    return AMPLabParameters(query_id=query_id, params=params)
