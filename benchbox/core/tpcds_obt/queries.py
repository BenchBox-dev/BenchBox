"""Query manager for the TPC-DS One Big Table benchmark."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from benchbox.core.tpcds_obt.manual_queries import MANUAL_QUERY_IDS, get_manual_query, render_manual_query
from benchbox.core.tpcds_obt.query_conversion import QueryConverter


def _load_query_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("query_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


# Queries that successfully convert to OBT schema
# Total: 89 out of 99 convertible (90% coverage)
# Blocked queries (10 total):
#   - Inventory fact table: Q21, Q22, Q37, Q39, Q72, Q82 (separate fact domain, not in OBT)
#   - Require external dimension tables for customer's CURRENT address/demographics:
#       Q46, Q64, Q68, Q84 (need customer, customer_address, household_demographics, etc.)
# Manually crafted queries: 14, 49 (complex semantics requiring manual rewrite)
# Note: Q64 uses cross-channel self-join pattern which defeats OBT's single-scan design
CONVERTIBLE_QUERY_IDS = tuple(_load_query_specs()["convertible_query_ids"])


class TPCDSOBTQueryManager:
    """Generates and manages OBT-adapted TPC-DS queries."""

    def __init__(self, converter: QueryConverter | None = None) -> None:
        self.converter = converter or QueryConverter()
        self._converted = self._load_queries()
        self._manual_queries = self._load_manual_queries()

    def _load_queries(self) -> dict[int, Any]:
        queries: dict[int, Any] = {}
        for qid in CONVERTIBLE_QUERY_IDS:
            if qid in MANUAL_QUERY_IDS:
                continue  # Skip manual queries, handled separately
            queries[qid] = self.converter.convert(qid)
        return queries

    def _load_manual_queries(self) -> dict[int, Any]:
        """Load manually crafted queries for complex cases."""
        manual: dict[int, Any] = {}
        for qid in CONVERTIBLE_QUERY_IDS:
            if qid in MANUAL_QUERY_IDS:
                manual[qid] = get_manual_query(qid)
        return manual

    def get_query(self, query_id: int | str, parameters: dict[str, Any] | None = None) -> str:
        """Return rendered SQL for a specific query id."""
        qid_int = self._normalize_id(query_id)
        if qid_int in self._manual_queries:
            return render_manual_query(qid_int, parameters)
        converted = self._get_converted(query_id)
        return self._render_query(converted, parameters or {})

    def get_template(self, query_id: int | str) -> str:
        """Return the template SQL with parameter placeholders intact."""
        qid_int = self._normalize_id(query_id)
        if qid_int in self._manual_queries:
            return self._manual_queries[qid_int].template_sql
        return self._get_converted(query_id).template_sql

    def get_queries(self, parameters: dict[str, Any] | None = None) -> dict[int, str]:
        """Return all rendered SQL queries keyed by numeric id."""
        return {qid: self.get_query(qid, parameters) for qid in self.list_query_ids()}

    def list_query_ids(self) -> list[int]:
        """Return available query identifiers."""
        all_ids = set(self._converted.keys()) | set(self._manual_queries.keys())
        return sorted(all_ids)

    def _render_query(self, converted: Any, parameters: dict[str, Any]) -> str:
        if not parameters:
            return converted.default_sql
        sql = converted.template_sql
        for name, param in converted.parameters.items():
            value = parameters.get(name, param.default)
            replacement = param.render(value)
            sql = self.converter._param_pattern(name).sub(replacement, sql)  # noqa: SLF001
        return sql

    def _get_converted(self, query_id: int | str) -> Any:
        qid_int = self._normalize_id(query_id)
        if qid_int in self._manual_queries:
            raise ValueError(f"Query {query_id} is a manual query, use get_query() instead")
        if qid_int not in self._converted:
            raise ValueError(f"Unknown query id: {query_id}")
        return self._converted[qid_int]

    def _normalize_id(self, query_id: int | str) -> int:
        if isinstance(query_id, int):
            return query_id
        try:
            return int(query_id)
        except ValueError as exc:
            raise ValueError(f"Unknown query id: {query_id}") from exc


__all__ = ["CONVERTIBLE_QUERY_IDS", "TPCDSOBTQueryManager"]
