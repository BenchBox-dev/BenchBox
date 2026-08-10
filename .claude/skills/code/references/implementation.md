# Code Implementation Actions

## Implement

Follow configured project conventions and checks.

## Commit

Discover session files, inspect `git status --porcelain` and the diff, verify,
make a conventional commit, and push through the commit framework.

## Fix

- Lint: use configured lint/fix commands.
- Type: run typecheck and add annotations where needed.
- Runtime: apply the investigation framework's Debug workflow.

## Debug

Use `SHARED/investigation-framework/SKILL.md` (Debug and Context Guide sections). A blocker requires a
known root cause, tried/ruled-out fixes, and remaining work outside authority.

## Perf

Measure baseline, profile, optimize, and remeasure. Keep the performance
budget explicit; apply `SHARED/review-protocol/SKILL.md` (Planning-Depth Layers) L3 before optimizing to confirm the
measured bottleneck is the real constraint.
