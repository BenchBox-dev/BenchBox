---
date: 2026-08-14
develop_sha: c72ee4efd5a73ed86e07bef3731c657067f330eb
measured_at_sha: c72ee4efd5a73ed86e07bef3731c657067f330eb
checked_sha: c72ee4efd5a73ed86e07bef3731c657067f330eb
---

# Strict-base refresh replay and negative controls

This report is evidence for
`strict-base-refresh-03-historical-replay-and-negative-controls`.
It does not authorize skip behavior. Activation remains
`strict-base-refresh-06-activation-decision-and-selected-path-handoff`.

Observed tip: `origin/develop` `c72ee4efd5a73ed86e07bef3731c657067f330eb`
(#1738, shadow workflows on `develop`).

## Window and method

- Window: merged `develop` PRs since 2026-08-13 (strict current-base lock, #1708).
- Refresh-like event: a PR commit with exactly two parents.
- Replay: `scripts/pr_refresh_replay.py` over normalized fixtures. No hosted
  workflow was rerun, cancelled, or altered.
- Required-gate and all-workflow measures are reported separately.
- Identity artifacts did not exist before #1738, so live historical requests
  fail closed. That fallback stays in the denominator.

## Inventory

27 merged PRs in the window. 6 PRs contained 10 two-parent commits.

Every sampled synchronize fanned out at least: Auto-merge revocation,
Develop PR, Documentation, Orphaned Commit Detector, PR base guard, and
Results Explorer browser tests. `Develop ruleset drift` appears after #1722
and is a required context.

Required contexts across the window: `ci-required-result`,
`Results Explorer browser gate`, and later `ruleset-drift`.

| PR | Two-parent commits | Required umbrella |
|---|---|---|
| 1732 | 4 | 3 success; 1 cancelled `medium-test` / failed umbrella |
| 1721 | 1 | success |
| 1719 | 1 | success |
| 1712 | 1 | cancelled `test` and `medium-test` / failed umbrella |
| 1711 | 1 | success; lint/test/medium skipped (docs) |
| 1708 | 2 | 1 cancelled `medium-test`; 1 success |

## Replay result

Normalized fixtures under `tests/fixtures/ci/pr-refresh-replay/` replay
through the classifier. The eligible fixture is `shadow_eligible`. Synthetic control
and negative fixtures are `full_required`.

| Class | Decision | Full-only failure? |
|---|---|---|
| Eligible exact refresh | `shadow_eligible` | no |
| Synthetic cancelled medium control (no identity artifacts) | `full_required` (`prior_check_unbound`) | no |
| Fork, chained refresh, self-change, merge-driver, semantic schema, head-drift race, malformed | `full_required` | no |

`full-only` means the classifier would have waived long lanes while those
lanes actually failed on the recorded full run. The fixture set holds **zero**
recorded historical observations (the cancelled-medium fixture is a synthetic
control carrying the eligible template's payload); populating recorded GitHub
payloads is needed before citing historical full-only rates.

Hit rate on the fixture set is not an activation number. Discarding
fallback reasons from the denominator would make a classifier that always
returns full look useful. Every fallback reason above stays counted.

## Latency and runner-minute split

`pr.yml` required-gate time is not whole-event cost. A synchronize also
starts Documentation, browser tests, ruleset-drift, PR base guard,
orphaned-commit detection, and auto-merge revocation.

- Required-gate: the merge-unblock wall is still `medium-test` on code PRs
  (about 26–31 minutes on recent #1732 / #1734 / #1738 refreshes).
- All-workflow: the same event also spends Documentation and other
  non-required runner-minutes. Those minutes are not saved by skipping
  `medium-test` alone.
- Cancelled refreshes waste runner-minutes without producing a certified
  tree. They are not skip-safety evidence.

## Confidence and limitation

This sample is small (10 refresh-like commits, one week). No sample-size
threshold alone authorizes activation. Shadow parity after #1738 will
observe live classify decisions; it still does not prove skipped-lane
safety. Semantic, metadata, merge-driver, chained-refresh, fork, race,
self-change, and malformed-evidence controls are fixture-proven, not
production-incident-proven.

Limitation: pre-#1738 history cannot produce `shadow_eligible` because
`pr-certification-identity` / `pr-certification-lanes` did not exist.
Post-#1738 shadow records are the next evidence layer, not this item's
activation gate.

## Activation implication

Keep `SHADOW_ONLY` available. Do not treat this replay as permission to
skip lint, typecheck, or long test lanes. A later decision may choose
`SHADOW_ONLY`, `REDUCED_FAST_REFRESH`, or `NATIVE_MERGE_QUEUE` only after
live shadow yield and any full-only failures are re-measured.
