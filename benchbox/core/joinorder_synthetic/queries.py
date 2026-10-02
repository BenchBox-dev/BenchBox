"""Join Order Benchmark query management.

This module provides functionality to load and manage the Join Order Benchmark
queries that test join order optimization capabilities using the IMDB dataset.
All queries are designed to stress-test query optimizers with complex multi-table
joins and varying selectivity patterns.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import os
from pathlib import Path
from typing import Any

from benchbox.utils.printing import emit

try:
    from benchbox.core.joinorder.queries import (
        CANONICAL_JOINORDER_QUERIES,
        JoinOrderQueryManager as _CanonicalQueryManager,
    )
except ImportError:
    CANONICAL_JOINORDER_QUERIES = {}
    _CanonicalQueryManager = None  # type: ignore[assignment]


class JoinOrderQueryManager:
    """Manager for Join Order Benchmark queries."""

    def __init__(self, queries_dir: str | None = None) -> None:
        """Initialize the Join Order query manager.

        The default surface is exactly the canonical 113-query JOB set:
        this manager holds one cached canonical manager and delegates
        every lookup to it, so the synthetic surface can never drift from
        canonical definitions again.

        Args:
            queries_dir: Path to directory containing Join Order Benchmark query files.
                        If None, uses the canonical embedded queries. A supplied directory is the
                        complete replacement query set: only its files are visible,
                        with no canonical fallback.
        """
        self._queries_dir = queries_dir
        self._queries = self._load_queries()
        # One cached canonical manager per instance (F5): never
        # reinstantiate per lookup, and never fall back to raw dicts that
        # skip portable-alias normalization.
        self._canonical: Any = None
        if not self._uses_custom_query_directory() and _CanonicalQueryManager is not None:
            self._canonical = _CanonicalQueryManager()

    def _uses_custom_query_directory(self) -> bool:
        """Whether a caller-supplied query directory replaces the built-in set.

        Returns:
            True when ``queries_dir`` pointed at an existing directory, in which
            case the files on disk are the complete query set.
        """
        return bool(self._queries_dir) and os.path.exists(self._queries_dir)

    def _load_queries(self) -> dict[str, str]:
        """Load all Join Order Benchmark queries.

        Returns:
            Dictionary mapping query IDs to SQL text
        """

        if self._queries_dir and os.path.exists(self._queries_dir):
            return self._load_queries_from_files()
        return {}

    def _load_queries_from_files(self) -> dict[str, str]:
        """Load queries from the Join Order Benchmark query files directory.

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        queries: dict[str, str] = {}
        queries_path = Path(self._queries_dir or "")

        for query_file in sorted(queries_path.glob("*.sql")):
            if query_file.stem.replace(".", "").replace("-", "").isalnum():
                query_id = query_file.stem
                try:
                    if content := query_file.read_text(encoding="utf-8").strip():
                        queries[query_id] = content
                except Exception as e:
                    emit(f"Warning: Could not load query {query_id}: {e}")

        return queries

    def get_query(self, query_id: str) -> str:
        """Get a Join Order Benchmark query by ID.

        Delegates to the cached canonical manager, which applies
        portable-alias normalization (e.g. 15a-d `at` -> `at1`).

        Args:
            query_id: Query identifier (e.g., '1a', '2b', etc.)

        Returns:
            SQL query text

        Raises:
            ValueError: If query_id is invalid
        """
        if query_id in self._queries:
            return self._queries[query_id]
        if self._canonical is not None:
            return self._canonical.get_query(query_id)
        available = ", ".join(sorted(set(self._queries) | set(CANONICAL_JOINORDER_QUERIES)))
        raise ValueError(f"Invalid query ID: {query_id}. Available: {available}")

    def get_all_queries(self) -> dict[str, str]:
        """Get all Join Order Benchmark queries.

        The canonical 113-query set, verbatim. When a custom query
        directory was supplied, the directory remains the complete
        replacement query set and no canonical queries are merged in.

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        if self._uses_custom_query_directory():
            return dict(self._queries)
        if self._canonical is not None:
            return self._canonical.get_all_queries()
        return dict(CANONICAL_JOINORDER_QUERIES)

    def get_query_ids(self) -> list[str]:
        """Get list of all query IDs.

        Returns:
            List of query IDs in sorted order
        """
        return sorted(self.get_all_queries().keys())

    def get_query_count(self) -> int:
        """Get total number of queries.

        Returns:
            Number of queries available
        """
        return len(self.get_all_queries())

    def get_queries_by_complexity(self) -> dict[str, list[str]]:
        """Categorize queries by complexity based on table count.

        Classifies the same merged query set reported by ``get_all_queries``,
        so the distribution accounts for all exposed queries.

        Returns:
            Dictionary mapping complexity levels to query IDs
        """
        complexity_map = {"simple": [], "medium": [], "complex": []}

        for query_id, query_sql in self.get_all_queries().items():
            # Count FROM clauses and JOIN keywords to estimate complexity
            from_count = query_sql.upper().count("FROM")
            join_count = query_sql.upper().count("JOIN")
            table_count = len(
                [
                    line
                    for line in query_sql.split("\n")
                    if "AS " in line and any(keyword in line.upper() for keyword in ["FROM", "JOIN", ","])
                ]
            )

            # Rough complexity classification
            total_complexity = from_count + join_count + (table_count // 2)

            if total_complexity <= 3:
                complexity_map["simple"].append(query_id)
            elif total_complexity <= 6:
                complexity_map["medium"].append(query_id)
            else:
                complexity_map["complex"].append(query_id)

        return complexity_map

    def get_queries_by_pattern(self) -> dict[str, list[str]]:
        """Categorize queries by join pattern.

        Classifies the same merged query set reported by ``get_all_queries``,
        so the distribution accounts for all exposed queries.

        Returns:
            Dictionary mapping join patterns to query IDs
        """
        pattern_map = {
            "star_join": [],  # Central table with many relationships
            "chain_join": [],  # Sequential joins
            "complex_join": [],  # Mixed patterns
        }

        for query_id, query_sql in self.get_all_queries().items():
            # Simple heuristic based on table patterns
            if "movie_companies" in query_sql and "movie_info" in query_sql:
                pattern_map["star_join"].append(query_id)
            elif query_sql.count("JOIN") >= 2:
                pattern_map["complex_join"].append(query_id)
            else:
                pattern_map["chain_join"].append(query_id)

        return pattern_map
