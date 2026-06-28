# Benchmark Plan And Execute Reference

Use for benchmark/platform features that need research, implementation, and verification.

## Flow

1. Research current benchmark/platform patterns, tests, docs, and TODOs.
2. State goal, scope, constraints, public interfaces, and success criteria.
3. Slice vertically: implement one working path, test, verify, commit, repeat.
4. Preserve phase propagation, validation, timing policy, artifact paths, and lazy optional deps.
5. Update docs/tests only where the behavior changes.

## Verification

Run targeted tests, fast smoke, standards/platform checks as applicable, and any policy audit for touched areas. Report skipped expensive/live checks explicitly.
