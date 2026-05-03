# Outline: What We Built on Top of SQLGlot (and Why Transpilation Isn't Enough)

> SQLGlot is the foundation, not the finished house. This post is the punchlist of what we still had to build.

**TL;DR**: BenchBox runs benchmarks across 36 SQL platforms. SQLGlot does the transpilation heavy lifting (and the recent mypyc work makes it dramatically faster), but real cross-engine portability needs a substantial additional layer: dialect normalization, post-generation fixups, engine-aware semantic rewrites, a 19-platform DDL rewrite registry, hand-written query overrides where translation can't deliver, and a SQL-to-DataFrame facade for engines that don't speak SQL. We catalog the gaps with file paths and concrete examples.

---

## Metadata

```yaml
title: "What we built on top of SQLGlot (and why transpilation isn't enough)"
series: building-benchbox
post_number: 11
type: architecture-design
target_length: 1,800-2,400 words
tags: [benchbox, sqlglot, sql, transpilation, dialects, dataframe, architecture, datafusion, clickhouse, questdb]
```

## Framing

- **Tone**: Genuinely complimentary about SQLGlot. Findings are about what a transpiler structurally cannot do, not about what SQLGlot does wrong.
- **Anchor**: The Fivetran post (2026-05-01) closes with "It has never been faster or easier to translate between different SQL dialects so that you can use different query engines." First half unambiguously true; second half is where our experience adds nuance.
- **Audience**: BenchBox users, SQL tooling builders, anyone evaluating SQLGlot for production cross-engine workloads.
- **Voice constraints**: "we" not "I"; hyphens only (no em-/en-dashes); neutral on platforms; frame extras as "what's left to build" not "what SQLGlot fails at."

## Section Plan

### 1. The Problem (~250 words)

**Thesis**: BenchBox's promise is "one benchmark, every engine." That is built on cross-dialect SQL translation. SQLGlot is the obvious tool. The gap between "transpile cleanly" and "execute correctly" is wider than any transpiler can close.

Frame: 36 SQL platforms + DataFrame engines, 18+ benchmarks, thousands of (query, dialect) combinations per release. Mention Fivetran mypyc speedups (~5x parser, ~2.5x generator, ~2x optimizer). Add caveat that we have not measured SQLGlot's runtime share. Reframe: "34 dialects supported" is parser/generator coverage, not production-engine compatibility.

### 2. How we got here (~300 words)

**Thesis**: Each layer added because the previous left an observable gap.

- Layer 1: `sqlglot.transpile()` directly, the obvious 80%
- Layer 2: Centralized wrapper at `benchbox/utils/dialect_utils.py`, 8 dialect normalizations + 4 generic post-fixups
- Layer 3: Per-platform query transformers, ClickHouse, QuestDB, DataFusion
- Layer 4: `benchbox/sql_compat/` registry, `ddl_optimize/`, `query_source/`, `query_adapter/`, `schema_emit/`, `benchmark_gate/`, plus `inventory.py` and `registry.py`

### 3. The seven categories (~900 words)

Center of gravity. Each category gets one paragraph: what SQLGlot does, what's left, file path, concrete example.

1. **Dialect normalization**: 8 dialects (Netezza, Greenplum, Vertica, DataFusion, ANSI, Standard, …) mapped to nearest peer (`postgres`).
2. **Post-generation fixups**: Table of three fixes (DuckDB `GROUP BY ALL`, SQLite date/EXTRACT, Postgres date arithmetic).
3. **Per-platform query transformers**: ClickHouse (case folding, division safety, Q23/Q87 session policy), QuestDB (comma joins, INTERVAL, SUBSTRING, CTE column lists). DataFusion handled in #4.
4. **Engine-semantic gaps (silent ones)**: DataFusion TPC-H Q11/Q16/Q18/Q20. Steelman + rebuttal.
5. **DDL semantics (19 platforms)**: Table of five examples (ClickHouse, Doris, SingleStore, Databricks, pg_mooncake).
6. **Hand-written query overrides**: H2O Q9 (`PERCENTILE_CONT WITHIN GROUP`); per-engine variants; bypass case for MySQL/SingleStore.
7. **SQL → DataFrame**: 8 DataFrame engines; `unified_frame.py` (the largest single file in the cross-platform layer).

### 4. What we learned (~350 words)

Five takeaways:

1. "Supported dialects" is a one-bit signal; per-dialect maturity matrix would help. Includes upstream contribution policy.
2. Engine-semantic bugs are most dangerous; community engine-bug registry would help.
3. DDL is half the work, structurally outside SQLGlot's scope.
4. AST rewriting sometimes less safe than session settings (ClickHouse Q23/Q87 lesson).
5. We use SQLGlot every day and would not replace it.

### 5. Try it yourself (~150 words)

`benchbox run --dry-run` shows the post-translation, post-rewrite SQL. Compatibility inventory is queryable: `uv run -- python -m benchbox.sql_compat.inventory`. Source code pointer list.

### Test Environment + Limitations (~150 words)

- SQLGlot pinned `>=20.0.0,<31.0.0` (resolved 30.6.0)
- DataFusion versions current to v0.2.1 platform matrix
- ClickHouse Cloud and self-hosted 25.x, QuestDB 9.3.4, Doris 2.1.x
- Engine versions matter; retirement protocol noted

## Research Status

- [x] Fivetran post (2026-05-01) reviewed for performance numbers and capability claims
- [x] BenchBox SQL infrastructure audit covers seven categories with verified file paths
- [x] DataFusion silent-corruption queries (Q11, Q16, Q18, Q20) confirmed in `datafusion_query_transformer.py`
- [x] QuestDB rewriter scope (comma joins, INTERVAL arithmetic, SUBSTRING form, CTE column lists) confirmed
- [x] 19 DDL rewrite modules enumerated under `sql_compat/rules/ddl_optimize/`
- [x] H2O Q9 hand-written variants confirmed in `h2odb_variants.py`
- [x] Subquery alias injection failure documented in `clickhouse_session_policy.py`
- [x] DataFrame `unified_frame.py` is the dominant file in the layer (verified via `wc -l` at write time)
- [x] SQLGlot pin recorded (`>=20.0.0,<31.0.0` in `pyproject.toml`; resolved 30.6.0 in `uv.lock`)
- [ ] Confirm DataFusion engine version that triggers Q11/Q16/Q18/Q20 issues for citation

## Visual Elements

1. Layer evolution diagram (section 2): conceptual layers from `sqlglot.transpile()` -> wrapper -> per-platform -> rule registry
2. Post-generation fixups table (section 3, Cat 2)
3. DataFusion silent-corruption table (section 3, Cat 4)
4. DDL transformations table (section 3, Cat 5)
5. MySQL Q9 bypass code snippet (section 3, Cat 6)
6. Three-engine dry-run comparison (section 5)

## Cross-References

- Fivetran post: <https://www.fivetran.com/blog/how-we-accelerated-transpilation-by-compiling-sqlglot-with-mypyc>
- SQLGlot project: <https://github.com/tobymao/sqlglot>
- BenchBox SQL compat README: `benchbox/sql_compat/README.md`
- Inventory tool: `benchbox/sql_compat/inventory.py`
- Companion ADR: `docs/development/adr/adr-sqlglot-use-and-non-use.md`
- Blind-spot pointer: `_project/blind-spots/2026-05-02-155448-validation-query-no-per-platform-override.md`

## Conflicts Check

- No overlap with post #5 (DuckDB tpch extension vs BenchBox): different topic.
- No overlap with planned DataFrame translation post (idea #4): this post mentions DataFrame as Category 7; a dedicated post can go deep on translation patterns.
- Complements platform-deep-dives series: this is the cross-platform infrastructure post; per-platform deep dives can reference these categories.
