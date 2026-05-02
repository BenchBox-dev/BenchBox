---
id: 2026-05-01-103000-hosted-submit-no-local-validate-preflight
date: 2026-05-01
status: open
finding_kind: scope-creep
review_context: "/code review of PRs #86–#93 (results-platform push)"
related_paths:
  - benchbox/cli/commands/submit.py
  - scripts/validate_submission.py
  - tests/integration/test_hosted_submission.py
suggested_sweep: "Decide whether `benchbox submit --service` should run validate_submission.py against the bundle before upload, matching the implicit contract of the --output flow."
todo_id: null
---

# `benchbox submit --service` skips the local validator that `--output` flow benefits from

## Finding

The Phase 2 PR flow produces a bundle that contributors run through
`scripts/validate_submission.py` before opening the PR (the README of the
output dir tells them to). The Phase 3 hosted flow added in PR #93
(`benchbox submit --service`) sends bytes to the API without first running
the validator locally. The hosted service is presumed to validate
server-side, but:

- Contributors with bad bundles pay full upload latency before the
  service tells them what's wrong.
- A schema mismatch between the develop validator and the hosted
  service's validator becomes invisible — the hosted service might
  accept a bundle that `published-results` would later reject (or vice
  versa) if the bundle is later mirrored into the PR corpus.
- There is no end-to-end test asserting that the same bundle produced
  by `submit` passes the develop validator AND the hosted service
  validator. The cross-branch drift guard
  (`test_vendored_validator_matches_develop_script`) only protects
  develop ↔ published-results, not develop ↔ hosted service.

## Why the five-axis review missed it

The five axes (correctness/readability/architecture/security/perf)
naturally evaluate per-PR code quality. They don't ask "does the path
this code adds preserve invariants the other path establishes?" That's
a *contract* axis — invisible unless you're holding the whole submission
flow in your head.

## Why this matters

If hosted ingest validation drifts from `scripts/validate_submission.py`,
contributors see "Hosted submission complete" but the bundle would fail
when later mirrored to `published-results`. There is no warning or
local pre-flight to catch this.

## Suggested next steps

Either:
1. Run `validate_submission.py` against the bundle in the `--service`
   path before upload (treat its errors as upload-blocking, warnings as
   advisory), or
2. Document explicitly that the hosted service is the sole source of
   truth for `--service` validation and that develop's validator may
   diverge — and add a contract test that asserts the hosted mock and
   `validate_submission.py` accept/reject the same bundles.

## Triage log

- 2026-05-02: verified actionable; option (2) is partially landed,
  contract test still owed. The "no local preflight" decision is now
  recorded inline at `benchbox/cli/commands/submit.py:172-182` (the
  `_dispatch_service_mode` docstring) with an explicit pointer back to
  this finding. The path remains: contributors pay full upload latency
  before the hosted service rejects a bad bundle. The contract test
  asserting that the hosted mock and `validate_submission.py`
  accept/reject the same bundles has NOT been written —
  `tests/integration/` has no test joining
  `test_hosted_submission.py` to `validate_submission.py`. Once that
  contract test ships, fail-fast preflight (option 1) becomes the
  obvious next move per the inline docstring.
