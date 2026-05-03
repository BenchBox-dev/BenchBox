---
id: 2026-05-03-084923-spec-approval-ergonomics
date: 2026-05-03
status: open
finding_kind: framework-gap
review_context: "code review of W4 design document in TODO results-explorer-uat-methodology-blind-spot-remediation"
related_paths:
  - _project/specs/uat-methodology-blind-spot-remediation.md
suggested_sweep: "extend the /code review checklist for spec/proposal docs that have a user-approval gate to include 'approval ergonomics': what does the user do to accept, partially accept, reject; what cascades."
todo_id: null
---

# Approval-gate specs need explicit approval protocols, not just open questions

## Finding

The W4 design document closes its "open questions" section with four
questions but no protocol for answering them. A user could:
- Reply "accept all defaults" — but does that answer all four?
- Reject only Finding 3 — does that auto-cancel TODO #2 in the
  implementation list?
- Approve some now and defer others — is that allowed?

The spec is otherwise well-structured but doesn't say. Approval
ergonomics is a category the standard /code review framework does
not name.

## Why this matters

When a spec includes a user-approval gate, the *response shape* is part
of the deliverable. Without it, the user has to design their own reply
format under uncertainty about what the implementer (next agent or
human) will interpret correctly. Particularly relevant when the spec
spawns parameterised follow-up work (W5 here) where partial approval
changes the parameter set.

A two-line "approval protocol" preamble — "respond yes/no per question,
defaults apply to anything you don't address; partial answers cascade
as follows: ..." — closes the gap cheaply.

## Suggested next steps

- [ ] Add an "Approval protocol" preamble to W4's Section 5.
- [ ] Consider adding "approval ergonomics" to the /code review checklist for proposal/spec docs with user-approval gates.
