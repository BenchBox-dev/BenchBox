# Prioritize TODOs

Rank open items and group them by topic. Do not change tracker state unless the user asks you to. This is a skill-only analysis. There is no `prioritize` CLI command.

Use it when the user says: "prioritize TODOs", "top N most important", "what should we work on", "rank the backlog", or "group ready work by topic".

## Before you start

1. Confirm the wrapper supports the inspect commands you need. Run `_project/scripts/todo --help` and check for at least `doctor`, `stats`, `ready`, `list`, `show`, and `deps`.
2. Run `todo doctor`. Use the production database:
   * Hosted: `TODO_DB_URL` plus `TODO_DB_AUTH_TOKEN` (the wrapper may refresh the token once).
   * Acceptable fallback for reads: an explicit replica path (`--db <git-root>/.todo-db/replica.db` or `TODO_DB_REPLICA`) — only if `doctor` reports the schema is OK and shows a non-trivial item count.
   * Do not use a silent local fallback database when `doctor` warns it is not the production tracker, unless the user explicitly asks for analysis on that file. Never run `todo migrate` to make a stale local copy readable.
3. If `doctor` fails on schema, auth, or identity, stop and report the gap. Do not build a backlog from `_project/TODO`, the committed snapshot at `_project/todo-db-export/`, or chat history.

## Inputs

| Input | Default | Notes |
|---|---|---|
| `N` | 25 | Max items to show |
| Scope | all open (`planning` + `active`) | Can limit to a worktree, category, or ready-only |
| Write-back | off | Only rewrite priorities when the user explicitly asks |

## Workflow

Collect the live picture first. Always start here:

```sh
todo doctor
todo stats
todo ready
todo list --priority critical
todo list --priority high
todo list --priority medium-high
todo list --state active
```

When `N` is large or medium-high matters, also list `medium`. Always surface the stderr warning from `ready`/`stats` about untriaged findings as a side note — triage with `todo finding candidates`. Findings are not ranked items.

Use `todo show <id>` and `todo deps <id>` for any item you cannot classify from the list line.

If the open set is small (about 15 or fewer) or you can answer from the CLI lists, you can stop here. Pick up to `N` items by hand using severity, then ready, then unlock value, then keyword risk (see signals below). Group by `category` or worktree from the list lines.

### When you need a structured ranking

Use this branch when the open high-priority set is large (more than about 15) or the user asked for topic groups. You need a bulk view.

Choose one source, in this order:

1. `todo export` output (the CLI command) — only if it is fresh enough for the question.
2. Read-only SQL on the explicit replica or local path that `doctor` already approved. Never query a file you guessed. The tracker tables are `items`, `item_deps`, and optionally `findings`. Check column names with `PRAGMA table_info` and a sample row first.

For each open candidate, compute:

| Signal | How to get it |
|---|---|
| Severity | `critical` > `high` > `medium-high` > `medium` > `low` |
| Ready | unblocked (`blocked_reason` empty) and no open dependency edges |
| Unlock value | count of open items that depend on this id |
| In-flight | `active` or currently claimed — small boost only |
| Risk keywords | words in title or category that suggest privacy, security, or correctness risk (for example, leak, secret, credential, egress, provenance, silent) |
| Human-only | maintainer or admin work — demote out of the agent-actionable top N (still note it in a footnote when it is critical) |

Default order:

1. severity band
2. ready before blocked or dependent
3. risk keyword boost within the band
4. unlock value
5. active or claimed
6. stable tie-break on `id`

Do not treat "claimed by me" as rank 1 when a higher-severity ready item is unclaimed.

### Topic groups

Give each ranked item exactly one topic.

1. Use `category` when it is stable and meaningful.
2. Else use worktree when it names a real program (not a catch-all like `main`).
3. Else use keyword buckets from the title or description. Reuse buckets you already saw in the inventory. Keep 4 to 8 groups for a top-25. Merge singletons into the nearest group or an "Other high-priority" group.

### Report

Include:

1. Method line — which database you used (hosted or replica path), open counts by priority, `N`, and that write-back is off.
2. Tables per topic — rank, id, priority, state, ready, unlocks, one-line reason.
3. Suggested order — a short, dependency-aware sequence across groups. Put privacy, security, and tracker-reliability before product work.
4. Demotions — high or critical items you left out of the top N, with reason (blocked, human-only, narrow risk, waiting on deps).
5. Side notes — open findings warning, stale-replica caveat, blocked criticals the user still owns.

These ranks are recommendations for this session. They do not change the database.

### Write-back — only when the user asks

Only when the user says to apply the ranking (for example, "write these priorities back"):

1. Confirm the wrapper supports `update` (`todo update --help` returns 0). If it does not, report the gap. Do not drop and recreate to change priority.
2. Update only items whose stored priority differs from the recommended band.
3. Give a one-line reason per update. Prefer band moves (`medium` → `high`) over invented ranks the schema cannot store.
4. Re-run `todo stats` and show before/after counts.

Do not do these even when ranking:

* Use a silent local fallback database after `doctor` warned it is not production.
* Run `todo migrate` on a local copy to make ranking work.
* Treat the committed snapshot at `_project/todo-db-export/` or `_project/TODO` trees as the live backlog.
* Change priorities, block, or claim as a side effect of a read-only ranking request.
* Dump all open medium items when the user asked for the top 25.
* Make one topic per item or one flat list when groups were requested.
