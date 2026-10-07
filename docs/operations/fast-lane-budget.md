# Fast-lane guards

The "fast lane" is every test collected under `pytest -m fast` (excluding
`slow`/`stress`/`resource_heavy`/`live_integration`) -- the required,
sub-few-minutes suite every develop PR runs in `code-test`
(`.github/workflows/ci.yml`).

## The test-count ceiling is retired

The lane used to have a hard limit on how many tests it could collect
(`max_fast_tests`), a per-PR growth limit, a nightly issue that asked for
limit bumps, and a log of those bumps. In practice the limit never rejected a
bad change: it failed whenever the count crossed a pinned number, and the only
response was a pull request that raised the number. That cost a bump PR, merge
conflicts between concurrent bumps, and a baseline workflow to feed the growth
limit, without protecting the lane's runtime. The `code-test` job now has a
`timeout-minutes` cap, which bounds the cost directly. The count limit, its
growth guard, its baseline workflow, the nightly issue and the bump log were
removed.

## Marker and path guards

`_project/scripts/fast_lane_ceiling_check.py` keeps the guards that stop the
wrong kind of test from entering the lane. It reads
`_project/config/fast_test_lane_policy.json`:

- `forbidden_marker_expressions`: for each expression, the script collects
  `pytest -m "fast and <expression>"`. A non-empty selection is a
  `FAST_LANE_VIOLATION` (currently `resource_heavy`, `stress` and
  `live_integration`).
- `forbidden_path_substrings`: any fast-lane test whose node ID contains one
  of these substrings is a `FAST_LANE_VIOLATION`. The list is empty today.
- `enabled`: set to `false` to switch the guards off.

The guards run as `guard-fast-lane-markers` in the `code-lint` job of
`ci.yml`, in `lint.yml` for release branches, in `make ci-lint`, and in the
`timing-policy-fast-lane` pre-push hook, all with `--strict`. If pytest
cannot collect, the script reports `FAST_LANE_ENVIRONMENT_ERROR` instead of a
violation, because nothing is known to be wrong with the lane; run it from the
project environment (`uv run -- python
_project/scripts/fast_lane_ceiling_check.py --strict`). To fix a violation,
remove the forbidden marker from the test or move the test out of the fast
tier.

## Wall-clock decision record (2026-08-15)

The four-week decision sample is now available. The read-only metrics
collection covered **491 merged develop PRs** from 2026-07-18 through
2026-08-14. It contained **395 completed-success fast-test job durations**:

| Measure | Fast-test job wall time |
| --- | ---: |
| Median | 675 seconds (11.25 minutes) |
| P95 | 752 seconds (12.53 minutes) |
| P99 | 778 seconds (12.97 minutes) |
| Maximum observed successful job | 797 seconds (13.28 minutes) |

The remaining 96 PRs are censored or absent observations: failed, cancelled,
missing, or otherwise non-successful jobs do not expose a completed duration in
this dataset. They are not evidence that the lane stayed below any budget.

**Decision (superseded).** This record originally kept the count regime and
declined a wall-clock failure for the fast lane. The count limit has since been
retired (see above). The table remains as a measurement of the lane's runtime.

## medium-test wall-clock budget

This is the `medium-test` job's `timeout-minutes` in
`.github/workflows/ci.yml` -- a hard cancel, not a policy check.

Sizing rule: **observed p95 + >=30% headroom**, rounded up. The timeout is
the only backstop against a genuinely hung medium tier, so it is not set to
a large "never think about it again" value -- that converts a hang into an
hour-long queue stall.

**2026-07-25 resize, 30 -> 40 min.** Last 20 runs of the former `pr.yml`: min 20.2 /
median 27.4 / p95 29.9 min, with 8 of 19 successful runs within 48s of the
old 30-minute cap. PR #1306 was cancelled twice at 30m16s having reached
95% of the suite; it added three monkeypatched tests worth ~2s, so it was
the straw, not the cause. `29.9 * 1.3 = 38.9 -> 40`.

**2026-10-03 resize, 40 -> 25 min, with four shards.** The medium tier is
now split across four runners instead of two, so each shard does half the
work it did. Hosted four-shard runs finished their shards in about 4 to 9
minutes, which leaves the 25-minute timeout well above the sizing rule's
headroom while still backstopping a hang. The earlier 30 -> 40 figures above
are the history of the two-shard tier.

**Read the old numbers as a floor, not a distribution.** A cancelled job
never reports a true wall time, so runs that would have exceeded the cap
are absent from the successful sample entirely. The observed p95 is
censored by the timeout itself: it looks healthy right up to the moment the
lane starts cancelling.

**Review hook.** `make dev-loop-metrics` reports `medium-test job seconds
avg/p95` beside the fast-test figures and prints
`MEDIUM_TEST_BUDGET_WARNING` once p95 reaches 75% of the timeout
(18.75 min against the current 25). That threshold is deliberately the point
at which the *previous* cap began cancelling, so the next regression of
this shape is flagged with ~10 minutes still in hand. On a warning: resize
per the rule above, or split the tier. `MEDIUM_TEST_TIMEOUT_MINUTES` in
`_project/scripts/dev_loop_pr_metrics.py` must be updated with the workflow
so the metric and the budget it measures cannot drift apart.

## Linux queue partitions

The medium tier collects its complete marker-selected test set once at the
checked commit, then splits sorted node IDs across four standard Linux runners.
Each shard preserves the medium timeout and worker limits. Pytest records its
actual collection and execution; the core result rejects missing, duplicate,
deselected, failed, or stale evidence before accepting the combined set.
`make test-medium` remains the full local suite.

The correctness tier also uses two Linux runners. Every existing Make command
belongs to exactly one partition, including the value, digest, query-set, and
no-skip checks. Raw bundled dbgen framing remains a required pre-merge check on
macOS and Windows. It also runs in the nightly Python 3.12 cells on Linux,
macOS, and Windows, alongside the installed-wheel generator smoke.

At maximum packaging coverage, the heavy payload uses twelve standard Linux
runners, including the shared collector. This follows the approved sharding
allowance in [the development-loop ADR](../development/adr/adr-dev-loop-v2.md).
Classifier, aggregate, fast-tier, and other merge-unit jobs are counted
separately. Hosted shard timings must establish the queue wall-time budget;
equal node counts alone do not prove balanced duration.

## Required-gate versus whole-event fan-out

Merge-unblock latency is the last **required** context (`core`, `explorer`,
`results-data`, `docs`, `landing`, `tooling`).
The remaining integration samples and other synchronize jobs
are all-workflow fan-out: they consume runner-minutes and can extend wall time
after the PR is already mergeable.
`dev_loop_pr_metrics.py --event-fanout` emits the versioned
`event_fanout_v1` section that keeps those clocks separate. Public
standard-runner dollar cost is reported as zero. See
`_project/decisions/strict-base-refresh-ci-profile-2026-08-14.md`.
