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

- Develop merges: 33 squash-merges to `develop` from 2026-08-14T00:15:10Z
  through 2026-08-17T00:49:53Z (`#1721` … `#1753`). 32 interarrival gaps.
- Required-gate wall: reuse profile #1734 (2026-08-14 code refreshes
  `#1717`/`#1718`/`#1719`) plus #1751 first `ci-required-result`
  (22:54:12Z–23:13:53Z = 19.7 min).
- Shadow yield: 10 most recent `develop-refresh-shadow.yml` artifacts as
  of 2026-08-17T01:04Z.

## Interarrival

| Stat | Minutes |
|---|---:|
| min | 4.3 |
| p50 | 31.3 |
| p75 | 66.2 |
| p95 | 634.0 |
| mean | 136.1 |
| max | 1361.8 |

18.8% of gaps are under 20 min. **50% of gaps are under 31 min**, the
#1734 `medium-test` merge-unblock wall.

## Required-gate duration

| Source | Wall |
|---|---|
| #1734 `#1717` | 30.2 min required-gate; medium-test 29.7 |
| #1734 `#1718` | 31.4 min; medium-test 29.2 |
| #1734 `#1719` | 27.0 min; medium-test 26.6 |
| #1751 first `ci-required-result` | 19.7 min |

Gate duration is a material fraction of interarrival. A PR that opens
current still has about even odds of seeing another develop merge before
a 31-minute gate finishes, in this window.

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

If every one of N open develop PRs auto-refreshed on each of the 32 gaps,
that is N full required gates per merge. At 27–31 min/gate and 50% of
gaps under 31 min, the first refresh to land re-stales the rest. That is
why bulk update is rejected.

## Single recommendation

**Keep `SHADOW_ONLY`.** Do not unblock 07a (no live `shadow_eligible`
yield). Do not unblock 07b (user-owned repo; operator transfer still
required). Ship 01 for open-stale only. Revisit 07a/07b only from a later
activation item after eligible yield is non-zero and an operator chooses.
