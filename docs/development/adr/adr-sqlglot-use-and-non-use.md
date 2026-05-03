# ADR: SQLGlot Use and Non-Use

## Status

Accepted (codifies existing practice as of 2026-05-03)

**SQLGlot version at acceptance**: pinned `>=20.0.0,<31.0.0` in
`pyproject.toml`; the resolved version in `uv.lock` was 30.6.0 at time of
acceptance. Decisions in this ADR were validated against that version; gaps
may have changed since.

**Maintenance protocol**: Re-review this ADR when (a) a new SQLGlot major
version is adopted, (b) the phase taxonomy in the sibling
[phase-aware pipeline ADR](adr-sql-compat-phase-aware-pipeline.md) changes,
or (c) `sqlglot[c]` is adopted in production. The ADR records a snapshot of
the boundary; the boundary itself is durable, but the version of SQLGlot it
was validated against is not.

## Date

2026-05-03

## Context

BenchBox runs benchmarks across 36 SQL platforms plus a fleet of DataFrame
engines. Cross-platform portability requires translating canonical benchmark
SQL into something each engine will accept and execute correctly. We chose
[SQLGlot](https://github.com/tobymao/sqlglot) early in the project as the
foundation for that translation, and we have continued to use it on every
release since. SQLGlot is excellent and the recent mypyc compilation work
delivered meaningful speedups for our workload (parser ~5x, generator ~2.5x,
optimizer ~2x).

This ADR exists because, over the last 12 months, BenchBox accreted a
substantial layer of SQL infrastructure on top of SQLGlot, organized into
seven categories: dialect normalization, post-generation fixups, three
per-platform query transformers, a 19-platform DDL rewrite registry,
hand-written query overrides, a SQL-to-DataFrame facade, and the
[`sql_compat` rule engine](adr-sql-compat-phase-aware-pipeline.md). The
answer to "why do we need so much code on top of a transpiler?" has
structural reasons rooted in what a SQL transpiler is and is not, and those
reasons deserve to be written down explicitly so future contributors
understand the boundary.

This is a complement to the
[`sql_compat` phase-aware pipeline ADR](adr-sql-compat-phase-aware-pipeline.md),
which documents *how* our compatibility decisions are organized. This ADR
documents *why* we use SQLGlot for some of those decisions and deliberately do
not use it for others.

The decision is not a critique of SQLGlot. SQLGlot is the best general-purpose
SQL transpiler available, and without it BenchBox would not be a multi-platform
project. This ADR is about scope and boundaries, not quality.

---

## Decision

**SQLGlot is the canonical translation engine for query-shaped SQL between
SQL dialects.** Every SQL query that travels from a benchmark's source dialect
to a target platform's dialect goes through SQLGlot at the `query_compile`
phase of the `sql_compat` pipeline, unless an explicit registry decision says
otherwise.

**SQLGlot is deliberately not used for** five categories of work that fall
outside what a syntactic SQL transpiler can structurally do:

1. Engine-semantic query rewrites (where the SQL is well-formed but the
   target engine's planner returns wrong results for a given query shape)
2. DDL physical-design semantics (engines, sort keys, shard keys, table
   formats, distribution policies)
3. Hand-written per-engine query variants (where SQLGlot's emitter produces
   SQL the target engine refuses)
4. SQL-to-DataFrame translation (Polars, Pandas, DataFusion-Python, PySpark,
   etc.)
5. Compatibility governance (registry, lint, capability matrix)

Each of these has a separate, documented home in the BenchBox codebase, listed
in the section below.

This ADR codifies existing practice. The pattern emerged organically over
2025-2026 and is documented here so future contributors do not need to
re-derive the boundary every time they hit a new dialect-translation problem.

### Non-Goals

- Replacing or forking SQLGlot.
- Adopting `sqlglot[c]` (mypyc-compiled SQLGlot) for production use.
  Deferred to a separate evaluation; we want to confirm wheel availability
  on all our supported Python versions and architectures first.
- Pinning a specific SQLGlot version permanently. We track upstream releases
  and upgrade on the normal cadence.
- Standardizing every dialect-branching call site in the codebase. Legitimate
  local rendering (type mapping, identifier quoting, storage layout) remains
  in adapter code, gated by `@compat_local`.

---

## Where SQLGlot is Canonical

SQLGlot is the source of truth for the following operations. Going around it
for any of these requires a registered `sql_compat` rule with explicit
rationale.

| Operation | Site | Notes |
|-----------|------|-------|
| Source-to-target SQL translation | `benchbox/utils/dialect_utils.py` `translate_sql_query()` | Centralized wrapper; pre/post processors plug in here |
| Identifier quoting | SQLGlot generator | Per-dialect, no override |
| Function and operator renaming | SQLGlot generator | Per-dialect, no override |
| Type-syntax conversion | SQLGlot generator | Type *aliasing* (e.g., `VARCHAR` to `STRING` for Doris) is a known gap and is handled at the DDL layer, not here |
| AST parsing for downstream rewrites | SQLGlot parser | The `query_adapter` and `query_compile` phases consume the parsed AST |
| Roundtrip parsing of TPC-base SQL | SQLGlot | Default base dialect is `netezza`; `dialect_utils.normalize_dialect_for_sqlglot()` maps unsupported targets to nearest peer |

**Why SQLGlot is canonical here**: It correctly handles the long tail of SQL
syntax variation across dialects (joins, CTEs, window functions, aggregates,
basic types, `LIMIT` to `TOP N` translations, `EXTRACT` to `DATE_PART` swaps,
function renames). This is the 80% case, and SQLGlot makes it invisible. We
are not interested in re-implementing this work, and we have tested SQLGlot
against tens of thousands of TPC-DS query translations on every BenchBox
release.

---

## Where SQLGlot is Deliberately Not Used

For each category below, we describe what the work is, why a SQL transpiler
structurally cannot do it, where it lives in BenchBox, and what fallback we
ship.

### 1. Engine-Semantic Query Rewrites

**What it is**: Some SQL constructs are well-formed in the target dialect's
grammar and accepted by SQLGlot's generator, but the target engine's planner
executes them incorrectly. The user-visible failure mode is "the query ran and
returned wrong results."

**Why SQLGlot cannot do this**: A syntactic transpiler operates on the AST and
the dialect generator. It does not know which query *shapes* trigger which
engine planner bugs. The SQL is correct in both dialects; the bug lives in the
target engine's planner.

**FailureMode classification**: These cases are tagged
`failure_mode=SILENT_CORRUPTION` in the rule registry; see the `FailureMode`
enum in the
[phase-aware pipeline ADR](adr-sql-compat-phase-aware-pipeline.md) for the
full taxonomy.

**Steelman and rebuttal**: One could argue that a portability-focused
transpiler should ship rewrite recipes for known engine bugs, since the
user-visible failure mode ("I transpiled and got wrong results") is
indistinguishable from a transpilation bug. We do not adopt this position.
SQLGlot's job is dialect-correct emission; an engine-bug registry is its own
artifact and could live alongside SQLGlot, in a sidecar project, or in
project-specific layers like ours. We would happily contribute to such an
artifact if one emerges, but its absence does not make these gaps SQLGlot's
responsibility.

**Where it lives in BenchBox**:
- [`benchbox/platforms/datafusion_query_transformer.py`](../../../benchbox/platforms/datafusion_query_transformer.py)
  rewrites four TPC-H queries (Q11, Q16, Q18, Q20) to avoid query shapes that
  DataFusion's planner returns incorrect results for.
- The compatibility registry `query_adapter` phase
  ([rules](../../../benchbox/sql_compat/rules/query_adapter/datafusion_query_rewrites.py))
  registers these rewrites as `REWRITE_QUERY` actions with a
  `transformer_id` per query.

**Fallback**: A documented rewrite per (platform, benchmark, query_id) tuple,
producing an equivalent query through a different shape that the engine plans
correctly. Each rewrite is validated against TPC-H reference answers in the
normal validation pipeline.

**Retirement protocol**: A rewrite is a candidate for retirement when (a) the
engine release notes claim the underlying bug is fixed, (b) we run the
rewrite-bypass version against TPC-H reference answers in the validation
pipeline and it passes, and (c) we remove the rule and re-run validation in
CI. Retirement is opt-in; we do not auto-retire stale rewrites, because the
cost of leaving a now-unnecessary rewrite in place is low, and the cost of
removing one prematurely is silent corruption.

### 2. DDL Physical-Design Semantics

**What it is**: Engine-specific physical design that determines whether a
table is even creatable and whether it performs reasonably. Examples:
- ClickHouse `ENGINE=MergeTree()` and `ORDER BY` are mandatory for most tables
- Doris requires `DUPLICATE KEY` and `DISTRIBUTED BY HASH` and rejects
  `STRING` as a key column
- SingleStore requires `SHARD KEY` and `SORT KEY` and uses
  `CREATE REFERENCE TABLE` for dimensions
- Databricks requires `USING DELTA` and idempotent `CREATE OR REPLACE TABLE`
- pg_mooncake silently falls back to row-store heap without `USING columnstore`

**Why SQLGlot cannot do this**: SQLGlot is a *query* transpiler. DDL physical
design depends on deployment context (table format choice, cluster topology,
catalog setup, version-gated capabilities). It is correctly outside the scope
of a transpiler.

**Where it lives in BenchBox**: 19 platform-specific DDL rewrite modules
under [`benchbox/sql_compat/rules/ddl_optimize/`](../../../benchbox/sql_compat/rules/ddl_optimize/),
plus the per-adapter `_optimize_table_definition()` hook documented in the
[phase-aware pipeline ADR](adr-sql-compat-phase-aware-pipeline.md).

Fabric Warehouse occupies a third path between "in the registry" and
"not in the registry":
[`fabric_dw_ddl_rewrites.py`](../../../benchbox/sql_compat/rules/ddl_optimize/fabric_dw_ddl_rewrites.py)
registers a `governance_only=True` rule so `compat_lint` can audit that
DDL rewriting is happening for the platform, but the runtime
transformation lives in `FabricWarehouseAdapter._optimize_table_definition()`
because the schema prefix it injects depends on runtime adapter state
(the adapter's configured `self.schema`). The registry rule is the
governance marker; the rewrite is operational. The parent ADR's
"Fabric Warehouse Decision" section captures the original reasoning for
keeping the runtime logic in the adapter; the governance-only rule was
added afterwards as a `compat_lint` accountability hook.

**Fallback**: Explicit DDL rewrite registered per platform. The rule engine
applies the rewrite at the `ddl_optimize` phase before the DDL reaches the
engine.

### 3. Hand-Written Per-Engine Query Variants

**What it is**: A small number of queries where SQLGlot's emitter produces
syntactically valid SQL that the target engine's parser refuses. The clearest
example is H2O Q9 (`PERCENTILE_CONT WITHIN GROUP`):
- ClickHouse needs `quantile()`
- StarRocks needs `PERCENTILE_APPROX()`
- MySQL/SingleStore accepts the ANSI form, but only without the multi-
  expression `WITHIN GROUP ORDER BY (CASE WHEN ... THEN ... ELSE NULL END)`
  decorator that SQLGlot's emitter adds

**Why SQLGlot cannot do this**: Function translation between vendor-specific
ordered-set aggregates is non-bijective. SQLGlot's emitter has to choose one
form, and there are cases where every choice fails on at least one engine. We
do not view this as a SQLGlot bug; we view it as a known limit of automated
function translation for ordered-set aggregates.

**Where it lives in BenchBox**: Hand-written variants under
[`benchbox/sql_compat/rules/query_source/`](../../../benchbox/sql_compat/rules/query_source/),
including `h2odb_variants.py`, `nyctaxi_variants.py`,
`coffeeshop_variants.py`, `tpcdi_variants.py`, and
`vector_search_variants.py`.

**Fallback**: A `SELECT_VARIANT` action at the `query_source` phase. The
variant SQL is already in the target dialect, which short-circuits SQLGlot.

### 4. SQL-to-DataFrame Translation

**What it is**: Translating SQL-shaped query intent into a DataFrame method
chain for engines that do not speak SQL: Polars, Pandas, DataFusion-Python,
PySpark, Dask, Modin, cuDF, LakeSail.

**Why SQLGlot cannot do this**: SQLGlot translates SQL into more SQL.
DataFrame translation is a different problem, and there is no reason to
expect a SQL transpiler to solve it. Polars has its own SQL frontend; we
evaluated it earlier in BenchBox's history and removed it ("fundamental
limitations" in our notes), so we ship a DataFrame-native translation layer
instead.

**Where it lives in BenchBox**:
- [`benchbox/platforms/dataframe/unified_frame.py`](../../../benchbox/platforms/dataframe/unified_frame.py)
  is a SQL-shaped facade over per-engine DataFrame APIs
  (approximately 4,200 lines)
- DataFusion's expression AST is parsed post-translation for aggregate
  arithmetic
- The `sql_compat` registry `dataframe_filter` phase is the dedicated home
  for skip/variant decisions in DataFrame mode

**Fallback**: We implement DataFrame translation by hand per engine family,
sharing helpers where the APIs converge.

### 5. Compatibility Governance

**What it is**: The metadata, lint, and capability-matrix layer that tracks
*every* compatibility decision so reviewers can audit them, contributors can
discover them, and users can see what works on which platform.

**Why SQLGlot cannot do this**: SQLGlot has no opinion about BenchBox's
compatibility policy. The registry is BenchBox-specific and exists to govern
the four categories above.

**Where it lives in BenchBox**:
- [`benchbox/sql_compat/`](../../../benchbox/sql_compat/) (the rule engine)
- [`scripts/compat_lint.py`](../../../scripts/compat_lint.py) (lint in
  permanent error mode after `w15`)
- [`scripts/generate_compat_docs.py`](../../../scripts/generate_compat_docs.py)
  (regenerates capability matrix and skip reference)
- Generated artifacts: [capability matrix](../../compat/capability-matrix.md),
  [skip reference](../../compat/skip-reference.md)

**Fallback**: The phase-aware pipeline ADR is the canonical document for
this layer.

---

## Alternatives Considered

### SQLGlot only (no infrastructure on top)

**Considered, rejected.** This is the implicit "what SQLGlot promises"
position: write canonical SQL, transpile to the target dialect, run. We
operated this way in early BenchBox releases. It produced silent validation
failures (DataFusion TPC-H Q11/Q16/Q18/Q20), table-creation failures
(ClickHouse missing engines, Doris missing distribution), and parse errors
(QuestDB comma joins, MySQL ordered-set aggregate decorators). Every category
in the "Deliberately Not Used" section above is something we tried *not*
doing, and shipped wrong answers as a result. Once validation surfaced the
failures, we built the infrastructure.

### Replace SQLGlot with a custom parser/transpiler

**Considered, rejected.** Building a maintained SQL parser/transpiler covering
20+ dialects is years of work. SQLGlot does it. The 20% we add is at the
boundary, not the core. There is no realistic scenario where rebuilding
the core is cheaper than working around the edges.

### Replace SQLGlot with sqlglotrs (Rust) for performance

**Considered, rejected for now.** The Fivetran post on mypyc compilation
demonstrates that pure-Python compilation gets us most of the speedup
without a Rust toolchain dependency. We track sqlglotrs but have not
needed it; SQLGlot's performance has not been a BenchBox bottleneck.

### Adopt sqlglot[c] (mypyc) immediately

**Deferred.** The mypyc speedups are real and would benefit our workload, but
we want to verify wheel availability across the Python versions and
architectures we test against before flipping the import. We have also not
rigorously measured SQLGlot's share of the BenchBox runtime budget; without
that measurement, the speedups are an opportunity rather than a quantified
need. Tracked as a future evaluation; this ADR does not block it.

### Hand-write SQL per platform with no transpilation

**Considered, rejected.** This is the alternative for projects that ship
small numbers of curated queries per engine. BenchBox ships 22 TPC-H
queries plus 99 TPC-DS queries plus several other benchmark suites across
36 platforms; manually maintaining 22 * 36 = 792 TPC-H query variants alone
is operationally infeasible. SQLGlot is the leverage that makes the project
tractable.

---

## Consequences

### Positive

- The boundary between "SQLGlot's job" and "BenchBox's job" is documented
  and stable. New contributors can decide where new compatibility work
  belongs without re-deriving the boundary.
- SQLGlot upgrades are routine. Because we do not depend on SQLGlot to do
  things it does not promise, version bumps rarely break us in surprising
  ways.
- The five categories above have explicit, separate homes in the codebase.
  A contributor who hits a DataFusion silent-corruption case knows to add a
  rule in `query_adapter`, not to file a SQLGlot bug.
- Our compatibility surface is auditable: the `sql_compat` inventory tool
  enumerates every dialect-branching decision point, so we can answer
  "what does BenchBox do for platform X?" precisely.

### Negative / Risks

- The infrastructure on top of SQLGlot covers seven categories and
  continues to grow as we add platforms. Any contributor evaluating
  BenchBox's cross-engine support has to read this ADR plus the
  phase-aware pipeline ADR to understand the scope.
- Engine version drift can re-open closed semantic-rewrite cases. If a
  DataFusion release fixes Q16 NULL semantics, our rewrite becomes
  redundant; we do not aggressively retire rewrites because the
  validation pipeline catches the case where they become wrong, but
  rewrites do accumulate.
- Hand-written query variants are a maintenance burden whenever a
  benchmark spec changes; we mitigate this by keeping the variant set
  small (most benchmarks have zero or one variant per query).

### Neutral

- We continue to use SQLGlot's main branch in our normal release cadence.
  If we adopt `sqlglot[c]` in the future, this ADR does not need updating;
  the boundary is the same regardless of how SQLGlot itself is compiled.

### Upstream Contribution Policy

This is not an alternative to the decision above; it is a standing policy
that runs alongside it. We are open to contributing patches upstream into
SQLGlot where they fit SQLGlot's mission:

- Bug fixes in dialect generators (e.g., `GROUP BY ALL` quoting in DuckDB)
- New tests for dialects we exercise heavily (Doris, QuestDB, DataFusion)

We do *not* expect SQLGlot to absorb:

- Engine-semantic rewrites (different scope)
- DDL physical-design (different scope)
- Hand-written variants (project-specific)
- DataFrame translation (different scope)
- Compatibility governance (project-specific)

When we contribute upstream, it is in the spirit of patches, not scope
expansion. Adoption of this ADR does not preclude or require any specific
upstream contribution.

---

## How to Decide Where New Work Goes

When a contributor hits a new compatibility case, the decision tree is:

1. **Does SQLGlot already handle this correctly when called via
   `dialect_utils.translate_sql_query()`?** If yes, no work needed.
2. **Is the SQL syntactically wrong on the target engine, and is the fix a
   small, dialect-generic post-processing step?** Add a post-processor in
   `dialect_utils.py` and register it as a `post_translate` action.
3. **Is the fix specific to one platform's syntax quirks?** Add a rule in
   `query_adapter`, with a `REWRITE_QUERY` action and a
   `transformer_id` pointing to the platform's transformer module.
4. **Is the SQL syntactically correct but the engine returns wrong
   results?** Add a rule in `query_adapter` with a `REWRITE_QUERY` action
   that produces an equivalent query through a different shape. Validate
   against reference answers.
   - **4a.** If the AST rewrite turns out to be structurally unsafe (corrupts
     queries that exercise `EXCEPT`/`INTERSECT`, `GROUP BY` at subquery
     boundaries, or other constructs the grammar allows but real query
     corpora exercise irregularly) and the engine offers a session knob,
     prefer `SET_SESSION_POLICY` at `query_adapter` over `REWRITE_QUERY`.
     The ClickHouse TPC-DS Q23/Q87
     `joined_subquery_requires_alias=0` rule is the canonical example: an
     AST-correct alias-injection rewrite still produced a semantically
     broken query, so the safe fix was the engine knob.
5. **Is the issue in DDL?** Add a rule in `ddl_optimize` and implement the
   transformation in the platform's `_optimize_table_definition()` hook.
6. **Does SQLGlot's emitter produce SQL the engine refuses, with no clean
   fix at the AST level?** Hand-write a variant in
   `sql_compat/rules/query_source/` and register a `SELECT_VARIANT`
   action.
7. **Is the platform a DataFrame engine?** Add the work to
   `unified_frame.py` or the per-engine adapter. Use the
   `dataframe_filter` phase for skip/variant decisions.

If none of these fit, the case is novel and warrants discussion. Open an
issue or a draft PR with the symptom and we will decide whether the
existing taxonomy needs to extend.

---

## Cross-References

- [ADR: `sql_compat` Phase-Aware Compatibility Pipeline](adr-sql-compat-phase-aware-pipeline.md)
  - The implementation of the rule engine that organizes everything
    described here.
- [Capability matrix](../../compat/capability-matrix.md)
  - Generated user-facing matrix of platform support levels.
- [Skip reference](../../compat/skip-reference.md)
  - Generated user-facing list of skipped queries / suppressed DDL /
    informational rules.
- [Dialect translation user guide](../../usage/dialect-translation.md)
  - User-facing distinction between dialect translation (SQLGlot) and
    platform adapters (BenchBox).
- [SQLGlot project](https://github.com/tobymao/sqlglot)
  - Upstream.
- [Fivetran post on compiling SQLGlot with mypyc (2026-05-01)](https://www.fivetran.com/blog/how-we-accelerated-transpilation-by-compiling-sqlglot-with-mypyc)
  - Context for the deferred `sqlglot[c]` adoption decision.
- BenchBox blog post: *"What we built on top of SQLGlot (and why transpilation
  isn't enough)"* in the `building-benchbox` series. External-facing
  explanation of the same boundary, written for a general SQL tooling
  audience. The published copy lives on the public BenchBox blog; the
  internal series source is under `_blog/building-benchbox/`.
