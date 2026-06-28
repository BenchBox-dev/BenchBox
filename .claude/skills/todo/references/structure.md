# TODO System Structure

## Config

Path resolution: explicit CLI/env root, then `todo.config.yaml`, then `_project/TODO` and `_project/DONE` at git root. Indexes under `_indexes/` are generated; never edit them manually.

## Layout

```text
{todo_root}/_indexes/
{todo_root}/{worktree}/planning/
{todo_root}/{worktree}/active/
{done_root}/_indexes/
{done_root}/{worktree}/{phase}/
```

## Item Schema

Required core fields:

```yaml
id: slug-matching-filename
title: Descriptive title
worktree: branch-or-area
priority: Critical|High|Medium-High|Medium|Low
status: Not Started|In Progress|Blocked|Completed
description: |
  Why this exists.
category: Core Functionality
work:
  - id: w1
    summary: First unit
    status: pending|in_progress|done
    needs: []
deferred:
  - summary: Out-of-scope work
    reason: Why deferred
deps:
  needs: [other-item-slug]
```

Implementation guardrails for code items: `must_preserve`, `approach`, `anti_patterns`, `verification`, `scope_limit`. Make them specific or omit risk-only fields.

## Semantics

- `work[].needs` orders work units inside one item.
- `deps.needs` links item slugs.
- A work unit is ready when `status: pending` and all `needs` are done.
- Work units should fit one focused agent session.

## Commands

Use project wrapper or:

```bash
todo-cli list|show|stats|ready|next|done|check-graph
todo-validate {path}
todo-index
```

Validate schema and graph after edits; regenerate indexes after changes.
