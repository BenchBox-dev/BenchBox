---
id: 2026-05-07-211858-release-readiness-against-pre-merge-tree
date: 2026-05-07
status: open
finding_kind: framework-gap
review_context: "PR #269 review (results-explorer-retheme-audit-followups) → PR #271 (results-explorer-retheme-postmerge-tokenize)"
related_paths:
  - _project/audits/results-explorer-retheme-final-2026-05-07.md
  - results-explorer/e2e/captures/release-final.spec.ts
  - results-explorer/src/pages/ResultDetail.tsx
  - results-explorer/src/pages/Compare.tsx
suggested_sweep: "before any retheme/release-readiness PR is marked READY, re-run the token scan and the release-final capture against the squash-merged develop tip, not just the PR branch"
todo_id: null
---

# Release-readiness reports generated against pre-merge tree silently miss concurrent-PR regressions

## Finding

PR #269 (`fix(explorer): address retheme release audit gaps`) authored a
release-readiness report and a `release-final.spec.ts` capture against its
own branch tree. PR #268 (`fix/pr246 result compare evidence`) merged onto
develop ~1h before #269 and introduced a new literal-styled `Result summary`
panel, `ResultMetricCard` helper, and `Compare guardrails` section in the
exact files PR #269 was tokenizing. PR #269 squash-merged onto the
now-#268-included develop, the merge resolution kept #268's literal-styled
sections, and PR #269's report still claimed READY because:

- the per-PR token scan ran against the PR branch, not the merged tree;
- the `release-final.spec.ts` capture and screenshots were generated against
  the PR branch, not the merged tree;
- CI green covered typecheck/tests/build but no token-scan gate.

The merged result on develop carried untokenized literal grays on the most
prominent panel of `/results/r/...` and on the Compare guardrails section,
contradicting the report. PR #271 closed the gap manually. The framework
has no automated gate against this class.

## Why this matters

Release-readiness reports describe a tree. If the tree the report
describes is not the tree that ships, the verdict is structurally
unreliable — even when every individual check passes. Concurrent PRs that
edit the same files are the obvious failure mode, but any post-authoring
change to develop (auto-rebases, CODEOWNER edits, hotfixes that land
between report generation and merge) produces the same gap. The report's
authority comes from coverage, and "coverage at PR HEAD" is a different
claim than "coverage on develop after merge."

This is not unique to retheme work. Any audit-style PR with a structured
report (security review, performance baseline, docs migration) has the
same exposure if the report and the merge are not regenerated together.

## Suggested next steps

- [ ] Add a token-scan gate (see TODO `results-explorer-token-scan-ci-gate`)
      that runs on every PR touching `results-explorer/src` and on develop
      after merge, so concurrent-PR regressions break CI rather than ship
      silently.
- [ ] Update the release-final capture flow to record the develop SHA the
      capture was generated from in the audit report, and add a CI job that
      refuses a "READY" verdict until the SHA matches the merge target's
      tip.
- [ ] Generalize: any structured report under `_project/audits/` should
      include the develop SHA it describes, and reviewers should refuse to
      merge a release-readiness PR whose report SHA is older than the merge
      target.
- [ ] Sweep: re-run `results-explorer-retheme-final-2026-05-07.md` with a
      capture against develop tip after PR #271 lands, so the artifact set
      reflects the shipped state.
