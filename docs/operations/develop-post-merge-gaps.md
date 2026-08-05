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

## What we do about it

Two additive pieces. Neither replaces per-push runs.

### 1. Scheduled sweep (coverage)

`develop-post-merge.yml` also runs on:

- `schedule: "17 * * * *"` (hourly, minute offset to spread load)
- `workflow_dispatch` (manual recovery)

On schedule it checks out the current `develop` tip and runs the **same**
gate jobs. Concurrency is split deliberately:

| Event | Concurrency group | Why |
| --- | --- | --- |
| `push` / `workflow_dispatch` | `develop-post-merge-${{ github.sha }}` | Concurrent merges must not cancel each other. |
| `schedule` | `develop-post-merge-schedule` (fixed) | A sweep must not cancel a push run for the same tip, and successive sweeps serialize. |

`cancel-in-progress` stays `false` in both cases.

The sweep covers **tip only**. Intermediate SHAs whose push events were
dropped still will not show a per-SHA run; they age out of lookback windows.
Safety property restored: develop tip is re-gated within about an hour even
when push delivery fails.

Permissions are unchanged: workflow-level `contents: read`, with the same
job-level escalations auto-revert / orphan-close already used.

### 2. Gap detector (instrumentation)

`.github/workflows/develop-post-merge-gap-detector.yml` runs daily
(`47 7 * * *`) and on `workflow_dispatch`. It is read-only
(`contents: read`, `actions: read`) and calls:

```bash
python3 scripts/detect_develop_post_merge_gaps.py \
  --live --branch origin/develop --commit-limit 20 --run-limit 100
```

The script compares the last N develop commits to recent
`develop-post-merge` run `headSha`s. Any commit with **no** run (any status)
is a gap: GitHub never started post-merge for that push. The job fails and
emits `::error` annotations so the class stays visible until the SHAs age
out of the lookback — it does **not** open PRs or re-run gates.

A tip that was only covered by the hourly sweep (event=`schedule`) still
counts as covered for that tip SHA. Intermediate dropped SHAs remain
uncovered by design: that is the instrumentation of the push-drop class.

## Verification ladder

Exact-SHA coverage for the last 10 develop commits:

```bash
bash -c '
  shas=$(git log --format=%H origin/develop -10)
  runs=$(gh run list --workflow develop-post-merge.yml --limit 60 --json headSha --jq .[].headSha)
  for s in $shas; do
    echo "$runs" | grep -q "$s" || exit 1
  done
'
```

- Exit `0`: every recent develop push has a post-merge run for its exact SHA
  (or a schedule/dispatch run was recorded against that SHA as tip).
- Exit `1`: at least one recent SHA has no run. That is the gap class. After
  a drop episode this can stay non-zero until those SHAs fall out of the
  `-10` window even if tip is currently green via the sweep.

Offline / scripted form of the same check:

```bash
git log --format=%H origin/develop -20 > /tmp/commits.txt
gh run list --workflow develop-post-merge.yml --limit 100 --json headSha \
  --jq '.[].headSha' > /tmp/runs.txt
python3 scripts/detect_develop_post_merge_gaps.py \
  --commits-file /tmp/commits.txt --runs-file /tmp/runs.txt --json
```

Live form used by CI:

```bash
python3 scripts/detect_develop_post_merge_gaps.py --live --json
```

## Manual recovery

If tip has no recent post-merge run and you do not want to wait for the
hourly sweep:

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
- **No new permission classes** beyond what develop-post-merge already uses
  (`actions: read` already appears on metrics / auto-revert jobs).
- **No claim that intermediate dropped SHAs are "covered" by a later tip
  sweep.** Tip safety and per-SHA instrumentation are separate signals.
