---
title: "SCD Type 2: Declarative CDC vs Portable SQL MERGE"
meta_description: "We tested whether Databricks AUTO CDC really replaces ~200 lines of MERGE for SCD Type 2: honest line counts, portable SQL, BenchBox numbers, and lock-in."
tags: [databricks, delta-lake, scd-type-2, merge, cdc, write-primitives, benchmarking, portability]
status: draft
date: 2026-06-30
---

# SCD Type 2: Declarative CDC vs Portable SQL MERGE

> We reconstruct the portable SQL that Databricks' declarative CDC replaces, count it
> honestly, measure it in BenchBox, and weigh convenience against portability.

**TL;DR**: Databricks' AUTO CDC (formerly APPLY CHANGES INTO) genuinely removes
boilerplate and a class of Slowly Changing Dimension bugs, and that convenience is
real. But it runs only on Databricks declarative pipelines, while the equivalent
portable SQL runs unchanged across standard-DML engines such as DuckDB,
PostgreSQL, Snowflake, and BigQuery (verified here on DuckDB). For a basic Type 2,
that portable SQL is about 20 lines, not 200. The honest trade-off is convenience
versus portability, not lines of code.

---

## Introduction

A widely shared claim about Databricks' declarative change data capture (CDC) is that
it replaces "~200 lines of MERGE logic" with a few declarative lines that handle
inserts, updates, deletes, history, and record open and close automatically. Slowly
Changing Dimension (SCD) Type 2 maintenance (closing the current version of a changed
row and opening a new version, keyed on a business key) is the workload most often
cited.

We wanted to test that claim fairly rather than restate it. So we did four things:
reconstructed the real portable SQL the declarative form replaces, counted it
honestly, measured the portable form in BenchBox, and characterized the declarative
form from Databricks' primary documentation. We did not have a Databricks workspace
to run a declarative pipeline, so everything we say about the declarative side is
documentation-grounded and labeled as such. We never present it as a BenchBox
measurement. Every number and behavior claim here traces to a dated entry in our
verification log[^log].

Two axes matter for this comparison, and we try to be honest about both:
ergonomics and maintainability (lines of code, edge cases handled for you), and
portability and lock-in (which engines can run it at all).

## The two forms, side by side

### Declarative: AUTO CDC

The declarative form is concise. Databricks' own SCD Type 2 example reads[^cdc]:

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

That is two statements, eight lines as shown, with about six to seven lines of actual
CDC logic, and it is genuinely doing a lot (more on that below). A naming note: this
API was called APPLY CHANGES INTO and is now AUTO CDC,
with the same syntax[^cdc]. It is part of what Databricks now calls Lakeflow Spark
Declarative Pipelines, the product formerly known as Delta Live Tables[^dlt].

### Portable: MERGE / UPDATE plus INSERT

The portable form is the SCD Type 2 operation we added to BenchBox's Write Primitives
benchmark[^op]. SCD Type 2 produces two row events per changed business key: one
UPDATE to close the old version, one INSERT to open the new one. Most engines cannot
do both for the same matched key in a single MERGE statement, so the canonical idiom
is an UPDATE followed by an INSERT:

```sql
-- 1. Close the current version of each changed business key
UPDATE scd2_ops_dim_customer
SET is_current = false,
    valid_to = (SELECT MIN(s.effective_ts) FROM scd2_ops_stage_customer s
                WHERE s.c_custkey = scd2_ops_dim_customer.c_custkey AND s.change_type = 'changed')
WHERE scd2_ops_dim_customer.is_current = true
  AND EXISTS (SELECT 1 FROM scd2_ops_stage_customer s
              WHERE s.c_custkey = scd2_ops_dim_customer.c_custkey
                AND s.change_type = 'changed'
                AND s.row_hash <> scd2_ops_dim_customer.row_hash);

-- 2. Open a new current version for changed keys, and insert brand-new keys
INSERT INTO scd2_ops_dim_customer
SELECT (SELECT MAX(sk) FROM scd2_ops_dim_customer) + ROW_NUMBER() OVER (ORDER BY s.c_custkey),
       s.c_custkey, s.c_name, s.c_address, s.c_acctbal, s.c_mktsegment, s.row_hash,
       true, s.effective_ts, DATE '9999-12-31'
FROM scd2_ops_stage_customer s
WHERE (s.change_type = 'new'
       OR (s.change_type = 'changed'
           AND EXISTS (SELECT 1 FROM scd2_ops_dim_customer d
                       WHERE d.c_custkey = s.c_custkey AND d.is_current = false AND d.valid_to = s.effective_ts)))
  AND NOT EXISTS (SELECT 1 FROM scd2_ops_dim_customer d2
                  WHERE d2.c_custkey = s.c_custkey AND d2.is_current = true);
```

This is portable standard SQL. It uses a business key (`c_custkey`), a current-version
flag (`is_current`), validity timestamps (`valid_from` and `valid_to`), and a
change-detection fingerprint (`row_hash`) to decide what changed. The close-and-insert
uses standard DML (UPDATE plus INSERT), so it runs unchanged on engines that support a
standard UPDATE: DuckDB (which we verify below), PostgreSQL, Snowflake, and BigQuery.
Two documented exceptions apply. DataFusion is marked unsupported for this exact
operation in BenchBox's Write Primitives catalog
(`platform_overrides: {"datafusion": null}`)[^op], so it is skipped. ClickHouse has no
standard UPDATE statement (row changes go through `ALTER TABLE ... UPDATE` mutations),
so only the insert-only path (`merge_scd_type2_new_keys_only`) is portable there; the
close-old step would need a mutation rewrite. Note the catalog currently marks only
DataFusion unsupported, so BenchBox does not yet special-case ClickHouse: a ClickHouse
run attempts the close-old ops (and errors on the UPDATE) rather than automatically
restricting to the insert-only path. The same standard-DML scoping applies to
the harness setup that seeds the dimension and change batch (it also uses string
concatenation and CAST), so the portability claim is about standard-DML engines end to
end, not just the operation.

### The honest line count

Here is where the "200 lines" claim deserves scrutiny. The portable basic Type 2 above
is 20 lines of SQL, measured from the registry, not hand-counted[^log] (two of those
lines are a `NOT EXISTS` guard that makes the insert idempotent on re-run). The
declarative form is about 6 to 7 lines. So the real ratio for a basic Type 2 is closer
to 3 to 1 than 11 to 1.

Where does "200" come from? It is Databricks' own figure, but it is a range and it is
about something larger. Their April 2026 post compares "~6-10 lines of declarative
pipeline definition" to "40-200+ lines of custom pipeline logic"[^blog]. That upper
bound describes full custom CDC pipeline logic, including the ordering, deduplication,
and late-data handling that a production pipeline needs, not a basic close-and-insert.
A separate "1,500 lines" figure that circulates is a named customer testimonial in the
same post, not an official Databricks metric[^blog]. Worth noting too: Databricks has
removed the full SCD Type 2 MERGE example from its own MERGE documentation and now
points readers to AUTO CDC[^merge], so the side-by-side line count can no longer be
sourced to one official code block.

## What the declarative form does for you

The convenience is real, and it is worth being specific about it. Beyond fewer lines,
AUTO CDC handles several things automatically that the portable form leaves to you[^scd]:

- Out-of-order events. `SEQUENCE BY` orders CDC events by a sequencing column, so late
  or reordered records still produce a correct history.
- Deletes. `APPLY AS DELETE WHEN <condition>` closes a record on a delete event.
- Column projection. `COLUMNS * EXCEPT (...)` keeps bookkeeping columns out of the
  tracked attributes.
- Record versioning. SCD Type 2 automatically maintains `__START_AT` and `__END_AT`
  columns for each version.

Our portable operation, by contrast, is a single ordered batch by design. It does not
reorder out-of-sequence events or process delete markers; if you needed those, you
would add window functions and extra predicates, and that is exactly the kind of code
that grows toward the 40-200+ range. This is the declarative form's genuine advantage:
it removes a class of SCD Type 2 bugs (incorrect ordering, missed record closing) that
hand-written logic has to handle explicitly.

## Portability and lock-in

The other axis is where the trade-off bites. AUTO CDC requires a streaming source and
runs on a Lakeflow declarative pipeline (the Pro, Advanced, or serverless edition)[^cdc].
As of 2026 you no longer have to hand-author a pipeline: you can create and refresh
standalone streaming tables from a Databricks SQL warehouse, and the system
auto-provisions a serverless pipeline to do the processing[^standalone]. That is a real
improvement in ergonomics. But the processing still happens on a Databricks serverless
pipeline, not on warehouse compute, and not on any other engine. It is not a standalone
statement you can run against an ordinary table, and it does not run on DuckDB,
PostgreSQL, Snowflake, BigQuery, or ClickHouse.

The portable form runs on the standard-DML engines in that list (ClickHouse, lacking a
standard UPDATE, needs the insert-only path or a mutation rewrite, as noted above). We
can show the portable form concretely on one engine. The bundled DuckDB 1.3.2 rejects
`MERGE INTO` outright, so BenchBox's standard run skips its
entire MERGE category on DuckDB[^skip]. Yet the portable SCD Type 2 operation, built
from UPDATE and INSERT rather than `MERGE INTO`, runs on DuckDB and passes its
correctness checks. The same SQL that an engine refuses in `MERGE INTO` form runs fine
in the portable form. That is the portability argument in miniature.

## What we measured

We measured the portable form only. We have no Databricks workspace, so we ran no AUTO
CDC pipeline and we claim no declarative timing or cost.

A methodology note on how we ran it. Because `benchbox run --platform duckdb` skips the
MERGE category on DuckDB (the legacy operations use `MERGE INTO`)[^skip], we exercised
the SCD Type 2 operation through BenchBox's operation API, the same path the integration
tests use. We loaded real TPC-H data with DuckDB's native `dbgen`, let BenchBox seed the
dimension and a mixed change batch (20 changed, 20 unchanged, 20 brand-new business
keys), then ran each operation with the dimension reset to its seed state between runs.

Results on DuckDB 1.3.2, Apple M4, in-memory. The numbers are the median per-operation
write time the harness reports, excluding setup and reset[^log].

At SF0.01 (dimension of 1,500 current rows, median of 30 runs):

| Operation | median (ms) | min (ms) | p90 (ms) | validation |
| --- | --- | --- | --- | --- |
| Basic (close old plus insert new) | 2.517 | 2.323 | 2.737 | passed |
| No change (idempotent re-run) | 2.066 | 1.921 | 2.196 | passed |
| New keys only (insert only) | 1.208 | 1.111 | 1.685 | passed |

At SF0.1 (dimension of 15,000 current rows, 10x larger, median of 15 runs):

| Operation | median (ms) | min (ms) | p90 (ms) | validation |
| --- | --- | --- | --- | --- |
| Basic (close old plus insert new) | 4.360 | 4.040 | 4.972 | passed |
| No change (idempotent re-run) | 3.690 | 3.031 | 3.806 | passed |
| New keys only (insert only) | 1.462 | 1.312 | 2.437 | passed |

One observation stands out. The dimension grew 10x, but the basic operation rose only
about 1.7x (2.5 ms to 4.4 ms). The workload is bounded by the fixed change batch plus
the dimension scans in the close predicate and the validation, so it is
change-batch-bound rather than dimension-size-bound. It is not perfectly flat, because
the larger dimension costs more to scan, but it is far from linear in dimension size.
These are single-machine, DuckDB-only numbers, and we present them as illustration of
the portable operation working and validating, not as a platform ranking.

## Convenience versus portability

So which form should you reach for? We will not give a verdict, because it genuinely
depends on the constraint you are optimizing for.

The declarative form is a strong fit when your stack is Databricks-centric, when you are
ingesting a streaming CDC feed with out-of-order events and deletes, and when removing
boilerplate and a class of SCD Type 2 bugs is worth more than running anywhere else. Six
declarative lines that handle ordering and record closing correctly are a real
maintainability win.

The portable form is a strong fit when portability is the point: benchmarking the same
workload across engines, running without a pipeline runtime, keeping full control of the
SQL, or running on an engine that does not support `MERGE INTO` at all. It is also the
only option when "the same operation, everywhere" is a hard requirement, which is exactly
why BenchBox models SCD Type 2 this way.

## Methodology and limitations

Anyone can reproduce the portable measurement. Load real TPC-H data with DuckDB's `dbgen`,
set up the Write Primitives benchmark, and run the operation:

```python
import duckdb
from benchbox import WritePrimitives

con = duckdb.connect(":memory:")
con.execute("INSTALL tpch; LOAD tpch; CALL dbgen(sf=0.01);")
wp = WritePrimitives(scale_factor=0.01, quiet=True)
wp.setup(con, force=True)
result = wp.execute_operation("merge_scd_type2_basic", con)
print(result.write_duration_ms, result.validation_passed)
```

Limitations we want to be clear about:

- No Databricks run. The declarative side is documentation-grounded only; we assert no
  AUTO CDC timing or cost.
- Single machine, DuckDB only, in-memory. The numbers illustrate the portable operation
  working, not a cross-engine comparison.
- Basic Type 2 only. Our line count compares one concrete portable implementation to one
  documented declarative example. Both are basic Type 2 and exclude the production
  hardening that the 40-200+ range covers.

## Conclusions

The "~200 lines of MERGE" framing is partly a strawman and partly fair. For a basic
Type 2 close-and-insert, the portable SQL is about 20 lines, not 200, so the headline
ratio is overstated. For a hardened production CDC pipeline that also handles ordering,
deletes, and late data, the 40-200+ range is Databricks' own figure and is reasonable,
and the declarative form absorbs that complexity for you.

The more useful way to read the comparison is convenience versus portability. AUTO CDC
buys you concise, correct-by-construction SCD Type 2 on Databricks. Portable SQL buys you
the same history-tracking workload on any standard-DML engine, including ones that reject
`MERGE INTO` (like DuckDB); engines without a standard UPDATE (such as ClickHouse) run
the insert-only path unchanged and need a mutation rewrite for the close-old step. Both
are legitimate choices; the right one depends on whether your constraint is
maintainability inside one platform or portability across many.

## Next steps

The portable operation lives in BenchBox's Write Primitives benchmark[^op], and the full
evidence behind every number here is in our verification log[^log]. We would love for
others to run the portable form on other standard-DML engines like PostgreSQL, Snowflake,
or BigQuery (and to try the insert-only path or a mutation rewrite on ClickHouse) and
compare. Open an issue to share results or to discuss the methodology.

---

## References

[^log]: Verification log for this post: `_blog/platform-deep-dives/research/apply-changes-into-vs-merge-verification-2026-06-27.md` (BenchBox repository). Contains the environment snapshot, source quotes, line counts, and measurement runs. Measurements run 2026-06-30; documentation accessed 2026-06-29.
[^cdc]: [Change data capture with AUTO CDC](https://docs.databricks.com/aws/en/ldp/cdc), Databricks documentation, accessed 2026-06-29. "The `AUTO CDC` APIs replace the `APPLY CHANGES` APIs and have the same syntax."
[^dlt]: [What happened to Delta Live Tables (DLT)?](https://docs.databricks.com/aws/en/ldp/concepts/where-is-dlt), Databricks documentation, last updated 2026-06-15, accessed 2026-06-29.
[^op]: Write Primitives SCD Type 2 operations (`merge_scd_type2_basic`, `merge_scd_type2_no_change`, `merge_scd_type2_new_keys_only`), BenchBox repository, `benchbox/core/write_primitives/catalog/operations.yaml`.
[^scd]: [AUTO CDC INTO (pipelines) SQL reference](https://docs.databricks.com/aws/en/ldp/developer/ldp-sql-ref-apply-changes-into) and [What is change data capture?](https://docs.databricks.com/aws/en/ldp/what-is-change-data-capture), Databricks documentation, accessed 2026-06-29.
[^blog]: [Stop hand-coding change data capture pipelines](https://www.databricks.com/blog/stop-hand-coding-change-data-capture-pipelines), Databricks blog, 2026-04-22, accessed 2026-06-29. Official figure: "~6-10 lines of declarative pipeline definition" versus "40-200+ lines of custom pipeline logic". The "1,500 lines" figure is a customer testimonial, not an official metric.
[^merge]: [Upsert into a Delta Lake table using merge](https://docs.databricks.com/aws/en/delta/merge), Databricks documentation, accessed 2026-06-29. The SCD section now points to AUTO CDC rather than a hand-written SCD Type 2 MERGE example.
[^standalone]: [Use standalone streaming tables](https://docs.databricks.com/aws/en/ldp/dbsql/streaming), Databricks documentation, accessed 2026-06-29. "You can create and refresh standalone streaming tables from a Databricks SQL warehouse... Instead, streaming tables rely on serverless pipelines for both creation and refresh."
[^skip]: DuckDB execution-filter rule for Write Primitives, BenchBox repository, `benchbox/sql_compat/rules/execution_filter/duckdb_write_primitives.py`. The MERGE category is skipped on DuckDB because the legacy operations use `MERGE INTO`, which the bundled DuckDB 1.3.2 rejects.

*Questions or feedback? Open an issue or join the discussion.*
