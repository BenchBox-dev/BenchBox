---
name: bossmode
description: Organize and execute complex multi-step work through an executive, accountable managers, focused workers, and independent review. Use when work divides across multiple parallel workstreams or requires an independent review gate.
version: 0.2.0
tools: Bash, Read, Write, Edit, Task
---

# Bossmode

Operate using this organizational structure:

```text
Executive (Loading Session Coordinator)
  -> Manager(s) (Goal Owner & Worktree Coordinator)
      -> Worker(s) (Focused Implementers in Dedicated Worktrees)
      -> Independent Reviewer (Read-Only Evaluator)
```

The loading agent session acts as coordinator (Executive and Manager). Two separations are mandatory:
1. **Worker Isolation**: A worker must not review its own work.
2. **Reviewer Independence**: The reviewer must be a separate dispatch running an enforced read-only configuration.

Use Bossmode when a goal requires parallel workstreams in separate worktrees or an explicit independent review gate. For single-file, single-symbol, or routine edits, act directly without spawning a hierarchy. Project tracking (e.g. `todo-db`, BenchBox `todo`) remains authoritative.

## Roles and Authority

### Executive
- Define outcomes, priorities, constraints, and authority boundaries.
- **Authorization Boundary**: A user request to implement authorizes repository writes within scope. A review, audit, or full-pass plan produces findings only; remediation requires a subsequent user turn (`shared-review-protocol/SKILL.md` [REVIEW-AUTH-001]). The human user holds sole authority over remote pushes, draft PRs, and destructive operations.
- Direct Managers; do not invoke worker CLIs directly.
- Accept concise summaries; do not micromanage workers.

### Manager
- Decompose goals into non-overlapping assignments with explicit boundaries and acceptance criteria.
- **Workspace Isolation**: Allocate dedicated worktrees for parallel workers (`git worktree add <path> -b bm/<goal>/<worker-n>`). Never permit concurrent writers on the same branch or workspace.
- **Tracker & Claim Safety**: Parallel workers share the single active task claim and must operate on disjoint path bounds. If the project tracker forbids concurrent workers, run them sequentially.
- Maintain proactive checkins with the Executive. Report progress when batches return or milestones pass.
- Delegate fixes back to workers. Do not act as primary implementer or independent reviewer of the same work.
- Arrange independent review before recommending acceptance to the Executive.

### Workers
- Own a single bounded assignment within an assigned worktree.
- Follow every rule in §Delegation Envelope; it is the contract under which workers are dispatched.

### Independent Review
- Structurally independent from implementation; must not have authored the reviewed work.
- **Read-Only Enforcement**: Inspect artifacts, code, and test outputs using enforced read-only modes (hard sandbox, tool allowlist, or plan mode). Never edit repository files, commit, push, or auto-merge.
- Judge work from the worker log, the worktree diff, and recorded verification output. Do not re-run mutating checks. If required evidence logs are missing, report that as a defect.
- Return concrete defect descriptions and acceptance recommendations.

## Operating Cycle

1. **Direct**: Executive defines the goal, constraints, and scope.
2. **Isolate**: Manager breaks down assignments and provisions dedicated Git worktrees for workers.
3. **Execute**: Workers run within their worktrees, execute verification ladders, and write outputs to `/tmp/bossmode/<goal>/<worker-n>.log`. Manager reports progress upon worker return.
4. **Integrate**: Manager merges worker branches into an integration branch (`bm/<goal>/integration`) without source edits. Content conflicts are delegated back to workers.
5. **Review**: A separate reviewer evaluates the integrated outcome against acceptance criteria using an enforced read-only configuration.
6. **Gate**:
   - *Review Passed*: Manager recommends acceptance to the Executive.
   - *Gaps Found*: The reviewer returns findings and stops. Manager delegates each finding to a worker as a bounded fix assignment, then re-runs step 5. After two failed correction rounds, stop and escalate outstanding findings to the Executive.
7. **Close**: Executive presents verified results to the user for final approval. After acceptance, remove worker worktrees (`git worktree remove`) and delete merged worker branches. Follow `shared-change-framework` for commit/PR close-out unless local-only.

## Checkin Loop

The Manager reports progress upward to the Executive proactively; the Executive remains event-driven and does not poll.

- **Trigger**: Report when a worker batch returns, at major milestone completions, or if a worker is blocked or exceeds its time budget.
- **Payload**:
  - *Current Focus*: Active worker IDs, assigned tasks, and worktree locations.
  - *Completed Milestones*: Steps finished and verification checks passed since last checkin.
  - *Blockers & Deviations*: Immediate obstacles, stuck workers, or unexpected failures.
  - *Next Action*: Immediate next milestone and planned next checkin event.

## Model Tiers

Tiers describe operating roles, not absolute quality rankings. Match models to task complexity and risk.

*Selection Rule*: Pick the tier here; take the exact identifier from the target harness row below. Default reasoning effort to `medium`. Use maximum effort only for Tier 1 adversarial review; use `low` for mechanical bulk work.

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

For `jcode`, `opencode`, `hermes`, `goose`, and `aider`, effort is selected via model variants (e.g. `gemini-3.7-flash-tiered`, `:thinking` suffix) or provider settings.

## Agent Dispatch

### Delegation Envelope

Every delegated prompt — native or headless — must include:
1. Exact path boundaries (do not modify files outside scope).
2. Git safety: Never run `git add -A`. Stage only modified files explicitly by path.
3. Identity safety: Adhere to `[COMMIT-IDENTITY-001]`; do not commit under synthetic or vendor agent identities (`shared-change-framework/SKILL.md`).
4. Verification: Run the repository's narrowest proving check before returning.
5. Evidence: Save command output to `/tmp/bossmode/<goal>/<worker-n>.log` and return concise status.
6. Reviewer prompts additionally state acceptance criteria, require findings-only output, and forbid edits, commits, and pushes.

Headless dispatch may suppress interactive approval prompts only when write scope is bounded by a sandbox, workspace flag, or dedicated worktree. Never pass flags that remove path or permission limits (e.g. `--permission-mode acceptEdits`, `--dangerously-skip-permissions`, `--always-approve`, or `--yolo`).

### Native Host Subagents

When running inside an environment with native subagent tooling (e.g. Antigravity `invoke_subagent`, Codex threads, Claude subagents), prefer native dispatch:
- Assign explicit roles, bounded prompts, and path constraints matching the Delegation Envelope.
- Reviewer subagents must run with read-only instructions and tools.

### Known-Good Harness Configurations

Confirm binary presence with `command -v <harness>` before dispatch.

#### Frontier Lab Harnesses

- **codex**
  - Worker (Write): `codex exec -C "$WORKSPACE" --model "$MODEL" --sandbox workspace-write "$PROMPT"`
  - Reviewer (Hard Read-Only): `codex exec -C "$WORKSPACE" --model "$MODEL" --sandbox read-only "$PROMPT"`
  - Known-good models: `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`
  - Effort: Optional `-c model_reasoning_effort="<level>"`
- **claude**
  - Worker (Write): `(cd "$WORKSPACE" && claude --print --model "$MODEL" --effort "$EFFORT" "$PROMPT")`
  - Reviewer (Hard Read-Only): `(cd "$WORKSPACE" && claude --print --tools Read,Grep,Glob --model "$MODEL" --effort "$EFFORT" "$PROMPT")`
  - Known-good models: `claude-fable-5`, `claude-opus-5`, `claude-sonnet-5`
- **agy**
  - Worker (Write): `(cd "$WORKSPACE" && agy --model "$MODEL" --effort "$EFFORT" --print="$PROMPT")`
  - Reviewer (Soft Read-Only): `(cd "$WORKSPACE" && agy --model "$MODEL" --effort "$EFFORT" --mode plan --print="$PROMPT")`
  - Known-good models: `gemini-3.7-flash-high`, `gemini-3.7-flash-medium`, `gemini-3.7-flash-low`
- **grok**
  - Worker (Write): `grok --cwd "$WORKSPACE" --single "$PROMPT" --model "$MODEL" --reasoning-effort "$EFFORT"`
  - Reviewer (Soft Read-Only): `grok --cwd "$WORKSPACE" --single "$PROMPT" --model "$MODEL" --reasoning-effort "$EFFORT" --permission-mode plan`
  - Known-good models: `grok-4.6`, `grok-4.5`
- **muse**
  - Worker (Write): `muse exec --workspace "$WORKSPACE" --disable-approval --model "$MODEL" --reasoning-effort "$EFFORT" "$PROMPT"`
  - Reviewer (Hard Read-Only): `muse exec --workspace "$WORKSPACE" --disable-approval --disable-write --disable-shell --model "$MODEL" --reasoning-effort "$EFFORT" "$PROMPT"`
  - Known-good models: `muse-spark-1.2-contributor`, `muse-spark-1.2`
  - Note: Unset invalid credentials with `env -u META_API_KEY` before execution.

#### Extensible and Community Harnesses

- **pi**
  - Worker (Write): `(cd "$WORKSPACE" && pi --print --model "$MODEL" --thinking "$EFFORT" "$PROMPT")`
  - Reviewer (Hard Read-Only): `(cd "$WORKSPACE" && pi --print --tools read,grep,find,ls --model "$MODEL" --thinking "$EFFORT" "$PROMPT")`
  - Known-good models: `openai-codex/gpt-5.6-sol`, `openai-codex/gpt-5.6-terra`, `openai-codex/gpt-5.6-luna`, `anthropic/claude-fable-5`, `anthropic/claude-opus-5`, `anthropic/claude-sonnet-5`, `xai/grok-4.6`, `xai/grok-4.5`, `muse-spark/muse-spark-1.2-contributor`
- **jcode**
  - Worker (Write): `jcode run -C "$WORKSPACE" --model "$MODEL" "$PROMPT"`
  - Reviewer (Hard Read-Only): `jcode run -C "$WORKSPACE" --disable-base-tools --tools read --model "$MODEL" "$PROMPT"`
  - Known-good models: `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `claude-fable-5`, `claude-opus-5`, `claude-sonnet-5`, `gemini-3.7-flash-tiered`, `muse-spark-1.2-contributor`
- **goose**
  - Worker (Write): `(cd "$WORKSPACE" && goose run --text "$PROMPT" --no-session --provider "$PROVIDER" --model "$MODEL")`
  - Reviewer (Hard Read-Only): `(cd "$WORKSPACE" && goose review --prompt "$CRITERIA_FILE" --model "$MODEL")`
- **prime-agent**
  - Worker (Write): `prime-agent -p --cwd "$WORKSPACE" --provider "$PROVIDER" --model "$MODEL" --thinking "$EFFORT" "$PROMPT"`
  - Reviewer (Hard Read-Only): `prime-agent -p --tools read,grep,find,ls --cwd "$WORKSPACE" --provider "$PROVIDER" --model "$MODEL" --thinking "$EFFORT" "$PROMPT"`
- **opencode**
  - Worker (Write): `(cd "$WORKSPACE" && opencode run -m "$MODEL" "$PROMPT")`
  - Reviewer (Soft Read-Only): `(cd "$WORKSPACE" && opencode run --agent plan -m "$MODEL" "$PROMPT")`
  - Note: Model format is `<provider>/<model>`.
- **hermes**
  - Worker (Write): `(cd "$WORKSPACE" && hermes chat -q "$PROMPT")`
  - Reviewer (Hard Read-Only): `(cd "$WORKSPACE" && hermes chat -q --tools read,search "$PROMPT")`
- **aider**
  - Worker (Write): `(cd "$WORKSPACE" && aider --model "$MODEL" --message "$PROMPT" --yes-always --no-auto-commits)`
  - Reviewer (Hard Read-Only): `(cd "$WORKSPACE" && aider --model "$MODEL" --message "$PROMPT" --chat-mode ask --yes-always)`
