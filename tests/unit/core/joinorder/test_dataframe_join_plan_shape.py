"""Structural guard: JoinOrder DataFrame mode measures multi-join EXECUTION.

The SQL JoinOrder Benchmark stresses the optimizer's freedom to reorder joins.
The DataFrame translation deliberately fixes the join order from the query's
syntactic topology (see benchbox/core/joinorder/dataframe_queries.py module
docstring) -- it measures multi-join execution with a fixed plan, NOT optimizer
ordering. Row-equality oracle tests cannot detect a drift from "fixed plan" to
"cost-reordered" because both can return identical rows. These tests pin the
plan shape so that semantic cannot silently change.
"""

from __future__ import annotations

import pytest
from sqlglot import parse_one

from benchbox.core.joinorder.dataframe_queries import (
    _QUERY_MANAGER,
    _flatten_and,
    _is_join_equality,
    _plan_join_sequence,
    _sql_tables,
)
from benchbox.core.joinorder.queries import CANONICAL_JOINORDER_QUERIES

QUERY_IDS = list(CANONICAL_JOINORDER_QUERIES)


def _plan_for(query_id: str):
    tree = parse_one(_QUERY_MANAGER.get_query(query_id), read="duckdb")
    tables = _sql_tables(tree)
    predicates = _flatten_and(tree.args["where"].this)
    join_predicates = [predicate for predicate in predicates if _is_join_equality(predicate)]
    return tables, join_predicates, _plan_join_sequence(tables, join_predicates)


@pytest.mark.fast
@pytest.mark.parametrize("query_id", QUERY_IDS)
def test_join_plan_is_left_deep_chain_over_all_tables(query_id: str) -> None:
    tables, _join_predicates, steps = _plan_for(query_id)
    # A left-deep chain joins every non-anchor table exactly once, always
    # extending the single growing result -- never a bushy / reordered plan.
    assert len(steps) == len(tables) - 1
    anchor = tables[0][0]
    assert not steps or steps[0].existing_alias == anchor  # anchored on the first FROM table, not a cost pick
    joined = {anchor}
    for step in steps:
        assert step.existing_alias in joined  # builds on what is already joined
        assert step.new_alias not in joined  # each table joined exactly once
        joined.add(step.new_alias)
    assert joined == {alias for alias, _table in tables}


@pytest.mark.fast
@pytest.mark.parametrize("query_id", QUERY_IDS)
def test_join_plan_is_pure_function_of_sql_not_data(query_id: str) -> None:
    # The plan is computed from SQL topology alone (no data / cardinality input),
    # so recomputation is identical: there is no cost-based reordering.
    _t1, _j1, steps_a = _plan_for(query_id)
    _t2, _j2, steps_b = _plan_for(query_id)
    assert steps_a == steps_b
    # Canonical JOB join graphs are connected: every join is predicate-driven,
    # never a cross-product fallback.
    assert all(step.predicate_index >= 0 for step in steps_a)
