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

The merge queue creates temporary merge group refs (`refs/heads/gh-readonly-queue/develop/...`) and dispatches GitHub Actions runs under the `merge_group: [checks_requested]` event. Exactly six status checks are required on `develop`. Each is one always-reporting unit job in `.github/workflows/ci.yml`; `.github/ci-units.yml` maps changed paths to units, an untouched unit reports success, and a touched unit succeeds only when every job it requires succeeded (a skipped required job fails the unit).

| Required Context | Workflow Path | Trigger Events | Contract on `merge_group` |
|---|---|---|---|
| `core` | `.github/workflows/ci.yml` | `pull_request`, `merge_group` | Lint, type checks, fast tests, and parity gates for the speculative tree. The heavy tier (medium-test, correctness-gate, plan-capture-gate, DataFusion integration, and the macOS and Windows TPC-H binary-framing matrix) runs on `merge_group` for every code-routed tree; `pull_request` runs skip it unless a carve-out applies (soundness paths, packaging paths). The unit models the skip explicitly (success when required, skipped when deferred). |
| `explorer` | `.github/workflows/ci.yml` | `pull_request`, `merge_group` | Token scan, Vitest, CLI-versus-explorer parity, the blocking Chromium suite, and the public-site visual comparison on explorer changes. Reports success on unaffected paths. |
| `results-data` | `.github/workflows/ci.yml` | `pull_request`, `merge_group` | Corpus inventory and validation, submission validator sync, and corpus contract tests on results-data changes. |
| `docs` | `.github/workflows/ci.yml` | `pull_request`, `merge_group` | Sphinx build with warnings as errors, example validation, spell check, docstring coverage, and the visual comparison on docs changes. |
| `landing` | `.github/workflows/ci.yml` | `pull_request`, `merge_group` | Site theme token scan and the visual comparison on landing changes. |
| `tooling` | `.github/workflows/ci.yml` | `pull_request`, `merge_group` | Every event. Validates soundness review evidence from the immutable base revision and fails closed for malformed or missing review attestations. Also runs the base-branch guard, content guard, skill integrity, audit checks by path, and, in the merge queue, ruleset drift from the trusted base checkout. |

The public-site visual comparison runs only when a render input changed. It compares against the exact protected base SHA and fails closed when that baseline is absent (see the follower policy below). The baseline is captured by `.github/workflows/docs.yml` on every push to `develop`.

### Merge-queue follower visual baseline policy

A queue follower's `merge_group.base_sha` is the head of the group ahead of it. The follower can merge only after that group merges as exactly that commit, so a capture of that head is the exact-base baseline. When the leader group's comparison passes, its visual job uploads `public-site-visual-baseline-<merge_group.head_sha>`. It accepts either a protected `develop` artifact (preferred, produced by a Documentation `push` or `workflow_dispatch` run on `develop`) or a candidate from a `merge_group` run of the CI workflow (`.github/workflows/ci.yml`, which validates queue groups and uploads the candidate) on this repository's `gh-readonly-queue/develop/*` branch at that SHA. A leader whose CI run has not finished is trusted once every job named `Public-site visual regression` in it has succeeded (the job list is read page by page, because the run has more jobs than one default page holds), since that job gates the candidate upload and the run's other jobs can last far longer than a follower waits. A leader that finished without succeeding is never trusted, and a job list that cannot be read in full (a failed request, a malformed entry, or more jobs than the page bound) is not evidence of success. If the leader fails, the queue rebuilds the follower on a new base and the old run is discarded, so a candidate for a head that never lands never certifies a merge. A test (`test_the_lookup_trusts_every_workflow_that_publishes_a_merge_queue_candidate`) keeps the workflows that upload candidates and the lookup's trusted list in step. The lookup establishes which workflow run produced an artifact and that the producing job succeeded; it does not authenticate what that workflow did. Trusting `ci.yml` as a producer therefore rests on the review controls for that workflow (code-owner and soundness-path review), the same boundary that already applied to the Documentation workflow.

When the group ahead changed no public-site inputs, its visual job is skipped and publishes nothing. The classifier therefore also lists site-equivalent ancestors: first-parent ancestors of the base whose public-site inputs are byte-identical to the base, stopping at the first one that differs. They render the same site as the base, which is the same premise that lets an unchanged tree skip the gate, so their baseline is the base's baseline. The lookup tries the exact base first, then each ancestor nearest first, and the compare step checks the downloaded manifest against the SHA actually used. A merge-group follower waits at most 10 minutes, because the wait holds a runner; when it ends without a baseline, the follower fails closed with the same recovery message as before.

A develop ancestor whose site inputs differ from the base is never used: it would compare against a tree that renders differently from the one the follower merges onto. Rationale and measurements are in `_project/decisions/visual-baseline-site-equivalent-ancestor-2026-09-27.md`.

Operator flow when a follower still fails at the download step: after the leader merges, confirm `public-site-visual-baseline-<develop head>` exists, or dispatch Documentation on develop with `baseline_source_sha`, then re-queue at the back (`jump:false`).

---

## 3. Queue Configuration Parameters

The operator configures the merge queue within the `develop-squash-only` ruleset using the following verified parameters:

```json
{
  "type": "merge_queue",
  "parameters": {
    "merge_method": "SQUASH",
    "min_entries_to_merge": 1,
    "max_entries_to_merge": 3,
    "grouping_strategy": "ALLGREEN",
    "check_response_timeout_minutes": 60,
    "max_entries_to_build": 2,
    "min_entries_to_merge_wait_minutes": 0
  }
}
```

- **`merge_method: SQUASH`**: Guarantees atomic, single-commit integration.
- **`grouping_strategy: ALLGREEN`**: Groups only entries whose required checks are green.
- **`check_response_timeout_minutes: 60`**: Provides the live queue timeout while preventing hung runners from stalling the queue.
- **`max_entries_to_build: 2`** and **`max_entries_to_merge: 3`**: Bound speculative builds at two entries and queue merges at three. Five parallel groups saturated the organization runner allowance and were ejected with `checks_timed_out`.
- **`min_entries_to_merge: 1`** and **`min_entries_to_merge_wait_minutes: 0`**: Permit immediate single-entry merges without an artificial wait.

Slow-marked reproducer jobs remain required PR CI through the `core` unit.
There is no post-merge lane, so these reproducers must remain in the required
PR lane.

---

## 4. Developer Workflow

### A. Submitting & Arming a PR

Developers submit and arm PRs through repository standard Makefile targets:

```bash
# Open PR against develop with currency check
make pr-open

# When PR is ready for merge, run the exact readiness transaction and arm
make pr-ready PR=<number> HEAD=$(git rev-parse HEAD) EVIDENCE=<readiness.json>
```

- `make pr-open` checks the actual `origin/develop`/`HEAD` merge first. For a
  conflict-free stale branch it requires a live, complete
  `ruleset_drift_check.py --queue-policy` result covering the queue
  parameters, required checks, strict current-base policy, review enforcement,
  and bypass-actor visibility. Only that verified queue permits publication
  without a local refresh; absent, unknown, or drifted queue state keeps the
  current-base gate and requires `make pr-refresh`.
- `make pr-ready` verifies the exact checkout, live PR identity, review state,
  required checks, holds, and readiness evidence before arming the queue.
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
