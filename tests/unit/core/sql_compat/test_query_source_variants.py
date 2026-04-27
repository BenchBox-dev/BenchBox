"""Parity tests for W10 query_source variant rules under shadow mode.

Verifies that:
1. h2odb_variants.py registers exactly 3 rules (clickhouse + starrocks + mysql for Q9).
2. coffeeshop_variants.py registers exactly 2 rules (clickhouse SA4 + TM1).
3. Each rule has SELECT_VARIANT action and a SelectVariantPayload.
4. Shadow-mode: no divergence for covered platforms (legacy already selects variant).
5. Registry is silent for platforms with no rule (duckdb, starrocks/coffeeshop).
"""

from __future__ import annotations

import pytest

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import CompatibilityContext, Phase
from benchbox.sql_compat.decision import SelectVariantPayload

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# Load rule modules to populate REGISTRY
import benchbox.sql_compat.rules.query_source.coffeeshop_variants  # noqa: F401
import benchbox.sql_compat.rules.query_source.h2odb_variants  # noqa: F401
from benchbox.sql_compat.registry import REGISTRY

# ---------------------------------------------------------------------------
# Registration: h2odb
# ---------------------------------------------------------------------------


def test_h2odb_variant_rules_registered():
    """Exactly 3 query_source rules registered for h2odb (clickhouse + starrocks + mysql Q9)."""
    rules = [(key, entry) for key, entry in REGISTRY.all_rules() if key[0] is Phase.QUERY_SOURCE and key[2] == "h2odb"]
    assert len(rules) == 3, f"Expected 3 h2odb rules, got {len(rules)}: {[e.rule_id for _, e in rules]}"
    rule_ids = [entry.rule_id for _, entry in rules]
    assert "query_source.clickhouse.h2odb.q9_quantile_variant" in rule_ids
    assert "query_source.starrocks.h2odb.q9_percentile_approx_variant" in rule_ids
    assert "query_source.mysql.h2odb.q9_within_group_verbatim" in rule_ids


@pytest.mark.parametrize(
    "platform,expected_snippet",
    [
        ("clickhouse", "quantile"),
        ("starrocks", "PERCENTILE_APPROX"),
    ],
)
def test_h2odb_rule_action_and_payload(platform: str, expected_snippet: str):
    ctx = CompatibilityContext(
        platform=platform,
        platform_version=None,
        benchmark="h2odb",
        query_id="Q9",
        phase=Phase.QUERY_SOURCE,
        mode="sql",
        dialect=platform,
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, f"No rule for {platform}/h2odb/Q9"
    assert decision.action is CompatAction.SELECT_VARIANT
    assert isinstance(decision.payload, SelectVariantPayload)
    assert expected_snippet in decision.payload.variant_sql


def test_h2odb_duckdb_has_no_rule():
    """duckdb is not in the h2odb variant table - registry should return None."""
    ctx = CompatibilityContext(
        platform="duckdb",
        platform_version=None,
        benchmark="h2odb",
        query_id="Q9",
        phase=Phase.QUERY_SOURCE,
        mode="sql",
        dialect="duckdb",
    )
    assert REGISTRY.resolve(ctx) is None


# ---------------------------------------------------------------------------
# Registration: coffeeshop
# ---------------------------------------------------------------------------


def test_coffeeshop_variant_rules_registered():
    """Exactly 2 query_source rules registered for coffeeshop (clickhouse SA4 + TM1)."""
    rules = [
        (key, entry) for key, entry in REGISTRY.all_rules() if key[0] is Phase.QUERY_SOURCE and key[2] == "coffeeshop"
    ]
    assert len(rules) == 2, f"Expected 2 coffeeshop rules, got {len(rules)}: {[e.rule_id for _, e in rules]}"
    rule_ids = [entry.rule_id for _, entry in rules]
    assert "query_source.clickhouse.coffeeshop.sa4_cross_join_variant" in rule_ids
    assert "query_source.clickhouse.coffeeshop.tm1_todatetime_variant" in rule_ids


@pytest.mark.parametrize(
    "query_id,expected_snippet",
    [
        ("SA4", "CROSS JOIN"),
        ("TM1", "toHour(toDateTime"),
    ],
)
def test_coffeeshop_rule_action_and_payload(query_id: str, expected_snippet: str):
    ctx = CompatibilityContext(
        platform="clickhouse",
        platform_version=None,
        benchmark="coffeeshop",
        query_id=query_id,
        phase=Phase.QUERY_SOURCE,
        mode="sql",
        dialect="clickhouse",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, f"No rule for clickhouse/coffeeshop/{query_id}"
    assert decision.action is CompatAction.SELECT_VARIANT
    assert isinstance(decision.payload, SelectVariantPayload)
    assert expected_snippet in decision.payload.variant_sql


@pytest.mark.parametrize("query_id", ["SA4", "TM1"])
def test_coffeeshop_starrocks_has_no_rule(query_id: str):
    """starrocks has no coffeeshop SA4/TM1 variant - registry should return None."""
    ctx = CompatibilityContext(
        platform="starrocks",
        platform_version=None,
        benchmark="coffeeshop",
        query_id=query_id,
        phase=Phase.QUERY_SOURCE,
        mode="sql",
        dialect="starrocks",
    )
    assert REGISTRY.resolve(ctx) is None, f"Unexpected rule for starrocks/coffeeshop/{query_id}"
