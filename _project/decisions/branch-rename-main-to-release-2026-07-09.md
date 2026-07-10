# Decision: rename the release branch `main` → `release` (Decision B)

Date: 2026-07-09
Status: In progress (in-repo rename landed via PR; admin branch-rename + ruleset
recreate are the maintainer's follow-up — see
`docs/operations/branch-rename-runbook.md`).

## Context

The branching-strategy review (session on PR #993) split into two decisions:

- **Decision A** — make `develop` the GitHub default branch. Done 2026-07-08
  (`_project/DONE/main/branch-default-switch-to-develop.yaml`); it also
  activated the previously-dark scheduled workflows (release-canary etc.), which
  fire from the default branch.
- **Decision B** — rename the release-only branch `main` → `release`, this
  record.

`main` was never the "primary" branch: `validate-*-pr.yml` rejects any PR whose
head is not a `vX.Y.Z` branch, `release-finalize` fast-forwards and tags it, and
its HEAD is always the latest-release commit. `release` is the accurate name.

## Decision

Rename the branch and every in-repo reference to it, in one PR, then perform the
GitHub-side branch rename + ruleset recreate as a coordinated admin step.

### Two ref classes — do not conflate

The rename surfaced that repo `main` references fall into two meanings:

- **Release-branch refs** → `release`: workflow triggers (lint/test/perf-smoke/
  docs/results-explorer-browser), `test.yml` `base_ref` release-gating
  conditionals, `release.yml`'s `verify-tag-on-main` publish gate (job +
  `refs/heads/main` ancestor check), the Makefile release targets (`--base`,
  `origin/main` merge-ours + changelog boundary, `checkout`/`pull`, guards), the
  `main-release-only` ruleset name, and the ops docs.
- **Default-branch refs** → `develop` (a Decision-A consequence, NOT `release`):
  `RELEASE_CANARY_BRANCH` (the canary now fires from `develop`, so its runs carry
  `head_branch=develop`) in `validate-release-pr.yml` and
  `release_readiness_check.py`; and the `nightly.yml` scheduled-workflow-liveness
  comment. Mechanically renaming these to `release` would be a soundness bug.

### Verified safe / unchanged

- **PyPI trusted publishing** is branch-independent (keyed on repo + workflow
  filename `release.yml` + environment `pypi`, never a branch).
- **GitHub Pages** deploys via `deploy-pages` (source = GitHub Actions), only the
  `refs/heads/release` deploy gate changes.
- The `validate-base` required-check *context name* is unchanged (only the
  workflow *file* is renamed `validate-main-pr.yml` → `validate-release-pr.yml`),
  so branch-protection required checks keep resolving.

## Consequences

- The `release-cut` / `release-finalize` flow now targets `release`. The
  `-s ours --allow-unrelated-histories` alignment merge uses `origin/release`
  (same unrelated-root history, preserved by the GitHub rename).
- `ruleset_drift_check.py` now parses the `release-only` ruleset from
  `repo-admin-settings.md`; the doc, script, and their tests moved in lockstep.
- Admin follow-up (maintainer-only, no admin scope in CI): rename the branch and
  recreate the ruleset as `release-only` on `refs/heads/release`. Runbook:
  `docs/operations/branch-rename-runbook.md`.
