"""Cross-source consistency for the remaining tuning capability registries.

From the 2026-07-12 tuning review, finding R7. Three independent sources each
carry their own notion of "which platforms does BenchBox know how to tune":

1. `get_ddl_generator()`'s platform-key mapping (benchbox/core/tuning/ddl_generator.py)
   - which platforms get a *real* DDL generator (indexes/partitioning/clustering
     clauses), keyed by every CLI-facing platform alias.
2. `TuningType._PLATFORM_COMPATIBILITY_MAP` (benchbox/core/tuning/interface.py)
   - which tuning *types* (partitioning, clustering, ...) are valid for a
     platform, keyed by canonical platform type only (no aliases).
3. `platform_capabilities.map_candidate_to_platform()` (benchbox/core/tuning/
   platform_capabilities.py) - which platforms have a *logical workload
   profile* mapping (TPC candidate roles -> physical tuning types), a strict
   subset used only by the TPC tuned-template tooling.

PR #1174 already added a sync test between `_PLATFORM_COMPATIBILITY_MAP` and
`_KNOWN_COMPATIBILITY_PLATFORMS` (they're derived from each other, so they
literally cannot diverge). This module covers the *remaining*, genuinely
independent sources: the DDL generator registry and the workload-profile
capability mapper, each compared against the compatibility map.

These three sources have different scopes by design (the generator registry
is deliberately more granular -- it registers CLI aliases like
"clickhouse-local" and platform families like "trino"/"presto"/"athena" that
the compatibility map has no opinion on) so an exact-match assertion would be
constant noise. Instead, every current divergence is enumerated in
`EXPECTED_DRIFT` below with a reason; consolidating these three registries
into one is gated on ADR-3 (referenced in interface.py and
test_ddl_generator_registry.py) and the tuning-platform-identity-canonical-keys
follow-on work. This test fails only when a *new*, undocumented divergence
appears (or a documented one silently disappears -- see
`test_ddl_generator_registry.py`'s `test_exempt_list_has_no_stale_entries` for
the same "no stale allowlist entries" pattern).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from benchbox.core.tuning import ddl_generator as ddl_generator_module
from benchbox.core.tuning.ddl_generator import get_ddl_generator
from benchbox.core.tuning.interface import _PLATFORM_COMPATIBILITY_MAP
from benchbox.core.tuning.platform_capabilities import map_candidate_to_platform
from benchbox.core.tuning.workload_profiles import VALID_ROLES, WorkloadTuningCandidate

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _discover_generator_registry_keys() -> frozenset[str]:
    """Statically extract the platform-key strings in get_ddl_generator()'s
    `generators` dict literal, by parsing its own source with `ast`.

    Mirrors test_ddl_generator_registry.py's approach of inspecting the dict
    literal's keys (there it inspects the values/class names) so this stays
    in sync with the real registry without re-declaring it.
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
# -server/chdb, pg-duckdb/pg_duckdb, pg-mooncake/pg_mooncake), platform
# families the compat map has no per-tuning-type opinion on yet (doris,
# firebolt, azure_synapse/synapse, trino/presto/athena, the Spark/Delta
# family, questdb, timescaledb). Consolidating these into one canonical key
# set is gated on ADR-3 (see interface.py's _PLATFORM_COMPATIBILITY_MAP
# docstring and test_ddl_generator_registry.py) -- do not grow the compat map
# to silence this without that ADR.
EXPECTED_GENERATOR_ONLY_KEYS = frozenset(
    {
        "doris",
        "clickhouse-local",
        "clickhouse-server",
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
