# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

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
    def __init__(self, queries_dir: str | None = None) -> None:
        self._queries_dir = queries_dir
        self._queries = self._load_queries()
        self._canonical: Any = None
        if not self._uses_custom_query_directory() and _CanonicalQueryManager is not None:
            self._canonical = _CanonicalQueryManager()

    def _uses_custom_query_directory(self) -> bool:
        return bool(self._queries_dir) and os.path.exists(self._queries_dir)

    def _load_queries(self) -> dict[str, str]:

        if self._queries_dir and os.path.exists(self._queries_dir):
            return self._load_queries_from_files()
        return {}

    def _load_queries_from_files(self) -> dict[str, str]:
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
        if query_id in self._queries:
            return self._queries[query_id]
        if self._canonical is not None:
            return self._canonical.get_query(query_id)
        available = ", ".join(sorted(set(self._queries) | set(CANONICAL_JOINORDER_QUERIES)))
        raise ValueError(f"Invalid query ID: {query_id}. Available: {available}")

    def get_all_queries(self) -> dict[str, str]:
        if self._uses_custom_query_directory():
            return dict(self._queries)
        if self._canonical is not None:
            return self._canonical.get_all_queries()
        return dict(CANONICAL_JOINORDER_QUERIES)

    def get_query_ids(self) -> list[str]:
        return sorted(self.get_all_queries().keys())

    def get_query_count(self) -> int:
        return len(self.get_all_queries())

    def get_queries_by_complexity(self) -> dict[str, list[str]]:
        complexity_map = {"simple": [], "medium": [], "complex": []}

        for query_id, query_sql in self.get_all_queries().items():
            from_count = query_sql.upper().count("FROM")
            join_count = query_sql.upper().count("JOIN")
            table_count = len(
                [
                    line
                    for line in query_sql.split("\n")
                    if "AS " in line and any(keyword in line.upper() for keyword in ["FROM", "JOIN", ","])
                ]
            )

            total_complexity = from_count + join_count + (table_count // 2)

            if total_complexity <= 3:
                complexity_map["simple"].append(query_id)
            elif total_complexity <= 6:
                complexity_map["medium"].append(query_id)
            else:
                complexity_map["complex"].append(query_id)

        return complexity_map

    def get_queries_by_pattern(self) -> dict[str, list[str]]:
        pattern_map = {
            "star_join": [],
            "chain_join": [],
            "complex_join": [],
        }

        for query_id, query_sql in self.get_all_queries().items():
            if "movie_companies" in query_sql and "movie_info" in query_sql:
                pattern_map["star_join"].append(query_id)
            elif query_sql.count("JOIN") >= 2:
                pattern_map["complex_join"].append(query_id)
            else:
                pattern_map["chain_join"].append(query_id)

        return pattern_map
