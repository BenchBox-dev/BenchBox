---
id: 2026-05-05-090216-defect-followup-artifact-freshness
date: 2026-05-05
status: open
finding_kind: framework-gap
review_context: "code review of fix/uat-framework-pr205-followups"
related_paths:
  - tests/uat/phases/validate.py
  - tests/uat/phases/execute.py
  - tests/uat/test_validate.py
  - tests/uat/test_phases.py
suggested_sweep: "For follow-up PR reviews, add a stale-artifact freshness check for phase outputs that are reused across reruns."
todo_id: null
---

# Defect Follow-Up Reviews Need Artifact Freshness Checks

## Finding
The five-axis review frame catches correctness of the new branch diff, but it does not force reviewers to ask whether a follow-up fix can accidentally consume artifacts produced by an earlier failed or aborted run. For defect-follow-up PRs, especially orchestration code that writes phase outputs, review should explicitly check that each phase proves the output it parses was produced by the current invocation.

## Why this matters
Follow-up fixes often focus on the named symptom and its regression test. That can miss temporal coupling between retries, reruns, and existing files in operator directories, where stale artifacts make a failed phase look recoverable.

## Suggested next steps
- [ ] Add an artifact-freshness prompt to the review checklist for orchestration and phase-output code.
- [ ] Sweep phase wrappers that parse output files after subprocess calls for stale-file reuse.
