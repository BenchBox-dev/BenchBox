---
id: 2026-05-05-154308-uat-cli-surface-constraint-no-enforcement
date: 2026-05-05
status: open
finding_kind: framework-gap
review_context: "principal-engineer review of UAT framework PR #205 (post-merge simplification audit)"
related_paths:
  - _project/specs/uat-framework.md
  - _project/DONE/main/active/uat-framework-tests-uat-runner.yaml
  - benchbox/cli/
suggested_sweep: "Either add a fast-marked drift guard test (5 lines) or remove the spec language that implies the constraint is enforced. Spec-of-record without test coverage is a future regression source — the parent TODO is in DONE/, so the verification step is one-shot, not ongoing."
todo_id: uat-framework-review-followups
---

# "No `benchbox` CLI surface change" is a spec-of-record claim with no automated enforcement

## Finding
`_project/specs/uat-framework.md:371-373` asserts:

> **No `benchbox` CLI surface change.** `git diff origin/develop -- benchbox/cli/`
> must produce no diff over the lifetime of this TODO. This is enforced by the
> verification block in the parent TODO.

The parent TODO `_project/DONE/main/active/uat-framework-tests-uat-runner.yaml`
contains a verification step (`expected_output: "no diff"`). However, that
TODO is now in `_project/DONE/` — the verification ran once at TODO completion
and is not re-evaluated.

I searched `.github/workflows/`, `tests/`, and the Makefile for any automation
that runs `git diff origin/develop -- benchbox/cli/` and asserts emptiness.
Zero hits. The constraint is reviewer-attention-only.

A future PR that adds a `benchbox uat` subcommand (or any `benchbox/cli/`
mutation) would land green unless a reviewer specifically catches the spec
intent — which is itself in a spec file the reviewer may not have read.

## Why this matters
The spec drives the framework's social contract: UAT is a developer concern,
`benchbox` is a user concern. Erosion of that line undoes the architectural
choice. The framing relied on the parent TODO's verification block as the
enforcement mechanism, but TODO verification is one-shot at landing, not
ongoing.

## Suggested next steps
- [ ] Decide: is the constraint genuine? If yes, add a fast-marked test
      `tests/uat/test_no_cli_surface_drift.py` that runs
      `git diff --name-only origin/develop -- benchbox/cli/` and asserts
      emptiness. ~5 lines. Or scope to "no new files" to allow
      legitimate fixes.
- [ ] If the constraint was scoped to the TODO lifetime only and is now
      retired, edit `_project/specs/uat-framework.md:371-373` to say so
      explicitly. Spec language that implies ongoing enforcement without
      ongoing enforcement is technical debt.
- [ ] Audit other "verification block in the parent TODO" claims — same
      pattern likely recurs.
