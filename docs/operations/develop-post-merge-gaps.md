<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Develop push gaps

```{tags} contributor, operations, ci
```

## What failed

GitHub has **dropped push delivery** for consecutive `develop` merges. In
principle every push to `develop` starts every workflow that listens for it. In
practice:

| When | Signal |
| --- | --- |
| 2026-08-03 | Three consecutive develop merges got **no** push workflows at all, which left the `published-results` corpus mirror stale (see the header comment on `corpus-drift-check.yml`). |
| 2026-08-04 | Six consecutive develop merges produced **no** run of the post-merge workflow that existed then. |

The mechanism (GitHub delivery drop, concurrency edge, or API lag) is not
fully proven. What is proven is the **observable gap**: `git log
origin/develop` SHAs with no matching workflow run.

That is a silent failure mode, and every workflow that fires only on `push` to
develop shares it. The full list of those workflows, what each loses when a push
is dropped, and how to recover is in
[`develop-push-drop-inventory.md`](develop-push-drop-inventory.md).

## What changed with the six-unit CI

The post-merge workflow (`develop-post-merge.yml`), its hourly tip sweep, and
its daily gap detector (`develop-post-merge-gap-detector.yml`) were retired.
Required checks now run on the exact tree that lands: the merge queue runs the
six units on the speculative merge commit, so a dropped push on develop no
longer leaves the tip ungated. What a dropped push can still cost is confined
to the push-only workflows in the inventory. Two matter for the queue itself:

| Workflow | Loses when its push is dropped | Recovery |
| --- | --- | --- |
| `fast-lane-baseline.yml` | The fast-lane count for that commit. The PR delta guard restores it by exact base SHA and **fails closed** on a miss, so PRs cut from that commit fail `guard-fast-lane-delta` until it exists. | `gh workflow run fast-lane-baseline.yml --ref develop` |
| `docs.yml` | The protected public-site visual baseline for that commit. A PR or queue entry whose render inputs changed then fails closed at the baseline download. | `gh workflow run docs.yml --ref develop -f baseline_source_sha=<sha>` |

Check whether a commit has a baseline before blaming a PR for either failure.

## Diagnostic

Exact-SHA coverage for the last 10 develop commits, for one workflow:

```bash
bash -c '
  shas=$(git log --format=%H origin/develop -10)
  runs=$(gh run list --workflow fast-lane-baseline.yml --limit 100 --json headSha --jq .[].headSha)
  for s in $shas; do
    echo "$runs" | grep -q "$s" || { echo "missing: $s"; }
  done
'
```

A missing SHA after a real push-drop episode is expected, and stays missing
until it ages out of the window. Re-dispatch the workflow as above if a PR
needs that commit as its base.

## Retired tooling

`scripts/detect_develop_post_merge_gaps.py`, `scripts/sweep_coverage.py`, and
`scripts/post_merge_signature.py` were written for the retired workflow and
have no workflow caller now. They remain in the tree until a follow-up removes
them together with their tests.

## What we deliberately did not do

- **No extra push-adjacent spam** (`pull_request`, `workflow_run`,
  `repository_dispatch`, and so on) to force more events. That papers over the
  class without bounding exposure cleanly and burns runners on every related
  event.
- **No replacement of the push trigger.** Push stays the primary trigger for
  workflows that record state on a develop commit; recovery is dispatch.
- **No mutation jobs on schedule.** Anything that opens or closes GitHub
  objects stays push and dispatch only, so a cron run cannot change state
  without a real merge event.
