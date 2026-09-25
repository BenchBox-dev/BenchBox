# External contributor submission dry run (maintainer-executed)

Date: 2026-09-25
Status: Engineering validation complete. Residual: live fork-PR firing needs a
secondary account with no write access; no code change gates on it.

## What was verified (following docs/contributing-results.md literally)

1. **Packaging (docs step 3)**: `benchbox submit <result> --output` on a real
   validated AMPLab/ClickHouse-Local sf0.01 result produced the documented
   layout (`bundle/*.json`, `<stem>.manifest.json`, `CONTRIBUTING.md`) plus
   exact next-step instructions (copy paths, inventory regen, validator
   command, PR title `results: AMPLab Big Data ClickHouse Local sf0.01`,
   target `published-results`).
2. **Negative paths**: an unvalidated result is refused
   (`validation_status=not_run`); a validated result with zero queries is
   refused (`queries array must not be empty`). Both refusals name the cause.
3. **Validator (docs step 5)**: `scripts/validate_submission.py` on the
   packaged bundle reports `0 error(s), 0 warning(s)` PASS. Same validator
   the CI workflow executes from the trusted base checkout.
4. **Trust classification**: the packaged manifest carries
   `result_source: community`, which `provenance.py` maps to the
   `community-submission` explorer badge. Fork-vs-maintainer workflow gates
   (`Reject validator or workflow changes`, `Reject non-maintainer vendor/
   additions`, keyed on `head.repo.fork` and `author_association`) are pinned
   by `test_validate_submission_vendor_gate.py`,
   `test_validate_submission_trusted_checkout.py`, and
   `test_validate_submission_workflow_guard_mirror.py` (26 passed).

## Deviation recorded

None. Every docs step behaved as written. The salt prerequisite
(`BENCHBOX_MACHINE_ID_SALT`) is documented before first use and the submit
command errors clearly without it.

## Residual (not gating)

Firing the real `pull_request_target` workflow from a fork PR requires a
maintainer-owned secondary account with no write access. That proves CI
delivery, not logic: the validator, gates, and trust mapping above are the
logic, and they are verified. Recruiting a genuine outsider remains a
research nicety for friction data only.
