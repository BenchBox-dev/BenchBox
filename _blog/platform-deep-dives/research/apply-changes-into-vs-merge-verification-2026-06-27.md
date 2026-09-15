# APPLY CHANGES INTO (AUTO CDC) vs Standard SQL MERGE: Claim Verification

> Evidence log for the platform-deep-dive post comparing Databricks' declarative
> CDC (AUTO CDC, formerly APPLY CHANGES INTO) to portable hand-written SQL for
> SCD Type 2 dimension maintenance. Every claim in the draft must trace to a
> dated entry here. BenchBox harness results and Databricks documentation/marketing
> claims are kept strictly separate.

## Objective

Test the marketing claim that Databricks' declarative CDC "replaces ~200 lines of
MERGE logic" with a few declarative lines, fairly and reproducibly: reconstruct the
real portable SQL it replaces, count it honestly, measure the portable form in
BenchBox, and characterize the declarative form accurately from primary Databricks
docs (we do not have a Databricks workspace to run an AUTO CDC pipeline, so the
declarative side is documentation-grounded and labeled as such, never presented as
a BenchBox harness result).

## Dates

- Documentation research access date: 2026-06-29 (all Databricks doc URLs below).
- BenchBox measurement runs: 2026-06-30.
- File named for the TODO creation date (2026-06-27); individual entries are dated
  when the check was actually run.

## Environment Snapshot (measurement runs)

- Timestamp (UTC): 2026-06-30T11:32:54Z
- OS: macOS 26.5 (25F71)
- Kernel: Darwin 25.5.0 (arm64)
- Device / chip: Apple M4, 10 cores (4 performance + 6 efficiency), 16 GB RAM
- Python: 3.12.11
- DuckDB: 1.3.2 (BenchBox-bundled driver)
- BenchBox: write_primitives SCD Type 2 operations (merged on `develop`)

---

## Part A: Databricks documentation claims (research, 2026-06-29)

All quotes are verbatim from the cited pages; the `docs.databricks.com/aws/en`
locale was used (AWS/Azure/GCP locales are content-identical). Three corrections
to the brief's starting assumptions are flagged inline, because they change how the
post must be worded.

### A1. The feature is now called AUTO CDC (APPLY CHANGES INTO renamed)

- Claim: AUTO CDC is the current API and replaces APPLY CHANGES with identical syntax.
- Source: https://docs.databricks.com/aws/en/ldp/cdc (accessed 2026-06-29)
- Quote: "The `AUTO CDC` APIs replace the `APPLY CHANGES` APIs and have the same syntax."
- Draft handling: use "AUTO CDC (formerly APPLY CHANGES INTO)" on first mention.

### A2. Current SQL grammar and an SCD Type 2 example

- Source: https://docs.databricks.com/aws/en/ldp/developer/ldp-sql-ref-apply-changes-into
  (page titled "AUTO CDC INTO (pipelines)") and https://docs.databricks.com/aws/en/ldp/cdc
  (accessed 2026-06-29)
- Verbatim SQL example (SCD Type 2):
  ```sql
  CREATE OR REFRESH STREAMING TABLE users_history;
  CREATE FLOW apply_cdc AS AUTO CDC INTO users_history
  FROM stream(main.cdc_tutorial.users_cdf)
  KEYS (userId)
  APPLY AS DELETE WHEN operation = "DELETE"
  SEQUENCE BY sequenceNum
  COLUMNS * EXCEPT (operation, sequenceNum)
  STORED AS SCD TYPE 2;
  ```
- This is the canonical "few declarative lines" form the marketing refers to.

### A3. Pipeline-context constraint, with a 2026 correction

- Claim (still true): the source must be a streaming source, and AUTO CDC runs on a
  Lakeflow declarative pipeline (Pro/Advanced or serverless edition), not as a
  one-shot DML statement against an ordinary Delta table.
  - Source: https://docs.databricks.com/aws/en/ldp/developer/ldp-sql-ref-apply-changes-into
  - Quote: "The source must be a streaming source. Use the STREAM keyword to use
    streaming semantics to read from the source." and "You must declare a target
    streaming table to apply the changes into."
  - Source: https://docs.databricks.com/aws/en/ldp/cdc
  - Quote: "To use the CDC APIs, your pipeline must be configured to use serverless
    SDP or the SDP `Pro` or `Advanced` editions."
- CORRECTION (do not claim "SQL-warehouse-forbidden"): standalone streaming tables
  can be created and refreshed from a Databricks SQL warehouse, with processing run
  on an auto-provisioned serverless pipeline.
  - Source: https://docs.databricks.com/aws/en/ldp/dbsql/streaming ("Use standalone
    streaming tables"), accessed 2026-06-29
  - Quotes: "You can create and refresh standalone streaming tables from a Databricks
    SQL warehouse, or from a notebook running on serverless general compute." and
    "These operations do not consume Databricks SQL warehouse compute. Instead,
    streaming tables rely on serverless pipelines for both creation and refresh. A
    dedicated serverless pipeline is automatically created and managed by the system
    for each streaming table."
  - Draft handling: state that AUTO CDC always executes on a (possibly
    auto-provisioned) serverless declarative pipeline, that you can now invoke it
    from a SQL warehouse via standalone streaming tables, but that it still runs only
    on Databricks/serverless pipelines, never on DuckDB, PostgreSQL, Snowflake,
    BigQuery, or ClickHouse, and is not a single standalone statement.
- COULD NOT VERIFY: no primary doc says AUTO CDC "cannot run in a SQL warehouse."
  That negative phrasing is avoided in the draft.

### A4. SCD Type 2 semantics AUTO CDC handles automatically

Source: https://docs.databricks.com/aws/en/ldp/developer/ldp-sql-ref-apply-changes-into,
https://docs.databricks.com/aws/en/ldp/cdc, and
https://docs.databricks.com/aws/en/ldp/what-is-change-data-capture (accessed 2026-06-29).

- Out-of-order events: "AUTO CDC automatically handles out-of-sequence records by
  processing events in the order defined by the sequencing column." `SEQUENCE BY` is required.
- Deletes: `APPLY AS DELETE WHEN <condition>`. `APPLY AS TRUNCATE` is SCD Type 1 only:
  "The `APPLY AS TRUNCATE WHEN` clause is supported only for SCD type 1. SCD type 2
  does not support the truncate operation."
- Column projection: `COLUMNS {columnList | * EXCEPT (exceptColumnList)}`.
- Record versioning: "SCD Type 2 preserves a complete history of changes by creating
  new rows for each version of a record, with `__START_AT` and `__END_AT` columns
  indicating when each version was active." The target schema must include
  `__START_AT` and `__END_AT`.

### A5. Naming history (DLT to Lakeflow)

- Source: https://docs.databricks.com/aws/en/ldp/concepts/where-is-dlt ("What happened
  to Delta Live Tables (DLT)?", last updated 2026-06-15), accessed 2026-06-29
- Quote: "The product formerly known as Delta Live Tables (DLT) has been updated to
  Lakeflow Spark Declarative Pipelines (SDP)."
- Supporting (Apache Spark contribution at Data + AI Summit, June 2025): DLT was
  contributed to Apache Spark and is available via `pyspark.pipelines` from Spark 4.1.
  Source: https://www.databricks.com/dataaisummit/session/build-data-pipelines-lakeflow-declarative-pipelines
- PARTIAL VERIFICATION: no single primary page dates the full DLT to Lakeflow
  Declarative Pipelines to Lakeflow Spark Declarative Pipelines chain; the June 2025
  date comes from the DAIS announcement, not a dated changelog. The draft states the
  chain conservatively and cites the "where-is-dlt" page for the current name.

### A6. The "~200 lines of MERGE" figure (official source, attributed carefully)

- Source: Databricks blog "Stop hand-coding change data capture pipelines",
  published 2026-04-22, https://www.databricks.com/blog/stop-hand-coding-change-data-capture-pipelines
  (accessed 2026-06-29)
- Official figure: "~6-10 lines of declarative pipeline definition" versus "40-200+
  lines of custom pipeline logic". This is the authoritative origin of the
  "200 lines" claim: it is a range (40-200+) for full custom pipeline logic, not a
  flat 200 for a basic Type 2.
- Customer testimonial (NOT an official metric): "I tried AutoCDC from Snapshots in
  Python and was amazed at how 4 lines of code could replace what I was doing in
  1,500 lines of code before." attributed to a "Senior Data Engineer, Fortune 500
  Aerospace & Defense Company." The 1,500-line figure is a customer quote and is
  labeled as such in the draft.
- Supporting prose: "Teams routinely hand-roll complex `MERGE` logic to handle
  updates, deletes, and late-arriving data: layering on staging tables, window
  functions, and sequencing assumptions that are difficult to reason about, and even
  harder to maintain as pipelines evolve."

### A7. Databricks removed the canonical SCD2 MERGE example from its MERGE docs

- Source: https://docs.databricks.com/aws/en/delta/merge (content-identical mirror
  https://learn.microsoft.com/en-us/azure/databricks/delta/merge, ms.date 2026-06-11),
  accessed 2026-06-29
- Quote (current SCD section in full): "Lakeflow Spark Declarative Pipelines has
  native support for tracking and applying SCD Type 1 and Type 2. Use `AUTO CDC ...
  INTO` with Lakeflow Spark Declarative Pipelines to ensure that out of order records
  are handled correctly when processing CDC feeds."
- Implication: the "equivalent hand-written MERGE" line count can no longer be pinned
  to one official Databricks code block; the draft reconstructs the portable form
  from the BenchBox operation and counts that, anchoring the official range to A6.

---

## Part B: Reconstructed portable SQL and honest line count (2026-06-30)

The portable SCD Type 2 workload is the BenchBox `merge_scd_type2_basic` operation
(merged on `develop`). The canonical two-statement form (close the current version,
then insert the new one) is what AUTO CDC's `STORED AS SCD TYPE 2` replaces.

Line counts derived from the registry (not hand-counted):

```
uv run -- python -c "from benchbox.core.write_primitives.catalog.loader import \
  load_write_primitives_catalog as L; c=L().operations; \
  print({k: c[k].write_sql.rstrip(chr(10)).count(chr(10))+1 for k in c if k.startswith('merge_scd_type2')})"
```

- `merge_scd_type2_basic`: 20 lines of SQL (close-old UPDATE + insert-new INSERT;
  includes a 2-line NOT EXISTS current-version guard added 2026-07-11 to make the
  insert idempotent on re-run - see scd2-basic-idempotency-and-cleanup-scoping)
- `merge_scd_type2_no_change`: 17 lines (idempotent re-run path)
- `merge_scd_type2_new_keys_only`: 7 lines (insert-only path)
- Each carries a 3-line cleanup statement.

The declarative AUTO CDC form for the same Type 2 result (A2) is about 6-7 lines.

Honest reading: for a basic Type 2 close-and-insert, the portable hand-written form
is roughly 20 lines, not 200. The official "40-200+ lines" range (A6) describes full
custom CDC pipeline logic that also handles out-of-order events, deletes, and
late-arriving data; AUTO CDC absorbs that hardening, and the BenchBox operation does
not implement it (it is a single-batch, ordered, portable workload by design). The
fair comparison is therefore: similar line counts for the basic happy path, with the
declarative form pulling ahead specifically on the hardening edge cases, at the cost
of running only inside Databricks/serverless pipelines.

## Part C: BenchBox measurements of the portable form (2026-06-30)

### C1. Why the operation API, not `benchbox run`

`benchbox run write_primitives --platform duckdb` currently skips the entire MERGE
category on DuckDB, because the 20 legacy MERGE operations use `MERGE INTO`, which
the bundled DuckDB 1.3.2 rejects (execution-filter rule
`benchbox/sql_compat/rules/execution_filter/duckdb_write_primitives.py`). The new
SCD Type 2 operations are categorized as MERGE but use portable UPDATE + INSERT, so
they run on DuckDB even though `MERGE INTO` does not. We therefore measure them
through the operation API (`WritePrimitives.execute_operation`), the same path the
integration tests use. (A follow-up to narrow that category skip so the portable ops
also run under `benchbox run` on DuckDB is tracked separately and is out of scope for
this post.)

This skip is itself a concrete illustration of the post's thesis: the portable form
runs on an engine that rejects `MERGE INTO` entirely.

### C2. Reproducible measurement script

Real TPC-H data via DuckDB's native `dbgen`, then the SCD2 operations via the
operation API. Full script:
`/private/tmp/.../scd2_measure.py` in the working session; the essential steps are:

```python
import duckdb
from benchbox import WritePrimitives
con = duckdb.connect(":memory:")
con.execute("INSTALL tpch; LOAD tpch; CALL dbgen(sf=0.01);")  # real TPC-H customer/orders/lineitem
wp = WritePrimitives(scale_factor=0.01, quiet=True)
wp.setup(con, force=True)                                      # seeds scd2_ops_dim_customer + change batch
for _ in range(30):
    wp.reset(con)                                             # restore dimension to seed state
    r = wp.execute_operation("merge_scd_type2_basic", con)   # write + validate + cleanup
    # r.write_duration_ms, r.validation_passed
```

### C3. Results

DuckDB 1.3.2, Apple M4, in-memory. Median of the per-operation write duration
reported by the harness (the write statements only, excluding setup/reset). The
change batch is fixed at 20 changed + 20 unchanged + 20 new business keys at every
scale factor by construction.

SF0.01 (dimension = 1,500 current rows; n = 30):

| Operation | median (ms) | min (ms) | p90 (ms) | validation |
| --- | --- | --- | --- | --- |
| merge_scd_type2_basic | 2.517 | 2.323 | 2.737 | passed |
| merge_scd_type2_no_change | 2.066 | 1.921 | 2.196 | passed |
| merge_scd_type2_new_keys_only | 1.208 | 1.111 | 1.685 | passed |

SF0.1 (dimension = 15,000 current rows, 10x larger; n = 15):

| Operation | median (ms) | min (ms) | p90 (ms) | validation |
| --- | --- | --- | --- | --- |
| merge_scd_type2_basic | 4.360 | 4.040 | 4.972 | passed |
| merge_scd_type2_no_change | 3.690 | 3.031 | 3.806 | passed |
| merge_scd_type2_new_keys_only | 1.462 | 1.312 | 2.437 | passed |

Observation: the dimension grew 10x (1,500 to 15,000 rows) but the basic operation
rose only about 1.7x (2.5 to 4.4 ms), because the work is bounded by the fixed
60-row change batch plus the dimension scans in the close-UPDATE predicate and the
one-current-per-key validation. The workload is change-batch-bound, not
dimension-size-bound, though not perfectly flat.

## Part D: Cross-check (draft claim to evidence)

- Draft claim: "AUTO CDC's SCD Type 2 example is about 6-7 declarative lines."
  - Evidence: A2 verbatim example.
- Draft claim: "The portable SQL it replaces, for a basic Type 2, is about 20 lines,
  not 200."
  - Evidence: Part B registry line count; A6 for the official 40-200+ range framing.
- Draft claim: "The '200 lines' figure is Databricks' own 40-200+ range for full
  custom pipeline logic; the 1,500-line figure is a customer quote."
  - Evidence: A6.
- Draft claim: "AUTO CDC runs only on Databricks/serverless pipelines (now invocable
  from a SQL warehouse via standalone streaming tables); the portable form runs
  unchanged on DuckDB and other engines."
  - Evidence: A3 (with correction); C1 (DuckDB runs the portable form while rejecting
    `MERGE INTO`).
- Draft claim: "The portable SCD2 operation runs, validates, and is repeatable on
  DuckDB; median basic-op write time ~2.5 ms at SF0.01 and ~4.4 ms at SF0.1."
  - Evidence: C3 (BenchBox harness result, DuckDB only, this machine).
- Draft claim: "AUTO CDC handles out-of-order events, deletes, and history
  automatically."
  - Evidence: A4.

## Limitations of this evidence

- No Databricks workspace was available, so no AUTO CDC pipeline was run. The
  declarative side is documentation-grounded only; no timing or cost figure for AUTO
  CDC is asserted anywhere in the draft.
- BenchBox numbers are single-machine (Apple M4), DuckDB-only, in-memory, and reflect
  the portable form measured through the operation API, not a multi-engine sweep.
- Line counts compare one concrete portable implementation (the BenchBox operation)
  to one documented declarative example; both are "basic Type 2" and exclude the
  production hardening that the 40-200+ range covers.
