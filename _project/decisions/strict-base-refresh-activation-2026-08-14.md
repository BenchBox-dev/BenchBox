# Decision: strict-base refresh activation

Date: 2026-08-14
Status: Accepted. This record selects the program path. It does not change
GitHub settings, required contexts, or workflow skip conditions.
Observed tip: `origin/develop` `7ba0944b62a78896800bd6947a7f58b30dec76b7`
(#1739 replay audit).

Related: `_project/decisions/strict-base-refresh-policy-2026-08-14.md` (#1731);
classifier #1732; shadow #1738; replay
`_project/audits/strict-base-refresh-replay-2026-08-14.md` (#1739); profile
#1734; queue assessment #1733.

Selected outcome: SHADOW_ONLY

## Live revalidation (2026-08-14T18:30Z)

| Surface | Live value |
|---|---|
| Ruleset `15611785` | `enforcement=active`; `strict_required_status_checks_policy=true` |
| Required contexts | `ci-required-result`, `Results Explorer browser gate`, `ruleset-drift` |
| Owner | User `joeharris76`; public; default branch `develop` |
| Merge queue | Unavailable on a user-owned public repository |
| Shadow workflow | `.github/workflows/develop-refresh-shadow.yml` registered `active` |
| Open develop PRs | #1737, #1735, #1724, #1718, #1717 (none are this activation) |

Dependency artifacts on this tip: policy, classifier, shadow workflows,
replay audit, CI profile, and merge-queue assessment.

## Coverage gates

| Gate | Evidence | Pass for reduced / queue? |
|---|---|---|
| full-only failures | Replay: zero on 10 refresh-like commits; cancelled `medium-test` cases were not `shadow_eligible` | Insufficient: no skipped-lane failures can exist until a skip exists |
| Semantic / negative controls | Fixture-proven: fork, chained, self-change, merge-driver, schema, head-drift, malformed | Yes for keep-failing-closed; not skip-safety |
| Hit rate | Fixture eligible path works; historical live hit rate is 0 because identity artifacts did not exist before #1738 | No |
| Required-gate vs all-workflow | Profile #1734: merge-unblock wall is still `medium-test` (~26–31 min). Documentation and other synchronize workflows are separate runner-minutes | Savings claim would be required-gate only |
| lint / ty | Policy forbids skipping `code-lint` (ruff and ty) on any reduced path | Would remain mandatory even if 07a were selected |
| Live shadow classify | #1739 `opened` → `full_required` / `missing_event_sha` (correct). Collector recorded empty `required_contexts` because `GITHUB_TOKEN` cannot read ruleset 15611785 | Fail-closed, so a later synchronize would also stay full until that collection gap is fixed |

No sample-size or calendar threshold is used as the sole gate.

## Comparison

| Path | Safety | Latency | Maintenance | Operator |
|---|---|---|---|---|
| `SHADOW_ONLY` | Full CI remains the oracle. Shadow is observational. Residual risk is unused evidence, not a skipped lane. | No required-gate saving. Refresh tax remains. | Keep shadow + identity artifacts. | None. |
| `REDUCED_FAST_REFRESH` | Would waive named long lanes after exact-merge proof. Residual risk is a skipped `medium-test` / correctness failure that lint and ty cannot see. | Could cut required-gate toward lint+fast if gates passed. All-workflow Documentation cost remains. | Typed waiver contract, kill switch, no generic skipped-as-pass. | Must name every waived lane. Not earned. |
| `NATIVE_MERGE_QUEUE` | Stronger combined-tree validator after org transfer and `merge_group` rehearsal. Residual risk is transfer (Pages `benchbox.dev`, 5 secrets, 3 environments). | Removes branch refresh tax after enqueue. | `merge_group` on all three required contexts. | Transfer is operator-only. 05 is DEFER. |

## Contract for the selected path

- Lanes: none waived. Every current code PR lane, including `code-lint`
  (ruff and ty), still runs.
- Trust: classifier and shadow remain fail-closed evidence. Missing
  artifacts, empty required contexts, forks, chained refreshes, and races
  stay `full_required`.
- Kill switch: disable or delete `develop-refresh-shadow.yml`. There is no
  skip path to unwind.
- rollback: checkout the parent of this decision; no GitHub setting
  changes to reverse.
- Operator: no settings mutation, no repository transfer, no custom merge
  steward.

A `SHADOW_ONLY` result is a valid completion and does not require
engineering a fast path. Strict current-base checks stay on.

## Tracker

`strict-base-refresh-07a-reduced-fast-refresh-rollout` remains blocked.
`strict-base-refresh-07b-native-merge-queue-migration` remains blocked.
Neither path is selected, so neither may become ready. Exactly one
implementation authority is actionable: none.

A later decision may reopen reduced refresh or a native queue only after
live `shadow_eligible` yield is measured with bound required contexts, and
after operator approval for any transfer.
