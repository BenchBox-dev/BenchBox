# Iterate To Green

Use when the user asks to drive a command, test suite, CI gate, lint/typecheck, or migration until passing.

## Loop

1. Run the requested command exactly unless unsafe.
2. Preserve full output in `_project/iterate/<slug>/run<N>.log` when long or recurring.
3. Cluster failures by signature: error class + failing unit + likely layer.
4. For one cluster at a time: research -> debug -> narrow fix -> targeted verify -> review -> commit if authorized by calling skill.
5. Re-run the original command.
6. Stop on green, documented hard blocker, or `--max-iterations` (default 20).

## Flags

- `--max-iterations N`: cap loop.
- `--narrow "<cmd>"`: preferred minimal repro.
- `--dry-run`: plan clusters/fixes but do not edit.
- `--no-commit`: only if user explicitly overrides the normal write-action commit rule.

## Artifacts

- `status.md`: current command, iteration, cluster status, last result.
- `run<N>.log`: raw command output when useful.
- `blockers.md`: root cause, tried/ruled fix hierarchy, why remaining work is outside authority.

## Rules

- Do not batch unrelated fixes.
- Do not mark blocked without the investigation-framework (Debug section) hard-blocker criteria.
- Do not hide remaining failures after one cluster turns green.
- Prefer smallest failing repro for edits; always finish by rerunning the original command.
- For verification-only commits, keep raw stdout in `/tmp`, CI artifacts, or
  `BENCHBOX_OUTPUT_DIR`; commit only the durable command, checked SHA/version,
  PASS/FAIL, and key lines/counts. Do not commit
  `_project/verification-logs/*.log` unless it is a deliberate small fixture
  with a named consumer.
- After `pr-open`, skip preflight/broad diffs unless mergeability flips, a
  required check fails, or `develop` advanced into PR paths. Command reruns
  and the PR-open/CI gate may be delegated for run-and-report; keep clustering,
  fixes, and stop decisions in the main session.
