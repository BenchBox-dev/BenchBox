# Results Explorer browser CI - lane status

**Audience:** Maintainers watching `.github/workflows/results-explorer-browser.yml`
and anyone triaging a red or advisory browser-lane check on a PR.
**Companion docs:** [`docs/development/browser-test-architecture.md`](../development/browser-test-architecture.md)
(why the suite is shaped this way) and
[`docs/development/results-explorer-browser-testing.md`](../development/results-explorer-browser-testing.md)
(how to run the suite locally, what's covered, how to add tests).

## Current lane status

| Browser  | Job name                          | Scope                | Gate       | Status as of 2026-07-23 |
|----------|------------------------------------|-----------------------|------------|--------------------------|
| Chromium | `Chromium (full suite, blocking)` | Full `e2e/` suite      | Blocking   | Cold-start flake mitigated 2026-07-25 (see below) |
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
