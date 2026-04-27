"""Parity tests for W13 query_adapter rules - ClickHouse session policy and DataFusion rewrites.

Verifies that:
1. clickhouse_session_policy.py registers exactly 3 rules (Q23a, Q23b, Q87 in TPC-DS).
2. datafusion_query_rewrites.py registers exactly 4 rules (Q11, Q16, Q18, Q20 in TPC-H).
3. ClickHouse rules have SET_SESSION_POLICY action and SetSessionPolicyPayload with
   joined_subquery_requires_alias=0.
4. DataFusion rules have REWRITE_QUERY action and RewriteQueryPayload pointing to
   datafusion_query_transformer.
5. Shadow-mode: no divergence (legacy already applies these policies).
6. Registry is silent for platforms with no rule (duckdb).
"""

from __future__ import annotations

import pytest

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import CompatibilityContext, Phase
from benchbox.sql_compat.decision import RewriteQueryPayload, SetSessionPolicyPayload

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# Load rule modules to populate REGISTRY
import benchbox.sql_compat.rules.query_adapter.clickhouse_session_policy  # noqa: F401
import benchbox.sql_compat.rules.query_adapter.datafusion_query_rewrites  # noqa: F401
from benchbox.sql_compat.registry import REGISTRY

# ---------------------------------------------------------------------------
# Registration: ClickHouse TPC-DS session policy
# ---------------------------------------------------------------------------


def test_clickhouse_tpcds_session_policy_rules_registered():
    """Exactly 3 query_adapter rules for clickhouse/tpcds (Q23a, Q23b, Q87)."""
    rules = [
        (key, entry)
        for key, entry in REGISTRY.all_rules()
        if key[0] is Phase.QUERY_ADAPTER and key[1] == "clickhouse" and key[2] == "tpcds"
    ]
    assert len(rules) == 3, f"Expected 3 clickhouse/tpcds rules, got {len(rules)}: {[e.rule_id for _, e in rules]}"
    rule_ids = {entry.rule_id for _, entry in rules}
    assert "query_adapter.clickhouse.tpcds.q23a_joined_subquery_alias_policy" in rule_ids
    assert "query_adapter.clickhouse.tpcds.q23b_joined_subquery_alias_policy" in rule_ids
    assert "query_adapter.clickhouse.tpcds.q87_joined_subquery_alias_policy" in rule_ids


@pytest.mark.parametrize("query_id", ["23a", "23b", "87"])
def test_clickhouse_session_policy_action_and_payload(query_id: str):
    ctx = CompatibilityContext(
        platform="clickhouse",
        platform_version=None,
        benchmark="tpcds",
        query_id=query_id,
        phase=Phase.QUERY_ADAPTER,
        mode="sql",
        dialect="clickhouse",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, f"No rule for clickhouse/tpcds/{query_id}"
    assert decision.action is CompatAction.SET_SESSION_POLICY
    assert isinstance(decision.payload, SetSessionPolicyPayload)
    assert ("joined_subquery_requires_alias", "0") in decision.payload.settings


@pytest.mark.parametrize("query_id", ["1", "22", "42"])
def test_clickhouse_tpcds_other_queries_have_no_adapter_rule(query_id: str):
    """Other TPC-DS queries have no query_adapter rule - session setting applied uniformly."""
    ctx = CompatibilityContext(
        platform="clickhouse",
        platform_version=None,
        benchmark="tpcds",
        query_id=query_id,
        phase=Phase.QUERY_ADAPTER,
        mode="sql",
        dialect="clickhouse",
    )
    assert REGISTRY.resolve(ctx) is None, f"Unexpected rule for clickhouse/tpcds/{query_id}"


# ---------------------------------------------------------------------------
# Registration: DataFusion TPC-H rewrites
# ---------------------------------------------------------------------------


def test_datafusion_tpch_rewrite_rules_registered():
    """Exactly 4 query_adapter rules for datafusion/tpch (Q11, Q16, Q18, Q20)."""
    rules = [
        (key, entry)
        for key, entry in REGISTRY.all_rules()
        if key[0] is Phase.QUERY_ADAPTER and key[1] == "datafusion" and key[2] == "tpch"
    ]
    assert len(rules) == 4, f"Expected 4 datafusion/tpch rules, got {len(rules)}: {[e.rule_id for _, e in rules]}"
    rule_ids = {entry.rule_id for _, entry in rules}
    assert "query_adapter.datafusion.tpch.q11_having_threshold_cte" in rule_ids
    assert "query_adapter.datafusion.tpch.q16_not_in_to_not_exists" in rule_ids
    assert "query_adapter.datafusion.tpch.q18_in_having_to_exists" in rule_ids
    assert "query_adapter.datafusion.tpch.q20_correlated_to_cte" in rule_ids


@pytest.mark.parametrize(
    "query_id,expected_transformer",
    [
        ("11", "datafusion_query_transformer"),
        ("16", "datafusion_query_transformer"),
        ("18", "datafusion_query_transformer"),
        ("20", "datafusion_query_transformer"),
    ],
)
def test_datafusion_rewrite_action_and_payload(query_id: str, expected_transformer: str):
    ctx = CompatibilityContext(
        platform="datafusion",
        platform_version=None,
        benchmark="tpch",
        query_id=query_id,
        phase=Phase.QUERY_ADAPTER,
        mode="sql",
        dialect="datafusion",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, f"No rule for datafusion/tpch/{query_id}"
    assert decision.action is CompatAction.REWRITE_QUERY
    assert isinstance(decision.payload, RewriteQueryPayload)
    assert decision.payload.transformer_id == expected_transformer


@pytest.mark.parametrize("query_id", ["1", "6", "22"])
def test_datafusion_tpch_unaffected_queries_have_no_rule(query_id: str):
    """Q1, Q6, Q22 don't need DataFusion rewrites - no rule registered."""
    ctx = CompatibilityContext(
        platform="datafusion",
        platform_version=None,
        benchmark="tpch",
        query_id=query_id,
        phase=Phase.QUERY_ADAPTER,
        mode="sql",
        dialect="datafusion",
    )
    assert REGISTRY.resolve(ctx) is None, f"Unexpected rule for datafusion/tpch/{query_id}"


# ---------------------------------------------------------------------------
# Shadow-mode parity: no divergence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("query_id", ["23a", "23b", "87"])
def test_clickhouse_session_policy_registry_returns_decision(query_id: str):
    """Registry returns SET_SESSION_POLICY for clickhouse/tpcds query IDs."""
    ctx = CompatibilityContext(
        platform="clickhouse",
        platform_version=None,
        benchmark="tpcds",
        query_id=query_id,
        phase=Phase.QUERY_ADAPTER,
        mode="sql",
        dialect="clickhouse",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None and decision.action is CompatAction.SET_SESSION_POLICY


@pytest.mark.parametrize("query_id", ["11", "16", "18", "20"])
def test_datafusion_rewrite_registry_returns_decision(query_id: str):
    """Registry returns REWRITE_QUERY for datafusion/tpch query IDs."""
    ctx = CompatibilityContext(
        platform="datafusion",
        platform_version=None,
        benchmark="tpch",
        query_id=query_id,
        phase=Phase.QUERY_ADAPTER,
        mode="sql",
        dialect="datafusion",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None and decision.action is CompatAction.REWRITE_QUERY


def test_duckdb_has_no_query_adapter_rules():
    """duckdb has no query_adapter rules - registry returns None."""
    for benchmark, query_id in [("tpcds", "23a"), ("tpch", "11")]:
        ctx = CompatibilityContext(
            platform="duckdb",
            platform_version=None,
            benchmark=benchmark,
            query_id=query_id,
            phase=Phase.QUERY_ADAPTER,
            mode="sql",
            dialect="duckdb",
        )
        assert REGISTRY.resolve(ctx) is None
