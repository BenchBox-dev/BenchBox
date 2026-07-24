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

Coverage note (`tuning-capability-registry-coverage-20260716`): the
trino/presto/athena/firebolt/azure-synapse/timescaledb/questdb/pg-duckdb/
pg-mooncake entries below extend this same non-"known" (starrocks/doris
style) treatment to the platforms that were previously undocumented
allowlist gaps in `test_capability_source_drift.py`. Every one of those 9
entries is `rendered_via="none"`: a repo-wide search found no call site for
any of these platforms' `generate_tuning_clause()` adapter override outside
its own definition and direct unit tests, so real execution never applies
the dry-run-preview generator's tuned clause -- it either does nothing, or
(azure_synapse/timescaledb/questdb) runs a separate mechanism driven by a
fixed platform default or a hardcoded per-table-name map rather than the
configured `TableTuning` columns. See the per-platform entries for exact
file:line evidence and the renderer-migration follow-up each implies.

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
#   "none"      - no *tuned* rendering of this TuningType exists yet, even
#                 though the type is accepted as compatible; a documented
#                 gap, not silent scope. This does NOT mean the platform
#                 emits no clause at all: some adapters emit a real, fixed
#                 clause regardless of the tuned configuration (e.g. Azure
#                 Synapse's DISTRIBUTION always gets a WITH (DISTRIBUTION =
#                 ...) clause, just never one derived from TableTuning
#                 columns) -- see each entry's mechanism notes for what, if
#                 anything, is actually emitted.
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
#
# Most alternate spellings never need an entry here: `resolve_platform_key`
# normalizes underscores to hyphens BEFORE consulting this dict, so
# "azure_synapse"/"azure-synapse" and "pg_duckdb"/"pg-duckdb" already collapse
# onto the same canonical (hyphenated) key without help. Two kinds of entry
# genuinely need to be listed explicitly:
#   1. A short alias that isn't an underscore/hyphen variant of its canonical
#      key at all -- e.g. Azure Synapse's "synapse".
#   2. An alias key that itself contains an underscore -- because
#      normalization runs first, an underscore in the DICT KEY here can never
#      match (the input would already have been folded to a hyphen before
#      lookup); the key must be written hyphenated. "fabric-warehouse" below
#      was originally stored as "fabric_warehouse" and consequently never
#      matched any input -- fixed here alongside "clickhouse-cloud", which
#      get_ddl_generator registers but this dict never listed at all.
PLATFORM_ALIASES: dict[str, str] = {
    "clickhouse-local": "clickhouse",
    "clickhouse-server": "clickhouse",
    "clickhouse-cloud": "clickhouse",
    "chdb": "clickhouse",
    "spark": "databricks",
    "delta": "databricks",
    "fabric-warehouse": "databricks",
    "synapse": "azure-synapse",
}


# Per-platform, per-tuning-type capability entries. Only platforms with an
# entry in `interface._PLATFORM_COMPATIBILITY_MAP` (the historical
# compatibility map) or explicitly named in the renderer-consolidation TODO
# (`starrocks`, `doris`) are covered; the DDL generator registry additionally
# covers ~10 more SQL platforms (redshift, snowflake, etc. below).
#
# Honesty correction (`tuning-registry-mixin-honesty`): the postgresql,
# snowflake, redshift, bigquery and mysql entries below previously claimed
# `_ddl("adapter_mixin:<X>Adapter.generate_tuning_clause", ...)`, but that
# mixin has no production call site anywhere -- create_schema builds DDL from
# `benchmark.get_create_tables_sql(tuning_config=...)`, which reads
# tuning_config only for PK/FK constraint flags, never the partition/cluster/
# distribution/sort columns (see e.g. core/tpch/benchmark.py:423-426). Those
# entries now describe reality: snowflake renders CLUSTERING/PARTITIONING
# post-load via a real ALTER TABLE ... CLUSTER BY in apply_table_tunings,
# while postgresql/redshift/bigquery/mysql render nothing at execution
# (rendered_via="none"; their generators/*.py DDL generators, where present,
# feed dry-run preview only) -- the same preview-only reality PR #1198
# recorded for the 9 coverage platforms below. The set of compatible tuning
# types per platform is unchanged, so is_compatible_with_platform behavior is
# preserved.
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
        _T.CLUSTERING: _post_load(
            "adapter_mixin:SnowflakeAdapter.apply_table_tunings",
            "Real execution issues ALTER TABLE ... CLUSTER BY (...) from "
            "SnowflakeAdapter.apply_table_tunings (snowflake.py:1710), reached via apply_unified_tuning -> "
            "apply_standard_unified_tuning after create_schema (base/result_capture.py:1751-1753). This is "
            "NOT part of the CREATE TABLE ddl and does NOT go through the adapter's generate_tuning_clause "
            "mixin (snowflake.py:1605): that method builds a CLUSTER BY string but has no production call "
            "site anywhere, and get_create_tables_sql consumes tuning_config only for PK/FK constraint "
            "flags, never clustering columns. core.tuning.generators.snowflake.SnowflakeDDLGenerator emits "
            "CLUSTER BY for dry-run preview only.",
        ),
        _T.PARTITIONING: _post_load(
            "adapter_mixin:SnowflakeAdapter.apply_table_tunings",
            "apply_table_tunings folds partitioning columns into the same ALTER TABLE ... CLUSTER BY when "
            "no clustering columns are configured (snowflake.py:1690-1693); Snowflake has no separate "
            "partition clause. See CLUSTERING entry for the full mechanism/evidence.",
        ),
        _T.MATERIALIZED_VIEWS: _none("unimplemented", "Compatible per the legacy map; no adapter implementation."),
        **_constraint_entries(),
    },
    "bigquery": {
        _T.PARTITIONING: _none(
            "bigquery_ddl_generator:preview_only",
            "core.tuning.generators.bigquery.BigQueryDDLGenerator computes a real PARTITION BY clause from "
            "tuned columns for dry-run preview, but real execution never renders it. "
            "BigQueryAdapter.generate_tuning_clause builds PARTITION BY/CLUSTER BY (bigquery.py:1893) but "
            "has no production call site; get_create_tables_sql consumes tuning_config only for PK/FK "
            "flags, never partition/cluster columns; and apply_table_tunings only inspects the table and "
            "logs 'Consider recreating the table' (bigquery.py:2023-2027) -- it never re-creates it. "
            "Corrects the prior false _ddl(adapter_mixin:BigQueryAdapter.generate_tuning_clause) claim.",
        ),
        _T.CLUSTERING: _none(
            "bigquery_ddl_generator:preview_only",
            "Same execution gap as PARTITIONING: generate_tuning_clause emits CLUSTER BY "
            "(bigquery.py:1940-1949) and the generator previews it, but nothing renders it at execution "
            "(apply_table_tunings only logs a recreation hint, bigquery.py:2013-2027).",
        ),
        _T.MATERIALIZED_VIEWS: _none("unimplemented", "Compatible per the legacy map; no adapter implementation."),
        _T.PRIMARY_KEYS: _ddl(_INLINE_CONSTRAINT, _CONSTRAINT_NOTE),
        _T.FOREIGN_KEYS: _ddl(_INLINE_CONSTRAINT, _CONSTRAINT_NOTE),
        _T.CHECK_CONSTRAINTS: _ddl(_INLINE_CONSTRAINT, _CONSTRAINT_NOTE),
    },
    "redshift": {
        _T.DISTRIBUTION: _none(
            "redshift_ddl_generator:preview_only",
            "core.tuning.generators.redshift.RedshiftDDLGenerator computes real DISTSTYLE/DISTKEY clauses "
            "from tuned columns for dry-run preview, but real execution never renders them. "
            "RedshiftAdapter.generate_tuning_clause builds DISTSTYLE KEY/DISTKEY (redshift.py:2464) but has "
            "no production call site; get_create_tables_sql consumes tuning_config only for PK/FK flags, "
            "never distribution columns; and apply_table_tunings only reads pg_table_def and logs "
            "'Redshift requires table recreation to change distribution/sort keys' (redshift.py:2607-2611) "
            "without recreating, then runs ANALYZE/VACUUM maintenance only (redshift.py:2616-2624). "
            "Corrects the prior false _ddl(adapter_mixin:RedshiftAdapter.generate_tuning_clause) claim.",
        ),
        _T.SORTING: _post_load(
            "redshift_ctas_sort",
            "Conditional post-load mechanism, gated on sorted ingestion being enabled "
            "(resolve_sorted_ingestion_strategy). After COPY/INSERT the loader calls apply_ctas_sort "
            "(redshift.py:1524, 1602), which resolves TuningType.SORTING columns and executes the SQL built "
            "by _build_ctas_sort_sql (redshift.py:207-224) -- either 'VACUUM SORT ONLY' or a CTAS "
            "'... ORDER BY <sort cols>' + DROP + RENAME. Inline SORTKEY remains preview-only: it is built by "
            "the uncalled generate_tuning_clause mixin (redshift.py:2500-2510) and the preview generator, and "
            "apply_table_tunings only logs the sort-key mismatch (redshift.py:2599-2605) because it cannot "
            "rewrite the key without table recreation. With sorted ingestion off, _build_ctas_sort_sql "
            "returns None and nothing is rendered.",
        ),
        _T.PARTITIONING: _none(
            "redshift_no_partition_rendering",
            "Redshift has no CREATE TABLE partition clause; generate_tuning_clause explicitly emits nothing "
            "for partitioning (redshift.py:2512-2517) and apply_table_tunings only logs the strategy "
            "(redshift.py:2629-2636). Nothing is rendered at execution.",
        ),
        _T.MATERIALIZED_VIEWS: _none("unimplemented", "Compatible per the legacy map; no adapter implementation."),
        **_constraint_entries(),
    },
    "sqlite": _constraint_entries(),
    "postgresql": {
        _T.PARTITIONING: _none(
            "postgresql_ddl_generator:preview_only",
            "core.tuning.generators.postgresql.PostgreSQLDDLGenerator computes a real PARTITION BY RANGE/"
            "LIST/HASH clause from tuned columns (generators/postgresql.py:139) for dry-run preview, but "
            "real execution never renders it. PostgreSQLAdapter.generate_tuning_clause unconditionally "
            "returns '' (postgresql.py:972-977) and has no production call site; apply_table_tunings and "
            "apply_unified_tuning are both no-ops (postgresql.py:968-970, 979-981); and get_create_tables_sql "
            "consumes tuning_config only for PK/FK constraint flags. Corrects the prior false "
            "_ddl(adapter_mixin:PostgreSQLAdapter.generate_tuning_clause) claim (already flagged in the "
            "pg-duckdb entry below).",
        ),
        _T.CLUSTERING: _none(
            "postgresql_ddl_generator:preview_only",
            "Same execution gap as PARTITIONING: the preview generator emits a CREATE INDEX + CLUSTER pair "
            "(generators/postgresql.py:141-159) but the uncalled generate_tuning_clause mixin returns '' and "
            "the no-op apply path renders nothing at execution.",
        ),
        _T.BLOOM_FILTERS: _none("unimplemented", "Compatible per the legacy map; no adapter implementation."),
        _T.MATERIALIZED_VIEWS: _none("unimplemented", "Compatible per the legacy map; no adapter implementation."),
        **_constraint_entries(),
    },
    "mysql": {
        _T.PARTITIONING: _none(
            "mysql_no_generator_dead_mixin",
            "No MySQLAdapter class exists (the prior mechanism named a nonexistent class); MySQL-wire "
            "adapters mix in base.mysql_wire.NoOpTableTuningMixin, whose generate_tuning_clause returns '' "
            "(base/mysql_wire.py:475-476) and whose apply_table_tunings/apply_unified_tuning are no-ops "
            "(base/mysql_wire.py:472-473, 478-479). get_ddl_generator('mysql') has no real generator and "
            "falls through to NoOpDDLGenerator, so no MySQL PARTITION BY is rendered at preview or "
            "execution. Corrects the prior false "
            "_ddl(adapter_mixin:MySQLAdapter.generate_tuning_clause) claim.",
        ),
        **_constraint_entries(),
    },
    # Explicitly named by the renderer-consolidation TODO even though absent
    # from interface.py's historical compatibility map (see module docstring
    # for why that stays true after this consolidation).
    "starrocks": {
        _T.PARTITIONING: _ddl(
            "starrocks_ddl_generator",
            "core.tuning.generators.starrocks.StarRocksDDLGenerator renders PARTITION BY from tuned "
            "partitioning columns at CREATE TABLE time. Consumed by both dry-run preview "
            "(get_ddl_generator('starrocks')) and real execution -- benchbox/platforms/starrocks/"
            "workload.py's _optimize_table_definition resolves the same generator via "
            "_resolve_tuned_ddl_clauses and injects the tuned PARTITION BY clause. No drift between "
            "preview and execution.",
        ),
        _T.SORTING: _ddl(
            "starrocks_ddl_generator",
            "Rendered as StarRocks' ORDER BY sort-key clause from tuned sorting columns via the shared "
            "generator (see PARTITIONING entry for the shared preview/execution note). The table's key "
            "model (DUPLICATE KEY / PRIMARY KEY) is still chosen from the source DDL's primary key by the "
            "workload rewrite, independent of the ORDER BY sort key.",
        ),
        _T.DISTRIBUTION: _ddl(
            "starrocks_ddl_generator",
            "DISTRIBUTED BY HASH(...) BUCKETS N is engine-mandatory (StarRocks requires a distribution "
            "key). The generator renders it, and a tuned distribution column now overrides the "
            "first-column default: the workload picks the hash key from the tuned config when present, "
            "falling back to StarRocksDDLGenerator.render_distribution_clause(<first_column>) for untuned "
            "tables -- byte-identical to the previous bespoke injection (BUCKETS 8). Preview and "
            "execution render through the same generator.",
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
    # ------------------------------------------------------------------
    # `tuning-capability-registry-coverage-20260716`: the 9 platforms below
    # have real `core.tuning.generators` DDL generators (reachable via
    # `get_ddl_generator`) but were undocumented allowlist gaps in
    # `tests/unit/core/tuning/test_capability_source_drift.py` until now.
    # None of them are in `_INTERFACE_KNOWN_PLATFORMS` (same treatment as
    # starrocks/doris above -- registry entries for rendering-mechanism
    # lookups and the `benchbox tuning platforms` CLI table, without
    # affecting the hard-error-vs-warning compatibility distinction).
    #
    # For every one of these 9, the finding is the same shape: the
    # dry-run/CLI-preview generator computes a real, tuning-config-derived
    # clause, but nothing in the adapter's execution path (create_schema /
    # apply_table_tunings / apply_unified_tuning) consumes it. Several of
    # these adapters define their own `generate_tuning_clause` override (the
    # per-adapter-mixin ADR-3 rendering universe used by e.g. Snowflake in
    # this same registry) that structurally *would* render the tuned clause
    # correctly -- but a repo-wide search for `.generate_tuning_clause(` call
    # sites (outside its own definitions and unit tests that invoke it
    # directly) turns up none for any of these 9 platforms: the method is
    # defined but never invoked from `create_schema` or anywhere else. Real
    # execution instead falls through to whatever `_optimize_table_definition`
    # (or, for azure_synapse/timescaledb/questdb, a platform-specific
    # post-processing step) does -- which is either nothing, or a fixed
    # engine default/hardcoded per-table-name mapping unrelated to the
    # configured `TableTuning` columns. `rendered_via="none"` throughout
    # records that dry-run-only reality honestly, per this TODO's
    # must_preserve, the same way #1180 recorded the starrocks/databricks
    # gaps above. Wiring each adapter's `generate_tuning_clause` (or
    # `get_ddl_generator`) into its real `create_schema` path is the
    # renderer-migration follow-up noted per platform below.
    "trino": {
        _T.PARTITIONING: _none(
            "trino_ddl_generator:preview_only",
            "core.tuning.generators.trino.TrinoDDLGenerator computes a real partitioned_by/partitioning "
            "WITH-property clause from tuned columns for dry-run preview (get_ddl_generator('trino')), "
            "but benchbox/platforms/trino.py's TrinoAdapter never consumes it at execution time: "
            "create_schema builds DDL via _create_schema_with_tuning (primary/foreign-key toggle only) "
            "then _optimize_table_definition (trino.py:190-218, file-format/WITH-clause string tweaks "
            "only, no tuning). TrinoAdapter.generate_tuning_clause (trino.py:220-266) re-implements "
            "similar WITH-properties logic but has no call site anywhere in the codebase (a repo-wide "
            "search for '.generate_tuning_clause(' finds only its own definition and unit tests that "
            "call it directly). apply_table_tunings (trino.py:268-298) only logs partition/sort column "
            "names, emitting no SQL. Renderer-migration follow-up: wire generate_tuning_clause (or "
            "get_ddl_generator) into the real create_schema path.",
        ),
        _T.DISTRIBUTION: _none(
            "trino_ddl_generator:preview_only",
            "Same gap as PARTITIONING: the generator computes bucketed_by/bucket_count for the Hive "
            "connector (trino.py:178-187) from tuned distribution columns, but nothing in TrinoAdapter's "
            "execution path renders it.",
        ),
        _T.SORTING: _none(
            "trino_ddl_generator:preview_only",
            "Same gap as PARTITIONING: the generator computes sorted_by for Hive/Iceberg connectors "
            "(trino.py:201-215) from tuned sorting columns, but nothing in TrinoAdapter's execution path "
            "renders it.",
        ),
        _T.CLUSTERING: _none(
            "trino_ddl_generator:preview_only",
            "Trino has no separate clustering clause; the generator folds clustering columns into "
            "sorted_by (trino.py:202-210, see SORTING entry), and the same execution-path gap applies.",
        ),
    },
    "presto": {
        _T.PARTITIONING: _none(
            "trino_ddl_generator:preview_only",
            "get_ddl_generator('presto') resolves to the same core.tuning.generators.trino."
            "TrinoDDLGenerator as trino (real partitioned_by/partitioning WITH-property clause computed "
            "from tuned columns for dry-run preview). benchbox/platforms/presto.py's PrestoAdapter never "
            "consumes it at execution time: _optimize_table_definition (presto.py:214-242) only does "
            "type/format string tweaks, PrestoAdapter.generate_tuning_clause (presto.py:244-272) has no "
            "call site anywhere in the codebase, and apply_table_tunings (presto.py:274-282) only logs "
            "via log_partition_tunings(...). See trino's PARTITIONING entry for the shared-generator "
            "note.",
        ),
        _T.DISTRIBUTION: _none(
            "trino_ddl_generator:preview_only",
            "Same gap as PARTITIONING: the shared generator computes bucketed_by/bucket_count from tuned "
            "distribution columns, but PrestoAdapter's execution path never renders it.",
        ),
        _T.SORTING: _none(
            "trino_ddl_generator:preview_only",
            "Same gap as PARTITIONING: the shared generator computes sorted_by from tuned sorting "
            "columns, but PrestoAdapter's execution path never renders it.",
        ),
        _T.CLUSTERING: _none(
            "trino_ddl_generator:preview_only",
            "Presto has no separate clustering clause; folded into sorted_by upstream (see SORTING "
            "entry), and the same execution-path gap applies.",
        ),
    },
    "athena": {
        _T.PARTITIONING: _none(
            "athena_ddl_generator:preview_incomplete_and_unconsumed",
            "Even the dry-run generator (AthenaDDLGenerator(TrinoDDLGenerator), trino.py:343-444) does "
            "not emit a real PARTITIONED BY clause: generate_create_table_ddl only appends a comment "
            "placeholder ('-- Note: PARTITIONED BY clause should be added with column types', "
            "trino.py:409-413) when partitioned_by is present. Real execution "
            "(benchbox/platforms/athena.py's AthenaAdapter) never calls AthenaDDLGenerator at all: "
            "create_schema (athena.py:627-695) rewrites the statement via _convert_to_external_table "
            "(athena.py:697-801), an independent regex-based CREATE EXTERNAL TABLE builder that never "
            "adds PARTITIONED BY and strips any WITH clause. AthenaAdapter.generate_tuning_clause "
            "(athena.py:1380-1399) has no call site anywhere in the codebase. apply_table_tunings "
            "(athena.py:1401-1415) logs 'applied at table creation time', which is not accurate -- "
            "nothing is applied. Renderer-migration follow-up: fix the dry-run generator's placeholder "
            "comment and wire real rendering into _convert_to_external_table.",
        ),
        _T.DISTRIBUTION: _none(
            "athena_ddl_generator:preview_incomplete_and_unconsumed",
            "The inherited generator computes bucketed_by/bucket_count from tuned distribution columns, "
            "but AthenaDDLGenerator's own generate_create_table_ddl explicitly excludes them from the "
            "emitted TBLPROPERTIES (the remaining_props filter, trino.py:433-437) -- silently dropped "
            "even in dry-run preview. Real execution never renders it either; see PARTITIONING entry.",
        ),
        _T.SORTING: _none(
            "athena_ddl_generator:preview_incomplete_and_unconsumed",
            "Same silent-drop gap as DISTRIBUTION: sorted_by is computed by the inherited generator from "
            "tuned sorting columns but excluded from Athena's TBLPROPERTIES output, and never rendered "
            "at execution either.",
        ),
        _T.CLUSTERING: _none(
            "athena_ddl_generator:preview_incomplete_and_unconsumed",
            "Athena has no separate clustering clause; folded into sorted_by upstream, which is dropped "
            "(see SORTING entry).",
        ),
    },
    "firebolt": {
        _T.DISTRIBUTION: _none(
            "firebolt_ddl_generator:preview_only",
            "core.tuning.generators.firebolt.FireboltDDLGenerator computes a real PRIMARY INDEX "
            "(col1, col2) clause from tuned distribution columns for dry-run preview "
            "(firebolt.py:144-149, 195-196), but benchbox/platforms/firebolt.py's FireboltAdapter never "
            "consumes it: create_schema uses _create_schema_with_tuning (primary/foreign-key toggle "
            "only) then _optimize_table_definition (firebolt.py:1267-1296, type-mapping/"
            "constraint-stripping only). FireboltAdapter.generate_tuning_clause (firebolt.py:1374-1411) "
            "has no call site anywhere in the codebase. apply_table_tunings (firebolt.py:1413-1421) only "
            "logs via log_partition_tunings(...).",
        ),
        _T.PARTITIONING: _none(
            "firebolt_ddl_generator:preview_only",
            "Same gap as DISTRIBUTION: the generator computes a real PARTITION BY clause from tuned "
            "partitioning columns (firebolt.py:151-156, 198-199) for dry-run preview only; execution "
            "never renders it.",
        ),
        _T.SORTING: _none(
            "firebolt_ddl_generator:log_only",
            "Firebolt sorts within segments automatically; the generator only info-logs sorting hints "
            "(firebolt.py:126-133) instead of computing a clause, even for dry-run preview.",
        ),
        _T.CLUSTERING: _none(
            "firebolt_ddl_generator:log_only",
            "Clustering is achieved through PRIMARY INDEX in Firebolt; the generator only info-logs "
            "clustering hints (firebolt.py:135-142) instead of computing a clause, even for dry-run "
            "preview.",
        ),
    },
    "azure-synapse": {
        _T.DISTRIBUTION: _none(
            "engine_default_not_tuned",
            "benchbox/platforms/azure_synapse.py's real _optimize_table_definition "
            "(azure_synapse.py:1046-1069, called at actual schema-creation time) does add a real "
            "WITH (DISTRIBUTION = ...) clause, but the value always comes from self.distribution_default "
            "(a platform/CLI option defaulted to ROUND_ROBIN, azure_synapse.py:117), never from "
            "TableTuning.distribution columns. The generator "
            "(core.tuning.generators.azure_synapse.AzureSynapseDDLGenerator) computes a real tuned "
            "HASH([col]) clause from those columns for dry-run preview only (azure_synapse.py:192-199, "
            "249-251); AzureSynapseAdapter.generate_tuning_clause (azure_synapse.py:1196-1228), which "
            "would correctly emit it, has no call site anywhere in the codebase. Same "
            "engine-mandatory-baseline-not-tuned pattern as StarRocks' DISTRIBUTION entry above: real "
            "DDL is emitted, but it is never derived from the tuned configuration.",
        ),
        _T.PARTITIONING: _none(
            "azure_synapse_ddl_generator:preview_only",
            "The generator computes a real (if structurally incomplete -- the RANGE RIGHT FOR VALUES () "
            "boundary list is always empty) PARTITION clause from tuned columns for dry-run preview "
            "(azure_synapse.py:201-209, 254-255), but real execution's _optimize_table_definition "
            "(azure_synapse.py:1046-1069) never adds a PARTITION clause at all.",
        ),
        _T.SORTING: _none(
            "azure_synapse_ddl_generator:log_only",
            "Azure Synapse sorting is handled by the index type; the generator only info-logs sorting "
            "hints (azure_synapse.py:173-181) instead of computing a clause, even for dry-run preview.",
        ),
        _T.CLUSTERING: _none(
            "azure_synapse_ddl_generator:log_only",
            "Clustering is achieved via DISTRIBUTION and CLUSTERED INDEX; the generator only info-logs "
            "clustering hints (azure_synapse.py:183-189) instead of computing a clause, even for dry-run "
            "preview.",
        ),
    },
    "timescaledb": {
        _T.PARTITIONING: _none(
            "timescaledb_hypertable_hardcoded_time_column",
            "core.tuning.generators.timescaledb.TimescaleDBDDLGenerator computes a real "
            "SELECT create_hypertable(...) post_create_statement using the first tuned PARTITIONING "
            "column as the time column (timescaledb.py:109-143) for dry-run preview only. Real execution "
            "(benchbox/platforms/timescaledb.py's TimescaleDBAdapter._convert_to_hypertables, "
            "timescaledb.py:378-447) ignores TableTuning entirely: it only converts tables that have a "
            "column literally named 'time' (information_schema lookup, timescaledb.py:459-467) and always "
            "passes the literal string 'time' to create_hypertable(), never the configured tuning column. "
            "TPC-H/TPC-DS benchmark schemas have no column literally named 'time', so this path does not "
            "fire for BenchBox's benchmarks today. TimescaleDBAdapter does not override "
            "apply_table_tunings/generate_tuning_clause, so it inherits PostgreSQLAdapter's unconditional "
            "no-ops (postgresql.py:894-903).",
        ),
        _T.SORTING: _none(
            "timescaledb_compression_hardcoded_segmentby",
            "The generator computes a real timescaledb.compress_orderby setting from tuned SORTING "
            "columns (timescaledb.py:189-196), gated on platform_opts.enable_compression, for dry-run "
            "preview only. Real execution's compression policy (TimescaleDBAdapter._add_compression_"
            "policy, timescaledb.py:476-521) never sets compress_orderby from any tuning source.",
        ),
        _T.DISTRIBUTION: _none(
            "timescaledb_compression_hardcoded_segmentby",
            "The generator computes real space-partitioning columns and a compress_segmentby setting "
            "from tuned DISTRIBUTION columns (timescaledb.py:131-141, 177-186) for dry-run preview only. "
            "Real execution's compression policy hardcodes compress_segmentby='' (empty, "
            "timescaledb.py:476-521), ignoring any configured distribution columns.",
        ),
        _T.CLUSTERING: _none(
            "timescaledb_compression_hardcoded_segmentby",
            "Merged with DISTRIBUTION into compress_segmentby by the generator (timescaledb.py:177-186); "
            "same real-execution gap -- compress_segmentby is hardcoded empty regardless of tuning.",
        ),
    },
    "questdb": {
        _T.PARTITIONING: _none(
            "questdb_ddl_generator:preview_only_separate_hardcoded_map",
            "core.tuning.generators.questdb.QuestDBDDLGenerator computes a real timestamp(col) + "
            "PARTITION BY suffix from the first tuned PARTITIONING column (questdb.py:154-170) for "
            "dry-run preview, falling back to its own module-level TPCH_DESIGNATED_TIMESTAMP/"
            "TPCH_PARTITION_BY dicts (questdb.py:49-64, 171-182) when no tuning is configured. Real "
            "execution (benchbox/platforms/questdb.py's QuestDBAdapter._apply_questdb_schema_"
            "enhancements, questdb.py:521-558) never reads TableTuning at all -- it applies timestamp/"
            "PARTITION BY using its own separate, adapter-local hardcoded TPCH_TIMESTAMP_COLUMNS/"
            "TPCH_PARTITION_DEFAULTS dicts (questdb.py:67-103), keyed by table name. For BenchBox's "
            "TPC-H defaults the two hardcoded maps happen to agree (lineitem/orders, MONTH), but any "
            "custom tuned PARTITIONING configuration is silently ignored by real execution. QuestDBAdapter "
            "defines no generate_tuning_clause/apply_table_tunings override at all.",
        ),
        _T.SORTING: _none(
            "questdb_ddl_generator:log_only",
            "QuestDB sorts by its designated timestamp automatically; the generator only info-logs "
            "sorting hints (questdb.py:185-191) instead of computing a clause, even for dry-run preview.",
        ),
        _T.DISTRIBUTION: _none(
            "questdb_ddl_generator:not_applicable_single_node",
            "QuestDB is single-node; the generator only warning-logs distribution hints and ignores the "
            "columns (questdb.py:193-199) instead of computing a clause, even for dry-run preview.",
        ),
    },
    "pg-duckdb": {
        _T.PARTITIONING: _none(
            "pg_duckdb_inherited_postgresql_noop",
            "core.tuning.generators.pg_duckdb.PgDuckDBDDLGenerator delegates to "
            "PostgreSQLDDLGenerator.generate_tuning_clauses (pg_duckdb.py:81), which computes a real "
            "PARTITION BY RANGE/LIST/HASH clause from tuned columns (postgresql.py:130-139) for dry-run "
            "preview. benchbox/platforms/pg_duckdb.py's PgDuckDBAdapter defines no create_schema/"
            "apply_table_tunings/generate_tuning_clause override at all -- it inherits PostgreSQLAdapter's "
            'verbatim, and PostgreSQLAdapter.generate_tuning_clause unconditionally returns "" while '
            "apply_table_tunings is a no-op (postgresql.py:894-902) regardless of input, so neither "
            "PostgreSQL nor pg_duckdb renders PARTITION BY at execution time. NOTE: this appears to also "
            "affect this registry's existing 'postgresql' entry, which describes PARTITIONING/CLUSTERING "
            "as rendered via 'adapter_mixin:PostgreSQLAdapter.generate_tuning_clause' -- that claim could "
            "not be corroborated by a repo-wide call-site search either. Auditing/correcting the existing "
            "postgresql entry is out of this TODO's scope (scope_limit is the 9 newly-covered platforms); "
            "flagged here, not fixed.",
        ),
        _T.CLUSTERING: _none(
            "pg_duckdb_inherited_postgresql_noop",
            "PgDuckDBDDLGenerator deliberately filters CLUSTER out of the inherited post_create_statements "
            "(pg_duckdb.py:83-88, DuckDB's vectorized engine bypasses index-based scan ordering) for "
            "dry-run preview, but the point is moot at execution time: see PARTITIONING entry -- "
            "PgDuckDBAdapter never runs any post_create_statements via the inherited no-op "
            "apply_table_tunings/generate_tuning_clause path.",
        ),
        _T.SORTING: _none(
            "pg_duckdb_inherited_postgresql_noop",
            "PostgreSQLDDLGenerator treats SORTING as CLUSTERING -- a shared code path (postgresql.py:"
            "141-159) appends both a CREATE INDEX and a CLUSTER post_create_statement for either tuning "
            "type. PgDuckDBDDLGenerator's inherited generate_tuning_clauses runs that same path before its "
            "filter (pg_duckdb.py:83-88) strips only the CLUSTER statement by prefix match, so a tuned "
            "SORTING config's CREATE INDEX still surfaces in dry-run preview, same as CLUSTERING. Same "
            "execution-time no-op as CLUSTERING/PARTITIONING regardless: PgDuckDBAdapter never runs "
            "post_create_statements via the inherited no-op apply_table_tunings/generate_tuning_clause "
            "path.",
        ),
    },
    "pg-mooncake": {
        _T.PARTITIONING: _none(
            "columnstore_manages_own_layout",
            "core.tuning.generators.pg_mooncake.PgMooncakeDDLGenerator.generate_tuning_clauses always "
            "returns an empty TuningClauses() regardless of input (pg_mooncake.py:61-81) -- by design, "
            "since Parquet/Iceberg columnstore tables manage their own storage layout. Consistent (not "
            "divergent) with the adapter: benchbox/platforms/pg_mooncake.py's PgMooncakeAdapter.supports_"
            "tuning_type unconditionally returns False for every tuning type (pg_mooncake.py:544-546), and "
            "_transform_create_statement is a deliberate passthrough that leaves the heap-table DDL "
            "unchanged for the bulk COPY load path (pg_mooncake.py:196-204) -- tuning is promoted away "
            "entirely once mooncake.create_table mirrors the loaded heap table.",
        ),
        _T.CLUSTERING: _none(
            "columnstore_manages_own_layout",
            "Same as PARTITIONING: the generator always returns empty clauses, and "
            "supports_tuning_type() is unconditionally False.",
        ),
        _T.SORTING: _none(
            "columnstore_manages_own_layout",
            "Same as PARTITIONING: the generator always returns empty clauses, and "
            "supports_tuning_type() is unconditionally False.",
        ),
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


def resolve_platform_key(platform: str) -> str:
    """Normalize a platform identifier to its canonical registry key.

    Applies the same case-folding, underscore-to-hyphen normalization, and
    `PLATFORM_ALIASES` lookup that `get_capability` uses to resolve a
    platform string to the key `PLATFORM_TUNING_CAPABILITIES` is keyed by.
    Exposed standalone (rather than inlined only in `get_capability`) so
    callers -- including tests that need to check "does this identifier
    resolve to a registry entry" without also needing a `TuningType` -- reuse
    the exact resolution logic instead of re-deriving an approximation of it
    (see `tests/unit/core/tuning/test_capability_source_drift.py`, which used
    to hand-roll a partial version of this normalization and missed aliases
    like "synapse" that aren't simple underscore/hyphen variants of their
    canonical key).

    Note this does not guarantee the returned key has a registry entry --
    callers that need that should check membership in
    `known_registry_platforms()` (or `PLATFORM_TUNING_CAPABILITIES`) too.
    """
    platform_key = platform.lower().replace("_", "-")
    return PLATFORM_ALIASES.get(platform_key, platform_key)


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
    platform_key = resolve_platform_key(platform)
    entries = PLATFORM_TUNING_CAPABILITIES.get(platform_key)
    if entries is None:
        return None
    return entries.get(tuning_type)


def known_registry_platforms() -> frozenset[str]:
    """All canonical platform keys with at least one registry entry (broader than interface.py's set)."""
    return frozenset(PLATFORM_TUNING_CAPABILITIES)


# Platforms whose logical-workload-tuning-candidate mapping
# (`benchbox.core.tuning.platform_capabilities.map_candidate_to_platform`) is
# implemented. Derived here (rather than redeclared in that module) so the
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
    "resolve_platform_key",
]
