# Post-load introspection receipts

Design note for TODO `tuning-introspection-receipts-20260716`. Builds on
the applied-tuning ledger (ADR-001,
`docs/development/tuning-adr-001-trust-and-hash-semantics.md`) and the
`benchbox.core.tuning.applied_ledger` module.

## Problem

The applied ledger records *what the execution path actually ran* and
derives `applied_unverified` when at least one tuning statement executed.
That is still self-attested: it certifies the statement did not raise, not
that the requested physical layout is present in the database. `ADR-001`
reserves `applied_verified` for a separate code path that corroborates the
ledger against the real catalog. This is that path.

## Trust rule (soundness)

`applied_verified` is claimable **only** via catalog corroboration, never
from the ledger alone (`AppliedTuningLedger.overall_status` never returns
it). Concretely, a run is upgraded `applied_unverified -> applied_verified`
iff:

1. introspection ran without error (bounded catalog reads, wrapped
   non-fatal); and
2. there is **at least one** catalog-backed (`verifiable`) executed
   ddl/post_load statement; and
3. **every** verifiable statement is `corroborated` -- none `absent`, none
   `mismatch`, none `unverifiable`; and
4. the ledger contains no failed ddl/post_load statement and no dropped
   tuning intent. Each physical failure receives a blocking `unverifiable`
   receipt entry with a code-authored failure reason, and dropped intents are
   copied into the receipt's additive `dropped` section. Raw driver detail
   remains in the ledger statement's `error` field, not the receipt reason.

Any introspection failure, timeout, or single non-corroborated statement keeps
an otherwise eligible run at `applied_unverified` with a receipt recording why.
An all-physical-failed ledger derives `failed` before corroboration, and an
empty ledger cannot earn the upgrade. The introspection step must never fail or
materially slow a run.

## Statement classes (per phase x mechanism)

`corroborate()` gates every ledger statement by recorded status and phase,
then classifies each **executed** statement and applies a
per-class rule. Classification is by generic SQL shape so the core stays
platform-agnostic; the per-platform catalog *reads* live in the
`Introspector` implementations.

| Ledger statement (shape)                     | phase          | class         | corroboration rule                                                                 | drives verification? |
| -------------------------------------------- | -------------- | ------------- | ---------------------------------------------------------------------------------- | -------------------- |
| `CREATE INDEX [IF NOT EXISTS] n ON T (cols)` | ddl/post_load  | `index`       | a catalog `index` fact on `T` whose columns equal `cols` (order- and case-normal)  | yes                  |
| `CREATE TABLE ... ORDER BY (cols)`           | ddl/post_load  | `sort_key`    | a catalog `sort_key` fact on `T` whose columns equal `cols`                         | yes                  |
| `CREATE TABLE ... PARTITION BY (cols)`       | ddl/post_load  | `partition_key` | a catalog `partition_key` fact on `T` whose columns equal `cols`                 | yes                  |
| `ALTER TABLE T CLUSTER BY (cols)`, `CREATE TABLE ... CLUSTER BY (cols)` | ddl/post_load | `cluster_key` | a catalog `cluster_key` fact on `T` whose columns equal `cols`, in order | yes |
| `SET ...`, `PRAGMA ...`                       | any            | `transient`   | session/config, no persistent catalog footprint -- noted, **non-blocking**         | no                   |
| `OPTIMIZE TABLE ...` / maintenance           | ddl/post_load  | `maintenance` | merge/compaction op, no distinct catalog footprint -- noted, **non-blocking**      | no                   |
| `ALTER TABLE T [RESUME/SUSPEND] RECLUSTER`   | ddl/post_load  | `maintenance` | reorganizes existing data; the clustering KEY is the catalog footprint -- **non-blocking** | no          |
| session-phase statement (any)                | session        | `transient`   | transient SET -- noted, **non-blocking** (documented default below)                | no                   |
| failed statement                             | ddl/post_load  | `unverifiable`| the requested physical change did not execute; failure reason is recorded -- **blocks** | n/a (blocks)     |
| failed statement                             | session        | `transient`   | transient session failure is noted but has no persistent catalog footprint -- **non-blocking** | no          |
| anything else                                | ddl/post_load  | `unverifiable`| no corroboration rule -- **blocks** the upgrade (conservative: stay unverified)    | n/a (blocks)         |

A `CREATE TABLE` carrying **both** an `ORDER BY` and a `PARTITION BY` (the
ClickHouse MergeTree shape) classifies as both `sort_key` and `partition_key`
and emits one receipt entry per clause, so each key must corroborate on its
own. Corroborating only the first clause would let a run reach
`applied_verified` while the other configured key never applied.

**Verdicts** (per statement): `corroborated`, `absent` (expected object not
in catalog), `mismatch` (object present, columns differ -- carries a short
diff), plus the non-blocking notes `transient` / `maintenance` and the
blocking `unverifiable`.

### Session SETs are corroboration-eligible? No (default).

Session `SET`/`PRAGMA` statements are transient: they configure the
connection, leave no catalog trace, and vanish when the session closes.
They are **noted** in the receipt (so the reader sees they ran) but do
**not** block verification and cannot, on their own, earn it. A run whose
only tuning is session SETs stays `applied_unverified` -- there is nothing
physical to corroborate. This matches the ledger's own physical-hash
intent (chronology of *layout* ops).

A failed session statement follows the same transient gate rule: it is
visible in the receipt but does not block a sibling physical statement that
the catalog corroborates. Conversely, session success cannot mask a run in
which every attempted ddl/post_load statement failed; that ledger derives
`failed`, not `applied_unverified`.

## Per-platform catalog reads (Introspector)

Each platform's `Introspector.introspect(connection, ledger) -> IntrospectedState`
returns structured catalog facts (`kind`, `table`, `columns`, `name`,
`evidence`), bounded to the tables the ledger touched and wrapped
non-fatal. **No screen-scraping of engine DDL text** where a structured
catalog exists. ClickHouse and Snowflake keep a hard catalog-row limit,
then filter the bounded result to table names extracted from every supported
ledger statement shape, including `ALTER TABLE`. Their `truncated` flag measures
the relevant rows after filtering, so an at-cap catalog full of unrelated tables
does not reject a complete target snapshot. A target omitted by the hard limit
still yields an `absent` verdict (and therefore cannot verify); a relevant result
that itself reaches the cap remains explicitly truncated.

- **DuckDB** (`benchbox/platforms/duckdb_introspection.py`): reads
  `duckdb_indexes()` -- the `table_name` / `index_name` / `expressions`
  columns (structured; `expressions` is the indexed-column list). One
  bounded query, filtered to the ledger's tables. Corroborates each
  `CREATE INDEX` ledger entry against its `index` row.

  Caveat (verified 2026-07-22, follow-up for the orchestrator): a DuckDB
  **SORTING** tuning renders to `CREATE INDEX idx_<t>_sort` *before* data
  load, but the loader's CTAS sorted ingestion then runs
  `CREATE OR REPLACE TABLE <t> AS SELECT * FROM <t> ORDER BY ...`, which
  **drops that index**. So at introspection time the sort index is absent
  and a sorting-only run honestly stays `applied_unverified` (the receipt
  records `absent`) -- a live demonstration of the "never verified without
  corroboration" invariant, not a bug in this module. The `CLUSTERING`
  branch of DuckDB's `apply_table_tunings` would produce a persisting index
  (CTAS only consumes SORTING columns), but DuckDB's config validation
  rejects the `clustering` tuning type, so that branch is currently
  unreachable. Corroboration -> `applied_verified` is exercised against a
  live DuckDB catalog where a recorded index persists (see
  `tests/unit/platforms/test_duckdb_introspection.py`). Making a full
  DuckDB *sorting* CLI run verification-eligible needs the sort layout
  recorded as a corroboratable footprint (e.g. recording the CTAS
  `ORDER BY`, or re-creating the index post-load) -- out of scope here.

- **Snowflake** (`benchbox/platforms/snowflake_introspection.py`): reads
  `INFORMATION_SCHEMA.TABLES.CLUSTERING_KEY` with bound, normalized schema
  parameters, then filters the structured rows to ledger tables. Both
  `LINEAR(A, B)` and `(A, B)` catalog forms normalize to the same exact,
  order-sensitive column tuple while the live catalog spelling remains
  unconfirmed.

  A matching catalog key certifies only that Snowflake accepted the clustering
  **key metadata**. It does not certify that existing micro-partitions have
  finished reclustering: `ALTER TABLE ... CLUSTER BY` updates metadata before
  asynchronous maintenance completes, and `RESUME RECLUSTER` remains a
  non-blocking maintenance statement. This is intentionally weaker than the
  ClickHouse receipt, whose CREATE-time sorting and partition keys describe the
  physical MergeTree layout. When a reused Snowflake table already has the
  requested key, the adapter skips both ALTER and RESUME and records the intent
  as dropped/already-present; that current run therefore stays fail-closed
  rather than claiming it physically applied the pre-existing layout.

- **ClickHouse** (`benchbox/platforms/clickhouse/introspection.py`): reads
  `system.tables` (`name` / `sorting_key` / `partition_key` -- structured
  comma-separated key expressions), filtered to `currentDatabase()` and the
  ledger's tables. Returns `sort_key` / `partition_key` facts as receipt
  **evidence**.

  Multi-column catalog keys may be returned as `(a, b)` or `tuple(a, b)`;
  receipt normalization removes exactly one balanced outer wrapper so those
  forms compare with the DDL intent `a, b`. Matching remains an exact,
  order-sensitive tuple comparison. Inner function-call parentheses are not
  stripped: for example, `f(a), b` remains distinct from `f(a, b)`.

  Expression spelling is deliberately not canonicalized. Verbatim expressions
  such as `toYYYYMM(ts)` corroborate, while ClickHouse rewrites such as
  `INTERVAL 1 DAY` to `toIntervalDay(1)` remain an honest fail-closed mismatch.
  Reimplementing ClickHouse's version-dependent expression canonicalizer here
  could over-certify a different expression.

  ClickHouse applies `ORDER BY` / `PARTITION BY` at `CREATE TABLE` time in the
  *schema* phase, which is not wrapped by the tuning recording connection, so
  `create_schema` records the executed statement onto the ledger itself
  (`_record_tuned_sort_key_op`, at `connection.execute` time so the
  order-sensitive `applied_ledger_hash` keeps true chronology). Only a table
  carrying a *tuned* clause is recorded: a MergeTree table's `sorting_key` is
  always present, so corroborating an untuned table's engine-mandatory
  `ORDER BY` would be a trivially-true, unearned upgrade. A table tuned with a
  partition key only is recorded too -- omitting it would leave an unapplied
  partition uncorroborated while a sibling table's sort key carried the run to
  `applied_verified`. The ledger's other ClickHouse entries stay
  `OPTIMIZE TABLE` (maintenance, `non-blocking`) and session SETs.

## Wiring

`run_enhanced_benchmark` (`benchbox/platforms/base/adapter.py`, after the
`overall_status` derivation ~line 984, connection still open): when the
derived status is `applied_unverified` and the adapter exposes an
introspector (`get_tuning_introspector()`), run introspection guarded,
corroborate, and upgrade to `applied_verified` iff the receipt corroborates.
The receipt rides inside the existing `.applied.json` companion
(`AppliedTuningLedger.to_payload(status=..., receipt=...)`) -- no new
companion file, no new plumbing through the CODEOWNERS-locked
`result_capture.py`. Anonymized exports scrub the receipt's free-text /
identifier fields exactly like the ledger statements.
