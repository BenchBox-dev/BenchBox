---
id: 2026-05-02-084332-read-primitives-cant-test-sketch-persistence
date: 2026-05-02
status: merged-to-todo
finding_kind: framework-gap
review_context: "ad-hoc research / Databricks sketch functions blog evaluation against read_primitives benchmark"
related_paths:
  - benchbox/core/read_primitives/catalog/queries.yaml
  - benchbox/core/read_primitives/benchmark.py
  - benchbox/core/read_primitives/variant_contracts.py
suggested_sweep: "before adding sketch queries, decide whether read_primitives is the right home for sketch persistence/merge tests or whether a new benchmark (or write_primitives extension) should own them"
todo_id: write-primitives-sketch-persistence-category
---

# read_primitives can score sketch *aggregates* but cannot exercise sketch *persistence*, which is the differentiated Databricks claim

## Finding

The standard "function-by-function competitor parity" framework I used to evaluate
the Databricks sketch announcement under-weights what's actually novel about the
post. The post's headline claim is not that approximate aggregates are faster
than exact ones (that's been true on every engine for a decade), but that
**sketches are storable, mergeable, requeryable artifacts** — "stored as columns
in Delta tables", "merged across time windows and partitions", "merge the
precomputed sketches in milliseconds". The `accumulate` / `combine` / `estimate`
function trio is what enables this; the single-pass `theta_sketch_agg` /
`approx_top_k` calls are the boring half of the announcement.

`read_primitives` is structurally a single-query benchmark: each query in
`catalog/queries.yaml` runs in isolation against TPC-H tables, with no facility
to (a) write a sketch column to a persisted table, (b) read sketches back in a
later query, or (c) merge sketches across partitions in a multi-query workflow.
Adding `APPROX_QUANTILES` and `APPROX_COUNT_DISTINCT` queries here measures
*aggregate latency*, which is largely uninteresting — the optimization the
vendors are competing on is the persist/merge/requery loop.

So a parity-table evaluation will conclude "yes, add the queries", and the
benchmark will technically run, but the queries we add will not exercise the
capability the post is actually announcing. This is a framework-gap: the
evaluation rubric (function name → competitor function name → add or skip)
doesn't have an axis for "does this benchmark's execution model fit the
capability under test."

## Why this matters

Whenever a vendor announces something framed as "stored, mergeable,
requeryable" — sketches, materialized aggregates, search indexes, vector
indexes, incremental MVs, ML features — a single-query benchmark catalog
cannot test the differentiated claim, only the trivial scalar-function
half. Future evaluations should explicitly ask "does the benchmark's
execution model fit the capability?" before mapping function names. The
right home for cross-query sketch persistence may be a new benchmark
(perhaps a `sketch_lifecycle` or `materialization` benchmark that writes
sketch artifacts in one phase and queries them in a later phase) or an
extension of `write_primitives` — not `read_primitives`.

## Suggested next steps

- [ ] Decide explicitly whether `read_primitives` adds *aggregate-only* sketch queries (cheap; runs everywhere; doesn't test the claim) or stays out of sketches entirely until a persistence-capable benchmark exists.
- [ ] If we want to test the persistence/merge claim, scope a new benchmark or `write_primitives` extension with a two-phase shape: phase 1 writes sketch columns to a table, phase 2 merges/queries them.
- [ ] Audit other recent vendor announcements we've evaluated against `read_primitives` for the same single-query/persistent-artifact mismatch.

## Triage log

- 2026-05-02: promoted to TODO `write-primitives-sketch-persistence-category`. The companion TODO `read-primitives-approximate-aggregate-queries` is a contributing resolver — it scopes out persistence on the read side (one-shot aggregates only) and adds the cross-platform reference doc that the write-side TODO links from. The framework gap (review rubrics needing an "execution-model fit" axis for persistence-flavored vendor announcements) is partially mitigated, not eliminated; future similar announcements (vector indexes, materialized aggregates) should still trigger an explicit fit-check before parity-mapping function names.
