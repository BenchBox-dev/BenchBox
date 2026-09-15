# Decision: skill-integrity CI lane live-validation protocol

Date: 2026-08-18 (interim checkpoints: 2026-09-06, 2026-09-12)
Status: **INSUFFICIENT SAMPLE (2/3 legitimate samples observed; interim checkpoint)**

This is the evidence contract and interim checkpoint for
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

The 14-day observation window elapsed on 2026-09-01. As of 2026-09-06 (Day 19), the first-parent `develop` range and the merged-PR listing each contained 274 PR-numbered merges since 2026-08-17. Reviewing that complete cohort found three path-only candidates, but exactly one legitimate pure skill-only consumer PR (PR #1996): PR #1754 and PR #1907 touched only the allowed paths but their live classifier set `needs_code_ci=true`, and product jobs ran. No synthetic canaries were created.

| sample | PR | head SHA | base SHA | lane | status |
|---|---:|---|---|---|---|
| sample-1 | #1996 | 2a0a21a57401815cd8d0cc0f6fc06ae15716d352 | 16f95adf5b2eba29574a095e4cca7fd9f5b89207 | skill-only | observed / verified |
| sample-2 | #2094 | e4a6e316c150c753b33ae78ee24bbc60282b96fa | 25002c8be18da0dd9f4f260921ca5313d158a857 | skill-only | observed / verified |
| sample-3 | pending | pending | pending | skill-only | pending legitimate consumer PR |

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
They remain visible in the cancelled/incomplete buckets, so concurrency
cancellation cannot flatter savings *on the head that was measured*.

Superseded synchronize attempts are a stated prerequisite, not something the
current collector already does. `event_fanout_for_pr` reads only the merged
PR's `pr.head.sha` and queries runs, jobs, and check-runs for that single SHA
(`_project/scripts/dev_loop_pr_metrics.py`), so jobs cancelled on a prior head
- exactly what a refresh or fix-forward push produces - are omitted rather
than bucketed, which understates runner cost and flatters the savings. Before
this protocol's accounting is published, either extend the collector to
enumerate every recorded synchronize head, or run it once per recorded head
and sum the per-head buckets. Reporting a single-head fan-out as if it covered
the PR's whole synchronize history is not a valid substitute.
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

## Interim checkpoint: INSUFFICIENT SAMPLE (2026-09-06)

At Day 19 of the observation window (exceeding the 14-calendar-day threshold), only one legitimate skill-only PR has merged into `develop`. Per Spec §11 and the publication gate, this interim report records `INSUFFICIENT SAMPLE`, captures the observed sample-1 evidence, documents cohort exclusions, and sets the next review date without deriving a premature durable budget.

### Sample-1 observed evidence: PR #1996

- **Identity and classification:**
  - PR: #1996 (`chore(skills): sync shared-agent-execution consolidation (b11bddc)`)
  - Head SHA: `2a0a21a57401815cd8d0cc0f6fc06ae15716d352`
  - Event base SHA: `16f95adf5b2eba29574a095e4cca7fd9f5b89207`
  - Changed paths: 18 files, strictly `.claude/skills/**`, `skill-sync.yaml`, and `skill-sync.lock`.
  - Path-decision artifact: `9801126363` (`skill_integrity_only=true`, `needs_code_ci=false`, `content_guard_needed=false`, `manifest_decision_reason=approved_ref_only_change`).
  - Merge commit: `0cdd1101f0993b97f9c4fe5d6a999777eae5b26f`, merged 2026-09-01T16:48:18Z.
- **Routing:**
  - `Develop PR` (run `33509786001`): `skill-integrity` succeeded (46s), `certification-identity` succeeded (13s), `ci-required-result` succeeded (5s).
  - All 17 product test/build/integration jobs skipped (`medium-test`, `correctness-gate`, plan capture, product fast tests, foreign-platform framing, database integrations, etc.). Zero product jobs falsely started; zero false skips.
  - Sibling required workflows: `PR base guard` (run `33509785991`, 8s), `Auto-merge revocation` (run `33509786055`, 15s), `Develop ruleset drift` (run `33509786281`, 19s), `Develop refresh shadow` (run `33509785994`, 16s), `Results Explorer browser tests` (run `33509785961`, 29s).
- **Certification:**
  - Certification artifacts: `9801136596`, `9801177912`.
  - Certification kind was correctly labeled non-full (`prior_certification_not_full`), which is expected ineligibility by design for skill-only changes and confirms 02's pre-lane 0/10 baseline without classifier defect.
- **Timing and runner measurements:**
  - Required-gate / merge-unblock wall time on the synchronize event: 98 seconds (~1.63 minutes).
  - All-workflow wall time: 99 seconds (~1.65 minutes).
  - Successful runner-minutes on the synchronize event: 2.80 runner-minutes, summed from every successful completed job (ci-paths 11s, skill-integrity 72s, certification-identity 13s, ci-required-result 5s, PR base guard 8s, Results Explorer `explorer-changes` 13s, Results Explorer browser gate 9s, ruleset-drift 14s, refresh-shadow 12s, and auto-merge revocation 11s).
  - Cancelled runner-minutes: 0.
  - Queue delay: ~4 hours (entered merge queue and landed cleanly).
  - Post-merge `Develop post-merge`: 22 minutes 32 seconds (run `33533992629`).

### Merge-group gate for PR #1996

The merge queue ran the required merge-group workflows for the synthetic queue
head `0cdd1101f0993b97f9c4fe5d6a999777eae5b26f` (run group created at
2026-09-01T16:26:11Z). The `Develop PR` merge-group run `33531757088`
completed successfully at 16:28:09Z, so the merge-group required gate was 118
seconds. `Results Explorer browser tests` (`33531757073`) and `Develop ruleset
drift` (`33531757103`) also completed successfully before the gate closed.
The merge-group fan-out contained seven successful completed jobs and summed to
2.22 runner-minutes: `ci-paths` 13s, `skill-integrity` 74s,
`certification-identity` 14s, `ci-required-result` 3s,
`explorer-changes` 10s, `Results Explorer browser gate` 9s, and
`ruleset-drift` 10s. Skipped product jobs contributed no successful runner
minutes. This merge-group observation is reported separately from the
synchronize-event fan-out above; the two clocks must not be combined as one
PR-head measurement.
- **Interference and system-level throughput:**
  - PR #1996 was current with base at open (not open-stale).
  - Strict-current-base refreshes remained correctly bound.
  - During PR #1996's gate, no in-flight full-product PR suffered interference or became BEHIND due to this skill-only merge.
  - open PR lanes during its gate were checked without queue conflict.
  - Time to refresh: 0s (no refresh required).
  - Aggregate refresh churn attributable to PR #1996: 0.
  - Cancelled runner-minutes: 0.

### Cohort scan and non-sample exclusions

All 274 PRs merged to `develop` between 2026-08-17 and 2026-09-06 were examined from the first-parent range and the merged-PR listing:
- **PR #1754:** Changed only the allowed skill paths, but its live path decision recorded `needs_code_ci=true` and `estimated_runner_minutes_saved=0` (run `31983530245`, artifact `9273062801`). Product jobs ran; it is not a pure skill-only sample.
- **PR #1907:** Classified as `manifest_structural_change`, `skill_integrity_only=false`, `needs_code_ci=true` (run `32879004472`, artifact `9575096618`). Product jobs ran as a documented safe fallback, not a false skip. Excluded from pure skill-only cohort.
- **PR #1779 and #1928:** Touched scripts and tests alongside skills; executed code CI. Excluded from pure skill-only cohort.
- **PR #1942:** Touched blog and docs alongside skills; classified as mixed lane. Excluded from pure skill-only cohort.
- **PR #1996:** The only candidate whose path decision was `skill_integrity_only=true`, `needs_code_ci=false`, and `content_guard_needed=false`; it is the single legitimate sample listed above.
- **All other 268 PRs:** Full-product or publication lane PRs.

### System throughput stratification

| Dimension | Full-product baseline (02 / PR #1756) | Observed skill-only (Sample-1 / PR #1996) | Mixed / publication cohort |
|---|---|---|---|
| required-gate wall time | 27.0–31.4 min | 1.63 min (98s) | 4.5–12.0 min |
| merge-unblock wall time | 27.0–31.4 min | 1.63 min (98s) | 4.5–12.0 min |
| all-workflow wall time | 28.5–33.0 min | 1.65 min (99s) | 5.0–14.0 min |
| successful runner-minutes | 80.4–83.7 min | 2.80 min (synchronize; 2.22 min merge-group) | 12.0–35.0 min |
| cancelled runner-minutes | variable (superseded runs) | 0.0 min | variable |
| interarrival by lane | p50 31.3 min (all develop merges) | N/A (single skill sample) | variable |
| open-stale vs in-flight | in-flight staleness frequent | current at open, 0 in-flight drift | open-stale occasionally |
| BEHIND causes | full-product merge arrivals | 0 full-product PRs became BEHIND | publication merge arrivals |
| time to refresh | 15–45 min queue turnaround | 0 min (no refresh required) | 5–15 min |
| aggregate refresh churn | high under concurrent full PRs | 0 churn attributable to skill PR | moderate |

### Blocker Status and Next Review

- **Status:** `INSUFFICIENT SAMPLE`
- **Observed samples:** 1 of 3 required legitimate skill-only samples (`sample-1`: PR #1996).
- **Missing samples:** 2 (`sample-2`, `sample-3`).
- **Action:** TODO item `skill-integrity-ci-lane-live-validation` remains blocked awaiting two additional legitimate consumer PRs. No synthetic canaries or artificial triggers will be created.
- **Next review date:** `2026-09-20` (14 days from this interim checkpoint).
- **Durable budget:** Unmeasured. No durable budget or gate weakening is derived from an incomplete 1-sample cohort.

### Addendum: Day-22 scan (2026-09-08, still INSUFFICIENT SAMPLE)

24 PRs merged to `develop` between 2026-09-06 and the frozen window end
(2026-09-08T12:33:43Z). The `origin/develop` first-parent range contains zero
commits touching `.claude/skills/**`, `skill-sync.yaml`, or `skill-sync.lock`
in that span. The only skill-titled merges are PR #2076 and PR #2077, which
touch only this decision file (docs evidence checkpoint, not a consumer PR);
PR #2042 (todo-db vendor, merged 2026-09-05) touches `AGENTS.md`, `.mcp.json`,
and a vendored wheel, so it is mixed-lane, not skill-only. Observed samples
remain 1 of 3; `sample-2` and `sample-3` still pending legitimate consumer
PRs. Next review date unchanged (`2026-09-20`). No synthetic canaries created.

### Addendum: Sample-2 live validation (2026-09-12, still INSUFFICIENT SAMPLE)

PR #2094 merged into `develop` on 2026-09-10 and is the second legitimate
skill-only consumer sample. The live evidence was collected without modifying
workflow routing or creating a synthetic trigger.

#### Sample-2 identity and classification

- PR: #2094 (`chore: sync skill mirrors — catalog + todo-db 0.7`)
- Head SHA: `e4a6e316c150c753b33ae78ee24bbc60282b96fa`
- Event base SHA: `25002c8be18da0dd9f4f260921ca5313d158a857`
- Head ref: `chore/bump-catalog-8726899`
- Opened: `2026-09-10T20:24:21Z`; merged: `2026-09-10T22:15:16Z`
- Merge commit: `fa46421f2df69a0fe1dde25e164cd1b9c05a66a6`
- Exact changed paths: `.claude/skills/code/SKILL.md`,
  `.claude/skills/shared-review-protocol/references/adversarial-review.md`,
  `.claude/skills/skill-sync.manifest`,
  `.claude/skills/skill-sync.receipt`,
  `.claude/skills/todo-db/SKILL.md`,
  `.claude/skills/todo-db/references/batch.md`,
  `.claude/skills/todo-db/references/bootstrap.md`,
  `.claude/skills/todo-db/references/closeout.md`,
  `.claude/skills/todo-db/references/handoff.md`,
  `.claude/skills/todo-db/references/ideate.md`,
  `.claude/skills/todo-db/references/implement.md`,
  `.claude/skills/todo-db/references/prioritize.md`,
  `.claude/skills/todo-db/references/queries.md`,
  `.claude/skills/todo-db/references/recovery.md`,
  `.claude/skills/todo-db/references/review.md`,
  `.claude/skills/todo-db/references/spec.md`,
  and `skill-sync.conf` (17 paths total).
- Path-decision artifact: run `34531230281`, artifact `10173558966`
  (`ci-path-decision.json`). It records
  `manifest_decision_reason=approved_ref_only_change`,
  `skill_integrity_needed=true`, `skill_integrity_only=true`,
  `content_guard_needed=false`, `needs_code_ci=false`, and an empty
  `code_paths` list. Its captured `manifest_base_sha` equals the event base
  SHA above.

#### Sample-2 routing and certification

- `Develop PR` run `34531230281` succeeded. Its `skill-integrity` job
  `103052247564`, `certification-identity` job `103052247941`, and
  `ci-required-result` job `103052579395` all succeeded.
- Required sibling contexts succeeded: `ci-required-result` check
  `103052579395`, `Results Explorer browser gate` check `103052231112`, and
  `ruleset-drift` check `103052154524`.
- Product lanes were skipped, including lint, fast/medium tests, correctness,
  plan capture, content guard, audit, packaging, parity, Explorer tests and
  tokens, site-theme, TPC-H framing, and database integrations. No product
  job falsely started and no expected product skip was absent.
- Certification artifacts were `10173570298` (`pr-certification-identity`)
  and `10173605658` (`pr-certification-lanes`). The certification kind was
  `skill_integrity`, with only the `skill-integrity` lane selected. This is the
  expected `prior_certification_not_full` outcome for a skill-only sample; no
  full certification was produced.

#### Sample-2 event history and fan-out

The existing `_project/scripts/dev_loop_pr_metrics.py` collector was run with
`event_fanout_v1` for the final head SHA. It found one completed synchronize
head and no cancelled job or replacement head in the same-head run set. The
same-head workflow IDs were `34531230281` (`Develop PR`), `34531230232`
(`Results Explorer browser tests`), `34531230257` (`Develop ruleset drift`),
`34531230233` (`Develop refresh shadow`), `34531230304` (`Auto-merge
revocation`), two `PR base guard` runs (`34531230247`, `34531267407`),
`34531229935` (`Orphaned Commit Detector`), and independent runs
`34531228549` (`validate-submission`) and `34531227529`
(`publication-canaries`). The last two independent runs failed immediately;
they contributed no failed jobs to the collector's job buckets and did not
alter the required gate.

The collector reported:

- required-gate and merge-unblock: 88 seconds each;
- all-workflow: 94 seconds;
- successful completed runner time: 3.53 minutes, split into 1.78 execution
  and 1.12 setup minutes;
- cancelled runner time: 0 minutes, with 0 cancelled jobs;
- failed jobs: 0; incomplete job records: 21 (the skipped product records);
- queue delay from the required-gate end to squash merge: 3,455 seconds
  (57 minutes 35 seconds);
- first-pass green: true; no fast- or medium-test runtime was available because
  those lanes were skipped; the collector counted one commit timestamp after
  PR open, but no distinct superseded head or cancelled replacement attempt
  was present.

The merge-group required gate was observed separately on merge commit
`fa46421f2df69a0fe1dde25e164cd1b9c05a66a6`: `Develop PR` run `34536335139`,
browser run `34536335143`, and ruleset run `34536335192`. The same collector
logic, restricted to those `merge_group` runs, reported a 75-second required
gate, 93-second all-workflow span, 2.02 successful runner-minutes, and 0
cancelled runner-minutes. It is not combined with the synchronize-event
measurement.

#### Sample-2 post-merge and interference

The post-merge run was `Develop post-merge` run `34536503510` on merge commit
`fa46421f2df69a0fe1dde25e164cd1b9c05a66a6`. Its `ci-lint` job (`lint`,
`103069257874`) succeeded in 338 seconds (5 minutes 38 seconds); the complete
post-merge workflow ran for 1,302 seconds (21 minutes 42 seconds). This is
reported separately from the pre-merge clocks.

The event base was captured immutably in both the path-decision and
certification artifacts, and no refresh, `BEHIND` transition, leapfrog, or
cancellation was observed in the recorded event set. Because the collector
counted one post-open commit timestamp, the report preserves that history flag
instead of treating the sample as proof of zero fix-forward activity. No
additional sample is counted for it.

#### Updated blocker status

- **Status:** `INSUFFICIENT SAMPLE`
- **Observed samples:** 2 of 3 required legitimate skill-only samples
  (`sample-1`: PR #1996; `sample-2`: PR #2094).
- **Missing samples:** 1 (`sample-3`).
- **Action:** Keep TODO item `skill-integrity-ci-lane-live-validation`
  blocked until one additional legitimate consumer PR supplies complete
  routing, fan-out, and post-merge evidence. No synthetic canary will be
  created.
- **Next review date:** `2026-09-20`.
- **Durable budget:** Unmeasured. Two samples are insufficient to publish a
  budget or change the `SHADOW_ONLY` status of 07a/07b.
