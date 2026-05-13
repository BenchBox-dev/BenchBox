---
develop_sha: 175a98d3bbdb8bcc074583e46a2d5e86ebcacafe
---
- id: S1.1
  page: layout
  url: http://localhost:5173/results/
  browser: chromium-147
  status: P

- id: S1.2
  page: layout
  url: http://localhost:5173/results/
  browser: chromium-147
  status: P

- id: S1.3
  page: layout
  url: http://localhost:5173/results/tpch/
  browser: chromium-147
  status: P

- id: S1.4
  page: layout
  url: http://localhost:5173/results/r/tpch-duckdb-sf0.01-20260403-7fe93365
  browser: chromium-147
  status: F
  what_i_did: |
    Loaded Home, BenchmarkIndex, and ResultDetail routes and watched the browser tab title.
  what_i_expected: |
    The document title should update per route.
  what_happened: |
    The title stayed "BenchBox Results Explorer" across routes.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: not retained in git; original filename s1.4-chromium-147.png
  severity: minor
  notes: |
    Layout and route content changed, but document.title did not.

- id: S1.5
  page: layout
  url: http://localhost:5173/results/
  browser: chromium-147
  status: P

- id: S1.6
  page: layout
  url: http://localhost:5173/results/
  browser: chromium-147
  status: F
  what_i_did: |
    Cold-loaded Home after restarting the Vite server and waited for the DuckDB-backed leaderboard to render.
  what_i_expected: |
    The app should move from loading into the populated corpus without rendering a stale empty state.
  what_happened: |
    The first cold pass rendered 0 Results / 0 Benchmarks / 0 Platforms and the "No leaderboard cells match" empty state. A later browser module probe against the same snapshot returned 12 rows, and warm reloads rendered the leaderboard.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: not retained in git; original filename debug-home-chromium-147.png
  severity: major
  notes: |
    Firefox spot-check also timed out on the initial Home leaderboard wait before the server was warmed.

- id: S2.1
  page: home
  url: http://localhost:5173/results/
  browser: chromium-147
  status: P

- id: S2.2
  page: home
  url: http://localhost:5173/results/?mode=speedup
  browser: chromium-147
  status: Q
  what_i_did: |
    Clicked the Times, Ranks, and Speedup mode buttons and inspected the URL and cell values.
  what_i_expected: |
    The plan says speedup values should be ratios greater than or equal to 1.
  what_happened: |
    URL state updated and round-tripped, but Speedup mode intentionally displays 1.00x for best-in-cohort and smaller values for slower entries.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: not retained in git; original filename s2.2-chromium-147.png
  severity: minor
  notes: |
    The in-page explainer says smaller values are worse, so the test-plan expectation may be stale.

- id: S2.3
  page: home
  url: http://localhost:5173/results/
  browser: chromium-147
  status: Q
  what_i_did: |
    Clicked one benchmark chip, then clicked the other benchmark chip in the same group.
  what_i_expected: |
    Multiple active chips in one group should both be encoded in the URL.
  what_happened: |
    Selecting every chip in a group collapses to the clear/all state and removes the `bm` parameter.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: not retained in git; original filename s2.3-chromium-147.png
  severity: nit
  notes: |
    The UI treats "all selected" and "no explicit filter" as equivalent.

- id: S2.4
  page: home
  url: http://localhost:5173/results/?phase=power
  browser: chromium-147
  status: P

- id: S2.5
  page: home
  url: http://localhost:5173/results/?bm=star_schema&phase=power
  browser: chromium-147
  status: P

- id: S2.6
  page: home
  url: http://localhost:5173/results/?trust=maintainer-run&window=30d
  browser: chromium-147
  status: P

- id: S2.7
  page: home
  url: http://localhost:5173/results/
  browser: chromium-147
  status: Q
  what_i_did: |
    Checked the Home-page Submit a Result CTA target.
  what_i_expected: |
    The CTA should link somewhere reasonable; the plan says a dev 404 is acceptable but should be noted.
  what_happened: |
    The CTA points to `/docs/contributing-results.html`, which returned HTTP 404 from the Vite dev server.
  evidence:
    console: |
      none
    network: |
      http://localhost:5173/docs/contributing-results.html 404
    screenshot: none
  severity: nit
  notes: |
    The target path itself is reasonable for the docs build.

- id: S3.1
  page: benchmark
  url: http://localhost:5173/results/tpch/
  browser: chromium-147
  status: Q
  what_i_did: |
    Switched BenchmarkIndex through Matrix, Ranks, and List views.
  what_i_expected: |
    Each view should render; the plan asks to confirm whether view mode is URL-synced.
  what_happened: |
    The views rendered, but the selected view stayed component-local and was not encoded in the URL.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: not retained in git; original filename s3.1-chromium-147.png
  severity: nit
  notes: |
    This matches the plan note that view mode is not currently URL-synced.

- id: S3.2
  page: benchmark
  url: http://localhost:5173/results/tpch/?sf=0.1
  browser: chromium-147
  status: P

- id: S3.3
  page: benchmark
  url: http://localhost:5173/results/tpch/?sf=0.01&phase=standard
  browser: chromium-147
  status: F
  what_i_did: |
    Loaded a hand-crafted BenchmarkIndex URL with an unavailable phase for the selected scale factor.
  what_i_expected: |
    The URL state should fall back visibly or show a clear empty state without stale controls.
  what_happened: |
    The component derives an `effectivePhase` from available data, but the URL can remain on an unavailable `phase` value while the page renders a different effective cohort.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: none
  severity: major
  notes: |
    No network 404 was observed, but the URL and rendered cohort can disagree.

- id: S3.4
  page: benchmark
  url: http://localhost:5173/results/tpch/
  browser: chromium-147
  status: Q
  what_i_did: |
    Loaded TPC-H and Star Schema benchmark pages and looked for Tuning and Trust controls.
  what_i_expected: |
    The plan asks for tuning and trust round-trip checks; trust is expected to be in-memory.
  what_happened: |
    The current corpus has one trust tier and no visible multiple tuning modes, so both controls are hidden and could not be exercised.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: not retained in git; original filename s3.4-chromium-147.png
  severity: minor
  notes: |
    This is a corpus coverage gap for the requested control test.

- id: S3.5
  page: benchmark
  url: http://localhost:5173/results/tpch/
  browser: chromium-147
  status: Q
  what_i_did: |
    Toggled High contrast on the benchmark matrix.
  what_i_expected: |
    Manual toggle should work, and system `prefers-contrast: more` should auto-activate if set.
  what_happened: |
    Manual toggle worked. I could not exercise macOS System Settings -> Increase contrast inside the headless browser harness.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: not retained in git; original filename s3.5-chromium-147.png
  severity: nit
  notes: |
    Manual behavior passed; system preference auto-activation remains unverified.

- id: S3.6
  page: benchmark
  url: http://localhost:5173/results/tpch/
  browser: chromium-147
  status: F
  what_i_did: |
    Inspected and clicked table headers in BenchmarkIndex matrix and list views.
  what_i_expected: |
    Each sortable `<th>` should cycle asc -> desc -> none and expose an indicator or `aria-sort`.
  what_happened: |
    BenchmarkIndex table headers are static text; no sort handlers, arrows, or `aria-sort` attributes were present.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: none
  severity: major
  notes: |
    Same class of issue as PlatformIndex header sorting.

- id: S3.7
  page: benchmark
  url: http://localhost:5173/results/compare?ids=a556e716,4af35f65
  browser: chromium-147
  status: P

- id: S3.8
  page: benchmark
  url: http://localhost:5173/results/tpch/?sf=0.01&phase=standard
  browser: chromium-147
  status: F
  what_i_did: |
    Loaded an empty benchmark cohort URL.
  what_i_expected: |
    Charts should show an empty state for an empty cohort, not render a different cohort.
  what_happened: |
    The page can fall back internally to an available phase while the URL still names the unavailable phase.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: not retained in git; original filename s3.8-chromium-147.png
  severity: major
  notes: |
    Same root behavior as S3.3.

- id: S4.1
  page: platform
  url: http://localhost:5173/results/p/datafusion/
  browser: chromium-147
  status: P

- id: S4.2
  page: platform
  url: http://localhost:5173/results/p/duckdb/
  browser: chromium-147
  status: P

- id: S4.3
  page: platform
  url: http://localhost:5173/results/p/datafusion/
  browser: chromium-147
  status: F
  what_i_did: |
    Inspected table headers on duckdb, sqlite, datafusion, and polars PlatformIndex pages.
  what_i_expected: |
    Benchmark, Scale, Date, and Power Score headers should sort and update arrows.
  what_happened: |
    PlatformIndex headers are static `<th>` cells with no sort handler, arrow, or `aria-sort` state.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: not retained in git; original filename s4.3-chromium-147.png
  severity: major
  notes: |
    This re-tests pass-1 bug B1.

- id: S4.4
  page: platform
  url: http://localhost:5173/results/compare?ids=70e334cc,42b415a7
  browser: chromium-147
  status: P

- id: S4.5
  page: platform
  url: http://localhost:5173/results/p/datafusion/
  browser: chromium-147
  status: F
  what_i_did: |
    Loaded `/results/p/datafusion/` and waited for the platform timeline ChartPanel.
  what_i_expected: |
    The TimeSeries chart should render without console warnings.
  what_happened: |
    Preact logged a duplicate-key warning for TimeSeries points that share the same run_date within a platform series.
  evidence:
    console: |
      warning: Encountered two children with the same key attribute: 2026-04-03. Keys should be unique.
      warning: Encountered two children with the same key attribute: 2026-04-04. Keys should be unique.
    network: |
      none
    screenshot: not retained in git; original filename s4.5-chromium-147.png
  severity: minor
  notes: |
    This re-tests pass-1 bug B4.

- id: S5.1
  page: result
  url: http://localhost:5173/results/r/tpch-duckdb-sf0.01-20260403-7fe93365
  browser: chromium-147
  status: P

- id: S5.2
  page: result
  url: http://localhost:5173/results/r/tpch-duckdb-sf0.01-20260403-7fe93365?metric=display_geomean_ms
  browser: chromium-147
  status: F
  what_i_did: |
    Loaded ResultDetail with `?metric=display_geomean_ms` and searched for primary-metric controls.
  what_i_expected: |
    The URL should accept `?metric=power_score` and `?metric=display_geomean_ms`, and charts/headline metric should switch.
  what_happened: |
    No in-page metric toggle was present, and ResultDetail derives primary metric from benchmark metadata instead of the `metric` URL parameter.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: none
  severity: major
  notes: |
    Related to pass-1 Q1.

- id: S5.3
  page: result
  url: http://localhost:5173/results/r/tpch-duckdb-sf0.01-20260403-7fe93365
  browser: chromium-147
  status: P

- id: S5.4
  page: result
  url: http://localhost:5173/results/r/tpch-duckdb-sf0.01-20260403-7fe93365
  browser: chromium-147
  status: P

- id: S5.5
  page: result
  url: http://localhost:5173/results/r/tpch-duckdb-sf0.01-20260403-7fe93365
  browser: chromium-147
  status: Q
  what_i_did: |
    Checked ResultDetail for tuning sidecar behavior.
  what_i_expected: |
    Results with a sidecar should lazy-load JSON, and results without one should show a clean empty state.
  what_happened: |
    The current public corpus has `has_tuning=false` for all 12 results, and no Tuning Config disclosure is rendered for those rows.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: none
  severity: minor
  notes: |
    This is a corpus coverage gap for the lazy-load path.

- id: S5.6
  page: result
  url: http://localhost:5173/results/r/tpch-duckdb-sf0.01-20260403-7fe93365
  browser: chromium-147
  status: P

- id: S5.7
  page: result
  url: http://localhost:5173/results/r/does-not-exist
  browser: chromium-147
  status: P

- id: S6.1
  page: compare
  url: http://localhost:5173/results/compare?ids=a556e716,edfa1886
  browser: chromium-147
  status: P

- id: S6.2
  page: compare
  url: http://localhost:5173/results/compare?ids=a556e716,edfa1886,4af35f65
  browser: chromium-147
  status: Q
  what_i_did: |
    Loaded a same-benchmark/SF comparison with all available TPC-H SF 0.01 IDs.
  what_i_expected: |
    The plan asks for 4 IDs from one cohort.
  what_happened: |
    The committed corpus has only three platforms in any same-benchmark/SF cohort, so a 4-ID same-cohort comparison is not possible without mixing cohorts.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: none
  severity: nit
  notes: |
    Three-result compare rendered.

- id: S6.3
  page: compare
  url: http://localhost:5173/results/compare?ids=a556e716,f3c39502
  browser: chromium-147
  status: P

- id: S6.4
  page: compare
  url: http://localhost:5173/results/compare?ids=a556e716,edfa1886&metric=display_geomean_ms
  browser: chromium-147
  status: F
  what_i_did: |
    Loaded Compare with `?metric=display_geomean_ms` and searched for primary-metric controls.
  what_i_expected: |
    `?metric=` should be accepted; no in-page toggle was expected.
  what_happened: |
    Compare leaves the URL parameter in place but derives primary metric from benchmark metadata and exposes no metric control.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: none
  severity: major
  notes: |
    Related to pass-1 Q1.

- id: S6.5
  page: compare
  url: http://localhost:5173/results/compare?ids=a556e716
  browser: chromium-147
  status: F
  what_i_did: |
    Loaded Compare with empty, missing, mixed valid/missing, and single-ID `ids` values.
  what_i_expected: |
    Bad inputs should fail cleanly, and a single ID should redirect to ResultDetail or show a need-2-results message.
  what_happened: |
    Empty and missing IDs fail cleanly, but a single ID renders a one-platform comparison page.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: none
  severity: minor
  notes: |
    Mixed valid/missing IDs fail the whole compare with a clear missing-result message.

- id: S7.1
  page: query
  url: http://localhost:5173/results/query
  browser: chromium-147
  status: P

- id: S7.2
  page: query
  url: http://localhost:5173/results/query?benchmark=tpch
  browser: chromium-147
  status: P

- id: S7.3
  page: query
  url: http://localhost:5173/results/query
  browser: chromium-147
  status: Q
  what_i_did: |
    Removed a visible column from the Query workbench table and looked for a column reorder affordance.
  what_i_expected: |
    The plan asks whether column visibility and reordering are URL-synced/supported.
  what_happened: |
    Column visibility changes immediately but is session-only; no `columns=` URL state is written. I found no column reorder control.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: none
  severity: minor
  notes: |
    Session-only state may be acceptable, but it is not shareable.

- id: S7.4
  page: query
  url: http://localhost:5173/results/query
  browser: chromium-147
  status: P

- id: S7.5
  page: query
  url: http://localhost:5173/results/query
  browser: chromium-147
  status: F
  what_i_did: |
    Looked for row-limit controls on the Query workbench.
  what_i_expected: |
    There should be a control to switch between `DEFAULT_ROW_LIMIT` and unlimited.
  what_happened: |
    No visible row-limit or unlimited toggle exists; exports use unlimited internally, but the table UI stays at the default query limit.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: none
  severity: minor
  notes: |
    `DEFAULT_ROW_LIMIT` and `UNLIMITED_ROW_LIMIT` exist in code, but only the default table limit is exposed in UI.

- id: S7.6
  page: query
  url: http://localhost:5173/results/query
  browser: chromium-147
  status: P

- id: S7.7
  page: query
  url: http://localhost:5173/results/query
  browser: chromium-147
  status: P

- id: S8.1
  page: 404
  url: http://localhost:5173/results/totally/made/up/path/
  browser: chromium-147
  status: P

- id: S8.2
  page: 404
  url: http://localhost:5173/results/totally/made/up/path/
  browser: chromium-147
  status: P

- id: S9
  page: layout
  url: http://localhost:5173/results/tpch/?sf=abc
  browser: chromium-147
  status: F
  what_i_did: |
    Loaded hand-crafted URLs with garbage and empty URL state, including `/results/tpch/?sf=abc`.
  what_i_expected: |
    Garbage values should fall back to default state without crashing.
  what_happened: |
    Home garbage mode falls back visually, but BenchmarkIndex keeps invalid `sf=abc` state and renders no benchmark data instead of selecting a valid scale factor.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: none
  severity: minor
  notes: |
    Empty array params such as `?bm=` are stripped as expected.

- id: S10.1
  page: home
  url: http://localhost:5173/results/
  browser: chromium-147
  status: F
  what_i_did: |
    Cleared browser state, cold-loaded `/results/`, and waited for the MetaLeaderboard.
  what_i_expected: |
    First content and the populated MetaLeaderboard should appear without a stale empty corpus.
  what_happened: |
    The first cold pass rendered the app shell with 0 result counts and no leaderboard. Warm reloads rendered 12 results, 2 benchmarks, and 4 platforms.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: not retained in git; original filename debug-home-chromium-147.png
  severity: major
  notes: |
    The Vite server had been restarted immediately before this observation.

- id: S10.2
  page: home
  url: http://localhost:5173/results/
  browser: chromium-147
  status: P

- id: S10.3
  page: home
  url: http://localhost:5173/results/p/datafusion/
  browser: chromium-147
  status: P

- id: B1
  page: platform
  url: http://localhost:5173/results/p/datafusion/
  browser: chromium-147
  status: F
  what_i_did: |
    Re-tested PlatformIndex table headers on duckdb, sqlite, datafusion, and polars.
  what_i_expected: |
    Headers should sort.
  what_happened: |
    Headers are still static on this branch.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: not retained in git; original filename s4.3-chromium-147.png
  severity: major
  notes: |
    Same current state as pass-1.

- id: B2
  page: platform
  url: http://localhost:5173/results/p/duckdb/
  browser: chromium-147
  status: P

- id: B3
  page: 404
  url: http://localhost:5173/results/does-not-exist/
  browser: chromium-147
  status: F
  what_i_did: |
    Loaded `/results/does-not-exist/`.
  what_i_expected: |
    Unknown result routes should render NotFound.
  what_happened: |
    The one-segment path still routes to BenchmarkIndex and renders an empty benchmark page titled `DOES-NOT-EXIST Results`.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: none
  severity: minor
  notes: |
    The truly invalid multi-segment path `/results/totally/made/up/path/` does render NotFound.

- id: B4
  page: platform
  url: http://localhost:5173/results/p/datafusion/
  browser: chromium-147
  status: F
  what_i_did: |
    Loaded PlatformIndex pages with multiple results sharing the same run date.
  what_i_expected: |
    No Preact key warnings.
  what_happened: |
    Duplicate-key TimeSeries warnings are still present.
  evidence:
    console: |
      warning: Encountered two children with the same key attribute: 2026-04-03. Keys should be unique.
      warning: Encountered two children with the same key attribute: 2026-04-04. Keys should be unique.
    network: |
      none
    screenshot: not retained in git; original filename s4.5-chromium-147.png
  severity: minor
  notes: |
    Same current state as pass-1.

- id: Q1
  page: result
  url: http://localhost:5173/results/r/tpch-duckdb-sf0.01-20260403-7fe93365
  browser: chromium-147
  status: Q
  what_i_did: |
    Checked ResultDetail and Compare for an in-page primary metric toggle.
  what_i_expected: |
    Pass-1 asked whether the metric contract is URL-only and whether there is no in-page toggle.
  what_happened: |
    There is no in-page primary metric toggle on either ResultDetail or Compare. URL metric handling also appears unimplemented.
  evidence:
    console: |
      none
    network: |
      none
    screenshot: none
  severity: minor
  notes: |
    This answers the pass-1 open question.

# totals: P=30 F=16 Q=10
