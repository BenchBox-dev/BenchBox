---
id: 2026-05-03-081922-uat-submit-success-metric-ambiguity
date: 2026-05-03
status: merged-to-todo
finding_kind: framework-gap
review_context: "code review of completed TODO _project/DONE/main/active/results-explorer-uat-multi-scale-corpus-sweep.yaml (W5 success_metrics + open_questions Q3)"
related_paths:
  - _project/DONE/main/active/results-explorer-uat-multi-scale-corpus-sweep.yaml
suggested_sweep: "audit UAT/dry-run TODO templates for success_metrics that conflate local-staging with upstream-publication; require open_questions that gate work to be resolved before that work begins, not deferred"
todo_id: uat-template-success-metric-terminal-state-and-gating
---

# UAT success metric "submitted via the BenchBox submission flow" did not disambiguate local-staging from upstream-publication

## Finding

The TODO success metric reads: "Result JSONs successfully submitted via the
BenchBox submission flow for the successful cells." The agent's interpretation
("submitted = packaged via `benchbox submit --output`") is reasonable but
differs from a strict "landed in `published-results`" reading. Open
Question Q3 (draft PR vs publish) was deferred rather than resolved.

## Why this matters

Two structurally different outcomes — local staging directory vs upstream
PR vs merged-to-`published-results` branch — were collapsed into one
sentence. This left the agent free to pick the lowest-risk reading
(local stage), which was probably correct given the validation failures,
but the TODO could not have *forced* a different choice if it mattered.

More general lesson: an `open_questions` block whose answer materially
changes the deliverable should not be a deferral mechanism. It either gates
the work (resolve before starting) or it gets removed (not actually
load-bearing). Q3 sat in the "deferred" position for a question that
genuinely changed the W5 deliverable, and the result is that nobody
explicitly authorised "stop at local staging." The agent inferred it from
validation evidence, which is correct judgment but not policy.

The same pattern appears (cf. `external-contributor-submission-dry-run`)
in other submission-flow TODOs. The fix is templating: success metrics for
submission flows should specify the exact terminal state ("merged to
`published-results`" / "open draft PR vs `published-results`" / "local
staging only — no upstream action") and `open_questions` that would change
that terminal state must be resolved before the relevant work unit starts.

## Suggested next steps

- [ ] Update `_project/TODO_ENTRY_TEMPLATE.yaml` so submission-related success metrics name a specific terminal state (local stage / draft PR / merged) rather than the verb "submit."
- [ ] Add a TODO-author convention: any `open_questions` entry whose answer changes a `success_metrics` entry must be marked `gating: true` and resolved before the dependent work unit starts; non-gating questions stay deferable.
- [ ] Sweep open UAT/dry-run TODOs for the "submitted via submission flow" pattern and disambiguate before they're picked up.

## Triage log

- 2026-05-03: promoted to TODO `uat-template-success-metric-terminal-state-and-gating`
