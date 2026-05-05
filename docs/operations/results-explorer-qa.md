# Results Explorer — QA Test Plan

**For:** human tester (you)  •  **Output:** structured findings I can ingest verbatim
**Server:** `http://localhost:5173/results/`
**Corpus:** `tpch` and `star_schema` at SF 0.01 and SF 0.1 across `duckdb`, `sqlite`, `datafusion`, `polars` (note: no `tpch-sqlite`, no `star_schema-polars` — expect those filter combinations to produce empty cohorts, not errors)

This plan is the maintained manual QA checklist for the Results Explorer.
It originated from pass-2 coverage and should be reused for future
pre-release and remediation passes. The goal is full functional +
usability coverage of every control and configuration on every page.

---

## Prereqs (operator)

Start the local Vite server before handing the plan to a tester:

```bash
cd results-explorer
npm run dev
```

Leave the server running and give the tester
`http://localhost:5173/results/`.

If the browser fixture corpus is stale, regenerate it first:

```bash
cd results-explorer
npm run test:e2e:fixtures
```

## Expected Hidden Controls

Some controls are intentionally hidden until the loaded corpus has more
than one selectable value:

- BenchmarkIndex **trust chips** are hidden when the current cohort has
  only one `trust_label`.
- BenchmarkIndex **tuning dropdown** is hidden when the current cohort
  has only one non-null `tuning_mode`.
- Home and Query facet groups may omit empty buckets.

Do not report these as bugs unless the fixture corpus has multiple
values and the relevant control is still absent.

## How to test

1. **Open in two browsers** if you can — Chromium 147+ and Firefox 148+. Most issues will show up in one but not both.
2. **Open DevTools before each page load** (Network + Console tabs). Keep "Preserve log" on. Cold-load each route at least once with cache disabled.
3. **Drive every interactive control at least once.** Click it, type into it, change its value. Then change it back. Then reload the page and verify the URL still encodes the state (where applicable — see §URL).
4. **Watch the Console.** Any warning, error, or 404 = a finding. Quote the exact message.
5. **Capture, don't summarize.** Screenshots, console text, network response status, full URL bar. I cannot see your screen.
6. **Don't fix, don't theorize.** Just report what happened vs. what you expected. I'll triage.

If a step's "expected" behavior is unclear or seems wrong on its face, mark it `Q` (open question) instead of `P`/`F` (pass/fail) — that's a usability finding too.

---

## Reporting format

Append one block per finding to a new file at `_project/audits/results-explorer-qa-pass2-findings.md`. **One finding per block, no prose between them.** Use this exact template — I parse it:

```yaml
- id: <STABLE_ID from this plan, e.g. S2.3, U1, F4>
  page: <home | benchmark | platform | result | compare | query | layout | 404>
  url: <full URL bar at the moment of the finding>
  browser: <chromium-147 | firefox-148 | webkit-... | other>
  status: <P | F | Q>            # Pass, Fail, open Question
  what_i_did: |
    <one to three sentences, action-by-action>
  what_i_expected: |
    <one sentence>
  what_happened: |
    <one to three sentences; quote console errors verbatim>
  evidence:
    console: |
      <paste any console output, or "none">
    network: |
      <paste any non-2xx responses with URL + status, or "none">
    screenshot: <relative path under _project/audits/screenshots/, or "none">
  severity: <blocker | major | minor | nit>   # only for F and Q; omit for P
  notes: |
    <anything else — repro flakiness, only-on-cold-load, etc.>
```

End the file with a single summary line: `# totals: P=<n> F=<n> Q=<n>`.

For **passes**, `status: P` plus the id, page, url, browser is enough — skip the rest. I only need detail on F/Q.

---

## S1 — Layout & global chrome (every page)

Test on at least Home and one ResultDetail.

- **S1.1** Header logo / title is present and links back to `/results/`.
- **S1.2** Footer (if any) renders without overflow at viewport widths 360px, 768px, 1280px, 1920px.
- **S1.3** Breadcrumb on BenchmarkIndex, PlatformIndex, ResultDetail, Compare reflects the current page and each segment is a working link.
- **S1.4** Page `<title>` updates per route (watch the browser tab).
- **S1.5** Keyboard tab order through any interactive header/nav element is sensible — no traps, no invisible focus.
- **S1.6** No layout shift after DuckDB-WASM finishes loading (CLS-style jank).

---

## S2 — Home (`/results/`)

### S2.1 Stat cards
- Three cards: Results / Benchmarks / Platforms. Numbers match the corpus (12 results, 2 benchmarks, 4 platforms expected).

### S2.2 MetaLeaderboard mode toggle (`?mode=`)
- Three modes: **times** (default), **ranks**, **speedup**. Click each.
- Verify URL updates to `?mode=ranks` / `?mode=speedup`. `mode=times` may or may not appear in the URL — note which.
- Reload after switching: mode persists.
- Numbers in cells change appropriately between modes: times = ms, ranks = small ints, speedup = best-in-cohort
  `1.00×` with slower entries below `1.00×`.

### S2.3 Filter chips (multi-select: Benchmark, Scale)
- Click a chip → row toggles, URL updates (`?bm=tpch` etc., array form).
- Click multiple chips of the same group → both encoded in URL.
- Click an active chip again → deselects.
- "Clear" / no-selection state shows all rows.
- Reload preserves selection.

### S2.4 Filter dropdowns (single-select: Phase, Tuning, Trust, Date window)
- For each: cycle through every option. URL updates (`?phase=…`, `?tuning=…`, `?trust=…`, `?window=…`).
- "all" state should not be encoded in URL (verify — if it is, that's a finding).
- Reload preserves selection.

### S2.5 Filter combinations
- Apply 2+ filters that produce an empty set (e.g. `tpch` + sqlite-only by date window). Verify a clear "no results" empty state, not a blank page or stack trace.
- Apply filters that match exactly one cohort. Verify the table shrinks correctly and platform avg-rank recalculates.

### S2.6 Cohort and platform links
- Click a cohort cell → lands on `/results/<benchmark>/?sf=…&phase=…` with active filters carried over (tuning/trust/window).
- Click a platform name → lands on `/results/p/<platform_id>/` with carryover filters.
- Back button returns to Home with filters intact.

### S2.7 "Recent" list / submit-results CTA
- "Submit a Result" button links somewhere reasonable (likely `/docs/contributing-results.html`). 404 on that link is acceptable in dev — note it as Q, not F.

---

## S3 — BenchmarkIndex (`/results/:benchmark/`)

Test against `/results/tpch/` and `/results/star_schema/`.

### S3.1 View modes (matrix / ranks / list)
- Switch between all three. Each renders without errors.
- View mode is **not currently URL-synced** (component state). Confirm this — note as Q if you'd expect it to be.

### S3.2 Scale filter
- Two scale factors per benchmark (0.01, 0.1). Switching changes URL `?sf=…` and re-fetches the cohort.

### S3.3 Phase filter
- Default = `power`. URL `?phase=…` round-trips. Phases offered must only be those that exist for the current SF — picking an unavailable phase should not produce a network 404 from the data layer.

### S3.4 Tuning + Trust filters
- Same round-trip + reload checks as S2.4. Trust filter is in-memory state (not URL-synced) — confirm.

### S3.5 High-contrast toggle
- Heatmap colors switch to a reduced/accessible palette. Toggle off restores the default.
- Try with system `prefers-contrast: more` set (macOS: System Settings → Accessibility → Display → Increase contrast). The toggle should activate automatically.

### S3.6 Sortable column headers
- Click each `<th>` in the matrix/list views. **Pass-1 found PlatformIndex headers are static** — verify whether BenchmarkIndex headers actually sort. Test asc → desc → none cycle, and that the indicator (arrow / aria-sort) updates.

### S3.7 Row-selection → Compare flow
- Tick 2+ rows, click "Compare". Lands on `/results/compare?ids=<id1>,<id2>,…` and renders.
- Single selection should disable or warn on Compare button.
- Selecting >N (whatever the cap is, if any) — note the limit and whether it's communicated.

### S3.8 Charts (ChartPanel inside this page)
- Each chart renders without error. Hover/legend interactions work.
- For empty cohorts (e.g. `/results/tpch/?sf=0.01&phase=standard`), charts show empty states, not stack traces.

---

## S4 — PlatformIndex (`/results/p/:platform/`)

Test all four platforms: `duckdb`, `sqlite`, `datafusion`, `polars`. **Pass-1 found duckdb + polars rendered empty** — verify status on this branch.

### S4.1 Page renders for each platform
- Title, breadcrumb, results table, charts.
- Document any platform that renders empty even when bundles exist for it.

### S4.2 Tuning filter (URL: `?tuning=`)
- Same round-trip checks as elsewhere.

### S4.3 Sortable column headers
- **Pass-1 confirmed these are static `<th>` with no sort handler (B1).** Re-verify on this branch and report current state.

### S4.4 Row selection → Compare
- Same flow as S3.7. Compare across benchmarks (mixing tpch + star_schema results) should either work or surface a "not comparable" warning, not silently produce a broken chart.

### S4.5 ChartPanel for cross-benchmark platform timeline
- Charts: TimeSeries, distribution, etc.
- **Pass-1 found a Preact duplicate-key warning when multiple results share `run_date` (B4).** Re-verify; quote any console warnings.

---

## S5 — ResultDetail (`/results/r/:resultId`)

Sample IDs (pick at least one from each combination):
- `tpch-duckdb-sf0.01-20260403-7fe93365`
- `tpch-duckdb-sf0.1-20260404-2c1585b9`
- `tpch-datafusion-sf0.1-20260404-c2e26b95`
- `tpch-polars-sf0.01-20260403-39bb1a7b`
- `star_schema-sqlite-sf0.01-20260403-cb13f61a`
- `star_schema-datafusion-sf0.1-20260404-4650fc65`

### S5.1 Header & badges
- Trust badge and Tuning badge render with the right label/color for the bundle's metadata.
- Methodology disclosure expands and collapses.

### S5.2 Primary metric (benchmark-derived)
- Primary metric is derived from the published DuckDB ranking metadata for the result's benchmark.
- `?metric=` is **not** a supported URL contract. Adding `?metric=power_score` or
  `?metric=display_geomean_ms` must not switch chart semantics or headline values.
- No in-page primary-metric toggle is expected.

### S5.3 Median timings table (sort: query_id / display_ms / sample_count)
- Click each header, cycle asc → desc → asc. Indicator updates.
- Null `display_ms` values sort last in asc (current code uses `Infinity`).

### S5.4 Raw queries table (sort: query_id / duration_ms / status)
- Same checks. Failed queries (`status` ≠ `success`) should be visually distinguished.

### S5.5 Tuning sidecar
- Click to expand. First click triggers a network fetch (verify in DevTools). Spinner appears, then content.
- Collapse → re-expand: should not refetch (or should, if that's the design — note observed behavior).
- Try a result with no tuning sidecar: expansion should produce a clean empty state, not an error.

### S5.6 ChartPanel charts on this page
- Every chart renders.
- Chart hover/legend toggle works without console errors.

### S5.7 Bad URL: `/results/r/does-not-exist`
- Should render an error message ("No result found for…"), not blank or stack trace.

---

## S6 — Compare (`/results/compare?ids=…`)

### S6.1 Two-result compare (same benchmark + SF)
- Use two sample IDs from above. Renders charts, comparison table, and a comparability receipt with no differences.

### S6.2 N-result compare (3+)
- Pile in 4 IDs from one cohort (same benchmark + SF). Verify rendering and that no chart visually breaks at higher N.

### S6.3 Comparability warnings
- Compare across **different SFs** (`tpch` SF 0.01 vs SF 0.1) — banner should appear.
- Compare across **different benchmarks** (`tpch` + `star_schema`) — banner should appear or compare should refuse.
- Banner text is specific (names the dimension that differs), not generic.

### S6.4 Primary metric (benchmark-derived)
- Same as S5.2: primary metric is benchmark-derived from DuckDB ranking metadata.
- `?metric=` is **not** a supported URL contract and must not switch Compare chart semantics.
- No in-page primary-metric toggle is expected.

### S6.5 Bad inputs
- `?ids=` empty → friendly error.
- `?ids=does-not-exist` → friendly error.
- `?ids=valid,does-not-exist` → either render the partial set with a warning, or fail cleanly. Report which.
- `?ids=` with a single id → either redirect to ResultDetail or show a "need 2+" message.

---

## S7 — Query (`/results/query`)

This is the DuckDB-WASM ad-hoc explorer. Heaviest surface — give it the most time.

### S7.1 Cold load
- DuckDB-WASM loads. Spinner clears within ~10s on warm cache. Note cold-load time (first hit after browser cache clear).

### S7.2 Faceted filters
- Multi-select: benchmark, platform, scale, tuning, trust, validation. Each updates URL (`?benchmark=…&platform=…` array form) and the rows + facet counts.
- Single-select: `has_cost`, `window` (date). URL round-trip.
- Clearing all filters returns to the unfiltered view.

### S7.3 Schema-aware column picker
- Click columns to add/remove from the table. Default set is reasonable.
- Reorder columns (if supported).
- Note whether the column visibility state is URL-synced or session-only.

### S7.4 Sortable columns
- Click each visible column header. Sort state (`run_date desc` is the default) updates.

### S7.5 Row limit
- The default row limit is `DEFAULT_ROW_LIMIT`. Switch to "unlimited" / `UNLIMITED_ROW_LIMIT` and verify the row count grows. Switch back.

### S7.6 SQL editor
- Default text: `SELECT * FROM bench.results ORDER BY run_date DESC`. Run it.
- Modify the query. Run again.
- Run an invalid query (`SELECT FROM`). Verify the error is shown inline, not in console only.
- Run a query that returns 0 rows. Empty state, not error.
- Run a query that returns columns the column-picker doesn't know about. Should still render.
- **Security check:** confirm `bench.results` is a view, not the bare table — or that DDL (`DROP TABLE`, `INSERT`) is rejected or a no-op.

### S7.7 Starter queries
- Cycle through every starter category. Each should be one click → SQL pasted into editor → click run → renders without error.

---

## S8 — NotFound

### S8.1 Truly invalid path
- `/results/totally/made/up/path/` → NotFound page. **Pass-1 found `/results/does-not-exist/` rendered an empty BenchmarkIndex (B3).** Re-verify; the preact-router fix may or may not be on this branch.

### S8.2 NotFound page itself
- Has a "back to home" link that works.

---

## S9 — URL state round-trip (cross-cutting)

For every URL-synced control found in S2–S7:

- **Forward**: change the control, observe the URL bar. Decode the param manually — does it match what you set?
- **Reverse**: paste a hand-crafted URL with the param into a fresh tab. The control should reflect that state on first paint (not after a flicker from default).
- **Garbage in**: pass nonsense (`?mode=banana`, `?sf=abc`, `?tuning=<script>`). Should fall back to default, not crash.
- **Empty arrays**: `?bm=` (empty value) should be equivalent to "no filter".

---

## S10 — Cold load & DuckDB-WASM

- **S10.1** First load of `/results/` from a cleared cache. Capture: time to first content, time to MetaLeaderboard rendered, any console warnings about WASM.
- **S10.2** Reload (warm). Should be visibly faster.
- **S10.3** Navigate between pages without full reload. The DuckDB instance should be reused (verify in Network: no second `.duckdb` fetch).

---

## S11 — Pass-1 confirmed bugs (must re-test)

Re-run these verbatim and report status. They drive the `results-explorer-qa-pass1-fixes` TODO.

- **B1** — PlatformIndex `<th>` headers don't sort. Confirm on every platform page.
- **B2** — `/results/p/duckdb/` and `/results/p/polars/` render empty. Hard refresh + warm reload + 30s wait.
- **B3** — `/results/does-not-exist/` renders empty BenchmarkIndex instead of NotFound.
- **B4** — TimeSeries Preact duplicate-key warning on PlatformIndex when multiple results share a `run_date`.
- **Q1** — Primary-metric URL-only contract: confirm there is no in-page toggle on ResultDetail or Compare.

Tag each as `id: B1` etc. in the findings file with current status (P / F / Q).

---

## Out of scope for this pass

Do not file findings for these — they're tracked separately:
- DuckDB-WASM exception-handling polyfill warnings.
- Vite "JSX-source babel plugin" warning at startup.
- Chrome-headless cold-load latency (tracked under `enable-duckdb-wasm-http-range-reads-for-registered-urls`).

---

## When you're done

Save findings at `_project/audits/results-explorer-qa-pass2-findings.md` and reply with just: "pass-2 findings ready, N=<count>". I'll read the file, triage, and either patch directly or update the existing pass-1 TODO.
