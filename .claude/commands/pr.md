---
allowed-tools: Bash(git:*), Bash(gh:*), Bash(make:*), Bash(uv:*)
description: BenchBox PR workflow - path-aware preflight, push, open PR vs develop, enable auto-merge
---

## Context

- Branch: !`git branch --show-current`
- Status: !`git status --short`
- Last commit: !`git log -1 --oneline`
- Ahead/behind develop: !`git rev-list --left-right --count origin/develop...HEAD 2>/dev/null || echo "(no origin/develop)"`

## Your task

This is the BenchBox-specific PR workflow. `develop` is PR-gated through
`ci-required-result`; linear history and squash-only merging are enforced. The
umbrella uses `.github/path-filters.yml`: content-only PRs run content
validation and skip Python fast tests, while code/infra/unknown-path PRs run the
post-Step-3 lint/type + Ubuntu 3.12 fast-test gate. The goal is to land a green
PR with one command and walk away - auto-merge handles the rest.

Execute the following in order, stopping on the first failure:

1. **Refuse if on `develop` or `main`.** If `git branch --show-current` returns
   one of those, stop and tell the user to switch to a feature branch (offer
   `make worktree-add BRANCH=<name>`).

2. **If there are uncommitted changes**, create a single conventional commit
   (`feat:`/`fix:`/`docs:`/`test:`/`chore:`/`ci:`/`refactor:` prefix) summarizing
   them. Stage explicitly by path — never `git add -A`. Include the standard
   `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` trailer.
   If pre-commit hooks rewrite files, re-stage and commit again (do NOT use
   `--amend`; create a new commit).

3. **Run `make pr-preflight`** to mirror the CI gate locally. If it fails, fix
   the root cause and loop back to step 2. Do NOT bypass with `--no-verify`.

4. **Run `make pr-open`** — pushes the branch, opens a PR vs `develop` with
   `gh pr create --fill`, and enables `gh pr merge --auto --squash`.

5. **Print the PR URL** and a one-line summary of what auto-merge will do
   ("will squash-merge once `ci-required-result` goes green").
   Do NOT poll for CI completion — auto-merge handles it.

You have the capability to call multiple tools in a single response. Call them
all in one message wherever the calls are independent. Do not narrate
intermediate steps unless you hit a blocker that needs the user's input.
