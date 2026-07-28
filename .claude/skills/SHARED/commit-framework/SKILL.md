---
name: commit-framework
description: Unified identify-verify-stage-commit workflow for skill-driven commits.
---

# Commit Framework

Use only when a calling skill authorizes a write-shaped commit.

## Inputs

| Parameter | Meaning |
|---|---|
| `file_scope` | Exact file discovery rule |
| `prefix` | Conventional type: `feat`, `fix`, `refactor`, `docs`, `test`, `chore` |
| `verify_cmd` | Required pre-commit verification |

## Steps

1. Discover files from `file_scope`; no files -> "No files to commit."
2. Inspect `git status --porcelain {files}`, `git diff {files}`, and recent log.
3. Run verification; fix failures or stop without committing.
4. Stage and commit explicit files in one shell command.
5. Push after successful commit; if no upstream, push with `-u origin {branch}`.

## Rules

- **[COMMIT-IDENTITY-001] Resolve and validate human identity.** Inspect the
  effective `user.name` and `user.email` with their config origins before the
  first commit. A repository-local value overrides the user's global identity;
  do not assume that makes it intentional. Reject known agent/service identities
  (for example Claude, Codex, Gemini, ChatGPT, or their vendor noreply addresses)
  unless the current authorized task explicitly names that exact identity.
  Otherwise use the user's effective human author and committer identity. Do not
  pass `--author` or set `GIT_AUTHOR_*` / `GIT_COMMITTER_*` merely to work around
  a stale config. A task-local override applies only to that task; never convert
  it into standing repository or skill policy.
- Do not add an agent/service `Co-Authored-By` trailer or any equivalent
  attribution unless the current task explicitly requests that exact trailer.
  A stale author request, tool convention, or claim that an agent contributed
  is not authorization.
- After committing, verify the resulting author and committer with
  `git show -s --format=fuller HEAD` when identity was explicitly overridden or
  identity is part of the acceptance criteria.
- Never `git add -A`.
- Commit only authorized/session-modified files.
- Use Conventional Commits.
- Do not commit if verification fails or scope is ambiguous.
- Push and other deterministic close-out gates (PR-open equivalent, CI status) may be delegated to a low-effort subagent for run-and-report only; the caller keeps failure analysis and fixes. See SHARED/verify-framework/SKILL.md.
