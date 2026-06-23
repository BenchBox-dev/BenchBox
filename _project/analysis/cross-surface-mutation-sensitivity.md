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
| `reverse_sort` | a reversed `ORDER BY` | reverse the row order, multiset preserved | **order** — the order-aware comparator (w2) compares the RETURNED order for any query whose `ORDER BY` maps to result columns, so a reversed order is a key-sequence mismatch |
| `drop_join` | a dropped/incorrect join changes a joined column value | perturb one cell to a value outside the reference | **value** check (`_values_equal`, tolerance-aware) |

## Caught-vs-uncaught matrix (verified at SF=0.1)

Each cell is the verdict for **both** backends (`expression` + `pandas`); a
"caught" mutation produced a divergence on both. Target queries were chosen to be
discriminating (multi-row, ORDER BY + GROUP BY) where the benchmark has one.

| Benchmark | Target | `flip_comparator` | `drop_group_key` | `reverse_sort` | `drop_join` |
| --- | --- | --- | --- | --- | --- |
| **ssb** | Q3.1 (149×4) | ✅ caught | ✅ caught | ✅ **caught (w2)** | ✅ caught |
| **amplab** | 4 (100×6) | ✅ caught | ✅ caught | ✅ **caught (w2)** | ✅ caught |
| **coffeeshop** | SA1 (93×5) | ✅ caught | ✅ caught | ✅ **caught (w2)** | ✅ caught |
| **clickbench** | Q8 (20×2) | ✅ caught | ✅ caught | ✅ **caught (w2)** | ✅ caught |
| **joinorder_synthetic** | 4a (1×2) | ✅ caught | ✅ caught | ⚪ no-op (single row) | ✅ caught |

Every benchmark therefore has **≥3** mutation classes the gate provably catches
(the w10 acceptance bar), and the one remaining non-catch (joinorder_synthetic's
single-row `reverse_sort`) is a degenerate no-op explained below, not a
comparator blind spot.

## The reversed-sort probe: BS2 closed by the order-aware comparator (w2)

`reverse_sort` is now **caught** on all four multi-row benchmarks — this is the
closed half of w2/BS2. Previously `ResultValidator.validate_results_exact`
(`benchbox/core/tpchavoc/validation.py`) full-row-sorted both sides and compared
positionally, so reversing the row order yielded two identical sorted lists and
the divergence was invisible. The w2 change adds an opt-in **order-aware** mode:
the cross-surface gate resolves each query's `ORDER BY` to result-column
positions (`cross_surface._order_by_result_key`, via sqlglot) and, when that
mapping succeeds, passes `order_aware=True`. The comparator then compares rows in
**returned order** — the sequence of distinct order-key values must match — while
still treating each tied group as a multiset (so a legitimate tie reshuffle is
*not* flagged) and the final group under a trailing `LIMIT` as a boundary tie (so
the tie-aware fix does not regress). A reversed `ORDER BY` produces a reversed
key sequence and is therefore reported. The dedicated
`test_reversed_sort_is_the_bs2_probe` now asserts ssb Q3.1's reversed result is
caught (and that the catch is a genuine ORDER BY mismatch, not a harness
`error:`).

The oracle is now strong on row-membership, column-shape, value, **and ordering**
bugs for any query whose `ORDER BY` key is a projected column.

### The residual, documented order blind spot

Order-awareness is engaged only when every `ORDER BY` term maps to a projected
output column. A query that sorts by a column **not in its result** cannot have
its order verified from the returned rows — e.g. clickbench Q25
(`SELECT SearchPhrase … ORDER BY EventTime LIMIT 10`) and Q24 (`SELECT * …
ORDER BY EventTime`). For those, `_order_by_result_key` returns `None` and the
gate falls back to the order-insensitive comparison rather than guess (an
order-blind fallback that silently "passed" would re-introduce exactly the BS2
gap). These are a small, enumerated set; closing them would require projecting
the sort key (which would change the canonical query) or a schema-resolved
`SELECT *` expansion, both out of scope. They are recorded here, not muted via a
baseline.

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
  degenerate outcome — it is *not* a comparator order blind spot (the order-aware
  catch is demonstrated instead on the four multi-row benchmarks above). The
  harness records this as an expected non-catch for
  `joinorder_synthetic/reverse_sort`.

The multi-row reverse-sort catch (the real BS2 probe) is established on ssb,
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

- **Closed (w2 / BS2):** the order-aware comparison mode (compare returned order,
  each tie group as a multiset, final-LIMIT group as a boundary tie) landed, so a
  reversed `ORDER BY` whose key is a projected column now flips to caught on all
  four multi-row benchmarks. `test_reversed_sort_is_the_bs2_probe` asserts the
  fixed property. The residual order blind spot (ORDER BY a non-projected column,
  e.g. clickbench Q24/Q25) is documented above, not muted via a baseline.
- The byte-stability regression promised in **w3** is included in the same suite
  (`test_gate_output_is_byte_stable_across_two_in_process_runs`): two in-process
  ssb gate runs on the same seed produce an identical divergence set.
