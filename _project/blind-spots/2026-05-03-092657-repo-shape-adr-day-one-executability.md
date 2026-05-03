---
id: 2026-05-03-092657-repo-shape-adr-day-one-executability
date: 2026-05-03
status: open
finding_kind: framework-gap
review_context: "/code review of W1 ADR commit 2cd65cb1c (published-results-slim-down-and-corpus-mirror), branch feat/published-results-slim-and-corpus-mirror"
related_paths:
  - docs/development/adr/adr-published-results-slim-corpus-branch.md
  - .claude/skills/code/references/five-axis-review.md
suggested_sweep: "Add a 'post-change dry-run' step to the review checklist for repo-shape ADRs (branch-shape changes, CI config moves, vendoring across branches)."
todo_id: null
---

# Five-axis review skips day-1 executability for repo-shape ADRs

## Finding

For ADRs that propose **operational repository-shape changes**
(force-pushing a shared branch, vendoring scripts across branches,
changing CI behavior on a target branch), the five-axis review
framework under-weights one specific dimension: **day-1 executability**.

Five-axis "Correctness" reads "is the reasoning sound?" but doesn't
ask "if I executed the proposed end state right now using only what's
on the allowlist, does CI run?" The W1 review caught a contradictory
pair — the ADR allowlists `validate-submission.yml` but excludes
`pyproject.toml` / `uv.lock`, and the workflow uses `uv run` which
needs project metadata — only because the reviewer mentally ran the
post-change CI step against the allowlist. Without that explicit
dry-run, the ADR would have shipped internally consistent but
producing broken CI on day one.

## Why this matters

Repo-shape ADRs are uniquely prone to this failure mode: the ADR
text is self-consistent (allowlist matches stated intent, exclusions
match stated intent) but the post-change branch has to interoperate
with consumers — CI workflows, contributor flows, automation — that
the ADR doesn't itself describe. A reviewer reading the ADR in
isolation cannot catch the contradiction without explicitly walking
through each consumer against the proposed end state. The lesson
generalises: when an ADR's deliverable is a *repository state*, not a
*code change*, the review owes a mechanical dry-run, not just a
narrative-soundness check.

## Suggested next steps

- [ ] Add a "post-change dry-run" subsection to `.claude/skills/code/references/five-axis-review.md` (or the project review checklist) that fires for ADRs whose deliverable is a branch-shape change, CI config move, or cross-branch vendoring.
- [ ] The dry-run step should require the reviewer to enumerate consumers of the affected branch (CI workflows, contributor flows, automation, downstream branches) and confirm each one works against the proposed end state.
- [ ] Sweep `docs/development/adr/` for prior repo-shape ADRs and spot-check whether their proposed end states would have passed a dry-run at write time.
