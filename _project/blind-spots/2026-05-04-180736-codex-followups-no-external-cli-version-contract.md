---
id: 2026-05-04-180736-codex-followups-no-external-cli-version-contract
date: 2026-05-04
status: open
finding_kind: framework-gap
review_context: "/code review of PR #194 (codex-pr-review-followups routine) on chore/codex-pr-review-followups"
related_paths:
  - _project/scripts/codex_pr_review_followups.py
  - Makefile
suggested_sweep: "find other scripts that shell out to third-party CLIs without a version probe or pin"
todo_id: null
---

# Routine ships hard-coded codex-cli flags with no version contract

## Finding

`run_codex_for_comment` hard-codes `--ask-for-approval` (line 434) and `--sandbox` (line 432) as positional flag/value pairs in the codex-cli argv. The installed codex-cli (`0.128.0`) does not have `--ask-for-approval`; the equivalent is now `-c approval_policy=...` or `--dangerously-bypass-approvals-and-sandbox`. The routine fails at the first comment with `error: unexpected argument '--ask-for-approval' found` and never advances. There is:

- no `codex --version` probe at startup,
- no minimum-version assertion or compat note in `pyproject.toml` / docs,
- no fallback flag style,
- no integration test that actually invokes `codex exec` against a real binary.

The five-axis review framework (correctness/readability/architecture/security/performance) does not include a "third-party CLI compatibility" axis, so reviews of scripts that wrap external tools systematically miss this class of failure until the script runs in anger.

## Why this matters

This is a **framework gap, not a single-script bug**. BenchBox has many scripts that shell out to `gh`, `git`, `make`, `uv`, `codex`, and platform CLIs (`duckdb`, `clickhouse-cloud`, etc.). Each one inherits the host machine's installed version. When upstream renames a flag, the failure surface is "the routine simply stops working" with no early warning. The five-axis frame treats external CLIs as black-box subprocess invocations whose return code is the only contract; it doesn't ask "what version contract does this script depend on, and how is it enforced?"

The PR also shipped without an end-to-end integration test — the test file exercises pure functions and one branch guard, but `codex exec` is never invoked against the real binary even in CI smoke. A `--codex-binary echo` or `--dry-codex` mode would have caught this.

## Suggested next steps

- [ ] Add a `_check_codex_version()` probe at the top of `run_action_loop` that runs `codex --version`, parses semver, and rejects unsupported versions with a clear remediation (upgrade/downgrade command).
- [ ] Replace `--ask-for-approval <mode>` with `-c approval_policy=<mode>` (config override syntax exists in 0.128.0 and likely in earlier versions) — this is more durable across codex-cli releases.
- [ ] Add an integration smoke test that invokes the routine with a fake `codex` shim on `PATH` (a 5-line bash script that echoes a fixed disposition) so the end-to-end argv assembly is exercised in CI.
- [ ] Adopt a repo-wide convention: any script that shells out to a non-bundled CLI declares its supported version range in a module-level constant + a probe function, and the test suite asserts the probe runs.
- [ ] Sweep `_project/scripts/` and `scripts/` for similar shell-outs (`subprocess.run([...])` with a non-stdlib binary) and audit each for a version contract.
