# ClickBench cross-surface divergences (staged gate)

Snapshot from `make clickbench-cross-surface-equivalence-report`
(`python -m benchbox.core.equivalence.cross_surface --benchmark clickbench`) at
SF=0.1 on DuckDB, SQL as the reference for its own DataFrame surface (`expression`
= Polars, `pandas`).

The ClickBench generator is now **seeded** (`random.seed(42)` in
`_generate_data_local`), so the data is fixed and the gate is stable: three
consecutive runs reported the **identical** 27-cell divergence set (0 flaky).
Previously the unseeded generator made top-N/tie-sensitive queries flip in and out
of divergence run-to-run. Watch-item: top-N queries with ties (`LIMIT` over tied
values) could still vary on a query engine with nondeterministic tie ordering;
adding deterministic tie-breaker sort keys is the belt-and-suspenders fix before
promoting clickbench to a blocking gate.

## Fixed in this pass (all 10 engine/error-category cells)

These were hard errors, not value mismatches; all now resolved:

| Fix | Cells cleared |
| --- | --- |
| `UnifiedStrExpr.replace` added (regex replace) | Q29 |
| `UnifiedLazyFrame.slice` added (LIMIT/OFFSET) | Q39, Q40, Q41, Q42 |
| Date columns compared to native `date` literals, not strings | Q37, Q38, Q39–Q42, Q43 |
| Pandas `<> ''` filters exclude NULL (`.notna()`), matching SQL/Polars | Q25, Q27 |

## Remaining: 27 value-divergence cells (14 queries) — per-query triage

Deterministic baseline; these are genuine SQL↔DataFrame value disagreements:

| Query | expression (SQL → DF) | pandas |
| --- | --- | --- |
| Q6 | — | 18 → 17 |
| Q9 | 584 → 407 (row 8) | (same) |
| Q10 | 196 → 117 (row 4) | (same) |
| Q15 | 10 → 1 | (same) |
| Q16 | 7599 → 44197 | (same) |
| Q17 | "" → None (col 1) | (same) |
| Q18 | 2594 → 20880 | (same) |
| Q19 | 281576 → 211201 | (same) |
| Q24 | "" → None (col 14) | (same) |
| Q31 | 4 → 10 | (same) |
| Q32 | 1751543 → 549458 | (same) |
| Q33 | 183107 → 1533813 | (same) |
| Q36 | 27418322 → 288711262 | (same) |
| Q38 | Home Page → Blog (row 1) | (same) |

Patterns for the burn-down:
- **Empty-string vs None** (Q17 col 1, Q24 col 14): SQL emits `""`, the DataFrame
  surface emits `None` — a null-materialization difference; confirm the source
  value before deciding which surface is correct.
- **Large aggregate differences** (Q16/Q18/Q32/Q33/Q36): a dropped predicate,
  missing `DISTINCT`, or wrong aggregation in the DataFrame impl.
- **Top-N row-value differences** (Q9 row 8, Q10 row 4, Q38 row 1, Q15, Q31):
  likely the DataFrame top-N breaks ties differently than the SQL `ORDER BY`;
  align the sort keys/tie-breakers (now reproducible thanks to the seed).

## Status

ClickBench stays in `STAGED_GATES` (report mode), **not** `GATES`: these 26 are
real bugs, not presentational, so they must be fixed (not added to a
`known_divergences` baseline). Promote to `GATES` + a blocking `pr.yml` step only
once clean.
