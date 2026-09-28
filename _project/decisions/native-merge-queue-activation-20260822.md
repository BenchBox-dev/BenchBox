# Decision: Adopt GitHub Native Merge Queue for `develop` (Post-v0.4.0)

Date: 2026-08-22
Status: Completed. Architecture, triggers, tooling, canary verification, and admin configuration fully implemented across Gates MQ-1 through MQ-5.
Destination: `BenchBox-dev/BenchBox`
Branch: `develop`

Related:
- `_project/decisions/strict-base-refresh-policy-2026-08-14.md`
- `_project/decisions/strict-base-refresh-merge-queue-2026-08-14.md`
- `_project/decisions/strict-base-refresh-activation-2026-08-14.md`
- `_project/decisions/behind-pr-occurrence-2026-08-16.md`
- `_project/decisions/github-org-transfer-benchbox-dev-2026-08-21.md`
- `docs/operations/merge-queue-governance.md`
- `docs/operations/repo-admin-settings.md`

---

## 1. Context & Motivation

On 2026-08-14, the initial merge queue assessment (`strict-base-refresh-merge-queue-2026-08-14.md`) deferred native merge queue adoption because `BenchBox` was owned by a personal user account (`joeharris76`), where GitHub Merge Queues are mechanically unavailable. The project adopted `SHADOW_ONLY` as a safe, fail-closed policy.

On 2026-08-22, the repository successfully transferred to the GitHub organization `BenchBox-dev` (Gates G0–G7 complete). While organization ownership unlocks technical availability, availability alone is not authorization.

This decision record establishes the formal architecture, parameter bounds, soundness invariants, and phased delivery sequence for adopting a GitHub Native Merge Queue on `develop` following the v0.4.0 release.

---

## 2. Decision & Operational Architecture

### 2.0 Governance amendment (verified 2026-08-31)

**Selected outcome: `AMEND_GOVERNANCE`.** Live ruleset verification for
`15611785` found the queue active with `ALLGREEN`, a 60-minute response
timeout, `max_entries_to_build: 5`, `max_entries_to_merge: 5`, `SQUASH`,
`min_entries_to_merge: 1`, and `min_entries_to_merge_wait_minutes: 0`.
The governance documentation is amended to match that live state and the
current `.github/workflows/pr.yml` `ci-required-result` `needs` contract.
The original activation decision and its historical 45-minute/
`ONLY_NON_FAILING` bounds remain below as historical context; they are not
silently rewritten.

This amendment records the configuration already active in GitHub and does
not change the ruleset. The operator-facing activation runbook has recorded
the `ALLGREEN`/60-minute direction since PR #1814; current evidence does not
justify a protected-settings rollback within this documentation-only item.

Slow-marked reproducer jobs remain required PR CI through
`ci-required-result`: post-merge has fast and medium lanes but no slow-signature
lane, so removing them from required PR CI would remove their only required
execution path.

`scripts/ruleset_drift_check.py` verifies the required-check contract but does
not inspect merge-queue parameters. Extending that checker remains a separate
follow-up rather than part of this amendment.

The project will adopt GitHub Native Merge Queue for `refs/heads/develop` under the following strict configuration:

### A. Queue Parameters

| Parameter | Value | Rationale |
|---|---|---|
| **Merge Method** | `SQUASH` | Strictly enforces single-commit integration per PR matching repository policy. |
| **Grouping Strategy** | `ALLGREEN` | Matches the active ruleset; entries are grouped only when required checks are green. |
| **Minimum Entries to Merge** | `1` | Ensures zero artificial latency when queue depth is low. |
| **Maximum Entries to Merge** | `5` | Bounds the CI concurrency footprint and failure bifurcation tree. |
| **Check Timeout** | `60 minutes` | Matches the active ruleset response timeout. |
| **Max Concurrent Builds** | `5` | Matches runner concurrency budget. |
| **Minimum Merge Wait** | `0 minutes` | Allows immediate merge when the minimum entry count is met. |

The initial 2026-08-22 activation bounds recorded `ONLY_NON_FAILING` and a
45-minute timeout. Those historical values are retained here for auditability;
the 2026-08-31 amendment above records the live configuration now governing
the queue.

### B. Required Status Checks Contract

The merge queue triggers GitHub Actions workflows via the `merge_group: [checks_requested]` event. Exactly three status checks remain required on `develop`, and each must report on `merge_group`:

1. `ci-required-result` (Aggregator in `.github/workflows/pr.yml`)
2. `Results Explorer browser gate` (Always-reporting contract in `.github/workflows/results-explorer-browser.yml`)
3. `ruleset-drift` (Trusted base check in `.github/workflows/develop-ruleset-drift.yml`)

### C. Soundness Review & Enqueue Invariants

1. **Zero Bypass Actors:** The `develop-squash-only` ruleset retains `bypass_actors: []`. No user, bot, or organization admin may bypass required status checks or review gates.
2. **Soundness Withholding:** Pull requests that touch `SOUNDNESS_PREFIXES` (as evaluated by `_project/scripts/auto_merge_soundness_paths.py`) cannot be automatically enqueued. They require explicit maintainer review and manual enqueueing.
3. **Fail-Closed Event Handling:** Any unhandled workflow event or malformed merge group payload must fail closed.

---

## 3. Implementation Phases (Gates MQ-1 through MQ-5)

```text
MQ-1 (Governance & Spec)
 └── merge-queue-01-decision-and-governance-spec [This Item]
MQ-2 (CI Workflow Triggers)
 └── merge-queue-02-workflow-merge-group-triggers
MQ-3 (Tooling & Enqueue Safety)
 └── merge-queue-03-soundness-and-tooling-adaptation
MQ-4 (Canary Rehearsal)
 └── merge-queue-04-canary-rehearsal-and-smoke
MQ-5 (Production Activation)
 └── merge-queue-05-develop-ruleset-activation
```

---

## 4. Rollback & Disaster Recovery

If the native merge queue experiences an outage, deadlocks, or blocks development throughput post-activation, the operator executes immediate rollback to standard branch protection:

```bash
# Operator rollback command: Disable merge_queue on develop-squash-only ruleset
gh api --method PUT repos/BenchBox-dev/BenchBox/rulesets/15611785 \
  --input - << 'EOF'
{
  "name": "develop-squash-only",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/develop"],
      "exclude": []
    }
  },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": true,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [
          { "context": "ci-required-result" },
          { "context": "Results Explorer browser gate" },
          { "context": "ruleset-drift" }
        ]
      }
    },
    {
      "type": "required_linear_history"
    }
  ]
}
EOF
```

Disabling `merge_queue` immediately restores standard `SHADOW_ONLY` PR squash merges without dropping pending commits or disrupting repository state.
