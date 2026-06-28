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
- Do not mark blocked without the debug-framework hard-blocker criteria.
- Do not hide remaining failures after one cluster turns green.
- Prefer smallest failing repro for edits; always finish by rerunning the original command.
