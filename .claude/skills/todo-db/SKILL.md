---
name: todo-db
description: Use when working in a project tracked by todo-db — "what should I work on", "what's ready", "claim a TODO", "start work on an item", "record progress", "finish an item", "create a TODO", "add a work item", "check scope", "release my claim", "why did finish fail", "tracker stats", "prioritize TODOs", "batch implementation", "batch handoff", "closeout", "write a spec", "ideate", "review TODO", "capture a finding". Drives the tracker through the todo-db MCP server.
---

# todo-db

The tracker is driven through **MCP tool calls**, not shell commands. Planning
and the working loop exist only as tools; the `todo-db` CLI keeps a small floor
of human and CI verbs listed at the end of this page. If the tools are not
available, the MCP server is not registered — see
`docs/operations/mcp-clients.md` in the todo-db repository.

## Critical rules

- Call `get_instructions` first in a session. It returns this protocol and, on
  clients that supply no explicit actor, pins your audit principal.
- The loop tools (`next`, `take`, `context`, `progress`) return a
  `next_action`: `{"tool": ..., "arguments": {...}}`. Follow it rather than
  guessing. Query and planning tools return their result alone. An idle `next`
  returns `{"action": "wait", ...}` with no tool to call.
- One active claim per principal. Taking a second item without releasing or
  finishing is refused; call `claims` to see what you hold.
- Only the claim holder may `progress`, `finish`, or `release` an item. Keep
  the `claim_token` from `take`; re-read it with `context` after a restart.
- Never hand-edit tracker state, and never create tracker files. The database
  is the only store.
- Do **not** run the stored verification commands yourself. A human runs them
  with `todo-db verify-run`.

## The loop

| Step | Tool | Notes |
|---|---|---|
| 1 | `next` | Ready queue, or the claim you already hold. |
| 2 | `take` | Claim an item. Omit `id` to take the top of the queue. |
| 3 | `context` | Bounded context for the claimed item; re-reads `claim_token`. |
| 4 | `progress` | One work unit at a time, with real evidence. Refreshes the lease. |
| 5 | `finish` | The close gate. |
| — | `release` | Hand the claim back without finishing. |

## Reading the response envelope

```json
{"ok": true,  "data": {...}}
{"ok": false, "code": "E_...", "error": "...", "recovery": [...], "kind": "gate|error"}
```

`get_instructions` returns markdown text directly; all other query, work, and
planning tools return the `{ok, ...}` JSON envelope.

`kind: "gate"` is an expected result you should act on. `kind: "error"` is an
environment or protocol failure — stop and report it. The `recovery` list names
concrete next steps; read it before improvising.

Responses are capped at 16 KiB. List tools page rather than truncate silently:
pass a smaller `limit` and a `cursor`, or request a `section`.

## Gates and what to do about them

| Code | Meaning | Do |
|---|---|---|
| `E_NOTHING_READY` | Ready queue is empty. | Report it. Do not invent work. |
| `E_MULTIPLE_CLAIMS` | You already hold a claim. | `claims`, then finish or `release` it. |
| `E_CLAIM_STALE` | Your lease expired or the token is wrong. | `context` to re-read, or `take` again. |
| `E_SCOPE_GATE` | A changed file is outside the item's scope rules. | `check_scope`; narrow the change or amend scope with `update_item`. |
| `E_LINT_GATE` | The item's planning quality is insufficient. | `lint` to see why; fix with `update_item`. |
| `E_VERIFY_GATE` | No current workspace attestation. | Stop. A human runs the `todo-db verify-run` command in `recovery`. |
| `E_BASE_DIVERGED` / `E_BASE_UNREACHABLE` | The scope git baseline no longer resolves. | Stop and report; a human runs `todo-db rebaseline`. |
| `E_NO_PRINCIPAL` | Principal not resolved. | Call `get_instructions`, then retry. |
| `E_OUTPUT_TRUNCATED` | Response exceeded 16 KiB. | Retry with a smaller `limit` plus `cursor`, or a `section`. |
| `E_IDENTITY` | The database belongs to another project. | Stop. This is the isolation guarantee, not a bug. |
| `E_SCHEMA` / `E_SCHEMA_BEHIND` / `E_SCHEMA_DIVERGED` | Schema mismatch. | Stop; a human runs `todo-db migrate`. |
| `E_NO_PROJECT` | No project identity resolved. | Run `doctor`; a human fixes `.todo-db/config.json`. |
| `E_AUDIT` | Audit chain verification failed. | Stop immediately and report; do not write. |
| `E_HOSTED` | Hosted backend problem. | Report it; hosted access is configured outside the agent. |
| `E_AUTH_MISSING` / `E_AUTH_REJECTED` | Hosted credential missing or rejected. | Stop writing. Report it; credentials are provisioned outside the agent. |

`E_SCOPE_GATE` and `E_VERIFY_GATE` are the two that most often end a session.
Neither is worked around — scope is narrowed or amended deliberately, and
verification is a human step.

## Planning

`create_item` takes the work breakdown, scope rules, preserves, and
verifications together. Titles must be non-empty and descriptions must be at
least 10 characters. An item created without scope rules or verifications will
fail `lint` and then `finish`, so supply them up front:

- **work** — the ordered work units, each independently evidenced.
- **scope** — the paths the item may touch (`only_modify` and optional
  `do_not_modify`). Keep it tight; a wide scope defeats the gate.
- **verifications** — the commands with `description` and `command` that prove
  the work, for a human to run.

Use `update_item` to amend an item without touching its lifecycle, and
`add_dependency(id=..., needs=...)` to record that one item needs another.
`ready` only returns items whose dependencies are met and that are not blocked.

## Finding the right tool

| You want to | Tool |
|---|---|
| See what is ready | `ready`, `next` |
| Inspect one item | `show_item`, `context` |
| List items | `list_items`, `deps` |
| Create or amend work | `create_item`, `update_item`, `add_dependency` |
| Record or close work | `start_unit`, `progress`, `finish`, `release` |
| Check before committing | `check_scope`, `lint`, `verify_list` |
| Park work | `defer`, `deferrals`, `promote_deferral`, `dismiss_deferral` |
| Health check | `doctor`, `stats` |
| Back up or audit | `export` |
| See what you hold | `claims` |
| Capture an observation | `finding_create` (needs `--profile full`) |

`verify_list` shows the stored verification commands; it never runs them.

## Process guides

For multi-step workflows, follow the dedicated reference guide:

| Workflow (guide, not a tool) | When to use it | Guide |
|---|---|---|
| prioritize | Rank open items by topic, severity, readiness, and unlock value | `references/prioritize.md` |
| batch | Implement a set of items in dependency order across bounded contexts | `references/batch.md` |
| closeout | Remediate reviewed findings and close batch items | `references/closeout.md` |
| handoff | Create a self-contained handoff prompt for another agent session | `references/handoff.md` |
| ideate | Refine a rough idea into an actionable problem statement | `references/ideate.md` |
| spec | Structure a specification for ingestion by `create_item` | `references/spec.md` |
| implement | Drive a claimed item through the working loop | `references/implement.md` |
| review | Audit planning quality, scope precision, and verification commands | `references/review.md` |
| queries | Search, filter, and manage items without direct SQL | `references/queries.md` |
| bootstrap | Initialize project config and verify hosted database health | `references/bootstrap.md` |
| recovery | Resolve gate codes, claim conflicts, and environment errors | `references/recovery.md` |

## Human-only floor verbs

These are not tools. When you hit a gate that needs one, stop and tell the
human the exact command:

- `todo-db verify-run <id> --claim-token <token> --actor <principal>` — runs the
  verification ladder once and binds a workspace attestation. It attests; it
  does not complete the item. Your `finish` call remains the closer.
- `todo-db --actor <principal> rebaseline <id> --reason "<why>"` — audited update
  of an item's scope baseline.
- `todo-db complete <id>` — human completion path.
- `todo-db finding sync` — lands finding drafts into the tracker.

Details: `references/recovery.md` and `references/implement.md`.


