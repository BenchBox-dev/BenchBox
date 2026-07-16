# ADR-3: Baseline Definition and the Single Tuning-DDL Renderer

## Status

Accepted, 2026-07-12. Decided by Joe.

## Date

2026-07-12

## Context

This is the decision gate for TODO `tuning-adr-baseline-definition-and-renderer-20260712`,
drawn from the 2026-07-12 tuning-system deep review (evidence pinned to commit
`acfb8992`; findings C5, R2, R3).

### `notuning` is not a baseline today

"notuning" is supposed to mean platform defaults plus whatever an engine
mandates for a working schema. In practice two platforms attach behavior to
the *absence* of tuning, or unconditionally, rather than to the tuned path:

- **ClickHouse inverts the pack.** `benchbox/platforms/clickhouse/tuning.py:74-100`
  applies an aggressive OLAP session pack — `join_algorithm=grace_hash`,
  `grace_hash_join_initial_buckets=8`, `optimize_aggregation_in_order=1`,
  `group_by_two_level_threshold=100000`, and 50%-of-memory spill thresholds
  for external group-by/sort — **only when `self.tuning_enabled` is
  `False`**. A user who explicitly asks for tuning gets none of this; a user
  who explicitly asks for no tuning gets a curated performance profile. The
  label and the behavior are backwards.
- **StarRocks injects unconditionally.** `benchbox/platforms/starrocks/workload.py:214-221`
  appends `DISTRIBUTED BY HASH(`col`) BUCKETS 8` to every `CREATE TABLE` that
  doesn't already declare a distribution clause, in every tuning mode. This is
  schema-shape physical layout the engine requires to have a working table,
  not an optimization choice — but nothing in bundle metadata currently
  labels it as engine-mandatory versus a tuning decision.

The same review also found that session-level `SET` statements (the
ClickHouse pack above, and equivalent StarRocks query settings) are not
recorded in the tuning bundle in any mode today — there is no ledger entry a
later run or an auditor can compare against.

### Three parallel rendering universes

Tuning DDL is rendered by three independent code paths that do not share
logic and can drift silently:

- `benchbox/core/tuning/generators/*` (one module per platform family,
  reachable through `benchbox/core/tuning/ddl_generator.py:get_ddl_generator`).
  This path is exercised by exactly one caller today: the dry-run preview
  (`benchbox/core/dryrun.py:1066-1091`).
- `SparkDDLGeneratorMixin.generate_tuning_clauses`
  (`benchbox/platforms/base/cloud_spark/mixins.py:290-322`), used by the
  cloud Spark/Onehouse execution path (`benchbox/platforms/onehouse/quanton_adapter.py`).
  It returns the same `TuningClauses` dataclass as `core/tuning/generators/*`
  (imported for the type only, at the fallback branch on line 320) but builds
  it independently through its own `_generate_delta_tuning` /
  `_generate_iceberg_tuning` / `_generate_hudi_tuning` /
  `_generate_parquet_tuning` / `_generate_hive_tuning` methods rather than
  consuming the generators module's per-format logic — it is a third
  renderer, not an existing generators caller, and needs its own
  migration/equivalence pass during consolidation, not just deletion of the
  dead `generate_tuning_clause` methods below.
- Per-adapter `generate_tuning_clause` mixin methods (singular — one clause
  string, not the generators' `TuningClauses` object), implemented
  independently on ~20 adapters (ClickHouse, Databricks, Redshift, BigQuery,
  Snowflake, Trino, Spark, DuckDB, Firebolt, Azure Synapse, Athena, Presto,
  and others). This is the path that touches real database connections
  during execution for those (non-Spark) platforms.

Because dry-run preview renders through `generators/*` and execution renders
through the adapter mixins, a preview can show DDL that the real run never
issues. Some adapter implementations are dead: `ClickHouse.generate_tuning_clause`
(`benchbox/platforms/clickhouse/tuning.py:354`) has zero production callers —
`rg -n "\.generate_tuning_clause\(" benchbox --include=*.py` (excluding the
`def` lines) returns nothing; it is exercised only by unit tests that call
the adapter method directly.

### Linked open question

The blocked TODO `databricks-liquid-clustering-tuning-review-20260526` has
two open questions (DBR-compatibility hard-error vs. warning; manual-mode
`liquid_clustering_columns` over 4 keys) that are instances of the same
policy axis this ADR settles: when does an engine-specific tuning constraint
block a run outright, versus warn and proceed? See Consequences.

## Decision

1. **Baseline definition.** `notuning` means platform defaults plus
   engine-mandatory schema choices only — nothing else. Curated
   session-optimization packs (e.g. the ClickHouse OLAP pack at
   `benchbox/platforms/clickhouse/tuning.py:74-100`) move to the tuned path,
   or to an explicitly recorded harness-defaults block if they must apply
   regardless of tuning mode; they must never apply silently only when
   tuning is disabled. Engine-mandatory physical layout that a working table
   requires (e.g. StarRocks `DISTRIBUTED BY HASH` injection at
   `benchbox/platforms/starrocks/workload.py:214-221`) is permitted in
   baseline, but must be labeled as engine-mandatory in bundle metadata so it
   is never mistaken for an applied tuning. Session-level `SET` statements
   are recorded in the bundle in every mode, not only when tuning is
   enabled. This settles the warn-vs-fail direction for the
   `databricks-liquid-clustering-tuning-review-20260526` open questions:
   compatibility checks warn first; a run is blocked only for explicit,
   named unsafe combinations, not by default.

2. **Single renderer.** `core/tuning/generators/*` becomes the single
   tuning-DDL renderer. Adapter mixins are migrated to consume the
   generators rather than maintaining independent `generate_tuning_clause`
   implementations, so dry-run preview and real execution call the same
   rendering function and cannot drift. Renderers with zero production
   callers (e.g. `ClickHouse.generate_tuning_clause`) are deleted during
   consolidation rather than migrated. Migration proceeds per platform, each
   with a before/after DDL snapshot test proving the adapter-mixin output and
   the generator output are equivalent prior to cutover.

## Consequences

- `tuning-renderer-consolidation-and-baseline-policy-20260712` implements
  decision 2 (and the labeling/recording half of decision 1): one capability
  registry, per-platform migration to the generators with before/after DDL
  snapshot tests, and deletion of dead renderers such as
  `ClickHouse.generate_tuning_clause`.
- `tuning-applied-ledger-and-validation-status-20260712` implements the
  recording half of decision 1: session-level `SET` statements (ClickHouse
  OLAP pack, StarRocks query settings) get bundle ledger entries in every
  mode, and `validation_status` stops certifying only that a metadata-table
  `INSERT` succeeded.
- `databricks-liquid-clustering-tuning-review-20260526` (blocked, w3's open
  question on DBR-compatibility hard-error vs. warning) is unblocked on this
  axis: warn-first, block only for explicit unsafe runtimes. Its second open
  question (hard-fail for explicit `>4` manual `liquid_clustering_columns`)
  already matches this ADR's "block only explicit unsafe combinations"
  direction and stands unchanged. Annotated directly on the TODO via
  `resolved_with`.
- The ClickHouse OLAP session pack and any similar per-platform pack must be
  re-homed (tuned path or harness-defaults block) as part of the renderer
  consolidation work, not left in place with a comment.

## Rejected Options

1. **Keep session packs where they are, add recording only.** Record the
   ClickHouse pack's `SET` statements in the bundle ledger but leave them
   firing only when tuning is disabled. Rejected: this fixes the
   observability gap (a reader now knows what ran) but not the semantic bug
   (baseline still promises "no tuning" while shipping a curated OLAP
   profile). "notuning" would remain a false label with better paperwork.
2. **Consolidate into adapter mixins instead of generators.** Make each
   adapter's `generate_tuning_clause` the source of truth and have dry-run
   preview call adapter instances instead of the standalone generators.
   Rejected: dry-run preview needs to render DDL without a live connection
   or fully constructed adapter instance, which the generators already
   support and most adapter mixins do not; a capability registry keyed by
   platform type is also cleaner to build against a stateless generator
   interface than against ~20 adapter classes with mixed constructor
   requirements. Generators additionally already cover more platforms
   (17 modules) than adapters currently delegate to.
