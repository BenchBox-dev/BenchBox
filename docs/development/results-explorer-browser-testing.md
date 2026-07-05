# Results Explorer - browser testing

**Audience:** Maintainers making changes to `results-explorer/` and release
drivers who need to know what browser coverage exists and what still must be
checked by hand.

This note is the operational counterpart to
[`browser-test-architecture.md`](browser-test-architecture.md). The architecture
note records *why* the suite is shaped the way it is; this note records *what
to run, when to run it, and what to do when it fails*.

## What's covered by automation

The Playwright suite under `results-explorer/e2e/` runs against the built
explorer (`dist/`) served via the static test server at
`results-explorer/scripts/serve-browser-tests.mjs`. Fixtures are generated
per run into `results-explorer/test-fixtures/.generated/` - the curated
public corpus is never modified.

Routes and behaviours with at least one browser-functional test:

| Route / surface | Happy path | Failure path |
|-----------------|------------|--------------|
| Home            | ✅          | -            |
| BenchmarkIndex  | ✅          | -            |
| PlatformIndex   | ✅          | -            |
| ResultDetail    | ✅          | ✅ (unreachable `results.duckdb`, sidecar fetch failure, unknown id) |
| Compare         | ✅ (deep link, share URL, sticky-bar flow) | ✅ (benchmark mismatch, scale mismatch, unknown id) |
| Query workbench | ✅ (sort, column toggle, starter query, CSV + JSON download) | ✅ (read-only write surfaces error) |
| NotFound        | ✅ (unknown `/results/...` path renders the 404 card) | - |
| DuckDB-WASM attach | ✅ (cold load, `waitForDataLoaded`) | ✅ (RG-2 range-read capability via test server) |

## Running the suite locally

Prerequisites: a Python toolchain with `uv`, Node 20+, and the explorer's
dependencies installed.

```bash
cd results-explorer
npm ci
npm run test:e2e:install       # one-time: installs Chromium/Firefox/WebKit
npm run test:e2e:chromium      # deterministic local/CI entrypoint
npm run test:e2e:full          # local full-matrix convenience entrypoint
```

On a clean machine, `npm run test:e2e:chromium:setup` wraps the one-time
browser install plus the same deterministic Chromium run.

Each browser script regenerates the fixture corpus and rebuilds `dist/`
before Playwright starts the static server, so the command stays aligned
with the shipped harness contract. `npm run test:e2e:full` is the
one-command local convenience path; CI stays split into per-browser jobs
so Chromium can block independently while Firefox/WebKit remain
non-blocking `@smoke`.

Cross-browser smoke passes:

```bash
npm run test:e2e:firefox
npm run test:e2e:webkit
```

Failure artifacts (traces, screenshots, video, HTML report) land under
`results-explorer/test-results/` and `results-explorer/playwright-report/`
and are both gitignored.

## What CI gates

[`.github/workflows/results-explorer-browser.yml`](../../.github/workflows/results-explorer-browser.yml)
runs on **pull requests** (to `main` or `develop`) that touch `results-explorer/`,
`_project/scripts/explorer_pipeline/`, `_project/scripts/explorer_publish.py`,
`results-data/`, or the workflow file itself, and on **pushes to `main`** that
touch those paths. Pushes to `develop` do not run it (the post-merge lane runs
only the token/theme scans and unit/fast tests).

- **Blocking:** `chromium` job - full suite must pass.
- **Non-blocking:** `firefox-smoke` and `webkit-smoke` jobs - `@smoke`-tagged
  subset only, `continue-on-error: true`. These graduate to blocking once the
  flake data collected during w9 of
  `implement-results-explorer-browser-functional-tests` supports it.

All three jobs upload Playwright reports on failure with a 14-day retention
so maintainers can download a full trace from the PR checks page. The CI
jobs call the same shared browser scripts that maintainers run locally,
rather than re-encoding fixture/build/test sequencing in the workflow.

## Manual release check

Automation does not replace the short cross-browser pass a maintainer should
run before shipping a meaningful explorer change. "Meaningful" means any PR
that touches routing, `src/db.ts`, a page component, or the pipeline that
produces `results.duckdb`.

Check the following in Chrome, Firefox, and Safari - one pass each, not a
full regression run:

1. **Home** - header, counts, recent-results table render; deep link into a
   benchmark index from the browse-by-benchmark card works.
2. **BenchmarkIndex** - the SF filter updates the URL; each platform row
   links to a ResultDetail.
3. **ResultDetail** - run header, badges, and timings table render; "Compare
   this result" deep-links into Compare.
4. **Compare** - two-platform compare renders side-by-side cards; Share URL
   button copies the current URL; hard-block error renders cleanly for a
   mismatched cohort.
5. **Query** - schema-driven table renders; a starter query populates the
   SQL textarea; Download CSV and Download JSON both emit a file.
6. **NotFound** - an unknown `/results/...` path renders the 404 card and
   the "Back to Results" recovery link.

Focus on layout, font rendering, scroll behaviour, and clipboard/download
permissions - the parts that Playwright covers functionally but cannot
judge visually.

## When a CI run fails

1. Open the failed job, download the `playwright-report-*` artifact, and
   open `index.html` in a browser. The trace viewer is the fastest path to
   understanding the failure.
2. If the failure is browser-specific and reproduces locally, keep the
   browser-specific fix scoped to that browser.
3. If the failure does not reproduce locally, capture it as a flaky-test
   TODO rather than re-running the PR until it passes. See w9 of the parent
   TODO for the flake-triage pattern.

## Adding new tests

- Put happy paths under `results-explorer/e2e/routes/` and tag the primary
  spec per route with `@smoke`.
- Put failure paths under `results-explorer/e2e/failures/`. Assertions must
  target user-visible error states (a visible heading or message), not just
  thrown exceptions or console output.
- Put server/runtime contract checks that are not user failure paths
  under `results-explorer/e2e/capability/` (e.g. the RG-2 range-read
  gate in `capability/range-read-budget.spec.ts`).
- If a test depends on fixture data that does not yet exist, add a variant
  to `results-explorer/scripts/generate-browser-fixtures.mjs` - do not
  mutate the curated public corpus.
- If a test needs failure injection, prefer Playwright's `page.route()`,
  `context.setOffline`, permission grants, and download events. Do not
  introduce a production-code test seam.
