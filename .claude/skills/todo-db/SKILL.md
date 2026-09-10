---
name: todo-db
description: Use when working in a project tracked by todo-db — "what should I work on", "what's ready", "claim a TODO", "finish an item", "create a TODO", "release my claim", "why did finish fail", "batch implementation", "batch handoff", "closeout", "write a spec", "ideate", "review TODO". Drives the tracker through the todo-db MCP server.
---

# todo-db

The tracker is driven through **MCP tool calls**, not shell commands. The
working loop exists only as tools; the `todo-db` CLI keeps bootstrap,
validation, migration, and recovery for humans and CI, listed at the end
of this page. If the tools are not available, the MCP server is not
registered — see `docs/operations/mcp-clients.md` in the todo-db
repository.

Task state is JSON (`index.json` plus `items/<id>.json`) published on a
dedicated Git state branch. Never hand-edit state-branch files; every
change goes through a tool so publication stays atomic.

## Critical rules

- Call `get_instructions` first in a session. It returns this protocol and,
  on clients that supply no explicit actor, pins your worker identity.
- One server instance is one worker identity. Run separate servers with
  different `--actor` values for concurrent workers.
- One live claim per worker. Taking a second item without releasing or
  finishing is refused with `E_MULTIPLE_CLAIMS`.
- Only the claim holder may `renew`, `finish`, or `release` an item. Keep
  the `generation` from `take`; after a restart, `take` the same item
  again to re-adopt (fresh generation, refreshed lease — any earlier
  process image holding the old generation goes stale).
- Never hand-edit tracker state, and never invent a second store. The
  state branch is the only store.

## The loop

| Step | Tool | Notes |
|---|---|---|
| 1 | `list_items` | Brief rows; filters `status`, `priority`, `text`, `ready_only`; paging with `limit` (default 5) + `cursor`. |
| 2 | `take` | Claim a task. Returns the claim `generation` plus enough context to begin work. |
| 3 | `show_item` | One task with needs, readiness, and sections. Large fields spill to `field`/`offset`/`budget` reads. |
| 4 | `renew` | Extend a long-running claim. Same generation; no progress milestones required. |
| 5 | `finish` | Close the task with the `generation` from `take`. No work breakdown or attestation required. |
| — | `release` | Hand the claim back without finishing (needs the `generation`). |
| — | `drop` | Abandon a task as dropped. Unclaimed tasks drop freely; a live claim needs its `generation`. |

## Reading the response envelope

```json
{"ok": true,  "data": {...}}
{"ok": false, "code": "E_...", "error": "...", "recovery": [...], "kind": "gate|error"}
```

`get_instructions` returns markdown text directly; the nine task tools
return the `{ok, ...}` JSON envelope.

`kind: "gate"` is an expected result you should act on. `kind: "error"` is an
environment or protocol failure — stop and report it. The `recovery` list names
concrete next steps; read it before improvising.

Responses are capped at 16 KiB. Lists page with cursors scoped to a state
revision: `E_CURSOR_STALE` means the branch moved under you — restart from
the first page, never skip ahead.

## Gates and what to do about them

| Code | Meaning | Do |
|---|---|---|
| `E_NOTHING_READY` | Nothing claimable. | Report it. Do not invent work. |
| `E_MULTIPLE_CLAIMS` | You already hold a claim. | Finish or `release` it first. |
| `E_CLAIM_STALE` | Wrong generation or another holder. | `show_item`, then `take` again if it is free. |
| `E_CONFLICT` | Someone changed the task first. | Re-read, re-evaluate; never overwrite blindly. |
| `E_CURSOR_STALE` | State moved under your pages. | Restart listing without a cursor. |
| `E_OVERSIZED` | One field exceeds the cap. | Read it with `show_item` `field`/`offset`/`budget`. |
| `E_OUTPUT_TRUNCATED` | Response exceeded 16 KiB. | Narrow filters, smaller `limit`, or a section read. |
| `E_NO_PRINCIPAL` | Identity not resolved. | Call `get_instructions`, then retry. |
| `E_OFFLINE` | Remote unreachable. | Reads may be cached and marked stale; mutations fail — retry when reachable. |
| `E_UNKNOWN` | Outcome undetermined. | Reconcile with the operation ID in `recovery`; do not re-apply blindly. |
| `E_STATE` | Malformed state or rejected request. | Read the message; report it if you cannot fix the request. |
| `E_SCHEMA` | State format newer than this package. | Stop; a human upgrades the package. |

## Planning

`create_item` takes `id`, `title`, and optionally `priority` (default
`medium`), `description`, `needs` (IDs this task waits on), `acceptance`,
`links`, and `context`. IDs use `a-z0-9-` (start/end alphanumeric).
Titles are 1–200 characters. There is no work breakdown, scope gate, or
verification ladder: an ordinary task closes with `take` + `finish`.

`update_item` amends title/priority/description/needs/sections, or moves
status between `open` and `blocked`. Closing goes through `finish`;
dropping a task is a human decision reported to the user.

`list_items(ready_only=true)` returns only claimable tasks: `open`,
unclaimed, dependencies all `done`. Readiness and unlock counts are
computed by the program — never scan history yourself.

## Finding the right tool

| You want to | Tool |
|---|---|
| See what is ready | `list_items(ready_only=true)` |
| Inspect one item | `show_item` |
| List or search items | `list_items` with `status`/`priority`/`text` |
| Create or amend work | `create_item`, `update_item` |
| Claim, extend, close, hand back, drop | `take`, `renew`, `finish`, `release`, `drop` |

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
| review | Audit task quality and readiness before closing | `references/review.md` |
| queries | Search, filter, and read items with bounded output | `references/queries.md` |
| bootstrap | Initialize state-branch config for a repository | `references/bootstrap.md` |
| recovery | Resolve error codes, conflicts, and offline states | `references/recovery.md` |

## Human-only floor verbs

These are not tools. When you hit a condition that needs one, stop and tell the
human the exact command:

- `todo-db bootstrap --state-remote <url> [--write-config]` — create the state branch.
- `todo-db validate` — check the accepted tip and report counts.
- `todo-db migrate --from-export <file> --backup-dir <dir> [--dry-run]` — migrate a legacy v2 export onto a freshly bootstrapped branch. Dry-run first; a real run requires `--backup-dir`.
- `todo-db recover --op-id <id>` / `--restore-rev <sha>` / `--limit N` — reconcile, restore, history.

Details: `references/recovery.md` and `references/bootstrap.md`.
