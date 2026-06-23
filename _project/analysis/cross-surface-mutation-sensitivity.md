# Cross-surface oracle: mutation-sensitivity evidence (w10 / C2)

The cross-surface SQL↔DataFrame campaign measured only that the gates **pass**
(specificity). It never measured whether they **catch a seeded bug**
(sensitivity). PR #859 added a single planted-divergence regression per enforced
gate, but there was no *systematic* mutation suite. This file records the
systematic result: for every enforced gated benchmark (read live from
`benchbox.core.equivalence.cross_surface.GATES`) we inject a known DataFrame-side
error into one query and observe whether the **real** gate machinery
(`find_cross_surface_divergences`, driving the reused `ResultValidator`) goes RED.

The harness lives in
`tests/integration/test_cross_surface_mutation_sensitivity.py`. It wraps the
target query's DataFrame impl at test time (via `dataclasses.replace` on the
`DataFrameQuery`) — it never edits the production query registries — runs the
real impl, materializes its rows through the same `materialize_rows` the gate
uses, applies one controlled perturbation, and returns the mutated rows. The
comparator is exercised end to end on the bounded SF=0.1 cell.

## Mutation classes

Each mutation models the **observable result shape** of a real DataFrame logic
bug of that class, and is designed to exercise a distinct detection path of the
comparator:

| Mutation | Models | Result-shape change | Detection path |
| --- | --- | --- | --- |
| `flip_comparator` (`<` → `<=`) | a relaxed filter admits boundary-equal rows | append a duplicate boundary row → +1 row | **row-count** check (first check in `validate_results_exact`) |
| `drop_group_key` | grouping on fewer keys changes the row shape | drop the leading column from every row | **column-count** check (per-row width) |
| `reverse_sort` | a reversed `ORDER BY` | reverse the row order, multiset preserved | **order** — the comparator full-row-sorts both sides, so there is none |
| `drop_join` | a dropped/incorrect join changes a joined column value | perturb one cell to a value outside the reference | **value** check (`_values_equal`, tolerance-aware) |

## Caught-vs-uncaught matrix (verified at SF=0.1)

Each cell is the verdict for **both** backends (`expression` + `pandas`); a
"caught" mutation produced a divergence on both. Target queries were chosen to be
discriminating (multi-row, ORDER BY + GROUP BY) where the benchmark has one.

| Benchmark | Target | `flip_comparator` | `drop_group_key` | `reverse_sort` | `drop_join` |
| --- | --- | --- | --- | --- | --- |
| **ssb** | Q3.1 (149×4) | ✅ caught | ✅ caught | ❌ **not caught** | ✅ caught |
| **amplab** | 4 (100×6) | ✅ caught | ✅ caught | ❌ **not caught** | ✅ caught |
| **coffeeshop** | SA1 (93×5) | ✅ caught | ✅ caught | ❌ **not caught** | ✅ caught |
| **clickbench** | Q8 (20×2) | ✅ caught | ✅ caught | ❌ **not caught** | ✅ caught |
| **joinorder_synthetic** | 4a (1×2) | ✅ caught | ✅ caught | ⚪ no-op (single row) | ✅ caught |

Every benchmark therefore has **≥3** mutation classes the gate provably catches
(the w10 acceptance bar), and every uncaught cell is explained below.

## The reversed-sort result is the headline BS2 probe

`reverse_sort` is **not caught** on any of the four multi-row benchmarks. This
**confirms** the unresolved half of w2/BS2: `ResultValidator.validate_results_exact`
(`benchbox/core/tpchavoc/validation.py`) calls `sorted(original_results)` and
`sorted(variant_results)` and compares positionally, so reversing the row order
of a result yields two identical sorted lists — the divergence is invisible. A
genuinely reversed `ORDER BY` in a gated DataFrame query would pass the gate
silently. The dedicated `test_reversed_sort_is_the_bs2_probe` pins this on
ssb Q3.1; if a future comparator change makes ORDER BY visible, that test flips
and forces this doc and the harness's `_EXPECT_CAUGHT` table to be updated.

This is honest evidence about the oracle's strength, not a failure of the
harness: the oracle is strong on row-membership, column-shape, and value bugs,
and **blind to pure ordering bugs**. It is tracked as the open half of **w2**
(BS2). It is *not* added to any `known_divergences` baseline (that would be the
exact anti-pattern the remediation flagged); it is recorded here as a sensitivity
gap with a tracking item.

### Why this blind spot is bounded in practice

A pure ordering bug that preserves the exact result multiset is the only thing
this misses. Any ordering bug that *also* changes which rows survive a `LIMIT`
(the common case for a top-N) changes the row multiset and is caught by the
row-count / value paths. The residual exposure is a reversed (or otherwise
permuted) `ORDER BY` on a result whose rows are all returned — exactly the case
`reverse_sort` models. Closing it requires the order-aware comparison mode
specified in w2 (compare the ordered prefix up to the first tie group exactly).

## Single-row + mostly-NULL caveat: joinorder_synthetic

Every gated `joinorder_synthetic` query is a single-row scalar aggregate
(verified at SF=0.1: all 13 queries return exactly one row). Worse, **most of
them return all-NULL** at the bounded cell — these are JOB-style "find the
min/argmin matching row" queries whose match simply does not exist in the
SF=0.1 data, so the aggregate is NULL (1a/1b/5a/6a/7a/8a/9a/10a/11a/12a are all
`(None, …)`). That is a **BS3-vacuous** result: a NULL-vs-NULL comparison is
non-discriminating, and a value mutation has nothing to perturb. This is itself
honest evidence — the gate is *running* on these queries but proving little at
SF=0.1; see w4 (vacuous-cell hygiene). The mutation target is therefore **4a**,
one of the few queries that returns a non-NULL row (`('3.2', 'A Action Action')`),
so its drop_join can land a real value mismatch:

- `flip_comparator`, `drop_group_key`, `drop_join` are all caught (row-count,
  column-count, and value paths respectively work on a single row; drop_join
  perturbs the rightmost string column, yielding a genuine value mismatch — not
  an `error:`).
- `reverse_sort` is a **no-op**: reversing a one-element list changes nothing, so
  no divergence is injected and none is reported. This is the expected,
  degenerate outcome — it is *not* the comparator's order-blindness (which is
  demonstrated instead on the four multi-row benchmarks above). The harness
  records this as an expected non-catch for `joinorder_synthetic/reverse_sort`.

The multi-row reverse-sort blindness (the real BS2 probe) is established on ssb,
amplab, coffeeshop, and clickbench, so joinorder_synthetic's single-row shape
does not weaken the headline finding.

## Note on clickbench target choice

The clickbench target is **Q8** (`GROUP BY AdvEngineID ORDER BY COUNT(*) DESC`,
**no** trailing `LIMIT` → the strict comparator, with a discriminating order
key). The obvious multi-key candidate, Q31, is vacuous for value mutations at
SF=0.1: its `COUNT(*)` order key is constant (every one of its 10 rows ties at
1) *and* it carries a trailing `LIMIT`, so the tie-aware path accepts any
single-row perturbation as an equally-valid boundary swap (a BS3-adjacent
artifact). Q8 avoids both, so its `drop_join` value mutation is genuinely caught.

## Tracking

- **Open (w2 / BS2):** reversed `ORDER BY` passes the gate silently. Add the
  order-aware comparison mode (ordered prefix exact, boundary tie as multiset) so
  this mutation flips to caught. The `test_reversed_sort_is_the_bs2_probe`
  regression will detect the moment that lands.
- The byte-stability regression promised in **w3** is included in the same suite
  (`test_gate_output_is_byte_stable_across_two_in_process_runs`): two in-process
  ssb gate runs on the same seed produce an identical divergence set.
