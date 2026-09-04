# Prioritize TODOs

Rank open items by topic without changing tracker state. There is no
`prioritize` MCP tool; this is a skill-only action driven by the inspect tools.

## Before you start

1. Call the `doctor` tool. The MCP server owns the database connection,
   credentials, and project identity.
2. If `doctor` reports a schema, authentication, or identity problem, stop.
   Do not build the backlog from `_project/TODO`, `_project/todo-db-export/`,
   or chat history, and do not analyse a non-production database unless the
   user explicitly asks for that file.

## Inputs

| Input | Default | Notes |
|---|---|---|
| `N` | 25 | Max items to show |
| Scope | all open (`planning` + `active`) | Can limit to a worktree, category, or ready-only |
| Write-back | off | Only rewrite priorities when the user explicitly asks |

## Workflow

Start with the live picture:

- `doctor` — confirm readiness and identity.
- `stats` — open counts by state, priority, worktree, and deferral.
- `ready` — items with no open blockers or dependencies.
- `list_items(fields=[...], limit=..., cursor=...)` — page through all open
  items, following `cursor` until exhausted. `list_items` has no priority or
  state filter, so request the fields you need (`id`, `title`, `priority`,
  `state`, `worktree`, `category`, `blocked_reason`) and filter by priority
  and state in-session.

Report any warning from `ready` or `stats`; warnings are not ranked items.

Use `show_item(id="...")` and `deps(id="...")` when list output is
insufficient.

For about 15 or fewer open items, rank up to `N` directly by severity,
readiness, unlock value, and keyword risk. Group by category or worktree.

### When you need a structured ranking

For more than about 15 high-priority items or requested topic groups, take a
bulk view with the `export` tool (deterministic JSON, available in all
profiles). Inspect `items`, `item_deps`, and any `findings` before ranking.

For each open candidate, compute:

| Signal | How to get it |
|---|---|
| Severity | `critical` > `high` > `medium-high` > `medium` > `low` |
| Ready | unblocked (`blocked_reason` empty) and no open dependency edges |
| Unlock value | count of open items that depend on this id |
| In-flight | `active` or currently claimed — small boost only |
| Risk keywords | Title/category terms suggesting privacy, security, or correctness risk, such as leak, secret, credential, egress, provenance, or silent |
| Human-only | Maintainer/admin work; demote from the agent-actionable top N but note critical items |

Default order:

1. severity band
2. ready before blocked or dependent
3. risk keyword boost within the band
4. unlock value
5. active or claimed
6. stable tie-break on `id`

A claim gives only a small boost; it never outranks a higher-severity ready item.

### Topic groups

Give each ranked item exactly one topic.

1. Prefer a stable, meaningful `category`.
2. Otherwise use a worktree that names a real program, not `main` or another
   catch-all.
3. Otherwise reuse keyword buckets from titles or descriptions. For a top 25,
   keep four to eight groups and merge singletons into the nearest group or
   "Other high-priority."

### Report

Include:

1. Method: database identity, open counts by priority, `N`, and write-back off.
2. Topic tables: rank, id, priority, state, readiness, unlocks, and one-line
   reason.
3. Suggested dependency-aware order across groups, with privacy, security, and
   tracker reliability before product work.
4. High or critical demotions and their reasons.
5. Findings warnings and user-owned blocked criticals.

Ranks are session recommendations and do not change the database.

### Write-back — only when the user asks

Only when the user asks to apply the ranking:

1. Confirm the `update_item` tool is available (it requires `--profile full`).
   If it is missing, report that; do not drop and recreate items.
2. Update only items whose stored priority differs from the recommended band,
   with `update_item(id="...", priority="...", reason="...")`.
3. Give a one-line reason per update. Prefer band moves (`medium` → `high`)
   over invented ranks the schema cannot store.
4. Re-run `stats` and show before/after counts.

Never change priorities, block, or claim during read-only ranking. Respect `N`
and requested grouping; do not dump all medium items, create one topic per item,
or return a flat list when groups were requested.
