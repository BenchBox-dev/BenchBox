# ClickBench cross-surface divergences (staged gate)

Snapshot from `make clickbench-cross-surface-equivalence-report`
(`python -m benchbox.core.equivalence.cross_surface --benchmark clickbench`) at
SF=0.1 on DuckDB. SQL is the reference for its own DataFrame surface; both
backends (`expression`/polars, `pandas`) are compared.

**Result: 32 of 86 query-backend cells divergent.** The build is load-faithful
(SQL loads via the production DuckDB loader with the real schema; DataFrame
contexts via the production loader), so these are genuine SQL<->DataFrame
disagreements, not build artifacts. ClickBench is therefore registered as a
STAGED gate (runnable in report mode) — **not** an enforced `GATES` entry — until
the divergences below are burned down. It stays UNGUARDED in the oracle coverage
map.

## A. DataFrame engine/abstraction gaps (10 cells) — highest priority

These are missing capabilities in the shared DataFrame abstraction; they block
several queries on the `expression`/`pandas` backends and should be fixed at the
engine layer (one fix clears multiple queries):

| Symptom | Cells |
| --- | --- |
| `'UnifiedLazyFrame' object has no attribute 'slice'` | Q39, Q40, Q41, Q42 (expression) |
| `'UnifiedStrExpr' object has no attribute 'replace'` | Q29 (expression) |
| `cannot compare 'date/datetime/time' to a string value` | Q37, Q38, Q43 (expression) |
| `'<' not supported between 'str' and 'NoneType'` | Q25, Q27 (pandas) |

## B. Value divergences (22 cells) — per-query triage

The DataFrame surface returns different values than SQL. Several are clearly real
logic bugs (not small-SF ordering ties): e.g. Q32/Q33 on pandas return ≈ the full
row count (9,994,262), implying a missing filter/`DISTINCT`; Q36 differs by ~6-16x.

| Query | expression (SQL → DF) | pandas (SQL → DF) |
| --- | --- | --- |
| Q6 | — | 18 → 17 |
| Q14 | games → education | — |
| Q15 | 6 → 9 (row 1) | — |
| Q16 | 77766 → 138185 | 77766 → 138185 |
| Q17 | "" → None (col 1) | 138185 → 87538 |
| Q18 | 85246 → 7233 | 85246 → 6 |
| Q19 | 6597 → 43822 | 6597 → 6 |
| Q24 | "" → None (col 14) | "" → None (col 14) |
| Q31 | 0 → 1 | 0 → 50 |
| Q32 | 1075964 → 817388 | 1075964 → 9994262 |
| Q33 | 185610 → 821440 | 185610 → 9994262 |
| Q36 | 171949499 → 1002602998 | 171949499 → 2870038854 |
| Q38 | (date-compare error, group A) | About Us → Blog |

Sub-notes:
- **Empty-string vs None** (Q17 col 1, Q24 col 14): SQL emits `""`, the DataFrame
  surface emits `None`. Likely a null-handling difference in DataFrame
  materialization; confirm whether the source value is genuinely empty or NULL
  before deciding which surface is correct (do not mute as "presentational").
- **≈full-row-count results** (Q32/Q33 pandas = 9,994,262): a dropped predicate /
  missing `DISTINCT` in the DataFrame impl — real logic bug.

## Burn-down dispatch (cross-surface gate w3)

1. Fix the group-A engine gaps first (`UnifiedLazyFrame.slice`,
   `UnifiedStrExpr.replace`, date/string comparison, str/None comparison) — these
   clear ~10 cells and likely benefit other benchmarks' DataFrame surfaces.
2. Triage group-B value divergences per query against the SQL reference; fix the
   wrong surface (usually the DataFrame impl) without changing query identity.
3. When clean, promote `clickbench` from `STAGED_GATES` into `GATES`, add a
   `clickbench-cross-surface` blocking step to `.github/workflows/pr.yml`
   (mirroring SSB), and a fast-lane regression.
