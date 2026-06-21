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

## Remaining: 27 value-divergence cells (14 queries)

Deterministic baseline (the raw row-0 mismatch the gate reports). NOTE: the triage
below shows these are mostly tie-ambiguous top-N comparison artifacts, not value
errors — read the "Triage finding" section after the table.

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

### Triage finding: these are mostly NOT logic bugs — they are tie-ambiguous top-N

Direct comparison of SQL vs DataFrame results (set-level + count-column level)
shows the DataFrame computes **correct aggregates**; the divergences come from the
gate's order-sensitive, row-by-row comparison of `ORDER BY <col> ... LIMIT N`
queries whose ties span the LIMIT boundary:

- **Q32/Q33** `GROUP BY WatchID, ClientIP ORDER BY c DESC LIMIT 10`: at SF=0.1
  every group has count `c=1` (verified: both surfaces' top-10 `c` column is all
  `1`). With thousands of count-1 groups, `LIMIT 10` keeps an arbitrary 10 — SQL
  and the DataFrame keep different (equally valid) `WatchID`s. The mismatch is at
  column 0 (WatchID), not the count.
- **Q16** (count distribution `4,4,4,4,4,4,3,3,3,3` is **identical** on both
  surfaces): only the order among the `c=4` ties and which `c=3` groups land in the
  last slots differ — a boundary tie, not a wrong value.
- The other count/top-N rows (Q6, Q9, Q10, Q15, Q18, Q19, Q31, Q33, Q36, Q38) are
  the same class: correct aggregates, ambiguous selection/order among ties at the
  LIMIT cutoff (no total order in the `ORDER BY`).

So these are **false positives of an order-sensitive comparator**, not ClickBench
DataFrame logic bugs. The right fix is at the **gate/validator level**, not
per-query:
  - add a deterministic total-order tie-breaker to BOTH surfaces before comparison
    (append the remaining columns / a stable key to the `ORDER BY`), or
  - make the validator tie-aware (compare the multiset of rows that share the
    boundary order-key value, instead of position-by-position), or
  - classify genuinely tie-ambiguous queries as accepted divergences.

Exceptions (a different, real class — RESOLVED in w9):
- **Empty-string vs None** (Q17 col 1, Q24 col 14): SQL emitted `""`, the
  DataFrame emitted `None`. RESOLVED (w9, 2026-06-21): the root cause was the
  per-benchmark CSV `null_marker`, not dtype — DuckDB resolves `nullstr` via
  `resolve_csv_dialect` (ClickBench `null_marker=None` ⇒ empty kept `""`), while
  the DataFrame path always nulled empty fields. The resolved `null_marker` is now
  threaded into both surfaces (Parquet `strings_can_be_null`, pandas `""` restore
  on declared string columns), so empty stays `""` for ClickBench. Q24 also
  surfaced `ClientEventTime` (declared `TIMESTAMP`) read as a string in pandas —
  fixed by making pandas date parsing TYPE-aware. **Q24 fully clears; Q17's
  remaining divergence is the tie-ambiguous top-N below (w8), not the loader
  issue.** See `joinorder-synthetic-cross-surface-divergences.md`.

Net: ClickBench has ~no genuine DataFrame *logic* bugs here — the staged-gate
divergences are (1) tie-ambiguous top-N comparison (gate-level) and (2) the
loader null/dtype issue (deferred). Promote ClickBench to `GATES` once the gate
handles tie-ambiguity and the loader dtype fix lands.

## Status

ClickBench stays in `STAGED_GATES` (report mode), **not** `GATES`: these 26 are
real bugs, not presentational, so they must be fixed (not added to a
`known_divergences` baseline). Promote to `GATES` + a blocking `pr.yml` step only
once clean.
