---
name: agent-execution
description: Select model tiers, map reasoning effort, and dispatch delegated work through native or external agent harnesses. Use when a workflow must choose an agent model or effort level, or launch a manager, worker, or independent reviewer; do not use for direct, undelegated tool calls.
---

# Agent Execution

Use this component when another skill delegates work and needs a consistent
model tier, reasoning effort, or agent harness configuration. The calling skill
continues to own task decomposition, authorization, workspace isolation, and
acceptance criteria.

## Model Tiers

Tiers describe operating roles, not absolute quality rankings. Match models to
task complexity and risk.

*Selection Rule*: Pick the tier here. For native dispatch, choose the listed
tier model directly. When an external harness is selected, take its exact
harness-specific identifier from
[references/external-harnesses.md](references/external-harnesses.md). Default
reasoning effort to `medium`. Use maximum effort only for Tier 1 adversarial
review; use `low` for mechanical bulk work.

- **Tier 1: Strategic**
  - Models: `gpt-5.6-sol`, `claude-fable-5`, `grok-4.6`, `gemini-3.7-flash-high`
  - Usage: Strategic planning, architecture, high-risk tradeoffs, and final adversarial review.
- **Tier 2: Generalist**
  - Models: `gpt-5.6-terra`, `claude-opus-5`, `grok-4.5`, `gemini-3.7-flash-medium`, `muse-spark-1.2`
  - Usage: Management, decomposition, integration, investigation, and routine review.
- **Tier 3: Contributor**
  - Models: `gpt-5.6-luna`, `claude-sonnet-5`, `gemini-3.7-flash-low`, `gemini-3.7-flash-tiered`, `muse-spark-1.2-contributor`
  - Usage: Focused implementation, bounded research, bulk work, and parallel coverage.

## Reasoning Effort Reference

| Harness | CLI Flag / Option | Supported Values (Lowest to Highest) |
| :--- | :--- | :--- |
| **pi** | `--thinking <level>` | `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max` |
| **claude** | `--effort <level>` | `low`, `medium`, `high`, `xhigh`, `max` |
| **muse** | `--reasoning-effort <EFFORT>` | `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `ultra` |
| **agy** | `--effort <level>` | `low`, `medium`, `high` |
| **grok** | `--reasoning-effort <EFFORT>` | `low`, `medium`, `high`, `xhigh` |
| **codex** | `-c model_reasoning_effort="<level>"` | `low`, `medium`, `high`, `xhigh`, `max`, `ultra` |
| **prime-agent** | `--thinking <level>` | `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max` |

For `jcode`, `opencode`, `hermes`, `goose`, and `aider`, effort is selected via
model variants (e.g. `gemini-3.7-flash-tiered`, `:thinking` suffix) or provider
settings.

## Dispatch Rules

Treat native subagents and external harnesses as peer dispatch choices. Select
between them using the factors relevant to the assignment: task and model fit,
provider usage or capacity, cost, isolation or read-only strength, and useful
parallelism. Assign an explicit role, bounded goal, path constraints,
permission scope, success criteria, and output contract.

Choose the dispatch mode from the delegated role:

- **Manager:** select a channel only when current runtime capabilities or
  behavioral evidence verify a stable live session identity, resume or
  follow-up, live status and interrupt, and a working path to dispatch or
  coordinate Workers and Reviewers. Do not infer Manager capability from a
  one-shot Worker or Reviewer command. Invocations such as `--print`, `exec`,
  `--single`, or equivalents are not Manager-capable unless a separate verified
  continuation channel supplies every required capability; they remain valid
  Worker or Reviewer choices.
- **Worker:** use a write-capable mode only within the authorized workspace or
  sandbox. Require the repository's narrowest proving check and explicit-path
  staging; never permit `git add -A`.
- **Reviewer:** use a separate dispatch that did not author the work. Prefer a
  hard read-only sandbox or tool allowlist. A plan mode is soft read-only and
  requires explicit findings-only instructions that forbid edits, commits,
  pushes, and other mutations.

When selecting an external or headless harness, read
[references/external-harnesses.md](references/external-harnesses.md), choose the
documented command for the role, and use it directly.

Headless Worker dispatch may automate confirmations only when write scope is
already bounded by a sandbox, workspace flag, or dedicated worktree. Never add
flags that remove workspace, sandbox, or tool boundaries.

The external harness reference contains the worker and reviewer commands, model
identifiers, and hard-versus-soft read-only classifications.
