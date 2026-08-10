# Dev-loop measurement — REASSESS

Window: 2026-07-11 through 2026-08-10 (rolling diagnostic window; not accepted as a causal measurement window).

Evidence source: `make dev-loop-metrics DEV_LOOP_METRICS_DAYS=30 DEV_LOOP_METRICS_LIMIT=500`, raw `metrics` artifacts downloaded to `/tmp/dev-loop-metrics-raw-20260810.6JMgZA`, and cross-run recovery pairing against `develop-post-merge.yml` runs. Coverage was 402 artifacts for 403 runs (99.75%), across 28 active merge days.

### P95 PR open-to-merged

P50 was 1,822 seconds (30.4 minutes) and P95 was 81,245 seconds (22.6 hours). Daily P95 exceeded one hour on 21 of 28 active days (75%), which meets the sustained trigger, but the metric includes review/draft dwell time as well as integration wait.

### Post-merge red rate

There were 33 red artifacts out of 402 (8.21% aggregate). Only 5 of 28 active days exceeded 5% (17.9%), so the prescribed sustained trigger did not fire.

### Time-to-recover red develop

All 33 red events paired with a later green develop run. Recovery P95 was 39,496 seconds (11.0 hours), with a maximum of 68,953 seconds; this exceeds the 30-minute trigger.

### Cross-PR conflict repairs

No artifact reported `conflict_on_merge=true`; observed count was zero.

### Orphaned failed PRs

No artifact reported `orphaned_failed_pr=true`, and no qualifying orphan pattern was found in the same-window PR audit.

### Runner minutes

The window consumed 15,753.48 runner minutes. This is a budget signal only and does not independently select a queue path.

### Causal-validity audit

The TODO required Steps 1–4 and Step 3a surfaces to remain frozen during the measurement. The diagnostic interval contains changes to protected CI, Make, and test surfaces, including medium-test lane changes, post-merge workflow changes, auto-merge changes, and agent-instruction/CI guard changes. Therefore the interval cannot establish whether queue infrastructure caused the observed tail latency. Treating the rolling sample as a BUILD/DO NOT BUILD decision would violate the item's own preservation and anti-pattern rules.

Recommendation: REASSESS

Do not build or re-enable Step 6 from this sample. Start a new full 30-calendar-day window after an explicit freeze of the protected surfaces, or amend the measurement contract in a separate decision. Step 6 remains dropped in the live tracker pending that future measurement/replan.
