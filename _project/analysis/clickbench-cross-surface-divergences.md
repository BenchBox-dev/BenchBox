# ClickBench cross-surface divergences — RESOLVED (enforced gate)

Snapshot from `make clickbench-cross-surface-equivalence-report`
(`python -m benchbox.core.equivalence.cross_surface --benchmark clickbench`) at
SF=0.1 on DuckDB, SQL as the reference for its own DataFrame surface (`expression`
= Polars, `pandas`).

**Status: ClickBench is GREEN with an empty baseline and is promoted from
`STAGED_GATES` to `GATES` (enforced).** The remediation below closed every class
of divergence the staged gate had reported. Gate is byte-stable across runs
(seeded data + single-threaded SQL reference + tie-tolerant comparator); proven
by `tests/integration/test_clickbench_cross_surface_equivalence.py`.

## Correcting the #848 record

PR #848 concluded ClickBench had "~no genuine DataFrame logic bugs" and triaged
all 27 divergences as tie-ambiguous top-N. That was **wrong on two counts**, both
now fixed:

1. **Q6/Q17/Q18/Q24 were REAL bugs**, not ties. The DataFrame loaders mapped an
   empty CSV field to `None`/`NaN` while the SQL reference (DuckDB `nullstr`)
   keeps `''`. ClickBench's schema is `NOT NULL` and its queries filter with
   `<> ''`, so this silently changed results:
   - **Q6** `COUNT(DISTINCT SearchPhrase)` `18 → 17` — a scalar with no `ORDER BY`
     and no `LIMIT`, so a tie is impossible; `nunique()` dropped the null'd ''.
   - **Q17/Q18** `GROUP BY ... SearchPhrase` — pandas `groupby(dropna=True)`
     silently dropped ~74k null-key rows, running the query over ~25% of the data.
   - **Q24** `SELECT * ... ORDER BY EventTime` — `''` vs `None` in output columns
     (and two all-empty `TEXT` columns the loader inferred as null, plus two
     `TIMESTAMP` columns pandas loaded as strings).
2. **The genuine ties were real**, but the gate's positional comparator turned
   them into noise. ClickBench is dominated by `ORDER BY <aggregate> [DESC]
   LIMIT N` over heavily tied aggregates (e.g. Q16/Q32/Q33: most groups have
   `count = 1`), so each engine returns a different but equally-valid slice of the
   tied rows at the LIMIT boundary.

## How each class was resolved

| Class | Cells | Resolution |
| --- | --- | --- |
| Empty-string → NULL conflation (real bug) | Q6, Q17, Q18, Q24, and `<> ''` filters | Loader honors `csv_null_marker` (ClickBench declares `None`): empty fields stay `''` on both the parquet and pandas CSV load paths. `TEXT`/`STRING` columns are typed (all-empty columns stay `''`); `TIMESTAMP`/`DATE` columns parse by declared type. |
| Genuine ORDER BY/LIMIT ties | Q9, Q10, Q15, Q16, Q17, Q18, Q19, Q24, Q31, Q32, Q33, Q36, Q38 | Order-aware, tie-tolerant comparator: the ordered prefix is compared exactly (a reversed/missing `ORDER BY` or a wrong interior row is still caught), and only the ambiguous LIMIT-boundary tie group is compared by size+key, not by member identity. |
| Impl/type errors (already fixed in a prior pass) | Q25, Q27, Q29, Q37–Q43 | `UnifiedStrExpr.replace`, `UnifiedLazyFrame.slice`, native-`date` comparison; the Q25/Q27 None/NaN sort crash is additionally fixed by the None-safe comparator. |

Result at SF=0.1: **0 divergent / 86 cells** (43 queries × 2 backends), empty
`known_divergences` baseline. SSB and coffeeshop gates stay 0-divergent; TPC-Havoc
SQL (220) and DataFrame (440) gates stay 0-divergent (the comparator change is
additive). joinorder_synthetic improved 10 → 2 as a side effect and stays staged
until its 2 pre-existing pandas string-dtype cells (4a/12a) burn down.

## Sensitivity (the comparator did not just go blind)

The tie tolerance is bounded to the LIMIT-boundary group; interior rows and the
order-key sequence are matched exactly. Proven by unit tests
(`test_tpchavoc_validation_coverage.py::TestValidateResultsOrdered`): a reversed
`ORDER BY` and a wrong interior tie-group row both raise, a `None`-vs-value
difference is a clean MISMATCH (never a sort crash), and the SSB planted-defect
integration test still fails as required.

## Determinism

The generator is seeded (`random.seed(42)`), the SQL reference runs single-thread
(`PRAGMA threads=1`), and the tie-tolerant comparator absorbs cross-engine tie
order — so the gate output is identical run-to-run. A `seed(42)` alone does NOT
make the gate deterministic; the comparator and single-thread do. (An explicit
per-query total-order tie-breaker — the original "belt and suspenders" idea — was
not needed and would have required rewriting every query and impl.)
