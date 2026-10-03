# Merge and trunk governance

This document defines how a change reaches `refs/heads/develop` and how `develop` is kept green afterwards: the required checks, the review requirement for result-affecting changes, auto-merge, the post-merge `trunk.yml` run, the revert-first policy and the nightly run. The repository does not use a GitHub merge queue or the strict up-to-date rule; the file keeps its original name so existing links work. The decision and its evidence are in `_project/decisions/merge-queue-retirement-2026-10-03.md`.

---

## 1. Governance Invariants

1. **Squash Integration Only:** All pull requests targeting `develop` must be integrated via squash merge. Merge commits and rebase-and-merge remain forbidden.
2. **Zero Bypass Actors:** The `develop-squash-only` ruleset enforces `bypass_actors: []`. No user, bot, or organization admin may bypass status checks, linear history, or code owner review.
3. **Soundness Review Boundary:** A result-affecting pull request (a path in `.github/soundness-paths.txt`) needs a completed external adversarial review of its current head. The required `oracle-review` check passes only when the Codex connector app has reviewed that head. The reviewer's Critical and High findings are posted as PR review threads, and required thread resolution makes them binding. A scheduled digest lists the soundness-path commits that merged and the review signal each had, and opens a tracker item for any with none. There is no attestation in the PR body: the author of a change can write that text, so it cannot bind, and the `soundness-flag` check that tested for it is deleted.
4. **Fail-Closed Execution:** A required check that cannot establish its result must report failure, not success.

---

## 2. Required Status Checks Contract

Seven status checks are required on `develop`: six always-reporting unit jobs in `.github/workflows/ci.yml`, and `oracle-review`. `.github/ci-units.yml` maps changed paths to units, an untouched unit reports success, and a touched unit succeeds only when every job it requires succeeded (a skipped required job fails the unit). The checks run on the pull request head. The strict up-to-date rule is off, so a pull request does not need to be current with `develop` to merge.

| Required Context | Workflow Path | Contract |
|---|---|---|
| `core` | `.github/workflows/ci.yml` | Lint, type checks, fast tests, and parity gates for the pull request head. The heavy tier (medium-test, correctness-gate, required-local-cases, plan-capture-gate, DataFusion integration, and the macOS and Windows TPC-H binary-framing matrix) is skipped on `pull_request` unless a carve-out applies (soundness paths, packaging paths); `trunk.yml` runs the medium tier, the correctness gate and `required-local-cases` on `develop` after each merge. |
| `explorer` | `.github/workflows/ci.yml` | Token scan, Vitest, CLI-versus-explorer parity, and the blocking Chromium suite on explorer changes. Reports success on unaffected paths. |
| `results-data` | `.github/workflows/ci.yml` | Corpus inventory and validation, submission validator sync, and corpus contract tests on results-data changes. |
| `docs` | `.github/workflows/ci.yml` | Sphinx build with warnings as errors, example validation, and spell check on docs changes. |
| `landing` | `.github/workflows/ci.yml` | Site theme token scan on landing changes. |
| `tooling` | `.github/workflows/ci.yml` | Every event. Content guard, skill integrity, and audit checks by path. |
| `oracle-review` | `.github/workflows/oracle-review.yml` (job and check name `oracle-review`) | Passes only when the Codex connector app has reviewed the current head of a result-affecting pull request. A new push changes the head, so it needs a new review. Pending for more than four hours means the connector is down. The owner, not an agent, then reviews the change in their own session and either re-requests the connector review or merges through the GitHub UI after temporarily removing `oracle-review` from the required checks, restoring it afterwards. An owner comment does not satisfy the check, because every human and agent posts as the owner account. |

The public-site visual comparison runs only when a render input changed. It compares against the exact protected base SHA, captured by `.github/workflows/docs.yml` on every push to `develop`. The comparison is advisory until the public site is in production: the job still runs and uploads its report, but a difference or a missing baseline does not block a merge. It becomes a required check again when the site is in production.

---

## 3. Merge Path

A pull request is armed with `make pr-arm`, which enables auto-merge for the exact head. GitHub merges the pull request with a squash commit as soon as every required check is green on that head. There is no queue and no combined-tree build before the merge. Because the strict up-to-date rule is off, a branch behind `develop` merges without a refresh unless it conflicts.

Slow-marked reproducer jobs remain required PR CI through the `core` unit, because the post-merge run has no slow-signature lane.

---

## 4. Developer Workflow

### A. Submitting & Arming a PR

Developers submit and arm PRs through repository standard Makefile targets:

```bash
# Open PR against develop
make pr-open

# When PR is ready for merge, run the exact readiness transaction and arm
make pr-ready PR=<number> HEAD=$(git rev-parse HEAD) EVIDENCE=<readiness.json>
```

- `make pr-open` opens or reuses the pull request. It refuses a branch that is not a revert when the newest completed `trunk.yml` run on `develop` failed more than 30 minutes ago (see section 5).
- `make pr-ready` verifies the exact checkout, live PR identity, review state, required checks, holds, and readiness evidence before arming auto-merge.
- Once the required checks are green on the head, GitHub merges the pull request.

### B. Soundness Path Withholding

If a PR modifies any soundness path (e.g. `benchbox/core/equivalence/`, `benchbox/core/expected_results/`, `auto_merge_soundness_paths.py`):
1. The `auto-merge-on-open.yml` workflow revokes auto-merge on every push, so arm the pull request with `make pr-arm` after its last push.
2. The required `oracle-review` check must pass on the current head before the pull request can merge.
3. A soundness-path pull request that sits green and unarmed is reported by the soundness-drain digest (`make soundness-drain-report`, see `docs/operations/soundness-drain.md`), not by the nightly green-unmerged sweep, which skips soundness-gated pull requests.

---

## 5. Trunk Run and Revert

`.github/workflows/trunk.yml` runs on every push to `develop`: the fast lane (with its ungraced ceiling), the four-shard medium tier, the correctness gate, and the `required-local-cases` job (`make test-required-local-cases`, which fails the run if a required local-engine case skips). It is the test of `develop` in its merged state. Runs queue behind each other and one pending run is kept, so busy hours batch. It is not a required check.

When a trunk run fails, the culprit is reverted first and fixed afterwards:

```bash
# Open the revert of a merged pull request
make trunk-revert PR=<number>
```

`make pr-open` refuses a branch that is not a revert when the newest completed `trunk.yml` run on `develop` failed more than 30 minutes ago (`scripts/trunk_revert.py gate`), so nothing new stacks on a broken tip. That rule is enforced. A trunk that stays red for more than two hours with no revert pull request open is a risk signal for the owner, who should revert the culprit; nothing enforces the two-hour figure.

More than one medium-tier shard kill a day means the shard's memory sampler output should be read for the test that is growing a worker.

If a trunk failure is traced to a pull request that was green on an older base, more than about once a week, turn the strict up-to-date rule back on for result-affecting paths only.

---

## 6. Nightly Run

`.github/workflows/nightly.yml` runs once a day (06:00 UTC) and on dispatch. It runs the slow and scheduled checks that no required check covers, plus the advisory ruleset drift check, which no longer runs in `ci.yml` (it ran only in merge groups) and is also run by hand after a settings change. A nightly failure never blocks a merge.

---

## 7. Historical: the Merge Queue

Until 2026-10-03 the repository ran a GitHub merge queue on `develop` with the strict up-to-date rule. The queue's configuration, the follower visual baseline policy and the queue canary rehearsal are kept in `_project/decisions/native-merge-queue-activation-20260822.md`, `_project/decisions/visual-baseline-site-equivalent-ancestor-2026-09-27.md` and `docs/operations/merge-queue-canary-runbook.md`. They no longer apply.
