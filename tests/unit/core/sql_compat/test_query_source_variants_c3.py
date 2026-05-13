"""Parity tests for W12 query_source variant rules - Vector Search.

Verifies that:
1. vector_search_variants.py registers exactly 44 rules:
     36 unversioned SELECT_VARIANT (6 platforms × 6 query IDs)
   +  6 LakeSail SKIP_QUERY rules
   +  2 version-gated StarRocks Q2 rules (SKIP_QUERY <3.2 + SELECT_VARIANT ≥3.2)
2. Each unversioned rule has SELECT_VARIANT action and a SelectVariantPayload.
3. StarRocks Q2 version gating fires correctly:
     platform_version=None  → unversioned SELECT_VARIANT (l2_distance SQL)
     platform_version=3.1   → SKIP_QUERY
     platform_version=3.2   → versioned SELECT_VARIANT
4. Shadow-mode: no divergence (legacy already selects the variant SQL).
5. Registry is silent for platforms with no rule (duckdb).
"""

from __future__ import annotations

import pytest

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import CompatibilityContext, Phase
from benchbox.sql_compat.decision import SelectVariantPayload, SkipQueryPayload

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# Load rule module to populate REGISTRY
import benchbox.sql_compat.rules.query_source.vector_search_variants  # noqa: F401
from benchbox.sql_compat.registry import REGISTRY

# ---------------------------------------------------------------------------
# Registration counts
# ---------------------------------------------------------------------------


def test_vector_search_rule_registration_count():
    """44 query_source rules for vector_search."""
    rules = [
        (key, entry)
        for key, entry in REGISTRY.all_rules()
        if key[0] is Phase.QUERY_SOURCE and key[2] == "vector_search"
    ]
    assert len(rules) == 44, f"Expected 44 vector_search rules, got {len(rules)}: {[e.rule_id for _, e in rules]}"


def test_vector_search_all_platforms_registered():
    """Each supported platform has 6 rules registered."""
    for platform in ("spark", "lakesail", "starrocks", "doris", "postgresql", "clickhouse", "snowflake"):
        rules = [
            (key, entry)
            for key, entry in REGISTRY.all_rules()
            if key[0] is Phase.QUERY_SOURCE and key[2] == "vector_search" and key[1] == platform
        ]
        # starrocks has 6 unversioned + 2 versioned = 8 total
        expected = 8 if platform == "starrocks" else 6
        assert len(rules) == expected, f"{platform}: expected {expected} rules, got {len(rules)}"


# ---------------------------------------------------------------------------
# Action and payload: one representative query per platform
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "platform,query_id,expected_snippet",
    [
        # StarRocks
        ("starrocks", "Q1", "cosine_similarity"),
        ("starrocks", "Q2", "l2_distance"),
        ("starrocks", "Q3", "cosine_similarity"),
        ("starrocks", "Q6", "cosine_similarity"),
        # Doris
        ("doris", "Q1", "cosine_distance"),
        ("doris", "Q2", "l2_distance"),
        ("doris", "Q6", "cosine_distance"),
        # PostgreSQL
        ("postgresql", "Q1", "<=>"),
        ("postgresql", "Q2", "<->"),
        # ClickHouse
        ("clickhouse", "Q1", "cosineDistance"),
        ("clickhouse", "Q2", "L2Distance"),
        # Snowflake
        ("snowflake", "Q1", "VECTOR_COSINE_SIMILARITY"),
        ("snowflake", "Q2", "VECTOR_L2_DISTANCE"),
        # Spark
        ("spark", "Q1", "zip_with"),
        ("spark", "Q2", "aggregate"),
    ],
)
def test_vector_search_rule_action_and_payload(platform: str, query_id: str, expected_snippet: str):
    ctx = CompatibilityContext(
        platform=platform,
        platform_version=None,
        benchmark="vector_search",
        query_id=query_id,
        phase=Phase.QUERY_SOURCE,
        mode="sql",
        dialect=platform,
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, f"No rule for {platform}/vector_search/{query_id}"
    assert decision.action is CompatAction.SELECT_VARIANT
    assert isinstance(decision.payload, SelectVariantPayload)
    assert expected_snippet in decision.payload.variant_sql


def test_vector_search_lakesail_rules_skip_queries():
    ctx = CompatibilityContext(
        platform="lakesail",
        platform_version=None,
        benchmark="vector_search",
        query_id="Q1",
        phase=Phase.QUERY_SOURCE,
        mode="sql",
        dialect="lakesail",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None
    assert decision.action is CompatAction.SKIP_QUERY
    assert isinstance(decision.payload, SkipQueryPayload)
    assert "lambda fallback" in decision.payload.reason


# ---------------------------------------------------------------------------
# Version gating: StarRocks Q2
# ---------------------------------------------------------------------------


def test_starrocks_q2_no_version_returns_select_variant():
    """When platform_version is None, unversioned SELECT_VARIANT fires (current behavior)."""
    ctx = CompatibilityContext(
        platform="starrocks",
        platform_version=None,
        benchmark="vector_search",
        query_id="Q2",
        phase=Phase.QUERY_SOURCE,
        mode="sql",
        dialect="starrocks",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None
    assert decision.action is CompatAction.SELECT_VARIANT
    assert decision.rule_id == "query_source.starrocks.vector_search.q2_variant"


def test_starrocks_q2_version_lt_32_returns_skip():
    """StarRocks <3.2: l2_distance parse error → SKIP_QUERY fires."""
    for version in ("3.0", "3.1"):
        ctx = CompatibilityContext(
            platform="starrocks",
            platform_version=version,
            benchmark="vector_search",
            query_id="Q2",
            phase=Phase.QUERY_SOURCE,
            mode="sql",
            dialect="starrocks",
        )
        decision = REGISTRY.resolve(ctx)
        assert decision is not None, f"No rule for starrocks/{version}/Q2"
        assert decision.action is CompatAction.SKIP_QUERY, f"Expected SKIP_QUERY for version {version}"
        assert isinstance(decision.payload, SkipQueryPayload)
        assert decision.rule_id == "query_source.starrocks.vector_search.q2_lt_32_skip"


def test_starrocks_q2_version_ge_32_returns_versioned_variant():
    """StarRocks ≥3.2: versioned SELECT_VARIANT wins over unversioned fallback."""
    for version in ("3.2", "3.3", "4.0"):
        ctx = CompatibilityContext(
            platform="starrocks",
            platform_version=version,
            benchmark="vector_search",
            query_id="Q2",
            phase=Phase.QUERY_SOURCE,
            mode="sql",
            dialect="starrocks",
        )
        decision = REGISTRY.resolve(ctx)
        assert decision is not None, f"No rule for starrocks/{version}/Q2"
        assert decision.action is CompatAction.SELECT_VARIANT, f"Expected SELECT_VARIANT for version {version}"
        assert decision.rule_id == "query_source.starrocks.vector_search.q2_ge_32_variant"
        assert isinstance(decision.payload, SelectVariantPayload)
        assert "l2_distance" in decision.payload.variant_sql


def test_starrocks_q2_non_pep440_engine_version_uses_versioned_variant():
    """Adapter version strings like 3.3.0-starrocks should still satisfy version gates."""
    ctx = CompatibilityContext(
        platform="starrocks",
        platform_version="3.3.0-starrocks",
        benchmark="vector_search",
        query_id="Q2",
        phase=Phase.QUERY_SOURCE,
        mode="sql",
        dialect="starrocks",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None
    assert decision.action is CompatAction.SELECT_VARIANT
    assert decision.rule_id == "query_source.starrocks.vector_search.q2_ge_32_variant"


def test_starrocks_q2_invalid_engine_version_falls_back_to_unversioned_variant():
    """Unparseable version strings should not crash registry resolution."""
    ctx = CompatibilityContext(
        platform="starrocks",
        platform_version="Athena (version unknown)",
        benchmark="vector_search",
        query_id="Q2",
        phase=Phase.QUERY_SOURCE,
        mode="sql",
        dialect="starrocks",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None
    assert decision.action is CompatAction.SELECT_VARIANT
    assert decision.rule_id == "query_source.starrocks.vector_search.q2_variant"


# ---------------------------------------------------------------------------
# No rule for duckdb
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("query_id", ["Q1", "Q2", "Q3"])
def test_vector_search_duckdb_has_no_rule(query_id: str):
    """duckdb has no vector_search variant rules - registry returns None."""
    ctx = CompatibilityContext(
        platform="duckdb",
        platform_version=None,
        benchmark="vector_search",
        query_id=query_id,
        phase=Phase.QUERY_SOURCE,
        mode="sql",
        dialect="duckdb",
    )
    assert REGISTRY.resolve(ctx) is None, f"Unexpected rule for duckdb/vector_search/{query_id}"


# ---------------------------------------------------------------------------
# Shadow-mode parity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "platform,query_id",
    [
        ("starrocks", "Q1"),
        ("starrocks", "Q2"),
        ("doris", "Q1"),
        ("postgresql", "Q1"),
        ("clickhouse", "Q1"),
        ("snowflake", "Q1"),
        ("snowflake", "Q6"),
    ],
)
def test_vector_search_registry_returns_variant(platform: str, query_id: str):
    """Registry returns SELECT_VARIANT for covered platform/vector_search combos."""
    ctx = CompatibilityContext(
        platform=platform,
        platform_version=None,
        benchmark="vector_search",
        query_id=query_id,
        phase=Phase.QUERY_SOURCE,
        mode="sql",
        dialect=platform,
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, f"No rule for {platform}/vector_search/{query_id}"
    assert decision.action is CompatAction.SELECT_VARIANT
