# Prioritize and rank TODOs

Rank open tracker items to guide what to work on next. This workflow is
read-only; it does not change database state unless the user explicitly
authorizes a write-back.

## Inputs

- **Count (`N`)**: Maximum items to rank (default: 25).
- **Scope filter**: Optional filter by category, worktree, or ready-only.
- **Write-back**: Disabled by default. Only update item priorities when asked.

## Workflow

### 1. Gather candidate items

Fetch active tracker state using MCP tools:

1. Call `ready(fields=["id", "title", "priority", "worktree", "category", "state"])`
   to find unblocked items with all dependencies satisfied.
2. Call `list_items(fields=[...], limit=50, cursor=0)` to retrieve open items
   (including blocked and dependent items). Use paging if needed to stay within
   the 16 KiB ceiling.
3. Call `deps(id=...)` to check an item's upstream prerequisites (`needs`), or
   inspect the open item list to compute downstream unlocks (items that depend
   on this item).

### 2. Multi-signal ranking heuristic

Evaluate each open item using these signals:

1. **Severity band (primary)**: `critical` > `high` > `medium-high` > `medium` > `low`.
2. **Readiness**: Ready items rank ahead of blocked or dependent items in the same band.
3. **Unlock value**: Count downstream open items waiting on this item. Items blocking
   multiple open tasks move up within their priority band.
4. **Risk keywords**: Scan titles and summaries for security, credential, data-loss,
   or audit terms (such as `secret`, `leak`, `auth`, `integrity`, or `silent`).
   Apply a small intra-band boost.
5. **In-flight status**: Items already claimed or active receive a small boost to
   encourage finishing started work. They never outrank higher-severity items.
6. **Human tasks**: Demote administrative or maintainer tasks from the agent queue.
7. **Tie-break**: Use a stable alphanumeric sort on `id`.

### 3. Group by topic

Organize the top N items into three to six clear groups:
- Use `category` first.
- If category is absent, group by `worktree` or component directory.
- Merge single items into an "Other high-priority" group.

### 4. Report the ranking

Present a structured, read-only summary:

1. **Baseline**: Total open items, ready count, and active database target.
2. **Topic tables**:
   | Rank | ID | Title | Stored Priority | Recommended Priority | Ready? | Unlocks | Rationale |
   |---|---|---|---|---|---|---|---|
   | 1 | `AUTH-01` | Token refresh fix | `medium` | `high` | Yes | 3 | Unblocks API tasks; credential safety |
3. **Execution sequence**: Recommended cross-group order (security and foundational
   fixes before product features).

### 5. Write-back (user-authorized only)

Only modify tracker priorities if the user explicitly asks to apply the ranking:

1. For each item whose stored priority changes, call `update_item`:
   ```json
   {
     "id": "AUTH-01",
     "priority": "high",
     "reason": "Prioritize pass: unblocks 3 items and resolves credential risk"
   }
   ```
2. Call `stats` and report the updated priority counts.
