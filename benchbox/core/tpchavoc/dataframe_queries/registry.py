"""TPC-Havoc DataFrame query registry."""

from __future__ import annotations

from importlib import import_module

from benchbox.core.dataframe.query import DataFrameQuery, QueryRegistry


def _build_registry() -> QueryRegistry:
    registry = QueryRegistry("TPC-Havoc DataFrame")
    for query_number in range(1, 23):
        module = import_module(f"benchbox.core.tpchavoc.dataframe_queries.q{query_number:02d}")
        variants = getattr(module, f"Q{query_number}_VARIANTS")
        registry.register_many(variants)
    return registry


TPCHAVOC_DATAFRAME_QUERIES = _build_registry()


def get_dataframe_queries() -> QueryRegistry:
    """Get the TPC-Havoc DataFrame query registry."""
    return TPCHAVOC_DATAFRAME_QUERIES


def get_query(query_id: str) -> DataFrameQuery:
    """Get a TPC-Havoc DataFrame variant by ID."""
    return TPCHAVOC_DATAFRAME_QUERIES.get_or_raise(query_id)


def list_query_ids() -> list[str]:
    """List all TPC-Havoc DataFrame variant IDs."""
    return TPCHAVOC_DATAFRAME_QUERIES.get_query_ids()
