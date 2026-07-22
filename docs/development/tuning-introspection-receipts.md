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
   `mismatch`, none `unverifiable`.

Any failure, timeout, empty ledger, or single non-corroborated statement
leaves the run at `applied_unverified` with a receipt recording why. The
introspection step must never fail or materially slow a run.

## Statement classes (per phase x mechanism)

`corroborate()` classifies each **executed** ledger statement and applies a
per-class rule. Classification is by generic SQL shape so the core stays
platform-agnostic; the per-platform catalog *reads* live in the
`Introspector` implementations.

| Ledger statement (shape)                     | phase          | class         | corroboration rule                                                                 | drives verification? |
| -------------------------------------------- | -------------- | ------------- | ---------------------------------------------------------------------------------- | -------------------- |
| `CREATE INDEX [IF NOT EXISTS] n ON T (cols)` | ddl/post_load  | `index`       | a catalog `index` fact on `T` whose columns equal `cols` (order- and case-normal)  | yes                  |
| `CREATE TABLE ... ORDER BY (cols)`           | ddl/post_load  | `sort_key`    | a catalog `sort_key` fact on `T` whose columns equal `cols`                         | yes                  |
| `CREATE TABLE ... PARTITION BY (cols)`       | ddl/post_load  | `partition_key` | a catalog `partition_key` fact on `T` whose columns equal `cols`                 | yes                  |
| `SET ...`, `PRAGMA ...`                       | any            | `transient`   | session/config, no persistent catalog footprint -- noted, **non-blocking**         | no                   |
| `OPTIMIZE TABLE ...` / maintenance           | ddl/post_load  | `maintenance` | merge/compaction op, no distinct catalog footprint -- noted, **non-blocking**      | no                   |
| session-phase statement (any)                | session        | `transient`   | transient SET -- noted, **non-blocking** (documented default below)                | no                   |
| anything else                                | ddl/post_load  | `unverifiable`| no corroboration rule -- **blocks** the upgrade (conservative: stay unverified)    | n/a (blocks)         |

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

## Per-platform catalog reads (Introspector)

Each platform's `Introspector.introspect(connection, ledger) -> IntrospectedState`
returns structured catalog facts (`kind`, `table`, `columns`, `name`,
`evidence`), bounded to the tables the ledger touched and wrapped
non-fatal. **No screen-scraping of engine DDL text** where a structured
catalog exists.

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

- **ClickHouse** (`benchbox/platforms/clickhouse/introspection.py`): reads
  `system.tables` (`name` / `sorting_key` / `partition_key` -- structured
  comma-separated key expressions), filtered to `currentDatabase()` and the
  ledger's tables. Returns `sort_key` / `partition_key` facts as receipt
  **evidence**.

  Limitation (documented, follow-up): ClickHouse applies `ORDER BY` /
  `PARTITION BY` at `CREATE TABLE` time in the *schema* phase, which is not
  wrapped by the tuning recording connection, so those column-bearing DDLs
  never enter the applied ledger. The ledger's ClickHouse tuning entries are
  `OPTIMIZE TABLE` (maintenance, `non-blocking`) and session SETs. The
  introspector therefore surfaces the physical keys as evidence but does
  **not** mint `applied_verified` from a MergeTree table's always-present
  `sorting_key` (that would be a trivially-true, unearned upgrade). Making
  ClickHouse verification-eligible requires routing the schema `ORDER BY` /
  `PARTITION BY` DDL through a recording connection -- out of scope here.

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
