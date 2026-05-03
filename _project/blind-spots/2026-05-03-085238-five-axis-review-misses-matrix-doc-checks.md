---
id: 2026-05-03-085238-five-axis-review-misses-matrix-doc-checks
date: 2026-05-03
status: open
finding_kind: framework-gap
review_context: "/code review of W1+W2 commit dbfbdcf04 (results-explorer-uat-corpus-integrate-validated-bundles), branch feat/results-explorer-uat-corpus-validated-bundle"
related_paths:
  - _project/handoffs/results-explorer-uat-corpus-integration-20260503.md
  - .claude/skills/code/references/five-axis-review.md
suggested_sweep: "Add a 'matrix/audit doc' branch to the /code review checklist that mandates regenerate-from-source diffing and an alternatives-considered section."
todo_id: null
---

# Five-axis review skips matrix arithmetic and alternatives in audit docs

## Finding

The five-axis review framework (Correctness, Readability, Architecture, Security,
Performance) under-weights two dimensions when the deliverable under review is a
**curation/audit document whose contents are tables of numbers**, not code:

1. **Quantitative auditability of the audit itself.** Five-axis "Correctness"
   reads as "is the reasoning sound?" not "do the numbers in the tables match
   the underlying source data?" The W2 review surfaced three quantitative errors
   (tpcds cohort row claimed 3 bundles vs actual 2; total-exclusion line claimed
   18 vs actual 17; "stages ~185" vs actual 188) that the framework caught only
   because the reviewer ran a manual `uv run -- python` regeneration pass against
   the bundle directory. Without that explicit "regenerate-from-source-and-diff"
   step, narrative review would have signed off the doc as correct.

2. **Forward-coupling to downstream policy decisions.** The audit decided
   exclusions (9 cohorts blocked by the `validate_corpus.py` ≥3-platform gate)
   but did not weigh the alternative (relax the gate) or quantify what the
   corpus would look like under each path. A reviewer evaluating the curation
   could not tell from the doc whether the chosen exclusion path was the only
   reasonable path or one of several.

## Why this matters

For docs whose deliverable IS a matrix, narrative review is structurally
incapable of catching arithmetic drift — only mechanical regeneration is.
Likewise, when an audit's recommendation depends on a policy gate, the gate
becomes load-bearing and the doc owes the reader a quantified comparison of
what alternatives would yield. Both are easy to miss because the standard
review rubric is code-centric.

## Suggested next steps

- [ ] Add a "matrix/audit doc" branch to `.claude/skills/code/references/five-axis-review.md` (or the project review checklist) that requires regenerate-from-source diffing of every numeric claim before sign-off.
- [ ] Add an "Alternatives considered" requirement to the audit-doc template/protocol when the audit's recommendation depends on a policy gate (corpus validator depth, contract-validator strictness, etc.).
- [ ] Sweep `_project/handoffs/` for any prior audit doc whose tables were never regenerate-diffed; spot-check representative ones.
