---
title: "What we built on top of SQLGlot (and why transpilation isn't enough)"
series: building-benchbox
post_number: 11
type: architecture-design
tags: [benchbox, sqlglot, sql, transpilation, dialects, dataframe, architecture, datafusion, clickhouse, questdb]
meta_description: "BenchBox runs benchmarks on 42 SQL platforms using SQLGlot for transpilation. Here are the seven categories of SQL infrastructure we still had to build on top."
status: draft
---

# What we built on top of SQLGlot (and why transpilation isn't enough)

> A query can transpile cleanly and still fail at table creation, engine planning, or result validation. This post catalogs the layer BenchBox built around SQLGlot to close that gap.

**TL;DR**: SQLGlot does the cross-dialect translation heavy lifting BenchBox depends on across 42 SQL platforms and 9 DataFrame engines. Production portability still required seven extra layers: dialect normalization, post-generation fixups, engine-semantic rewrites, DDL rules, query overrides, registry governance, and a SQL-to-DataFrame facade.

---

## Introduction

BenchBox's promise is "one benchmark, every engine." We run TPC-H, TPC-DS, ClickBench, SSB, H2O, NYC Taxi, and a dozen other benchmark specs across:

- **42 SQL platforms**: embedded engines (DuckDB, SQLite, DataFusion), open-source servers (Postgres, ClickHouse, Doris, StarRocks, QuestDB, SingleStore, Firebolt), cloud warehouses (Snowflake, Databricks, BigQuery, Redshift, Synapse, Fabric), and Spark-flavored runtimes (Trino, Athena, EMR, Dataproc, LakeSail).
- **9 DataFrame engines**: Polars, Pandas, DataFusion-Python, PySpark, Dask, Modin, cuDF, Databricks-DF, LakeSail-DF.

Multiplied out, that is thousands of (query, dialect) combinations per release.

That promise is built on cross-dialect SQL translation, and SQLGlot[^1] is the standard tool for the job. We use it on every release.

The Fivetran team's recent mypyc compilation work[^2] reports roughly 5x parser, 2.5x generator, and 2x optimizer speedups while keeping the pure-Python path intact. We have not rigorously measured SQLGlot's share of our runtime budget, so we treat the speedups as an opportunity rather than a quantified need. Without SQLGlot, BenchBox would not exist as a multi-platform tool.

The Fivetran post closes with: "It has never been faster or easier to translate between different SQL dialects so that you can use different query engines." The first half is unambiguously true. The second half is where our experience adds nuance. Running the same benchmark on different engines is *partly* about transpilation, and *partly* about everything else. This post is what "everything else" looked like for us.

## How we got here

We did not set out to build SQL infrastructure. Each layer below got added because the previous one left an observable gap.

**Layer 1: `sqlglot.transpile()` directly.** Handles the bulk of common translation work: joins, CTEs, window functions, most aggregates, basic types, identifier quoting, `LIMIT` to `TOP N`, `EXTRACT` to `DATE_PART`, dialect function renames. The standard cases are by far the largest population of cases.

**Layer 2: A centralized wrapper** at `benchbox/utils/dialect_utils.py`. Once we hit the second post-generation fixup, we centralized. This layer normalizes five dialects with no SQLGlot entry to their nearest peer (mostly `postgres`) and applies three generic post-generation fixups.

**Layer 3: Per-platform query transformers.** For platform-specific quirks: a ClickHouse transformer for case folding and division safety, a dedicated QuestDB rewriter for syntax gaps, a DataFusion transformer for engine-semantic rewrites.

**Layer 4: `benchbox/sql_compat/` registry.** When the per-platform code grew structure of its own: `ddl_optimize/` for DDL across 19 platforms, `query_source/` for hand-written variants, `query_adapter/` for post-translation rewrites, `schema_emit/` for DDL emission, `benchmark_gate/` for platform-by-benchmark blocks, plus an `inventory.py` and `registry.py` for governance.

We did not design this in advance. It accreted: each new layer existed because the previous one couldn't carry the load.

## The seven categories of "everything else"

### 1. Dialect normalization

Public dialect counts are a coarse signal. The Fivetran post puts SQLGlot at "34 different SQL dialects"[^2]; SQLGlot's current GitHub README[^1] says "31 different dialects." Both numbers are accurate as counts of parser/generator pairs. Neither directly answers "which engines can I ship to."

Our list includes Netezza, Greenplum, Vertica, DataFusion, plus a "raw ANSI" target, none of which have native SQLGlot dialect entries. We map them to the nearest peer (`postgres`) in `dialect_utils.py`. The "N dialects" headline is best read as "N parser/generator pairs," not "N production engines you can ship to."

### 2. Post-generation fixups

SQLGlot emits standard SQL. Sometimes the standard form fails on the target engine. We carry three fixes that affect everyday TPC-H and TPC-DS expressions:

| Fix | What SQLGlot emits | What the engine accepts | Affects |
|-----|---------------------|--------------------------|---------|
| `_restore_group_order_by_all_keyword` | `GROUP BY "ALL"` (quoted) | `GROUP BY ALL` (keyword) | DuckDB |
| `_fix_sqlite_unsupported_syntax` | `DATE + INTERVAL '5' DAY`, `EXTRACT(part FROM date)` | `DATE(..., '+5 days')`, `STRFTIME(...)` | SQLite |
| `fix_postgres_date_arithmetic` | `d_date + 5` | `d_date + INTERVAL '5' DAY` | Postgres, DataFusion |

None of these are exotic. They round-trip the AST cleanly; they just fail at the engine.

### 3. Per-platform query transformers

Three platforms required dedicated modules.

**ClickHouse** (`platforms/clickhouse/query_transformer.py`) handles three concerns:

- Case folding for unquoted identifiers.
- DECIMAL division-by-zero NULL wrapping.
- Subquery aliasing for TPC-DS Q23 and Q87.

The Q23/Q87 case is worth telling. We wrote an AST visitor to inject `AS _sqN` on every unaliased subquery, but it corrupted Q23 (pulled `GROUP BY` out of a subquery) and Q87 (injected aliases inside `EXCEPT/INTERSECT`). The fix that shipped was a session setting, `joined_subquery_requires_alias=0`. The lesson: even with full AST control, the safer move was to abandon the rewrite and use the session setting the engine already exposed.

**QuestDB** (`platforms/questdb_rewriter.py`) is a dedicated post-AST rewriter for four constructs the SQLGlot dialect entry does not fully cover:

- Implicit comma joins, converted to explicit `INNER JOIN ... ON`.
- `INTERVAL` arithmetic, converted to `dateadd('d', n, ts)`.
- `SUBSTRING(s FROM p FOR l)`, converted to `substring(s, p, l)`.
- CTE column-alias lists, stripped.

QuestDB has a SQLGlot dialect entry; the dialect entry does not cover what QuestDB 9.3.4 actually accepts. Without our rewriter, every TPC-H, TPC-DS, and SSB query fails before the first row.

**DataFusion** is its own category, and it is the most expensive one we have.

### 4. Engine-semantic gaps (the silent ones)

This is the category we worry about most. SQLGlot transpiles cleanly. The SQL executes. The results are wrong.

DataFusion has a SQLGlot dialect entry. We observed that SQLGlot translates four TPC-H queries into syntactically valid DataFusion SQL that the engine runs to completion and returns the wrong answer for. These observations are pinned to the BenchBox `uv.lock` resolved version of the `datafusion` Python package (53.0.0); upstream planner work may resolve any of them in later releases.

| TPC-H query | Issue (observed on DataFusion Python 53.0.0) | Our rewrite |
|--------------|-------|-------------|
| Q11 | HAVING with scalar subquery: planner miscomputes the threshold | Hoist threshold into a CTE, filter with WHERE |
| Q16 | NOT IN with NULLs: SQL three-valued logic not honored | Rewrite to NOT EXISTS |
| Q18 | IN inside HAVING: decorrelation bug returns extra rows | Rewrite to EXISTS wrapper |
| Q20 | Nested correlated IN: incorrect join cardinality | Extract to CTEs with explicit joins |

Critical framing: these are engine planner semantics, not SQLGlot bugs. But the user-visible failure mode is "I transpiled and got wrong results." A syntactic transpiler structurally cannot catch this; the SQL is well-formed in both dialects, the bug lives in the engine's planner. We discovered ours by validating BenchBox results against TPC-H reference answers.

You could push back: if SQLGlot's pitch is portability across engines, isn't shipping rewrite recipes for known engine bugs within scope? It is a fair argument. We do not adopt it because we think SQLGlot's job is dialect-correct emission, and an engine-bug registry is a different artifact: it could live alongside SQLGlot, in a sidecar project, or in project-specific layers like ours. We would happily contribute to such an artifact if one emerges.

### 5. DDL semantics, across 19 platforms

SQLGlot is a *query* transpiler. DDL is correctly out of scope. But running a benchmark on a new platform requires creating tables, and that means engine-specific physical design. We maintain DDL rewrite modules under `sql_compat/rules/ddl_optimize/` for: ClickHouse, Databend, Databricks, Doris, Fabric DW, Firebolt, LakeSail, pg_mooncake, PostgreSQL/CedarDB, Presto, QuestDB, Redshift, SingleStore, Snowflake, Spark, StarRocks, Synapse, Trino, and Velox. Examples:

| Platform | Required DDL transformation | If you skip it |
|----------|------------------------------|----------------|
| ClickHouse | Strip `Nullable NOT NULL`; inject `ENGINE=MergeTree() ORDER BY (...)` | Table creation fails |
| Doris | `TIME` to `VARCHAR(8)`; `STRING` to `VARCHAR(65533)`; `ARRAY[N]` to `ARRAY`; inject `DUPLICATE KEY` and `DISTRIBUTED BY HASH` | Type, key, or distribution errors |
| SingleStore | Strip FK; `CREATE REFERENCE TABLE` for dimensions; inject `SHARD KEY` and `SORT KEY` (in order) | Error 2752, or terrible distribution |
| Databricks | `CREATE OR REPLACE TABLE ... USING DELTA TBLPROPERTIES(...)` | Idempotency fails on re-run |
| pg_mooncake | Append `USING columnstore` | Silent fallback to row-store heap |

This is the half of cross-engine portability that gets least attention and matters most operationally.

### 6. Hand-written query overrides

When SQLGlot's emitter produces SQL the engine refuses, we ship hand-written variants. The clearest example is H2O Q9 (`PERCENTILE_CONT WITHIN GROUP`):

```python
# benchbox/sql_compat/rules/query_source/h2odb_variants.py
CLICKHOUSE_Q9_SQL = "...uses ClickHouse quantile()..."
STARROCKS_Q9_SQL  = "...uses PERCENTILE_APPROX()..."
MYSQL_Q9_SQL      = "...verbatim ANSI WITHIN GROUP, bypasses SQLGlot..."
```

`PERCENTILE_CONT WITHIN GROUP` is not exotic; it is a SQL standard ordered-set aggregate. SQLGlot's MySQL/SingleStore output adds a multi-expression `WITHIN GROUP ORDER BY (CASE ... ELSE NULL END)` decorator that SingleStore's parser rejects. We bypass SQLGlot for that single query. Same pattern in `nyctaxi_variants.py`, `coffeeshop_variants.py`, `tpcdi_variants.py`, `vector_search_variants.py`.

### 7. SQL to DataFrame translation

Alongside the SQL platforms, BenchBox targets 9 DataFrame engines: Polars, Pandas, DataFusion-Python, PySpark, Dask, Modin, cuDF, Databricks-DF, LakeSail-DF. SQLGlot translates SQL into more SQL; targeting a DataFrame API is a different problem.

Our `platforms/dataframe/unified_frame.py` is a SQL-shaped facade over per-engine DataFrame APIs (about 4,200 lines, the largest single file in our cross-platform layer), with bespoke parsing of DataFusion's expression AST for aggregate arithmetic. Polars' own SQL frontend was tried and removed earlier ("fundamental limitations" in our notes). This is not a SQLGlot gap; it is the boundary of what a SQL transpiler is for.

## What we learned

**1. "Supported dialects" is a one-bit signal that needs more bits.** Public dialect counts (31 in SQLGlot's README, 34 in the Fivetran post) are accurate as parser/generator pair counts but less useful as maturity signals.

In our experience, Postgres support is the most reliable dialect we exercise; the Doris generator emits `VARCHAR` to `STRING` in a way that breaks key columns. A per-dialect maturity matrix (A-grade tested, best effort, parser-only) would be valuable for production users. Our standing position on upstreaming: test cases for dialects we exercise heavily, plus bug fixes in dialect generators where we have isolated reproductions.

**2. Engine-semantic bugs are the most dangerous category.** The DataFusion rewrites are not in any "transpilation correctness" failure list because the transpilation is correct. The user-visible failure mode is "I transpiled and got wrong results." A community-maintained registry of "this query shape produces wrong results on engine X version >= Y," with rewrite recipes, would help every team that hits these.

**3. DDL is half the work, and it is structurally outside SQLGlot's scope.** Engine-specific physical design (engines, sort keys, shard keys, table formats) is too tied to deployment to live in a transpiler. But any team using SQLGlot for cross-engine deployment should budget separately for DDL infrastructure.

**4. AST rewriting is sometimes less safe than session settings.** Our ClickHouse Q23/Q87 alias-injection rewrite *had* full AST control. It still corrupted real queries. The fix that shipped was a session setting. Real query corpora exercise constructs the grammar allows but nobody writes by hand; when the engine offers a knob, prefer it.

**5. We use SQLGlot every day and would not replace it.** The investments above exist *because* SQLGlot handles the 80% nobody wants to write. Without it, BenchBox would have one platform's queries.

## Try it yourself

The easiest way to see what each layer does is `--dry-run`:

```bash
$ benchbox run --platform duckdb --benchmark tpch --queries Q1 --dry-run preview/duckdb
$ benchbox run --platform clickhouse --benchmark tpch --queries Q1 --dry-run preview/ch
$ benchbox run --platform datafusion --benchmark tpch --queries Q1 --dry-run preview/df
```

Diff the three to see what each layer added. The compatibility inventory is queryable:

```bash
$ uv run -- python -m benchbox.sql_compat.inventory
```

Source code pointers:

- `benchbox/utils/dialect_utils.py` (centralized wrapper)
- `benchbox/platforms/datafusion_query_transformer.py` (engine-semantic rewrites)
- `benchbox/platforms/questdb_rewriter.py` (post-AST syntax rewrites)
- `benchbox/platforms/clickhouse/query_transformer.py` (case folding, division safety)
- `benchbox/sql_compat/rules/ddl_optimize/` (19 DDL rewrite modules)
- `benchbox/sql_compat/rules/query_source/h2odb_variants.py` (hand-written overrides)
- `benchbox/platforms/dataframe/unified_frame.py` (SQL-shaped DataFrame facade)

We would love to hear about gaps you have hit in your own SQLGlot-based projects. Open an issue on the BenchBox repo; chances are we have either a workaround or a similar war story to compare notes on.

---

## Test environment

- SQLGlot pinned `>=20.0.0,<31.0.0` in `pyproject.toml`; resolved to 30.6.0 in `uv.lock` at time of writing
- DataFusion Python `>=50.1.0` in `pyproject.toml`; resolved to 53.0.0 in `uv.lock` at time of writing. The Q11/Q16/Q18/Q20 rewrites in this post are pinned to that resolved version.
- ClickHouse Cloud and self-hosted 25.x
- QuestDB 9.3.4
- Doris 2.1.x

The 19 DDL rewrite modules under `benchbox/sql_compat/rules/ddl_optimize/` and the dialect coverage gap (five dialects with no SQLGlot entry, normalized by `dialect_utils.normalize_dialect_for_sqlglot`) are verifiable in the listed paths. The DataFusion silent-corruption queries (Q11, Q16, Q18, Q20) are documented in `datafusion_query_transformer.py` with the rewrite recipes inline.

## Limitations

- This post catalogs *what we built*, not the full set of SQLGlot gaps a different project might hit. Workloads with heavy DDL automation, ETL with stored procedure translation, or live query rewriting against a SaaS warehouse will produce a different list.
- The "categories" framing is post-hoc; the code grew organically.
- Engine versions matter. The DataFusion rewrites above are verified against `datafusion` Python 53.0.0 from the BenchBox lockfile. Some silent-corruption cases may resolve in later DataFusion planner releases, at which point a rewrite becomes a candidate for retirement: we run the rewrite-bypass version against TPC-H reference answers, and remove the rule only if validation passes. Retirement is opt-in.

---

## References

[^1]: [SQLGlot project repository](https://github.com/tobymao/sqlglot), accessed May 2026.

[^2]: Evangelos Danias, ["How we accelerated transpilation by compiling SQLGlot with mypyc"](https://www.fivetran.com/blog/how-we-accelerated-transpilation-by-compiling-sqlglot-with-mypyc), Fivetran blog, 2026-05-01.

*Questions or feedback? [Open an issue](https://github.com/joeharris76/BenchBox/issues) or join the discussion.*
