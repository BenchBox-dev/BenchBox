# Prioritize TODOs

Rank open items by topic without changing tracker state. There is no
`prioritize` CLI command.

## Before you start

1. Run `_project/scripts/todo --help` and confirm `doctor`, `stats`, `ready`,
   `list`, `show`, and `deps`.
2. Run `todo doctor`. Use the production database:
   - Hosted: `TODO_DB_URL` and credentials resolved via `TODO_DB_CREDENTIAL_COMMAND`
     (or explicit `TODO_DB_RO_AUTH_TOKEN` / `TODO_DB_AUTH_TOKEN`).
   - Read-only fallback: an explicit `--db <git-root>/.todo-db/replica.db` or
     `TODO_DB_REPLICA`, but only when `doctor` approves its schema and shows a
     non-trivial item count.
3. Stop on schema, authentication, or identity failure. Use a non-production
   file only when the user explicitly requests analysis of that file. Never run
   `todo migrate` on a stale copy or build the backlog from `_project/TODO`,
   `_project/todo-db-export/`, or chat history.

## Inputs

| Input | Default | Notes |
|---|---|---|
| `N` | 25 | Max items to show |
| Scope | all open (`planning` + `active`) | Can limit to a worktree, category, or ready-only |
| Write-back | off | Only rewrite priorities when the user explicitly asks |

## Workflow

Start with the live picture:

```sh
todo doctor
todo stats
todo ready
todo list --priority critical
todo list --priority high
todo list --priority medium-high
todo list --state active
```

When `N` is large or medium-high matters, also list `medium`. Report any
findings warning from `ready` or `stats`; findings are not ranked items.

Use `todo show <id>` and `todo deps <id>` when list output is insufficient.

For about 15 or fewer open items, rank up to `N` directly by severity,
readiness, unlock value, and keyword risk. Group by category or worktree.

### When you need a structured ranking

Use a bulk view for more than about 15 high-priority items or requested topic
groups.

Choose one source, in this order:

1. Fresh `todo export` output.
2. Read-only SQL against a path approved by `doctor`. Never guess the file.
   Inspect `items`, `item_deps`, and optional `findings` columns with
   `PRAGMA table_info` and a sample row before querying.

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
5. Findings warnings, replica caveats, and user-owned blocked criticals.

Ranks are session recommendations and do not change the database.

### Write-back — only when the user asks

Only when the user asks to apply the ranking:

1. Confirm `todo update --help` succeeds. Report a missing command; do not drop
   and recreate items.
2. Update only items whose stored priority differs from the recommended band.
3. Give a one-line reason per update. Prefer band moves (`medium` → `high`) over invented ranks the schema cannot store.
4. Re-run `todo stats` and show before/after counts.

Never change priorities, block, or claim during read-only ranking. Respect `N`
and requested grouping; do not dump all medium items, create one topic per item,
or return a flat list when groups were requested.
