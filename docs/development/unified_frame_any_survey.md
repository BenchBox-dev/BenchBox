---
title: unified_frame.py `Any` annotation survey
status: living-document
owner: quality-migrate-unified-frame-any-to-protocol
last_reviewed: 2026-04-13 (w1 session)
source: docs/development/unified_frame_any_survey.csv
---

# unified_frame.py `Any` annotation survey

Outcome of w1 of `quality-migrate-unified-frame-any-to-protocol`: AST-based
inventory of every `Any` reference inside an annotation in
`benchbox/platforms/dataframe/unified_frame.py` (4,138 lines), classified
for migration.

The TODO premise estimated **82** `Any` references; the actual AST count
of `Any` *inside annotations* is **83** (one more than estimated; the
estimate was a grep, which missed `Any` nested inside generic args like
`int | Any`).

## Counts

| Slice | Count |
|---|---:|
| Total `Any` annotation references | **83** |
| Parameter annotations | 68 |
| Return annotations | 14 |
| Module-level `AnnAssign` | 1 |

## Category breakdown

The classification follows the TODO's three buckets:

| Category | Count | Migration target |
|---|---:|---|
| **(a) generic dispatch** | **25** | `LazyFrameLike` (the protocol shipped by the parent TODO) |
| **(b) library-specific** | **38** | concrete types behind `TYPE_CHECKING` imports |
| **(c) genuine escape hatch** | **20** | keep `Any`, add inline rationale comment |

## Top recommended destinations (rankable migration targets)

| Recommended type | Sites |
|---|---:|
| `LazyFrameLike` | 25 |
| `Any (keep)` | 20 |
| DataFusion expression/df concrete types | 18 |
| `pyspark.sql.DataFrame` | 11 |
| Backend expression concrete types (Polars/PySpark expr) | 9 |

## Classification heuristics applied

A simple rule-driven classifier was used (see `tools/survey_unified_frame_any.py`
output). Sites flagged as ambiguous (~category c with note `needs human review`)
should be inspected by hand before w4 commits land.

| Heuristic | Mapping |
|---|---|
| Scope contains `pyspark` or `_pyspark_` | (b) `pyspark.sql.DataFrame` |
| Scope contains `datafusion` / `_is_datafusion` / `_extract_datafusion` / `_apply_datafusion` | (b) DataFusion concrete |
| Param name in {`kwargs`, `params`, `options`, `config`, `metadata`, `extra`, `kw`} | (c) keep `Any` |
| Annotation matches `dict[str, Any]` or ends with `Any]` | (c) keep `Any` (heterogeneous dict value) |
| Param name in {`df`, `frame`, `other`, `right`, `left`, `native`, `src`} | (a) `LazyFrameLike` |
| Param name contains `expr` | (b) concrete backend expression |
| Return annotation otherwise | (a) `LazyFrameLike` (frame-shaped return) |
| Otherwise | (c) keep `Any` (needs human review) |

## Observations

1. **PySpark and DataFusion drive most category-(b) sites (29 of 38).**
   Their helpers don't accept arbitrary frames - they accept *concretely*
   PySpark `DataFrame` / DataFusion `DataFrame` or expression objects.
   Forcing `LazyFrameLike` here would be incorrect.
2. **Generic-dispatch sites cluster on `UnifiedLazyFrame` core methods**
   (`join`, `_pyspark_join`, etc.). These are the highest-impact
   migrations and should land first under w2.
3. **The 20 escape-hatch sites are dominated by passthrough kwargs and
   heterogeneous result dicts.** Each needs a one-line `# Any: <reason>`
   comment so future readers know not to "fix" them.
4. **One module-level `AnnAssign`** - likely a class-level attribute
   typed as `Any`. Worth a manual look before deciding migration target.
5. The estimate of "82 Any references" in the parent TODO was a grep
   count; the AST count is 83. Difference is small but pin the AST
   number for w5 verification.

## Per-category w-unit assignments

| Category | Owner work unit | Suggested batching |
|---|---|---|
| (a) - 25 sites (heuristic; ~2 verified) | w2 | small slices, manual verification per site |
| (b) - 38 sites (heuristic) | w3 | two commits (PySpark family ~11, DataFusion family ~18, plus stragglers ~9) |
| (c) - 20 sites (heuristic) | w4 | one commit, comment-only |

## Heuristic limitations (added during w2)

The w1 classifier was too eager about category (a). When the w2 migration
began, hand-verification revealed several false positives that must be
re-classified before any large batch lands:

| CSV row | Site | Heuristic | Actual | Why |
|---|---|---|---|---|
| line 742 | `UnifiedExpr.native -> Any` | (a) `LazyFrameLike` | (b) concrete backend expr | returns the underlying expression object, not a frame |
| lines 753-978 (16 dunder ops) | `UnifiedExpr.__add__/__sub__/__mul__/__eq__/...(other: Any)` | (a) `LazyFrameLike` | (c) keep `Any` | `other` is a scalar / `UnifiedExpr` / column-name string, never a frame |
| line 2115 | `_is_polars_df(df)` | (a) `LazyFrameLike` | (b) `polars.DataFrame` | Polars-specific isinstance check |
| line 3156 | `_polars_join_with_exprs(other)` | (a) `LazyFrameLike` | (b) `polars.LazyFrame` | scope contains `_polars_*` (heuristic only checked `pyspark`/`datafusion`) |
| line 4001 | `UnifiedLazyFrame.collect() -> Any` | (a) `LazyFrameLike` | (c) keep `Any` | returns materialized data (Polars `DataFrame`, list of rows, etc.), not a lazy frame |
| line 4069 | `UnifiedLazyFrame.scalar() -> Any` | (a) `LazyFrameLike` | (c) keep `Any` | returns a scalar value |

**Net of corrections, the genuine category-(a) sites are roughly:**

| Verified site | Status |
|---|---|
| `wrap_dataframe(df: Any, adapter)` (line 4128) | migrated in w2 commit 1 |
| `UnifiedLazyFrame.join(other: UnifiedLazyFrame \| Any)` (line 2659) | migrated in w2 commit 1 (tightened `\| Any` → `\| LazyFrameLike`) |
| Remaining (a) candidates | need per-site hand verification before w2 batch 2 |

**Lesson for w3/w4:** the same heuristic over-assignment likely contaminates
the (b) and (c) bins. Re-walk each site before edits land.

## Re-classification log (added during w3 batches)

Hand verification of the (b) bin during w3 batch migrations surfaced
further heuristic mistakes. The corrected mappings:

| CSV row | Site | Heuristic (b) note | Actual | Why |
|---|---|---|---|---|
| line 85 | `_is_polars_expr(expr)` | concrete backend expr | (c) keep `Any` | runtime probe; called *before* backend type is known |
| line 91 | `_is_datafusion_expr(expr)` | concrete backend expr | (c) keep `Any` | runtime probe; same as `_is_polars_expr` |
| line 728 | `UnifiedExpr.__init__(expr)` | concrete backend expr | (c) keep `Any` | accepts any backend's native expr OR scalar literal; narrowing forces opt-dep imports |
| lines 107, 291, 471, 518, 573, 705 | `Unified{Str,List,Map,Dt,Struct}Expr.__init__(expr)` | concrete backend expr | (c) keep `Any` | inherit the `UnifiedExpr.__init__` rationale; comment lives on the parent |
| line 2117 | `wrap_expr(expr)` | concrete backend expr | (c) keep `Any` | same - accepts any backend's native expr |
| line 2155 | `_is_pyspark_column(expr)` | concrete backend expr | (c) keep `Any` | runtime probe |

**Genuine (b) sites successfully migrated in w3:**

| Site | Migration |
|---|---|
| `_polars_join_with_exprs(other, return)` | `pl.DataFrame \| pl.LazyFrame` |
| `_pyspark_join` / `_cross_join` / `_join_expr` / `_join_multi_expr` (4 methods × 2 sites) | `pyspark.sql.DataFrame` |
| `_apply_datafusion_post_ops`, `_datafusion_join_with_exprs` | `datafusion.DataFrame` |
| `_get_datafusion_ast_string`, `_rebuild_datafusion_pure_aggregate`, `_extract_datafusion_agg_arithmetic` | `datafusion.Expr` |
| `_DataFusionSplitListExpr.__init__`, `_DataFusionSplitListExpr.get`, `_DataFusionDeferredRank.__init__` (3 expressions × 1-2 params) | `datafusion.Expr` |
| `_DataFusionDeferredFilter.__init__` (expr + condition) | reverted to `Any` after review - call site unwraps `.native` (which is `Any`); see commit 0a58d15e2 |
| `_PySparkDeferredRank.__init__` | `pyspark.sql.Column` |

CSV at [`unified_frame_any_survey.csv`](./unified_frame_any_survey.csv).
