"""Parity tests for W14 StarRocks pipeline rules - query adapter and DDL optimize.

Verifies that:
1. query_adapter/starrocks_query_rewrites.py registers exactly 1 platform-wide rule.
2. ddl_optimize/starrocks_ddl_rewrites.py registers exactly 1 platform-wide rule.
3. REWRITE_QUERY rule fires for any (benchmark, query_id) combination on starrocks.
4. REWRITE_DDL rule fires for any (benchmark, query_id) combination on starrocks.
5. Shadow-mode: no divergence for either rule.
6. Registry is silent for EXECUTION_FILTER / DATAFRAME_FILTER phases (no rules yet).
7. Registry is silent for non-starrocks platforms on QUERY_ADAPTER / DDL_OPTIMIZE.
"""

from __future__ import annotations

import pytest

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import CompatibilityContext, Phase
from benchbox.sql_compat.decision import RewriteDDLPayload, RewriteQueryPayload

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# Load rule modules to populate REGISTRY
import benchbox.sql_compat.rules.ddl_optimize.starrocks_ddl_rewrites  # noqa: F401
import benchbox.sql_compat.rules.query_adapter.starrocks_query_rewrites  # noqa: F401
from benchbox.sql_compat.registry import REGISTRY

# ---------------------------------------------------------------------------
# Registration: StarRocks QUERY_ADAPTER rule
# ---------------------------------------------------------------------------


def test_starrocks_query_adapter_rule_registered():
    """Exactly 1 platform-wide query_adapter rule for starrocks."""
    rules = [
        (key, entry) for key, entry in REGISTRY.all_rules() if key[0] is Phase.QUERY_ADAPTER and key[1] == "starrocks"
    ]
    assert len(rules) == 1, (
        f"Expected 1 starrocks query_adapter rule, got {len(rules)}: {[e.rule_id for _, e in rules]}"
    )
    rule_id = rules[0][1].rule_id
    assert rule_id == "query_adapter.starrocks.all.inject_subquery_aliases"


def test_starrocks_ddl_optimize_rule_registered():
    """Exactly 1 platform-wide ddl_optimize rule for starrocks."""
    rules = [
        (key, entry) for key, entry in REGISTRY.all_rules() if key[0] is Phase.DDL_OPTIMIZE and key[1] == "starrocks"
    ]
    assert len(rules) == 1, f"Expected 1 starrocks ddl_optimize rule, got {len(rules)}: {[e.rule_id for _, e in rules]}"
    rule_id = rules[0][1].rule_id
    assert rule_id == "ddl_optimize.starrocks.all.optimize_table_definition"


# ---------------------------------------------------------------------------
# Action and payload
# ---------------------------------------------------------------------------

# NOTE: Parameters named 'bmark' instead of 'benchmark' to avoid clashing with
# the pytest-benchmark plugin's 'benchmark' fixture, which causes INTERNALERROR.


@pytest.mark.parametrize(
    "bmark,query_id",
    [
        ("tpcds", "1"),
        ("tpcds", "23a"),
        ("tpch", "11"),
        ("h2odb", "Q1"),
    ],
)
def test_starrocks_rewrite_query_action_and_payload(bmark: str, query_id: str):
    """Platform-wide REWRITE_QUERY rule fires for any benchmark/query_id on starrocks."""
    ctx = CompatibilityContext(
        platform="starrocks",
        platform_version=None,
        benchmark=bmark,
        query_id=query_id,
        phase=Phase.QUERY_ADAPTER,
        mode="sql",
        dialect="starrocks",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, f"No rule for starrocks/{bmark}/{query_id}"
    assert decision.action is CompatAction.REWRITE_QUERY
    assert isinstance(decision.payload, RewriteQueryPayload)
    assert decision.payload.transformer_id == "starrocks_subquery_alias_injector"


@pytest.mark.parametrize(
    "bmark,query_id",
    [
        ("tpcds", None),
        ("tpch", None),
        ("h2odb", None),
    ],
)
def test_starrocks_rewrite_ddl_action_and_payload(bmark: str, query_id: str | None):
    """Platform-wide REWRITE_DDL rule fires for any benchmark on starrocks."""
    ctx = CompatibilityContext(
        platform="starrocks",
        platform_version=None,
        benchmark=bmark,
        query_id=query_id,
        phase=Phase.DDL_OPTIMIZE,
        mode="sql",
        dialect="starrocks",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, f"No rule for starrocks DDL_OPTIMIZE/{bmark}"
    assert decision.action is CompatAction.REWRITE_DDL
    assert isinstance(decision.payload, RewriteDDLPayload)
    assert decision.payload.transformer_id == "starrocks_ddl_optimizer"


# ---------------------------------------------------------------------------
# Shadow-mode: no divergence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bmark,query_id",
    [
        ("tpcds", "23a"),
        ("tpch", "11"),
        ("h2odb", "Q1"),
    ],
)
def test_starrocks_rewrite_query_registry_returns_rewrite(bmark: str, query_id: str):
    """StarRocks registry returns REWRITE_QUERY for any benchmark/query combination."""
    ctx = CompatibilityContext(
        platform="starrocks",
        platform_version=None,
        benchmark=bmark,
        query_id=query_id,
        phase=Phase.QUERY_ADAPTER,
        mode="sql",
        dialect="starrocks",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None and decision.action is CompatAction.REWRITE_QUERY


@pytest.mark.parametrize("bmark", ["tpcds", "tpch", "h2odb"])
def test_starrocks_rewrite_ddl_registry_returns_rewrite(bmark: str):
    """StarRocks registry returns REWRITE_DDL for any benchmark."""
    ctx = CompatibilityContext(
        platform="starrocks",
        platform_version=None,
        benchmark=bmark,
        query_id=None,
        phase=Phase.DDL_OPTIMIZE,
        mode="sql",
        dialect="starrocks",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None and decision.action is CompatAction.REWRITE_DDL


# ---------------------------------------------------------------------------
# Non-StarRocks platforms have no QUERY_ADAPTER / DDL_OPTIMIZE rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("platform", ["duckdb", "clickhouse", "datafusion"])
def test_non_starrocks_has_no_query_adapter_rule_from_this_module(platform: str):
    """Other platforms have no QUERY_ADAPTER rules from starrocks_query_rewrites."""
    # ClickHouse and DataFusion may have their own QUERY_ADAPTER rules - filter to starrocks origin only
    rules = [
        (key, entry)
        for key, entry in REGISTRY.all_rules()
        if key[0] is Phase.QUERY_ADAPTER and key[1] == platform and "starrocks" in entry.rule_id
    ]
    assert len(rules) == 0, f"{platform} should have no starrocks-origin QUERY_ADAPTER rules"


@pytest.mark.parametrize("platform", ["duckdb", "datafusion"])
def test_non_starrocks_has_no_ddl_optimize_rule(platform: str):
    """Platforms without their own DDL_OPTIMIZE rules return None (ClickHouse has one, so excluded)."""
    ctx = CompatibilityContext(
        platform=platform,
        platform_version=None,
        benchmark="tpch",
        query_id=None,
        phase=Phase.DDL_OPTIMIZE,
        mode="sql",
        dialect=platform,
    )
    assert REGISTRY.resolve(ctx) is None, f"Unexpected DDL_OPTIMIZE rule for {platform}"


# ---------------------------------------------------------------------------
# EXECUTION_FILTER and DATAFRAME_FILTER: registry is silent (no rules yet)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "platform,bmark,query_id",
    [
        ("starrocks", "tpcds", "1"),
        ("starrocks", "tpch", "11"),
        ("duckdb", "tpch", "1"),
        ("clickhouse", "tpcds", "23a"),
    ],
)
def test_execution_filter_registry_silent(platform: str, bmark: str, query_id: str):
    """No EXECUTION_FILTER rules registered yet - registry returns None for all platforms."""
    ctx = CompatibilityContext(
        platform=platform,
        platform_version=None,
        benchmark=bmark,
        query_id=query_id,
        phase=Phase.EXECUTION_FILTER,
        mode="sql",
        dialect=platform,
    )
    assert REGISTRY.resolve(ctx) is None


@pytest.mark.parametrize(
    "platform,bmark,query_id",
    [
        ("starrocks", "tpch", "Q1"),
        ("duckdb", "tpch", "Q1"),
    ],
)
def test_dataframe_filter_registry_silent(platform: str, bmark: str, query_id: str):
    """No DATAFRAME_FILTER rules registered yet - registry returns None for all platforms."""
    ctx = CompatibilityContext(
        platform=platform,
        platform_version=None,
        benchmark=bmark,
        query_id=query_id,
        phase=Phase.DATAFRAME_FILTER,
        mode="dataframe",
        dialect=platform,
    )
    assert REGISTRY.resolve(ctx) is None
