"""TSBS DevOps benchmark queries.

Implements typical DevOps monitoring queries:
- Single host metrics over time
- Multi-host aggregations
- High/low cardinality lookups
- Time-windowed analytics
- Grouped aggregations by tags

Based on TSBS query patterns:
https://github.com/timescale/tsbs/tree/master/cmd/tsbs_generate_queries

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np

from benchbox.core.static_query_catalog import load_static_query_catalog

QUERIES: dict[str, dict[str, Any]] = load_static_query_catalog(__package__)["QUERIES"]


class TSBSDevOpsQueryManager:
    """Manages TSBS DevOps benchmark queries."""

    def __init__(
        self,
        num_hosts: int = 100,
        start_time: Optional[datetime] = None,
        duration_days: int = 1,
        seed: Optional[int] = None,
    ) -> None:
        """Initialize query manager.

        Args:
            num_hosts: Number of hosts in the dataset
            start_time: Start time for the dataset
            duration_days: Duration of the dataset in days
            seed: Random seed for parameter generation
        """
        self.num_hosts = num_hosts
        self.start_time = start_time or datetime(2024, 1, 1)
        self.duration_days = duration_days
        self.rng = np.random.default_rng(seed)

        # Generate host list for parameter selection
        self.hostnames = [f"host_{i}" for i in range(num_hosts)]
        self.regions = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]

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
        if query_id not in QUERIES:
            raise ValueError(f"Unknown query: {query_id}. Available: {list(QUERIES.keys())}")

        query_def = QUERIES[query_id]
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

        # Calculate time range
        duration_hours = query_params.get("duration_hours", 1)
        duration_minutes = query_params.get("duration_minutes", duration_hours * 60)

        # Pick a random point in time within the dataset
        # Use actual dataset duration instead of hardcoded 24 hours
        total_dataset_hours = self.duration_days * 24
        max_offset_hours = max(1, total_dataset_hours - duration_hours)
        offset_hours = int(self.rng.integers(0, max_offset_hours))

        start = self.start_time + timedelta(hours=offset_hours)
        end = start + timedelta(minutes=duration_minutes)

        params["start_time"] = start.strftime("%Y-%m-%d %H:%M:%S")
        params["end_time"] = end.strftime("%Y-%m-%d %H:%M:%S")

        # Random hostname
        params["hostname"] = overrides.get(
            "hostname",
            self.hostnames[int(self.rng.integers(0, len(self.hostnames)))],
        )

        # Random region
        params["region"] = overrides.get(
            "region",
            self.regions[int(self.rng.integers(0, len(self.regions)))],
        )

        # Apply overrides
        params.update(overrides)

        return params

    def get_queries(self) -> dict[str, str]:
        """Get all queries with generated parameters.

        Returns:
            Dictionary mapping query IDs to query strings
        """
        return {qid: self.get_query(qid) for qid in QUERIES}

    def get_query_info(self, query_id: str) -> dict[str, Any]:
        """Get query metadata.

        Args:
            query_id: Query identifier

        Returns:
            Query metadata dictionary
        """
        if query_id not in QUERIES:
            raise ValueError(f"Unknown query: {query_id}")
        return QUERIES[query_id]

    def get_queries_by_category(self, category: str) -> list[str]:
        """Get query IDs for a specific category.

        Args:
            category: Query category

        Returns:
            List of query IDs
        """
        return [qid for qid, qdef in QUERIES.items() if qdef.get("category") == category]

    @staticmethod
    def get_categories() -> list[str]:
        """Get all query categories.

        Returns:
            List of unique categories
        """
        return list({str(qdef["category"]) for qdef in QUERIES.values()})

    @staticmethod
    def get_query_count() -> int:
        """Get total number of queries.

        Returns:
            Number of queries
        """
        return len(QUERIES)
