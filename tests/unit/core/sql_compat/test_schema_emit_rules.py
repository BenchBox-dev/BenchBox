"""Parity tests for W15 schema_emit rules - TSBS DevOps and NYC Taxi DDL.

Verifies that:
1. tsbs_devops_ddl.py registers exactly 3 rules (clickhouse+all, timescale+all, timescale+tags).
2. nyctaxi_ddl.py registers exactly 4 rules (clickhouse, postgres, postgresql, timescale).
3. REWRITE_DDL fires for clickhouse + tsbs_devops (any table).
4. REWRITE_DDL fires for timescale + tsbs_devops for non-"tags" tables.
5. NATIVE override fires for timescale + tsbs_devops + "tags" table (tier-1 wins over tier-2).
6. REWRITE_DDL fires for clickhouse + nyctaxi (any table).
7. REWRITE_DDL fires for postgres/postgresql/timescale + nyctaxi.
8. Other platforms (duckdb, starrocks) have no SCHEMA_EMIT rules from these modules.
9. compat_lint exits 0 in error mode (0 unregistered dialect branches, W16).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import CompatibilityContext, Phase
from benchbox.sql_compat.decision import RewriteDDLPayload

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# Load rule modules to populate REGISTRY
import benchbox.sql_compat.rules.schema_emit.nyctaxi_ddl  # noqa: F401
import benchbox.sql_compat.rules.schema_emit.tsbs_devops_ddl  # noqa: F401
from benchbox.sql_compat.registry import REGISTRY

# ---------------------------------------------------------------------------
# Registration counts
# ---------------------------------------------------------------------------


def test_tsbs_devops_schema_emit_rules_registered():
    """Exactly 3 schema_emit rules for tsbs_devops across all platforms."""
    rules = [
        (key, entry) for key, entry in REGISTRY.all_rules() if key[0] is Phase.SCHEMA_EMIT and key[2] == "tsbs_devops"
    ]
    rule_ids = [entry.rule_id for _, entry in rules]
    assert len(rules) == 3, f"Expected 3 tsbs_devops SCHEMA_EMIT rules, got {len(rules)}: {rule_ids}"
    expected = {
        "schema_emit.clickhouse.tsbs_devops.all.mergetree_ddl",
        "schema_emit.timescale.tsbs_devops.all.hypertable_ddl",
        "schema_emit.timescale.tsbs_devops.tags.native_ddl",
    }
    assert set(rule_ids) == expected, f"Unexpected rule IDs: {rule_ids}"


def test_nyctaxi_schema_emit_rules_registered():
    """Exactly 4 schema_emit rules for nyctaxi across all platforms."""
    rules = [(key, entry) for key, entry in REGISTRY.all_rules() if key[0] is Phase.SCHEMA_EMIT and key[2] == "nyctaxi"]
    rule_ids = [entry.rule_id for _, entry in rules]
    assert len(rules) == 4, f"Expected 4 nyctaxi SCHEMA_EMIT rules, got {len(rules)}: {rule_ids}"
    expected = {
        "schema_emit.clickhouse.nyctaxi.all.mergetree_ddl",
        "schema_emit.postgres.nyctaxi.all.range_partition_ddl",
        "schema_emit.postgresql.nyctaxi.all.range_partition_ddl",
        "schema_emit.timescale.nyctaxi.all.range_partition_ddl",
    }
    assert set(rule_ids) == expected, f"Unexpected rule IDs: {rule_ids}"


# ---------------------------------------------------------------------------
# TSBS DevOps: ClickHouse REWRITE_DDL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table_name", ["cpu", "mem", "disk", "net", "tags"])
def test_tsbs_devops_clickhouse_rewrite_ddl(table_name: str):
    """ClickHouse fires REWRITE_DDL for every tsbs_devops table."""
    ctx = CompatibilityContext(
        platform="clickhouse",
        platform_version=None,
        benchmark="tsbs_devops",
        query_id=table_name,
        phase=Phase.SCHEMA_EMIT,
        mode="sql",
        dialect="clickhouse",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, f"No SCHEMA_EMIT rule for clickhouse/tsbs_devops/{table_name}"
    assert decision.action is CompatAction.REWRITE_DDL
    assert isinstance(decision.payload, RewriteDDLPayload)
    assert decision.payload.transformer_id == "tsbs_devops_clickhouse_ddl"


# ---------------------------------------------------------------------------
# TSBS DevOps: TimescaleDB - REWRITE_DDL for non-tags, NATIVE for tags
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table_name", ["cpu", "mem", "disk", "net"])
def test_tsbs_devops_timescale_non_tags_rewrite_ddl(table_name: str):
    """TimescaleDB fires REWRITE_DDL for all non-tags tsbs_devops tables (tier-2)."""
    ctx = CompatibilityContext(
        platform="timescale",
        platform_version=None,
        benchmark="tsbs_devops",
        query_id=table_name,
        phase=Phase.SCHEMA_EMIT,
        mode="sql",
        dialect="timescale",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, f"No SCHEMA_EMIT rule for timescale/tsbs_devops/{table_name}"
    assert decision.action is CompatAction.REWRITE_DDL
    assert isinstance(decision.payload, RewriteDDLPayload)
    assert decision.payload.transformer_id == "tsbs_devops_timescale_hypertable"


def test_tsbs_devops_timescale_tags_native_override():
    """TimescaleDB + tags fires NATIVE (tier-1 overrides tier-2 hypertable rule)."""
    ctx = CompatibilityContext(
        platform="timescale",
        platform_version=None,
        benchmark="tsbs_devops",
        query_id="tags",
        phase=Phase.SCHEMA_EMIT,
        mode="sql",
        dialect="timescale",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, "No SCHEMA_EMIT rule for timescale/tsbs_devops/tags"
    assert decision.action is CompatAction.NATIVE, (
        f"Expected NATIVE for timescale/tags, got {decision.action}. "
        "Tier-1 tags override must win over tier-2 hypertable rule."
    )
    assert decision.rule_id == "schema_emit.timescale.tsbs_devops.tags.native_ddl"


# ---------------------------------------------------------------------------
# NYC Taxi: ClickHouse REWRITE_DDL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table_name", ["trips", "green_trips", "hvfhv_trips", "taxi_zones"])
def test_nyctaxi_clickhouse_rewrite_ddl(table_name: str):
    """ClickHouse fires REWRITE_DDL for every nyctaxi table."""
    ctx = CompatibilityContext(
        platform="clickhouse",
        platform_version=None,
        benchmark="nyctaxi",
        query_id=table_name,
        phase=Phase.SCHEMA_EMIT,
        mode="sql",
        dialect="clickhouse",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, f"No SCHEMA_EMIT rule for clickhouse/nyctaxi/{table_name}"
    assert decision.action is CompatAction.REWRITE_DDL
    assert isinstance(decision.payload, RewriteDDLPayload)
    assert decision.payload.transformer_id == "nyctaxi_clickhouse_ddl"


# ---------------------------------------------------------------------------
# NYC Taxi: postgres / postgresql / timescale REWRITE_DDL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "platform,table_name",
    [
        ("postgres", "trips"),
        ("postgres", "taxi_zones"),
        ("postgresql", "trips"),
        ("postgresql", "green_trips"),
        ("timescale", "trips"),
        ("timescale", "hvfhv_trips"),
    ],
)
def test_nyctaxi_postgres_family_rewrite_ddl(platform: str, table_name: str):
    """postgres/postgresql/timescale fire REWRITE_DDL for nyctaxi tables."""
    ctx = CompatibilityContext(
        platform=platform,
        platform_version=None,
        benchmark="nyctaxi",
        query_id=table_name,
        phase=Phase.SCHEMA_EMIT,
        mode="sql",
        dialect=platform,
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, f"No SCHEMA_EMIT rule for {platform}/nyctaxi/{table_name}"
    assert decision.action is CompatAction.REWRITE_DDL
    assert isinstance(decision.payload, RewriteDDLPayload)
    assert decision.payload.transformer_id == "nyctaxi_postgres_partition_ddl"


# ---------------------------------------------------------------------------
# Other platforms: no SCHEMA_EMIT rules from these modules
# ---------------------------------------------------------------------------


# NOTE: Parameters named 'bmark' instead of 'benchmark' to avoid clashing with
# the pytest-benchmark plugin's 'benchmark' fixture, which causes INTERNALERROR.


@pytest.mark.parametrize(
    "platform,bmark",
    [
        ("duckdb", "tsbs_devops"),
        ("duckdb", "nyctaxi"),
        ("starrocks", "tsbs_devops"),
        ("starrocks", "nyctaxi"),
        ("datafusion", "nyctaxi"),
    ],
)
def test_other_platforms_no_schema_emit_rule(platform: str, bmark: str):
    """DuckDB, StarRocks, etc. have no SCHEMA_EMIT rules for these benchmarks."""
    ctx = CompatibilityContext(
        platform=platform,
        platform_version=None,
        benchmark=bmark,
        query_id=None,
        phase=Phase.SCHEMA_EMIT,
        mode="sql",
        dialect=platform,
    )
    assert REGISTRY.resolve(ctx) is None, f"Unexpected SCHEMA_EMIT rule for {platform}/{bmark}"


# ---------------------------------------------------------------------------
# compat_lint passes in permanent error mode (0 unregistered dialect branches)
# ---------------------------------------------------------------------------


def test_compat_lint_passes():
    """uv run scripts/compat_lint.py exits 0 (error mode as of W16 - 0 unregistered branches)."""
    result = subprocess.run(
        [sys.executable, "scripts/compat_lint.py"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"compat_lint exited {result.returncode}.\nstderr: {result.stderr}\nstdout: {result.stdout}"
    )
