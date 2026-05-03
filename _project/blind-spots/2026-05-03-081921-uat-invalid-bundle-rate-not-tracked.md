---
id: 2026-05-03-081921-uat-invalid-bundle-rate-not-tracked
date: 2026-05-03
status: open
finding_kind: missed-axis
review_context: "code review of completed TODO _project/DONE/main/active/results-explorer-uat-multi-scale-corpus-sweep.yaml (W5 submission flow validation)"
related_paths:
  - _project/DONE/main/active/results-explorer-uat-multi-scale-corpus-sweep.yaml
  - _project/DONE/main/active/results-explorer-uat-defect-normalized-cost-unavailable-bundles.yaml
  - _project/DONE/main/active/results-explorer-uat-defect-zero-query-timing-bundles.yaml
suggested_sweep: "treat 'attempted-pass-but-validator-rejected' as its own corpus-quality metric and add it to UAT success_metrics with an explicit budget"
todo_id: null
---

# UAT triaged failures per-cluster but never tracked the overall invalid-bundle rate as a methodology metric

## Finding

W5 full-package validation rejected 171 of 376 packaged bundles
(~45 percent). The two corpus-integrity TODOs (#141 normalized-cost,
#143 zero-query-timing) treat this as a contract/platform issue, but the
rate itself suggests sweep configuration may have systematically produced
unsubmittable results — that's a process finding worth surfacing separately.

## Why this matters

The UAT triage rubric (W4) classifies failures by exit/error class:
trivially fixable, environmental, deferred-engineering. None of those buckets
capture "the run technically passed but the artifact it produced cannot be
submitted." That category is structurally different — it represents
*silent corpus pollution*, where success is overcounted at run time and the
real cost shows up only at validation time.

When ~45% of "passed" cells produce unsubmittable bundles, the headline
W3 success counts (434 passed of 527 attempted, ~82%) overstate corpus
health by ~2x. Future UATs should treat the "passed-but-rejected" rate as
its own first-class methodology metric with an explicit budget — both as a
go/no-go gate before publication and as a signal that the success metric
language is failing to track what actually matters.

## Suggested next steps

- [ ] Add a "validator-clean rate" metric to UAT `success_metrics`: e.g. ">=80% of W3-passed cells produce bundles that pass `scripts/validate_submission.py`."
- [ ] Capture the rate per-platform and per-benchmark in the W7 report — clusters with low validator-clean rates are higher-priority defect targets than clusters with low W3-pass rates.
- [ ] Reconsider whether `--phases load,power` plus default validation is the right floor for a UAT corpus when so many bundles fail downstream contract validation; possibly add a pre-submission validator pass to W3 itself.
