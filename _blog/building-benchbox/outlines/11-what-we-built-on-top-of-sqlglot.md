# What We Built on Top of SQLGlot (and Why Transpilation Isn't Enough)

> SQLGlot is the foundation, not the finished house. This post is the punchlist of what we still had to build.

**TL;DR**: BenchBox runs benchmarks across 36 SQL platforms. SQLGlot does the transpilation heavy lifting (and the recent mypyc work makes it dramatically faster), but real cross-engine portability needs ~2,500 lines of additional infrastructure: dialect normalization, post-generation fixups, engine-aware semantic rewrites, a 19-platform DDL rewrite registry, hand-written query overrides where translation can't deliver, and a SQL-to-DataFrame layer that SQLGlot doesn't address. We catalog the gaps with file paths and concrete examples.

---

## Metadata

```yaml
title: "What we built on top of SQLGlot (and why transpilation isn't enough)"
series: building-benchbox
post_number: 11
type: architecture-design
target_length: 2,200-2,800 words
tags: [benchbox, sqlglot, sql, transpilation, dialects, dataframe, architecture, datafusion, clickhouse, questdb]
```

---

## Framing

**Tone**: Genuinely complimentary about SQLGlot. The project is excellent and the recent mypyc work is the kind of under-the-radar engineering that benefits the whole ecosystem for years. Our findings are about what a transpiler structurally can't do, not about what SQLGlot does wrong.

**Anchor**: The Fivetran post (May 1, 2026) closes with "It has never been faster or easier to translate between different SQL dialects so that you can use different query engines." The first half is unambiguously true. The second half is where our experience adds nuance: running across engines is *partly* transpilation and *partly* everything else.

**Audience**: BenchBox users, SQL tooling builders, anyone evaluating SQLGlot for production cross-engine workloads. They want honest signal about where the line falls.

**Voice constraints to apply throughout draft**:
- "we" not "I"
- Hyphens only, never em-dashes or en-dashes (`,` and `-`)
- Neutral on platforms: DataFusion's HAVING/decorrelation issues are engine-semantic gaps that a syntactic transpiler can't catch, not vendor failings
- Frame our extras as "what's left to build" not "what SQLGlot fails at"

---

## Outline

### 1. The Problem: "Run the same benchmark on every engine" sounds simple (~300 words)

**Thesis**: BenchBox's promise is "one benchmark, every engine." That promise is built on cross-dialect SQL translation, and SQLGlot is the obvious tool for the job. We use it. We also discovered the gap between "transpile cleanly" and "execute correctly with the right semantics" is wider than any transpiler can close on its own.

**Concrete framing**:
- 36 SQL platforms (DuckDB, Snowflake, Databricks, BigQuery, Redshift, ClickHouse, Trino, Athena, Doris, StarRocks, Postgres, MySQL, Vertica, SingleStore, QuestDB, DataFusion, Firebolt, Synapse, ...) plus DataFrame engines (Polars, Pandas, DataFusion-Python, PySpark)
- 18+ benchmarks: TPC-H (22 queries), TPC-DS (99 queries), ClickBench (43), SSB (13), H2O, NYC Taxi, ...
- Multiplied out: thousands of (query, dialect) combinations on every release

**The Fivetran milestone**: A respectful nod. The mypyc work delivers ~5x parser, ~2.5x generator, and ~2x optimizer speedups while keeping pure-Python compatibility. For a project that translates tens of thousands of TPC-DS queries on every release, this is a meaningful improvement.

**The reframe**: SQLGlot's headline metric is "34 dialects supported." Our experience is that *parser/generator coverage* and *production-engine compatibility* are different problems. The first is what SQLGlot ships. The second is what we ship on top.

**Closing transition**: Here's what "on top" actually looks like.

---

### 2. What we tried: starting simple, ending with a registry (~400 words)

**Thesis**: We didn't set out to build SQL infrastructure. We set out to use `sqlglot.transpile()` and let it handle the work. Each layer below got added because the previous layer left a real, observable gap.

**Evolution** (chronological):

**Layer 1: `sqlglot.transpile()` directly**. This handled the obvious 80%, joins, CTEs, window functions, most aggregates, basic types, identifier quoting, `LIMIT` ↔ `TOP N`, `EXTRACT` ↔ `DATE_PART`, dialect function renames. Still does. We don't want to lose that framing.

**Layer 2: A centralized wrapper** (`benchbox/utils/dialect_utils.py`). Once we hit the second post-generation regex fixup, we centralized. Currently does:
- Maps 8 dialects with no SQLGlot entry (Netezza, Greenplum, Vertica, DataFusion, ANSI, Standard, ...) to their nearest peer (`postgres`, mostly)
- Fixes 4 generic post-generation issues that affect multiple dialects

**Layer 3: Per-platform query transformers**. When a single platform's quirks were too platform-specific for the wrapper, we extracted them:
- `clickhouse/query_transformer.py` (case folding, division safety, type casts)
- `questdb_rewriter.py` (450 lines of post-AST rewrites)
- `datafusion_query_transformer.py` (engine-semantic query rewrites)

**Layer 4: A SQL compatibility registry** (`benchbox/sql_compat/`). When the per-platform code grew structure, we built explicit rule families:
- `ddl_optimize/` for DDL semantics (19 platforms)
- `query_source/` for hand-written platform-specific queries
- `query_adapter/` for post-translation query rewrites
- `schema_emit/` for schema generation rules
- `benchmark_gate/` for platform x benchmark compatibility checks
- `inventory.py` and `registry.py` for governance

**Tone**: Honest about how it grew. "We didn't design this; it accreted." Each new layer existed because the previous one couldn't carry the load. That's not a SQLGlot failing; it's what production-grade cross-engine work looks like once the easy cases are handled.

---

### 3. What we built: seven categories of "everything else" (~800 words)

**Thesis**: Our SQL infrastructure breaks into seven categories. SQLGlot handles syntax. The categories below are the parts SQLGlot can't see (engine semantics, DDL physical design, ordered-set aggregates that emit valid-but-rejected SQL, etc.).

This is the post's center of gravity. Every category gets:
- One sentence on what SQLGlot does
- One sentence on what's left
- A concrete example with a file path and platforms affected
- (Where useful) a one-line code snippet

**Category 1: Dialect normalization**

8 of our target dialects have no SQLGlot entry. We map them to nearest peer.

```python
# benchbox/utils/dialect_utils.py
def normalize_dialect_for_sqlglot(dialect: str) -> str:
    # netezza, greenplum, vertica, datafusion, ansi, standard, ... -> postgres
```

The "34 dialects" headline is best read as "34 parser/generator pairs," not "every production engine you might ship to."

**Category 2: Post-generation fixups for valid-but-broken output**

SQLGlot emits standard SQL. Sometimes the standard form fails on the target engine.

| Fix | What SQLGlot emits | What the engine accepts | Affects |
|-----|--------------------|--------------------------|---------|
| `_restore_group_order_by_all_keyword` | `GROUP BY "ALL"` (quoted) | `GROUP BY ALL` | DuckDB |
| `_fix_sqlite_unsupported_syntax` | `DATE + INTERVAL '5' DAY`, `EXTRACT(part FROM date)` | `DATE(..., '+5 days')`, `STRFTIME(...)` | SQLite |
| `fix_postgres_date_arithmetic` | `d_date + 5` | `d_date + INTERVAL '5' DAY` | Postgres, DataFusion |

None of these are exotic. They are everyday TPC-H/TPC-DS expressions. They round-trip the AST fine; they just fail at the engine.

**Category 3: Per-platform query transformers**

Three platforms required dedicated transformer modules.

**ClickHouse** (`platforms/clickhouse/query_transformer.py`):
- Case folding for unquoted identifiers (ClickHouse is case-sensitive; SQLGlot doesn't fold)
- DECIMAL division-by-zero NULL wrapping
- TPC-DS Q23/Q87 subquery aliasing: we tried AST injection, it corrupted GROUP BY in Q23 and aliases inside `EXCEPT/INTERSECT` in Q87. We fell back to a session setting (`joined_subquery_requires_alias=0`) because the AST rewrite was unsafe.

**QuestDB** (`platforms/questdb_rewriter.py`, ~450 lines):
- Implicit comma joins -> explicit `INNER JOIN ... ON` (every TPC-H, TPC-DS, SSB query)
- `INTERVAL` arithmetic -> `dateadd('d', n, ts)` (TPC-H Q1, Q4, Q6, Q17)
- `SUBSTRING(s FROM p FOR l)` -> `substring(s, p, l)`
- CTE column-alias lists (`WITH x (a, b) AS ...`) stripped

QuestDB has a SQLGlot dialect entry. The dialect entry doesn't cover what real QuestDB 9.3.4 actually accepts. Our rewriter is the bridge.

**DataFusion** (`platforms/datafusion_query_transformer.py`): see Category 4.

**Category 4: Engine-semantic gaps (the silent ones)**

The most expensive category. SQLGlot transpiles cleanly. The SQL executes. The results are wrong.

| TPC-H Query | Issue | Our fix |
|-------------|-------|---------|
| Q11 | HAVING with scalar subquery: planner miscomputes the threshold | Hoist threshold to a CTE, filter with WHERE |
| Q16 | NOT IN with NULLs: three-valued logic not honored | Rewrite to NOT EXISTS |
| Q18 | IN inside HAVING: decorrelation bug returns extra rows | Rewrite to EXISTS wrapper |
| Q20 | Nested correlated IN: incorrect join cardinality | Extract to CTEs with explicit joins |

**Critical framing**: These are engine planner semantics, not SQLGlot bugs. But the implicit promise of "transpile across engines" is that *behavior* travels with the syntax. It doesn't. A transpiler that doesn't know which query *shapes* trigger known engine bugs will silently produce wrong answers on those shapes. No syntactic transpiler can catch this. Someone has to.

**Category 5: DDL semantics (19 platforms)**

SQLGlot is a *query* transpiler. DDL is correctly out of scope. But running a benchmark on a new platform requires creating tables, and creating tables means engine-specific DDL.

We maintain `sql_compat/rules/ddl_optimize/` for: ClickHouse, Databend, Databricks, Doris, Fabric DW, Firebolt, LakeSail, pg_mooncake, PostgreSQL/CedarDB, Presto, QuestDB, Redshift, SingleStore, Snowflake, Spark, StarRocks, Synapse, Trino, Velox.

Concrete examples:

| Platform | Required DDL transformation | If you skip it |
|----------|------------------------------|----------------|
| ClickHouse | Strip `Nullable NOT NULL`; inject `ENGINE=MergeTree() ORDER BY (...)` | Table creation fails |
| Doris | TIME -> VARCHAR(8); STRING -> VARCHAR(65533); ARRAY[N] -> ARRAY; inject `DUPLICATE KEY` + `DISTRIBUTED BY HASH` | Type/key/distribution errors |
| SingleStore | Strip FK; `CREATE REFERENCE TABLE` for dimensions; inject `SHARD KEY` and `SORT KEY`, in that order | Error 2752 (FK), or terrible distribution |
| Databricks | `CREATE OR REPLACE TABLE ... USING DELTA TBLPROPERTIES(...)` | Idempotency fails on re-run |
| pg_mooncake | Append `USING columnstore` | Silent fallback to row-store heap |

This is the half of cross-engine portability that gets least attention and matters most operationally.

**Category 6: Hand-written query overrides**

Where SQLGlot's emitter produces SQL the engine refuses, we ship hand-written variants per engine. Example: H2O Q9 (ordered-set percentile aggregate).

```
sql_compat/rules/query_source/h2odb_variants.py
  CLICKHOUSE_Q9_SQL  -> uses ClickHouse quantile()
  STARROCKS_Q9_SQL   -> uses PERCENTILE_APPROX()
  MYSQL_Q9_SQL       -> bypasses SQLGlot entirely; ships verbatim ANSI WITHIN GROUP
                        because SQLGlot adds a multi-expression decorator that
                        SingleStore rejects
```

The MySQL/SingleStore case is worth dwelling on: `PERCENTILE_CONT WITHIN GROUP` is not exotic. It's a SQL standard ordered-set aggregate. SQLGlot's emitter "improves" it in a way at least one production engine refuses. We bypass the transpiler for that query.

Same pattern in `nyctaxi_variants.py`, `coffeeshop_variants.py`, `tpcdi_variants.py`, `vector_search_variants.py`.

**Category 7: SQL -> DataFrame translation**

Half of BenchBox's targets are DataFrame engines: Polars, Pandas, DataFusion-Python, PySpark, Dask, Modin, cuDF, LakeSail. SQLGlot doesn't address translating SQL into Polars expressions; that's a different problem.

Our `platforms/dataframe/unified_frame.py` (~2,200 lines) is a SQL-shaped facade over per-engine DataFrame APIs. Polars' own SQL frontend was tried and removed: "fundamental limitations" in our notes. DataFusion's expression AST has to be parsed post-translation for aggregate arithmetic.

This isn't a SQLGlot gap; it's the boundary of what a SQL transpiler is for. But anyone shopping for "a SQL portability layer" should know it exists.

---

### 4. What we learned (~400 words)

**Thesis**: Five takeaways, organized from most to least confident.

**1. "Supported dialects" is a one-bit signal that needs more bits.**
SQLGlot's "34 dialects" is accurate as a count of parser/generator pairs. It's less useful as a maturity signal. The Postgres support is rock-solid. The Doris support emits VARCHAR -> STRING in a way that breaks key columns. A per-dialect maturity matrix (A-grade tested, best effort, parser-only) would be transformative for production users. We'd happily contribute test cases.

**2. Engine-semantic bugs are the most dangerous category.**
The DataFusion TPC-H rewrites are not in any "transpilation correctness" framework's failure list, because the transpilation is correct. The engine's planner is the proximate cause of the wrong answer. Yet the user-visible failure mode is "I transpiled and got wrong results." A community-maintained registry of "this query shape produces wrong results on engine X version >= Y" with rewrite recipes would help every team that hits these. Today every team rediscovers them privately.

**3. DDL is half the work, and it's structurally outside SQLGlot's scope.**
We don't think SQLGlot should solve DDL semantics; engine-specific physical design (engines, sort keys, shard keys, table formats) is too tied to deployment. But anyone planning to "use SQLGlot for cross-engine deployment" should budget separately for DDL infrastructure. We have 19 platform-specific DDL rewrite modules. That's not going away.

**4. AST rewriting is sometimes less safe than session settings.**
Our ClickHouse Q23/Q87 alias-injection rewrite *had* full AST control. It still corrupted real queries (split GROUP BY out of subqueries; injected aliases inside `EXCEPT/INTERSECT`). The fix that shipped was a session setting. The lesson: an AST-correct transformation can still produce a semantically broken query. When the engine offers a knob, prefer it.

**5. We use SQLGlot every day and would not replace it.**
Worth saying out loud. The investments above are not arguments against SQLGlot; they are the work that exists *because* SQLGlot handles the ~80% that nobody wants to write. Without SQLGlot we would not have BenchBox; we would have one platform's queries.

---

### 5. Try it yourself (~200 words)

**Thesis**: Readers can run the same multi-platform translations BenchBox does, see the wrapper behavior, and inspect the rule registry.

```bash
# Translate the same query across three engines:
$ benchbox run --platform duckdb --benchmark tpch --queries Q1 --dry-run preview/duckdb
$ benchbox run --platform clickhouse --benchmark tpch --queries Q1 --dry-run preview/ch
$ benchbox run --platform datafusion --benchmark tpch --queries Q1 --dry-run preview/df
```

`--dry-run` writes the final, post-translation, post-rewrite SQL we'd actually send. Diff the three to see what each layer added.

The compatibility inventory is also queryable:

```bash
$ uv run -- python -m benchbox.sql_compat.inventory
# emits a JSON report of every dialect-branching decision point in BenchBox
```

Source code pointers:
- `benchbox/utils/dialect_utils.py` (centralized wrapper)
- `benchbox/platforms/datafusion_query_transformer.py` (engine-semantic rewrites)
- `benchbox/platforms/questdb_rewriter.py` (post-AST syntax rewrites)
- `benchbox/sql_compat/rules/ddl_optimize/` (19 DDL rewrite modules)
- `benchbox/sql_compat/rules/query_source/h2odb_variants.py` (hand-written overrides)

We'd love to hear about gaps you've hit in your own SQLGlot-based projects. Open an issue at the BenchBox repo, we likely have either a workaround or a kindred scar.

---

## Research Status

- [x] Fivetran post (2026-05-01) reviewed for performance numbers and capability claims
- [x] BenchBox SQL infrastructure audit (~2,500 lines across 7 categories, file paths verified)
- [x] DataFusion silent-corruption queries (Q11, Q16, Q18, Q20) confirmed in `datafusion_query_transformer.py`
- [x] QuestDB rewriter line count and rewrite categories confirmed
- [x] 19 DDL rewrite modules enumerated under `sql_compat/rules/ddl_optimize/`
- [x] H2O Q9 hand-written variants confirmed in `h2odb_variants.py`
- [x] Subquery alias injection failure documented in `clickhouse_session_policy.py`
- [x] DataFrame `unified_frame.py` line count (~2,200) confirmed
- [ ] Verify exact line counts in draft via `wc -l` before publish
- [ ] Confirm DataFusion engine version that triggers Q11/Q16/Q18/Q20 issues for citation

## Visual Elements for Draft

1. **Layer evolution diagram** (section 2): conceptual layers from `sqlglot.transpile()` -> wrapper -> per-platform -> rule registry
2. **Post-generation fixups table** (section 3, Cat 2): three rows, what SQLGlot emits vs what the engine accepts
3. **DataFusion silent-corruption table** (section 3, Cat 4): four queries, issue, our fix
4. **DDL transformations table** (section 3, Cat 5): five platforms, what's required, failure mode if skipped
5. **MySQL Q9 bypass code snippet** (section 3, Cat 6): three-line illustration of when we drop SQLGlot entirely
6. **Three-engine dry-run comparison** (section 5): the canonical "show me the difference" example

## Cross-References

- Fivetran post (anchor for the framing): https://www.fivetran.com/blog/how-we-accelerated-transpilation-by-compiling-sqlglot-with-mypyc
- SQLGlot project: https://github.com/tobymao/sqlglot
- BenchBox SQL compat README: `benchbox/sql_compat/README.md`
- Inventory tool: `benchbox/sql_compat/inventory.py`
- Blind spot pointer: `_project/blind-spots/2026-05-02-155448-validation-query-no-per-platform-override.md`

## Conflicts Check

- No overlap with post #5 (DuckDB tpch extension vs BenchBox): different topic
- No overlap with planned post on DataFrame translation (idea #4 in series): this post mentions DataFrame as Category 7 but a dedicated DataFrame post can go deep on translation patterns
- Complements platform-deep-dives series: this is the cross-platform infrastructure post; per-platform deep dives can reference these categories
