# Results Explorer — manual QA test plan

End-to-end manual QA pass against the live Results Explorer. Hand this
file to a tester (or run it yourself); they fill in the report template
at the end and return it. Per-section findings map cleanly to bug fixes
or follow-up TODOs.

History: this plan was originally drafted in agent conversation state
during the 2026-04-28 QA pass (commit `ca9a8ed9b`) and lost on the next
context reset. It now lives here so it cannot rot away.

## Prereqs (operator)

You — not the tester — set up the environment first. The tester only
needs a browser.

```bash
# From the repo root, or any worktree of it.
cd results-explorer
npm install                  # one-time, on a fresh checkout
npm run dev                  # starts Vite at http://localhost:5173/results/
```

Leave the dev server running in a terminal. Hand the tester
`http://localhost:5173/results/` and this document.

If you want to test against a fresh production-shape DB, regenerate it
once before starting:

```bash
# From the repo root
uv run benchbox explorer build --data-dir results-data/ \
                               --output results-explorer/public/data/
```

## Setup (tester)

- Open the URL in **Chrome** and **Firefox** (DuckDB-WASM uses cross-origin
  isolation; ad-blockers and strict-tracker extensions can break it).
- Open DevTools → Console and Network tabs before navigating. Leave them
  open through every step.
- Hard-refresh (Cmd-Shift-R) once to clear any stale WASM.

For each step, mark **OK / BUG / SLOW** and add a one-line note. At the
end, paste the filled template back to the operator.

## Expected hidden controls

Two filter UIs auto-hide when the dataset has only one value to filter
on. This is by design, not a bug:

- **Trust chips** — auto-hidden when all rows share a single `trust_label`
  (the default published corpus has only `maintainer-run`).
- **Tuning dropdown** — auto-hidden when all rows have a single
  `tuning_mode` (the default published corpus has `tuning_mode=NULL` for
  every row).

If the tester sees these missing, that's expected. To exercise them,
ingest a community-submitted bundle or a tuned run.

## 1. Home page (`/results/`)

1. Page paints within ~3s; meta-leaderboard table appears.
2. The "Filter cohorts" controls (benchmark / scale / phase) update the
   leaderboard live — no page reload, no flash of empty state.
3. Each cohort row links to a benchmark page and the link works.
4. Each platform row's avg-rank cell matches its position relative to
   others (e.g. avg_rank 1.0 should be top).
5. Resize the window narrow (≤480px). Layout doesn't overflow
   horizontally; text remains readable.

## 2. Benchmark index (`/results/tpch/`, `/results/star_schema/`)

The published corpus only has `tpch` and `star_schema` data. Note:
the SSB display label is shown for `star_schema` (it's an alias), so
the heading reads "SSB Results" on `/results/star_schema/`. Visiting
`/results/ssb/` shows an empty-corpus message ("No published results
yet for SSB") because the data is filed under `star_schema`. **Do not
test `/results/ssb/` as a separate route** — that's a navigation
quirk, not a bug.

For each of `tpch` and `star_schema`:

1. Title shows the right benchmark.
2. **Scale factor** selector lists the SFs present and switches the
   matrix without errors.
3. **View mode** toggle (matrix / chart / etc.) — switch through every
   option and confirm each renders a chart with axes labeled, no
   overlapping text, no `NaN`/`undefined`.
4. **High contrast** toggle visibly changes colors and remains
   accessible.
5. Tick 2-3 rows → **Compare selected** button activates and navigates
   to `/results/compare?ids=...`.
6. Click a platform name → goes to `/results/p/<platform>/`.
7. Click a row link → goes to `/results/r/<short_id>`.

## 3. Platform index (`/results/p/duckdb/`, try also `polars`, `datafusion`, `sqlite`)

1. Header shows the platform's display name (not the slug).
2. Sort each table column (Benchmark, Scale, Date, Power Score, Geomean)
   — arrows update, ordering is correct.
3. Tick 2 rows → **Compare** button enables and navigates correctly.

If you see "No results found for platform: duckdb." on the DuckDB or
Polars pages, that's a known cold-load race (B2 in
`_project/TODO/main/active/results-explorer-qa-pass1-fixes.yaml`). Wait
30-60s and reload; if it still empty, mark as BUG.

## 4. Result detail (`/results/r/<short_id>`)

Open one from each platform via the links from §2-3.

1. All header fields populated: platform, version, tuning, trust, run
   date, geomean, power.
2. **Median timings** table: sort by query_id, display_ms, sample_count
   — each direction correct.
3. **Raw timings** section: same sort behavior.
4. Expand **Tuning** disclosure: it lazy-loads JSON; no infinite
   spinner.
5. **Download bundle** link returns the JSON with HTTP 200.
6. Charts (CDF, percentile ladder, histogram, distribution box, stacked
   phase) all render with axis labels and no clipping.
7. The chart axis label reflects the benchmark's primary metric:
   ClickBench / TSBS-style benchmarks use power-score; TPC-H / TPC-DS
   use geomean (ms). The metric is **benchmark-derived, not user-
   toggleable** — this is by design (see Q1 in the parent TODO).

## 5. Compare (`/results/compare?ids=<short_id>,<short_id>`)

1. Open with 2 result ids selected from §2 — both load.
2. Try with 3+ ids — table widens, no horizontal scroll bug.
3. **Share** button copies a URL; pasting it in a new tab reproduces
   the same view.
4. Try an invalid id (`?ids=zzz`) — page shows a clear error, doesn't
   crash.
5. **Δ fastest** column: fastest row reads `—` or `0`; others are
   positive.

Note: like §4, there is no in-page primary-metric toggle. Compare
inherits the benchmark's primary metric from the loaded results. Cross-
benchmark comparisons are explicitly rejected with "Cannot compare
results from different benchmarks."

## 6. Query (`/results/query`)

1. Default table loads with "results" rows, sorted by run_date desc.
2. Each facet panel (benchmark / platform / scale / tuning / trust /
   validation / has-cost / date-window) shows counts; clicking filters;
   counts update across other facets accordingly.
3. **Column visibility** toggles add/remove columns immediately.
4. Sort by every visible column; both directions correct.
5. **SQL** text area: run the default query — rows render. Edit to
   `SELECT 1` → renders 1 row. Edit to invalid SQL → an error is shown
   inline (no white screen).
6. **Download CSV** (or whatever the export is) produces a non-empty
   file with the current filtered rows.

## 7. Cross-cutting

1. NotFound: visit `/results/no/such/route/` — friendly 404 page, no
   console error stack. Visit `/results/totally-fake/` — also 404, with
   a message naming the unknown benchmark slug. Visit
   `/results/clickbench/` — empty-corpus state ("No published results
   yet for ClickBench"), NOT a 404.
2. Browser back/forward through 5+ pages — state restores, no DuckDB
   re-init flash.
3. DevTools Console: report any **red** errors or warnings encountered
   during the run.
4. DevTools Network: confirm `results.duckdb` loads once per
   page-session, not on every navigation.
5. Lighthouse → Accessibility on Home and one BenchmarkIndex; report
   scores <90.

## Report template (paste this back filled in)

```
Browser: Chrome <ver> / Firefox <ver>
Build commit: <git rev-parse --short HEAD output>

§1 Home
  1.1 OK
  1.2 BUG: filter "phase=throughput" leaves table empty even though results exist
  ...

§2 Benchmark index
  /results/tpch/
    2.1 OK
    2.3 view-mode "chart": x-axis labels overlap on narrow window — SLOW
    ...

§3 Platform index
  ...

§4 Result detail (<short_id1>, <short_id2>)
  ...

§5 Compare
  ...

§6 Query
  ...

§7 Cross-cutting
  Console errors:
    - <verbatim message + page>
  Network anomalies:
    - <e.g. results.duckdb fetched 7× during 4 navigations>
  Lighthouse a11y: Home=<n>, /results/tpch/=<n>
```

That structure is enough for the operator to diff against expected
behaviour and open issues per §-numbered failure. Start with §1, work
down — if §1 is broken don't bother with §4+.
