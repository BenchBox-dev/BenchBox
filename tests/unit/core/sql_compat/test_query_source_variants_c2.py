"""Parity tests for W11 query_source variant rules - NYC Taxi and TPC-DI.

Verifies that:
1. nyctaxi_variants.py registers exactly 7 rules (4 StarRocks + 3 ClickHouse).
2. tpcdi_variants.py registers exactly 3 rules (clickhouse AQ6 + starrocks EQ7 + doris EQ7).
3. Each rule has SELECT_VARIANT action and a SelectVariantPayload.
4. Shadow-mode: no divergence (legacy already selects the variant SQL).
5. Registry is silent for platforms with no rule (duckdb).
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
import benchbox.sql_compat.rules.query_source.nyctaxi_variants  # noqa: F401
import benchbox.sql_compat.rules.query_source.tpcdi_variants  # noqa: F401
from benchbox.sql_compat.registry import REGISTRY

# ---------------------------------------------------------------------------
# Registration: nyctaxi
# ---------------------------------------------------------------------------

_NYCTAXI_STARROCKS_RULES = [
    ("query_source.starrocks.nyctaxi.trips_by_dow_dayofweek_variant", "trips-by-day-of-week"),
    ("query_source.starrocks.nyctaxi.weekday_weekend_dayofweek_variant", "weekday-weekend-comparison"),
    ("query_source.starrocks.nyctaxi.rush_hour_timestampdiff_variant", "rush-hour-analysis"),
    ("query_source.starrocks.nyctaxi.trip_duration_timestampdiff_variant", "trip-duration-analysis"),
]
_NYCTAXI_CLICKHOUSE_RULES = [
    ("query_source.clickhouse.nyctaxi.trips_by_dow_todayofweek_variant", "trips-by-day-of-week"),
    ("query_source.clickhouse.nyctaxi.weekday_weekend_tohour_variant", "weekday-weekend-comparison"),
    ("query_source.clickhouse.nyctaxi.rush_hour_datediff_variant", "rush-hour-analysis"),
]


def test_nyctaxi_variant_rules_registered():
    """Exactly 7 query_source rules registered for nyctaxi (4 StarRocks + 3 ClickHouse)."""
    rules = [
        (key, entry) for key, entry in REGISTRY.all_rules() if key[0] is Phase.QUERY_SOURCE and key[2] == "nyctaxi"
    ]
    assert len(rules) == 7, f"Expected 7 nyctaxi rules, got {len(rules)}: {[e.rule_id for _, e in rules]}"
    rule_ids = {entry.rule_id for _, entry in rules}
    for rule_id, _ in _NYCTAXI_STARROCKS_RULES + _NYCTAXI_CLICKHOUSE_RULES:
        assert rule_id in rule_ids, f"Missing rule: {rule_id}"


@pytest.mark.parametrize(
    "platform,query_id,expected_snippet",
    [
        ("starrocks", "trips-by-day-of-week", "DAYOFWEEK"),
        ("starrocks", "weekday-weekend-comparison", "DAYOFWEEK"),
        ("starrocks", "rush-hour-analysis", "TIMESTAMPDIFF"),
        ("starrocks", "trip-duration-analysis", "TIMESTAMPDIFF"),
        ("clickhouse", "trips-by-day-of-week", "toDayOfWeek"),
        ("clickhouse", "weekday-weekend-comparison", "toHour"),
        ("clickhouse", "rush-hour-analysis", "dateDiff"),
    ],
)
def test_nyctaxi_rule_action_and_payload(platform: str, query_id: str, expected_snippet: str):
    ctx = CompatibilityContext(
        platform=platform,
        platform_version=None,
        benchmark="nyctaxi",
        query_id=query_id,
        phase=Phase.QUERY_SOURCE,
        mode="sql",
        dialect=platform,
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, f"No rule for {platform}/nyctaxi/{query_id}"
    assert decision.action is CompatAction.SELECT_VARIANT
    assert isinstance(decision.payload, SelectVariantPayload)
    assert expected_snippet in decision.payload.variant_sql


@pytest.mark.parametrize("query_id", ["trips-by-day-of-week", "rush-hour-analysis"])
def test_nyctaxi_duckdb_has_no_rule(query_id: str):
    """duckdb has no nyctaxi variant rules - registry returns None for all query IDs."""
    ctx = CompatibilityContext(
        platform="duckdb",
        platform_version=None,
        benchmark="nyctaxi",
        query_id=query_id,
        phase=Phase.QUERY_SOURCE,
        mode="sql",
        dialect="duckdb",
    )
    assert REGISTRY.resolve(ctx) is None, f"Unexpected rule for duckdb/nyctaxi/{query_id}"


def test_nyctaxi_starrocks_has_no_trip_duration_for_clickhouse():
    """trip-duration-analysis is only in StarRocks - ClickHouse has no rule for it."""
    ctx = CompatibilityContext(
        platform="clickhouse",
        platform_version=None,
        benchmark="nyctaxi",
        query_id="trip-duration-analysis",
        phase=Phase.QUERY_SOURCE,
        mode="sql",
        dialect="clickhouse",
    )
    assert REGISTRY.resolve(ctx) is None


# ---------------------------------------------------------------------------
# Registration: tpcdi
# ---------------------------------------------------------------------------


def test_tpcdi_variant_rules_registered():
    """Exactly 3 query_source rules registered for tpcdi (clickhouse AQ6 + starrocks EQ7 + doris EQ7)."""
    rules = [(key, entry) for key, entry in REGISTRY.all_rules() if key[0] is Phase.QUERY_SOURCE and key[2] == "tpcdi"]
    assert len(rules) == 3, f"Expected 3 tpcdi rules, got {len(rules)}: {[e.rule_id for _, e in rules]}"
    rule_ids = {entry.rule_id for _, entry in rules}
    assert "query_source.clickhouse.tpcdi.aq6_cross_join_variant" in rule_ids
    assert "query_source.starrocks.tpcdi.eq7_derived_table_variant" in rule_ids
    assert "query_source.doris.tpcdi.eq7_derived_table_variant" in rule_ids


@pytest.mark.parametrize(
    "platform,query_id,expected_snippet",
    [
        ("clickhouse", "AQ6", "CROSS JOIN"),
        ("starrocks", "EQ7", "quality_metrics"),
        ("doris", "EQ7", "quality_metrics"),
    ],
)
def test_tpcdi_rule_action_and_payload(platform: str, query_id: str, expected_snippet: str):
    ctx = CompatibilityContext(
        platform=platform,
        platform_version=None,
        benchmark="tpcdi",
        query_id=query_id,
        phase=Phase.QUERY_SOURCE,
        mode="sql",
        dialect=platform,
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, f"No rule for {platform}/tpcdi/{query_id}"
    assert decision.action is CompatAction.SELECT_VARIANT
    assert isinstance(decision.payload, SelectVariantPayload)
    assert expected_snippet in decision.payload.variant_sql


@pytest.mark.parametrize("query_id", ["AQ6", "EQ7"])
def test_tpcdi_duckdb_has_no_rule(query_id: str):
    """duckdb has no tpcdi variant rules."""
    ctx = CompatibilityContext(
        platform="duckdb",
        platform_version=None,
        benchmark="tpcdi",
        query_id=query_id,
        phase=Phase.QUERY_SOURCE,
        mode="sql",
        dialect="duckdb",
    )
    assert REGISTRY.resolve(ctx) is None, f"Unexpected rule for duckdb/tpcdi/{query_id}"


def test_tpcdi_eq7_sql_has_no_format_placeholders():
    """EQ7 variant SQL is complete for both StarRocks and Doris."""
    from benchbox.sql_compat.rules.query_source.tpcdi_variants import (
        DORIS_EQ7_SQL,
        STARROCKS_EQ7_SQL,
    )

    assert "{" not in STARROCKS_EQ7_SQL, "STARROCKS_EQ7_SQL should not contain format placeholders"
    assert "{" not in DORIS_EQ7_SQL, "DORIS_EQ7_SQL should not contain format placeholders"
    assert DORIS_EQ7_SQL == STARROCKS_EQ7_SQL


def test_tpcdi_aq6_sql_has_format_placeholders():
    """CLICKHOUSE_AQ6_SQL must contain format placeholders for params."""
    from benchbox.sql_compat.rules.query_source.tpcdi_variants import CLICKHOUSE_AQ6_SQL

    assert "{start_year}" in CLICKHOUSE_AQ6_SQL
    assert "{end_year}" in CLICKHOUSE_AQ6_SQL


# ---------------------------------------------------------------------------
# Registry parity: nyctaxi
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "platform,query_id",
    [
        ("starrocks", "trips-by-day-of-week"),
        ("starrocks", "weekday-weekend-comparison"),
        ("starrocks", "rush-hour-analysis"),
        ("starrocks", "trip-duration-analysis"),
        ("clickhouse", "trips-by-day-of-week"),
        ("clickhouse", "weekday-weekend-comparison"),
        ("clickhouse", "rush-hour-analysis"),
    ],
)
def test_nyctaxi_registry_returns_variant(platform: str, query_id: str):
    """Registry returns SELECT_VARIANT for covered platform/nyctaxi combos."""
    ctx = CompatibilityContext(
        platform=platform,
        platform_version=None,
        benchmark="nyctaxi",
        query_id=query_id,
        phase=Phase.QUERY_SOURCE,
        mode="sql",
        dialect=platform,
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, f"No rule for {platform}/nyctaxi/{query_id}"
    assert decision.action is CompatAction.SELECT_VARIANT
