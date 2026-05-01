- id: B1
  page: benchmark
  url: http://localhost:4319/results/tpch/?sf=0.01&phase=standard
  browser: chromium-147
  status: P
  notes: |
    PlatformIndex and BenchmarkIndex sortable-header regressions are covered by
    `routes/index-sort-headers.spec.ts`. Full Chromium e2e pass on 2026-04-30:
    44 passed, 1 skipped.

- id: B3
  page: 404
  url: http://localhost:4319/results/does-not-exist/
  browser: chromium-147
  status: P
  notes: |
    Unknown benchmark slugs render NotFound with benchmark-specific copy.
    Covered by `routes/not-found.spec.ts` in the full Chromium e2e pass.

- id: B4
  page: platform
  url: http://localhost:4320/results/p/duckdb/
  browser: chromium-147
  status: P
  notes: |
    Chromium console-capture smoke on the platform timeline returned no
    duplicate-key, warning, or error messages: `[]`.

- id: N1-chromium
  page: home
  url: http://localhost:4319/results/
  browser: chromium-147
  status: P
  notes: |
    Home cold-load e2e smoke reached the populated `Recent Results` state in
    Chromium. Unit coverage also exercises the staged empty-result snapshot
    and confirms the 0/0/0 empty state does not render while data readiness is
    unresolved.

- id: N1-firefox
  page: home
  url: http://localhost:4319/results/
  browser: firefox-148
  status: P
  notes: |
    Firefox 148.0.2 smoke gate passed `Home › @smoke renders the header,
    counts, and recent-results table`.

- id: N2
  page: benchmark
  url: http://localhost:4319/results/tpch/?sf=0.01&phase=power
  browser: chromium-147
  status: P
  notes: |
    Invalid BenchmarkIndex phase URL state settles to `phase=standard` for the
    generated fixture corpus and renders the matching grid.

- id: N3
  page: benchmark
  url: http://localhost:4319/results/tpch/?sf=abc&phase=standard
  browser: chromium-147
  status: P
  notes: |
    Invalid BenchmarkIndex scale-factor URL state settles to `sf=0.01` and
    renders the matching grid.

- id: N4
  page: compare
  url: http://localhost:4319/results/compare?ids=a556e716
  browser: chromium-147
  status: P
  notes: |
    Single-id Compare URLs redirect to the corresponding ResultDetail route
    instead of rendering a one-row comparison.

- id: N5
  page: layout
  url: http://localhost:4319/results/
  browser: chromium-147
  status: P
  notes: |
    Vitest route-title coverage passed in the full suite: 30 test files,
    306 tests. Covered routes include Home, BenchmarkIndex, PlatformIndex,
    ResultDetail, Compare, Query, and NotFound.

- id: N6
  page: query
  url: http://localhost:4319/results/query
  browser: chromium-147
  status: P
  notes: |
    Query row-limit UI is covered by `routes/query.spec.ts`; Chromium e2e
    passed the `row-limit toggle updates the URL and shows the all-rows footer`
    case.

- id: E1
  page: home
  url: http://localhost:4319/results/?mode=speedup
  browser: chromium-147
  status: P
  notes: |
    The maintained QA plan now documents the intended speedup contract:
    best-in-cohort is `1.00×`; slower entries are below `1.00×`.

- id: pass3-gates
  page: layout
  url: http://localhost:4319/results/
  browser: chromium-147
  status: P
  notes: |
    Verification commands:
      - `cd results-explorer && npm run test`: 30 files, 306 tests passed.
      - `cd results-explorer && npm run typecheck`: passed.
      - `cd results-explorer && npm run test:e2e:chromium`: 44 passed,
        1 skipped.
      - `cd results-explorer && npm run test:e2e:firefox`: 8 passed.
      - Playwright browser versions: Chromium 147.0.7727.15, Firefox 148.0.2.

# totals: P=12 F=0 Q=0
