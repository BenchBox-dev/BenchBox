---
id: 2026-05-04-083819-w0-evidence-replay-drift
date: 2026-05-04
status: merged-to-todo
finding_kind: framework-gap
review_context: "/code review W0 / chore/retire-sqlglot-duckdb-all-workaround"
related_paths:
  - _project/sqlglot-upstream/repros/repro_all.py
  - _project/TODO/main/active/retire-sqlglot-duckdb-all-workaround.yaml
suggested_sweep: "Consider whether re-validation gates that use unpinned `uv run --with <pkg>` should always commit a transcript or pin file alongside the status flip, so a reviewer landing the PR days later can replay the same evidence."
todo_id: todo-skill-evidence-durability-conventions
---

# W0 evidence-replay drift

## Finding

The five-axis review framework (correctness/readability/architecture/security/performance)
does not have an axis for *evidence durability* on verification-only work units.

W0 in the `retire-sqlglot-duckdb-all-workaround` TODO is purely a re-validation gate: run
the unpinned harness, confirm item #1 PASSes. The instruction is "STOP and re-investigate
before w1" if the harness output drifts. But the only evidence the gate produced was a
free-text line in the commit message ("re-validated repro harness against resolved sqlglot
30.6.0"). A reviewer landing the PR later cannot replay this — `uv run --with sqlglot`
(no pin) resolves whatever is current under the cap at replay time, which may differ from
what the implementer observed.

## Why this matters

Verification-only commits are common in TODOs that retire workarounds (e.g. "confirm the
upstream fix is in the resolved version before deleting the local fixup"). When the
evidence is a transient harness output rather than a committed artifact, the safety
predicate that gated the next work unit is not auditable post-hoc. If a reviewer challenges
the conclusion days later, the implementer has to re-run the harness — and the resolved
version may have moved. This is a class of issue the five-axis rubric doesn't catch
because it scores the *change*, not the *evidence the change relied on*.

## Suggested next steps

1. **For this PR**: no action. The gap closes naturally in w1 — the floor bump pins what
   counts as "current sqlglot," so the harness is reproducible against `>=25.6.0,<31.0.0`.
2. **For sweep**: consider whether verification-only work units in TODOs should default to
   capturing a `verification_log.txt` (or similar artifact) alongside the status flip. A
   simple convention: if `verification:` lists a runnable command and the work unit's only
   output is "ran it, here's the result," commit the captured stdout under
   `_project/verification-logs/<todo-id>/<work-id>.log`.
3. **For framework**: add an axis to the review checklist for "evidence durability" on
   verification-only commits, or document that this kind of commit should always cite a
   committed artifact (lockfile, transcript, captured plan).

This is a `framework-gap` against the five-axis review rubric for verification-only
commits, not a `bug-class`. It does not block this PR.

## Triage log

- 2026-05-05: actionable (sweep). Sibling of
  `2026-05-04-074634-todo-implement-time-freshness-drift`.
  `_project/verification-logs/` does not exist; verification-only commits
  still rely on free-text commit messages. Carry forward the convention +
  framework-axis next-steps.
- 2026-05-05: promoted to TODO `todo-skill-evidence-durability-conventions`
