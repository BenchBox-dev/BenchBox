# Merge-queue visual baseline: site-equivalent ancestors and a short wait

Date: 2026-09-27
Status: Decided. Amends `visual-baseline-queue-candidate-2026-09-26.md`: the
leader candidate stays, the 30-minute follower wait is replaced, and ancestor
resolution is allowed only for ancestors whose public-site inputs are
byte-identical to the base.

## Problem

After the leader candidate landed, `Public-site visual acceptance` still ejected
merge groups. From 2026-09-26 16:00 to 2026-09-27 04:00 UTC, all 12 visual
failures in `merge_group` Documentation runs stopped at
`Download exact base visual baseline` after the full 30-minute wait. For 6 of
the 7 distinct bases examined, the group ahead changed no public-site inputs,
so its build and visual jobs were skipped and it published no candidate (the
"known limit" of the previous decision). The seventh followed a leader whose
own comparison failed.

The wait also made the queue slower. It held a runner for up to 30 minutes per
waiting group, and a 45-minute visual job plus a 13-15 minute build left no
room for runner queueing inside the 60-minute merge-queue check timeout. During
runner contention, merge-group Documentation runs took 108 to 136 minutes and
groups were removed with `checks_timed_out`.

## Decision

1. The input classifier lists baseline candidates: the exact base, then its
   first-parent ancestors (at most 25) while every public-site input is
   byte-identical to the base (`git diff --quiet <ancestor> <base> -- <site
   inputs>`). The walk stops at the first ancestor that differs.
2. The lookup tries the candidates in order and returns the first trusted
   artifact, with the same producer trust rules as before, applied to the
   candidate's own SHA. The download step publishes the SHA it used, and the
   compare step checks the manifest's `source_sha` against it.
3. The merge-group wait falls from 30 to 10 minutes and the visual job timeout
   from 45 to 30 minutes.

Replaying the classifier against the failed bases from the measurement window
(`fc0572f`, `91c925f`, `d0e13f3`, `7d31a7d`) finds an unexpired trusted
baseline for every one without waiting.

## Why this is sound

The gate already relies on this premise: when a tree changes no public-site
input relative to its base, `changed=false` and no comparison is required. The
path list is the documented closure of rendered dependencies. An ancestor whose
site inputs are byte-identical to the base renders the same site, so its
capture is a capture of the base's site. An ancestor whose inputs differ is
never used, which keeps the earlier rejection of general ancestor resolution.

## Alternatives rejected

- Keep waiting longer: already measured to exceed the queue timeout and to hold
  runners.
- Make skipped leaders republish a baseline: needs a capture on every leader,
  which is the rebuild cost the skip exists to avoid.
- Make `merge_group` visual comparison advisory: drops the landed-tree guarantee.

## Review follow-ups (same day)

- Added `uv.lock` to the site-input list (results-explorer's lockfile was
  already covered): a dependency-only change re-renders the site, so it breaks
  ancestor equivalence and must require its own comparison.
- Require completed `success` runs and the producing repository for both
  producers.
- Cover all 26 candidate SHAs, cap artifact pagination, list named artifacts
  in one batch, and prefer any landed develop baseline over any speculative
  queue capture.
- The compare step now requires a well-formed baseline SHA, so a missing or
  stale download cannot compare pixels alone.
