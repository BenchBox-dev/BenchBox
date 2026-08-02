# Results Explorer browser CI - lane status

**Audience:** Maintainers watching `.github/workflows/results-explorer-browser.yml`
and anyone triaging a red or advisory browser-lane check on a PR.
**Companion docs:** [`docs/development/browser-test-architecture.md`](../development/browser-test-architecture.md)
(why the suite is shaped this way) and
[`docs/development/results-explorer-browser-testing.md`](../development/results-explorer-browser-testing.md)
(how to run the suite locally, what's covered, how to add tests).

## Frontend dependency audit

The blocking Chromium job and the nightly parity job run
`npm run audit:high` immediately after `npm ci`. The command fails on any
high or critical advisory; low-severity build-tool advisories remain visible
in the audit output and are not silently allowlisted. Dependency updates must
use the narrowest patched range and retain deterministic `npm ci` behavior;
`npm audit fix --force` is not an accepted remediation. The only transitive
override currently present is `undici >=7.28.0`, constrained to remove the
Playwright tooling advisory range; remove it when the upstream graph no longer
needs it.

## Current lane status

| Browser  | Job name                          | Scope                | Gate       | Status as of 2026-07-23 |
|----------|------------------------------------|-----------------------|------------|--------------------------|
| Chromium | `Chromium (full suite, blocking)` | Full `e2e/` suite      | Blocking   | Zero-row snapshot race mitigated 2026-07-29 (see correction below) |
| Firefox  | `Firefox (@smoke, non-blocking)`  | `@smoke`-tagged subset | Advisory   | Green in recent history |
| WebKit   | `WebKit (@smoke, non-blocking)`   | `@smoke`-tagged subset | Advisory   | Fixed 2026-07-23 (see below) - was deterministically red on PRs #1264 and #1270 |

WebKit root cause (`webkit-smoke-fix-or-demote-2`): four `@smoke` specs
(`benchmark-index`, `platform-index`, `query`, and the funding-legend test in
`funding-disclosure`) asserted a data-bound heading or control with the
Playwright default 10s expect timeout, immediately after `waitForShell()`
(which only waits for the static header link, not for data). WebKit's
cold-start DuckDB-WASM attach - even single-threaded, per the `--workers=1`
fix from `stabilize-webkit-browser-smoke-flake-under-parallel-workers` -
regularly exceeds that 10s budget, while Chromium and Firefox do not. Sibling
assertions in the same spec files that already called `waitForDataLoaded()`
(30s timeout) or used an explicit 20s timeout passed consistently, which is
what pointed at timeout margin rather than a functional break. The fix adds
`waitForDataLoaded()` calls ahead of the four assertions, matching the
existing in-file pattern - no test was skipped, no assertion was weakened.

## Chromium cold-start flake (2026-07-25)

On PR #1298 the Chromium blocking gate went red on a *genuinely flaky*
(varies run-to-run) data-load timeout: a different spec timed out each run
(`result-detail-failures` one run, `compare` the next), always the same
symptom - the first data-bound element never rendered within the wait window
- while 103-107 of 111 tests passed. Two independent runs failed on different
specs, which is the "varies across attempts" signal from the triage rule
below, not a functional break in the PR under test. The required
`test:e2e:chromium` command runs both Playwright invocations with
`--workers=1`, so the live cause is serial DuckDB-WASM cold-start exceeding
the 30s `waitForDataLoaded` budget, not concurrent-worker contention.
(Superseded - see the 2026-07-29 correction below. It is not a cold-start
latency problem at all.)

Mitigation (harness-only, no `results-explorer/src/**` change; the blocking
command remains serial):

- `waitForDataLoaded` budget 30s -> 45s (matches the margin the suite's
  careful inline data waits already use, and the exact value the failing
  `result-detail-failures` inline wait used).
- Per-test `timeout` 60s -> 90s so a ~45s data wait plus the rest of a flow
  fits inside the cap.
- CI `retries` 1 -> 2 so a spec slow on both its first attempts gets a third.
  A real regression still fails all three attempts (deterministic), so this
  does not mask functional breaks.

### Correction (2026-07-29): it was never a latency problem

The diagnosis above is wrong, and the timeout widening it prescribes cannot
work. Measured locally on an idle machine, serial (`--workers=1`), with the
45s budget in place:

- Every flaky spec burned the **entire** 45s and the element never appeared.
  A budget that is never nearly met is not a budget problem.
- The suite's own performance spec puts DuckDB-WASM cold init at
  **P50 564ms / P95 978ms**, and leaderboard data after init at P50 6ms. A
  healthy load finishes ~45x inside the old 30s budget.
- In `compare-entrypoints` the route heading rendered while the result rows
  stayed empty; in `responsive` and `index-sort-headers` the same, the heatmap
  and grid rows never arriving after the heading was visible.

The live cause is a **cold-snapshot zero-row race**: the first keyed query
against a not-yet-queryable DuckDB-WASM snapshot answers with zero rows, the
view renders its empty state, and it never re-queries. No single-shot budget
can ever succeed against that; only a fresh navigation can, which is exactly
why CI (`retries: 2`) stayed green while the same specs still failed locally
(`retries: 0`).

A second, compounding harness bug: `waitForDataLoaded(page, /TPC-H Results/)`
waits on a **shell-rendered route heading**, not on data. It returns happily
while the snapshot is still empty, so every row-bound assertion after it races
the snapshot with only the 10s default `expect` timeout.

Current mitigation (`e2e/support/fixtures.ts`):

- Data waits run up to three attempts (10s + 8s + 8s, plus two re-navigations
  bounded at 10s each: ~46s worst case, about the 45s it replaces) and
  **re-navigate to the entry URL between attempts**, which is the only action
  that clears the race. Attempts are deliberately shorter than the single 45s
  budget: a healthy load finishes in ~1s, so a racing wait now costs ~10s
  before it re-navigates rather than burning 45s. That matters because several
  specs chain multiple data waits inside one 90s per-test cap.
- Re-navigation is skipped if the page has left the URL the wait began on, so
  a wait placed after a click cannot rewind the page under the test.
- `waitForResultRows(page, scope, minimum)` gates on real `tbody
  tr[data-testid]` rows **within the table under test**, instead of trusting a
  shell heading.

**This is mitigation, not a fix, and it costs one class of coverage.** A
regression that breaks only the *first* load — every user's first visit renders
the empty state, a reload fixes it — now passes on attempt 2, so a wait that
re-navigates **cannot** catch first-load-only correctness. That is the same
defect class being worked around here, which is exactly where regression
pressure is highest. A regression that survives a reload still fails every
attempt.

To keep that coverage somewhere, `e2e/failures/platform-index-cold-load.spec.ts`
deliberately does **not** use the re-navigating helpers: it is the dedicated
cold-load regression guard (the pass-1 bug it pins surfaced as *partial* rows,
1 of 5, which a `count > 0` check would have passed). Leave its single-shot
waits and exact row counts alone — if it flakes, that is signal, not noise.

The blocking Chromium command therefore runs every spec under `e2e/failures/`
in a separate `--retries=0` invocation. The ordinary CI retry policy must not
turn a probabilistic cold-load regression into a flaky-but-green gate.

`queryRows` deliberately retries only zero-row answers during the bounded cold
window. A generic non-empty result carries no trustworthy completeness signal:
retrying every non-empty query would penalize legitimate `LIMIT`, filtered, and
streaming reads, while guessing expected row counts from SQL would be brittle.
Partial non-empty reads are therefore an accepted residual risk at this layer,
pinned by the dedicated cold-load spec's fixture-derived exact row counts.

The root cause is in `results-explorer/src/**` (gate the first keyed query on a
queryable snapshot, or re-query when it returns zero rows), tracked as
`explorer-cold-snapshot-zero-row-race-20260729`; the e2e suite is not permitted
to change `src/**`. Until that lands, expect residual flake at any data-bound
assertion that still waits single-shot, and treat the coverage gap above as
live.

## Triage rule

**Firefox is green in recent CI history; do not dismiss WebKit failures as
flake.** A prior WebKit fix
(`stabilize-webkit-browser-smoke-flake-under-parallel-workers`) addressed a
*concurrent-workers* race. `webkit-smoke-fix-or-demote-2` shows that
"non-blocking" does not mean "safe to ignore" - the same job stayed
deterministically red across two PRs a day apart because per-test timeout
margin, not worker contention, was the live issue. When the WebKit job goes
red:

1. Do not assume it's a known flake. Pull the job log and identify which
   spec(s) fail and whether the failure is identical across the retry
   attempt (deterministic) or varies (genuinely flaky).
2. Compare against Firefox's result for the same run. If Firefox is green
   and WebKit is red on the same commit, the failure is WebKit-specific, not
   an environment-wide break.
3. Check whether the failing assertion is data-bound (depends on the
   DuckDB-WASM corpus query resolving) and whether it uses `waitForShell`
   only versus `waitForDataLoaded`/an extended timeout. This exact pattern
   caused `webkit-smoke-fix-or-demote-2`.
4. If a real fix requires touching `results-explorer/src/**`, do not attempt
   it under the browser-CI TODO scope - file it separately and demote the
   WebKit job to nightly-only (`.github/workflows/nightly.yml`) with a
   linked tracking issue rather than leaving it both non-blocking and red.

## Graduation path

Firefox and WebKit `@smoke` stay advisory (`continue-on-error: true`) until
each independently clears the 10-consecutive-green criterion defined in
`graduate-browser-smoke-to-blocking-gates`. Each browser is promoted in its
own commit - do not batch both, and do not promote on a calendar/release
schedule. The Chromium full-suite blocking gate is unaffected by either
browser's promotion status.
