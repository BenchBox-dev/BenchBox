# Native Merge Queue Canary Rehearsal Runbook

This runbook provides the operational procedure and scenario checklist for conducting an end-to-end rehearsal of the GitHub Native Merge Queue on `BenchBox-dev/BenchBox` prior to production enablement on `refs/heads/develop`.

---

## 1. Objectives & Safety Invariants

- **Isolation Invariant:** The production `develop-squash-only` ruleset must remain untouched during initial canary runs. Rehearsals run against a dedicated test branch (e.g. `smoke/merge-queue-canary`) or staged sandbox ruleset.
- **Contract Proof:** Prove that all three required status checks (`ci-required-result`, `Results Explorer browser gate`, `ruleset-drift`) report successfully under `merge_group: checks_requested`.
- **Soundness Gate Proof:** Prove that pull requests touching `SOUNDNESS_PREFIXES` are strictly withheld from auto-enqueueing.

---

## 2. Rehearsal Scenarios & Verification Matrix

### Scenario 1: Documentation / Content PR (Fast Lane)
- **Action:** Open PR modifying markdown documentation only (e.g. `docs/about/overview.md`).
- **Execution:**
  1. Open and arm PR: `make pr-open READY=1`
  2. Verify PR enters the merge queue upon passing initial branch checks.
  3. Inspect the spawned `merge_group` workflow run:
     - `ci-paths` classifies `safe-content-only: true`.
     - Code lanes skip; `content-guard` passes; `ci-required-result` aggregates green.
     - `Results Explorer browser gate` reports success (no explorer changes).
     - `ruleset-drift` executes trusted base check and reports green.
  4. Verify PR squash-merges cleanly into target branch.

### Scenario 2: Code PR (Full Test Matrix)
- **Action:** Open PR modifying core Python code and unit tests (e.g. `benchbox/core/` non-soundness path).
- **Execution:**
  1. Open and arm PR: `make pr-open READY=1`
  2. Verify PR enters the merge queue.
  3. Inspect the spawned `merge_group` workflow run:
     - `ci-paths` classifies `needs-code-ci: true`.
     - `code-lint`, `code-test`, `medium-test`, `correctness-gate`, and `parity-check` execute fully on the speculative merge tree.
     - `ci-required-result` aggregates green.
     - `Results Explorer browser gate` reports success.
     - `ruleset-drift` reports green.
  4. Verify atomic squash merge completes.

### Scenario 3: Soundness PR Negative Control (Review Withholding)
- **Action:** Open PR modifying a soundness-critical path (e.g. `benchbox/core/expected_results/` or `_project/scripts/auto_merge_soundness_paths.py`).
- **Execution:**
  1. Attempt to open with auto-merge: `make pr-open READY=1`
  2. Assert that `make pr-arm-auto-merge` prints: `Soundness-critical paths changed; leaving auto-merge disabled pending review.`
  3. Verify on GitHub that `autoMergeRequest` is `null` (auto-merge withheld).
  4. If manually armed via API, verify `.github/workflows/auto-merge-on-open.yml` immediately executes and revokes auto-merge.
  5. Confirm PR **does not enter the merge queue** without maintainer CODEOWNERS review and explicit manual enqueue.

---

## 3. Operator Verification Checklist

| Check | Expected Outcome | Command / Check Method |
|---|---|---|
| 1. Workflow YAML Validity | Pass with zero syntax errors | `python -c "import yaml; [yaml.safe_load(open(f)) for f in ['.github/workflows/pr.yml', '.github/workflows/results-explorer-browser.yml', '.github/workflows/develop-ruleset-drift.yml']]"` |
| 2. Unit Tests Passing | All workflow tests green | `uv run -- python -m pytest tests/unit/workflows/ -q` |
| 3. Soundness Tests Passing | All 38 soundness tests green | `uv run -- python -m pytest tests/unit/test_auto_merge_soundness_paths.py -q` |
| 4. Status Check Match | Exact required check names match ruleset | `rg -n 'ci-required-result|Results Explorer browser gate|ruleset-drift' .github/workflows/` |
| 5. Trusted Base Drift | Checkout uses `merge_group.base_sha` | `rg -n 'merge_group.base_sha' .github/workflows/develop-ruleset-drift.yml` |

---

## 4. Rollback Readiness

If any failure occurs during canary rehearsal or rollout:
1. Disable `merge_queue` on the target ruleset.
2. Confirm standard `develop-squash-only` ruleset is restored.
3. Validate with `python scripts/ruleset_drift_check.py --ruleset develop-squash-only`.
