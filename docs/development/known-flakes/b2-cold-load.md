# B2: PlatformIndex empty rows on cold-load (DuckDB-WASM)

Manual reproduction procedure for the bug labelled **B2** in
`_project/TODO/main/active/results-explorer-qa-pass1-fixes.yaml`.

## Symptom

`/results/p/duckdb/` and `/results/p/polars/` (and occasionally other
platform pages) intermittently render:

```
heading: <slug> Results        # lowercase — display-name fallback
body:    No results found for platform: <slug>.
```

instead of the expected populated table. Reload the page and it usually
renders correctly. The empty state is indistinguishable from a real
"no results" condition because `PlatformIndex.tsx` shows the same
empty-state copy in both cases.

## Why this is not in the e2e harness

The standard harness (`npm run test:e2e:chromium`) regenerates
`test-fixtures/.generated/data/results.duckdb` from
`test-fixtures/source/` at the start of every run. The auto-fixture
corpus is too small to hit the race (3 platforms max in any cohort)
and any DB you copy in by hand gets wiped before the next test run.
`results-explorer/e2e/README.md` further forbids mutating
`results-explorer/public/data/` or `results-data/bundles/`.

A clean fix would inject a production-shape DB via Playwright route
interception (mock the `/results/data/results.duckdb` response). That
work is in scope for the eventual remediation but not the
investigation; this doc captures the manual procedure for now.

## Reproduction

From the worktree root:

```bash
cd results-explorer
npm install                          # if not already
npm run test:e2e:fixtures             # generate the small fixture corpus
npm run build                         # produce dist/
cp ../results-explorer/public/data/results.duckdb \
   test-fixtures/.generated/data/results.duckdb
# ^ Overwrite the small fixture DB with the production-shape one.
#   This file is gitignored under .generated/, so it does not violate
#   the e2e/README.md rule against mutating tracked data.

# Run the same Playwright command a few times. Expect ~50% failure rate
# on a fresh chromium context until the DuckDB-WASM module is warm.
for i in 1 2 3 4 5; do
  echo "=== run $i ==="
  npx playwright test --project=chromium --workers=1 \
    --grep "PlatformIndex" 2>&1 | tail -3
done
```

The original investigation (commit recorded in the YAML) saw runs
P/F, F/F, P/P across three serial invocations.

## What to capture before remediating

The mechanism is not pinned. Three plausible candidates:

1. **DuckDB-WASM cold-load partial data** — a `SELECT` resolves before
   the runtime has fetched all of the table's pages. Underlying
   range-read issue is tracked separately as
   `enable-duckdb-wasm-http-range-reads-for-registered-urls` (see
   `results-explorer/src/db.ts:67-77`).
2. **Preact `useEffect` cleanup race** — `PlatformIndex.tsx:24-40`
   uses `let cancelled = false; if (!cancelled) setRows(r)`. If a
   navigation triggers cleanup mid-flight, `setRows` is silently
   dropped and the page falls back to the empty state.
3. **Shared `initPromise` race in `db.ts:48-96`** — `getDb()` reuses
   `initPromise` across mounts. If component A starts the promise and
   component B awaits on a partially-resolved state, the resulting
   `dbInstance` could behave inconsistently.

Confirming which one is correct requires instrumentation —
`console.log("rows.length:", r.length)` inside `getPlatformIndexRows()`,
captured across 5+ failing and 5+ passing runs. The fix should be
chosen *after* the mechanism is confirmed, not before.

## When to delete this doc

Once w3 of `results-explorer-qa-pass1-fixes` lands and the cold-load
empty-state behaviour is removed, this doc moves to `_project/DONE/`
or is deleted outright. Do not let it rot.
