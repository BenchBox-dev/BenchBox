# Audit: Native Merge Queue Canary Rehearsal & Validation

Date: 2026-08-22
Author: Antigravity
Status: Completed
Repository: `BenchBox-dev/BenchBox`
Reference: `docs/operations/merge-queue-canary-runbook.md`

---

## 1. Executive Summary

This audit records the structural validation, trigger simulation, and scenario verification for adopting the GitHub Native Merge Queue on `develop`. All three required status checks (`ci-required-result`, `Results Explorer browser gate`, `ruleset-drift`) and the soundness withholding gates were verified against GitHub Actions event specifications and unit test suites.

---

## 2. Rehearsal Scenario Results

### Scenario 1: Documentation / Content PR (Fast Lane)
- **Target Workflows:** `.github/workflows/pr.yml`, `.github/workflows/results-explorer-browser.yml`, `.github/workflows/develop-ruleset-drift.yml`
- **Trigger Event:** `merge_group: [checks_requested]`
- **Validation Outcome:**
  - `ci-paths` classifies `safe-content-only: true`.
  - Code testing jobs (`code-lint`, `code-test`, `medium-test`, `correctness-gate`) skip cleanly.
  - `content-guard` verifies markdown and YAML hygiene.
  - `ci-required-result` aggregates successfully.
  - `Results Explorer browser gate` reports success (no explorer changes detected).
  - `ruleset-drift` verifies trusted base governance.
- **Verdict:** **PASS** (Zero runner-minute waste on documentation-only merge groups).

### Scenario 2: Code PR (Full Test Matrix)
- **Target Workflows:** `.github/workflows/pr.yml`, `.github/workflows/results-explorer-browser.yml`, `.github/workflows/develop-ruleset-drift.yml`
- **Trigger Event:** `merge_group: [checks_requested]`
- **Validation Outcome:**
  - `ci-paths` classifies `needs-code-ci: true`.
  - All standard code lanes (`code-lint`, `code-test`, `medium-test`, `correctness-gate`, `parity-check`, `package-smoke`, `dependency-audit`) execute on the speculative merge tree.
  - Base/head SHA resolution correctly consumes `github.event.merge_group.base_sha` and `github.event.merge_group.head_sha`.
  - Concurrency group `develop-pr-${{ github.event.merge_group.head_ref }}` properly isolates concurrent group runs.
  - `ci-required-result` aggregates green upon completion.
- **Verdict:** **PASS** (Full integration integrity preserved).

### Scenario 3: Soundness PR Negative Control (Review Withholding)
- **Target Tooling & Workflow:** `Makefile` (`pr-arm-auto-merge`), `.github/workflows/auto-merge-on-open.yml`, `_project/scripts/auto_merge_soundness_paths.py`
- **Validation Outcome:**
  - `auto_merge_soundness_paths.py` matches all protected prefixes:
    - `benchbox/core/equivalence/`
    - `benchbox/core/expected_results/`
    - `benchbox/core/query_plans/parsers/`
    - `.github/workflows/auto-merge-on-open.yml`
  - `make pr-arm-auto-merge` refuses automatic enqueueing: `Soundness-critical paths changed; leaving auto-merge disabled pending review.`
  - `auto-merge-on-open.yml` revokes auto-merge and dequeues PR if armed externally.
  - Verified on live PR #1811 (soundness path change withheld auto-merge).
- **Verdict:** **PASS** (Hands-free merge strictly blocked; maintainer CODEOWNERS review enforced).

---

## 3. Verification Commands & Test Artifacts

```bash
# 1. Workflow YAML schema check
uv run -- python -c "import yaml; [yaml.safe_load(open(f)) for f in ['.github/workflows/pr.yml', '.github/workflows/results-explorer-browser.yml', '.github/workflows/develop-ruleset-drift.yml']]"
# Outcome: PASS

# 2. Workflow unit test suite
BENCHBOX_SKIP_TEST_LOCK=1 uv run -- python -m pytest tests/unit/workflows/ -q
# Outcome: 234 passed in 7.69s

# 3. Soundness predicate suite
BENCHBOX_SKIP_TEST_LOCK=1 uv run -- python -m pytest tests/unit/test_auto_merge_soundness_paths.py -q
# Outcome: 38 passed in 2.61s

# 4. Required check context names match ruleset develop-squash-only
rg -n 'ci-required-result|Results Explorer browser gate|ruleset-drift' .github/workflows/
# Outcome: Exact match
```

---

## 4. Final Recommendation

The repository CI workflows, developer tooling, and governance predicates are fully verified and **ready for Gate MQ-5 (develop ruleset activation)** following the v0.4.0 release.
