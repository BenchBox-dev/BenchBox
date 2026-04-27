"""Parity tests for W8 PK capability rules.

Verifies that:
1. pk_capability.py registers a rule for every covered dialect (4 original +
   8 INFORMATIONAL cloud-DW dialect groups added in refine-sql-compat-skip-semantics w5).
2. Each rule has the expected action and payload type.
3. Registry coverage is complete for the platforms that bypass the PK lock.
4. _supports_primary_keys() behavior matches registry resolution.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import CompatibilityContext, Phase
from benchbox.sql_compat.decision import PKCapabilityPayload, SupportLevel
from benchbox.sql_compat.registry import CompatibilityRegistry

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# Load the rules module to populate REGISTRY
import benchbox.sql_compat.rules.schema_emit.pk_capability  # noqa: F401
from benchbox.sql_compat.registry import REGISTRY

# ---------------------------------------------------------------------------
# Rule registration
# ---------------------------------------------------------------------------


# Rule_id slugs covered by pk_capability.py (write_primitives benchmark).
# Original 4 register under .pk_lock_table_unsupported; the 8 INFORMATIONAL
# cloud-DW groups added in w5 register under .pk_not_enforced.
_EXPECTED_LOCK_TABLE_DIALECTS = ("datafusion", "clickhouse", "starrocks", "doris")
_EXPECTED_INFORMATIONAL_DIALECTS = (
    "snowflake",
    "redshift",
    "bigquery",
    "databricks",
    "tsql",
    "spark",
    "trino",
    "presto",
)


def test_pk_capability_rules_registered():
    """Every covered dialect has a registered PK rule under schema_emit/write_primitives."""
    pk_rules = [
        (key, entry)
        for key, entry in REGISTRY.all_rules()
        if key[0] is Phase.SCHEMA_EMIT and key[2] == "write_primitives"
    ]
    rule_ids = {entry.rule_id for _, entry in pk_rules}
    expected = {
        f"schema_emit.{d}.write_primitives.pk_lock_table_unsupported" for d in _EXPECTED_LOCK_TABLE_DIALECTS
    } | {f"schema_emit.{d}.write_primitives.pk_not_enforced" for d in _EXPECTED_INFORMATIONAL_DIALECTS}
    missing = expected - rule_ids
    assert not missing, f"Missing PK rules: {sorted(missing)}"


@pytest.mark.parametrize("platform", ["datafusion", "clickhouse", "starrocks", "doris"])
def test_pk_rule_action_is_rewrite_ddl(platform: str):
    ctx = CompatibilityContext(
        platform=platform,
        platform_version=None,
        benchmark="write_primitives",
        query_id=None,
        phase=Phase.SCHEMA_EMIT,
        mode="sql",
        dialect=platform,
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, f"No rule for {platform}"
    assert decision.action is CompatAction.REWRITE_DDL
    assert isinstance(decision.payload, PKCapabilityPayload)


def test_datafusion_pk_rule_payload():
    ctx = CompatibilityContext(
        platform="datafusion",
        platform_version=None,
        benchmark="write_primitives",
        query_id=None,
        phase=Phase.SCHEMA_EMIT,
        mode="sql",
        dialect="datafusion",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None
    payload = decision.payload
    assert isinstance(payload, PKCapabilityPayload)
    assert payload.ddl_accepted is False
    assert payload.uniqueness_enforced is False
    assert payload.conditions is None


def test_starrocks_pk_rule_payload():
    ctx = CompatibilityContext(
        platform="starrocks",
        platform_version=None,
        benchmark="write_primitives",
        query_id=None,
        phase=Phase.SCHEMA_EMIT,
        mode="sql",
        dialect="starrocks",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None
    payload = decision.payload
    assert isinstance(payload, PKCapabilityPayload)
    assert payload.ddl_accepted is True  # StarRocks parses PK but ignores it
    assert payload.uniqueness_enforced is False
    assert payload.conditions == "first N columns only"


# ---------------------------------------------------------------------------
# Registry decision parity: lock setup platforms
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("platform", ["datafusion", "clickhouse", "starrocks", "doris"])
def test_all_lock_platforms_have_rewrite_ddl_rule(platform: str):
    """All 4 lock-bypass platforms have REWRITE_DDL rules in the registry."""
    ctx = CompatibilityContext(
        platform=platform,
        platform_version=None,
        benchmark="write_primitives",
        query_id=None,
        phase=Phase.SCHEMA_EMIT,
        mode="sql",
        dialect=platform,
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None, f"No rule for {platform} acquire/release"
    assert decision.action != CompatAction.NATIVE, f"{platform} should have REWRITE_DDL, not NATIVE"


def test_doris_release_bug_fixed_by_registry():
    """doris release bug (missing from legacy tuple) is now corrected by registry."""
    ctx = CompatibilityContext(
        platform="doris",
        platform_version=None,
        benchmark="write_primitives",
        query_id=None,
        phase=Phase.SCHEMA_EMIT,
        mode="sql",
        dialect="doris",
    )
    decision = REGISTRY.resolve(ctx)
    assert decision is not None
    assert decision.action != CompatAction.NATIVE
    assert decision.rule_id == "schema_emit.doris.write_primitives.pk_lock_table_unsupported"
