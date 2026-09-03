# TODO Queries and Updates

## Create and update (requires `--profile full`)

- **Create item:** Call `create_item(id="...", title="...", priority="...", worktree="...", description="...", scope=[...], verifications=[...], work=[...])`.
- **Update item:** Call `update_item(id="...", ...)`. It accepts `title`, `description`, `priority`, `worktree`, `add_work`, `edit_work`, `add_verify`, `drop_verify`, and `reason`.
- Edit work units only while pending; completed units carry evidence and are immutable.
- Always provide a `reason` when editing done or dropped items.

## Inspect (available in all profiles)

- `doctor` — check database connection, schema version, and project identity
- `list_items(fields=[...], limit=..., cursor=...)` — list items with paging fallback
- `show_item(id="...", fields=[...])` — inspect details of a specific item
- `ready` — view items ready to be worked on
- `stats` — summary counts by state, priority, worktree, and deferral
- `deps(id="...")` — inspect upstream and downstream dependencies
- `claims` — inspect active claims held by your principal
- `export` — generate deterministic JSON export

## Block, release, and drop

- `release(id="...", claim_token="...")` — release an active claim without finishing
- `block(id="...", reason="...")` — mark an item blocked (`--profile full`)
- `unblock(id="...")` — unblock an item (`--profile full`)
- `drop(id="...", reason="...")` — drop an item (`--profile full`)
- Stale claims held by disconnected sessions can be cleared by an operator using the floor command `todo-db sweep-stale`.
