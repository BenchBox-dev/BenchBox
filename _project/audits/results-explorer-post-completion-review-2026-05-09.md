---
develop_sha: dbac33ee16d93b4b651d6b26d1dec02bd5c74e5a
---

# Results Explorer Post-Completion Review — 2026-05-09

**Develop SHA reviewed:** `dbac33ee1`
**Reviewer date:** 2026-05-09
**Scope:** Post-completion acceptance pass over the Results Explorer follow-up
work that landed before `dbac33ee1`. Findings here are the originating
record for the six `_project/TODO/main/planning/results-explorer-post-completion-*.yaml`
items; numeric finding ids in those TODO descriptions resolve to the table
below.

## Methodology

- Started a clean Vite dev server from `dbac33ee1` and exercised the
  routes listed under each finding from a desktop browser.
- Recorded selected-tab state, table contents, accessible names, link
  targets, and rendered copy where the observation was about UX.
- Cross-referenced linked detail pages against leaderboard/cell state
  for data-consistency findings.
- A defect was recorded only when the observed behaviour was
  reproducible from a fresh page load on `dbac33ee1`.

## Severity legend

- **P0** — blocks the canonical workflow that the page exists to
  support (e.g. cannot start a comparison from where compatible runs
  are surfaced).
- **P1** — produces incorrect or self-contradicting claims to the
  user, but the page still partially functions.
- **P2** — degrades trust or polish; defensible but visible.

## Findings

| # | Title | Area | Severity | Route(s) | Observation | Owning TODO |
|---|---|---|---|---|---|---|
| 1 | Benchmark-detail compare checkboxes render at 0×0 and cannot be clicked | Compare entrypoint | P0 | `/results/tpch/` | Compare-selection checkbox column is present in DOM but bounding boxes are 0×0; no visible proxy control; selecting two rows never enables a compare action. | compare-selection-recovery |
| 2 | Compare picker hides compatible second choices below the viewport after the first selection | Compare picker | P0 | `/results/compare` | After picking one row, compatible rows are not promoted; user must scroll past hundreds of disabled incompatible rows to find a second compatible run. | compare-selection-recovery |
| 3 | Query Workbench leaves every visible row disabled while Compare still says "need 2+" | Compare entrypoint | P0 | `/results/query` | Same off-screen-compatibles trap as #2 plus a misleading Compare prompt; the page never recovers from the first selection. | compare-selection-recovery |
| 4 | Cross-Benchmark Leaderboard renders linked "No run" for TPC-H Polars SF 0.1 | Leaderboard data | P1 | `/results/`, `/results/r/tpch-polars-sf0.1-20260502-0093bb7a` | Leaderboard cell links to a result detail that *does* render a valid Polars TPC-H SF 0.1 power score. Two pages contradict each other on the same run. | leaderboard-data-consistency |
| 5 | TPC-H Charts Rank tab does not activate from the default Overview state | Chart panel state | P1 | `/results/tpch/` | Clicking Rank from a fresh page load does not set `aria-selected=true` on Rank or render the Rank table; Overview content stays. | chart-tabs-and-disambiguation |
| 6 | Per-query Heatmap on benchmark detail duplicates the page-level benchmark matrix | Chart scope | P2 | `/results/tpch/` | Charts > Per-query > Heatmap renders the same matrix already shown directly above it on benchmark detail. | chart-tabs-and-disambiguation |
| 7 | Distribution box-plot labels truncate repeated run identities | Run-label disambiguation | P1 | `/results/tpch/` | Multiple DataFusion, Polars, PySpark, Spark, and SQLite labels truncate to identical strings; full RunIdentity is hidden. | chart-tabs-and-disambiguation |
| 8 | Same-platform compare summary says "Polars is 1.00× faster" with "WINNER Polars" | Compare summary semantics | P1 | `/results/compare` | Two Polars v1.40.0 runs from different dates produce a winner card and a 1.00× speedup statement. | compare-summary-semantics |
| 9 | Query Wins denominator mixes comparable and missing-data queries | Compare summary semantics | P1 | `/results/compare` | The denominator used for win rates includes queries that were excluded for missing data, depressing or inflating apparent win rates. | compare-summary-semantics |
| 10 | Compare picker shows duplicate SSB benchmark options | Compare picker filter | P2 | `/results/compare` (no ids) | Legacy SSB slugs are not canonicalized before render; two options appear with no way to tell them apart. | compare-summary-semantics |
| 11 | Compare picker checkbox accessible names are under-disambiguated | Compare picker a11y | P1 | `/results/compare` | "Select DuckDB for comparison" repeats across many distinct candidate runs; assistive tech and locator-driven tests cannot distinguish them. | compare-selection-recovery |
| 12 | Result receipt Cost section leaks raw `not_applicable` enum values | Result receipt copy | P2 | `/results/r/tpch-polars-sf0.1-20260502-0093bb7a` | Cost line renders "compute only, billing: not_applicable, region: not_applicable" verbatim. | result-receipt-cost-copy |
| 13 | Comparability guardrail copy says only "benchmark and scale" | Compare summary semantics | P2 | `/results/compare` | Cohort lock is benchmark + scale + phase (and primary metric where enforced); the copy under-states the actual gate. | compare-summary-semantics |

## Owning TODO map

- `results-explorer-post-completion-compare-selection-recovery.yaml` → #1, #2, #3, #11
- `results-explorer-post-completion-leaderboard-data-consistency.yaml` → #4
- `results-explorer-post-completion-chart-tabs-and-disambiguation.yaml` → #5, #6, #7
- `results-explorer-post-completion-compare-summary-semantics.yaml` → #8, #9, #10, #13
- `results-explorer-post-completion-result-receipt-cost-copy.yaml` → #12
- `results-explorer-post-completion-release-gate.yaml` → acceptance gate over #1–#13

## Acceptance contract

Each TODO carries a `w0` work unit that re-validates its findings on the
current develop tip and writes stdout to
`_project/verification-logs/<id>/w0.log`. Implementation work is gated on
that log; the release-gate TODO consumes the per-item logs plus a fresh
browser pass to produce
`_project/audits/results-explorer-post-completion-release-gate-<gate-date>.md`.

If a finding here no longer reproduces on a future develop tip, the
owning TODO's `w0` log records that fact and the finding is treated as
already-satisfied at gate time.

## Status notes (post-cited-tip changes)

This section records changes that landed on `develop` *after* the cited
`dbac33ee1` tip but *before* implementation work begins. It does not
move findings; it just narrows where each `w0` should look.

- **PR #316 (`b94cb59bb`)** — `fix(explorer): close follow-up usability
  review gaps`. Centralized compare cohort locking via
  `results-explorer/src/lib/compareCohort.ts`, capped entrypoint
  selections at four runs, and threaded cohort-aware labels into the
  remaining Compare chart consumers. Findings to re-verify in light of
  this PR: #1 (still in BenchmarkIndex), #2/#3 (cohort lock helper now
  exists; ordering of compatible candidates still unconfirmed), #8/#11
  (Compare-side cohort labels may already disambiguate same-platform
  copy in some surfaces).
- **Already-shipped overlap to confirm in w0, not re-implement**:
    - Finding #6 (Per-query Heatmap duplicate): matrix-view dedup
      lives at `results-explorer/src/pages/BenchmarkIndex.tsx`
      (`excludeChartIds={["query_heatmap"]}`, PR #300). w0 should
      check whether the duplicate reappears in non-matrix view modes
      or has regressed.
    - Finding #10 (duplicate SSB options): legacy slug labeling lives
      at `results-explorer/src/lib/displayLabels.ts:80`
      (`"SSB (legacy slug)"`, PR #285). w0 should check whether the
      Compare picker builds its option list from a source that
      bypasses the labeler.
    - Finding #7 (Distribution truncation): cohort-aware formatter
      already applied to Distribution/Rank/Trend/Overview charts
      (PRs #286 + #309). The remaining work is post-formatter
      truncation budget; see
      `results-explorer-post-completion-chart-tabs-and-disambiguation.yaml`
      w3 notes.
