# Design: Integrated Task Management

> Unifying BenchBox TODOs, Beads concepts, and Claude Code Tasks into a
> coherent three-layer system.

## Problem Statement

The current TODO system is **rich but flat**. Each YAML item embeds a
deeply nested `tasks.phases[].items[].subtasks[]` tree that agents must
read, mentally flatten, figure out where work left off, and decide what
to do next. There is no computable "ready queue" - agents parse prose.
Dependencies between TODO items exist as file paths in a loosely-typed
`dependencies` object with inconsistent field naming across 32 items.

Meanwhile, Claude Code Tasks (the `TodoWrite` tool) provide excellent
real-time session tracking but are ephemeral - they vanish when the
session ends. And Beads has proven that a dependency DAG with a `ready`
command dramatically reduces agent cognitive load.

**Goal**: Keep the strategic richness of YAML TODOs. Add Beads-style
dependency tracking. Make the internal work breakdown directly mappable
to Claude Code Tasks.

---

## Design: Three Layers

```
┌─────────────────────────────────────────────────────┐
│  Layer 1: TODO Items (YAML files)                   │
│  Strategic - persistent - rich context & guardrails  │
│  "What needs to happen and why"                      │
├─────────────────────────────────────────────────────┤
│  Layer 2: Work Units (flat list within YAML)        │
│  Tactical - dependency-ordered - small & concrete    │
│  "What to do next, in what order"                    │
├─────────────────────────────────────────────────────┤
│  Layer 3: Claude Code Tasks (TodoWrite)             │
│  Operational - session-scoped - real-time display    │
│  "What I'm doing right now"                          │
└─────────────────────────────────────────────────────┘
```

Each layer has a clear owner, lifecycle, and purpose. They compose
rather than compete.

---

## Layer 1: TODO Items (unchanged, with targeted improvements)

### What stays exactly as-is

All required fields, all guardrail fields, all context fields:

```yaml
# Required
title, worktree, priority, status, description

# Guardrails
must_preserve, approach, anti_patterns, verification, scope_limit

# Context
category, impact, files_affected, context_sections,
technical_requirements, metadata, success_metrics, open_questions
```

These are the strategic backbone. They tell agents *why* this work
matters, *what not to break*, and *how to approach it*. Beads has
nothing equivalent. This is your competitive advantage - keep it.

### What changes

**1. Add stable `id` field (required)**

```yaml
id: motherduck-platform-adapter   # matches filename slug
```

Every item gets a stable identifier that matches its filename slug.
Cross-references use these IDs instead of file paths. This decouples
identity from directory structure (so moving `planning/ → active/`
doesn't break references).

**2. Normalize `deps` field (replaces `dependencies`)**

```yaml
deps:
  needs: ["fix-dataframe-parameter-parity"]   # I can't start until these are done
```

- Uses slugs (stable IDs), not file paths
- Single source of truth: store only inbound `needs`
- Reverse edges (`blocks`) are computed by CLI/index generation, never authored
- `related` moves to metadata (it's informational, not structural)
- `needs` is an optional list

Why this matters: `todo_cli.py ready` can now compute which items have
all `needs` satisfied without parsing prose or resolving file paths.

**3. Replace `tasks.phases` with flat `work` list (Layer 2)**

See next section.

---

## Layer 2: Work Units

### The problem with phases

Current structure:
```yaml
tasks:
  phases:
    - phase: "Phase 1: Adapter Structure"
      done: true
      items:
        - summary: "Create motherduck.py"
          done: true
          subtasks:
            - summary: "Support md:database_name syntax"
              done: true
            - summary: "Handle database creation if not exists"
              done: false
              notes: "Deferred"
```

Issues:
- 3 levels of nesting that agents flatten mentally anyway
- `done` is boolean - no "in progress" or "blocked" at subtask level
- Phase ordering is implicit (Phase 1 before Phase 2) not encoded
- Adding a task between phases requires restructuring
- Deferred items are tracked as `done: false` with notes, polluting
  the work list
- An agent resuming work must scan every phase to find incomplete items

### The replacement: flat work units with dependency edges

```yaml
work:
  - id: w1
    summary: "Create MotherDuck adapter class with DuckDB inheritance"
    status: done

  - id: w2
    summary: "Implement token-based auth (env var + config file)"
    needs: [w1]
    status: done

  - id: w3
    summary: "Handle md: connection string syntax"
    needs: [w1]
    status: in_progress

  - id: w4
    summary: "Unit tests with mocked connection"
    needs: [w2, w3]
    status: pending

deferred:
  - summary: "Cloud storage upload loading strategy"
    reason: "Requires MotherDuck cloud storage setup"
  - summary: "Integration tests with live MotherDuck account"
    reason: "Requires credentials not available in CI"
```

### Work unit properties

| Field     | Type       | Required | Description                               |
|-----------|------------|----------|-------------------------------------------|
| `id`      | string     | yes      | Unique within this TODO item (w1-w999)    |
| `summary` | string     | yes      | One-line description of the work          |
| `needs`   | list[str]  | no       | IDs of work units this depends on         |
| `status`  | enum       | yes      | `pending` \| `in_progress` \| `blocked` \| `done` |
| `notes`   | string     | no       | Implementation notes or context           |

### Deferred items

Items that are known but explicitly not in scope move to a separate
`deferred` list. This declutters the work DAG - agents don't waste
tokens parsing items they can't act on.

| Field     | Type   | Required | Description                      |
|-----------|--------|----------|----------------------------------|
| `summary` | string | yes      | What was deferred                |
| `reason`  | string | yes      | Why it's deferred                |

### Computable ready queue

A work unit is **ready** when:
1. `status` is `pending` (or `in_progress` when resuming same unit)
2. All items in `needs` have `status: done` (or `needs` is empty)
3. The work graph has no cycles (validated by CLI/schema checks)

This is the Beads `bd ready` concept, applied within a single TODO item.
No prose parsing. No phase scanning. A simple graph traversal.

### Sizing guidance

Each work unit should be completable in a single Claude Code session
(roughly 1-4 hours of agent work). If a unit is too large, split it.
If it's too small (< 15 minutes), merge it with a neighbor.

This sizing is what makes Layer 2 → Layer 3 mapping clean: one work
unit becomes one or two Claude Code Tasks.

---

## Layer 3: Claude Code Tasks (TodoWrite)

### How the mapping works

When an agent starts implementing a TODO item:

```
1. Read YAML → identify ready work units
2. Create TodoWrite tasks from ready units
3. Work through them (one in_progress at a time)
4. On each completion → update YAML (`status: done`) + TodoWrite (completed)
5. Session end → reconcile status and commit code+YAML together
```

### Example session

Agent picks up `motherduck-platform-adapter`. YAML has `w3` ready and
`w4` blocked (w1, w2 are done; w4 still needs w3).

```python
# Agent creates TodoWrite tasks:
TodoWrite([
    {"content": "Handle md: connection string syntax (w3)",
     "activeForm": "Implementing md: connection string handling",
     "status": "in_progress"},
    {"content": "Unit tests with mocked connection (w4)",
     "activeForm": "Writing unit tests for MotherDuck adapter",
     "status": "pending"},
])
```

Agent completes w3, updates YAML (`w3.status: done`), marks w3 completed
in TodoWrite, moves w4 to in_progress. This is the natural rhythm
agents already follow - the design just makes the layers explicit.

### Session boundary protocol (Beads-inspired)

At session end, the agent must:

1. Update all completed work unit statuses to `done` in the YAML
2. If all work units are done → set TODO `status: Completed`,
   add `completed_date`, move to DONE tree
3. If work remains → leave TODO `status: In Progress`
4. Commit code + YAML changes in the same checkpoint commit
5. Optionally: add new work units discovered during implementation

This is Beads' "land the plane" concept adapted for your system. The
YAML is the persistent memory that survives session boundaries.

---

## Dependency Tracking Between TODO Items

### Current state (inconsistent)

Across 32 items with dependencies, the field usage is:
- `dependencies.related` (most common) - informational links
- `dependencies.blocked_by` (4 items) - actual blocking relationships
- `dependencies.blocks` (template only) - never used in practice
- `dependencies.dependencies` (some items) - redundant nesting

### New model

```yaml
deps:
  needs: ["fix-dataframe-parameter-parity"]
```

Rules:
- `deps.needs` is canonical and hand-authored
- `blocks` is derived from reverse lookup at runtime/index time
- Unknown dependency IDs fail validation
- Dependency cycles fail validation

### CLI: `todo_cli.py ready`

New command that computes the project-wide ready queue:

```bash
$ uv run _project/scripts/todo_cli.py ready

Ready to work (all dependencies satisfied):
  HIGH   motherduck-platform-adapter     (3 work units remaining)
  MEDIUM github-archive-benchmark        (8 work units remaining)
  MEDIUM nyc-taxi-benchmark-expansion    (6 work units remaining)

Blocked:
  MEDIUM implement-dataframe-benchmarks  ← needs: fix-dataframe-parameter-parity
  LOW    coverage-ci-enforcement         ← needs: 5 items (2 remaining)
```

This is the single most impactful improvement from Beads. Instead of
reading index files and mentally filtering, agents run one command and
get actionable output.

### CLI: `todo_cli.py next <slug>`

Shows the ready work units within a specific TODO item:

```bash
$ uv run _project/scripts/todo_cli.py next motherduck-platform-adapter

motherduck-platform-adapter (High, In Progress)
  Ready:
    w3  Handle md: connection string syntax
  Blocked:
    w4  Unit tests with mocked connection  ← needs: w3
  Done:
    w1  Create adapter class  ✓
    w2  Implement token auth  ✓
  Deferred:
    -   Cloud storage upload strategy (requires cloud storage setup)
```

### CLI: `todo_cli.py done <slug> <work-id>`

Marks a work unit complete and auto-cascades:

```bash
$ uv run _project/scripts/todo_cli.py done motherduck-platform-adapter w3
# Updates w3.status=done in YAML
# Reports: w4 is now ready (all deps satisfied)
# If all work units done: prompts to complete the TODO item
```

### CLI: `todo_cli.py check-graph`

Validates the global DAG and per-item work graphs:

```bash
$ uv run _project/scripts/todo_cli.py check-graph
✅ No TODO dependency cycles
✅ No work-unit cycles
✅ No dangling refs (deps.needs / work.needs)
```

---

## Schema Changes

### New fields in TODO_SCHEMA.yaml

```yaml
# Add to required fields
id:
  type: string
  pattern: "^[a-z0-9][a-z0-9-]*[a-z0-9]$"
  description: "Stable identifier matching filename slug"

# Replace 'tasks' with 'work'
work:
  type: array
  items:
    type: object
    required: [id, summary, status]
    properties:
      id:
        type: string
        pattern: "^w[0-9]{1,3}$"
      summary:
        type: string
        minLength: 5
        maxLength: 200
      needs:
        type: array
        items:
          type: string
      status:
        type: string
        enum: [pending, in_progress, blocked, done]
      notes:
        type: string

# New deferred list
deferred:
  type: array
  items:
    type: object
    required: [summary, reason]
    properties:
      summary:
        type: string
      reason:
        type: string

# Replace 'dependencies' with 'deps'
deps:
  type: object
  properties:
    needs:
      type: array
      items:
        type: string
  additionalProperties: false
```

### Backward compatibility

- `tasks` field: accepted but deprecated (validator warns)
- `dependencies` field: accepted but deprecated (validator warns)
- `work.done` boolean is accepted during migration and rewritten to `status`
- Migration scripts convert legacy formats; normal write path emits only new fields

---

## Migration

### Migration scripts (planned)

Use small, composable scripts instead of one monolith.

1. `backfill_todo_ids.py`
- Adds missing top-level `id` from filename slug
- Verifies `id == slug` and reports mismatches
- No other mutation

2. `migrate_dependencies_to_deps.py`
- Converts legacy `dependencies.blocked_by` to `deps.needs`
- Converts path references to slug IDs
- Moves informational links (`related`, legacy flat lists) to `metadata.related`
- Does not write `blocks`

3. `migrate_tasks_to_work.py`
- Converts `tasks.phases` into `work[]` with `status`
- Mapping:
  - `done: true` -> `status: done`
  - `done: false` -> `status: pending`
- Subtasks become first-class work units
- Parent/subtask edges become explicit via `needs`
- Phase boundaries are preserved as ordering hints in `notes`; no automatic cross-phase hard dependency injection
- Marks ambiguous dependency inference with `notes: "MIGRATION_REVIEW_REQUIRED"` for manual follow-up

4. `validate_task_graphs.py`
- Validates no dangling refs and no cycles in:
  - item-level `deps.needs`
  - per-item `work[].needs`
- Returns non-zero on graph integrity errors

5. `migration_report.py`
- Produces machine-readable summary:
  - files migrated
  - files requiring manual review
  - counts by transformation type

### Rollout plan (low-risk, low-churn)

1. Ship read-path compatibility first
- CLI/validators read both legacy and new formats
- Write path still emits legacy format

2. Run migration in dry-run mode
- Generate patch previews and `migration_report.json`
- No file writes in this step

3. Apply migration in batches
- Batch A: `Not Started` + `Identified`
- Batch B: `Blocked` + `Under Review`
- Batch C: `In Progress` (manual check required)

4. Run integrity gates after each batch
- `validate_todo.py --all`
- `todo_cli.py check-graph`
- Index regeneration + diff sanity check

5. Flip write path to new format
- New TODO creation writes `id`, `deps.needs`, `work[].status`
- Legacy fields still readable but deprecated with warnings

6. Remove legacy write support in a later cleanup release
- Keep legacy read support for one additional release window

---

## Updated Skill Workflow

### `implement` action (revised)

```
1. User says "implement TODO <slug>"
2. Agent runs: todo_cli.py ready → confirms item is ready
3. Agent runs: todo_cli.py next <slug> → gets ready work units
4. Agent reads full YAML for guardrails (must_preserve, anti_patterns, etc.)
5. Agent creates TodoWrite tasks from ready work units
6. For each work unit:
   a. Mark in_progress in TodoWrite
   b. Implement (respecting approach, anti_patterns, scope_limit)
   c. Run verification commands
   d. Run: todo_cli.py done <slug> <work-id>
   e. Mark completed in TodoWrite
   f. Continue to next ready unit (same session)
7. Session end:
   a. If all work done → complete the TODO item, move to DONE
   b. If work remains → ensure YAML reflects current state
   c. Commit code + YAML in one checkpoint commit
```

### `list` / `create` / `review` actions

Largely unchanged. `create` generates items with `work` instead of
`tasks.phases`. `review` scoring adds a "Work Breakdown" dimension
(are units well-sized? are dependencies accurate?).

### Skill update plan

Update these skills to prevent process drift:

1. `project-todo-sync`
- Add checks for `id`, `deps.needs`, and `work[].status`
- Enforce graph validation before reindex/commit

2. `todo-create`
- Emit only new fields (`id`, `deps.needs`, `work`, `deferred`)
- Default work-unit statuses to `pending`

3. `todo-implement`
- Run `todo_cli.py ready` then `todo_cli.py next <slug>`
- During implementation, use `todo_cli.py done <slug> <work-id>`
- End with a single checkpoint commit containing code + TODO updates

4. `todo-complete`
- Verify all `work[].status == done` before moving item to DONE
- Reject completion if unresolved dependencies remain

5. `todo-review`
- Add explicit checks:
  - no dependency cycles
  - no dangling references
  - deferred items include clear reactivation trigger text

6. `todo-cleanup`
- Add `todo_cli.py check-graph` as required pre-commit gate
- Fail cleanup if legacy fields are reintroduced in newly modified items

---

## What We Took From Each System

| Concept                        | Source    | Adaptation                              |
|--------------------------------|-----------|----------------------------------------|
| Flat dependency DAG            | Beads     | `work[].needs` within items            |
| Ready queue (`bd ready`)       | Beads     | `todo_cli.py ready` + `next`           |
| Stable IDs for cross-refs      | Beads     | `id` field matching filename slug      |
| Session boundary protocol      | Beads     | "Land the plane" → checkpoint commit for code + YAML |
| Deferred items as separate list| Beads     | `deferred` list outside the work DAG   |
| Session-scoped execution       | CC Tasks  | TodoWrite maps 1:1 from work units     |
| Real-time progress display     | CC Tasks  | TodoWrite status line during sessions  |
| Implementation guardrails      | Yours     | Kept: must_preserve, approach, etc.    |
| Rich context & metadata        | Yours     | Kept: impact, files_affected, etc.     |
| Directory lifecycle            | Yours     | Kept: planning/ → active/ → DONE/     |
| Schema validation              | Yours     | Extended for new fields                |
| Index generation               | Yours     | Extended with ready-queue index        |

---

## What We Did NOT Take

| Concept                  | Source | Why not                                     |
|--------------------------|--------|---------------------------------------------|
| SQLite database          | Beads  | YAML-in-git is simpler and already works    |
| MCP server               | Beads  | Adds infrastructure; CLI is sufficient      |
| Hash-based IDs           | Beads  | Slug-based IDs are human-readable           |
| `bd compact`             | Beads  | DONE tree already serves this purpose       |
| `--claim` atomics        | Beads  | Not required now; use graph validation + git conflict checks, revisit if concurrency increases |
| Persistent Tasks         | CC     | Session-scoped is correct for this layer    |
| JSONL export             | Beads  | YAML indexes serve the same role            |

---

## Index Enhancements

### New index: `by-ready.yaml`

```yaml
ready_items:
  - id: motherduck-platform-adapter
    priority: High
    ready_units: 1
    total_units: 4
    done_units: 2
    deferred: 2
  - id: github-archive-benchmark
    priority: Medium
    ready_units: 8
    total_units: 8
    done_units: 0
    deferred: 0

blocked_items:
  - id: implement-dataframe-benchmarks
    priority: Medium
    blocked_by: ["fix-dataframe-parameter-parity"]  # derived from deps.needs
    reason: "1 unresolved dependency"
```

This is the index agents read first. Instead of loading `by-priority`
and mentally filtering, they get a pre-computed action list.

Design note:
- `generated_at` is optional and omitted by default to reduce diff churn
- A `--include-timestamp` flag can opt in when needed for diagnostics

---

## Summary

The integrated system keeps your TODO items as the strategic layer
(what Beads can't do), adds Beads' best idea (computable dependency
DAG with a ready queue), and uses Claude Code Tasks as the operational
layer (real-time session display). No new infrastructure. No new
databases. Just a flatter internal structure, stable IDs, normalized
dependencies, graph integrity checks, and focused CLI commands.

The work breakdown changes from "read a nested tree and figure it out"
to "run `next <slug>` and get a list." That's the core improvement.
