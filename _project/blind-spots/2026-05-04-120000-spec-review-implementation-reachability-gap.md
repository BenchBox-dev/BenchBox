---
id: 2026-05-04-120000-spec-review-implementation-reachability-gap
date: 2026-05-04
status: open
finding_kind: framework-gap
review_context: "/code review of W1 spec _project/specs/uat-framework.md on branch feat/uat-framework-w1-spec"
related_paths:
  - _project/specs/uat-framework.md
  - _project/TODO/main/active/uat-framework-tests-uat-runner.yaml
suggested_sweep: "add an implementation-reachability axis to multi-W spec reviews; flag any W estimated >300 LOC pre-approval"
todo_id: null
---

# Spec reviews don't rate whether 11-W vertical slices are actually deliverable

## Finding

The five-axis review framework (correctness, completeness, consistency,
reviewability, adversarial honesty) rates a multi-work-unit spec's text
against its W1 requirements but does not rate **implementation
reachability** — whether the proposed work units can actually be
delivered as one-PR-per-W vertical slices given the LOC distribution
the spec implies. For the UAT framework spec, the review noted ~1,500
LOC across 13 modules and 11 work units, with W4 alone bundling
preflight + enumerate + execute + cleanup + ladder (estimated ~580
LOC, the largest single W). The framework asserts vertical-slice
discipline; the review framework has no axis for "does the slicing
actually slice?"

## Why this matters

Spec reviews catch logical and structural issues; they don't catch
deliverability problems that only surface during W2-W11 implementation.
A spec that passes review can still produce a W4 PR that's so large
it bypasses meaningful review or gets split mid-flight, eroding the
vertical-slice promise the spec made. The reviewer at W1 is the only
reliable gate for catching unreachable slicing — by W4 the LOC has
already been written and the cost of restructuring is high.

This is a generic gap in spec-shaped reviews, not specific to UAT
framework work. Any spec that proposes a multi-work-unit decomposition
(framework specs, refactor plans, migration specs) is exposed.

## Suggested next steps

- [ ] Add an "implementation reachability" check to multi-work-unit spec reviews: estimate LOC per W from the spec's module/responsibility breakdown, flag any W estimated >300 LOC pre-approval, ask the spec author to split before sign-off rather than mid-implementation.
- [ ] Consider whether the L2 audit prompt for multi-W specs should include LOC distribution as a default question (alongside the existing axes).
- [ ] If the UAT framework W4 hits >500 LOC during implementation, treat that as confirming evidence for this finding and promote to a TODO that revises the spec-review framework.
