---
date: 2026-09-06
develop_sha: d1accbb6ec4706664fcf33ba58f275d667982050
measured_at_sha: d1accbb6ec4706664fcf33ba58f275d667982050
checked_sha: d1accbb6ec4706664fcf33ba58f275d667982050
---

# Develop PR Concurrency Cancellation Audit

## 1. Background and Objective

This audit evaluates the CI compute cost and dev-loop impact of workflow concurrency cancellation (`cancel-in-progress: true`) on `develop` pull requests.

On 2026-08-20, an operational concern was raised regarding `.github/workflows/pr.yml:8-10`, `.github/workflows/results-explorer-browser.yml:32-34`, and `.github/workflows/develop-refresh-shadow.yml:15`. Under the concurrency group `develop-pr-${{ github.ref }}` with `cancel-in-progress: true`, every new commit on a PR branch cancels in-flight required gates and restarts them on the new head. Prior to merge queues, when combined with strict required status check policies, PRs that became `BEHIND` due to intervening merges on `develop` required manual absorption (`make pr-refresh`). If another merge landed while the refreshed PR ran its required gate (p50 interarrival of 27.5 minutes vs. a 20–32 minute test wall), the in-flight gate would be cancelled and restarted, creating a cycle of discarded runner-minutes.

The objective of this audit is to:
1. Quantify the compute discarded by concurrency cancellations across a 14-day trailing window of merged `develop` PRs.
2. Differentiate between ordinary feature pushes and base-refresh merges.
3. Compare the compute cost of cancelling runs against the cost of letting superseded runs finish.
4. Evaluate whether workflow concurrency settings require adjustment.

---

## 2. Methodology and Sample

The measurement sample covers a 14-day trailing cohort of 195 merged `develop` PRs (PR #1827 through PR #2060), collected via `_project/scripts/dev_loop_pr_metrics.py --event-fanout --json` and GitHub Actions run history.

The analysis inspects:
- **Final PR Heads**: The terminal commit of each merged PR, evaluating completed and cancelled runner-minutes, required gate wall times, all-workflow durations, and queue delays under the `event_fanout_v1` schema.
- **Intermediate Superseded Pushes**: A targeted sample of intermediate pushes on feature branches where in-flight runs were terminated by `cancel-in-progress: true`.

---

## 3. Findings and Metrics

### 3.1 Final Head Aggregate Metrics (N = 195 PRs)

| Metric | Aggregate Value |
|---|---|
| Sample Size | 195 merged PRs |
| Pushes After Open (Median) | 1 push (42.1% had 0 pushes; 57.9% had ≥ 1 push) |
| First-Pass Green Rate | 72.3% (141 / 195) |
| Fast-Test Job Duration (`test (ubuntu-latest, 3.12)`) | Mean: 13.7 min (822.6s) / p95: 21.8 min (1,306.0s) |
| Medium-Test Job Duration (`medium-test`) | Mean: 20.1 min (1,204.2s) / p95: 26.6 min (1,594.0s) |
| Required Gate Wall Time (`ci-required-result`) | Median: 21.8 min (1,310.0s) / p95: 32.2 min (1,930.2s) |
| All-Workflow Wall Time | Median: 22.1 min (1,326.0s) / p95: 35.4 min (2,126.4s) |
| Queue Delay | Median: 25.8 min (1,549.0s) |
| Total Completed Runner-Minutes | 15,682.1 runner-minutes (Median: 81.3 runner-minutes per PR) |
| **Cancelled Runner-Minutes on Final Heads** | **0.27 runner-minutes total** (Max: 0.27 min; 2 cancelled jobs) |

Across final heads that actually merged, cancelled compute is virtually non-existent (0.27 minutes total across 195 PRs). Final heads are pushed and left to complete their required gates without immediate preemption.

### 3.2 Intermediate Superseded Pushes

To measure discarded compute on non-terminal commits, we sampled 15 intermediate workflow runs cancelled by subsequent pushes:

| Run ID | Branch | Commit Summary | Discarded Compute |
|---|---|---|---|
| 34006483201 | `feat/pub-migration-soak-f` | `feat(publication): align sound` | 65.8 runner-min |
| 34006470113 | `feat/pub-migration-soak-f` | `feat(publication): align sound` | 0.0 runner-min |
| 34006452348 | `feat/pub-transaction-executor-c` | `feat(publication): implement t` | 44.6 runner-min |
| 34006438155 | `feat/pub-transaction-executor-c` | `feat(publication): implement t` | 0.0 runner-min |
| 34006250853 | `feat/pub-transaction-executor-c` | `feat(publication): implement t` | 13.1 runner-min |
| 34006159275 | `feat/pub-transaction-journal-b` | `feat(publication): implement c` | 48.5 runner-min |
| 34005834208 | `feat/corpus-coverage-final-integration` | `feat(corpus): coverage final int` | 47.8 runner-min |
| 34005710786 | `feat/pub-migration-soak-f` | `feat(publication): align sound` | 22.8 runner-min |
| 34005664160 | `feat/pub-transaction-executor-c` | `feat(publication): implement t` | 45.2 runner-min |
| 34005600375 | `feat/pub-transaction-journal-b` | `feat(publication): implement c` | 46.3 runner-min |
| 34001961157 | `feat/pub-transaction-executor-c` | `feat(publication): implement t` | 73.0 runner-min |
| 34001905337 | `feat/pub-migration-soak-f` | `feat(publication): align sound` | 52.5 runner-min |
| 34001833818 | `feat/pub-transaction-journal-b` | `feat(publication): implement c` | 32.3 runner-min |
| 34001832919 | `feat/pub-provider-feasibility-a` | `feat(publication): define prov` | 62.0 runner-min |
| 34000907773 | `feat/pub-transaction-recovery-d` | `feat(publication): implement e` | 82.8 runner-min |

**Summary of Sampled Intermediate Cancellations:**
- Mean discarded compute per cancelled run: 42.5 runner-minutes.
- Typical cancellation point: Mid-flight during the 20–30 minute `medium-test` or `correctness-gate` execution.

---

## 4. Discarded Compute vs. Cost of Letting Superseded Runs Finish

A key question is whether `cancel-in-progress: true` saves or wastes compute when a commit supersedes an in-flight run.

### 4.1 Ordinary Feature Pushes

When an author pushes a new commit to a feature branch (addressing review feedback, fixing a local test, or amending a change), the previous commit is invalidated. The prior commit will never be merged.

- **Completed run cost:** ~81.3 runner-minutes (full required gate matrix).
- **Discarded cost at cancellation:** ~42.5 runner-minutes (sampled mean).
- **Savings achieved by cancellation:** ~38.8 runner-minutes saved per superseded commit.

If `cancel-in-progress` were disabled (`false`), the system would spend the full 81.3 runner-minutes on the obsolete commit while simultaneously starting another 81.3 runner-minute run on the new commit. This would almost double runner concurrency consumption for no verification benefit. Therefore, `cancel-in-progress: true` is strictly optimal for ordinary pushes.

### 4.2 Base-Refresh Merges and Merge Queue Architecture

The problematic scenario occurred when a PR was ready and green, but had to absorb an updated `develop` base (`git merge origin/develop`). Because the PR branch changed its SHA, `cancel-in-progress` aborted the previous run. If multiple merges landed on `develop` in quick succession, the PR could be repeatedly restarted without ever merging.

However, on 2026-08-22, BenchBox merged PR #1808, adopting the **GitHub Native Merge Queue** (`merge_group` workflow triggers and merge queue branch protection).

The native merge queue alters the dev loop:
1. PR branches run their required checks on their own feature head once.
2. When checks pass and auto-merge is armed (`make pr-ready`), the PR enters the merge queue (`gh-readonly-queue/develop/...`).
3. The merge queue generates a speculative merge commit against the latest `develop` tip and executes required checks under an isolated `merge_group` concurrency group (`develop-pr-${{ github.event.merge_group.head_ref }}`).
4. Other PRs merging into `develop` or joining the queue do not cancel in-flight merge queue runs.
5. PR branches are no longer forced to run repeated manual `make pr-refresh` loops against `develop`.

---

## 5. Conclusion and Recommendations

1. **Retain `cancel-in-progress: true`:**
   Workflow cancellation remains the correct setting for PR branches in `.github/workflows/pr.yml`, `.github/workflows/results-explorer-browser.yml`, and `.github/workflows/develop-refresh-shadow.yml`. It prevents substantial compute waste (~39 runner-minutes per superseded commit) during normal iterative development.
2. **No Workflow or Ruleset Modifications:**
   The historical risk of required-gate starvation from base refreshes has been resolved by the GitHub Native Merge Queue (`merge_group` isolation).
3. **Observation Completed:**
   No further action, workflow changes, or ruleset modifications are required for this item.

---

## 6. w3 correction with complete lifecycle evidence (2026-09-08)

Sections 1–5 above are preserved unchanged as the w0–w2 record. Their final-head
aggregate (§3.1) understated cancellation cost: it measured 0.27 cancelled
runner-minutes on terminal heads only. Recomputed from the full-cohort lifecycle
baseline (`_project/analysis/ci-lifecycle-baseline.json`, 349 in-window PRs,
1384 synchronize heads including 239 branch-runs-recovered orphan tips,
9112 attempts, every run attempt per head):

| Metric | Value |
|---|---|
| Cancelled runner-minutes, all heads | 7719.0 |
| Cancelled on final (merged) heads | 499.8 |
| Cancelled on superseded (non-final) heads | 7219.3 |
| Failed-job runner-minutes (own bucket since the method correction) | 2715.1 |
| PRs with any superseded-head cancellation | 108 of 349 |
| Superseded-head cancelled minutes per head | mean 7.0, p50 0.0, max 62.2 (n = 1035) |

Superseded-head cancellations split by the refresh classifier:

| Following push kind | Cancelled minutes |
|---|---|
| Ancestry-only refresh (exact two-parent, no feature edits) | 1438.6 |
| Ordinary feature push | 3122.4 |
| Unclassifiable (orphan tips outside PR history, externally-based) | 2658.2 |

The 2658.2-minute remainder is conservatively excluded from both named buckets:
those heads cannot be classified by the history-based classifier, so they are
not counted as refresh waste.

Corrected reading: whole-lifecycle cancellation cost is ~28,000× the final-head
figure, concentrated on superseded heads as the item description predicted. The
w0–w2 recommendation stands: cancellation remains optimal for ordinary feature
pushes (3122.4 minutes were already spent when those runs were superseded;
letting them finish would have cost full gates on obsolete commits), and the
refresh-following portion (1438.6 minutes over 28 days) is the only arguably
avoidable share — already addressed structurally by the native merge queue
(§4.2), which this item does not modify. Non-tip intra-push commits (296 of
1384, classified separately in the lifecycle baseline) never ran CI and are
excluded from both totals; missing-artifact heads are zero, so both figures
are lower bounds only via retention loss, not via unobserved history.
