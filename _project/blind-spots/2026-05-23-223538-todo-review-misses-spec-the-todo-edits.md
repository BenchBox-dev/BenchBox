---
id: 2026-05-23-223538-todo-review-misses-spec-the-todo-edits
date: 2026-05-23
status: actionable
finding_kind: framework-gap
review_context: "/todo review — chore/shrink-review-followup-todos (shrink-campaign follow-ups)"
related_paths:
  - _project/TODO/main/planning/shrink-objective-function-and-guardrail.yaml
  - _project/goal-shrink-core-code.md
suggested_sweep: "grep active TODO descriptions for 'goal line N' / spec line-number citations; promote a rubric-extension TODO if it recurs"
todo_id: null
---

# TODO-review freshness axis misses spec/goal docs the TODO itself edits

## Finding
A TODO that proposes to edit a living policy/spec document (here
`_project/goal-shrink-core-code.md`) cited that document's current state as
fixed evidence ("goal line 12", "goal line 19", "still driven by a single
naive `cloc` metric"). The goal file had since been rewritten to encode the
very objective function the TODO's w1 was going to author, and the cited line
numbers no longer held. The TODO scored 3 on clarity, guardrails, prior_art,
and work breakdown and would have passed a mechanical review; only manually
reading the goal file revealed w1 was already done and the premise falsified.
The review rubric's evidence-durability sub-axis enumerates dependency
versions, harness PASS, and observed external behavior — but not "the
spec/goal file this TODO proposes to modify may have already moved."

## Why this matters
TODOs authored from a campaign review often target the campaign's governing
spec, and that spec is itself a living document. Quoting its line numbers as
fixed evidence makes the whole TODO go stale the moment the spec is edited —
silently, because every other axis still scores well. The freshness axis
should treat a TODO's own edit target as a durability hazard, not just its
external dependencies.

## Suggested next steps
- [ ] Extend the todo `review` evidence-durability rule: when a TODO's
      `scope_limit.only_modify` includes a policy/spec/goal doc AND its
      `description` quotes that doc, require a `w0` that re-reads current state
      and diffs against the quoted text (score 0 if absent).
- [ ] Spot-check other active TODOs for spec line-number citations that can
      drift (sql-catalog already corrected to a stable phrase reference here).

## Triage log

- 2026-07-18: actionable — The original shrink TODO is completed in DONE/ as of 2026-05-24, but recheck of the current /todo review rubric shows the own-edit-target freshness gap remains; revised the record to separate the resolved example from the live framework gap.
- 2026-07-19: actionable — The 2026-07-18 pass rewrote the title and `## Finding` body in place instead of confining its update to this Triage log, losing the original verbatim finding (per this directory's README: `## Finding` is verbatim audit text, triage may only touch frontmatter `status`/`todo_id` plus append here). Restored the original 2026-05-23 title and Finding text verbatim from git history (commit 9833fedc); the 2026-07-18 entry's substance (shrink TODO completed in DONE/, review-framework gap still live) stands as the triage-log record of that recheck.
