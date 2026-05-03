---
id: 2026-05-03-090105-mixed-tooling-data-pr-review-gap
date: 2026-05-03
status: open
finding_kind: framework-gap
review_context: "/code review of W3 commit eb9dcdfd9 (results-explorer-uat-corpus-integrate-validated-bundles), branch feat/results-explorer-uat-corpus-validated-bundle"
related_paths:
  - .pre-commit-config.yaml
  - .claude/skills/code/references/five-axis-review.md
  - _project/handoffs/results-explorer-uat-corpus-integration-20260503.md
suggested_sweep: "Add a 'mixed tooling+data PR' branch to the review checklist that requires per-component reversibility/blast-radius analysis and a named upstream/downstream alternative."
todo_id: null
---

# Five-axis review collapses tooling+data PRs into a single review surface

## Finding

For PRs that **bundle tooling changes with data changes**, the five-axis
review framework treats them as a single review unit when in practice they
are two distinct review surfaces. The W3 corpus-integration commit added
188 bundle JSONs (data) AND a `.pre-commit-config.yaml` exclusion (tooling).
Two specific gaps surfaced:

1. **The tooling change has different reversibility/blast-radius properties
   than the data change.** A bundle JSON can be reverted with a single
   commit; a `.pre-commit-config.yaml` exclusion affects every future commit
   project-wide. The framework doesn't ask "if the tooling change is wrong,
   what's the cleanup cost?" separately from "if the data change is wrong,
   what's the cleanup cost?"

2. **Upstream/downstream alternatives go uninspected.** The W3 fix added a
   pre-commit exclusion to bypass an EOF-normalization conflict with
   hash-pinned bundle JSONs. The root cause is that the bundle emitter does
   not write a trailing newline; an upstream fix in the emitter would make
   the band-aid unnecessary forever. The five-axis framework didn't
   naturally ask "could this fix have been made one layer up?" — for
   tooling band-aids that mask a data-emission contract weakness, the
   band-aid stays forever unless someone explicitly tracks the upstream fix.

## Why this matters

Mixed tooling+data PRs are a recurring shape (CI exclusions added so a
data file can land, hook tweaks added so a doc layout doesn't trip
linters, etc.). Treating them as one review unit lets the more durable
component (tooling) inherit the lower scrutiny appropriate to the more
disposable component (data). The lesson generalises: when a PR mixes
artefacts with very different blast radii, the review owes the reader
*per-component* reasoning, not aggregate reasoning.

## Suggested next steps

- [ ] Extend `.claude/skills/code/references/five-axis-review.md` (or the project review checklist) with a "mixed tooling+data PR" branch that requires per-component reversibility analysis and an "upstream/downstream alternative considered" line.
- [ ] When such a PR is reviewed and the upstream alternative is deferred, require a follow-up TODO id in the review output so the band-aid doesn't outlive its rationale.
- [ ] File the upstream byte-stable bundle emission TODO that this finding refers to (currently outstanding).
