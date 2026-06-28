---
name: verify-framework
description: Post-edit verification workflow for lint, typecheck, tests, and spot checks.
---

# Verify Framework

Run before return/stage/commit.

## Checks

1. Read back edited regions (+5 lines): indentation, nesting, stale imports, orphaned lines.
2. Run project lint if available.
3. Run project typecheck if available.
4. Run targeted tests, then fast/default suite for meaningful code changes.

## Rules

- Never silently skip verification; if unavailable, report why.
- Fix failures before committing or clearly report blocker.
- Report command, result, and residual risk.

- Narrowest check that proves the change first; full fast/preflight are final gates, not exploration. Long output → log file, report summary.

## Delegated gate runs

When a low-effort subagent is available, the main agent may delegate boilerplate deterministic gate runs — full/default test suite, project preflight, CI status check, push, PR-open equivalent, PR-followup runner, or any long run-and-report gate. The main agent chooses the command, cwd, log path, max runtime, and stop condition, and keeps all failure analysis, fixes, scope decisions, retries, and final reporting. The subagent only runs that command and reports status, log tail, PR URL, and check state — no edits, scope/command changes, unrequested retries, review-thread resolution, or policy calls. Gates still run unchanged; only who waits on them shifts. With no subagent or reasoning-effort control available, run the gate inline as before.
