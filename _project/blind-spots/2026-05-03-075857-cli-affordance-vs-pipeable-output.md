---
id: 2026-05-03-075857-cli-affordance-vs-pipeable-output
date: 2026-05-03
status: actioned
finding_kind: framework-gap
review_context: "/code review of PR #154 (results-explorer-uat-defect-submission-batch-path-affordances)"
related_paths:
  - benchbox/cli/commands/results.py
suggested_sweep: "When a CLI affordance is added to address a scripting/loop pain point, audit the output channel: is the new output cleanly pipeable (plain stdout, no decorations, no preamble) or just rendered alongside existing TTY-only output? Check other recent CLI additions for the same pattern."
todo_id: null
---

# Five-axis review misses workflow-fit for CLI affordances driven by scripting pain

## Finding
The five-axis frame (Correctness, Readability, Architecture, Security, Performance) does not natively ask: "Does the new CLI output match the workflow that motivated the change?" PR #154 was justified by W5 needing to loop `benchbox submit` over 388 captured paths. The delivered `benchbox results --paths` *prints* those paths, but only after a Rich-formatted summary table, on the same `console` object that emits style markup. A contributor who tries the obvious next step — `benchbox results --paths | xargs -n1 benchbox submit` — has to grep past a table and strip color codes. The affordance technically exists; the *workflow* the UAT defect named is still broken.

## Why this matters
"Make X easier" UX changes need a workflow-fit axis distinct from the standard five. Correctness, readability, and architecture can all pass while the user's actual pipeline stays awkward. Whenever a CLI affordance is justified by a scripting/loop pain point, the review should explicitly verify the output is consumable by the scripts the user will actually write — plain stdout, no decorative preamble, no markup that bleeds through `tee`/`xargs`. Otherwise the PR ships a half-fix that looks complete in the test suite.

## Suggested next steps
- [ ] Sweep recent `benchbox <verb>` additions that emit "copyable" or "exportable" output (e.g., paths, IDs, URLs) and confirm each can be piped without grep filtering.
- [ ] Decide whether to add a workflow-fit checklist item to the project review rubric for any change framed as "make scripting easier" (e.g., must demonstrate `<cmd> | xargs ...` works in the PR description).
- [ ] If `benchbox results --paths` is updated, prefer `click.echo` (or `console.print(..., markup=False)` with no preamble when `--paths` is the only mode requested) so output round-trips through pipes cleanly.

## Triage log

- 2026-05-03: actioned — Fixed inline in fix/results-paths-pipeable-affordance — paths now write to plain stdout via click.echo, hint to stderr, mutually exclusive with --submitted.
