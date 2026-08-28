<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Develop post-merge push gaps

```{tags} contributor, operations, ci
```

## What failed

`Develop post-merge` (`.github/workflows/develop-post-merge.yml`) is the
safety net that re-runs lint, fast-test, explorer-tokens, and medium-test
against the actual `develop` tip after a merge. Its primary trigger is:

```yaml
on:
  push:
    branches: [develop]
```

There is no path filter. In principle every develop push should produce a
run for that exact SHA. In practice GitHub has **dropped push delivery** for
consecutive develop merges:

| When | Signal |
| --- | --- |
| 2026-08-03 | Three consecutive develop merges got **no** push workflows at all — not even develop-post-merge — which left the `published-results` corpus mirror stale (see the header comment on `corpus-drift-check.yml`). |
| 2026-08-04 | Six consecutive develop merges produced **no** develop-post-merge run for their SHAs. |

The mechanism (GitHub delivery drop vs concurrency edge vs API lag) is not
fully proven. What is proven is the **observable gap**: `git log
origin/develop` SHAs with no matching `gh run list --workflow
develop-post-merge.yml` `headSha`.

That is a silent failure mode. Push-only guards share it. Every workflow
that only fires on `push` to develop can miss the same window.

**Full inventory of develop-push workflows** (which ones already have a
schedule, which residual gaps are accepted, and recovery commands) lives in
[`develop-push-drop-inventory.md`](develop-push-drop-inventory.md). This page
stays focused on the `develop-post-merge` backstop and gap detector.

## What we do about it

Two additive pieces. Neither replaces per-push runs.

### 1. Scheduled sweep (coverage)

`develop-post-merge.yml` also runs on:

- `schedule: "17 * * * *"` (hourly, minute offset to spread load)
- `workflow_dispatch` (manual recovery)

**Schedule path is slim and gates-only:**

| Job | `push` / `workflow_dispatch` | `schedule` |
| --- | --- | --- |
| lint, fast-test, explorer-tokens | yes | yes |
| medium-test (~40 min) | yes | **no** |
| close-orphaned-prs, auto-revert-on-failure, green-run-cleanup | yes | **no** (mutation) |

Medium-test stays on the real merge path so a squash race still trips
auto-revert; the hourly sweep deliberately omits it to avoid ~24 full
medium runs/day when tip is already push-covered. Schedule also never
opens revert PRs, closes orphaned PRs, or cleans green-run issues — those
remain push/dispatch only.

Concurrency:

| Event | Concurrency group | `cancel-in-progress` |
| --- | --- | --- |
| `push` / `workflow_dispatch` | `develop-post-merge-${{ github.sha }}` | `false` (concurrent merges must not cancel each other) |
| `schedule` | `develop-post-merge-schedule` (fixed) | `true` (newer sweep supersedes an older still-running one; never shares a group with push) |

**Success criterion for the sweep:** develop **tip** is re-gated by the
slim gates within about an hour of a silent push-drop. That is the safety
property. It is **not** a claim that every intermediate dropped SHA gets
its own run, and it is **not** a claim that the exact-SHA verification
ladder stays green after an incident.

Permissions are unchanged: workflow-level `contents: read`, with the same
job-level escalations auto-revert / orphan-close already used on the
push path only.

### 2. Gap detector (instrumentation)

`.github/workflows/develop-post-merge-gap-detector.yml` runs daily
(`47 7 * * *`) and on `workflow_dispatch`. It is read-only
(`contents: read`, `actions: read`) and calls:

```bash
python3 scripts/detect_develop_post_merge_gaps.py \
  --live --branch origin/develop --commit-limit 20
```

The script compares the last N develop commits to recent
`develop-post-merge` run `headSha`s. Any commit with **no** run (any status)
is a gap: GitHub never started post-merge for that push. The job fails and
emits `::error` annotations so the class stays visible until the SHAs age
out of the lookback — it does **not** open PRs or re-run gates.

Live mode paginates the run list until it has enough **unique** headShas
(`commit_limit + margin`, default margin 10) or hits a hard row cap
(default 1000). A fixed shallow `--limit` is not safe: after many hourly
schedule runs for the same tip, the most-recent N rows can all share one
`headSha` and would otherwise hide older push-covered commits deeper in
history (self-poisoning).

A tip that was only covered by the hourly sweep (event=`schedule`) still
counts as covered for that tip SHA. Intermediate dropped SHAs remain
uncovered by design: that is the instrumentation of the push-drop class.

## Verification ladder

Exact-SHA coverage for the last 10 develop commits (diagnostic, not a
post-incident green promise):

```bash
bash -c '
  shas=$(git log --format=%H origin/develop -10)
  runs=$(gh run list --workflow develop-post-merge.yml --limit 100 --json headSha --jq .[].headSha)
  for s in $shas; do
    echo "$runs" | grep -q "$s" || exit 1
  done
'
```

How to read the result:

| Exit | Meaning |
| --- | --- |
| `0` | Every looked-up develop SHA currently has at least one post-merge run (push, schedule, or dispatch) whose `headSha` matches. Quiet periods with healthy push delivery look like this. |
| `1` | At least one recent SHA has no run. **Expected after a real push-drop episode**, and can remain non-zero until those intermediate SHAs age out of the lookback — even when tip is green via the hourly sweep. Do not treat this as "the sweep is broken." |

Preferred scripted form (paginates unique headShas; same honesty rules):

```bash
python3 scripts/detect_develop_post_merge_gaps.py --live --json
```

Offline form (no pagination; you supply both lists):

```bash
git log --format=%H origin/develop -20 > /tmp/commits.txt
gh run list --workflow develop-post-merge.yml --limit 200 --json headSha \
  --jq '.[].headSha' > /tmp/runs.txt
python3 scripts/detect_develop_post_merge_gaps.py \
  --commits-file /tmp/commits.txt --runs-file /tmp/runs.txt --json
```

## Manual recovery

If tip has no recent post-merge run and you do not want to wait for the
hourly sweep (full push-equivalent path including medium-test and mutation
jobs when tip is red/green as usual):

```bash
gh workflow run develop-post-merge.yml --ref develop
```

To re-check the gap class without waiting for the daily detector:

```bash
gh workflow run develop-post-merge-gap-detector.yml --ref develop
```

## What we deliberately did not do

- **No extra push-adjacent spam** (`pull_request`, `workflow_run`,
  `repository_dispatch`, etc.) to force more events. That papers over the
  class without bounding tip exposure cleanly and burns runners on every
  related event.
- **No replacement of the push trigger.** Push remains primary; schedule is
  additive.
- **No full medium-test on every hourly sweep.** Cost decision: slim
  schedule (lint + fast-test + explorer-tokens) bounds tip exposure without
  ~24× medium-tier runner hours/day.
- **No mutation jobs on schedule.** Auto-revert / orphan-close / green-run
  cleanup stay push + dispatch only so a sweep cannot open or close GitHub
  objects without a real merge event.
- **No new permission classes** beyond what develop-post-merge already uses
  (`actions: read` already appears on metrics / auto-revert jobs).
- **No claim that intermediate dropped SHAs are "covered" by a later tip
  sweep, or that the every-SHA ladder stays green post-incident.** Tip
  safety (≤~1h re-gate) and per-SHA instrumentation are separate signals.
