# Iterate To Green

Use when the user asks to drive a command, test suite, CI gate, lint, typecheck,
or migration until it passes.

## Loop

1. Run the requested command exactly unless unsafe.
2. Save long or recurring output in `_project/iterate/<slug>/run<N>.log`.
3. Cluster failures by signature: error class + failing unit + likely layer.
4. For one cluster at a time: research, debug, make a narrow fix, verify the
   target, review, and commit it.
5. Re-run the original command.
6. Stop on green, documented hard blocker, or `--max-iterations` (default 20).

## Flags

- `--max-iterations N`: cap loop.
- `--narrow "<cmd>"`: preferred minimal repro.
- `--dry-run`: plan clusters/fixes but do not edit.
- `--no-commit`: use only when the user explicitly requires local-only work.

## Artifacts

- `status.md`: current command, iteration, cluster status, last result.
- `run<N>.log`: raw command output when useful.
- `blockers.md`: root cause, tried/ruled fix hierarchy, why remaining work is outside authority.

## Rules

- Do not batch unrelated fixes.
- Apply the investigation framework's hard-blocker criteria before marking work
  blocked.
- Do not hide remaining failures after one cluster turns green.
- Edit against the smallest failing reproduction. Finish by rerunning the
  original command.
- For verification-only commits, keep raw stdout in `/tmp`, CI artifacts, or
  the configured artifact directory, such as `BENCHBOX_OUTPUT_DIR`. Commit only
  the durable command, checked SHA or version, PASS/FAIL result, and key lines
  or counts. Do not commit
  `_project/verification-logs/*.log` unless it is a deliberate small fixture
  with a named consumer.
- After `pr-open`, repeat preflight or broad diffs only if mergeability changes,
  a required check fails, or the integration branch, such as `develop`, advances
  into PR paths. Command reruns and PR or CI gates may be delegated for
  run-and-report. Keep clustering, fixes, and stop decisions in the main
  session.
