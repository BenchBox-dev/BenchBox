---
id: 2026-05-03-081920-uat-cross-scale-deliverable-not-guarded
date: 2026-05-03
status: open
finding_kind: framework-gap
review_context: "code review of completed TODO _project/DONE/main/active/results-explorer-uat-multi-scale-corpus-sweep.yaml (W6 cross-scale UX deliverable)"
related_paths:
  - _project/DONE/main/active/results-explorer-uat-multi-scale-corpus-sweep.yaml
  - _project/handoffs/results-explorer-uat-retrospective-20260502.md
suggested_sweep: "before the next UAT sweep, require an explicit cross-scale exercise checklist that the W6 report must check off, not just a free-form findings list"
todo_id: null
---

# UAT framework declared a headline deliverable but never enforced that it was exercised

## Finding

W6's stated highest-signal goal was "defects you would NOT have found without
a multi-scale multi-platform corpus" — i.e. cross-scale comparison UX. The
four W6 findings are all minor/nit and none are about cross-scale views
specifically. With only 9 DuckDB bundles surviving validation across 3
scales, true cross-scale comparison was likely under-tested.

## Why this matters

UAT TODOs that declare a "headline deliverable" via prose but rely on the
agent's free-form report to demonstrate coverage have no failsafe when the
agent's exploration drifts to easier surfaces (mechanics, accessibility,
mobile drawer) and away from the harder one. The report comes back full of
real findings — they're just not findings against the headline axis. The
absence is invisible in the W7 review because every section has content.

This generalises beyond UAT. Any TODO whose value proposition rests on a
specific cross-cutting surface (cross-scale, cross-platform, cross-region,
cold-vs-warm, before-vs-after) needs an enumerated coverage checklist the
final report explicitly answers, not a prose ask the agent might honor.

## Suggested next steps

- [ ] For the next UAT, add an enumerated cross-scale checklist (e.g. "for at least 3 platforms, open the same benchmark at SF=0.01/0.1/1.0 and capture cross-scale comparison findings") to W6 work unit notes.
- [ ] Update `_project/TODO_ENTRY_TEMPLATE.yaml` (or a UAT-specific subtemplate) so headline deliverables are declared as `success_metrics` entries with measurable coverage commands, not prose-only goals.
- [ ] Audit other in-flight UAT-style TODOs (e.g. `external-contributor-submission-dry-run`) for the same pattern and decide whether to retrofit explicit coverage checklists.
