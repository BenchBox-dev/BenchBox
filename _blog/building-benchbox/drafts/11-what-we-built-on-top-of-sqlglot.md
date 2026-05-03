---
title: "What we built on top of SQLGlot (and why transpilation isn't enough)"
series: building-benchbox
post_number: 11
type: architecture-design
tags: [benchbox, sqlglot, sql, transpilation, dialects, dataframe, architecture, datafusion, clickhouse, questdb]
meta_description: "BenchBox runs benchmarks on 36 SQL platforms using SQLGlot for transpilation. Here are the seven categories of SQL infrastructure we still had to build on top."
status: draft
---

# What we built on top of SQLGlot (and why transpilation isn't enough)

> SQLGlot is the foundation, not the finished house. This post is the punchlist of what we still had to build.

**TL;DR**: BenchBox runs benchmarks across 36 SQL platforms. SQLGlot does the transpilation heavy lifting, and the recent mypyc work makes it dramatically faster, but real cross-engine portability needs about 2,500 lines of additional infrastructure on top: dialect normalization, post-generation fixups, engine-aware semantic rewrites, a 19-platform DDL rewrite registry, hand-written query overrides where translation cannot deliver, and a SQL-to-DataFrame layer that SQLGlot does not address. We catalog the seven categories of work with file paths and concrete examples.

---

## Introduction

BenchBox's promise is "one benchmark, every engine." We run TPC-H, TPC-DS, ClickBench, SSB, H2O, NYC Taxi, and a dozen other benchmark specs across 36 SQL platforms (DuckDB, Snowflake, Databricks, BigQuery, Redshift, ClickHouse, Trino, Athena, Doris, StarRocks, Postgres, MySQL, Vertica, SingleStore, QuestDB, DataFusion, Firebolt, Synapse, and many more) plus a fleet of DataFrame engines (Polars, Pandas, DataFusion-Python, PySpark, Dask, Modin, cuDF, LakeSail). Multiplied out, that is thousands of (query, dialect) combinations on every release.

That promise is built on cross-dialect SQL translation, and SQLGlot[^1] is the obvious tool for the job. We use it. We also discovered that the gap between "transpile cleanly" and "execute correctly with the right semantics" is wider than any transpiler can close on its own.

Last week the SQLGlot team at Fivetran shipped a milestone[^2]: they compiled SQLGlot's hot Python with mypyc and got a roughly 5x parser speedup, 2.5x generator speedup, and 2x optimizer speedup while keeping the pure-Python path intact as a fallback. For a project that translates tens of thousands of TPC-DS queries on every release, this is a meaningful improvement, and worth saying out loud. Our experience with SQLGlot is overwhelmingly positive; without it, BenchBox would not exist as a multi-platform tool.

The Fivetran post closes with: "It has never been faster or easier to translate between different SQL dialects so that you can use different query engines." The first half of that sentence is unambiguously true. The second half is where our experience can add nuance. Running the same benchmark on different query engines is *partly* about transpilation, and *partly* about everything else. This post is what "everything else" looked like for us.

## How we got here: starting simple, ending with a registry

We did not set out to build SQL infrastructure. We set out to call `sqlglot.transpile()` and let it handle the work. Each layer below got added because the previous layer left a real, observable gap.

**Layer 1: `sqlglot.transpile()` directly.** This handled the obvious 80%: joins, CTEs, window functions, most aggregates, basic types, identifier quoting, `LIMIT` to `TOP N` translation, `EXTRACT` to `DATE_PART` swaps, dialect function renames. Still does. We don't want to lose that framing as we list the gaps below; the easy cases are by far the largest population of cases, and SQLGlot makes them invisible.

**Layer 2: A centralized wrapper** at `benchbox/utils/dialect_utils.py`. Once we hit the second post-generation regex fixup, we centralized. Today this layer normalizes 8 dialects with no SQLGlot entry to their nearest peer (mostly `postgres`) and applies four generic post-generation fixups that affect multiple dialects.

**Layer 3: Per-platform query transformers.** When a single platform's quirks were too platform-specific for the wrapper, we extracted them: a ClickHouse transformer for case folding and division safety, a 450-line QuestDB rewriter for syntax gaps, a DataFusion transformer for engine-semantic query rewrites.

**Layer 4: A SQL compatibility registry** under `benchbox/sql_compat/`. When the per-platform code grew structure of its own, we built explicit rule families: `ddl_optimize/` for DDL semantics across 19 platforms, `query_source/` for hand-written platform-specific queries, `query_adapter/` for post-translation query rewrites, `schema_emit/` for schema generation rules, `benchmark_gate/` for platform-by-benchmark compatibility checks, plus an `inventory.py` and `registry.py` for governance.

We did not design this in advance. It accreted. Each new layer existed because the previous one couldn't carry the load, and that is what production-grade cross-engine work looks like once the easy cases are handled.

## The seven categories of "everything else"

### 1. Dialect normalization

SQLGlot's headline metric is "supports 34 SQL dialects." That is accurate as a count of parser/generator pairs. Our list of target platforms includes Netezza, Greenplum, Vertica, DataFusion, plus a "raw ANSI" target, none of which have native SQLGlot dialect entries. We map them to the nearest peer in `dialect_utils.py`:

```python
# benchbox/utils/dialect_utils.py
def normalize_dialect_for_sqlglot(dialect: str) -> str:
    # netezza, greenplum, vertica, datafusion, ansi, standard, ... -> postgres
```

This works fine in practice: Postgres is a workable approximation for most of them. But the gap is real. The "34 dialects" claim is best read as "34 parser/generator pairs," not "34 production engines you can ship to."

### 2. Post-generation fixups

SQLGlot emits standard SQL. Sometimes the standard form fails on the target engine. We carry four post-generation fixes that affect everyday TPC-H and TPC-DS expressions:

| Fix | What SQLGlot emits | What the engine accepts | Affects |
|-----|---------------------|--------------------------|---------|
| `_restore_group_order_by_all_keyword` | `GROUP BY "ALL"` (quoted) | `GROUP BY ALL` (keyword) | DuckDB |
| `_fix_sqlite_unsupported_syntax` | `DATE + INTERVAL '5' DAY`, `EXTRACT(part FROM date)` | `DATE(..., '+5 days')`, `STRFTIME(...)` | SQLite |
| `fix_postgres_date_arithmetic` | `d_date + 5` | `d_date + INTERVAL '5' DAY` | Postgres, DataFusion |

None of these are exotic. They round-trip the AST (Abstract Syntax Tree, the parsed expression tree SQLGlot operates on) cleanly, they just fail at the engine. Every one of them is something we hit in the first 10 queries of a standard benchmark spec.

### 3. Per-platform query transformers

Three platforms required dedicated transformer modules.

**ClickHouse** (`platforms/clickhouse/query_transformer.py`) handles:

- Case folding for unquoted identifiers (ClickHouse is case-sensitive for unquoted identifiers; SQLGlot does not fold by default)
- DECIMAL division-by-zero NULL wrapping
- Subquery aliasing for TPC-DS Q23 and Q87 (see story below)

The TPC-DS Q23 and Q87 case is worth telling. ClickHouse rejects derived tables without aliases, so we wrote an AST visitor that walks the parsed query and injects `AS _sqN` on every unaliased subquery. The visitor was correct in isolation. On real queries, it corrupted Q23 (it pulled the GROUP BY clause out of a subquery boundary) and Q87 (it injected aliases inside `EXCEPT/INTERSECT`, where they are not allowed). We disabled the rewriter and shipped a session setting instead (`joined_subquery_requires_alias=0`). The lesson, which we will return to, is that even with full AST control, the safe move was to abandon the rewrite and twist the engine knob.

**QuestDB** (`platforms/questdb_rewriter.py`, about 450 lines) is a post-AST rewriter for:

- Implicit comma joins, converted to explicit `INNER JOIN ... ON` (every TPC-H, TPC-DS, and SSB query, since the legacy specs use comma joins)
- `INTERVAL` arithmetic, converted to `dateadd('d', n, ts)` (TPC-H Q1, Q4, Q6, Q17, and others)
- `SUBSTRING(s FROM p FOR l)`, the SQL:1999 form, converted to `substring(s, p, l)`
- CTE column-alias lists (`WITH x (a, b) AS ...`), stripped down to `WITH x AS ...`

QuestDB has a SQLGlot dialect entry. The dialect entry does not cover what real QuestDB 9.3.4 actually accepts. Our rewriter is the bridge. Without it, every TPC-H, TPC-DS, and SSB query fails before the first row is read.

**DataFusion** is its own category, and it is the most expensive one we have.

### 4. Engine-semantic gaps (the silent ones)

This is the category we worry about most. SQLGlot transpiles cleanly. The SQL executes. The results are wrong.

DataFusion has a SQLGlot dialect entry. SQLGlot translates four TPC-H queries into syntactically valid DataFusion SQL that the engine runs to completion and returns the wrong answer for:

| TPC-H query | Issue | Our rewrite |
|--------------|-------|-------------|
| Q11 | HAVING with a scalar subquery: planner miscomputes the threshold | Hoist threshold into a CTE, filter with WHERE |
| Q16 | NOT IN with NULLs: SQL three-valued logic not honored | Rewrite to NOT EXISTS |
| Q18 | IN inside HAVING: decorrelation bug returns extra rows | Rewrite to EXISTS wrapper |
| Q20 | Nested correlated IN: incorrect join cardinality | Extract to CTEs with explicit joins |

Critical framing: these are engine planner semantics, not SQLGlot bugs in any strict sense. But the user-visible failure mode for someone using SQLGlot to run their workload across engines is "I transpiled and got wrong results." A syntactic transpiler structurally cannot catch this; the SQL is well-formed in both dialects, the bug lives in the target engine's planner. Someone has to know which query *shapes* trigger which engine bugs, and write a rewrite that produces the same answer through a different shape. Today, every team that hits these issues discovers them privately. We discovered ours by validating BenchBox results against TPC-H reference answers and watching four queries fail validation while running.

### 5. DDL semantics, across 19 platforms

SQLGlot is a *query* transpiler. DDL is correctly out of scope. But running a benchmark on a new platform requires creating tables, and creating tables means engine-specific physical design.

We maintain dedicated DDL rewrite modules under `sql_compat/rules/ddl_optimize/` for: ClickHouse, Databend, Databricks, Doris, Fabric DW, Firebolt, LakeSail, pg_mooncake, PostgreSQL/CedarDB, Presto, QuestDB, Redshift, SingleStore, Snowflake, Spark, StarRocks, Synapse, Trino, and Velox. A few representative examples:

| Platform | Required DDL transformation | If you skip it |
|----------|------------------------------|----------------|
| ClickHouse | Strip `Nullable NOT NULL`; inject `ENGINE=MergeTree() ORDER BY (...)` | Table creation fails |
| Doris | TIME to VARCHAR(8); STRING to VARCHAR(65533); ARRAY[N] to ARRAY; inject `DUPLICATE KEY` and `DISTRIBUTED BY HASH` | Type, key, or distribution errors |
| SingleStore | Strip FK; `CREATE REFERENCE TABLE` for dimensions; inject `SHARD KEY` and `SORT KEY`, in that order | Error 2752 (FK), or a terrible distribution layout |
| Databricks | `CREATE OR REPLACE TABLE ... USING DELTA TBLPROPERTIES(...)` | Idempotency fails on re-run |
| pg_mooncake | Append `USING columnstore` | Silent fallback to row-store heap (no error, just bad performance) |

This is the half of cross-engine portability that gets least attention and matters most operationally. It is also a category where we think SQLGlot is right to stay out: engine-specific physical design is too tied to deployment to live in a transpiler. But anyone reading "transpile SQL across engines" and assuming that means "deploy the same benchmark on both engines from one source" should budget separately for this work.

### 6. Hand-written query overrides

When SQLGlot's emitter produces SQL the engine refuses, we ship hand-written variants per engine. The clearest example is H2O Q9, which uses an ordered-set percentile aggregate:

```python
# benchbox/sql_compat/rules/query_source/h2odb_variants.py
CLICKHOUSE_Q9_SQL = "...uses ClickHouse quantile()..."
STARROCKS_Q9_SQL  = "...uses PERCENTILE_APPROX()..."
MYSQL_Q9_SQL      = "...verbatim ANSI WITHIN GROUP, bypasses SQLGlot..."
```

The MySQL/SingleStore case is the one to dwell on. `PERCENTILE_CONT WITHIN GROUP` is not exotic; it is a SQL standard ordered-set aggregate. SQLGlot's MySQL/SingleStore output adds a multi-expression `WITHIN GROUP ORDER BY (CASE WHEN ... THEN ... ELSE NULL END)` decorator that SingleStore's parser rejects. We bypass SQLGlot for that single query and ship the hand-written ANSI form directly.

This is a category, not a one-off. Every benchmark we ship has a few queries where the right answer is "do not transpile, hand-write." The same pattern shows up in `nyctaxi_variants.py`, `coffeeshop_variants.py`, `tpcdi_variants.py`, and `vector_search_variants.py`.

### 7. SQL to DataFrame translation

Half of BenchBox's targets are DataFrame engines: Polars, Pandas, DataFusion's Python frontend, PySpark, Dask, Modin, cuDF, LakeSail. SQLGlot does not address translating SQL into Polars expressions, which is a different problem from translating SQL into more SQL.

Our `platforms/dataframe/unified_frame.py` is about 2,200 lines of SQL-shaped facade over per-engine DataFrame APIs, with bespoke parsing of DataFusion's expression AST for aggregate arithmetic. Polars' own SQL frontend was tried and removed earlier in BenchBox's history; "fundamental limitations" is the note we left ourselves.

This is not a SQLGlot gap; it is the boundary of what a SQL transpiler is for. But it is worth flagging for anyone shopping for a "SQL portability layer." Transpilation only takes you to engines that speak SQL.

## What we learned

**1. "Supported dialects" is a one-bit signal that needs more bits.** SQLGlot's "34 dialects" is accurate as a count. It is less useful as a maturity signal. The Postgres support is rock-solid. The Doris support emits `VARCHAR` to `STRING` in a way that breaks key columns. A per-dialect maturity matrix (A-grade tested, best effort, parser-only) would be transformative for production users. We would happily contribute test cases for the dialects we exercise heavily.

**2. Engine-semantic bugs are the most dangerous category.** The DataFusion TPC-H rewrites are not in any "transpilation correctness" framework's failure list, because the transpilation is correct. The engine's planner is the proximate cause of the wrong answer. Yet the user-visible failure mode is "I transpiled and got wrong results." A community-maintained registry of "this query shape produces wrong results on engine X version >= Y," with rewrite recipes, would help every team that hits these. Today every team rediscovers them privately.

**3. DDL is half the work, and it is structurally outside SQLGlot's scope.** We do not think SQLGlot should solve DDL semantics; engine-specific physical design (engines, sort keys, shard keys, table formats, distribution policies) is too tied to deployment. But any team planning to use SQLGlot for cross-engine deployment should budget separately for DDL infrastructure. We have 19 platform-specific DDL rewrite modules. They are not going away.

**4. AST rewriting is sometimes less safe than session settings.** Our ClickHouse Q23 and Q87 alias-injection rewrite *had* full AST control. It still corrupted real queries (split GROUP BY out of subqueries; injected aliases inside `EXCEPT/INTERSECT`). The fix that shipped was a session setting. The lesson: an AST-correct transformation can still produce a semantically broken query, because real query corpora do things the grammar allows but nobody writes by hand. When the engine offers a knob, prefer it.

**5. We use SQLGlot every day and would not replace it.** Worth saying out loud. The investments above are not arguments against SQLGlot; they are the work that exists *because* SQLGlot handles the 80% nobody wants to write. Without SQLGlot, BenchBox would have one platform's queries.

## Try it yourself

The easiest way to see what each layer does is `--dry-run`, which writes the final, post-translation, post-rewrite SQL we would actually send to the engine without running it:

```bash
$ benchbox run --platform duckdb --benchmark tpch --queries Q1 --dry-run preview/duckdb
$ benchbox run --platform clickhouse --benchmark tpch --queries Q1 --dry-run preview/ch
$ benchbox run --platform datafusion --benchmark tpch --queries Q1 --dry-run preview/df
```

Diff the three output directories to see what each layer added. The compatibility inventory is also queryable:

```bash
$ uv run -- python -m benchbox.sql_compat.inventory
```

That emits a JSON report of every dialect-branching decision point in the BenchBox codebase, which is a useful starting point if you are evaluating a new platform.

Source code pointers:

- `benchbox/utils/dialect_utils.py` (centralized wrapper)
- `benchbox/platforms/datafusion_query_transformer.py` (engine-semantic rewrites)
- `benchbox/platforms/questdb_rewriter.py` (post-AST syntax rewrites)
- `benchbox/platforms/clickhouse/query_transformer.py` (case folding, division safety)
- `benchbox/sql_compat/rules/ddl_optimize/` (19 DDL rewrite modules)
- `benchbox/sql_compat/rules/query_source/h2odb_variants.py` (hand-written overrides)
- `benchbox/platforms/dataframe/unified_frame.py` (SQL-shaped DataFrame facade)

We would love to hear about gaps you have hit in your own SQLGlot-based projects. Open an issue on the BenchBox repo, we likely have either a workaround or a kindred scar.

---

## Test environment

The patterns described here are taken from the BenchBox codebase as of v0.2.1, with additional details verified against:

- SQLGlot main branch as of May 2026
- DataFusion versions current to the BenchBox v0.2.1 platform matrix
- ClickHouse Cloud and self-hosted 25.x
- QuestDB 9.3.4
- Doris 2.1.x

The line counts cited (450 lines for the QuestDB rewriter, 2,200 for `unified_frame.py`, 19 DDL rewrite modules) are file-level counts from `wc -l` on the listed paths. The dialect coverage gap (8 platforms with no SQLGlot entry) is from `dialect_utils.normalize_dialect_for_sqlglot`. The DataFusion silent-corruption queries (Q11, Q16, Q18, Q20) are documented in `datafusion_query_transformer.py` with the rewrite recipes.

## Limitations

- This post catalogs *what we built*, not the full set of SQLGlot gaps a different project might hit. Workloads with heavy DDL automation, ETL with stored procedure translation, or live query rewriting against a SaaS warehouse will have a different list.
- The "categories" framing is post-hoc; the code grew organically. A team starting today with the same platform list might land on a different decomposition.
- Engine versions matter. Some of the silent-corruption cases on DataFusion may resolve in future planner releases. We re-validate on each platform upgrade.

---

## References

[^1]: [SQLGlot project repository](https://github.com/tobymao/sqlglot), accessed May 2026.

[^2]: Evangelos Danias, ["How we accelerated transpilation by compiling SQLGlot with mypyc"](https://www.fivetran.com/blog/how-we-accelerated-transpilation-by-compiling-sqlglot-with-mypyc), Fivetran blog, 2026-05-01.

*Questions or feedback? [Open an issue](https://github.com/joeharris76/BenchBox/issues) or join the discussion.*
