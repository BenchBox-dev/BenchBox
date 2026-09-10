# Implement a TODO

Drive a claimed tracker item from start to completion using MCP tools.

## The implementation sequence

### 1. Claim the work

1. Call `list_items(ready_only=true)` to find claimable work.
2. Call `take(id=...)` to claim the item. Store the returned
   `generation`. The response already carries the context to begin:
   title, priority, needs, unmet needs, and a description excerpt.
3. Call `show_item(id=...)` only if you need sections beyond the excerpt.

### 2. Do the work

Edit code, test locally, keep the change focused on the task. There are
no work units to tick off and no scope gate to satisfy — the task
description and your judgment define the work.

If the claim may outlast its lease (default 24h), call
`renew(id=..., generation=...)`. Same generation, no milestones needed.

### 3. Finish or hand back

1. Call `finish(id=..., generation=...)` to close the item.
2. If you must abandon work, call `release(id=..., generation=...)` so
   the task returns to the ready queue.

If you find necessary work outside the task, `create_item` a follow-up
with `needs` pointing at the current item rather than widening scope
silently.
