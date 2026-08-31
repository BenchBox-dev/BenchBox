# Merge Queue Governance and Operational Specification

This document defines the operational architecture, required status check contracts, soundness review invariants, and developer workflows for the GitHub Native Merge Queue on `refs/heads/develop`.

---

## 1. Governance Invariants

1. **Squash Integration Only:** All pull requests targeting `develop` must be integrated via squash merge. Merge commits and rebase-and-merge remain forbidden.
2. **Zero Bypass Actors:** The `develop-squash-only` ruleset enforces `bypass_actors: []`. No user, bot, or organization admin may bypass status checks, linear history, or code owner review.
3. **Soundness Review Boundary:** Any pull request touching files within `SOUNDNESS_PREFIXES` (or matching `_VALIDATION_RE` in `_project/scripts/auto_merge_soundness_paths.py`) cannot be automatically enqueued. It requires explicit maintainer review and manual enqueueing.
4. **Fail-Closed Execution:** If an Actions workflow encounter an unknown or malformed `merge_group` event payload, it must fail closed and withhold reporting green.

---

## 2. Required Status Checks Contract

The merge queue creates temporary merge group refs (`refs/heads/gh-readonly-queue/develop/...`) and dispatches GitHub Actions runs under the `merge_group: [checks_requested]` event. Exactly three status checks are required on `develop`:

| Required Context | Workflow Path | Trigger Events | Contract on `merge_group` |
|---|---|---|---|
| `ci-required-result` | `.github/workflows/pr.yml` | `pull_request`, `push`, `merge_group` | Aggregates fast/medium tests, lint, type checks, and parity gates for the speculative tree. |
| `Results Explorer browser gate` | `.github/workflows/results-explorer-browser.yml` | `pull_request`, `push`, `merge_group` | Always-reporting contract. Runs Chromium on explorer changes; posts success on unaffected paths. |
| `ruleset-drift` | `.github/workflows/develop-ruleset-drift.yml` | `pull_request`, `push`, `merge_group`, `schedule` | Executes trusted base check to ensure no ruleset mutation occurs. |

---

## 3. Queue Configuration Parameters

The operator configures the merge queue within the `develop-squash-only` ruleset using the following verified parameters:

```json
{
  "type": "merge_queue",
  "parameters": {
    "merge_method": "SQUASH",
    "min_entries_to_merge": 1,
    "max_entries_to_merge": 5,
    "grouping_strategy": "ALLGREEN",
    "check_response_timeout_minutes": 60,
    "max_entries_to_build": 5,
    "min_entries_to_merge_wait_minutes": 0
  }
}
```

- **`merge_method: SQUASH`**: Guarantees atomic, single-commit integration.
- **`grouping_strategy: ALLGREEN`**: Groups only entries whose required checks are green.
- **`check_response_timeout_minutes: 60`**: Provides the live queue timeout while preventing hung runners from stalling the queue.
- **`max_entries_to_build: 5`** and **`max_entries_to_merge: 5`**: Bound speculative builds and queue merges at five entries each.
- **`min_entries_to_merge: 1`** and **`min_entries_to_merge_wait_minutes: 0`**: Permit immediate single-entry merges without an artificial wait.

Slow-marked reproducer jobs remain required PR CI through `ci-required-result`.
Post-merge provides fast and medium lanes but no slow-signature lane, so these
reproducers must remain in the required PR lane.

---

## 4. Developer Workflow

### A. Submitting & Arming a PR

Developers submit and arm PRs through repository standard Makefile targets:

```bash
# Open PR against develop with currency check
make pr-open

# When PR is ready for merge, arm auto-enqueue
make pr-ready
```

- `make pr-open` enforces that `origin/develop` is an ancestor of `HEAD` (fails fast on stale branches).
- `make pr-ready` verifies the PR does not touch soundness paths before arming `gh pr merge --auto --squash`.
- Once approved and green on initial `pull_request` checks, GitHub automatically adds the PR to the merge queue.

### B. Soundness Path Withholding

If a PR modifies any soundness path (e.g. `benchbox/core/equivalence/`, `benchbox/core/expected_results/`, `auto_merge_soundness_paths.py`):
1. `make pr-ready` withholds auto-enqueue.
2. The `auto-merge-on-open.yml` workflow revokes any accidental auto-merge flag.
3. The PR requires maintainer approval before manual enqueuing.

---

## 5. Rollback Procedure

If the merge queue must be immediately disabled due to CI outages, deadlocks, or GitHub platform degradation, the operator executes:

```bash
# Emergency rollback to standard branch protection
gh api --method PUT repos/BenchBox-dev/BenchBox/rulesets/15611785 \
  --input docs/operations/rulesets/develop-squash-only-rollback.json
```

Disabling the queue restores immediate single-PR squash merges under the `SHADOW_ONLY` strict-base policy.
