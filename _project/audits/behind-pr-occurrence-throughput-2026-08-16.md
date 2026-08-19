---
date: 2026-08-16
develop_sha: 360cd918756597b298af3f0d18434f35387b0fe1
measured_at_sha: 360cd918756597b298af3f0d18434f35387b0fe1
checked_sha: 360cd918756597b298af3f0d18434f35387b0fe1
---

# Behind-PR throughput measurement

Evidence for `behind-pr-occurrence-02-throughput-measurement`. This audit
does not skip required checks and does not unblock
`strict-base-refresh-07a-reduced-fast-refresh-rollout` or
`strict-base-refresh-07b-native-merge-queue-migration`.

Related: `_project/decisions/behind-pr-occurrence-2026-08-16.md`;
`_project/decisions/strict-base-refresh-ci-profile-2026-08-14.md`;
`_project/decisions/strict-base-refresh-activation-2026-08-14.md`.

Observed tip: `origin/develop` `360cd918756597b298af3f0d18434f35387b0fe1`
(#1753).

## Sample

- Develop merges: 34 squash-merges to `develop` from 2026-08-14T00:15:09Z
  through 2026-08-17T00:49:53Z (`#1721` … `#1753`). 33 interarrival gaps.
  Counted with `git log --first-parent`; an earlier revision of this audit
  reported 33 merges / 32 gaps because it omitted `#1711`, which landed at
  2026-08-14T00:36:32Z between `#1721` and `#1719`. No exclusion criterion
  justified dropping it, so the table below is recomputed over every merge.
- Required-gate wall: reuse profile #1734 (2026-08-14 code refreshes
  `#1717`/`#1718`/`#1719`) plus #1751 first `ci-required-result`
  (22:54:12Z–23:13:53Z = 19.7 min).
- Shadow yield: 10 most recent `develop-refresh-shadow.yml` artifacts as
  of 2026-08-17T01:04Z.

## Interarrival

| Stat | Minutes |
|---|---:|
| min | 4.3 |
| p50 | 27.5 |
| p75 | 44.9 |
| p95 | 802.5 |
| mean | 132.0 |
| max | 1361.8 |

Percentiles use the repo-wide nearest-rank definition (`percentile_ms`).

18.2% of gaps are under 20 min. **51.5% of gaps are under 31 min**, the
#1734 `medium-test` merge-unblock wall.

## Required-gate duration

| Source | Wall |
|---|---|
| #1734 `#1717` | 30.2 min required-gate; medium-test 29.7 |
| #1734 `#1718` | 31.4 min; medium-test 29.2 |
| #1734 `#1719` | 27.0 min; medium-test 26.6 |
| #1751 first `ci-required-result` | 19.7 min |

Gate duration is a material fraction of interarrival. For a PR that opens
*immediately after a merge*, this window puts the odds of another develop
merge landing inside a 31-minute gate at about even.

That bound does not generalize to a PR opening at an arbitrary moment. The
share of *gaps* shorter than the gate is not the probability an arbitrary
PR is overtaken: that depends on where within a gap PRs actually open, and
arbitrary-time sampling lands in long gaps more often than their count
suggests (length-biased sampling). This sample records merge times only,
with no PR-open distribution, so the stronger claim is not supported here -
measuring current PR open times would be needed to make it.

Open-time currency (`behind-pr-occurrence-01-pr-open-currency`) removes
the open-stale residual. It does not remove this in-flight residual.

## shadow_eligible yield

Ten newest shadow artifacts, all `full_required`, **zero** `shadow_eligible`:

| Run | PR | event_action | reasons | required_contexts |
|---|---:|---|---|---|
| 31983854498 | 1755 | opened | missing_event_sha | empty |
| 31983530274 | 1754 | opened | missing_event_sha | empty |
| 31983096008 | 1753 | opened | missing_event_sha | empty |
| 31982510062 | 1751 | synchronize | self_change | 3 bound |
| 31981456945 | 1752 | opened | missing_event_sha | empty |
| 31977629013 | 1750 | synchronize | prior_check_unbound | 3 bound |
| 31977618058 | 1751 | opened | missing_event_sha | empty |
| 31977435001 | 1750 | synchronize | not_exactly_two_parents | empty |
| 31975266896 | 1749 | synchronize | not_exactly_two_parents | empty |
| 31974891703 | 1750 | opened | missing_event_sha | empty |

Opened events still fail closed on `missing_event_sha` with empty
`required_contexts` (token cannot read ruleset 15611785), matching
activation-day #1739. Synchronize events that bind contexts still fail
closed (`self_change`, `prior_check_unbound`). Exact two-parent refresh
heads are not yet appearing in this live sample (`not_exactly_two_parents`).

Fail-closed behavior is correct. Live eligible yield is 0, so 07a is not
earned.

## Refresh-storm cost

If every one of N open develop PRs auto-refreshed on each of the 33 gaps,
that is N full required gates per merge. At 27–31 min/gate and 50% of
gaps under 31 min, the first refresh to land re-stales the rest. That is
why bulk update is rejected.

## Single recommendation

**Keep `SHADOW_ONLY`.** Do not unblock 07a (no live `shadow_eligible`
yield). Do not unblock 07b (user-owned repo; operator transfer still
required). Ship 01 for open-stale only. Revisit 07a/07b only from a later
activation item after eligible yield is non-zero and an operator chooses.
