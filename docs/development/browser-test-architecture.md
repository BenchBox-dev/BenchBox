# Browser-functional test architecture for the results explorer

**Status:** Accepted - 2026-04-18
**Scope:** Locks the architecture decisions that gate implementation of the
browser-functional test layer tracked by
`implement-results-explorer-browser-functional-tests`.
**Audience:** Maintainers adding or modifying the explorer's `e2e/` suite.

This note records the four architecture decisions required by the TODO's
research gate. Each section states the decision, evidence from the current
repo, rejected alternatives, and the implementation consequences that follow.
No implementation starts on w2 or later until the decisions below are
considered binding.

---

## Current state the decisions must fit

- Routes are defined by `preact-router` in `results-explorer/src/App.tsx` under
  a hard-coded `/results/` base prefix, including `/results/compare`,
  `/results/query`, `/results/r/:resultId`, `/results/:benchmark/`, and
  `/results/p/:platform/`.
- The app is built by Vite with `base: "/results/"` (see
  `results-explorer/vite.config.ts`) and is deployed as a static SPA under
  `benchbox.dev/results/`. Cross-origin isolation headers
  (`Cross-Origin-Embedder-Policy`, `Cross-Origin-Opener-Policy`) are set on
  the dev server; production serves similarly.
- DuckDB-WASM is the sole browser store for user-visible metrics
  (`results-explorer/src/db.ts`). It lazy-loads a Vite-bundled same-origin
  worker/WASM bundle, attaches `/results/data/results.duckdb` as read-only via
  `ATTACH ... (READ_ONLY)`, and has no JSON fallback - any attach failure
  surfaces to the user.
- The DuckDB snapshot is produced by
  `_project/scripts/explorer_pipeline/pipeline.py` via
  `uv run -- python _project/scripts/explorer_publish.py build
  --data-dir <bundles> --output <dist-data>`.
- Local `npm run dev` first runs `npm run dev:snapshot`, which rebuilds
  `results-explorer/public/data/results.duckdb` when the local snapshot is
  missing or older than `results-data/bundles/` or the Explorer publish
  pipeline. Set `EXPLORER_SKIP_PREDEV=1` only when intentionally testing a
  missing or stale snapshot error path.
- Unit and component coverage lives under `results-explorer/src/__tests__/`,
  `results-explorer/src/components/__tests__/`,
  `results-explorer/src/lib/__tests__/`, and
  `results-explorer/src/pages/__tests__/`. Vitest runs in jsdom - no real
  browser, no real WASM worker, no real `Worker`/`Blob` URL creation.
- The only prior real-browser verification work is
  `verify-trust-badge-rendering-in-explorer` (done 2026-04-12). It used an
  ad-hoc local Playwright-driven check plus a throwaway fixture branch and
  explicitly discarded the branch in its `scope_limit`. There is no
  durable harness, fixture generator, or CI gate yet.
- The production archived handoff
  (`_project/_archive/handoffs/handoff-results-publishing-phase2.md`) notes
  cross-browser acceptance stayed manual through Phase 1 launch.

---

## Decision 1 - Built app as the test target

**Decision.** The browser-functional suite runs against the production build
output (`results-explorer/dist/`) served by a Playwright `webServer`, not
against `vite dev`.

**Why.**

- DuckDB-WASM is code-split into its own chunk by
  `vite.config.ts`'s `manualChunks.duckdb` rule. Dev-mode ESM module graph
  loading behaves differently from the built chunked output, so asset
  resolution and worker URL construction are only validated in `dist/`.
- The `/results/` base path, the `ATTACH ... (READ_ONLY)` URL derived in
  `db.ts` via `new URL("/results/data/results.duckdb", window.location.origin)`,
  and relative asset references are all path-sensitive and only match
  production when Vite has emitted built assets under `/results/`.
- The dev server re-transforms modules on request and injects HMR - that
  masks real browser MIME and caching behavior, and it cannot reproduce
  the same-origin worker/WASM asset URLs that DuckDB-WASM resolves in the
  built explorer.
- `must_preserve` requires that "the explorer continues to run correctly
  under the `/results/` base path" and that deep links stay valid. The only
  way to verify that claim per run is to load the compiled `dist/` under the
  real prefix.

**Rejected alternatives.**

- **Run against `vite dev`.** Fast to start but masks chunking, base-path,
  and worker behavior (the exact surface we need to cover).
- **Run against a previewed dev build (`vite preview`).** Acceptable in
  principle - it serves `dist/` - but it does not allow us to swap in a
  test-only `/results/data/` directory without rebuilding. We need that
  swap to be cheap per-test-run (see Decision 2), so we front `dist/` with
  a tiny static wrapper instead.

**Consequences.**

- The harness runs `npm run build` once per Playwright run (Playwright's
  `webServer` block handles this), then serves `dist/` through a minimal
  static server that routes `/results/data/*` to the generated fixture
  corpus and everything else to `dist/`.
- Suite startup is slower than dev-server tests. That is the right tradeoff
  for a quality gate; developers keep Vitest as the fast inner loop
  (explicit in `must_preserve`).
- Playwright `webServer` with `reuseExistingServer: true` locally keeps
  iteration tolerable once the first build lands.

---

## Decision 2 - Generated fixture corpus in an isolated workspace

**Decision.** Each test run regenerates its fixture DuckDB snapshot into
`results-explorer/test-fixtures/.generated/` (gitignored). The static
server mounts that directory at `/results/data/` for the duration of the
run. `results-explorer/public/data/` and `results-data/bundles/` are not
touched.

**Why.**

- `results-explorer/public/data/bundles/` and `results.duckdb` are the
  committed curated corpus. `must_preserve` and `scope_limit.do_not_modify`
  explicitly forbid mutating them. Tests that need compare-invalid cohorts,
  mixed trust labels, or missing sidecars would otherwise have to either
  pollute that data or depend on whatever happened to be checked in at
  test time.
- `results-data/bundles/` is the public curated source - same prohibition.
- The pipeline already has a supported data-in / data-out shape:
  `uv run -- python _project/scripts/explorer_publish.py build --data-dir <in>
  --output <out>` reads bundles from any directory and writes `results.duckdb`
  plus copied bundle downloads to any directory. We do not need a new seam;
  we need a thin fixture generator that:
  1. Copies canonical schema-v2 bundles (and companion `.plans.json`
     / `.tuning.json` / `<result>.manifest.json` sidecars) from a small
     committed source set under `results-explorer/test-fixtures/source/`
     into an ephemeral staging dir.
  2. Applies controlled metadata mutations in memory per variant
     (trust label, tuning mode, sidecar presence, compare-invalid
     mismatches).
  3. Runs `uv run -- python _project/scripts/explorer_publish.py build`
     against the staging dir, writing into
     `results-explorer/test-fixtures/.generated/data/`.
- Mutating metadata in an ephemeral staging copy - rather than via the
  published corpus - means the generator can produce compare-invalid
  cohorts (benchmark mismatch, scale mismatch) without violating the
  ≥3-platform depth invariant that
  `launch-results-explorer-acceptance-and-seed` pinned on the real corpus.

**Rejected alternatives.**

- **Mutate `results-explorer/public/data/` during test setup and restore
  after.** Explicitly forbidden by `must_preserve`. Also fragile: a test
  crash mid-run leaves the public corpus in a bad state and can leak into
  commits.
- **Commit a second fixture DuckDB file.** Binary artifacts decay, do not
  round-trip pipeline changes, and couple the suite to whatever version of
  `explorer_pipeline/duckdb_builder.py` built them. Regenerating forces
  each run to exercise the actual pipeline - which is the real contract
  under test.
- **Mock `getDb()` to return a stub.** That is what Vitest already does.
  The missing coverage is specifically the real WASM worker, real HTTP
  attach, and real `ATTACH READ_ONLY` behavior. Mocking defeats the point.

**Consequences.**

- `results-explorer/test-fixtures/source/` is committed (small, curated -
  one bundle per benchmark we need plus a compare-invalid cohort).
- `results-explorer/test-fixtures/.generated/` is gitignored.
  `results-explorer/test-results/` (Playwright artifacts) is also
  gitignored.
- A small Python glue module under `_project/scripts/explorer_pipeline/` is
  permitted if a test-only metadata mutator is needed, but the first slice
  prefers a pure-fixture approach where the committed source bundles
  already encode each variant and the fixture generator just re-runs the
  pipeline.
- The static server used in Decision 1 routes `/results/data/` → the
  generated directory. That makes the fixture swap a directory mount
  rather than a file copy.

---

## Decision 3 - Chromium blocking, Firefox/WebKit smoke only (initially)

**Decision.** Chromium runs the full suite and is a blocking gate in CI from
the first merge. Firefox and WebKit run only tests tagged `@smoke` and
are non-blocking for two weeks of stable data, after which they graduate
based on observed flake rate.

**Why.**

- `anti_patterns` warns: "DO NOT make all three browsers blocking before
  flake characteristics are known." DuckDB-WASM has known browser-specific
  loading quirks (the archived handoff calls this out explicitly), and
  WebKit's `Worker`/`SharedArrayBuffer` support varies by version.
- The phase-1 launch acceptance
  (`launch-results-explorer-acceptance-and-seed` w2) treated cross-browser
  as manual per-release. That is the residual manual pass we keep (w6).
  The automation's job is to catch Chrome-class regressions deterministically
  and give us Firefox/WebKit early-warning signal, not to block merges on
  WebKit flake.
- Our WebKit coverage can only run on macOS runners. Making WebKit required
  pins the gate to a specific runner family and adds queue pressure.

**Rejected alternatives.**

- **All three browsers blocking from day one.** High false-failure rate
  risk, no prior flake data for this app, and likely to stall adoption.
- **Chromium only, forever.** Misses Firefox and WebKit regressions until
  manual release check catches them - which is the current state we are
  explicitly trying to improve.
- **Chromium + Firefox blocking, WebKit smoke.** Firefox does have the
  fewest known DuckDB-WASM quirks, but we still lack flake data. Stage
  Firefox to blocking only after real CI signal.

**Consequences.**

- Playwright `projects` config declares three projects: `chromium`
  (default grep), `firefox` (grep `@smoke`), `webkit` (grep `@smoke`).
- Tests meant for cross-browser smoke coverage are tagged `@smoke` in
  their titles. New happy-path route tests start Chromium-only; we
  promote them to `@smoke` as they prove stable.
- CI has three jobs: `e2e-chromium` (required), `e2e-firefox` (optional
  / warning only), `e2e-webkit` (optional / warning only, macOS runner).
- w7 explicitly gates the cross-browser promotion decision on repeatable
  runs, not on a single green CI job.

---

## Decision 4 - No production seam for failure injection; use Playwright routing

**Decision.** All required failure-path coverage is achieved through
Playwright's `page.route()` interception and context capabilities. No
test-only code path, feature flag, or bypass is added to the production
bundle.

**Why.**

- The error surface the suite must prove is already user-visible:
  `db.ts` rejects `getDb()` when `ATTACH` fails, and pages are documented
  to "surface the error to the user rather than silently rendering empty
  state." We test that user-visible state, not the internal exception.
- The failure modes the TODO enumerates all map cleanly to HTTP-level
  interception:
  - DuckDB snapshot missing/corrupt/unreachable → intercept
    `/results/data/results.duckdb` and return 404, truncated bytes, or
    network abort.
  - Tuning-config sidecar fetch failure → intercept the sidecar URL and
    return 404 or 500.
  - Online/offline → `browserContext.setOffline(true)` plus the existing
    `window.addEventListener("online")` retry logic in `db.ts`.
  - Clipboard/share URL → `context.grantPermissions(['clipboard-read',
    'clipboard-write'])` and assert via `navigator.clipboard.readText()`.
  - Download flows → `page.waitForEvent('download')` with
    `download.saveAs()` into the artifact directory.
- `must_preserve` requires that the query workbench stays read-only and
  that no test-only writable bypass is introduced. The cleanest way to
  guarantee that is to add no seam at all.
- A production seam would also drift: tests passing against the seam
  could diverge from real browser behavior, which is the jsdom problem
  we are already trying to solve.

**Rejected alternatives.**

- **Add a `?test=1` query-param branch in `db.ts` that loads a fixture
  URL.** Pollutes production code with test-only conditionals and risks
  leaking into shipped builds.
- **Inject a window global for the harness to toggle error modes.**
  Same objection; also a supply-chain footgun if any production code ever
  reads it.
- **Build a parallel "test mode" bundle.** Doubles the build matrix and
  invalidates the point of testing the production build.

**Consequences.**

- Failure-path tests live alongside happy-path tests; each uses
  `page.route()` helpers defined in `results-explorer/e2e/support/`.
- Read-only SQL enforcement is verified by running `INSERT` / `UPDATE` /
  `DROP` through the Query workbench UI and asserting the user-visible
  error, not by poking at internals.
- If a future feature genuinely needs a seam (e.g., slow-network
  simulation that Playwright cannot express), that's a separate decision
  and requires its own note here.

---

## Decision summary

| # | Question | Decision |
|---|----------|----------|
| 1 | Built app vs dev server | Built `dist/` served by Playwright `webServer`. |
| 2 | Fixture corpus location | Generated per-run into `results-explorer/test-fixtures/.generated/` (gitignored); mounted at `/results/data/`. Curated corpus untouched. |
| 3 | Browser matrix | Chromium full + blocking. Firefox & WebKit `@smoke` only, non-blocking initially. |
| 4 | Failure-injection seam | None. All failure paths covered via Playwright `page.route()`, offline toggle, and permissions. |

## Implementation gating

- w2 may begin once this note is merged. w2's `playwright.config.ts`,
  `webServer` block, and `projects` list must match Decisions 1 and 3.
- w3's fixture generator must match Decision 2; it must not write outside
  `results-explorer/test-fixtures/.generated/`.
- w5 must rely on the interception surface in Decision 4 and must not
  introduce a production-code seam. Any deviation requires an update to
  this note and re-approval.
- w6 must not promote Firefox or WebKit to blocking without recorded flake
  data; the graduation criteria are part of w7.
