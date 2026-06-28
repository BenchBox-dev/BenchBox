# Code Compare Reference

Compare behavioral contracts, not formatting.

## Extract

- Public functions/classes/CLI/API surfaces and inputs/outputs.
- Side effects, errors, validation, persistence, network/filesystem use.
- Dependencies, registration points, config/env vars.
- Control/data flow and performance-sensitive paths.
- Tests or callers proving expected behavior.

## Compare

Use SHARED/compare-framework/SKILL.md scoring. Mark as breaking when a public contract, error behavior, persistence format, security property, or required dependency changes. Mark as high risk when relationships or registration paths disappear.

## Output

Report shared behavior, unique behavior, changed contracts, lost relationships, confidence, and recommended follow-up tests.
