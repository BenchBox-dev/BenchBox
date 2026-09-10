# Queries and item management

Inspect, filter, and read tracker items with bounded output. Filtering,
sorting, readiness, and unlock counts run inside the program — never scan
history yourself.

## Query patterns

| Goal | Tool call | Notes |
|---|---|---|
| Ready work | `list_items(ready_only=true)` | `open`, unclaimed, dependencies all `done`. |
| List or search | `list_items(status=..., priority=..., text=...)` | Brief rows; default 5 per page. |
| Inspect one task | `show_item(id=...)` | Needs, unmet needs, unlock count, sections. |
| Next page | `list_items(cursor=<next_cursor>)` | Cursors bind to a state revision. |

## Managing output limits

Responses are capped at 16 KiB at their final serialization.

- Page with `limit` + `cursor`. Every page with items remaining carries
  `next_cursor`; an empty page means you are done.
- `E_CURSOR_STALE` means the branch moved under you. Restart without a
  cursor; never skip ahead.
- Large fields arrive as section reads:
  `show_item(id=..., field="description", offset=0, budget=6000)`.
  Follow `continuation` until it disappears; each step is guaranteed to
  make progress.
- There is no full-dump tool. If the eight tools omit data you need,
  report the gap instead of probing for an export.
