---
id: 2026-05-04-074634-todo-implement-time-freshness-drift
date: 2026-05-04
status: merged-to-todo
finding_kind: framework-gap
review_context: "/todo review retire-sqlglot-duckdb-all-workaround"
related_paths:
  - _project/TODO/main/planning/retire-sqlglot-duckdb-all-workaround.yaml
  - _project/sqlglot-upstream/repros/repro_all.py
  - .claude/skills/todo/SKILL.md
suggested_sweep: "consider adding a 'verify research findings still hold' step at the start of any TODO whose safety hinges on an upstream third-party state — check across the planning/ backlog for similar shape (upstream-fix retirements, dependency-floor bumps, deprecated-warning sweeps)"
todo_id: todo-skill-evidence-durability-conventions
---

# TODO review rubric does not score implement-time freshness drift

## Finding
The /todo review rubric (clarity / completeness / actionability / freshness /
guardrails / work-breakdown) scores write-time quality. It does not capture
whether the *prerequisite evidence* a TODO depends on is still valid at
implement time.

`retire-sqlglot-duckdb-all-workaround` rests on a single PASS observation
from `_project/sqlglot-upstream/repros/repro_all.py` against
`sqlglot==30.6.0`. If the TODO sits in `planning/` for weeks or months, the
evidence may decay in three ways the rubric does not surface:

1. A new sqlglot major (>=31.0.0) lands; the upper-cap `<31.0.0` becomes the
   harder constraint than the floor bump and may itself need re-validation
   before the helper is removed.
2. The repro script could be edited (paths, fixtures, expectations) and the
   "PASS" the TODO description quotes may no longer reproduce verbatim.
3. `uv lock` (in w2) pulls *current* sqlglot, not 30.6.0; if a regression is
   introduced upstream between 30.6.0 and the version `uv lock` resolves, w5's
   live regression is the only safety net.

The TODO has thorough guardrails for *the deletion order* (floor first, then
delete, then docs) but no instruction to re-run the repro harness against the
*resolved* sqlglot version at the start of implementation, which is what
links write-time evidence to implement-time reality.

## Why this matters
Any TODO whose safety predicate is "an external project's behavior at write
time" carries this drift risk. The rubric scores the *quality of the artifact*;
it has no axis for *the durability of its assumed inputs*. This is a
framework gap, not a defect of this specific TODO. The same gap will recur on
every "retire workaround once upstream lands fix" task, every "remove
deprecation warning once Python X.Y is dropped" task, and every "narrow
dependency cap once upstream stabilizes" task.

A simple convention would close it: a `freshness_check` field (or a
conventionally-named first work unit) that re-runs the original evidence
against the *current* dependency snapshot before any code is touched.

## Suggested next steps
- [ ] Decide whether to add an optional `freshness_check` block to the TODO
      schema (or a strong-convention "w0: re-validate research evidence" first
      work unit) for upstream-dependent items.
- [x] In-scope nudge for `retire-sqlglot-duckdb-all-workaround`: applied as
      `w0` (re-run `repro_all.py` against the version `uv` resolves, gating
      `w1`) plus a matching `anti_pattern` and a second `verification` entry
      (unpinned harness check). Captured in the same PR as this finding.
- [ ] Sweep planning/ for sibling TODOs that retire workarounds once an
      upstream fix lands; if 2+ exist, the schema-level convention above pays
      for itself.

## Triage log

- 2026-05-05: actionable (sweep). Partially advanced: the in-scope nudge for
  `retire-sqlglot-duckdb-all-workaround` landed (TODO now in DONE/).
  Schema-level `freshness_check` field and TODO-skill rubric updates have
  not shipped. Carry forward steps 1 and 3.
- 2026-05-05: promoted to TODO `todo-skill-evidence-durability-conventions`
