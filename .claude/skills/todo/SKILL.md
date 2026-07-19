---
name: todo
description: Use when the user asks to "ideate on an idea", "refine an idea", "brainstorm", "write a spec", or "create a specification". Idea -> spec authoring that precedes tracked work; all TODO tracker actions (create/claim/implement/complete/defer/batch/...) belong to the `todo-db` skill.
version: 0.7.0
tools: Bash, Read, Edit, Write, Task
---

# Idea → Spec Authoring

Diverge on an idea, converge to a decision-ready spec — the thinking that
happens *before* anything enters the tracker. All tracker state (create,
claim, implement, verify, complete, defer, batch, review, ...) belongs to the
`todo-db` skill; this skill never writes tracker state.

## Actions

| Action | Trigger | Contract |
|---|---|---|
| `ideate` | "ideate", "refine idea", "brainstorm" | Diverge/converge on ideas, surface and stress-test assumptions |
| `spec` | "write spec", "create specification" | Produce a decision-ready spec before code |
| `help` | "help", "list actions" | Show actions |

## Action Notes

- **Ideate:** restate as the problem, ask only material questions, generate
  options, stress-test assumptions, recommend MVP / not-doing / open
  questions; before recommending, apply SHARED/plan-deepening-framework/SKILL.md
  L3 and the L2 missed-dimension question inline, note any reframe; save only
  after confirmation.
- **Spec:** state assumptions, define objective, commands, structure, style,
  tests, boundaries, success criteria, and review gate; before finalizing
  apply plan-deepening L3, include a reframe only if it changes the spec; save
  only after confirmation.
- **Prior art:** a spec for new infrastructure MUST list existing patterns
  (file paths) and reuse decisions (extend / supersede / genuinely new).

## Handoff

Once a spec is agreed, turn it into tracked work with the `todo-db` skill —
`todo create` (or its create-from-spec flow). Do not write TODO state to files
here; the tracker database is the only record.
