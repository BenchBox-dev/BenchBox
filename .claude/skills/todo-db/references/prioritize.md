# Prioritize and rank TODOs

Rank open tracker items to guide what to work on next. This workflow is
read-only; it does not change state unless the user explicitly authorizes
a write-back.

## Workflow

1. Call `list_items(ready_only=true, limit=50)` for claimable items,
   paging with `cursor` as needed.
2. Call `list_items(status="blocked", limit=50)` if blocked work matters
   to the ranking.
3. Rank by: readiness first, then priority
   (`critical` > `high` > `medium-high` > `medium` > `low`), then unlock
   value — `show_item` reports `unlocks`, the count of open tasks waiting
   on each item.
4. Only `update_item` priorities when the user asked for a write-back.
   Say which items changed and why.
