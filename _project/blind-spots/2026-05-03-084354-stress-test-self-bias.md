---
id: 2026-05-03-084354-stress-test-self-bias
date: 2026-05-03
status: open
finding_kind: framework-gap
review_context: "code review of W3 stress-test in TODO results-explorer-uat-methodology-blind-spot-remediation"
related_paths:
  - _project/handoffs/uat-methodology-w3-stress-test.md
suggested_sweep: "when stress-testing proposals against historical cases, separate the 'designer' and 'reviewer' roles, or explicitly include a 'strongest argument against each proposal' section to counter the natural survivorship bias."
todo_id: null
---

# Self-designed stress-tests survive too easily — proposer bias

## Finding

The W3 stress-test replays each W2 proposal against three historical UATs
and finds that all three proposals "survive replay with no false
positives." The proposer designed both the proposals and the stress test,
so the test is unlikely to surface failure modes the proposer hadn't
already considered when drafting. The doc names "narrow stress-test
surface (only 3 UATs)" as a limitation but doesn't name the
self-grading bias.

## Why this matters

Stress-tests are most useful when they're adversarial. A self-designed
stress-test that finds no problems looks like validation but is more like
a sanity check — the proposer already filtered out the obvious failure
modes during drafting. Either (a) split designer and reviewer roles
across agents/humans, or (b) explicitly include a "strongest argument
against each proposal" section in the stress-test doc so the structure
forces adversarial framing.

This pattern probably affects future proposals/spec docs that include
stress-test sections. A short sweep of `_project/specs/` and
`_project/handoffs/` for stress-test sections that conclude
"all proposals survive" would identify whether this is a single
incident or a recurring shape.

## Suggested next steps

- [ ] Add a "strongest case against each proposal" subsection to the W3 stress-test doc (or fold into W4).
- [ ] Consider promoting "adversarial framing or independent reviewer for stress-tests" into the /code review and /todo skill checklists.
- [ ] Sweep recent specs/handoffs for stress-test sections that conclude with universal proposal survival; flag for re-review.
