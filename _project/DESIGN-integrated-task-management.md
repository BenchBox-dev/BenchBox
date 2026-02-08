# Design: Integrated Task Management

> Unifying BenchBox TODOs, Beads concepts, and Claude Code Tasks into a
> coherent three-layer system.

## Problem Statement

The current TODO system is **rich but flat**. Each YAML item embeds a
deeply nested `tasks.phases[].items[].subtasks[]` tree that agents must
read, mentally flatten, figure out where work left off, and decide what
to do next. There is no computable "ready queue" — agents parse prose.
Dependencies between TODO items exist as file paths in a loosely-typed
`dependencies` object with inconsistent field naming across 32 items.

Meanwhile, Claude Code Tasks (the `TodoWrite` tool) provide excellent
real-time session tracking but are ephemeral — they vanish when the
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
│  Strategic — persistent — rich context & guardrails  │
│  "What needs to happen and why"                      │
├─────────────────────────────────────────────────────┤
│  Layer 2: Work Units (flat list within YAML)        │
│  Tactical — dependency-ordered — small & concrete    │
│  "What to do next, in what order"                    │
├─────────────────────────────────────────────────────┤
│  Layer 3: Claude Code Tasks (TodoWrite)             │
│  Operational — session-scoped — real-time display    │
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
nothing equivalent. This is your competitive advantage — keep it.

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
  blocks: ["cloud-platform-comparison"]        # These can't start until I'm done
```

- Uses slugs (stable IDs), not file paths
- Two keys only: `needs` (inbound) and `blocks` (outbound)
- `related` moves to metadata (it's informational, not structural)
- Both keys are optional lists

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
- `done` is boolean — no "in progress" or "blocked" at subtask level
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
    done: true

  - id: w2
    summary: "Implement token-based auth (env var + config file)"
    needs: [w1]
    done: true

  - id: w3
    summary: "Handle md: connection string syntax"
    needs: [w1]
    done: false

  - id: w4
    summary: "Unit tests with mocked connection"
    needs: [w2, w3]
    done: false

deferred:
  - summary: "Cloud storage upload loading strategy"
    reason: "Requires MotherDuck cloud storage setup"
  - summary: "Integration tests with live MotherDuck account"
    reason: "Requires credentials not available in CI"
```

### Work unit properties

| Field     | Type       | Required | Description                           |
|-----------|------------|----------|---------------------------------------|
| `id`      | string     | yes      | Unique within this TODO item (w1-w99) |
| `summary` | string     | yes      | One-line description of the work      |
| `needs`   | list[str]  | no       | IDs of work units this depends on     |
| `done`    | bool       | yes      | Whether this unit is complete         |
| `notes`   | string     | no       | Implementation notes or context       |

### Deferred items

Items that are known but explicitly not in scope move to a separate
`deferred` list. This declutters the work DAG — agents don't waste
tokens parsing items they can't act on.

| Field     | Type   | Required | Description                      |
|-----------|--------|----------|----------------------------------|
| `summary` | string | yes      | What was deferred                |
| `reason`  | string | yes      | Why it's deferred                |

### Computable ready queue

A work unit is **ready** when:
1. `done: false`
2. All items in `needs` have `done: true` (or `needs` is empty)

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
4. On each completion → update YAML (done: true) + TodoWrite (completed)
5. Session end → commit YAML changes
```

### Example session

Agent picks up `motherduck-platform-adapter`. YAML has `w3` and `w4`
ready (w1, w2 already done; w4 needs w3 so only w3 is truly ready).

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

Agent completes w3, updates YAML (`w3.done: true`), marks w3 completed
in TodoWrite, moves w4 to in_progress. This is the natural rhythm
agents already follow — the design just makes the layers explicit.

### Session boundary protocol (Beads-inspired)

At session end, the agent must:

1. Update all completed work unit `done` flags in the YAML
2. If all work units are done → set TODO `status: Completed`,
   add `completed_date`, move to DONE tree
3. If work remains → leave TODO `status: In Progress`
4. Commit the YAML changes
5. Optionally: add new work units discovered during implementation

This is Beads' "land the plane" concept adapted for your system. The
YAML is the persistent memory that survives session boundaries.

---

## Dependency Tracking Between TODO Items

### Current state (inconsistent)

Across 32 items with dependencies, the field usage is:
- `dependencies.related` (most common) — informational links
- `dependencies.blocked_by` (4 items) — actual blocking relationships
- `dependencies.blocks` (template only) — never used in practice
- `dependencies.dependencies` (some items) — redundant nesting

### New model

```yaml
deps:
  needs: ["fix-dataframe-parameter-parity"]
  blocks: ["cloud-platform-comparison"]
```

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
# Updates w3.done=true in YAML
# Reports: w4 is now ready (all deps satisfied)
# If all work units done: prompts to complete the TODO item
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
    required: [id, summary, done]
    properties:
      id:
        type: string
        pattern: "^w[0-9]{1,2}$"
      summary:
        type: string
        minLength: 5
        maxLength: 200
      needs:
        type: array
        items:
          type: string
      done:
        type: boolean
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
    blocks:
      type: array
      items:
        type: string
  additionalProperties: false
```

### Backward compatibility

- `tasks` field: accepted but deprecated (validator warns)
- `dependencies` field: accepted but deprecated (validator warns)
- Migration script converts both to new format

---

## Migration

### Automated conversion: `migrate_to_work_units.py`

For each TODO item with `tasks.phases`:

1. Flatten phases → items → subtasks into a linear list
2. Assign IDs: `w1`, `w2`, ..., `wN`
3. Infer dependencies from phase ordering:
   - Items in Phase 2 `needs` last item in Phase 1
   - Subtasks `needs` their parent item
4. Items with `done: false` and `notes` containing "Deferred" → move to
   `deferred` list
5. Write `work` list, remove `tasks` block
6. Add `id` field from filename slug

For `dependencies` → `deps`:

1. `blocked_by` → `deps.needs` (convert paths to slugs)
2. `blocks` → `deps.blocks` (convert paths to slugs)
3. `related` → `metadata.related` (informational, not structural)
4. `dependencies` (flat list) → `metadata.related`

### Manual review needed

- Phase dependency inference may be too conservative or too loose
- Some items have complex inter-phase relationships
- 3 "In Progress" items should be reviewed for accurate work unit status

### Rollout plan

1. Write migration script
2. Run on a copy, diff against originals
3. Review the 3 In Progress items manually
4. Apply to real files
5. Update schema, template, CLI, skill definition
6. Regenerate indexes
7. Commit as single atomic change

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
   f. Commit code changes
7. Session end:
   a. If all work done → complete the TODO item, move to DONE
   b. If work remains → ensure YAML reflects current state
   c. Commit YAML changes
```

### `list` / `create` / `review` actions

Largely unchanged. `create` generates items with `work` instead of
`tasks.phases`. `review` scoring adds a "Work Breakdown" dimension
(are units well-sized? are dependencies accurate?).

---

## What We Took From Each System

| Concept                        | Source    | Adaptation                              |
|--------------------------------|-----------|----------------------------------------|
| Flat dependency DAG            | Beads     | `work[].needs` within items            |
| Ready queue (`bd ready`)       | Beads     | `todo_cli.py ready` + `next`           |
| Stable IDs for cross-refs      | Beads     | `id` field matching filename slug      |
| Session boundary protocol      | Beads     | "Land the plane" → commit YAML at end  |
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
| `--claim` atomics        | Beads  | Single-agent workflow; no race conditions   |
| Persistent Tasks         | CC     | Session-scoped is correct for this layer    |
| JSONL export             | Beads  | YAML indexes serve the same role            |

---

## Index Enhancements

### New index: `by-ready.yaml`

```yaml
generated_at: '2026-02-08T...'
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
    blocked_by: ["fix-dataframe-parameter-parity"]
    reason: "1 unresolved dependency"
```

This is the index agents read first. Instead of loading `by-priority`
and mentally filtering, they get a pre-computed action list.

---

## Summary

The integrated system keeps your TODO items as the strategic layer
(what Beads can't do), adds Beads' best idea (computable dependency
DAG with a ready queue), and uses Claude Code Tasks as the operational
layer (real-time session display). No new infrastructure. No new
databases. Just a flatter internal structure, stable IDs, normalized
dependencies, and three new CLI commands.

The work breakdown changes from "read a nested tree and figure it out"
to "run `next <slug>` and get a list." That's the core improvement.
