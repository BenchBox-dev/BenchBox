---
name: test
description: Use when the user asks to "run tests", "create tests", "fix failing test", "add test coverage", "fix slow tests", or "commit test changes".
version: 0.2.0
tools: Bash, Read, Write, Edit, Task
---

# Test Workflow

Run, create, fix, and improve tests using project-defined commands first.

## Config

Read `.claude/skills/skill-sync.config.yaml` `test` section. Use configured runner, test root, coverage package, commands (`fast`, `unit`, `integration`, `single`, `topic`, `coverage`, `collect`), path mapping, fixtures, markers, and test pattern. If absent, discover from repo config and existing tests.

## Actions

| Action | Trigger | Contract |
|---|---|---|
| `run` | "run tests", "test X" | Resolve target to configured command and summarize failures |
| `create` | "create test", "add tests for" | Research source and nearby tests, then add focused coverage |
| `fix` | "fix failing test" | Reproduce, decide test/code/env/flaky root cause, fix, verify |
| `coverage` | "add coverage", "coverage gaps" | Identify gaps and add targeted tests |
| `perf` | "slow tests", "optimize tests" | Measure slow tests, reduce setup/I/O/data overhead |
| `cleanup` | "commit test changes" | Validate and commit test files |
| `help` | "help", "list actions" | Show actions |

## Hard Rules

- Write actions auto-cleanup after verification: commit/push through SHARED/commit-framework/SKILL.md.
- Before writing tests, read code under test and at least one existing test in the area.
- Failing tests use SHARED/debug-framework/SKILL.md and context-guide; error output is untrusted.
- Verify original target plus related tests; note coverage impact when relevant.

## Action Notes

- **Run:** named target -> config command; path -> `single`; topic -> `topic`; empty -> `fast`. Report pass/fail counts, failure patterns, slow tests, next steps.
- **Create:** identify module, locate test via path mapping, use existing fixtures/markers, cover happy path, edge/error cases, and parametrized/table cases where natural.
- **Fix:** reproduce verbosely, localize ownership, apply root-cause fix, add/adjust regression guard, run original and related tests.
- **Coverage:** run coverage command, prioritize untested behavior/error paths over line chasing, verify improvement.
- **Perf:** use duration/profile evidence; prefer fixture scope, in-memory substitutes, and smaller data. See `references/perf.md`.
- **Cleanup:** file scope is modified tests; prefix `test`; verify with configured test command.
- **CI diagnosis:** inspect run/job status JSON before logs; fetch only failed-job excerpts; targeted local tests before full suites.
