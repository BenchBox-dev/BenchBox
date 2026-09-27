# Merge-queue visual baseline: leader candidate plus bounded follower wait

Date: 2026-09-26
Status: Decided. Supersedes the "re-queue-after-leader" decision in
`visual-baseline-queue-follower-policy-2026-09-25.md`. The ancestor-resolution
rejection in that record still stands.

## Problem

`Public-site visual acceptance` compares a merge group's rendered site against
a baseline captured from exactly `merge_group.base_sha`. Only `develop` pushes
and recovery dispatches published baselines. A queue follower's base is the
head of the group ahead of it, which is not a develop commit while the follower
runs, so the download step failed closed within about 12 seconds and the queue
ejected the whole group.

Measured over `merge_group` Documentation runs from 2026-09-24 to
2026-09-26 00:26 UTC:

- 148 runs: 31 passed, 112 failed, 5 in progress.
- 109 of the 112 failures were at `Download exact base visual baseline`. Only
  one failure was a real visual difference.
- Those 109 failures covered 99 distinct bases. 85 never reached develop,
  because the group ahead failed or was rebuilt. 25 later landed.
- For bases that landed, the develop baseline appeared 0 to 52 minutes after
  the follower had already failed (median about 27 minutes).

So a longer retry alone would help only about a quarter of followers, and some
of those would still exceed the 60-minute queue check timeout.

## Decision

1. A `merge_group` visual job whose exact-base comparison passed uploads its
   capture as `public-site-visual-baseline-<merge_group.head_sha>` (7-day
   retention). The upload uses default `success()` gating, so a failed or
   skipped comparison publishes nothing.
2. The download script trusts that artifact only when the producing run is a
   `merge_group` run of `.github/workflows/docs.yml`, on a
   `gh-readonly-queue/develop/*` branch, in this repository, with `head_sha`
   equal to the requested base. A protected develop artifact wins when both
   exist. Artifact names alone stay untrusted.
3. The visual job captures its own tree first, then waits for the exact-base
   artifact: up to 30 minutes for `merge_group`, the existing short retry for
   `pull_request`. Polling slows to once a minute after the short retry.
   Timeout still fails closed with the existing recovery message. The job
   timeout rises from 25 to 45 minutes so build plus this job fit inside the
   queue's 60-minute check timeout.

## Which tree is certified

A follower's merged tree is F and its base is H, the head of the group ahead.
The gate certifies that F's capture matches the capture of exactly H, or that
the differences carry exact-SHA approval. This is the same claim it made before.

It is sound because:

- F can merge only on top of H. With squash, all-green grouping, the queue
  merges the group ahead as exactly H before F. If that group fails, the queue
  rebuilds F on a new base and discards the old run, so a certificate against
  an H that never lands never authorizes a merge.
- The candidate is captured by the same workflow and capture profile from the
  same tree H that a later develop push would build. Only GitHub's merge queue
  can create `gh-readonly-queue/develop/*` refs, and it builds them only from
  PRs that already satisfy the develop ruleset. Pull request runs cannot
  produce a trusted candidate even if they upload the same artifact name.

Ancestor resolution stays rejected. It compares F against a develop ancestor
that F does not land on. The candidate is the capture of F's exact base, not a
substitute for it.

## Known limits

- If the group ahead changed no public-site inputs, its visual job is skipped
  and publishes no candidate. The follower then waits for the develop push
  baseline, which usually arrives about 18 minutes after the leader merges, and
  fails closed if that takes longer than the wait. The documented recovery
  (dispatch with `baseline_source_sha`, then re-queue) still applies.
- A waiting follower holds a runner for up to 30 minutes. That is cheaper than
  the previous requeue cycle, which cost 60 to 90 minutes of grouped CI and
  ejected up to five PRs.

## Alternatives rejected

- Wait only, without a leader candidate: depends on the leader merging and a
  full develop Documentation run finishing. Measured gaps would still hit the
  queue timeout. It remains the behavior when no candidate exists.
- Ancestor plus structural diff, or incremental delta certification: both need
  new comparison logic and a new soundness argument. The exact-base candidate
  needs neither.
- Scheduled baseline publication: a speculative queue head does not exist
  until the group forms, so a schedule cannot cover it.
- Advisory `merge_group` comparison: drops the guarantee that the landed tree
  was compared against its exact base.
- Narrowing the site-input path list: independent of this problem. Each
  removal needs its own rendered-dependency argument.
