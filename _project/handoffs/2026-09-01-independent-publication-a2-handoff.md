# Handoff: 2026-09-01 Independent-Publication (A2–A11) Session

**Status:** Historical record. This file does not authorize repository writes,
reviews, publication, or hosted actions. Only a current user request can grant
that authority under `[REVIEW-AUTH-001]`. Place this record in the canonical
clone's `_project/handoffs/` only after a user authorizes that write; the
primary clone is read-only for agents.

## 1. Goal

Open the checker-authority PR and implement the independent-publication
migration phases A2–A11, per the user's directive to "complete the
implementation of the A2-A11 phases." A2 is the first implementable phase; this
session scoped itself to completing **A2's foundation increment** (positive
corpus allowlist + workflow gate + tests + docs). The remaining A2 work (w2,
w4) and phases A3–A11 are open future work.

## 2. Session result (verified in this session)

- **PR #1991** (open) — checker-authority fix: source A0–A11 sequence from the
  live tracker (`scripts/publication/check_plan_reconciliation.py` + its
  tests), commits `f67d428`, `1d2dad7`, `c659914`, `053ff4e`. Branch
  `fix/publication-checker-live-tracker-authority`.
- **PR #1994** (open) — A2 foundation increment, committed `b61e5d80d` on branch
  `fix/publication-corpus-data-only-allowlist`, based on current
  `origin/develop`. Auto-merge withheld.
- Both PRs verified open via `gh pr view` (`state: OPEN`). The worktree is
  clean (`git status --short` empty) and sits on the A2 branch.

### A2 foundation increment contents (PR #1994)

- `scripts/validate_submission.py`: added `CORPUS_RELATIVE_ROOT`,
  `_CORPUS_ROOT_PARTS`, `_CORPUS_METADATA_SUFFIXES`, `_CORPUS_METADATA_FILENAMES`,
  `_CORPUS_NON_DATA_JSON`; `_is_allowed_corpus_data_name(name)`;
  `executable_mode(path)`; `corpus_permit_rejections(changed_paths)` (positive
  allowlist: reject absolute paths, `..` traversal, non-`.json`, non-data
  `.json` such as `package.json`/`tsconfig.json`, hidden dirs/files; on disk
  reject symlink/executable/non-regular-file). Added `--corpus-changed-paths
  <file>` CLI flag; restructured `main()` tail so the corpus gate runs even with
  no bundle paths; disallowed paths force exit 1. `benchbox/validation/bundle.py`
  was **not** modified.
- `.github/workflows/validate-submission.yml`: added step `id: corpus-paths`
  ("Reject disallowed corpus paths") after "Find changed bundles"; uses
  `CORPUS_CHANGED_PATHS_FILE` env (default `/tmp/corpus_changed_paths.txt`);
  `git diff --name-only --diff-filter=ACMRD "$BASE_SHA"...HEAD --
  'results-data/bundles/**'`; runs
  `uv run -- python scripts/validate_submission.py --corpus-changed-paths "$CORPUS_PATHS"`.
  The `pull_request` trigger was NOT rewritten (w2 trusted-checkout deferred).
- `tests/unit/scripts/test_validate_submission_corpus_allowlist.py`: 30 unit +
  3 CLI tests.
- `tests/unit/workflows/test_validate_submission_corpus_allowlist.py`: 3
  workflow tests (fails-closed on `evil.sh`, passes on `bundle.json`), using
  `run_posix_shell`/`skip_without_posix_shell`.
- `docs/contributing-results.md`: documented the data-only allowlist in the CI
  validation section.

### Verification evidence

- `uv run -- ruff check` on the 3 changed Python files: clean (0 errors).
- `uv run -- ruff format --check` on the 3 Python files: clean.
- Targeted affected suites: 202 passed (incl.
  `test_validate_submission_fail_open.py`, `..._changed_bundles.py`,
  `..._vendor_gate.py`, `..._comment_security.py`).
- `make pr-preflight`: passed in 83.97s — **28742 passed, 19 skipped**.
- Pre-commit hooks passed on the A2 commit (`b61e5d80d`), human identity
  Joe Harris `<joeharris76@gmail.com>`, worktree-pinned.
- Docs note: `docs/contributing-results.md` is not a Python ruff target; ruff
  reports ~1316 pre-existing markdown-doc errors if passed explicitly, all
  unrelated to the A2 prose edit.

## 3. Decisions and alternatives rejected

- **Split A2 onto its own branch** rather than folding it into the still-open
  PR #1991. The A2 commit and #1991 share zero files, and stacked/feature-base
  PRs are unsupported by repo policy (`pr-base-guard.yml` fails loud; must
  retarget/rebase onto `develop`). Cherry-picked `668939488` →
  `b61e5d80d` onto `origin/develop`. This let each increment get its own
  `make pr-open` close-out.
- **Positive allowlist, not a deny-list of executables** (A2 anti-pattern):
  only supported data paths/types are admitted.
- **Do not use `pull_request_target` to check out contributor head** (A2
  anti-pattern): trusted-checkout rework is deferred to A2 w2.
- **`CORPUS_CHANGED_PATHS_FILE` env with a default** to avoid a shared
  `/tmp/corpus_changed_paths.txt` race between shell tests across xdist
  workers (root-caused ~40% intermittent failure; fixed and verified 20/20).

## 4. Blockers and open work

- **A2 w2** — trusted validator invocation: `pull_request_target` trusted-base
  checkout, inspect event metadata and dispatch a trusted controller at the
  merge SHA. Closes the self-green gap noted in
  `_project/audits/results-explorer-publication-adversarial-review.md` §2.7.
- **A2 w4** — merge-SHA revalidation + `scripts/publication/validator_parity.py`
  (that script does not exist yet).
- **A3, A5** — externally blocked (maintainer/GitHub App + secrets/env-policy
  approval; production deploy-drill approval + rollback-artifact retention).
  Cannot be unblocked by code.
- **Ordering (A0)**: a later phase is not ready merely because a TODO exists;
  predecessor gate fresh-evidence must be confirmed first. Closest authority
  for A1: `docs/reference/threat-model.md`, the A0 freeze decision, and the
  §2.7 audit. A1's decision doc is not committed on disk.
- **Live tracker** requires auth:
  `TODO_DB_CREDENTIAL_COMMAND="security find-generic-password -w -s benchbox-todo-rw"`
  exported before `_project/scripts/todo` commands.

## 5. Exact next steps

1. Confirm PR #1991 review/merge, then green A2 w2:
   - Rework `validate-submission.yml` to invoke the validator from a trusted
     base (event metadata + merge-SHA dispatch), not contributor head.
   - Add/update unit + workflow tests for the trusted path; rerun the affected
     suites and `make pr-preflight`.
2. Implement A2 w4 (parity + merge-SHA revalidation) on a fresh
   `origin/develop`-based branch, verify with ruff + `make pr-preflight`, and
   `make pr-open` per increment.
3. Re-check A3/A5 unblock status with a maintainer before attempting them
   (GitHub App + secrets/env policy; production deploy drill).
4. Tag the A2 entry (and any completed later phases) in the tracker with a
   `verification` ladder from the live read before claiming done.

## 6. Assumptions

- Worktree base at `/Users/joe/Developer/BenchBox.wt-publication-checker-authority`;
  primary clone `/Users/joe/Developer/BenchBox` is read-only for agents.
- This handoff is a historical/continuation record only and grants no
  authorization to write, publish, or take hosted actions.
