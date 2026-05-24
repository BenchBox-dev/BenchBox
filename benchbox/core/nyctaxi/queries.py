"""NYC Taxi OLAP benchmark queries.

Implements representative OLAP analytics queries:
- Temporal aggregations (hourly, daily, monthly)
- Geographic patterns (zone-level analytics)
- Financial analytics (revenue, tips, fares)
- Multi-dimensional analysis

Query sources:
- Todd Schneider's nyc-taxi-data repository
- ClickHouse official documentation
- DuckDB taxi dataset benchmarks
- Mark Litwintschik's database performance analyses

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np

from benchbox.core.static_query_catalog import load_static_query_catalog

_CATALOG = load_static_query_catalog(__package__)
QUERIES: dict[str, dict[str, Any]] = _CATALOG["QUERIES"]
GREEN_QUERIES: dict[str, dict[str, Any]] = _CATALOG["GREEN_QUERIES"]
HVFHV_QUERIES: dict[str, dict[str, Any]] = _CATALOG["HVFHV_QUERIES"]
CROSS_TYPE_QUERIES: dict[str, dict[str, Any]] = _CATALOG["CROSS_TYPE_QUERIES"]


class NYCTaxiQueryManager:
    """Manages NYC Taxi benchmark queries.

    By default only exposes the 25 Yellow Taxi queries (QUERIES) for backwards
    compatibility. Pass taxi_type_queries=True to also include Green, HVFHV, and
    cross-type queries.
    """

    def __init__(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        seed: Optional[int] = None,
        include_green_queries: bool = False,
        include_hvfhv_queries: bool = False,
        include_cross_type_queries: bool = False,
    ) -> None:
        """Initialize query manager.

        Args:
            start_date: Start date for the dataset
            end_date: End date for the dataset
            seed: Random seed for parameter generation
            include_green_queries: Include Green Taxi-specific queries
            include_hvfhv_queries: Include HVFHV-specific queries
            include_cross_type_queries: Include cross-type comparison queries
        """
        self.start_date = start_date or datetime(2019, 1, 1)
        self.end_date = end_date or datetime(2019, 12, 31)
        self.rng = np.random.default_rng(seed)

        # Popular zone IDs for point queries
        self.popular_zones = [132, 138, 161, 162, 163, 164, 186, 230, 234, 236, 237, 239, 261, 262, 263]

        # Build active query registry
        self._active_queries: dict[str, Any] = dict(QUERIES)
        if include_green_queries:
            self._active_queries.update(GREEN_QUERIES)
        if include_hvfhv_queries:
            self._active_queries.update(HVFHV_QUERIES)
        if include_cross_type_queries:
            self._active_queries.update(CROSS_TYPE_QUERIES)

    def get_query(
        self,
        query_id: str,
        params: Optional[dict[str, Any]] = None,
    ) -> str:
        """Get a query with parameters filled in.

        Args:
            query_id: Query identifier
            params: Optional parameter overrides

        Returns:
            Parameterized query string

        Raises:
            ValueError: If query_id is unknown
        """
        if query_id not in self._active_queries:
            raise ValueError(f"Unknown query: {query_id}. Available: {list(self._active_queries.keys())}")

        query_def = self._active_queries[query_id]
        sql = query_def["sql"].strip()

        # Build parameters
        query_params = self._generate_params(query_def, params)

        # Format the query
        return sql.format(**query_params)

    def _generate_params(
        self,
        query_def: dict[str, Any],
        overrides: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Generate query parameters.

        Args:
            query_def: Query definition
            overrides: Parameter overrides

        Returns:
            Dictionary of parameters
        """
        params = {}
        query_params = query_def.get("params", {})
        overrides = overrides or {}

        # Calculate date range
        duration_days = query_params.get("duration_days", 30)

        # Pick a random start point within the dataset
        dataset_days = (self.end_date - self.start_date).days
        max_offset = max(1, dataset_days - duration_days)
        offset_days = int(self.rng.integers(0, max_offset))

        start = self.start_date + timedelta(days=offset_days)
        end = start + timedelta(days=duration_days)

        params["start_date"] = start.strftime("%Y-%m-%d")
        params["end_date"] = end.strftime("%Y-%m-%d")

        # Random zone for point queries
        params["zone_id"] = overrides.get(
            "zone_id",
            self.popular_zones[int(self.rng.integers(0, len(self.popular_zones)))],
        )

        # Apply overrides
        params.update(overrides)

        return params

    def get_queries(self) -> dict[str, str]:
        """Get all active queries with generated parameters.

        Returns:
            Dictionary mapping query IDs to query strings
        """
        return {qid: self.get_query(qid) for qid in self._active_queries}

    def get_query_info(self, query_id: str) -> dict[str, Any]:
        """Get query metadata.

        Args:
            query_id: Query identifier

        Returns:
            Query metadata dictionary
        """
        if query_id not in self._active_queries:
            raise ValueError(f"Unknown query: {query_id}")
        return self._active_queries[query_id]

    def get_queries_by_category(self, category: str) -> list[str]:
        """Get query IDs for a specific category.

        Args:
            category: Query category

        Returns:
            List of query IDs
        """
        return [qid for qid, qdef in self._active_queries.items() if qdef.get("category") == category]

    def get_categories(self) -> list[str]:
        """Get all active query categories.

        Returns:
            List of unique categories
        """
        return list({str(qdef["category"]) for qdef in self._active_queries.values()})

    def get_query_count(self) -> int:
        """Get total number of active queries.

        Returns:
            Number of queries
        """
        return len(self._active_queries)
