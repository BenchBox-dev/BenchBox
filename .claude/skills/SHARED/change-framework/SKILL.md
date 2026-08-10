---
name: change-framework
description: "Unified source-code selection and change-execution workflow: reuse ladder, vertical slicing, post-edit verification, and authorized commits."
---

# Change Framework

Governs how in-scope edits are selected, sliced, verified, and, when
authorized, committed.

## 1. Source-code selection

After required research and before editing source code, choose the first option
that fully satisfies the authorized requirement and applicable repository and
safety constraints:

1. No change, if the required outcome already exists.
2. An existing helper or established pattern.
3. A standard-library or native platform feature.
4. A declared, direct dependency supported by the project.
5. The smallest clear new implementation.

Do not weaken correctness, compatibility, validation, security, accessibility,
or explicit requirements to use an earlier option. Document a bounded
simplification only when its ceiling is material or non-obvious; state the
condition that would justify replacing it.

## 2. Slicing discipline

Use for multi-file work, features, refactors, or any change likely to exceed about 100 lines before testing.

- Touch only task-required code; surface adjacent issues as "noticed but not touching."
- Prefer vertical slices; use contract-first for parallel components and risk-first for uncertainty.
- Each slice must implement, test, and verify one logical behavior. When
  Section 4 authorizes commits, commit one slice at a time.
- Keep the project buildable and each increment independently revertible.
- New incomplete code stays disabled by default.

## 3. Post-edit verification ladder

Run before return/stage/commit.

### Checks

1. Read back edited regions (+5 lines): indentation, nesting, stale imports, orphaned lines.
2. Run project lint if available.
3. Run project typecheck if available.
4. Run targeted tests, then fast/default suite for meaningful code changes.

### Rules

- Never silently skip verification; if unavailable, report why.
- Fix failures before committing or clearly report blocker.
- Report command, result, and residual risk.
- Narrowest check that proves the change first; full fast/preflight are final gates, not exploration. Long output → log file, report summary.

### Delegated gate runs

When a low-effort subagent is available, the main agent may delegate boilerplate deterministic gate runs — full/default test suite, project preflight, CI status check, push, PR-open equivalent, PR-followup runner, or any long run-and-report gate. The main agent chooses the command, cwd, log path, max runtime, and stop condition, and keeps all failure analysis, fixes, scope decisions, retries, and final reporting. The subagent only runs that command and reports status, log tail, PR URL, and check state — no edits, scope/command changes, unrequested retries, review-thread resolution, or policy calls. Gates still run unchanged; only who waits on them shifts. With no subagent or reasoning-effort control available, run the gate inline as before.

## 4. Authorized commit workflow

Use only when a calling skill authorizes a write-shaped commit.

### Inputs

| Parameter | Meaning |
|---|---|
| `file_scope` | Exact file discovery rule |
| `prefix` | Conventional type: `feat`, `fix`, `refactor`, `docs`, `test`, `chore` |
| `verify_cmd` | Required pre-commit verification |

### Steps

1. Discover files from `file_scope`; no files -> "No files to commit."
2. Inspect `git status --porcelain {files}`, `git diff {files}`, and recent log.
3. Run verification (Section 3, Post-edit verification ladder); fix failures or stop without committing.
4. Stage and commit explicit files in one shell command.
5. Push after successful commit; if no upstream, push with `-u origin {branch}`.

### Rules

- **[COMMIT-IDENTITY-001] Resolve and validate human identity.** Inspect the
  effective `user.name` and `user.email` with their config origins before the
  first commit. A repository-local value overrides the user's global identity;
  do not assume that makes it intentional, and every linked worktree inherits
  it. This binds authorship: reject known agent/service identities (for example
  Claude, Codex, Gemini, ChatGPT, or their vendor noreply addresses) as author
  unless the current authorized task explicitly names that exact identity.
  Otherwise use the user's effective human author identity. A commit-signing
  service may hold the committer slot behind a human author, so signatures stay
  verifiable without misattributing the work. Do not pass `--author` or set
  `GIT_AUTHOR_*` / `GIT_COMMITTER_*` merely to work around a stale config; an
  explicitly authorized task-local override applies only to that task and never
  becomes standing repository or skill policy.
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
- Push and other deterministic close-out gates may be delegated to a low-effort
  subagent for run-and-report only. The caller keeps failure analysis and fixes.
  See Section 3, Delegated gate runs.
