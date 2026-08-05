# Prioritize TODOs

Produce a ranked shortlist of open tracker items, grouped by topic, without
rewriting tracker state. This is a **skill action**, not a CLI verb: the
resolved `todo` command has no `prioritize` subcommand. Read-only by default.

Triggers: "prioritize TODOs", "top N most important", "what should we work on",
"rank the backlog", "group ready work by topic".

## Preconditions

1. Resolve the `todo` command per SKILL.md (wrapper only when it advertises
   the inspect verbs you need: at least `doctor`, `stats`, `ready`, `list`,
   `show`, `deps`).
2. Run `todo doctor`. Prefer the production backend:
   - Hosted: `TODO_DB_URL` + `TODO_DB_AUTH_TOKEN` (or the wrapper's remint).
   - Acceptable read fallback: an explicit embedded replica
     (`--db <git-root>/.todo-db/replica.db` or `TODO_DB_REPLICA`) when doctor
     reports schema OK and a non-trivial item count.
   - Refuse the silent local fallback DB when doctor warns it is **not** the
     production tracker, unless the user explicitly authorizes analysis on
     that file. Never run `todo migrate` just to make a stale local spike
     readable.
3. If doctor fails on schema/auth/identity, stop and report the gap. Do not
   invent a parallel backlog from `_project/TODO`, export archives, or chat
   history.

## Inputs

Parse the request; use defaults when omitted:

| Input | Default | Notes |
|---|---|---|
| `N` | 25 | Max ranked items to present |
| Scope | all open (`planning` + `active`) | May restrict to a worktree, category, or ready-only |
| Write-back | off | Only rewrite priorities with explicit user authorization |

## Workflow

### 1. Inventory via CLI (always)

Collect the machine picture first:

```sh
todo doctor
todo stats
todo ready
todo list --priority critical
todo list --priority high
todo list --state active
```

When `N` is large or medium-high matters, also list `--priority medium-high`
and, if still short, open `medium`. Surface the untriaged-findings stderr
banner from `ready`/`stats` as a side note (triage via `todo finding
candidates`); findings are **not** ranked items.

Use `todo show <id>` / `todo show <id> --json` and `todo deps <id>` for any
item you cannot classify from the list line alone.

### 2. Structured ranking (when CLI lists are too flat)

When the open high-priority set is larger than ~15 or the user wants topic
groups, build a candidate table. Prefer, in order:

1. `todo export` JSONL/index if present and fresh enough for the question.
2. Read-only SQL against the **explicit** replica/local path already accepted
   by doctor (never against a guessed file). Schema is the tracker's own
   tables (`items`, `item_deps`, optional `findings`); do not assume column
   names beyond what `PRAGMA table_info` / a sample row shows.

For each open candidate compute:

| Signal | How |
|---|---|
| Severity | `critical` > `high` > `medium-high` > `medium` > `low` |
| Readiness | unblocked (`blocked_reason` empty) and no open dependency edges |
| Unlock value | count of open items that `needs` this id |
| In-flight | `active` and/or currently claimed (slight boost, not a free pass) |
| Blast-radius keywords | privacy/security/correctness tokens in title or category (e.g. leak, secret, credential, egress, pseudonym, oracle, misclassif, provenance, silently, orphan) |
| Human-only | demote maintainer/admin/settings-only work out of the agent-actionable top N (still list under a "maintainer" footnote when critical) |

Default composite order:

1. severity band
2. ready before blocked/dependent
3. blast-radius keyword boost within band
4. unlock value
5. active/claimed
6. stable tie-break on `id`

Do **not** treat "claimed by me" as automatic #1 when a higher-severity
unclaimed ready item exists.

### 3. Topic grouping

Assign each ranked item exactly one topic. Prefer, in order:

1. Explicit `category` when it is stable and human-meaningful.
2. Worktree when it is a real program (not a catch-all like `main`).
3. Keyword buckets from title/description. Reuse buckets that already appear
   in the inventory rather than inventing a new taxonomy every run. Common
   BenchBox-shaped buckets (adapt per project): public privacy / credential
   egress; result integrity & explorer trust; CI / merge / release safety;
   tracker reliability; UAT operational defects; product/feature spine;
   architecture / platform.

Keep 4–8 topic groups for a top-25. Merge singletons into a nearest neighbor
or an "Other high-priority" group rather than emitting fifteen headings.

### 4. Present the shortlist

Default report shape:

1. **Method line** — backend used (hosted / replica path), open counts by
   priority, `N`, write-back off.
2. **Grouped tables** — for each topic: rank, id, priority, state, ready?,
   unlocks, one-line why.
3. **Suggested execution order** — a short dependency-aware sequence across
   groups (privacy/security before product spine; tracker lies-to-agents
   before large batches).
4. **Demotions** — high/critical items excluded from the top N with reason
   (blocked, human-only, narrow blast radius, behind deps).
5. **Side notes** — open findings banner, stale-replica caveat, blocked
   criticals the user still owns.

Ranks are **session recommendations**. They do not change `priority` in the
DB.

## Write-back (opt-in only)

Only when the user explicitly asks to apply the ranking (e.g. "write these
priorities back", "update priorities to match"):

1. Confirm the resolved command supports `update` (standalone todo-db
   >= 0.3). If the project wrapper lacks it, report the capability gap per
   SKILL.md rule 4 — do not drop+recreate to change priority.
2. Update only items whose recommended band differs from stored priority.
3. Record a one-line reason per update. Prefer band moves
   (`medium` → `high`) over inventing fractional ranks the schema cannot
   store.
4. Re-run `todo stats` and show the before/after open-by-priority counts.

## Anti-patterns

- Ranking from the silent local fallback DB after doctor warned it is not
  production.
- Running `todo migrate` on a local spike to "make prioritize work".
- Treating export archives or `_project/TODO` trees as the live backlog.
- Rewriting priorities, blocking, or claiming as a side effect of a read-only
  prioritize request.
- Dumping all open medium items when the user asked for top 25.
- One topic per item (topic soup) or a single undifferentiated list when
  groups were requested.
- Scoring scripts that hard-code one project's worktree names as the only
  possible topics without falling back to category/keywords.

## Minimal CLI-only path

If SQL/export is unavailable, still deliver value:

1. `stats` + `ready` + `list --priority critical` + `list --priority high`.
2. Manually pick up to `N` using severity → ready → unlock (via `todo deps`)
   → keyword blast radius.
3. Group by worktree/category from the list lines.
4. State that unlock counts and blocked reasons may be incomplete without
   structured dep expansion.
