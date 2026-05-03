---
id: 2026-05-03-083859-proposals-doc-decidability-gap
date: 2026-05-03
status: merged-to-todo
finding_kind: framework-gap
review_context: "code review of W2 deliverable in TODO results-explorer-uat-methodology-blind-spot-remediation"
related_paths:
  - _project/handoffs/uat-methodology-w2-proposals.md
  - _project/specs/uat-methodology-blind-spot-remediation.md
suggested_sweep: "when reviewing proposals/spec docs, add a 'decidability' check beyond the five-axis code rubric: each open question needs a stated default, a stated consequence, and a clear yes-or-no path for the user."
todo_id: code-review-checklist-additions-for-spec-docs
---

# Five-axis code review framework misses decidability gaps in proposals docs

## Finding

Reviewing the W2 proposals handoff with the standard five-axis code review
(Correctness/Readability/Architecture/Security/Performance) caught a
factual error (open_questions schema claim) but did not initially flag
that several "tooling vs convention" proposals were worded conditionally
("IF the user wants enforcement") without giving the user a clear default
or a per-finding recommendation. The result: the user reading W4 would be
asked to make small decisions whose answers the doc is best-positioned to
recommend.

## Why this matters

A proposals/spec document's quality is partially captured by code-review
axes (correctness of claims, readability, structural coherence) but its
*function* is to let the user decide. The missing axis is **decidability**:
each user-facing choice should ship with a default, a consequence, and a
recommendation. Conditional phrasing without a default pushes work back
to the user instead of distilling it.

This pattern probably affects future spec/plan docs in `_project/specs/`
too, not just this one. A short addition to the /code review checklist —
"for proposals/spec docs, also check decidability" — would close the gap
cheaply.

## Suggested next steps

- [ ] Patch the W2 proposals doc to recommend per-finding tooling vs convention rather than leaving it conditional.
- [ ] When the W4 design document collates user decisions, ensure each one has default + consequence + recommendation, not just a question.
- [ ] Consider promoting "decidability check for proposals/spec docs" into the `/code review` skill checklist.

## Triage log

- 2026-05-03: promoted to TODO `code-review-checklist-additions-for-spec-docs`
