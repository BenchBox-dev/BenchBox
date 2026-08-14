# Decision: whole-event CI latency profile for strict-base refresh

Date: 2026-08-14
Status: Measurement for the TODO 06 activation gate. This record does not
skip jobs, change required contexts, or remove tests.
Related: `_project/decisions/strict-base-refresh-policy-2026-08-14.md`;
`_project/scripts/dev_loop_pr_metrics.py` (`event_fanout_v1`).

## Metrics

| Clock | What it measures | Not |
|---|---|---|
| **required-gate** | First required-check start → last latest-success of `ci-required-result`, `Results Explorer browser gate`, and `ruleset-drift` | Documentation or advisory jobs |
| **merge-unblock** | Same as required-gate under current strict checks | Auto-merge arm time |
| **queue-delay** | Required-gate end → squash `merged_at` | GitHub merge-queue wait (none today) |
| **all-workflow** | First synchronize workflow start → last completed sibling on that head SHA | Required-only path |
| **runner-minute** | Successful completed job minutes, plus a separate cancelled bucket | Incomplete jobs as if they finished |
| **setup / execution** | Job steps whose names start with checkout/setup/install versus the rest | A second metrics stack |

Cancelled and in-progress observations never enter completed-run minutes.
Reruns use the latest same-named check. A renamed required context is a
missing check. Public standard-runner dollar cost is **0**.

Existing `PrMetrics` / `summarize` keys are unchanged. Fan-out is the
versioned `event_fanout_v1` object.

## Live cohort (activation-day code refreshes)

Same-head measurements from 2026-08-14, already used in the policy review:

| PR refresh | required-gate / merge-unblock (Develop PR wall) | all-workflow runner-min | Documentation runner-min | medium-test | correctness | fast test | lint |
|---|---:|---:|---:|---:|---:|---:|---:|
| #1717 `c12118ac5e` | 30.2 min | 83.7 | 11.6 | 29.7 | 18.4 | 12.1 | 5.3 |
| #1718 `c683c184c0` | 31.4 min | 80.4 | 10.0 | 29.2 | 15.9 | 12.3 | 5.5 |
| #1719 `d80e08e03b` | 27.0 min | 83.2 | 13.8 | 26.6 | 18.5 | 12.2 | 5.5 |

Required-gate is the `medium-test` critical path. Documentation adds 10–14
runner-minutes and about 6.5 wall minutes but does **not** sit on
merge-unblock. Browser gate and `ruleset-drift` finish in seconds when
Explorer is quiet.

## Critical path

1. **merge-unblock:** `medium-test` (26–30 min).
2. Parallel, not on the wall once medium is running: `correctness-gate`
   (16–18), `code-test` (12), `lint` (5.3–5.5).
3. **all-workflow extra:** Documentation `build` + `linkcheck` (6–7 wall).

A 5-minute refresh p50 that only subtracts `pr.yml` jobs is not an
all-event target.

## Safe full-CI follow-ups (not authorized here)

Prefer work that keeps coverage:

- Cache and setup reuse on `lint` / `code-test` (setup is a small slice of
  the 5–12 minute jobs; it is not the merge-unblock problem).
- Deterministic medium-test sharding or runtime cuts that preserve the
  same cases.
- Documentation path-filter or incremental Sphinx only if a later item
  proves docs drift cannot sneak onto develop through a code refresh.

Do **not** delete or silently demote medium or correctness from the
required lane in a profiling change. Those are separate TODOs.

## What TODO 06 should take

- Lead with required-gate / merge-unblock, not runner-minutes.
- A reduced refresh that keeps the full `lint` job and skips medium /
  correctness / fast tests is the only custom option that attacks the
  observed 27–31 minute wall.
- Native merge queue would still pay one full integration build per group;
  it does not make medium-test cheap.
- Shadow-only leaves the 30-minute refresh tax in place.
