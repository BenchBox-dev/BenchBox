"""Canonical JoinOrder DataFrame capability tests."""

from __future__ import annotations

import pytest

from benchbox.core.joinorder.benchmark import JoinOrderBenchmark
from benchbox.core.joinorder.dataframe_queries import (
    get_dataframe_queries,
    get_implemented_dataframe_query_ids,
    get_untranslated_dataframe_query_ids,
    q13a_expression_impl,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_registry_contains_all_canonical_query_ids() -> None:
    registry = get_dataframe_queries()

    assert len(registry) == 113
    assert set(get_implemented_dataframe_query_ids()).isdisjoint(get_untranslated_dataframe_query_ids())
    assert len(get_implemented_dataframe_query_ids()) == 13
    assert len(get_untranslated_dataframe_query_ids()) == 100


def test_default_dataframe_selection_exposes_only_implemented_queries() -> None:
    benchmark = JoinOrderBenchmark()
    registry = benchmark.get_dataframe_queries()
    skip_ids = set(benchmark.get_dataframe_skip_queries())
    selected_ids = [query.query_id for query in registry.get_all_queries() if query.query_id not in skip_ids]

    assert selected_ids == sorted(get_implemented_dataframe_query_ids())


def test_untranslated_query_stub_points_to_track2_todo() -> None:
    with pytest.raises(NotImplementedError, match="track2-joinorder-dataframe-coverage.yaml"):
        q13a_expression_impl(None)
