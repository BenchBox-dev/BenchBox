# CI-failure baseline (dev-loop-metrics-ci-failure-baseline-2)

Source: `dev-loop-metrics-ci-failure-baseline-2`. First real-data baseline for
the dev-loop CI-reduction workstreams (WS1-WS4), captured **before** any
reduction work lands, so later re-measures have something to compare against.

**Measured**: 2026-07-23, trailing 28 days (since 2026-06-25).
**Re-measure cadence**: every 2 weeks while WS1-WS4 are active.
**Re-measure command**:

```
uv run -- python _project/scripts/dev_loop_pr_metrics.py --days 28 --json \
  > _project/analysis/ci-failure-$(date +%F).json
```

(also runs automatically, text-mode, as an additive step of `make
dev-loop-metrics` — note that step uses the target's default
DEV_LOOP_METRICS_DAYS=30 window, vs this baseline's 28; the JSON form above
is for snapshotting a new dated baseline file like this one).

**Decision hooks**:
- WS1-WS4 effectiveness review — compare each re-measure's first-pass green
  rate, pushes-after-open, and fast-test job wall time against this baseline;
  a workstream that doesn't move these numbers didn't reduce real CI-failure
  cost, regardless of its effect on head-SHA check-run color.
- Input to `dev-loop-step-6-queue-decision-gate` — the merge-queue
  build/no-build decision should weigh the measured composition-conflict
  rate (`fast_test_lane_policy.json` touch rate) and fix-forward push rate
  here, not a guess.

## Why not head-SHA check runs (confirmed, not assumed)

Dev PRs land via squash auto-merge once the required checks are green, so a
merged PR's HEAD-SHA check runs are *definitionally* green — measuring them
tells you about the auto-merge gate, not about CI-failure cost. This was
re-confirmed live (w0) rather than assumed: 5 recent merged `develop` PRs
(#1274, #1275, #1276, #1277, #1278) were sampled via
`mcp__github__pull_request_read` (`method: get_check_runs`).

| PR | ci-required-result | all check runs at head |
|---|---|---|
| #1274 | success | all success/skipped |
| #1275 | success | all success/skipped |
| #1276 | success | all success/skipped |
| #1277 | success | all success/skipped |
| #1278 | success | `ci-required-result` success, but **`Chromium (full suite, blocking)` = failure** and `WebKit (@smoke, non-blocking)` = failure at head |

#1278 is the useful counter-example: it merged with a "blocking"-named
Playwright job **red at the merged head SHA**, because that job is not in
`ci-required-result`'s dependency set. Head-SHA check-run color conflates
"required and green" with "every job green" and would have under-*and*-over-
counted red here depending on which check you picked — exactly the
anti-pattern this baseline avoids. All 5 PRs' `ci-required-result` (the
actual gate) was green at head, confirming the squash-auto-merge policy is
in force and head-SHA-based failure measurement is a dead end, full stop.

## Method

Two data sources, kept separate below because they cover different windows:

1. **Full-population counts** — local `git log` against `origin/develop`
   inside this worktree. The clone starts shallow; it was deepened
   (`git fetch origin develop --deepen=1000`) until the oldest visible commit
   (2026-05-01) predates the 28-day window start (2026-06-25), so the count
   below is a complete population count, not a sample.
   - `git log --since="2026-06-25T00:00:00" --oneline origin/develop | wc -l`
   - `git log --since="2026-06-25T00:00:00" --oneline origin/develop -- _project/config/fast_test_lane_policy.json | wc -l`
   - `git log --since="2026-06-25T00:00:00" --format="%s" origin/develop | grep -c '^Revert '`
2. **Per-PR / per-run detail** (open-to-merge time, fix-forward pushes,
   first-pass required-lane green rate, fast-test job wall time) — GitHub
   MCP tools (`mcp__github__list_pull_requests`,
   `mcp__github__pull_request_read`, `mcp__github__actions_list`), repo
   `joeharris76/benchbox` only, paginated in batches of 10 PRs /
   30-100 runs. **This is a sample, not the full population** — see
   Limitations.

## Full-population counts (28-day window, git log, N=355)

| Metric | Value |
|---|---|
| Merged `develop` PRs (squash commits with a trailing `(#NNN)` subject) | **355** |
| `_project/config/fast_test_lane_policy.json` touches | **16** (4.5%) |
| Confirmed auto-revert-triggered revert commits (`^Revert `) merged to develop | **0** |
| Merge cadence | ~12.7 PRs/day average, uneven (0-33 commits/day; gaps on 2026-07-01, 2026-07-13 to 2026-07-15) |

Zero confirmed reverts landed in the window, but the window's **last day**
carried a live, unresolved incident: PR #1279 (`auto-revert/035c92b3d341`),
opened 2026-07-23T13:33Z reverting #1276 after develop went red
post-merge (lint job), was still open/unmerged at measurement time — so it
correctly does not count as a landed revert, but it is real evidence the
mechanism fires. Re-measure in 2 weeks should confirm whether #1279 (or its
fix-forward equivalent) landed and whether any further reverts occurred.

## Sampled per-PR / per-run metrics

Sample: the 19-21 most recently merged/active `develop` PRs and branches at
measurement time (PRs #1259, #1261-#1278 minus #1260/#1279 which didn't
merge), spanning **2026-07-22T01:01Z to 2026-07-23T14:11Z** (~37 hours) —
the tail of the 28-day window, not a stratified sample across it (see
Limitations for why).

### Open-to-merge wall time (n=19, exact PR `created_at`/`merged_at`)

| Stat | Value |
|---|---|
| Median | **1827s (30.5 min)** |
| Mean | 15857s (264 min) — heavily skewed by 3 outliers |
| P95 (of 19) | ~2151 min (~35.9h) |

Outliers, all explainable, not noise:
- **#1259** (35.9h): long-lived PR reused across a review-followup sweep,
  multiple pushes, one run explicitly `cancelled` by the workflow's
  `cancel-in-progress` concurrency group.
- **#1273** (17.5h): `findings-phase3-schema-cli` — PR body explicitly says
  "Do NOT auto-merge — coordinated production migration required"; long
  merge time is by design, not CI friction.
- **#1272** (13.9h): `chore/sync-develop-version-0.3.1` — first "Develop PR"
  run **failed**, fixed forward, merged on the second run.
- **#1262** (7.7h): `feat/tuning-starrocks-ddl-generator` — same pattern,
  first run failed, fixed forward.

### Fix-forward pushes after open (n=21 branches, proxy: count of
`pull_request`-event "Develop PR" workflow runs on the branch, minus 1)

| Stat | Value |
|---|---|
| Median | 0 |
| Mean | 0.43 |
| Branches with ≥1 extra run | 6 / 21 (28.6%) |

This is a coarse proxy (a manual re-run or a concurrency-cancelled-then-
retried push both count identically to a real fix-forward push); the script
(`dev_loop_pr_metrics.py`) instead uses the PR's own commit list
(`pulls/{n}/commits`) as the primary metric, which is more precise per-PR
but costs one extra API call per PR — a tradeoff documented in the script
itself.

### First-pass required-lane green rate (n=21 branches; first `pull_request`-
event "Develop PR" run per branch)

| Outcome | Count | Share |
|---|---|---|
| success (green on first try) | 15 | 71.4% |
| failure (fixed forward) | 3 | 14.3% |
| cancelled (superseded by a fast follow-up push, concurrency group) | 3 | 14.3% |

**First-pass green rate = 15/18 = 83.3%** (cancelled runs excluded — a
concurrency-cancel is not a CI failure, it's evidence of *rapid* fix-forward
push, which the pushes-after-open metric already captures) — or **15/21 =
71.4%** if cancellations are conservatively counted as non-green. Both
readings are reported because "cancelled" is genuinely ambiguous evidence
and re-measures should track whether the ratio of cancelled:failed:green
shifts, not just the single green-rate number.

The 3 real failures (`feat/tuning-starrocks-ddl-generator` #1262,
`chore/sync-develop-version-0.3.1` #1272,
`feat/tuning-drift-validation-bundle-routing` #1277) each independently
correspond to a PR whose own body/notes describe a fast-lane-cap or
version-drift issue caught and fixed forward — the metric and the PR
narratives agree, which is a good sanity check on the method.

### Fast-test job wall time (`test (ubuntu-latest, 3.12)`, n=8 runs)

| Stat | Value |
|---|---|
| Average | 631s (~10m31s) |
| P95 | 651s (~10m51s) |
| Range | 589s-651s |

Sampled from job timings on 8 first-attempt "Develop PR" runs (5 via
`pull_request_read get_check_runs` on PRs #1274-#1278, 3 via
`actions_list list_workflow_jobs` on PRs #1261/#1269/#1273). Tight range
(589-651s) suggests the job is CPU/IO-bound and consistent, not currently a
source of CI-time variance worth optimizing first.

## Per-PR appendix (sample, n=19)

| PR | Title | Open->Merge | First-pass | Fix-fwd pushes (proxy) |
|---|---|---|---|---|
| #1278 | Explorer receipt hash test coverage | 18min | green | 0 |
| #1277 | Route rerun drift-validation into applied.json | 1.3h | failure->fixed forward | 1 |
| #1276 | Capture native Spark session config in applied ledger | 30min | green | 0 |
| #1275 | Make DuckDB sorting + ClickHouse keys verification-eligible | 22min | green | 0 |
| #1274 | Propagate DataFrame tuning config non-interactive | 20min | green | 0 |
| #1273 | findings-domain phase 3 (schema v3 + CLI) - manual gate | 17.5h | green | 0 |
| #1272 | Sync develop version to 0.3.1 | 13.9h | failure->fixed forward | 1 |
| #1271 | findings-domain phases 0/1/2 | 1.3h | cancelled(concurrency)->green | 3 |
| #1270 | Tuning-policy generation seam | 45min | cancelled(concurrency)->green | 1 |
| #1269 | DataFrame tuning ledger parity | 35min | green | 0 |
| #1268 | Tuning introspection receipts | 30min | green | 0 |
| #1267 | Cross-surface baseline autodetect | 30min | green | 0 |
| #1266 | Promote regression reproducers into required gate | 27min | green | 0 |
| #1265 | Consolidate DataFrame CSV empty-string/null coercion | 22min | green | 0 |
| #1264 | Explorer consumes bundle hashes | 30min | green | 0 |
| #1263 | Correct capability-registry mixin honesty | 27min | green | 0 |
| #1262 | StarRocks DDL generator | 7.7h | failure->fixed forward | 1 |
| #1261 | Applied-tuning ledger + honest validation_status | 31min | green | 0 |
| #1259 | PR review follow-up sweep #1244-#1258 | 35.9h | cancelled(concurrency)->green | 2 |

("Fix-fwd pushes (proxy)" is the branch's extra `pull_request`-event run
count, as described above; #1259/#1270/#1271's `cancelled` runs are counted
here since they represent a real second push, even though the run itself
carries `cancelled` rather than `failure`.)

## What could not be computed, and why

- **Stratified sample across the full 28 days.** `actions_list
  list_workflow_runs` returns full run objects (~13KB each); a single page
  of 30 rows is ~400K characters and hit the tool's output-size limit even
  at `per_page=100` (the server appears to cap the effective page size
  regardless of the requested value). Paginating back 28 days at that rate
  would need dozens of multi-hundred-KB calls. The sample used here is
  therefore the most recent ~37h of the window (the tail), which happens to
  include an unusually dense "batch landing" burst (11+ PRs in a few hours
  on 2026-07-22/23) — likely not representative of a typical day's pace.
  **Re-measure should either sample multiple shorter windows spread across
  the 28 days, or accept the recency bias and track it explicitly.**
- **Full-population open-to-merge / first-pass-green / pushes-after-open.**
  These require per-PR or per-branch API calls; computing them for all 355
  window PRs was out of budget for this baseline. The 19-21 PR sample above
  is the practical bound described in the TODO's "paginate 10 at a time,
  keep MCP result sizes bounded" instruction.
- **True historical PR count without deepening the clone.** The worktree
  clone started shallow at exactly 57 commits (coincidentally close to a
  plausible "in-window" count, which nearly produced a wrong population
  figure — flagged here as a process note for future baselines: always
  verify `git rev-parse --is-shallow-repository` and that the oldest visible
  commit predates the window before trusting a local `git log --since`
  count).
- **pytest `--durations=20` top-20 local list.** `dev_loop_pr_metrics.py
  --collect-durations` was implemented (per the TODO's w4 instruction) but
  deliberately **not run** in this session — the fast lane is ~25k tests and
  the run would be too slow for this baseline capture. It is documented as a
  local-machine-only measure (not comparable across machines) in the
  script's own help text and module docstring.

## Reproduction

```bash
# Population counts (run from a worktree with enough depth; see Method §1)
git fetch origin develop --deepen=1000   # only if the clone is shallow
git log --since="$(date -d '28 days ago' +%F)T00:00:00" --oneline origin/develop | wc -l
git log --since="$(date -d '28 days ago' +%F)T00:00:00" --oneline origin/develop -- _project/config/fast_test_lane_policy.json | wc -l

# Per-PR sample + fast-test job timing (script; needs gh CLI or GITHUB_TOKEN)
uv run -- python _project/scripts/dev_loop_pr_metrics.py --days 28 --json
```
