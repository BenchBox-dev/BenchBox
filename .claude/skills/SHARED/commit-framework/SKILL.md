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

- Never `git add -A`.
- Commit only authorized/session-modified files.
- Use Conventional Commits.
- Do not commit if verification fails or scope is ambiguous.
- Push and other deterministic close-out gates (PR-open equivalent, CI status) may be delegated to a low-effort subagent for run-and-report only; the caller keeps failure analysis and fixes. See SHARED/verify-framework/SKILL.md.
