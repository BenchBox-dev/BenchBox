# BenchBox Development Loop v2 — Baseline Metrics

Captured: 2026-09-28
Repository SHA: `64f2f1f603083fc3f6b9c3b13d12ce73f97e6fd3` (`origin/develop`)

## 1. Summary Metrics

| Metric | Baseline Value | Measurement Command |
|---|---|---|
| Active GitHub Actions workflows | 46 files | `find .github/workflows -maxdepth 1 -name "*.yml" \| wc -l` |
| Workflow total lines of code | 15,540 lines | `wc -l .github/workflows/*.yml \| tail -n 1` |
| Makefile root lines of code | 2,050 lines | `wc -l Makefile` |
| Makefile included modules LOC (`make/*.mk`) | 629 lines | `wc -l make/*.mk \| tail -n 1` |
| Makefile declared targets | 216 targets | `jq '(.targets // {}) \| length' make/inventory.json` |
| Makefile phony targets | 162 targets | `jq '(.phony_targets // []) \| length' make/inventory.json` |
| Tracked process test files | 181 files | `git ls-files tests/unit/workflows tests/unit/scripts tests/unit/release tests/unit/test_auto_merge_* tests/unit/test_release_* \| wc -l` |
| Tracked automation scripts | 188 files | `git ls-files scripts _project/scripts \| wc -l` |
| Pre-commit hooks | 23 hooks | Parsed from `.pre-commit-config.yaml` |
| Local fast test tier (T1 local) | ~2 min 18 s | `make pr-preflight-fast-tests` (32,208 passed in 138 s across 5 workers) |
| Merge-queue test tier (T2 local) | ~12 min | Component sum: unit 252s + integration 228s + slow 80s + matrix_sql 75s + matrix_df 32s + gate 25s + smoke 13s + build 7s |
| Median PR open->merge wall time | 14,205 s (~3.95 h) | `uv run -- python _project/scripts/dev_loop_pr_metrics.py --days 30` (pinned in `pr-metrics-snapshot.json`, 401 merged PRs) |
| Median pushes after open | 1 push | `uv run -- python _project/scripts/dev_loop_pr_metrics.py --days 30` |
| First-pass required-lane green rate | 70.4% (n=399) | `uv run -- python _project/scripts/dev_loop_pr_metrics.py --days 30` |
| Fast-test CI job seconds (avg / p95) | 1,108 s / 1,458 s | `uv run -- python _project/scripts/dev_loop_pr_metrics.py --days 30` (18.5 min avg / 24.3 min p95) |
| Medium-test CI job seconds (avg / p95) | 1,257 s / 1,761 s | `uv run -- python _project/scripts/dev_loop_pr_metrics.py --days 30` (21.0 min avg / 29.4 min p95) |
| Fast test lane policy touch rate | 2.0% (8 / 401 PRs) | `uv run -- python _project/scripts/dev_loop_pr_metrics.py --days 30` |
| Develop-red incidents (last 30 days) | 0 incidents | Monitored via merge queue failures and incident labels |
| Open remote branches | 97 branches | `gh api repos/BenchBox-dev/BenchBox/branches --paginate --jq '.[].name' \| wc -l` |
| Configured labels | 15 labels | `gh api repos/BenchBox-dev/BenchBox/labels --paginate --jq '.[].name' \| wc -l` |
| Configured environments | 4 environments | `gh api repos/BenchBox-dev/BenchBox/environments` (`github-pages`, `publication-attestation`, `pypi`, `test-pypi`) |
| Configured repository secrets | 7 secrets | `gh secret list --repo BenchBox-dev/BenchBox` (names only: `CODECOV_TOKEN`, `PUBLICATION_APP_ID`, `PUBLICATION_APP_PRIVATE_KEY`, `RULESET_DRIFT_TOKEN`, `TODO_DB_RO_AUTH_TOKEN`, `TODO_DB_URL`, `TODO_EXPORT_PR_TOKEN`) |

> Note: The 30-day cohort metrics and per-PR evaluation records are preserved in `pr-metrics-snapshot.json` (`backup-metadata.json`), capturing the fixed trailing window ending at `2026-09-28T11:45:00-04:00` against develop SHA `64f2f1f603083fc3f6b9c3b13d12ce73f97e6fd3`.

## 2. Directory Breakdown of Tracked Process Files

| Directory | Tracked Files | Scope / Classification |
|---|---|---|
| `.github/workflows` | 46 | Workflow definitions (PR gates, post-merge, publication, scheduled) |
| `tests/unit/workflows` | 47 | Unit tests verifying workflow syntax and execution contracts |
| `tests/unit/scripts` | 124 | Unit tests verifying dev-loop scripts |
| `tests/unit/release` | 4 | Tests for legacy release cut and validation |
| `tests/unit/test_auto_merge_*` | 2 | Auto-merge predicate and soundness hold tests |
| `tests/unit/test_release_*` | 4 | Release infrastructure tests |
| `scripts` | 110 | Repository scripts (PR lifecycle, publication, verification) |
| `_project/scripts` | 78 | Internal project scripts (metrics, audits, fixtures) |
| **Total Process Files** | **415** | Subject to safety property ledger classification |

## 3. GitHub Rulesets Baseline

1. `develop-squash-only` (ID 15611785):
   - Target: `refs/heads/develop`
   - Merge Queue: enabled (ALLGREEN, max_entries_to_build 5, max_entries_to_merge 5, min 1, timeout 60 min)
   - Required checks: `ci-required-result`, `Results Explorer browser gate`, `ruleset-drift`, `Public-site visual acceptance`
   - Code-owner review: required (approvals 0)

2. `release-only` (ID 19149459):
   - Target: `refs/heads/release`
   - Required checks: `validate-base`, `release-required-result`

3. `v-release-branches-minimal` (ID 15611787):
   - Target: `refs/heads/v*`
   - Non-fast-forward: blocked

4. `v-tag-restricted` (ID 18774756):
   - Target: `refs/tags/v*`
   - Creation: restricted
