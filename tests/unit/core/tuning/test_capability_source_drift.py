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

`TestGeneratorRegistryVsCompatibilityMapDrift` and
`TestCapabilityMapperVsCompatibilityMapDrift` below predate the w1
consolidation (originally added by PR #1177, finding R7, before this TODO's
capability_registry existed) and cover a related but distinct question:
drift between the three sources *as they present themselves independently*
today -- `get_ddl_generator()`'s registry, `_PLATFORM_COMPATIBILITY_MAP`, and
`platform_capabilities.map_candidate_to_platform()`'s supported-platform set.
None of those three sources' *observable behavior* changed under this TODO
(only how `_PLATFORM_COMPATIBILITY_MAP` and the workload-profile mapper's
dispatch are *computed*, not what they return), so those tests still hold
and are kept unchanged alongside the registry-consolidation tests below.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from benchbox.core.tuning import ddl_generator as ddl_generator_module
from benchbox.core.tuning.capability_registry import (
    PLATFORM_TUNING_CAPABILITIES,
    WORKLOAD_PROFILE_MAPPED_PLATFORMS,
    get_capability,
    interface_compatibility_map,
    known_registry_platforms,
    resolve_platform_key,
)
from benchbox.core.tuning.ddl_generator import get_ddl_generator
from benchbox.core.tuning.interface import (
    _KNOWN_COMPATIBILITY_PLATFORMS,
    _PLATFORM_COMPATIBILITY_MAP,
    TuningType,
)
from benchbox.core.tuning.platform_capabilities import map_candidate_to_platform
from benchbox.core.tuning.workload_profiles import VALID_ROLES, WorkloadTuningCandidate

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
# docstring). They were out of scope for the original w1 capability-registry
# consolidation (none of them were in that TODO's w2 migration order --
# duckdb, clickhouse, starrocks) but are exactly the worklist the follow-up
# `tuning-capability-registry-coverage-20260716` TODO closed: every alias
# below now resolves (via capability_registry.resolve_platform_key) to a
# real PLATFORM_TUNING_CAPABILITIES entry, so this allowlist is strict/empty.
# Any future generator-backed platform added without a matching registry
# entry fails this test immediately instead of silently rotting into a new
# undocumented gap.
EXPECTED_GENERATOR_PLATFORMS_WITHOUT_REGISTRY_ENTRY: frozenset[str] = frozenset()


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
    """starrocks/doris (+ this TODO's 9) get registry entries without becoming interface.py 'known' platforms.

    See capability_registry's module docstring and
    tests/unit/core/tuning/test_platform_identity_keys.py's
    test_known_platform_set_stays_in_sync_with_compatibility_map, which pins
    the exact nine-platform 'known' set. This test documents the converse:
    the registry is intentionally broader. The
    `tuning-capability-registry-coverage-20260716` TODO added 9 more
    registry-only platforms (trino/presto/athena/firebolt/azure-synapse/
    timescaledb/questdb/pg-duckdb/pg-mooncake -- canonical registry keys, not
    every CLI alias) alongside the original starrocks/doris pair, all under
    the same non-"known" treatment.
    """
    extra = known_registry_platforms() - _KNOWN_COMPATIBILITY_PLATFORMS
    assert extra == {
        "starrocks",
        "doris",
        "trino",
        "presto",
        "athena",
        "firebolt",
        "azure-synapse",
        "timescaledb",
        "questdb",
        "pg-duckdb",
        "pg-mooncake",
    }


def test_workload_profile_mapped_platforms_matches_actual_dispatch():
    """WORKLOAD_PROFILE_MAPPED_PLATFORMS is exactly the set map_candidate_to_platform special-cases."""
    from benchbox.core.tuning.workload_profiles import ACCEPTED, TEMPORAL_PARTITION

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

    This is a membership check, not a construction: EVERY key in
    get_ddl_generator()'s own `generators` dict literal is checked against
    the registry -- via `GENERATOR_REGISTRY_KEYS` (module-level below, an AST
    inspection of that dict's source -- see `_discover_generator_registry_keys`)
    -- to confirm the registry gap is exactly the allowlisted one, no smaller,
    no larger. A prior version of this test checked a hand-maintained literal
    subset instead: a future platform registered in get_ddl_generator without
    a matching registry entry would never have entered that literal, so the
    drift guard would have missed it silently. Deriving the checked set from
    the real registry closes that hole -- get_ddl_generator can't be imported
    directly at module scope here (its `generators` dict is built with lazy,
    function-local imports specifically to dodge a circular import with
    `core.tuning.generators.*`), so AST inspection of its source is the
    lowest-risk way to introspect it without restructuring that function.

    Coverage resolves through `capability_registry.resolve_platform_key`
    (the same alias/normalization logic `get_capability` uses at runtime)
    rather than a hand-rolled hyphen/underscore check: a prior version of
    this check only normalized hyphen-aliases to underscore-keys, which
    cannot detect coverage added under a hyphenated canonical key (e.g.
    "azure-synapse") or resolve a short alias like "synapse" that isn't a
    hyphen/underscore variant of its canonical key at all.
    """
    generator_backed_aliases = GENERATOR_REGISTRY_KEYS
    registry_platforms = known_registry_platforms()
    without_entry = frozenset(
        alias for alias in generator_backed_aliases if resolve_platform_key(alias) not in registry_platforms
    )
    assert without_entry == EXPECTED_GENERATOR_PLATFORMS_WITHOUT_REGISTRY_ENTRY

    # Every alias really does resolve to a non-NoOp generator (guards against
    # the coverage claim above resting on a typo'd or fallback-NoOp platform
    # key). Previously this only checked the (now-empty) allowlist; checking
    # every alias keeps the guard meaningful now that the allowlist is empty.
    for alias in generator_backed_aliases:
        generator = get_ddl_generator(alias)
        assert type(generator).__name__ != "NoOpDDLGenerator", f"{alias} unexpectedly has no real DDL generator"


@pytest.mark.parametrize("platform", ["duckdb", "clickhouse", "databricks", "starrocks"])
def test_w2_migration_order_platforms_have_registry_entries(platform):
    """The three platforms migrated in w2 (plus databricks, registry-only) all have entries."""
    assert platform in PLATFORM_TUNING_CAPABILITIES
    assert PLATFORM_TUNING_CAPABILITIES[platform], f"{platform} has an empty capability entry"


@pytest.mark.parametrize(
    "platform",
    [
        "trino",
        "presto",
        "athena",
        "firebolt",
        "azure-synapse",
        "timescaledb",
        "questdb",
        "pg-duckdb",
        "pg-mooncake",
    ],
)
def test_coverage_20260716_platforms_have_registry_entries(platform):
    """The 9 platforms this TODO covers all have non-empty registry entries.

    Companion to test_w2_migration_order_platforms_have_registry_entries:
    pins presence the same way, for the canonical keys added by
    `tuning-capability-registry-coverage-20260716`.
    """
    assert platform in PLATFORM_TUNING_CAPABILITIES
    assert PLATFORM_TUNING_CAPABILITIES[platform], f"{platform} has an empty capability entry"


@pytest.mark.parametrize(
    "alias,canonical",
    [
        ("azure_synapse", "azure-synapse"),
        ("synapse", "azure-synapse"),
        ("pg_duckdb", "pg-duckdb"),
        ("pg-duckdb", "pg-duckdb"),
        ("pg_mooncake", "pg-mooncake"),
        ("pg-mooncake", "pg-mooncake"),
    ],
)
def test_coverage_20260716_aliases_resolve_to_canonical_registry_key(alias, canonical):
    """Every spelling of the 3 multi-token platforms in this batch resolves identically.

    Guards the specific hyphen/underscore split that made the old ad hoc
    drift-test check miss "synapse" and "azure_synapse" (see
    test_ddl_generator_platforms_without_registry_entry_are_the_expected_set's
    docstring): both must land on the same canonical key real callers
    (get_capability, the CLI table) would resolve to.
    """
    assert resolve_platform_key(alias) == canonical
    assert canonical in PLATFORM_TUNING_CAPABILITIES


def test_pg_duckdb_sorting_has_a_registry_entry():
    """Regression for #1198: PgDuckDBDDLGenerator inherits PostgreSQLDDLGenerator's
    SUPPORTED_TUNING_TYPES, which includes sorting (postgresql.py:78) -- a tuned
    SORTING config is processed (as a CLUSTER-index pair, then CLUSTER filtered
    out), not rejected. The registry entry originally covered only PARTITIONING
    and CLUSTERING, so get_capability("pg-duckdb", SORTING) returned None
    (== "not compatible") instead of the correct rendered_via="none"
    ("compatible, but real execution renders nothing").
    """
    capability = get_capability("pg-duckdb", TuningType.SORTING)
    assert capability is not None
    assert capability.rendered_via == "none"


# ---------------------------------------------------------------------------
# Pre-existing drift coverage from PR #1177 (finding R7), kept as-is: these
# compare the three sources' independent, as-presented-today behavior (not
# their internal computation, which is what the tests above pin) and remain
# valid unchanged by the w1 registry consolidation -- see module docstring.
# ---------------------------------------------------------------------------


def _discover_generator_registry_keys() -> frozenset[str]:
    """Statically extract the platform-key strings in get_ddl_generator()'s
    `generators` dict literal, by parsing its own source with `ast`.

    Mirrors test_ddl_generator_registry.py's approach of inspecting the dict
    literal's keys (there it inspects the values/class names) so this stays
    in sync with the real registry without redeclaring it.
    """
    source = inspect.getsource(get_ddl_generator)
    tree = ast.parse(source)
    function_node = tree.body[0]
    assert isinstance(function_node, ast.FunctionDef)

    for node in ast.walk(function_node):
        is_generators_assign = isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "generators" for target in node.targets
        )
        is_generators_annassign = (
            isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "generators"
        )
        if not (is_generators_assign or is_generators_annassign):
            continue

        dict_node = node.value
        assert isinstance(dict_node, ast.Dict)
        keys: set[str] = set()
        for key in dict_node.keys:
            assert isinstance(key, ast.Constant) and isinstance(key.value, str), (
                f"Expected a string literal key in generators dict, got {key!r}"
            )
            keys.add(key.value)
        return frozenset(keys)

    raise AssertionError("Could not find a `generators = {...}` assignment in get_ddl_generator()")


def _discover_tuning_free_platform_keys() -> frozenset[str]:
    return frozenset(ddl_generator_module._TUNING_FREE_PLATFORMS)


def _make_candidate(role: str) -> WorkloadTuningCandidate:
    return WorkloadTuningCandidate(
        benchmark="tpch",
        table="t",
        column="c",
        type="DATE",
        roles=(role,),
        query_count=1,
        query_ids=("Q1",),
        status="accepted",
        rationale="capability-source-drift probe",
        evidence_source="test_capability_source_drift.py",
    )


def _discover_capability_supported_platforms(candidate_platform_keys: frozenset[str]) -> frozenset[str]:
    """A platform counts as "supported" by map_candidate_to_platform if at
    least one logical role maps to a MAPPED decision for it. This calls the
    real function across every known role instead of re-implementing its
    per-platform branch logic.
    """
    supported: set[str] = set()
    for platform in candidate_platform_keys:
        for role in VALID_ROLES:
            mapping = map_candidate_to_platform(platform, _make_candidate(role))
            if mapping.decision == "mapped":
                supported.add(platform)
                break
    return frozenset(supported)


GENERATOR_REGISTRY_KEYS = _discover_generator_registry_keys()
COMPAT_MAP_KEYS = frozenset(_PLATFORM_COMPATIBILITY_MAP)
CAPABILITY_SUPPORTED_KEYS = _discover_capability_supported_platforms(GENERATOR_REGISTRY_KEYS | COMPAT_MAP_KEYS)

# Generator-registry keys with no _PLATFORM_COMPATIBILITY_MAP entry. Expected:
# the generator registry deliberately carries CLI aliases (clickhouse-local/
# -server/-cloud/chdb, pg-duckdb/pg_duckdb, pg-mooncake/pg_mooncake), platform
# families the compat map has no per-tuning-type opinion on yet (doris,
# starrocks, firebolt, azure_synapse/synapse, trino/presto/athena, the
# Spark/Delta family, questdb, timescaledb). starrocks stays generator-only by
# design: it gets a real generator + capability_registry entry for rendering
# lookups, but is deliberately kept out of interface.py's "known" compatibility
# set (see capability_registry's module docstring and
# test_platform_identity_keys.py). Consolidating these into one canonical key
# set is gated on ADR-3 (see interface.py's _PLATFORM_COMPATIBILITY_MAP
# docstring and test_ddl_generator_registry.py) -- do not grow the compat map
# to silence this without that ADR.
EXPECTED_GENERATOR_ONLY_KEYS = frozenset(
    {
        "doris",
        "starrocks",
        "clickhouse-local",
        "clickhouse-server",
        "clickhouse-cloud",
        "chdb",
        "firebolt",
        "azure_synapse",
        "synapse",
        "trino",
        "presto",
        "athena",
        "spark",
        "delta",
        "fabric_warehouse",
        "questdb",
        "pg-duckdb",
        "pg_duckdb",
        "pg-mooncake",
        "pg_mooncake",
        "timescaledb",
    }
)

# _PLATFORM_COMPATIBILITY_MAP keys with no DDL generator registration.
# "sqlite" is in _TUNING_FREE_PLATFORMS (no physical tuning surface at all,
# a deliberate permanent NoOp) so it is exempt from the generator-registered
# expectation. "mysql" is NOT in _TUNING_FREE_PLATFORMS and has no generator
# either -- get_ddl_generator("mysql") falls through to a *warning* NoOp
# today. That is a real, known gap (the compat map claims mysql supports
# PARTITIONING/PRIMARY_KEYS/etc. tuning types but nothing renders DDL for
# them), tracked for resolution alongside the ADR-3 consolidation rather than
# fixed here (scope_limit for this TODO is tests-only plus coverage.py).
EXPECTED_COMPAT_ONLY_KEYS = frozenset({"sqlite", "mysql"})

# _PLATFORM_COMPATIBILITY_MAP keys with no logical workload-profile mapping.
# map_candidate_to_platform only implements databricks/duckdb/bigquery/
# redshift/snowflake branches today (TPC tuned-template tooling scope);
# clickhouse/postgresql/mysql/sqlite have compat-map tuning-type entries but
# no workload_profiles.py mapping yet.
EXPECTED_COMPAT_NOT_IN_CAPABILITY = frozenset({"clickhouse", "postgresql", "mysql", "sqlite"})

# Every platform map_candidate_to_platform supports today is also a
# _PLATFORM_COMPATIBILITY_MAP key -- no known divergence in this direction.
EXPECTED_CAPABILITY_NOT_IN_COMPAT: frozenset[str] = frozenset()


class TestGeneratorRegistryVsCompatibilityMapDrift:
    def test_generator_only_keys_match_allowlist(self) -> None:
        actual = GENERATOR_REGISTRY_KEYS - COMPAT_MAP_KEYS
        assert actual == EXPECTED_GENERATOR_ONLY_KEYS, (
            f"New drift between get_ddl_generator()'s registry and "
            f"_PLATFORM_COMPATIBILITY_MAP: {sorted(actual - EXPECTED_GENERATOR_ONLY_KEYS)} newly "
            f"generator-only, {sorted(EXPECTED_GENERATOR_ONLY_KEYS - actual)} no longer generator-only "
            "(stale allowlist entry -- remove it). Update EXPECTED_GENERATOR_ONLY_KEYS with a reason, "
            "or add a _PLATFORM_COMPATIBILITY_MAP entry if this platform should now enforce "
            "tuning-type compatibility."
        )

    def test_compat_only_keys_match_allowlist(self) -> None:
        actual = COMPAT_MAP_KEYS - GENERATOR_REGISTRY_KEYS
        assert actual == EXPECTED_COMPAT_ONLY_KEYS, (
            f"New drift: {sorted(actual - EXPECTED_COMPAT_ONLY_KEYS)} newly compat-only, "
            f"{sorted(EXPECTED_COMPAT_ONLY_KEYS - actual)} no longer compat-only (stale allowlist "
            "entry -- remove it, or register a DDL generator / add to _TUNING_FREE_PLATFORMS)."
        )

    def test_stale_tuning_free_exemption_is_not_hiding_new_compat_only_drift(self) -> None:
        # sqlite is exempted above because it's declared tuning-free; if it
        # were ever removed from _TUNING_FREE_PLATFORMS without a real
        # generator being registered, it would silently warn at runtime
        # exactly like today's "mysql" gap. Pin that today's tuning-free set
        # still covers every compat-only key we exempt for that reason.
        tuning_free = _discover_tuning_free_platform_keys()
        assert "sqlite" in tuning_free


class TestCapabilityMapperVsCompatibilityMapDrift:
    def test_compat_keys_missing_from_capability_mapper_match_allowlist(self) -> None:
        actual = COMPAT_MAP_KEYS - CAPABILITY_SUPPORTED_KEYS
        assert actual == EXPECTED_COMPAT_NOT_IN_CAPABILITY, (
            f"New drift: {sorted(actual - EXPECTED_COMPAT_NOT_IN_CAPABILITY)} newly unsupported by "
            f"map_candidate_to_platform, {sorted(EXPECTED_COMPAT_NOT_IN_CAPABILITY - actual)} no longer "
            "unsupported (stale allowlist entry -- remove it, since the mapper now covers this platform)."
        )

    def test_capability_mapper_keys_missing_from_compat_map_match_allowlist(self) -> None:
        actual = CAPABILITY_SUPPORTED_KEYS - COMPAT_MAP_KEYS
        assert actual == EXPECTED_CAPABILITY_NOT_IN_COMPAT, (
            f"map_candidate_to_platform now supports a platform absent from "
            f"_PLATFORM_COMPATIBILITY_MAP: {sorted(actual)}. Add a compatibility-map entry, or "
            "document the divergence in EXPECTED_CAPABILITY_NOT_IN_COMPAT with a reason."
        )

    def test_capability_mapper_supported_set_is_the_expected_five_platforms(self) -> None:
        # Pins today's exact scope of platform_capabilities.py so silent
        # additions (or removals) are caught even though they wouldn't
        # necessarily create a compat-map divergence.
        assert frozenset({"databricks", "duckdb", "bigquery", "redshift", "snowflake"}) == CAPABILITY_SUPPORTED_KEYS
