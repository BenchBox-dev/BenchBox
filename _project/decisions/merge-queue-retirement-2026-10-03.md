# Retire the merge queue, the strict up-to-date rule and the soundness attestation

Date: 2026-10-03
Status: Decided. The ruleset change that removes the merge queue and the strict
up-to-date rule from `develop-squash-only` is a repository settings change and
lands separately; until it is made, the queue and the strict rule still apply.
Related: `docs/operations/merge-queue-governance.md` (now "Merge and trunk
governance"); `docs/development/adr/adr-dev-loop-v2.md` (D4 and the 2026-10-03
amendment); `.github/workflows/trunk.yml`.

## Decision

`develop` stops using GitHub's merge queue and its strict up-to-date rule.
A pull request merges through auto-merge once its required checks pass on its
own head. A new workflow, `.github/workflows/trunk.yml`, tests `develop` after
each merge, and a revert-first policy handles a red trunk. The PR-body
`Soundness review:` attestation check (the `soundness-flag` job) is deleted. A
required `oracle-review` check takes its place for result-affecting changes. The
public-site visual comparison is advisory until the site is in production.

## Evidence

All counts were measured on 2026-10-02 and 2026-10-03.

Of the 40 most recent failed merge-group runs (2026-10-01T22:55Z to
2026-10-02T22:45Z), 38 were failures of the queue machinery, not of the code
being merged. The soundness-flag anchor byte-identity check failed 13 times: in
a merge group it compared the group tree with the pull request head, so any
other merge ahead of a pull request ejected it. A medium-test shard was killed
by the runner 12 times. A ruleset-drift pin mismatch accounted for 8, and a
visual baseline that was absent or mismatched for 5. The other two were a
state-dependent test flake that passed unchanged 22 minutes later, and a Windows
lock timeout in a job that runs only in the queue. None of the 40 was a
confirmed cross-PR integration failure, which is the failure a queue exists to
catch. On 2026-10-02 the queue ran 94 times for 37 merges.

The medium shard kills had one cause: a single test,
`tests/unit/core/tpcds/test_parameter_consumption_inventory.py`, grew one worker
to 14 GB. That is fixed in #2560. In the visual comparison, the one render in 58
that differed between runs was a smooth scroll still in flight at capture; the
capture spec now waits for it.

## What replaces each control

| Control removed | Replacement |
|---|---|
| Merge queue testing the combined tree before merge | Required PR checks on the pull request head, then auto-merge. `.github/workflows/trunk.yml` tests `develop` after each merge: the fast lane (with an ungraced fast-lane ceiling), a four-shard medium tier and the correctness gate. |
| Strict up-to-date rule (race lock) | The post-merge trunk run. A change that passed on an older base and breaks the merged tree shows up there, not in a queue. |
| Ejection of a bad group | Revert first. `make trunk-revert PR=<n>` opens the revert of a merged pull request, and `make pr-open` refuses non-revert PRs while trunk has been red for more than 30 minutes. |
| PR-body `Soundness review:` attestation (`soundness-flag`) | A required `oracle-review` check that passes only when the Codex connector app has reviewed the current head of a result-affecting PR. Required review-thread resolution and the scheduled post-merge digest are unchanged. |
| Visual comparison as a merge gate in queue groups | Advisory. The job still runs and uploads its report. It becomes a gate again when the public site is in production. |
| Heavy tier run only in the queue | The four-shard medium tier and correctness gate run in `trunk.yml` on every merge. |

## Risks and the signal for each

- A change that is green on an older base breaks the merged tree. Signal: a
  trunk failure whose culprit PR was green on an older base, more than about
  once a week. Response: turn the strict up-to-date rule back on for
  result-affecting paths only, not for the whole branch.
- Trunk stays red and nobody reverts. Signal: trunk red for more than two hours
  with no revert PR open. Response: the owner reverts the culprit with
  `make trunk-revert PR=<n>`.
- The Codex connector is down, so `oracle-review` never reports. Signal: the
  check pending for more than four hours. Response: treat the connector as
  down and the owner reviews the change.
- Medium-tier shards are killed again. Signal: more than one shard kill a day.
  Response: read the shard's memory sampler output to find the test that is
  growing a worker.

## Supersedes

- `native-merge-queue-activation-20260822.md`: the decision to run the native
  merge queue on `develop`, its parameters, and the `merge_group` required-check
  contract no longer hold.
- `native-queue-local-landing.md`: a stale branch no longer publishes without a
  refresh because the queue tests the speculative merge; there is no queue to
  verify and no `queue_verified` result to consume.
- `strict-base-refresh-merge-queue-2026-08-14.md`: the assessment that a native
  queue is the stronger long-term integration validator no longer holds; trunk
  testing after the merge replaces it.
- `strict-base-refresh-activation-2026-08-14.md`: the selected path keeps the
  strict current-base rule as the race lock, and that rule is retired.
- `strict-base-refresh-policy-2026-08-14.md`: "keep the strict current-base rule
  as the race lock, and treat refresh CI as a latency optimization inside it" no
  longer holds, and so the refresh program it governs is closed.
- `strict-base-refresh-ci-profile-2026-08-14.md`: the profile measured the
  merge-unblock wall under strict checks, where every `develop` advance forced a
  refresh run; no refresh run exists now.
- `heavy-tier-queue-only-2026-09-16.md`: running the heavy tier only in the
  merge-queue run no longer holds, because there is no merge-group run to carry
  it.
- `public-site-visual-required-check-2026-09-24.md`: visual acceptance as a
  required check no longer holds; it is advisory until the site is in
  production.
- `visual-baseline-queue-follower-policy-2026-09-25.md`: the queue-follower
  baseline policy has no queue to apply to.
- `visual-baseline-queue-candidate-2026-09-26.md`: the leader candidate and the
  follower wait serve merge groups, which no longer exist.
- `visual-baseline-site-equivalent-ancestor-2026-09-27.md`: the
  site-equivalent ancestor lookup and the 10-minute follower wait serve merge
  groups, which no longer exist.
- `auto-merge-policy-consolidation-2026-08-06.md` (in part): D7, which kept
  review gates advisory and out of the merge path; the required `oracle-review`
  check is now a merge-blocking review signal for result-affecting changes, and
  the PR-body attestation is gone.
- `codeowner-approving-count-zero-constraint-2026-09-15.md` (in part): item 3,
  no merge-blocking automated review gate. The `oracle-review` check is one for
  result-affecting changes. Items 1 and 2 stand.
