---
id: 2026-05-07-211858-release-readiness-against-pre-merge-tree
date: 2026-05-07
status: actionable
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

## Recommended actions

Step #1 is already tracked by TODO
`_project/TODO/main/planning/results-explorer-token-scan-ci-gate.yaml`
(adds a CI gate against raw Tailwind palette literals under
`results-explorer/src`). The remaining gaps need their own work:

1. **Stamp `develop` SHA into release-readiness audits.**
   Modify the capture flow that emits
   `_project/audits/results-explorer-retheme-final-<date>.md` (and the
   sibling `release-final.spec.ts` capture under
   `results-explorer/e2e/captures/`) to record the `develop` SHA the
   capture was generated against. Concretely:
   - Extend the capture spec / its driver to call
     `git rev-parse origin/develop` at run-start and inject it into the
     screenshot manifest and audit frontmatter (e.g. a new
     `develop_sha:` field).
   - Add a CI job that compares that recorded SHA against the merge
     target's tip and refuses a "READY" verdict if they diverge.
   - Wire the gate into the existing `results-explorer/src` path filter
     so it only runs when the explorer surface changes.

2. **Generalize the SHA stamp to every structured `_project/audits/`
   report.** The retheme audit is one instance of a class — security
   reviews, performance baselines, docs migrations, etc. all have the
   same exposure.
   - Add a tiny helper script under `_project/scripts/` (e.g.
     `audit_sha_check.py`) that parses an audit's frontmatter for a
     `develop_sha:` field and exits non-zero if missing or stale
     relative to a passed-in target SHA.
   - Add a `make audit-sha-check FILE=…` target that wraps the script.
   - Backfill `develop_sha:` into every existing `_project/audits/*.md`
     via `_project/scripts/audit_sha_backfill.py` (idempotent, derives
     the SHA from the introducing commit) so the validator can enforce
     uniformly without grandfathering.
   - Document the requirement in the closest audit-authoring doc (likely
     `docs/operations/results-explorer-qa.md` for now, with a note that
     the contract applies to all `_project/audits/` reports).
   - Add a CI hook on `_project/audits/**` so any new audit landing
     without a `develop_sha:` is blocked at PR time.

3. **Re-run the release-final capture against post-#271 develop tip.**
   PR #271 (`274a4a11e`) closed the literal regression, but the
   2026-05-07 audit and screenshot set under
   `_project/audits/screenshots/results-explorer-retheme-final-2026-05-07/`
   still describe the pre-#271 tree. Regenerate the audit and capture
   on top of the current `develop` and replace the 2026-05-07 artifact
   in place via `git mv` (rename to a fresh dated path so `git log
   --follow` recovers the pre-#271 verdict for post-mortems), stamping
   the new artifact with `develop_sha:` per #1.

## Triage log

- 2026-05-08: actionable — Re-verified 2026-05-08: PR #271 (274a4a11e) closed the immediate token regression but next steps #2 (capture/develop-SHA gate), #3 (generalize SHA stamp to all _project/audits/ reports), and #4 (re-run release-final capture against post-#271 develop tip) remain. Next step #1 already tracked by TODO results-explorer-token-scan-ci-gate.
- 2026-05-08: actionable — commits: implementation branch `chore/explorer-audit-sha-gate` closes the generalized develop-SHA gate path via TODO `audit-develop-sha-stamping-and-ci-gate`; post-#271 recapture remains tracked separately by TODO `results-explorer-retheme-recapture-against-post-271-develop`.
