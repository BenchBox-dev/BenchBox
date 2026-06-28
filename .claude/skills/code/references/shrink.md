# Code Shrink Reference

Use SHARED/shrink-framework/SKILL.md for code compression.

## Preserve

Public API, imports/dependencies, registrations, side effects, error handling, validation, types, comments that explain why, TODO/FIXME, tests' expected behavior, and performance-critical behavior.

## Safe Cuts

Dead code, repeated branches, unnecessary intermediates, comments that restate code, verbose constructions with equivalent concise forms, and duplicate implementations after proving one path is unused.

## Validation

Compare semantics against baseline, run targeted tests for touched behavior, then lint/typecheck/fast tests as appropriate. Do not shrink tests, migrations, generated files, or vendored code.
