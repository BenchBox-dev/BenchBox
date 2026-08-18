# Decision: skill-integrity CI lane live-validation protocol

Date: 2026-08-18
Status: **Protocol defined; live samples pending.**

This is the w0 evidence contract for
`skill-integrity-ci-lane-live-validation`. It is observational only. It does
not change workflow routing, required contexts, strict-current-base behavior,
test coverage, auto-merge policy, GitHub settings, or the blocked 07a/07b
paths.

## Decision

Use one bounded report and the existing
`_project/scripts/dev_loop_pr_metrics.py --event-fanout` implementation. Do not
create a second metrics implementation or manually sum selected jobs. Savings
remain **unmeasured** until three legitimate skill-only samples are recorded.

A result above five minutes or ten runner-minutes is an investigation
threshold, not a pre-proven contract or an automatic rollback trigger.

## Legitimate cohort

A sample is a merged `develop` PR whose live synchronize event is classified as
an approved pure skill-only change by the repository path-decision artifact:

- the exact changed paths are limited to `.claude/skills/**`, `skill-sync.yaml`,
  and/or `skill-sync.lock`;
- `skill_integrity_needed=true`, `skill_integrity_only=true`,
  `content_guard_needed=false`, and `needs_code_ci=false`;
- no synthetic trigger commit or content change is created to obtain a sample;
- the sample records the PR number, head SHA, **event** base SHA, exact changed
  paths, decision artifact identity, synchronize attempt/run IDs, merge time,
  and post-merge run identity;
- the event base SHA is the immutable
  `github.event.pull_request.base.sha`, not a later mutable `origin/develop` tip.

The first three distinct eligible PRs are `sample-1` through `sample-3`. A
retry, rerun, fix-forward push, refresh, or duplicate observation of the same
head SHA is not a new sample. Mixed and full-product PRs are comparison cohorts,
not substitutes for the three skill-only samples.

### Sample identities

No live samples have been recorded at w0. Do not populate this table with
synthetic or guessed identities; later work units must add the exact 40-character
head and event base SHAs.

| sample | PR | head SHA | base SHA | lane | status |
|---|---:|---|---|---|---|
| sample-1 | pending | pending | pending | skill-only | pending live canary |
| sample-2 | pending | pending | pending | skill-only | pending live sample |
| sample-3 | pending | pending | pending | skill-only | pending live sample |

## Evidence captured per sample

For each eligible PR, capture the following without mutating the PR or creating
an artificial canary:

1. **Identity and classification:** PR number, head SHA, event base SHA, head
   ref, opened/merged timestamps, exact changed paths, path-decision JSON and
   path-list artifact references, and the classifier result.
2. **Routing:** the `Develop PR` skill-integrity job and
   `ci-required-result` result; required contexts `ci-required-result`,
   `Results Explorer browser gate`, and `ruleset-drift`; and proof that
   product jobs did not start: `medium-test`, `correctness-gate`, plan capture,
   product fast tests, foreign-platform framing, and database integrations.
3. **Certification:** the skill-integrity certification kind, required
   umbrella observation, and any `prior_certification_not_full` result.
   Skill-only prior non-full certification is expected ineligibility, not a
   false skip and not evidence for full certification.
4. **Event history:** every relevant synchronize attempt, rerun, fix-forward,
   refresh, cancellation, failure, and the final merge; include workflow run
   IDs and head SHAs so superseded attempts cannot be silently omitted.
5. **Post-merge:** the post-merge `ci-lint` run and its duration/result,
   separately from pre-merge required-gate and all-workflow clocks.

## Interference and staleness classification

Record interference instead of averaging it away:

- **open-stale:** the PR lacked the current event base at open. This is an
  ancestry/open-currency failure and is not a valid clean canary comparison;
- **in-flight:** the PR was current at open but another `develop` merge landed
  before or during its required gate, producing a `BEHIND` transition;
- **refresh:** record the time from the stale/behind observation to the exact
  one-at-a-time refresh, the refreshed head/base identities, and all cancelled
  superseded work;
- **fix-forward/rerun:** retain the original and replacement attempt IDs and
  classify the sample by its original eligible head, without counting a retry
  as a second sample;
- **workflow interference:** record concurrency cancellation, missing,
  failed, or incomplete runs separately from successful completed work.

A stale or interfered sample may remain in the report as an operational
observation, but it cannot be presented as an uncensored pure-lane savings
sample. No open-PR bulk refresh is performed.

## Metric contract

Run the existing `event_fanout_v1` collector for each same-head synchronize
event and report these dimensions separately for skill-only, mixed, and
full-product cohorts:

| Scope | Meaning |
|---|---|
| required-gate | First required-check start to the latest successful required context |
| merge-unblock | The same current strict required-context gate |
| all-workflow | First synchronize workflow start to the last completed sibling on that head SHA |
| successful runner | Completed successful job minutes only |
| cancelled runner | Cancelled job minutes and count, separately from successful work |
| queue delay | Required-gate end to squash merge; not a merge-queue service clock |
| post-merge | Post-merge `ci-lint` duration/result, outside the pre-merge gate |
| setup/execution | The collector's existing successful-job step split |

The all-workflow set includes `Develop PR`, `Results Explorer browser tests`,
`Develop ruleset drift`, `Documentation`, `Auto-merge revocation`, and `PR
base guard`. Include independent always-on workflows, required-gate results,
refresh-shadow observations, revocation, orphan detection, browser umbrella,
and post-merge work where present; do not report only the skill job.

Cancelled and incomplete jobs never enter successful completed runner-minutes.
They remain visible in the cancelled/incomplete buckets, including superseded
synchronize attempts, so concurrency cancellation cannot flatter savings.
Reruns use the collector's existing same-named/latest-success behavior, and a
missing required context is a failure rather than a zero-duration result.

## Certification and safety outcomes

For each sample, explicitly record:

- whether the skill-integrity lane ran and succeeded;
- whether `ci-required-result` observed every selected lane;
- whether any product job falsely skipped or unexpectedly started;
- whether certification was incorrectly labeled `full`;
- whether `prior_certification_not_full` was the expected skill-only outcome;
- whether any structural, classifier, tool, provenance, or policy defect caused
  a fail-closed full-product fallback.

A false-negative route, missing required integrity result, invalid full
certification, or persistent inability to execute the lane is a defect to
report and separately remediate. Measurement itself cannot weaken or reroute a
gate.

## Publication gate

Before calling any savings measured or deriving a durable budget, the report
must contain three distinct sample rows with explicit PR numbers, distinct
40-character head SHAs, and explicit event base SHAs. It must then include
median and maximum required-gate, merge-unblock, all-workflow, successful
runner-minute, cancelled runner-minute, queue-delay, post-merge, BEHIND,
leapfrog, refresh-delay, and false-skip results.

If three legitimate samples do not arrive within 14 days of this protocol,
record `INSUFFICIENT SAMPLE` with the observed cohort search and leave the
budget unmeasured. The historical full-code baseline remains the
2026-08-14 `event_fanout_v1` profile: approximately 27.0–31.4 minutes of
required-gate / merge-unblock wall time and 80.4–83.7 successful runner-minutes
for its three refresh observations. It is a comparison baseline, not a target
or authorization to activate 07a/07b.

07a and 07b remain `SHADOW_ONLY` regardless of the eventual observational
result. Any recommendation or activation decision requires its own explicit
authorization and tracker path.
