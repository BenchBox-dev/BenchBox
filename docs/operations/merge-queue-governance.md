# Merge and trunk governance

This document defines how a change reaches `refs/heads/develop` and how `develop` is kept green afterwards: the required checks, the review requirement for result-affecting changes, auto-merge, the post-merge `trunk.yml` run, the revert-first policy and the nightly run. The repository does not use a GitHub merge queue or the strict up-to-date rule; the file keeps its original name so existing links work. The decision and its evidence are in `_project/decisions/merge-queue-retirement-2026-10-03.md`.

---

## 1. Governance Invariants

1. **Squash Integration Only:** All pull requests targeting `develop` must be integrated via squash merge. Merge commits and rebase-and-merge remain forbidden.
2. **Zero Bypass Actors:** The `develop-squash-only` ruleset enforces `bypass_actors: []`. No user, bot, or organization admin may bypass status checks, linear history or required thread resolution through that ruleset. Code-owner review is disabled.
3. **Soundness Review Boundary:** A result-affecting pull request (a path in `.github/soundness-paths.txt`) needs a completed external adversarial review of its current head. The required `oracle-review` check passes only when the Codex connector app has reviewed that head. The reviewer's Critical and High findings are posted as PR review threads, and required thread resolution makes them binding. A scheduled digest lists the soundness-path commits that merged and the review signal each had, and opens a tracker item for any with none. There is no attestation in the PR body: the author of a change can write that text, so it cannot bind, and the `soundness-flag` check that tested for it is deleted.
4. **Fail-Closed Execution:** A required check that cannot establish its result must report failure, not success.

---

## 2. Required Status Checks Contract

Seven status checks are required on `develop`: six always-reporting unit jobs in `.github/workflows/ci.yml`, and `oracle-review`. `.github/ci-units.yml` maps changed paths to units, an untouched unit reports success, and a touched unit succeeds only when every job it requires succeeded (a skipped required job fails the unit). The checks run on the pull request head. The strict up-to-date rule is off, so a pull request does not need to be current with `develop` to merge.

| Required Context | Workflow Path | Contract |
| --- | --- | --- |
| `core` | `.github/workflows/ci.yml` | Lint, type checks, fast tests, and parity gates for the pull request head. The heavy tier (medium-test, correctness-gate, required-local-cases, plan-capture-gate, DataFusion integration, and the macOS and Windows TPC-H binary-framing matrix) is skipped on `pull_request` unless a carve-out applies (soundness paths, packaging paths); `trunk.yml` runs the medium tier, the correctness gate and `required-local-cases` on `develop` after each merge. |
| `explorer` | `.github/workflows/ci.yml` | Token scan, Vitest, CLI-versus-explorer parity, and the blocking Chromium suite on explorer changes. Reports success on unaffected paths. |
| `results-data` | `.github/workflows/ci.yml` | Corpus inventory and validation, submission validator sync, and corpus contract tests on results-data changes. |
| `docs` | `.github/workflows/ci.yml` | Sphinx build with warnings as errors, example validation, and spell check on docs changes. |
| `landing` | `.github/workflows/ci.yml` | Site theme token scan on landing changes. |
| `tooling` | `.github/workflows/ci.yml` | Every event. Content guard, skill integrity, and audit checks by path. |
| `oracle-review` | `.github/workflows/oracle-review.yml` (job and check name `oracle-review`) | Passes when no soundness path changes, or when the Codex connector app has reviewed the current head and none of its threads is unresolved. A new push needs a new review. If no reviewer can run (all four tried on the head with recorded quota or unavailability evidence, and four hours without a connector signal), the owner reviews the exact head and follows the one-merge recovery window in the dev-loop ADR, D4. An owner comment does not satisfy the check, because every human and agent posts as the owner account. |

The public-site visual comparison runs only when a render input changed. It compares against the exact protected base SHA, captured by `.github/workflows/docs.yml` on every push to `develop`. The comparison is advisory until the public site is in production: the job still runs and uploads its report, but a difference or a missing baseline does not block a merge. It becomes a required check again when the site is in production.

---

## 3. Merge Path

A pull request is armed with `make pr-arm`, which enables auto-merge for the exact head. GitHub merges the pull request with a squash commit once every required check is green on that head and all review threads are resolved. There is no queue and no combined-tree build before the merge. Because the strict up-to-date rule is off, a branch behind `develop` merges without a refresh unless it conflicts. A changed head needs fresh CI and connector review before re-arming.

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

1. Withdraw readiness before editing an armed PR (`make pr-landing-withdraw PR=<n> HEAD=<sha>`). After the last push, obtain CI and the connector's review or thumbs-up on that exact head before arming with `make pr-arm`. The `auto-merge-on-open.yml` workflow retains label-based revocation for `no-auto-merge`; it no longer revokes based on soundness paths.
2. The required `oracle-review` check must pass on the current head before the pull request can merge.
3. A soundness-path pull request that sits green and unarmed is reported by the soundness-drain digest (`make soundness-drain-report`, see `docs/operations/soundness-drain.md`), not by the nightly green-unmerged sweep, which skips soundness-gated pull requests.

---

## 5. Trunk Run and Revert

`.github/workflows/trunk.yml` runs on pushes to `develop`: the fast lane, the four-shard medium tier, the correctness gate, and the `required-local-cases` job (`make test-required-local-cases`, which fails the run if a required local-engine case skips). The `dist-artifact` job builds and verifies the release wheel and sdist. The test-count ceiling is retired; marker and forbidden-path guards remain. This workflow tests `develop` in its merged state and is not a required PR check.

Runs use `concurrency.queue: max` with running work retained, so later pushes do not replace earlier pending runs. Results can lag during a burst of merges. This protects queued runs for delivered events, not push-event delivery itself. Release admission requires the latest exact-commit trunk `push` run on `develop` to succeed and have a matching artifact attempt; it never falls back to an older success. See [the release artifact contract](release-artifacts.md).

When a trunk run fails, the culprit is reverted first and fixed afterwards:

```bash
# Open the revert of a merged pull request
make trunk-revert PR=<number>
```

`make pr-open` refuses a branch that is not a revert when the newest completed `trunk.yml` run on `develop` failed more than 30 minutes ago (`scripts/trunk_revert.py gate`), so nothing new stacks on a broken tip. That rule is enforced. A trunk that stays red for more than two hours with no revert pull request open is a risk signal for the owner, who should revert the culprit; nothing enforces the two-hour figure.

More than one medium-tier shard kill a day means the shard's memory sampler output should be read for the test that is growing a worker.

If a trunk failure is traced to a pull request that was green on an older base more than about once a week, the owner should consider reinstating the strict up-to-date rule and its refresh cost.

---

## 6. Post-Merge Soundness Digest

`.github/workflows/soundness-merge-digest.yml` runs daily and on demand. It runs `_project/scripts/soundness_merge_digest.py`, which reads the first-parent commits on `develop` since a stored checkpoint and keeps those that change a path on `.github/soundness-paths.txt`, counting both sides of a rename. Each commit is judged by the manifest and predicate (`_project/scripts/soundness_paths.py`) as they stood at its first parent, so a later commit that removes a rule cannot hide an earlier change, and a commit that removes a rule cannot hide its own. The manifest, the predicate, the digest script and the digest workflow are always kept, whatever the manifest says. The digest script and workflow are also listed in the manifest. For each one it finds the pull request that merged into `develop` as that commit and records which review signal the pull request had at merge, for its final content:

- the Codex connector's submitted review of the last content commit, or of a merge that only refreshed the base after it;
- the connector's thumbs-up reaction, or
- an external review posted as a PR comment that names its reviewer (`Reviewer: codex`, `muse` or `agy`).

The reaction and the comment must come after the last content commit and before the merge. The digest dates that commit by when GitHub first ran this pull request's workflows for it, because commit dates are set by the author. When that commit has no run (for example it was pushed with `[skip ci]`, or its runs expired), the digest uses the first run of a later commit, and when there is none, the merge time. Each fallback makes the date later, so it can report a gap that was not one and cannot hide a real gap. A review submitted after the merge, or still pending, does not count.

A merge of `develop` into the branch is a refresh, not content, when it has two parents, one of them already on `develop`, and its tree equals what merging the parents mechanically produces. A merge that needed conflict resolution, carries any other change, merges two branches that are not on `develop`, or has more than two parents counts as content. An "eyes" reaction is not a signal.

The connector review names a commit, so it cannot be backdated. A posted review is text the author can write, so it shows that a review was recorded, not what it examined. A run that lists no pull request is matched to one by repository and branch name, so an author who reuses a branch name across pull requests, shares a commit between them and pushes the final content with `[skip ci]` can make the date earlier than it was. That needs deliberate set-up of the same kind as posting a review comment that was never written, and the digest does not defend against it.

A commit gets an issue labelled `soundness-review-gap` when it has no signal, no merged pull request, or a reviewer thread that was resolved with no commit after it. An agent runs the external review and either records a clean result on the issue or opens a fix or revert pull request.

The checkpoint is stored in the body of the one issue labelled `soundness-merge-digest`, and it must be on the first-parent history of `develop`. A missing issue, a second issue with the label, a body without the checkpoint marker, or a checkpoint off that history fails the run, so a damaged checkpoint cannot silently skip commits. Record the first checkpoint by dispatching the workflow with `bootstrap` set; the run reports nothing and later runs report the commits after it. Restore a damaged checkpoint with `--since <sha> --apply`. A read that fails or comes back incomplete also fails the run and leaves the checkpoint where it was.

Run it locally without changing anything: `uv run -- python _project/scripts/soundness_merge_digest.py --since <sha>`.

---

## 7. Nightly Run

`.github/workflows/nightly.yml` runs once a day (06:00 UTC) and on dispatch. It runs the slow and scheduled checks that no required check covers, plus the advisory ruleset drift check, which no longer runs in `ci.yml` (it ran only in merge groups) and is also run by hand after a settings change. A nightly failure never blocks a merge.

---

## 8. Historical: the Merge Queue

Until 2026-10-03 the repository ran a GitHub merge queue on `develop` with the strict up-to-date rule. The queue's configuration, the follower visual baseline policy and the queue canary rehearsal are kept in `_project/decisions/native-merge-queue-activation-20260822.md`, `_project/decisions/visual-baseline-site-equivalent-ancestor-2026-09-27.md` and `docs/operations/merge-queue-canary-runbook.md`. They no longer apply.
