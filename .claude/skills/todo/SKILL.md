---
name: todo
description: Use when the user asks to "ideate on an idea", "refine an idea", "brainstorm", "write a spec", or "create a specification". Idea -> spec authoring that precedes tracked work; all TODO tracker actions (create/claim/implement/complete/defer/batch/...) belong to the `todo-db` skill.
version: 0.7.0
tools: Bash, Read, Edit, Write, Task
---

# Idea → Spec Authoring

This is the pre-tracker thinking workflow. Route to `ideate` or `spec`; all
tracker state belongs to `todo-db`, never this skill.

## Actions

| Action | Trigger | Read |
|---|---|---|
| `ideate` | ideate/refine/brainstorm | `references/ideate.md` |
| `spec` | write/create a specification | `references/spec.md` |
| `help` | help/list actions | this table |

## Handoff

Once the spec is agreed, use `todo-db`: `todo create` (or its create-from-spec
flow). Do not write TODO state to files; the tracker database is the record.
