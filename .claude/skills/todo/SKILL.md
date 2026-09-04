---
name: todo
description: Use when the user asks to "ideate on an idea", "refine an idea", "brainstorm", "write a spec", "create a specification", "create a TODO", "show TODO items", "manage TODOs", "prioritize TODOs", "top N most important todos", "rank the backlog", "what should we work on", "implement a TODO", "implement a batch of TODOs", "complete a TODO", "cleanup TODOs", "review TODO quality", "claim a TODO", "what's ready" / "ready queue", "defer this work", "promote a deferral", "dismiss a deferral", "block"/"unblock a TODO", "create TODOs from a spec", "create a batch handoff", "close out a reviewed batch", or "todo stats". Covers the lifecycle from idea to specification, implementation, and completion.
version: 1.0.0
tools: Bash, Read, Edit, Write, Task
---

# Todo — Idea to Done

## Critical rules

Interact with tracker state exclusively through the registered `todo-db` MCP server.

- **No shell wrappers:** Never execute `_project/scripts/todo` or invoke model-facing tracker verbs via shell.
- **Fail-closed preflight:** Check that `todo-db` MCP tools (`next`, `take`, etc.) exist in your tool registry. If absent, stop and instruct the operator to register `todo-db-mcp` per client setup instructions.
- **Drive via `next_action`:** Inspect the `next_action` field (`{"tool": "...", "arguments": {...}}`) in each tool response and execute the directed tool call.
- **Retain Bash only for workspace commands:** Use `Bash` strictly for repo test suites, linters, and builds. Do not manipulate tracker database files or execute tracker mutations via Bash.

Skill-only actions: `prioritize`, `batch`, `handoff`, and `closeout`; follow their reference guides.

If one request combines review or validation with close-out, perform the read-only review and stop at findings under `shared-review-protocol/SKILL.md`. A later user message may authorize `closeout`.

### Lifecycle and Gate Rules

- **Preflight diagnostics:** Call the MCP `doctor` tool to verify database readiness, identity, and schema version.
- **Start work:** Call `next` to retrieve available work, then execute the directed `take(id="...")` call to acquire a `claim_token`.
- **Bounded context:** Call `context(id="...")` to fetch work units, scope rules, must-preserve notes, anti-patterns, and the active `claim_token`.
- **Progress units:** After implementing changes for a work unit in the repository, call `progress(id="...", wid="...", evidence="...", claim_token="...")`.
- **Scope & Review:** Call `check_scope(id="...", files=[...])` and `lint(id="...")` before finishing.
- **Deferrals:** Handle scope exceptions immediately with `defer(id="...", summary="...", reason="...")`. Resolve deferrals before finish with `dismiss_deferral(deferral_id=..., reason="...")` or `promote_deferral(deferral_id=...)`.
- **Human Verification Gate (`E_VERIFY_GATE`):**
  - Call `finish(id="...", claim_token="...")`.
  - If `finish` returns `E_VERIFY_GATE`, workspace commands must be attested by a human operator.
  - Extract the exact command from `recovery[0]` (e.g. `todo-db --actor <principal> verify-run <id> --claim-token <token>`).
  - **Do NOT execute `verify-run` via `Bash`.** Present the exact command to the user and pause until the user confirms execution. Once confirmed, retry `finish`.
- **Multiple claims recovery:** If an operation returns `E_MULTIPLE_CLAIMS`, call `claims` to inspect active leases and `release(id="...", claim_token="...")` unneeded items.

### Floor CLI Boundary

The floor CLI (`todo-db`) is reserved strictly for non-agent operations:
- Setup & migration: `todo-db init-project`, `todo-db migrate`
- Diagnostics: `todo-db doctor`
- Human attestation & gates: `todo-db verify-run`, `todo-db rebaseline`, `todo-db complete`
- Integrity & audit: `todo-db audit verify`, `todo-db finding sync`

## Actions

| Action | When to use it | MCP Tool / Guide |
|---|---|---|
| `ideate` | Refine or brainstorm an idea | `references/ideate.md` |
| `spec` | Write a specification | `references/spec.md` |
| `doctor`, `bootstrap` | Verify or initialize tracker | `doctor` tool / `references/bootstrap.md` |
| `next`, `take`, `context`, `progress`, `finish`, `release` | Implement and complete a TODO | `references/implement.md` |
| `defer`, `dismiss_deferral`, `promote_deferral` | Manage work deferrals | `references/implement.md` |
| `check_scope`, `lint` | Verify scope and review quality | `references/review.md` |
| `list_items`, `show_item`, `stats`, `deps`, `export` | Query tracker items and statistics | `references/queries.md` |
| `create_item`, `update_item`, `block`, `unblock` | Backlog grooming (`--profile full`) | `references/queries.md` |
| `finding_create`, `finding_triage`, `finding_promote` | Triage findings (`--profile full`) | `references/implement.md` |
| `prioritize` | Rank open items and group by topic (skill-only) | `references/prioritize.md` |
| `batch` | Implement multiple TODOs in order (skill-only) | `references/batch.md` |
| `handoff` | Create a self-contained batch handoff (skill-only) | `references/handoff.md` |
| `closeout` | Remediate and close a reviewed batch (skill-only) | `references/closeout.md` |
