"""Single capability registry for tuning-type rendering across platforms.

Per ADR-3 (`docs/development/tuning-adr-003-baseline-and-single-renderer.md`)
and the `tuning-renderer-consolidation-and-baseline-policy-20260712` TODO,
this module is the ONE place that answers, for a canonical platform type and
a `TuningType`: *how does BenchBox actually apply this tuning, if at all?*

It is built by reading the other capability sources that already exist in
the codebase -- `benchbox.core.tuning.ddl_generator.get_ddl_generator`
(which generator, if any, a platform resolves to and what tuning types that
generator supports), `benchbox.core.tuning.interface._PLATFORM_COMPATIBILITY_MAP`
(the historical compatibility map), and direct inspection of adapter/mixin
source (`benchbox/platforms/<platform>/*.py`) -- rather than inventing new
policy. `interface.py`'s compatibility map and `platform_capabilities.py`'s
workload-profile mapping now derive their platform-set data from this
module (see the constants they import below) instead of maintaining
independent copies.

Scope note: this registry intentionally does NOT change
`TuningType.is_compatible_with_platform` behavior. `_INTERFACE_KNOWN_PLATFORMS`
below reproduces the exact nine-platform set `interface.py` has always used
(pinned by `tests/unit/core/tuning/test_platform_identity_keys.py`); platforms
like `starrocks` and `doris` get real registry entries here (for rendering
lookups and the `benchbox tuning platforms` CLI table) without becoming
"known" for the hard-error-vs-warning compatibility distinction, because
that distinction is deliberately lenient for platforms the interface map has
no opinion on (see `TuningType.is_known_platform`'s docstring). A candidate
correction was investigated during this consolidation (Databricks
`DISTRIBUTION` looked, at first read, like a dead compatibility entry -- no
adapter code renders a literal DISTRIBUTED-BY clause for it) but shipped
examples (`examples/tunings/databricks/tpch_tuned.yaml`,
`tpcds_tuned.yaml`, etc.) set `distribution:` columns that the Z-ORDER
workload-profile mapping (`platform_capabilities.py::_map_databricks`) folds
into ZORDER locality upstream of the adapter. Removing the compatibility
entry would newly hard-error those shipped configs, so it was left
unchanged. No `is_compatible_with_platform` behavior changes ship in this
TODO; this module is a consolidation of *lookup*, not a correctness pass.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from benchbox.core.tuning.interface import TuningType

# Where/how a tuning type is actually rendered for a platform, today:
#   "ddl"       - part of the CREATE TABLE statement (inline clause or table
#                 property) at schema-creation time.
#   "post_load" - a statement run after data load (CTAS reorder, OPTIMIZE,
#                 ZORDER, etc.).
#   "session"   - a session-level SET statement.
#   "none"      - no physical rendering exists yet, even though the type is
#                 accepted as compatible; a documented gap, not silent scope.
RenderedVia = Literal["ddl", "post_load", "session", "none"]


@dataclass(frozen=True)
class TuningCapability:
    """One platform+tuning-type capability entry."""

    rendered_via: RenderedVia
    mechanism_id: str
    notes: str = ""


def _ddl(mechanism_id: str, notes: str = "") -> TuningCapability:
    return TuningCapability(rendered_via="ddl", mechanism_id=mechanism_id, notes=notes)


def _post_load(mechanism_id: str, notes: str = "") -> TuningCapability:
    return TuningCapability(rendered_via="post_load", mechanism_id=mechanism_id, notes=notes)


def _session(mechanism_id: str, notes: str = "") -> TuningCapability:
    return TuningCapability(rendered_via="session", mechanism_id=mechanism_id, notes=notes)


def _none(mechanism_id: str, notes: str = "") -> TuningCapability:
    return TuningCapability(rendered_via="none", mechanism_id=mechanism_id, notes=notes)


_T = TuningType
_INLINE_CONSTRAINT = "inline_column_constraint"
_CONSTRAINT_NOTE = "Rendered as an inline column/table constraint clause at CREATE TABLE time."


def _constraint_entries() -> dict[TuningType, TuningCapability]:
    """Shared entries for the four schema-constraint tuning types.

    Every platform below renders these the same way: inline at CREATE TABLE
    time. Returned as a fresh dict per call so callers can safely merge it
    into a larger per-platform dict literal.
    """
    return {
        _T.PRIMARY_KEYS: _ddl(_INLINE_CONSTRAINT, _CONSTRAINT_NOTE),
        _T.FOREIGN_KEYS: _ddl(_INLINE_CONSTRAINT, _CONSTRAINT_NOTE),
        _T.UNIQUE_CONSTRAINTS: _ddl(_INLINE_CONSTRAINT, _CONSTRAINT_NOTE),
        _T.CHECK_CONSTRAINTS: _ddl(_INLINE_CONSTRAINT, _CONSTRAINT_NOTE),
    }


# Platform aliases: alternate canonical keys (deployment variants, format
# aliases) that resolve to the same capability entry. Mirrors
# `get_ddl_generator`'s alias table so this registry does not silently miss
# a platform key that already has a real generator.
PLATFORM_ALIASES: dict[str, str] = {
    "clickhouse-local": "clickhouse",
    "clickhouse-server": "clickhouse",
    "chdb": "clickhouse",
    "spark": "databricks",
    "delta": "databricks",
    "fabric_warehouse": "databricks",
}


# Per-platform, per-tuning-type capability entries. Only platforms with an
# entry in `interface._PLATFORM_COMPATIBILITY_MAP` (the historical
# compatibility map) or explicitly named in the renderer-consolidation TODO
# (`starrocks`, `doris`) are covered; the DDL generator registry additionally
# covers ~10 more SQL platforms (redshift, snowflake, etc. below) whose
# adapter execution paths were not audited/migrated this round -- their
# entries reflect the "per-adapter mixin" renderer ADR-3 calls the third
# rendering universe, unchanged by this TODO.
PLATFORM_TUNING_CAPABILITIES: dict[str, dict[TuningType, TuningCapability]] = {
    "duckdb": {
        _T.SORTING: _post_load(
            "duckdb_ctas_sort",
            "CTAS reorder (CREATE OR REPLACE TABLE ... AS SELECT * FROM ... ORDER BY ...) run after data "
            "load; DuckDB has no inline CREATE TABLE ORDER BY syntax. Consumed via "
            "core.tuning.generators.duckdb.DuckDBDDLGenerator.generate_ctas_ddl by both dry-run preview "
            "and real execution as of the w2 duckdb migration.",
        ),
        _T.PARTITIONING: _none(
            "duckdb_copy_to_hint_only",
            "DuckDBDDLGenerator.generate_tuning_clauses logs a COPY TO Hive-partitioning hint for "
            "partition columns but no BenchBox code path applies it to the physical benchmark schema. "
            "Documented gap, not migrated this round (compatible per the legacy map; no rendering yet).",
        ),
        **_constraint_entries(),
    },
    "clickhouse": {
        _T.PARTITIONING: _ddl(
            "clickhouse_ddl_generator:PARTITION_BY",
            "core.tuning.generators.clickhouse.ClickHouseDDLGenerator renders PARTITION BY at CREATE "
            "TABLE time. Consumed by dry-run preview and (as of the w2 clickhouse migration) real "
            "execution in ClickHouseWorkloadMixin._optimize_table_definition.",
        ),
        _T.SORTING: _ddl(
            "clickhouse_ddl_generator:ORDER_BY",
            "Rendered as ORDER BY, combined with any clustering columns. See PARTITIONING entry for the "
            "shared migration note.",
        ),
        _T.CLUSTERING: _ddl(
            "clickhouse_ddl_generator:ORDER_BY",
            "ClickHouse has no separate clustering clause; clustering columns are folded into ORDER BY "
            "ahead of sorting columns by the generator.",
        ),
        _T.PRIMARY_KEYS: _ddl(
            "clickhouse_order_by_or_tuple_fallback",
            "MergeTree requires ORDER BY. When no tuned sort/cluster columns are configured, "
            "_optimize_table_definition falls back to primary-key-derived columns or ORDER BY tuple() -- "
            "this fallback is the engine-mandatory baseline (see ADR-3 baseline policy), not tuned "
            "rendering.",
        ),
        _T.UNIQUE_CONSTRAINTS: _none(
            "unimplemented",
            "Compatible per the legacy map (downgraded to a warning regardless, as a constraint type); "
            "ClickHouse has no UNIQUE constraint syntax and no adapter code renders one.",
        ),
        _T.MATERIALIZED_VIEWS: _none(
            "unimplemented",
            "Compatible per the legacy map; no adapter code creates a materialized view.",
        ),
    },
    "databricks": {
        _T.PARTITIONING: _ddl(
            "delta_partitioned_by",
            "Rendered as Delta PARTITIONED BY at CREATE TABLE time via the cloud_spark DDL mixin "
            "(third renderer per ADR-3; not migrated to core.tuning.generators this round -- Databricks "
            "migration is explicitly out of scope, owned by the blocked databricks-liquid-clustering "
            "TODO).",
        ),
        _T.CLUSTERING: _post_load(
            "databricks_z_order_or_liquid",
            "Rendered post-load as OPTIMIZE ... ZORDER BY (z_order strategy) or ALTER TABLE ... CLUSTER "
            "BY (Liquid Clustering strategies) by benchbox/platforms/databricks/adapter.py. Not migrated "
            "this round; see PARTITIONING entry.",
        ),
        _T.DISTRIBUTION: _none(
            "no_user_managed_distribution_key",
            "Databricks has no user-managed distribution key (see platform_capabilities.py's own "
            "reasoning strings). Distribution columns configured in shipped examples "
            "(examples/tunings/databricks/*_tuned.yaml) are folded into ZORDER locality by the "
            "workload-profile mapping upstream of the adapter, not rendered as a literal clause here.",
        ),
        _T.Z_ORDERING: _post_load("databricks_z_order_or_liquid", "See CLUSTERING entry."),
        _T.LIQUID_CLUSTERING: _post_load("databricks_z_order_or_liquid", "See CLUSTERING entry."),
        _T.AUTO_OPTIMIZE: _ddl(
            "delta_tblproperties",
            "Rendered as a Delta TBLPROPERTIES entry (delta.autoOptimize.optimizeWrite) at CREATE TABLE time.",
        ),
        _T.AUTO_COMPACT: _ddl(
            "delta_tblproperties",
            "Rendered as a Delta TBLPROPERTIES entry (delta.autoOptimize.autoCompact) at CREATE TABLE time.",
        ),
        _T.BLOOM_FILTERS: _none(
            "unimplemented",
            "Compatible per the legacy map; no adapter code creates a Bloom filter index.",
        ),
        _T.MATERIALIZED_VIEWS: _none(
            "unimplemented",
            "Compatible per the legacy map; no adapter code creates a materialized view.",
        ),
        **_constraint_entries(),
    },
    "snowflake": {
        _T.CLUSTERING: _ddl(
            "adapter_mixin:SnowflakeAdapter.generate_tuning_clause",
            "Execution still renders via the adapter's own generate_tuning_clause mixin, independent of "
            "core.tuning.generators.snowflake.SnowflakeDDLGenerator (dry-run preview's renderer). Third "
            "rendering universe per ADR-3; not in this TODO's migration order (duckdb, clickhouse, "
            "starrocks).",
        ),
        _T.PARTITIONING: _ddl("adapter_mixin:SnowflakeAdapter.generate_tuning_clause", "See CLUSTERING entry."),
        _T.MATERIALIZED_VIEWS: _none("unimplemented", "Compatible per the legacy map; no adapter implementation."),
        **_constraint_entries(),
    },
    "bigquery": {
        _T.PARTITIONING: _ddl("adapter_mixin:BigQueryAdapter.generate_tuning_clause", "See snowflake entry note."),
        _T.CLUSTERING: _ddl("adapter_mixin:BigQueryAdapter.generate_tuning_clause", "See snowflake entry note."),
        _T.MATERIALIZED_VIEWS: _none("unimplemented", "Compatible per the legacy map; no adapter implementation."),
        _T.PRIMARY_KEYS: _ddl(_INLINE_CONSTRAINT, _CONSTRAINT_NOTE),
        _T.FOREIGN_KEYS: _ddl(_INLINE_CONSTRAINT, _CONSTRAINT_NOTE),
        _T.CHECK_CONSTRAINTS: _ddl(_INLINE_CONSTRAINT, _CONSTRAINT_NOTE),
    },
    "redshift": {
        _T.DISTRIBUTION: _ddl("adapter_mixin:RedshiftAdapter.generate_tuning_clause", "See snowflake entry note."),
        _T.SORTING: _ddl("adapter_mixin:RedshiftAdapter.generate_tuning_clause", "See snowflake entry note."),
        _T.PARTITIONING: _ddl("adapter_mixin:RedshiftAdapter.generate_tuning_clause", "See snowflake entry note."),
        _T.MATERIALIZED_VIEWS: _none("unimplemented", "Compatible per the legacy map; no adapter implementation."),
        **_constraint_entries(),
    },
    "sqlite": _constraint_entries(),
    "postgresql": {
        _T.PARTITIONING: _ddl("adapter_mixin:PostgreSQLAdapter.generate_tuning_clause", "See snowflake entry note."),
        _T.CLUSTERING: _ddl("adapter_mixin:PostgreSQLAdapter.generate_tuning_clause", "See snowflake entry note."),
        _T.BLOOM_FILTERS: _none("unimplemented", "Compatible per the legacy map; no adapter implementation."),
        _T.MATERIALIZED_VIEWS: _none("unimplemented", "Compatible per the legacy map; no adapter implementation."),
        **_constraint_entries(),
    },
    "mysql": {
        _T.PARTITIONING: _ddl("adapter_mixin:MySQLAdapter.generate_tuning_clause", "See snowflake entry note."),
        **_constraint_entries(),
    },
    # Explicitly named by the renderer-consolidation TODO even though absent
    # from interface.py's historical compatibility map (see module docstring
    # for why that stays true after this consolidation).
    "starrocks": {
        _T.PARTITIONING: _none(
            "log_only",
            "StarRocksTuningMixin.apply_table_tunings only logs configured partitioning columns; no "
            "PARTITION BY clause is generated. No StarRocks entry exists in "
            "core.tuning.ddl_generator.get_ddl_generator, so dry-run preview is also empty (NoOp "
            "fallback) -- there is no drift between preview and execution, both are silent. Documented "
            "gap; this TODO explicitly scopes StarRocks generator-writing out (no generator exists to "
            "migrate to).",
        ),
        _T.SORTING: _none(
            "log_only",
            "Same log-only gap as PARTITIONING; StarRocks data-model keys (DUPLICATE KEY / PRIMARY KEY) "
            "are chosen from the source DDL's primary key, not tuned sort columns.",
        ),
        _T.DISTRIBUTION: _none(
            "engine_mandatory_baseline_not_tuned",
            "benchbox/platforms/starrocks/workload.py's schema rewrite unconditionally appends "
            "DISTRIBUTED BY HASH(<first_column>) BUCKETS 8 when no distribution clause is already "
            "present, in every tuning mode. This is engine-mandatory baseline (StarRocks requires a "
            "distribution clause for a working table), not a tuned rendering of TuningType.DISTRIBUTION "
            "-- configured distribution columns are only logged, never used to pick the hash key. Per "
            "the TODO: no StarRocks generator exists and none is written this round; tuned distribution "
            "stays a documented gap.",
        ),
    },
    "doris": {
        _T.PARTITIONING: _ddl(
            "doris_ddl_generator",
            "core.tuning.generators.doris.DorisDDLGenerator exists and is reachable via "
            "get_ddl_generator('doris') for dry-run preview. Adapter execution-path parity was not "
            "audited this round (Doris is not in this TODO's migration order).",
        ),
        _T.SORTING: _ddl("doris_ddl_generator", "See PARTITIONING entry."),
        _T.DISTRIBUTION: _ddl("doris_ddl_generator", "See PARTITIONING entry."),
    },
}


# The exact platform-key set `interface.py`'s compatibility map has always
# used. Pinned by tests/unit/core/tuning/test_platform_identity_keys.py --
# `starrocks`/`doris` are deliberately excluded (see module docstring): they
# get registry entries above for rendering-mechanism lookups, but keeping
# them out of the "known" set preserves the existing warn-not-error
# treatment for platforms interface.py has no compatibility opinion on.
_INTERFACE_KNOWN_PLATFORMS: frozenset[str] = frozenset(
    {
        "duckdb",
        "snowflake",
        "bigquery",
        "redshift",
        "clickhouse",
        "databricks",
        "sqlite",
        "postgresql",
        "mysql",
    }
)


def interface_compatibility_map() -> dict[str, frozenset[TuningType]]:
    """Build `interface._PLATFORM_COMPATIBILITY_MAP`'s data from this registry.

    Returns the same shape (canonical platform key -> frozenset of compatible
    `TuningType`s) `interface.py` has always hand-maintained, but computed
    from `PLATFORM_TUNING_CAPABILITIES` so the two can no longer drift.
    Restricted to `_INTERFACE_KNOWN_PLATFORMS` -- see module docstring.
    """
    return {platform: frozenset(PLATFORM_TUNING_CAPABILITIES[platform]) for platform in _INTERFACE_KNOWN_PLATFORMS}


def get_capability(platform: str, tuning_type: TuningType) -> TuningCapability | None:
    """Look up the rendering capability for a platform + tuning type.

    Args:
        platform: Canonical platform type key (case-insensitive); aliases in
            `PLATFORM_ALIASES` are resolved first.
        tuning_type: The tuning type to look up.

    Returns:
        The `TuningCapability`, or None if the platform has no registry
        entry, or has an entry but no opinion on this specific tuning type
        (equivalent to "not compatible" -- distinct from an explicit `"none"`
        rendered_via, which means "compatible, but not rendered yet").
    """
    platform_key = platform.lower().replace("_", "-")
    platform_key = PLATFORM_ALIASES.get(platform_key, platform_key)
    entries = PLATFORM_TUNING_CAPABILITIES.get(platform_key)
    if entries is None:
        return None
    return entries.get(tuning_type)


def known_registry_platforms() -> frozenset[str]:
    """All canonical platform keys with at least one registry entry (broader than interface.py's set)."""
    return frozenset(PLATFORM_TUNING_CAPABILITIES)


# Platforms whose logical-workload-tuning-candidate mapping
# (`benchbox.core.tuning.platform_capabilities.map_candidate_to_platform`) is
# implemented. Derived here (rather than re-declared in that module) so the
# "which platforms does the TPC template mapper know about" fact has one
# owner; see platform_capabilities.py.
WORKLOAD_PROFILE_MAPPED_PLATFORMS: frozenset[str] = frozenset(
    {"databricks", "duckdb", "bigquery", "redshift", "snowflake"}
)


__all__ = [
    "RenderedVia",
    "TuningCapability",
    "PLATFORM_ALIASES",
    "PLATFORM_TUNING_CAPABILITIES",
    "WORKLOAD_PROFILE_MAPPED_PLATFORMS",
    "get_capability",
    "interface_compatibility_map",
    "known_registry_platforms",
]
