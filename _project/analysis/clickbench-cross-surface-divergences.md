# ClickBench cross-surface divergences (staged gate)

Snapshot from `make clickbench-cross-surface-equivalence-report`
(`python -m benchbox.core.equivalence.cross_surface --benchmark clickbench`) at
SF=0.1 on DuckDB, SQL as the reference for its own DataFrame surface (`expression`
= Polars, `pandas`).

## Correction to the earlier "no logic bugs" record (cross-surface-oracle-remediation w1/w5)

An earlier pass concluded *"ClickBench has ~no genuine DataFrame logic bugs — the
divergences are tie-ambiguous top-N (gate-level) and a deferred loader null/dtype
issue."* **That conclusion was wrong**, on two counts, both reproduced by re-running
the gate (not trusted from a prior snapshot):

1. **The generator is NOT seeded, and the gate is NOT stable.** Three identical
   runs returned **26 → 25 → 26** divergent cells with per-query values changing
   run-to-run. The generated *data* is byte-identical only if seeded; it is not, so
   the row sets wobble. Even with fixed data the wobble would persist, because the
   surviving cause is **engine tie-ordering** under `LIMIT` without a total
   `ORDER BY` (DuckDB/Polars thread parallelism), not the data. `random.seed(42)`
   would make the data reproducible but would **not** make the gate deterministic —
   a deterministic total-order tie-breaker + single-threaded execution is what does
   (tracked as **w3**). A `known_divergences` baseline is un-pinnable until then.

2. **Q6 / Q17 / Q18 / Q24 were real null-handling logic bugs, not ties or cosmetics.**
   The DataFrame production loader mapped empty string `''` to null/NaN, while the
   SQL reference (DuckDB) keeps `''`. This is not presentational — it changes
   `COUNT(DISTINCT)` and `GROUP BY` membership:

   - **Q6** `SELECT COUNT(DISTINCT SearchPhrase)` — a scalar with **no** `ORDER BY`
     and **no** `LIMIT`, so a tie is impossible. SQL=18, pandas=17. Root cause:
     `SearchPhrase` has ~75k empty strings / 0 nulls; the loader turned them into
     null and pandas `.nunique()` dropped the null. A genuine off-by-one logic bug
     that the earlier pass mislabeled "tie-ambiguous."
   - **Q17 / Q18** `GROUP BY UserID, SearchPhrase` — pandas default
     `groupby(dropna=True)` silently dropped every null-key row, so the query ran
     over ~75% of the data. The group **count-multiset** differed, which a boundary
     tie cannot cause.
   - **Q17 col-1 / Q24** `"" → None` — the same root cause the earlier pass deferred
     as a cosmetic "dtype" issue. It is the same null bug, not a separate cosmetic
     one.

   **Fixed at the loader contract (w1)**, on the two load paths the gate exercises:
   - Parquet path: `FormatConverter.convert_csv_to_parquet` now passes
     `strings_can_be_null=False` (PyArrow's default `null_values` contains `''`, so
     `True` coerced empties to null); cache version bumped `v3 → v4`. The gate's
     Polars (`expression`) surface loads via Parquet (its recommended format), so
     this is what fixes Polars.
   - Pandas CSV path: `PandasDataFrameAdapter.read_csv` reads declared string
     columns as text (so an all-digit VARCHAR keeps `'007'`/`'10'` verbatim) and
     restores `''` for their empty fields (`pd.read_csv` maps `''` → NaN by
     default). Pandas's recommended format is CSV, so this is what fixes pandas.

   Note: Polars `scan_csv` does NOT keep `''` (it maps an empty unquoted field to
   null); the gate avoids that path because the Polars adapter loads Parquet. The
   raw-CSV read paths of the non-Parquet adapters (Polars `scan_csv`, modin, dask,
   cudf) still emit null for empty string fields and would reintroduce this
   divergence under `prefer_parquet=False`. Closing that across every adapter is
   tracked under **w6** (drive a real production-loader-path gate cell through each
   adapter); it is out of scope for the two surfaces this gate compares.

   After w1, all three surfaces agree: `SearchPhrase` = 0 nulls / 37,404 empties /
   18 distinct at SF=0.1; the Q17/Q18 full `GROUP BY` covers all rows on every
   surface (e.g. 50,000 rows / 49,298 groups identical across DuckDB, Polars,
   pandas). **Q6 is gone from the divergence set.** Pinned by unit tests on both
   load paths (`test_convert_empty_string_column_stays_empty_not_null`,
   `test_read_csv_empty_string_column_stays_empty_not_null`).

## Genuine fixes from the original campaign (still valid)

These were hard errors, not value mismatches; all resolved earlier and unchanged:

| Fix | Cells cleared |
| --- | --- |
| `UnifiedStrExpr.replace` added (regex replace) | Q29 |
| `UnifiedLazyFrame.slice` added (LIMIT/OFFSET) | Q39, Q40, Q41, Q42 |
| Date columns compared to native `date` literals, not strings | Q37, Q38, Q39–Q42, Q43 |
| Pandas `<> ''` filters exclude NULL (`.notna()`), matching SQL/Polars | Q25, Q27 |

## Remaining after w1: the tie-ambiguous / nondeterminism class (needs w2 + w3)

With the null bugs fixed, the residual divergences are the genuine
tie-ambiguous-top-N / engine-nondeterminism class — and only this class:
**Q9, Q10, Q15, Q16, Q19, Q31, Q32, Q33, Q36, Q38** (plus any boundary-tie rows of
Q17/Q18/Q24 that survive `LIMIT`). These are `ORDER BY <col> ... LIMIT N` queries
whose ties span the `LIMIT` boundary, so each engine returns a different but
equally-valid row set/order; the gate's position-by-position comparator flags them.

These are **not** ClickBench DataFrame logic bugs — the aggregates agree; the
selection/order among ties at the cutoff differs. The fix is at the comparator and
the determinism layer, not per-query:

- **w2** — make the comparator order-aware and tie-aware: compare the ordered
  prefix up to the first tie group exactly, then compare the boundary-key rows as a
  multiset. (Must stay additive — TPC-Havoc relies on the shared validator.)
- **w3** — pin engine nondeterminism: single-threaded gate execution + a
  deterministic total-order tie-breaker before any `LIMIT` on both surfaces.

Until w2 + w3 land, ClickBench cannot be deterministically green and its residual
cells cannot be cleanly re-triaged; w5's full closeout depends on them.

### w9 update (2026-06-21): empty-string/None and TIMESTAMP dtype resolved

The Q17 col-1 / Q24 `"" → None` divergence is resolved at the loader. The root
cause was the per-benchmark CSV `null_marker`, not dtype: DuckDB resolves
`nullstr` via `resolve_csv_dialect` (ClickBench `null_marker=None` ⇒ empty kept
`""`), while the DataFrame path previously always nulled empty fields. The
resolved `null_marker` is now threaded into both surfaces (Parquet
`strings_can_be_null`, pandas `""` restore on declared string columns), so empty
stays `""` for ClickBench **and** stays NULL for `null_marker=""` datasets (e.g.
joinorder_synthetic — this conditioning is what w9 adds over w1's unconditional
fix). Q24 also surfaced `ClientEventTime` (declared `TIMESTAMP`) read as a string
in pandas — fixed by making pandas date parsing TYPE-aware. Q24 fully clears;
Q17's remaining divergence is the tie-ambiguous top-N above (w2/w3), not the
loader issue. See `joinorder-synthetic-cross-surface-divergences.md`.

## Status

ClickBench stays in `STAGED_GATES` (report mode), **not** `GATES`. Per the
remediation anti-patterns, a staged gate is **not** promoted to `GATES` while it is
nondeterministic or has a non-empty baseline — green + empty + deterministic first.
Promotion (and a blocking `pr.yml` step) is gated on w2 + w3, then a clean
re-triage (w5). Do **not** silence the residual cells via `known_divergences` — the
remaining differences are real tie/order artifacts to fix at the comparator, not
presentational exceptions.
