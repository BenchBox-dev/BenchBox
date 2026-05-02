---
id: 2026-05-01-103001-published-results-validator-no-per-bundle-test
date: 2026-05-01
status: actioned
finding_kind: bug-class
review_context: "/code review of PR #87 (validator manifest compatibility) and PR #88 (closure)"
related_paths:
  - tests/integration/test_cross_branch_validator_contract.py
  - tests/fixtures/published_results_validator.py
  - scripts/validate_submission.py
suggested_sweep: "Add a cross-branch contract test that exercises the per-bundle <stem>.manifest.json discovery path, mirroring the existing legacy submission-manifest.json coverage."
todo_id: null
---

# Per-bundle manifest path landed without an integration test

## Finding

PR #87 added a code path to `scripts/validate_submission.py` (and the
identical vendored fixture) that prefers `<bundle-stem>.manifest.json`
over `submission-manifest.json` and skips `*.manifest.json` during bundle
discovery. The PR shipped without an integration test exercising that
new path:

- `tests/integration/test_cross_branch_validator_contract.py` lines 168,
  177, and 200 only set up `submission-manifest.json` (legacy).
- The drift guard `test_vendored_validator_matches_develop_script`
  passes because both files were updated in lockstep, but it doesn't
  exercise the discovery preference.
- PR #88's claim that "cross-branch contract test already exists" is
  technically true — the file exists — but the new code path is not
  covered.

## Why the five-axis review missed it

A "missing test" axis exists, but it tends to flag tests for *new*
modules. When a single-file change extends an existing module that
*already* has a test file, the natural assumption is "covered." The
extra step — checking whether the existing test exercises the new
branch — is easy to skip.

## Why this matters

If a future refactor breaks per-bundle discovery (or worse, regresses
the discovery preference so legacy beats per-bundle), CI on develop will
not notice. The hosted submit path now writes `<stem>.manifest.json`
exclusively; if validator drift puts the legacy fallback ahead, hosted
bundles mirrored into the PR corpus would fail with confusing errors.

## Suggested next steps

Add a `test_per_bundle_manifest_preferred_over_legacy` to
`test_cross_branch_validator_contract.py`:

1. Create a bundle dir with both `<stem>.manifest.json` (correct hash)
   and `submission-manifest.json` (incorrect hash).
2. Run the validator and assert it succeeds, proving per-bundle wins.
3. Mirror the test for the per-bundle-only case.

## Triage log

- 2026-05-02: actioned — Sweep 2026-05-02: tests/integration/test_cross_branch_validator_contract.py now contains test_validator_prefers_per_bundle_manifest_over_legacy (line 229) which asserts the validator prefers <stem>.manifest.json over submission-manifest.json when both are present, and test_validator_skips_per_bundle_manifest_during_discovery (line 269) which guards the discovery skip. Both run against the develop script and the vendored fixture, exercising the per-bundle code path the original PR #87 added.
