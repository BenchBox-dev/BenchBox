# Results Explorer browser CI - lane status

**Audience:** Maintainers watching `.github/workflows/results-explorer-browser.yml`
and anyone triaging a red or advisory browser-lane check on a PR.
**Companion docs:** [`docs/development/browser-test-architecture.md`](../development/browser-test-architecture.md)
(why the suite is shaped this way) and
[`docs/development/results-explorer-browser-testing.md`](../development/results-explorer-browser-testing.md)
(how to run the suite locally, what's covered, how to add tests).
**Admin wiring:** [`docs/operations/repo-admin-settings.md`](repo-admin-settings.md)
(develop ruleset required checks).

## Merge-gate decision

**Decision: the Chromium full suite gates merges.** The job name
`Chromium (full suite, blocking)` is truthful: Chromium is not
`continue-on-error`, and its result feeds a required status check on
`develop`.

### How the gate actually blocks

Merge blocking is **not** wired through `ci-required-result` in
`.github/workflows/pr.yml`. Cross-workflow `needs` is not a GitHub Actions
feature, so the browser suite cannot be a subordinate of that umbrella.
It is wired through the develop branch ruleset instead:

| Piece | Value |
|-------|--------|
| Ruleset | `develop-squash-only` (resolve by name; current id `15611785` until a transfer) |
| Required context | `Results Explorer browser gate` |
| Gate job | `browser-required-result` in `results-explorer-browser.yml` |
| Gate inputs | `needs: [explorer-changes, chromium]`, `if: always()` |

The gate job, not the Chromium job itself, holds the required context.
Chromium is path-gated via `explorer-changes` and is skipped when nothing
explorer-relevant changed; a required check that never reports leaves a PR
unmergeable forever. The gate therefore always runs and:

- **passes** when Chromium succeeded, or when change detection said the
  suite was not needed (`needed=false` and Chromium was legitimately skipped);
- **fails closed** if Chromium failed/cancelled, if Chromium was skipped while
  `needed=true`, or if `explorer-changes` itself did not succeed.

Firefox and WebKit remain advisory (`non-blocking` in the job name,
`continue-on-error: true`) and are deliberately absent from the gate job's
`needs`. Promote them only via the graduation path below.

Live ruleset confirmation:

```bash
gh api repos/joeharris76/BenchBox/rulesets --jq '.[] | select(.name=="develop-squash-only") | .id' \
  | xargs -I{} gh api repos/joeharris76/BenchBox/rulesets/{} \
  --jq '.rules[]|select(.type=="required_status_checks")'
```

Expect both `ci-required-result` and `Results Explorer browser gate` in
`required_status_checks`. Unit tests under
`tests/unit/workflows/test_results_explorer_browser_gate.py` pin the
workflow-local half of the name/wiring agreement (Chromium not
`continue-on-error`, gate depends on Chromium, documented context string);
the live ruleset membership is the admin half.

### Historical note

The Chromium job advertised "blocking" before the ruleset required the gate
context. That name-without-wiring defect is closed: the required check and
the always-running gate job exist, and recent browser workflow runs are
green. Do **not** rename Chromium away from "blocking" while it still feeds
the required gate — that would re-create the lie in the opposite direction.
Do **not** demote the suite solely because retry-based data waits trade a
class of first-load coverage (see the cold-snapshot section below); that is
a known residual risk, not evidence the gate should be unwired.

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

## WebKit `/results/tpch/` data-bind failure (2026-08-03 investigation)

The failure signature is the harness's own message:

```text
Data-bound wait failed after 3 attempts (budgets 10s + 8s + 8s, 26.2s elapsed)
on http://127.0.0.1:4319/results/tpch/. Re-navigation ... did not help, so this
is NOT the cold-snapshot zero-row race that budget is sized for -- do not "fix"
it by widening the budget.
```

That distinction still holds: this is not the zero-row race in the section
above, and widening `DATA_ATTEMPT_BUDGETS_MS` is not a fix for either.

**Status: not reproducible, and not observed on any tree that contains #1484.**
Recorded here so the next occurrence starts from evidence rather than from
scratch.

### What the CI history actually shows

Every `/results/tpch/` occurrence landed on a branch that predates #1484
(`chore: enforce results explorer dependency audit`, merged 2026-08-03 12:47
UTC), which bumped `@playwright/test` from `^1.49.0` to `^1.62.1`:
`feat/results-explorer-cohort-identity-contract` and
`feat/results-explorer-corpus-sanitization`. Every run on a tree containing
#1484 has a green WebKit job. The one post-#1484 WebKit failure
(run 30864773163) is a different, fully explained cause: PR #1496 renamed the
Home headline and `home.spec.ts` still asserted the old string.

Correlation is not causation here — see the refuted hypotheses below.

### Reproducing Linux WebKit locally

macOS WebKit is a different build and passes where CI fails, so a local macOS
run is not evidence. Use a Linux container. Build the fixtures and `dist/` on
the host first — fixture generation shells out to `uv`/Python, which the
Playwright image does not carry:

```bash
# Build in a subshell so the rsync source below still resolves from the
# repository root, and create the mount point first - rsync will not create
# multiple missing destination components on a machine with no leftover state.
(cd results-explorer && npm run test:e2e:fixtures && npm run build)
mkdir -p /tmp/linux-wk
rsync -a --exclude node_modules --exclude playwright-report \
  --exclude test-results results-explorer/ /tmp/linux-wk/results-explorer/
mocker run -d -m 8g --cpus 4 -v /tmp/linux-wk:/work \
  mcr.microsoft.com/playwright:v1.62.1-noble \
  sh -c 'exec > /work/run.log 2>&1
    cp -a /work/results-explorer /app && cd /app && rm -rf node_modules
    npm ci --no-audit --no-fund
    CI=1 npx playwright test --project=webkit --workers=1 --retries=0 \
      --reporter=line'
```

Two container gotchas cost real time; both are worked around above:

- **Run detached (`-d`) and write logs into the mount.** An attached
  `mocker run` is torn down after roughly 30 seconds — it returns exit 0 with
  the work unfinished, which reads exactly like a passing run.
- **Match the image tag to the tree's `@playwright/test` pin.** A mismatch
  fails with `Executable doesn't exist at /ms-playwright/webkit-<n>`, not with
  a data-bind error.

### Hypotheses tested and refuted

| Hypothesis | Test | Result |
|---|---|---|
| Fixed on develop by the #1496–#1500 batch | develop tree, Linux WebKit, full `@smoke` | 16/16 pass — consistent, but does not isolate a cause |
| Caused by the older Playwright/WebKit build | Known-bad tree at its own 1.59.1 pin | **Refuted** — passes |
| Fixed by the 1.62.1 bump | Same known-bad tree upgraded to 1.62.1 | **Refuted** — passes at both versions |
| CPU/memory starvation on shared runners | develop tree at 2 cores / 2 GB, 3 consecutive runs | **Refuted** — 3/3 pass (10.0s, 9.0s, 8.7s) |

### The amd64 arm (2026-08-04)

The architecture variable left open above has now been run. It does not close
the investigation, and the reason is worth recording so nobody re-runs it
expecting an answer.

Under `--platform linux/amd64` (Rosetta emulation on Apple silicon; requires
`softwareupdate --install-rosetta`, otherwise the container fails to bootstrap
with `Rosetta is not installed`) the develop tree fails **10 of 16** WebKit
`@smoke` tests, `benchmark-index` 3/3, with the CI signature exactly:
`waitForDataLoaded` throwing at `e2e/support/fixtures.ts:124`. On `linux/arm64`
the same tree passes 16/16.

That looks like a reproduction and is not one. The emulated run took
**10.5 minutes** (630s) against **58 seconds** on arm64.

**No slowdown ratio can be computed from those two numbers, in either
direction.** The 630s includes ten tests that were *terminated* by their wait
budgets before completing their normal workload, while the arm64 run completed
all 16; Playwright's polling also overlaps application processing. Subtracting
the timeout budgets does not repair that - it leaves work for six completed and
ten aborted tests, which is not comparable to 58s of sixteen completed ones. An
earlier revision of this section claimed "~11x", then "~6x upper bound"; both
were unsupported and have been withdrawn. A defensible figure would need
matched successful-phase timings, which this arm did not collect.

The direction is all this arm supports, and it is enough: every failure is a
data-bound wait exhausting its budget, which any large slowdown produces
regardless of cause. GitHub's runners are *native* amd64, not emulated, and the
WebKit lane is green there.

So the architecture hypothesis is **not supported**: native amd64 passes in CI,
and the emulated failures are a timing artifact of the emulator.

| Hypothesis | Test | Result |
|---|---|---|
| Architecture (arm64 harness vs amd64 CI) | develop tree under emulated `linux/amd64` | **Confounded, not supported** — 10/16 fail under an emulator of unquantified slowness; native amd64 is green in CI |

What the arm does establish is a robustness fact worth keeping: these waits
fail by timeout under a slow enough environment rather than degrading
gracefully. A slow runner therefore stays a plausible trigger for the original
failures, even though CPU starvation at 2 cores was not enough to produce one.
How slow is slow enough remains unmeasured.

**Do not run the emulated amd64 arm again** — its result is known and
uninformative. The next real step is a *native* amd64 reproduction, which means
running the harness on a GitHub runner (`workflow_dispatch` on
`results-explorer-browser.yml`) rather than locally.

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
