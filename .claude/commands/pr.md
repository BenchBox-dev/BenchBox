---
allowed-tools: Bash(git:*), Bash(gh:*), Bash(make:*), Bash(uv:*)
description: BenchBox PR workflow - path-aware preflight, push, open PR vs develop; does not enable auto-merge unless READY=1
---

## Context

- Branch: !`git branch --show-current`
- Status: !`git status --short`
- Last commit: !`git log -1 --oneline`
- Ahead/behind develop: !`git rev-list --left-right --count origin/develop...HEAD 2>/dev/null || echo "(no origin/develop)"`

## Your task

BenchBox PR workflow targeting `develop` with linear history and squash-only merging.

Execute the following in order, stopping on the first failure:

1. **Run `make agent-write-preflight`.** If it refuses (BenchBox primary clone), stop and tell
   the user to create a worktree (`make worktree-create BRANCH=<name> WORKTREE_PATH=<path>`).
   Do not commit, push, or open a PR from the primary clone without `BENCHBOX_ALLOW_MAIN_CLONE_WRITE=1`.

2. **Refuse if on `develop` or `main`.** Stop and switch to a feature branch worktree if needed.

3. **Stage authorized changes and commit.** Stage authorized paths explicitly (never `git add -A`),
   verify `make agent-identity-check`, and create a conventional commit.

4. **Run `make pr-preflight`** as the path-aware local gate. CI-only coverage remains separate.
   Fix root causes if failing; do not use `--no-verify`.

5. **Run `make pr-open`** — pushes branch and opens a PR vs `develop`. Note: auto-merge stays withheld
   unless `READY=1` (`make pr-open READY=1` or `make pr-ready`).

6. **Print the PR URL** and reported auto-merge status. Do not poll CI: pending is terminal.
