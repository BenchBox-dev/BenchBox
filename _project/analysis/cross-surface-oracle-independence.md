# Cross-surface oracle: what independence each gated benchmark actually has

> Provenance: this is a hand-written, point-in-time correctness analysis. When you
> revise it against a specific tree, stamp the reviewed commit here
> (`Reviewed-at: <git-sha>`) and re-check `git merge-base --is-ancestor <sha>
> origin/develop` before publishing — see `_project/analysis/REVIEW-PROTOCOL.md`.

The cross-surface SQL↔DataFrame gate is a correctness oracle only to the extent
the two surfaces are *independent*. That independence is weaker than the phrase
"two independent implementations" implies, and it varies by benchmark. This file
records the honest per-benchmark picture (remediation **w7 / BS1**).

## The two axes of independence

1. **SQL text vs DataFrame code.** Always present, but both surfaces are authored
   by the same person from the same understanding of the query. So the oracle
   reliably catches **transcription** errors (a column, filter, join, or literal
   mistyped on one surface) but not a shared **conceptual** error (a misread of
   the intended query that the author encodes identically on both surfaces).
2. **DataFrame backend vs DataFrame backend** (Polars expression family vs
   Pandas). Present only when the benchmark hand-writes a *separate* impl per
   backend. When both backends are generated from one DSL spec row, a logic error
   in that spec appears identically on both — they are not independent of each
   other, and the only independent reference is the SQL surface.

## Per gated benchmark

| Benchmark | DataFrame impls | Backend-vs-backend independence | What a green gate proves |
| --- | --- | --- | --- |
| **ssb** | Fully DSL-generated — both backends emitted from `_QUERY_SPECS` via `_make_expression_impl` / `_make_pandas_impl` | **None** (one spec → both backends) | SQL text agrees with the shared DataFrame spec; a spec-level logic bug is invisible to backend comparison |
| **clickbench** (staged) | ~40/43 DSL-generated; a handful hand-written | **None** for the generated queries; per-query for the hand-written ones | Same as ssb for the generated majority |
| **coffeeshop** | Hand-written per query — separate `*_expression_impl` / `*_pandas_impl` | **Per-query** (two hand-written impls) | SQL ↔ DF transcription *and* Polars↔Pandas engine-semantics agreement |
| **amplab** | Hand-written per query — separate `q*_expression_impl` / `q*_pandas_impl` | **Per-query** (two hand-written impls) | Same as coffeeshop |
| **joinorder_synthetic** (staged) | See its module | per its impls | — |

## Consequence

- For **ssb** and **clickbench**, do not market the gate as "two independent
  implementations." It is SQL-vs-one-DataFrame-spec; the second backend is a
  near-copy of the first. A spec error reaches production on every backend.
- For **coffeeshop** and **amplab**, the gate has genuine backend-vs-backend
  independence (still same author), so it additionally catches engine-semantics
  divergences.
- The deeper limitation — that cross-surface proves *agreement*, not
  *correctness* against an external ground truth — is tracked as a deferred item
  in `cross-surface-oracle-remediation.yaml` (a truly independent SQL-side oracle,
  e.g. an upstream published answer set, would be required to close it).
