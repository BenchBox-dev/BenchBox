# Fast-lane test-count budget

The "fast lane" is every test collected under `pytest -m fast` (excluding
`slow`/`stress`/`resource_heavy`/`live_integration`) -- the required,
sub-few-minutes suite every develop PR runs in `code-test`
(`.github/workflows/pr.yml`). `_project/scripts/timing_policy_check.py`'s
fast-lane check enforces a hard ceiling on how many tests that lane may
collect, `max_fast_tests` in `_project/config/fast_test_lane_policy.json`.

## Why this file exists (fast-lane-decouple-ceiling-contention-2)

Through mid-2026, `max_fast_tests` was a single JSON integer plus a ~6KB
single-line prose `_ceiling_note` field recording every bump. Every PR that
added a fast test had to touch that one line -- ~30 bumps between April and
July, almost always with the smallest possible headroom (a handful of
tests), because there was no convention pushing back on how tight a bump
could be. Two consequences followed directly:

- **Merge-queue contention.** Two or more PRs bumping the same JSON value
  in the same window conflict on adjacent lines, or worse, both land with
  policy content that individually looked fine but together exceeded the
  cap once composed -- this produced a develop-red incident (#1281) from
  three PRs composing over the ceiling in one merge queue, and at least two
  other episodes where PRs had to hand-compose a single bump between them
  to avoid the same failure mode.
- **No warning before the wall.** Because headroom was habitually left at
  single digits, any unrelated PR landing first could push the *next* PR
  over the ceiling with zero fast tests of its own added -- this batch
  itself had to medium-mark two tests specifically to dodge a 25545 ceiling
  with under 5 tests of headroom.

The fix is not a bigger ceiling (that just delays the same collision) -- it
is decoupling: separate the append-only bump *log* from the *check*, add a
per-PR *delta* signal that catches runaway growth before it ever reaches
the shared ceiling, and surface the need for a bump automatically instead
of relying on whoever happens to hit the wall.

## The model

**1. Quantum ceiling -- coarse backstop, everywhere, every phase.**
`max_fast_tests` in `fast_test_lane_policy.json` remains the absolute,
always-enforced limit: PR lane (`guard-timing-policy` in `pr.yml`), the
develop-post-merge safety net (`lint` job in `develop-post-merge.yml`, via
`make ci-lint`), and the release lane (`lint.yml`). This is a **backstop**,
never a delta-only check -- a fast lane growing by small increments across
many PRs still eventually needs a real ceiling, and this is it.

Bumps now follow a fixed convention (`_project/config/fast_lane_ceiling_log.md`
header has the full text): **+500 quantum**, resulting headroom **>= 250**,
one dated log entry per bump, no hand-composed multi-PR bumps. A bump this
size is deliberately generous -- it absorbs several PRs' worth of ordinary
growth before the next bump is needed, which is what actually kills the
contention (few, larger, uncontested bumps beat many, minimal, colliding
ones).

**2. Per-PR delta guard -- catches runaway growth early.** The PR lane's
`code-lint` job restores the most recent develop fast-lane count (cached by
`develop-post-merge.yml` after every push to develop) and compares this PR's
own collect count against it:

- delta > 150 fails the guard (`guard-fast-lane-delta`, `pr.yml`).
- delta > 75 warns (does not fail).
- No baseline available (cache miss -- e.g. the very first run after this
  landed, or a cache eviction) -- **fails open**: prints
  `DELTA_CHECK_SKIPPED (no develop baseline available - absolute ceiling
  still enforced)` and exits 0. This is deliberate: the absolute ceiling
  check (`guard-timing-policy`, run just before this guard in the same
  job) is the enforced backstop in that case, and a hard failure on a
  missing baseline would make the delta guard a single point of failure for
  every PR whenever the cache happens to be cold.

**3. Nightly ratchet signal -- surfaces the need for a bump before the next
PR collides with it.** `_project/scripts/fast_lane_ratchet_check.py` runs
nightly (`fast-lane-ratchet-check` job, `nightly.yml`), collects the fast
lane fresh, and -- if headroom drops below the same 100-test warning
threshold `timing_policy_check.py`'s own `FAST_LANE_WARNING` uses --
files/updates ONE marker-tagged tracking issue ("Fast-lane ceiling needs a
quantum bump") naming the current numbers and the exact edit to make. It
never pushes a branch or opens a PR itself: `GITHUB_TOKEN`-authored PRs get
no required checks (the same constraint `green_unmerged_sweep.py`'s
docstring documents for its own stranded-PR sweep), so a ceiling bump stays
a deliberate human/agent-authored PR -- this signal only means nobody has
to notice the ceiling is close by accident.

**4. Union-merge log.** `_project/config/fast_lane_ceiling_log.md` replaced
the old `_ceiling_note` JSON field. It is append-only, and
`.gitattributes` marks it `merge=union` -- two branches that each append a
dated entry compose cleanly instead of conflicting on adjacent lines, which
was the proximate cause of every hand-composed multi-PR bump under the old
scheme. The JSON policy file now only carries a short `_ceiling_log`
pointer string.

## What to do when each guard fires

- **`FAST_LANE_WARNING` (advisory, `timing_policy_check.py`, any lane
  that runs it):** headroom is below 100. Not a failure by itself, but the
  next test-adding PR may hit the ceiling. Bump `max_fast_tests` by +500
  (or the smallest multiple of 500 that restores >= 250 headroom -- see
  `suggested_next_ceiling` in `fast_lane_ratchet_check.py` for the exact
  rule) and add a dated entry to `fast_lane_ceiling_log.md`.
- **`FAST_LANE_VIOLATION: fast lane count N exceeds limit M`
  (`guard-timing-policy`, blocking):** the absolute ceiling backstop
  tripped. Bump per the convention above; this is the hard stop, not a
  suggestion.
- **`FAST_LANE_DELTA_WARNING` (`guard-fast-lane-delta`, non-blocking):**
  this PR alone adds more than 75 fast tests over develop's current
  baseline. Consider whether the new coverage needs sub-second fast-lane
  execution or can be marked `medium`
  (`pytestmark = [pytest.mark.unit, pytest.mark.medium]`).
- **`FAST_LANE_DELTA_VIOLATION` (`guard-fast-lane-delta`, blocking):** this
  PR alone adds more than 150 fast tests over develop's baseline. Mark new
  tests medium or split the change across PRs. A genuinely warranted increase
  is accepted only when the same PR bumps the absolute ceiling by the
  prescribed +500 quantum and adds a dated justification entry; the delta
  guard validates that convention before allowing the bump.
- **`DELTA_CHECK_SKIPPED (no develop baseline available - absolute ceiling
  still enforced)` (`guard-fast-lane-delta`, exits 0):** no cached develop
  count was found (cold cache, first run after this feature landed, or an
  eviction). Not an error -- `guard-timing-policy`'s absolute ceiling is
  still enforcing normally. No action needed.
- **Nightly issue "Fast-lane ceiling needs a quantum bump":** open a normal
  PR making the exact edit the issue body names (ceiling bump +
  `fast_lane_ceiling_log.md` entry). The issue self-clears (patched once,
  not deleted) once the bump lands and headroom recovers.

## Future: w6 -- a wall-clock budget instead of a test-count ceiling

A test *count* ceiling is a proxy for what actually matters: how long the
required PR lane takes to run. A pure wall-clock budget (fail the PR lane
if it takes longer than N minutes, independent of how many tests that is)
would be a more direct signal and would stop rewarding/punishing PRs based
on test *count* when what's really being protected is developer wait time.

This is a deliberate **decision gate for later**, not implemented here:
`w6` in `fast-lane-decouple-ceiling-contention-2`'s scope says explicitly
not to build it yet. The right threshold (and whether count-based and
wall-clock budgets should coexist, e.g. count as the cheap pre-flight
signal and wall-clock as the final gate) needs real data first -- the
nightly ratchet signal above starts accumulating exactly that data (each
fired/cleared cycle is a headroom-vs-time data point). Revisit after
roughly 4 weeks of that signal running, per the TODO's guidance.

## medium-test wall-clock budget (distinct from w6 above)

Not to be confused with w6: that gate is about *replacing* the fast lane's
count ceiling. This is the `medium-test` job's `timeout-minutes` in
`.github/workflows/pr.yml` -- a hard cancel, not a policy check.

Sizing rule: **observed p95 + >=30% headroom**, rounded up. The timeout is
the only backstop against a genuinely hung medium tier, so it is not set to
a large "never think about it again" value -- that converts a hang into an
hour-long queue stall.

**2026-07-25 resize, 30 -> 40 min.** Last 20 `pr.yml` runs: min 20.2 /
median 27.4 / p95 29.9 min, with 8 of 19 successful runs within 48s of the
old 30-minute cap. PR #1306 was cancelled twice at 30m16s having reached
95% of the suite; it added three monkeypatched tests worth ~2s, so it was
the straw, not the cause. `29.9 * 1.3 = 38.9 -> 40`.

**Read the old numbers as a floor, not a distribution.** A cancelled job
never reports a true wall time, so runs that would have exceeded the cap
are absent from the successful sample entirely. The observed p95 is
censored by the timeout itself: it looks healthy right up to the moment the
lane starts cancelling.

**Review hook.** `make dev-loop-metrics` reports `medium-test job seconds
avg/p95` beside the fast-test figures and prints
`MEDIUM_TEST_BUDGET_WARNING` once p95 reaches 75% of the timeout
(30 min against the current 40). That threshold is deliberately the point
at which the *previous* cap began cancelling, so the next regression of
this shape is flagged with ~10 minutes still in hand. On a warning: resize
per the rule above, or split the tier. `MEDIUM_TEST_TIMEOUT_MINUTES` in
`_project/scripts/dev_loop_pr_metrics.py` must be updated with the workflow
so the metric and the budget it measures cannot drift apart.
