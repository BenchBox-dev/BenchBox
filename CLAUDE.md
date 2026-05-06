# CLAUDE.md - Quick Reference

→ **See AGENTS.md for full guidance.** This file contains only Claude
Code-specific shortcuts: critical rules, the worktree session-start
protocol, blind-spot bindings, and the pre-approved-commands allowlist.

**Critical rules**: Always `uv run` (never bare `python`/`pytest`/`ruff`/`ty`).
Never `git add -A`. Dev PRs target `develop`, never `main` (`main` is
release-only; `develop` is PR-gated — no direct push to either).
**All agent edits and commits happen in a worktree off `develop`.
If a session begins in the main clone (`/Users/joe/Developer/BenchBox`),
creating a worktree is the FIRST action (see "Session start" below).
Never `git checkout`/`switch`/`branch -m` in the main clone without
explicit user approval — that clone stays on `develop`.**
**Never open a PR or enable auto-merge as a side-effect of a review,
audit, or research action — see `~/.claude/skills/SHARED/review-protocol/SKILL.md` §1.
Landing changes requires explicit user authorization in a separate turn;
this fires before any "auto-commit" or "file-first capture" mandate
elsewhere.** Conversely, write work on a worktree ends at `make pr-open`,
not at `git push` — `make pr-open` is in the pre-approved set.
TPC-DS SF<1 requires the patched dsdgen bundled with BenchBox.
No `-o "addopts="` with pytest.

## Session start

**First action of any new session that might write to the repo**:
confirm you are in a worktree, not the main clone.

```bash
git rev-parse --show-toplevel
# If the output is /Users/joe/Developer/BenchBox you are in the main
# clone. Stop. Claim a retained pool worktree BEFORE any edit, commit,
# or branch switch:
BRANCH=fix/short-slug   # choose chore|fix|feat|docs
WORKTREE_PATH=$(make -s worktree-claim BRANCH="$BRANCH" | sed -n 's/^WORKTREE_PATH=//p')
cd "$WORKTREE_PATH"
```

Pick the branch name from the user's task (e.g. `fix/explorer-cold-load`,
`chore/claude-md-rules`). If unclear, ask before creating the worktree.

**Read-only carveout.** Pure Q&A / exploration — no edits, no commits,
no state-mutating commands — may stay in the main clone. The instant
the session turns into a write task, create a worktree before the first
edit.

**If you find the main clone on a non-`develop` branch**, surface it
to the user and ask before writing anything — that may be in-progress
work; do not reflexively `git checkout develop` to clean up.

See AGENTS.md for worktree pool operations (`worktree-pool-status`,
`worktree-pool-sweep-stale`, `worktree-pool-reset`, etc.) and the
full PR/release/CI flow.

## Review workflow — blind-spot capture

Behavior is governed by `~/.claude/skills/SHARED/review-protocol/SKILL.md`.
BenchBox bindings:

- Path: `_project/blind-spots/YYYY-MM-DD-HHMMSS-<slug>.md`
- Schema: `_project/blind-spots/README.md`
- Validate: `uv run --project _project/scripts -- python _project/scripts/validate_blind_spot.py <file>`
- Sweep: `make blind-spots-{list,report,sweep}`
- Chat marker: prefix the body quote with `Recorded: _project/blind-spots/<file>.md`

Per SHARED §4: capture is local-only — do not commit beyond the
capture file, do not push, do not run `make pr-open`. Apply the
SHARED §2 defect gate before recording — defects belong in the
severity table and TODOs, not in blind-spots. The `/blind-spot` slash
command is the explicit-recording entrypoint.

## Pre-approved Commands

- **Dev/Test**: `make test-*`, `make coverage*`, `make lint`, `make format`, `make typecheck`, `uv run -- python -m pytest *`
- **PR/Worktree (read-only)**: `make pr-preflight`, `make pr-preflight-fast-tests`, `make pr-content-guard *`, `make pr-status`, `make dev-loop-metrics`, `make worktree-pool-status`, `make worktree-pool-check`, `make worktree-list`, `git worktree list*`, `gh pr list*`, `gh pr view*`, `gh pr checks*`
- **PR/Worktree (write — feature/pool worktrees only)**: `make pr-open`, `make pr-fanout`, `make pr-refresh`, `make worktree-claim BRANCH=*`, `make worktree-release`, `make worktree-pool-sweep-stale`, `git push -u origin chore/*`, `git push -u origin fix/*`, `git push -u origin feat/*`, `git push -u origin docs/*`, `gh pr create --fill*`, `gh pr merge --auto --squash*`
- **Manual/admin escape hatches** (not broad auto-allow): `make worktree-pool-init`, `make worktree-pool-reset POOL=NN`, `make worktree-prune`
- **Never auto-allowed**: `git push * develop`, `git push * main`, `git push --force*`, `gh pr create --base main*` — prompt-on-use
- **Files**: `ls*`, `find*`, `cat*`, `head*`, `tail*`, `wc*`, `file*`, `stat*`, `du*`, `tree*`, `which*`
- **Git**: `git status`, `git diff*`, `git log*`, `git show*`, `git branch*`, `git remote*`, `git config --list`, `git worktree list*`
- **Python**: `uv tree`, `uv pip list`, `uv pip show*`, `uv export`, `uv run -- python -c*`, `uv run -- python -m*`
- **TPC**: `timeout 30s _binaries/tpc-{h,ds}/<platform>/dsdgen*`, `timeout 60s _binaries/tpc-{h,ds}/<platform>/dsqgen*`
- **TODO**: `uv run --project _project/scripts -- python _project/scripts/todo_cli.py list*|show*|stats|ready|next*|done*|check-graph`, `uv run --project _project/scripts -- python _project/scripts/validate_todo.py*`, `uv run _project/scripts/generate_indexes.py`
- **Blind-spots**: `make blind-spots-list`, `make blind-spots-report`, `make blind-spots-sweep`, `uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py *`, `uv run --project _project/scripts -- python _project/scripts/validate_blind_spot.py *`
- **UAT**: `make uat-cell PLATFORM=* BENCHMARK=* SCALE=*`, `make uat-stress`, `make uat-sweep CONFIG=*`, `make uat-execute CONFIG=*`, `make uat-validate RESULTS_DIR=* OUTPUT_TSV=*`, `make uat-package CONFIG=* SUBMISSIONS_DIR=* RESULTS=*`, `make uat-explorer-smoke BUNDLES_DIR=* OUTPUT_DIR=* LOG_DIR=*`, `make uat-report CELLS_JSONL=* OUTPUT_TSV=*`
- **System**: `ps*`, `uname*`, `whoami`, `pwd`, `env | grep*`
