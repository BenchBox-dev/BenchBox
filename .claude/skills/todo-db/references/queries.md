# Queries and item management

Inspect, filter, and manage tracker items using MCP tools without direct
database queries.

## Query tools

| Goal | Tool call | Notes |
|---|---|---|
| View ready items | `ready(fields=[...], limit=20, cursor=0)` | Returns unblocked items with satisfied dependencies. |
| List items | `list_items(fields=[...], limit=20, cursor=0)` | Supports field projection and paging; filter client-side. |
| Inspect one item | `show_item(id=..., fields=[...])` | Retrieves full item details or selected fields. |
| Check dependencies | `deps(id=...)` | Returns upstream prerequisite items (`needs`). |
| View open deferrals | `deferrals()` | Lists open work parked for later triage. |
| Full backup snapshot | `export()` | Exports all items and verification ladders (large payload). |
| Check held claims | `claims()` | Shows all active claims held by your principal. |
| System statistics | `stats()` | Item counts by priority, state, and findings. |

## Managing output limits

Responses are capped at 16 KiB. To avoid `E_OUTPUT_TRUNCATED`:
- Request only necessary fields:
  `list_items(fields=["id", "title", "priority", "state"])`
- Use pagination:
  Pass `limit=20` and increment `cursor` across pages.
- Note that `export()` produces an uncapped payload intended for full snapshots;
  use `list_items` or `ready` during normal sessions.

## Administrative mutations (profile: full)

When running with `--profile full`, agents can manage item lifecycle flags:

- **Block an item**:
  `block(id="ITEM-1", reason="Waiting for API access")`
- **Unblock an item**:
  `unblock(id="ITEM-1")`
- **Drop an item**:
  `drop(id="ITEM-1", reason="Superseded by architectural refactor")`
