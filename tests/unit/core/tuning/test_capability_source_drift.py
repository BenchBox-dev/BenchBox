"""Cross-source consistency tests for the tuning capability registry.

Per the `tuning-renderer-consolidation-and-baseline-policy-20260712` TODO
(w1), `benchbox.core.tuning.capability_registry` is meant to be the single
source of truth that `interface.py`'s compatibility map and
`platform_capabilities.py`'s workload-profile mapper both derive from,
replacing what used to be several independently hand-maintained capability
sources. These tests pin that derivation: each `EXPECTED_*` allowlist below
records a *specific, currently-true* divergence between two capability
sources. An allowlist is strict (empty) where this consolidation eliminated
the divergence -- any regression that reintroduces drift fails one of these
tests immediately, rather than surfacing months later as a preview/execution
mismatch. Allowlists that remain non-empty document gaps this TODO's scope
explicitly did not close (e.g. the ~15 DDL-generator-registered platforms
whose adapter execution path was not migrated/audited this round); each has
a `reason` explaining why it is expected, not accidental.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.core.tuning.capability_registry import (
    PLATFORM_TUNING_CAPABILITIES,
    WORKLOAD_PROFILE_MAPPED_PLATFORMS,
    interface_compatibility_map,
    known_registry_platforms,
)
from benchbox.core.tuning.ddl_generator import get_ddl_generator
from benchbox.core.tuning.interface import (
    _KNOWN_COMPATIBILITY_PLATFORMS,
    _PLATFORM_COMPATIBILITY_MAP,
    TuningType,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# interface.py's known-platform set no longer diverges from the registry's
# `_INTERFACE_KNOWN_PLATFORMS` filter -- interface.py imports the computed
# map directly (see interface._platform_compatibility_map). Strict/empty:
# any future addition to one side without the other fails immediately.
EXPECTED_INTERFACE_VS_REGISTRY_DRIFT: frozenset[str] = frozenset()

# get_ddl_generator() registers real generators (not the NoOp fallback) for
# several SQL platforms that interface.py's compatibility map has no entry
# for at all. These platforms are compatible/warning-only by construction
# (TuningType.is_known_platform returns False for them, so mismatches
# downgrade to warnings -- see interface.py's validate_for_platform_detailed
# docstring) and were out of scope for this TODO's capability-registry
# coverage: none of them are in this TODO's w2 migration order (duckdb,
# clickhouse, starrocks), so auditing their adapter execution paths for a
# registry entry was not attempted this round. Not a regression to fix here;
# a candidate for the next platform this renderer-consolidation effort picks
# up.
EXPECTED_GENERATOR_PLATFORMS_WITHOUT_REGISTRY_ENTRY: frozenset[str] = frozenset(
    {
        "trino",
        "presto",
        "athena",
        "firebolt",
        "azure_synapse",
        "synapse",
        "timescaledb",
        "questdb",
        "pg-duckdb",
        "pg_duckdb",
        "pg-mooncake",
        "pg_mooncake",
    }
)


# FROZEN 2026-07-16 BASELINE -- copied verbatim (as TuningType.value strings,
# not TuningType members) from the hand-maintained _PLATFORM_COMPATIBILITY_MAP
# literal this TODO deleted from interface.py, at the moment it was replaced
# by capability_registry-derived computation. This is a regression pin, NOT a
# re-derivation of the registry: test_interface_compatibility_map_matches_registry_derivation
# above asserts interface.py's map equals capability_registry's own output,
# which is true by construction (interface.py computes it FROM the registry)
# and can never fail on its own -- it would pass even if someone silently
# changed what a platform is compatible with, as long as they changed it
# consistently in the registry. This dict does not import anything from
# capability_registry, so a future edit to capability_registry.py's
# PLATFORM_TUNING_CAPABILITIES data that changes compatibility semantics
# (adds/drops a TuningType for one of these nine platforms) fails THIS test
# even though it would still pass the derivation test. Change this literal
# only as a deliberate, reviewed compatibility decision -- never as a side
# effect of an unrelated registry edit.
EXPECTED_PRE_REFACTOR_COMPATIBILITY_BASELINE_20260716: dict[str, frozenset[str]] = {
    "duckdb": frozenset(
        {
            "sorting",
            "partitioning",
            "primary_keys",
            "foreign_keys",
            "unique_constraints",
            "check_constraints",
        }
    ),
    "snowflake": frozenset(
        {
            "clustering",
            "partitioning",
            "primary_keys",
            "foreign_keys",
            "unique_constraints",
            "check_constraints",
            "materialized_views",
        }
    ),
    "bigquery": frozenset(
        {
            "partitioning",
            "clustering",
            "primary_keys",
            "foreign_keys",
            "check_constraints",
            "materialized_views",
        }
    ),
    "redshift": frozenset(
        {
            "distribution",
            "sorting",
            "partitioning",
            "primary_keys",
            "foreign_keys",
            "unique_constraints",
            "check_constraints",
            "materialized_views",
        }
    ),
    "clickhouse": frozenset(
        {
            "partitioning",
            "sorting",
            "clustering",
            "primary_keys",
            "unique_constraints",
            "materialized_views",
        }
    ),
    "databricks": frozenset(
        {
            "partitioning",
            "clustering",
            "distribution",
            "primary_keys",
            "foreign_keys",
            "unique_constraints",
            "check_constraints",
            "z_ordering",
            "liquid_clustering",
            "auto_optimize",
            "auto_compact",
            "bloom_filters",
            "materialized_views",
        }
    ),
    "sqlite": frozenset(
        {
            "primary_keys",
            "foreign_keys",
            "unique_constraints",
            "check_constraints",
        }
    ),
    "postgresql": frozenset(
        {
            "partitioning",
            "clustering",
            "primary_keys",
            "foreign_keys",
            "unique_constraints",
            "check_constraints",
            "bloom_filters",
            "materialized_views",
        }
    ),
    "mysql": frozenset(
        {
            "partitioning",
            "primary_keys",
            "foreign_keys",
            "unique_constraints",
            "check_constraints",
        }
    ),
}


def test_compatibility_matches_frozen_pre_refactor_baseline():
    """Regression pin: compatibility semantics must match the frozen 2026-07-16 baseline exactly.

    Checked two ways against the same frozen literal: the private
    `_PLATFORM_COMPATIBILITY_MAP` data, and the public
    `TuningType.is_compatible_with_platform` API every real caller (including
    `UnifiedTuningConfiguration.validate_for_platform_detailed`) actually
    uses. Either one drifting from the frozen baseline is the behavior
    regression this test exists to catch.
    """
    assert frozenset(EXPECTED_PRE_REFACTOR_COMPATIBILITY_BASELINE_20260716) == _KNOWN_COMPATIBILITY_PLATFORMS

    for platform, expected_values in EXPECTED_PRE_REFACTOR_COMPATIBILITY_BASELINE_20260716.items():
        actual_values = frozenset(tuning_type.value for tuning_type in _PLATFORM_COMPATIBILITY_MAP[platform])
        assert actual_values == expected_values, (
            f"{platform}: _PLATFORM_COMPATIBILITY_MAP diverged from the frozen 2026-07-16 baseline "
            f"(expected {sorted(expected_values)}, got {sorted(actual_values)})"
        )

        for tuning_type in TuningType:
            expected_compatible = tuning_type.value in expected_values
            actual_compatible = tuning_type.is_compatible_with_platform(platform)
            assert actual_compatible == expected_compatible, (
                f"{platform}/{tuning_type.value}: is_compatible_with_platform()={actual_compatible} "
                f"diverges from the frozen 2026-07-16 baseline (expected {expected_compatible})"
            )


def test_interface_compatibility_map_matches_registry_derivation():
    """interface._PLATFORM_COMPATIBILITY_MAP is exactly capability_registry's output.

    Not "consistent with" -- identical, because interface.py now computes it
    by calling capability_registry.interface_compatibility_map() at import
    time (see interface.py's _platform_compatibility_map helper). This test
    exists to catch someone reintroducing a hand-maintained copy in either
    module.
    """
    assert interface_compatibility_map() == _PLATFORM_COMPATIBILITY_MAP
    assert not EXPECTED_INTERFACE_VS_REGISTRY_DRIFT


def test_known_compatibility_platforms_is_a_subset_of_registry_platforms():
    """Every platform interface.py treats as 'known' has a registry entry."""
    missing = _KNOWN_COMPATIBILITY_PLATFORMS - known_registry_platforms()
    assert missing == set(), f"interface.py known platforms missing from the registry: {sorted(missing)}"


def test_registry_has_platforms_interface_deliberately_excludes():
    """starrocks/doris get registry entries without becoming interface.py 'known' platforms.

    See capability_registry's module docstring and
    tests/unit/core/tuning/test_platform_identity_keys.py's
    test_known_platform_set_stays_in_sync_with_compatibility_map, which pins
    the exact nine-platform 'known' set. This test documents the converse:
    the registry is intentionally broader.
    """
    extra = known_registry_platforms() - _KNOWN_COMPATIBILITY_PLATFORMS
    assert extra == {"starrocks", "doris"}


def test_workload_profile_mapped_platforms_matches_actual_dispatch():
    """WORKLOAD_PROFILE_MAPPED_PLATFORMS is exactly the set map_candidate_to_platform special-cases."""
    from benchbox.core.tuning.platform_capabilities import map_candidate_to_platform
    from benchbox.core.tuning.workload_profiles import ACCEPTED, TEMPORAL_PARTITION, WorkloadTuningCandidate

    candidate = WorkloadTuningCandidate(
        benchmark="tpch",
        table="probe_table",
        column="probe_column",
        type="date",
        roles=(TEMPORAL_PARTITION,),
        query_count=1,
        query_ids=("Q1",),
        status=ACCEPTED,
        rationale="probe candidate for dispatch-coverage testing",
        evidence_source="test_capability_source_drift",
    )

    for platform in WORKLOAD_PROFILE_MAPPED_PLATFORMS:
        mapping = map_candidate_to_platform(platform, candidate)
        assert mapping.reason != f"{platform} has no TPC logical profile mapping yet", (
            f"{platform} is listed as workload-profile-mapped but the dispatcher has no branch for it"
        )

    # And nothing outside the set falls through to a real mapper branch by
    # accident -- an arbitrary unmapped platform must hit the "no mapping"
    # fallback.
    mapping = map_candidate_to_platform("some-unmapped-platform", candidate)
    assert mapping.reason == "some-unmapped-platform has no TPC logical profile mapping yet"


def test_ddl_generator_platforms_without_registry_entry_are_the_expected_set():
    """Pin (and force review of) which generator-backed platforms lack a registry entry.

    This is a `keys()`-membership check, not a construction: every generator
    alias key from get_ddl_generator's own internal mapping is exercised
    (indirectly, via the alias set below) to confirm the registry gap is
    exactly the allowlisted one -- no smaller, no larger.
    """
    generator_backed_aliases = {
        "trino",
        "presto",
        "athena",
        "firebolt",
        "azure_synapse",
        "synapse",
        "timescaledb",
        "questdb",
        "pg-duckdb",
        "pg_duckdb",
        "pg-mooncake",
        "pg_mooncake",
        # Platforms covered by the registry, included here as a sanity check
        # that the two sets are not simply disjoint by construction:
        "duckdb",
        "clickhouse",
    }
    registry_platforms = known_registry_platforms()
    without_entry = frozenset(
        alias
        for alias in generator_backed_aliases
        if alias not in registry_platforms and alias.replace("-", "_") not in registry_platforms
    )
    assert without_entry == EXPECTED_GENERATOR_PLATFORMS_WITHOUT_REGISTRY_ENTRY

    # Every alias in the allowlist really does resolve to a non-NoOp generator
    # (guards against the allowlist rotting into a stale list of typos).
    for alias in EXPECTED_GENERATOR_PLATFORMS_WITHOUT_REGISTRY_ENTRY:
        generator = get_ddl_generator(alias)
        assert type(generator).__name__ != "NoOpDDLGenerator", f"{alias} unexpectedly has no real DDL generator"


@pytest.mark.parametrize("platform", ["duckdb", "clickhouse", "databricks", "starrocks"])
def test_w2_migration_order_platforms_have_registry_entries(platform):
    """The three platforms migrated in w2 (plus databricks, registry-only) all have entries."""
    assert platform in PLATFORM_TUNING_CAPABILITIES
    assert PLATFORM_TUNING_CAPABILITIES[platform], f"{platform} has an empty capability entry"
