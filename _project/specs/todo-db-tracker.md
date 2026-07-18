# TODO Tracker on a Shared Database — Design Spec

Status: proposed (decision-ready; not yet implemented).
Author: agent session, 2026-07-18, from the TODO-infrastructure review.
Decision owner: maintainer.

## Problem statement

The YAML-in-git TODO system fails in three recorded ways, all traced (5-whys)
to a single root cause: **invariants are enforced by prose and model
compliance instead of by code at a mandatory write chokepoint.**

Evidence base:

- **Deferred work loss.** `deferred[]` is write-only; nothing reads it after
  an item moves to DONE. Three forensic sweeps recovered 9 + 5 + 5 lost items
  (PRs #1181, #1210, #1195: "deferred notes were buried inside DONE items —
  recorded but not surfaced in the ready queue").
- **Duplicated-state drift.** Done-ness is encoded in the `status` field, the
  TODO/DONE directory, and the tree. #1181 restored three items on a stale
  `status: Not Started`; #1186 reversed it ("the restore was driven by the
  metadata field, not the code/docs/config state").
- **Silent schema drift.** `validate_todo.py --all` reports 1362/1362 valid
  while 247 DONE files use deprecated `tasks:`, 93 use `dependencies:`, and
  `--warn-deprecated` finds 340 issues (non-strict default,
  `additionalProperties: true`). `migrate_todo_format.py report` claims
  "COMPLETE" while ignoring the archive.
- **Standing cost.** 13 MB / 212k lines of DONE YAML; ~3,500 lines of
  tooling incl. three migration/normalization scripts; ~600 lines of
  governing prose (skill + references + schema + template) loaded into agent
  context; 46 TODO/DONE bookkeeping commits since 2026-01-01, each paying a
  full PR + CI cycle for what is often a pure status change.

## Objective

Replace the file-based tracker with a shared, HTTPS-reachable database whose
constraints enforce the lifecycle, fronted by a thin `todo` CLI that is the
**only write path**. Success criteria:

1. A deferred item cannot be silently lost: `complete` refuses while any
   linked deferral is unresolved (promoted or dismissed), enforced in a
   transaction.
2. A dangling inter-item dependency is unrepresentable (FK), and dependency
   cycles are rejected at insert (recursive-CTE check in the CLI
   transaction).
3. Illegal state transitions are rejected by the CLI state machine; there is
   exactly one encoding of lifecycle state.
4. Guardrails (`scope_rules`, `verifications`, `preserves`, `anti_patterns`,
   `prior_art`) are structured rows, assembled into a work order by a single
   query, and machine-consumable (`check-scope`, `verify --run`, `lint`).
5. The governing skill prose shrinks to ~10 workflow lines; schema file,
   entry template, `validate_todo.py`, `generate_indexes.py`, and all
   migration scripts are deleted.
6. Cross-session live status: claims and state changes are visible to all
   sessions immediately, with no PR cycle for status changes.
7. Provenance survives: append-only `events` table + nightly deterministic
   export committed to the repo (alerting on failure).

## Design principles

- **Column/row for anything a gate, hook, or query consumes; prose (TEXT)
  only for genuinely narrative content** (`description`, `approach`).
- **Mandatory context rides on mandatory commands**: `todo claim` prints the
  full work order (units, scope globs, preserves, verification commands), so
  "remember to read X" prose rules become structurally unnecessary.
- **The DB is the record; the harness session task list is display only.**
  Durable per-work-unit status stays in the DB so a successor session can
  resume a dead session's item.
- **No offline write queue.** Reads degrade to a gitignored local cache with
  a staleness banner; writes fail loudly. A write queue is a second
  consistency system and is explicitly rejected.

## Schema (DDL sketch)

Target dialect: libsql/SQLite-compatible SQL (portable to Postgres). Enums
are CHECK constraints in libsql.

```sql
CREATE TABLE items (
  id           TEXT PRIMARY KEY,          -- slug, ^[a-z0-9][a-z0-9-]*[a-z0-9]$
  title        TEXT NOT NULL CHECK (length(title) BETWEEN 5 AND 200),
  worktree     TEXT NOT NULL,             -- branch/area grouping
  priority     TEXT NOT NULL CHECK (priority IN
                 ('critical','high','medium-high','medium','low')),
  state        TEXT NOT NULL DEFAULT 'planning' CHECK (state IN
                 ('planning','active','done','dropped')),
  blocked_reason TEXT,                    -- NULL = not blocked (annotation, not a state)
  description  TEXT NOT NULL CHECK (length(description) >= 10),
  approach     TEXT,                      -- narrative implementation strategy
  claimed_by   TEXT,                      -- actor id (session/host), NULL = unclaimed
  claimed_at   TEXT,                      -- ISO8601; lease TTL enforced by CLI sweep
  created_at   TEXT NOT NULL,
  completed_at TEXT,
  completed_pr INTEGER                    -- PR number that landed the work
);

CREATE TABLE work_units (
  item_id  TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  wid      TEXT NOT NULL CHECK (wid GLOB 'w[0-9]'
             OR wid GLOB 'w[0-9][0-9]'
             OR wid GLOB 'w[0-9][0-9][0-9]'),
             -- w0..w999; SQLite GLOB '*' matches any chars, so 'w[0-9]*'
             -- would accept e.g. 'w1abc' — enumerate the digit widths
  summary  TEXT NOT NULL CHECK (length(summary) BETWEEN 5 AND 200),
  status   TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
             ('pending','in_progress','done')),
  evidence TEXT,                          -- required by `todo done`: command run, commit, PR
  notes    TEXT,
  PRIMARY KEY (item_id, wid)
);

CREATE TABLE work_needs (                  -- intra-item DAG
  item_id  TEXT NOT NULL,
  wid      TEXT NOT NULL,
  needs_wid TEXT NOT NULL,
  PRIMARY KEY (item_id, wid, needs_wid),
  FOREIGN KEY (item_id, wid)       REFERENCES work_units(item_id, wid) ON DELETE CASCADE,
  FOREIGN KEY (item_id, needs_wid) REFERENCES work_units(item_id, wid) ON DELETE CASCADE
);

CREATE TABLE item_deps (                   -- inter-item DAG; FK kills dangling deps
  item_id    TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  needs_item TEXT NOT NULL REFERENCES items(id),
  PRIMARY KEY (item_id, needs_item)
);
-- Cycle prevention: SQL cannot express acyclicity; the CLI runs a
-- recursive-CTE reachability check inside the same transaction as the
-- insert and aborts on a cycle.

-- Guardrails: first-class, machine-consumable.
CREATE TABLE scope_rules (
  item_id   TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  kind      TEXT NOT NULL CHECK (kind IN ('only_modify','do_not_modify')),
  path_glob TEXT NOT NULL,
  PRIMARY KEY (item_id, kind, path_glob)
);

CREATE TABLE verifications (
  item_id     TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  seq         INTEGER NOT NULL,           -- ladder order: narrowest first
  description TEXT NOT NULL,
  command     TEXT,                        -- runnable via `todo verify --run`
  expected    TEXT,
  last_run    TEXT,                        -- ISO8601
  last_result TEXT CHECK (last_result IN ('pass','fail') OR last_result IS NULL),
  PRIMARY KEY (item_id, seq)
);

CREATE TABLE preserves (                   -- must_preserve
  item_id  TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  behavior TEXT NOT NULL,
  PRIMARY KEY (item_id, behavior)
);

CREATE TABLE anti_patterns (
  item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  dont    TEXT NOT NULL,
  why     TEXT NOT NULL,
  instead TEXT NOT NULL,
  PRIMARY KEY (item_id, dont)
);

CREATE TABLE prior_art (
  item_id  TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  path     TEXT NOT NULL,                  -- file path or path:symbol
  concept  TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('reuse','extend','supersede')),
  PRIMARY KEY (item_id, path, concept)
);

-- Deferral is an operation with a mandatory terminal state, not a field.
CREATE TABLE deferrals (
  id             INTEGER PRIMARY KEY,
  from_item      TEXT NOT NULL REFERENCES items(id),
  summary        TEXT NOT NULL,
  reason         TEXT NOT NULL,
  resolution     TEXT NOT NULL DEFAULT 'open' CHECK (resolution IN
                   ('open','promoted','dismissed')),
  resolved_item  TEXT REFERENCES items(id), -- set when promoted
  resolved_reason TEXT,                     -- required when dismissed
  created_at     TEXT NOT NULL
);

-- Append-only audit; the provenance record and the export source.
CREATE TABLE events (
  seq     INTEGER PRIMARY KEY,
  at      TEXT NOT NULL,
  actor   TEXT NOT NULL,                   -- session/host identity from env
  item_id TEXT,
  action  TEXT NOT NULL,                   -- create|claim|start|done|defer|dismiss|complete|drop|edit|sweep
  detail  TEXT                             -- JSON payload of the change
);

CREATE TABLE meta (                        -- schema_version pin for the CLI
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
```

### Enforced lifecycle invariants (in-CLI transactions)

| Invariant | Mechanism |
| --- | --- |
| `complete` requires all work units `done` | txn check in `todo complete` |
| `complete` refuses with unresolved deferrals | txn check: no `deferrals.resolution='open'` for the item |
| `done <wid>` requires evidence | NOT-NULL argument on the command; row updated atomically |
| Legal transitions only: planning→active→done; planning/active→dropped | state-machine table in CLI; illegal transition = error |
| No dangling deps | FK |
| No dependency cycles (item and work-unit DAGs) | recursive-CTE check inside insert txn |
| Ready = state active/planning, unclaimed or own claim, all `item_deps` done, per-unit `work_needs` done | single query behind `todo ready` / `todo claim` |
| Stale claims | lease TTL (default 24h) + `todo sweep-stale` |

## CLI surface

Single executable `todo` (Python, `_project/scripts` project or standalone
package), env-configured via `TODO_DB_URL` (never echoed). All writes stamp
`actor` from session env into `events`.

```
todo create   --title ... --worktree ... --priority ... [--edit-body]   # opens/accepts structured flags for guardrail rows
todo show     <id> [--json]                 # full item incl. guardrail rows
todo claim    <id>                          # atomic claim + prints WORK ORDER:
                                            #   ready units, scope globs, preserves,
                                            #   anti-patterns, verification ladder
todo start    <id> <wid>  |  todo done <id> <wid> --evidence "..."
todo defer    <id> --summary ... --reason ...          # creates deferral row
todo promote  <deferral-id> [--to-item <new-slug> ...] # deferral -> planning item, linked
todo dismiss  <deferral-id> --reason ...
todo complete <id> --pr <n>                 # gated: units done + deferrals resolved
todo drop     <id> --reason ...
todo ready | todo list [filters] | todo stats | todo deps <id>
todo check-scope <id>                       # git diff --name-only vs scope_rules; exit-coded
todo verify   <id> [--run [seq]]            # records last_run/last_result
todo lint     <id>                          # deterministic quality checks (see below)
todo sweep-stale                            # release expired leases
todo export   [--out DIR]                   # deterministic JSONL + markdown render
todo admin migrate                          # only schema-migration path; CLI pins schema_version
```

`todo lint` mechanical checks (replaces the rubric's mechanical axes):
verification rows exist and ≥1 has a `command`; scope rules present for code
items; `prior_art` rows present when the item is tagged new-module/env-var/
fs-convention; description cites re-runnable evidence (a `w0` unit exists)
when it pins upstream behavior. Judgment axes (clarity, premise freshness)
remain agent work in the skill's `review` action.

## Thin-wrapper contract

The `todo` skill shrinks to roughly:

> All TODO state lives in the shared DB; the `todo` CLI is the only write
> path — never write TODO state to files. Implement flow:
> `todo claim <id>` → follow the printed work order → per unit
> `todo done <id> <wid> --evidence ...` → `todo verify <id> --run` →
> `todo complete <id> --pr <n>`. Defer out-of-scope work with `todo defer`
> at the moment you decide to skip it. Use the harness session task list for
> intra-session progress display only; the DB is the record.

Retained LLM actions: `ideate`, `spec`, `from-spec`, judgment half of
`review`. Deleted artifacts: `TODO_SCHEMA.yaml`, `TODO_ENTRY_TEMPLATE.yaml`,
`validate_todo.py`, `generate_indexes.py`, `migrate_todos.py`,
`migrate_todo_format.py`, `normalize_done_yaml.py`, `_indexes/` machinery,
`references/structure.md`, and the schema-compliance prose in `SKILL.md`.

## Operational design

- **Host requirement: HTTPS-reachable.** Remote sessions tunnel outbound
  traffic through an HTTPS proxy; raw Postgres wire (TCP 5432) is assumed
  blocked. Candidates: Turso/libsql (HTTP-native; primary candidate), Neon
  serverless HTTP driver, Supabase REST. **Gate G1 below verifies
  reachability from a live remote session before any further build.**
- **Credentials:** `TODO_DB_URL` (+ auth token) in remote environment config
  and local `.env`. CLI never prints the DSN; error messages redact it.
  Read-write token for sessions; read-only token available for ad-hoc tools.
- **Identity:** `actor` = `${CLAUDE_SESSION_ID:-$(whoami)@$(hostname)}`.
  Weak identity is acceptable for a single-maintainer project; the audit
  goal is "which session did this," not authentication.
- **Degraded mode:** every successful read refreshes a gitignored local
  cache (`.todo-cache.json`); on connection failure, reads serve the cache
  with a prominent `STALE (age Xh)` banner; writes fail with a clear error.
- **Backup / escape hatch:** nightly CI job runs `todo export` and commits
  the deterministic JSONL + rendered markdown to the repo (stable ordering,
  stable timestamps from row data → clean diffs). The job **alerts on
  failure** (it is load-bearing for provenance). Host-side PITR is the
  second line. The export is the vendor-lock escape: it contains full state.
- **CI stays DB-free.** No repo CI job queries the DB; all gates live in the
  CLI (pre-commit/preflight hooks may call `todo check-scope`). The
  `pr-content-guard` TODO-file checks are retired with the files. The export
  job is the single exception and uses the read-only token.
- **Schema evolution:** CLI embeds expected `schema_version`, refuses on
  mismatch, `todo admin migrate` applies versioned migrations. Migrations
  ship in the same PR as the CLI change that needs them.
- **Testing:** CLI test suite runs against in-memory/local SQLite via
  env-switched DSN; never the production DB. Transition/gate/cycle checks
  are unit-tested; a small integration test exercises Turso HTTP if
  `TODO_TEST_DB_URL` is set.
- **Latency budget:** one network round-trip per CLI call; `show`/`claim`
  are single multi-join queries. Acceptable at interactive scale.

## Accepted residual risks (maintainer sign-off required)

1. **Availability coupling:** DB outage blocks status writes (reads degrade
   to cache). The export restores data, not service.
2. **Backlog edits are no longer PR-reviewed at write time.** Mitigations:
   `todo lint` gates mechanical quality; the nightly export gives a
   reviewable diff trail; `review` action remains for judgment.
3. **New operational surface:** one hosted service, one secret, one
   migration mechanism.

## Local-SQLite spike (2026-07-18)

To evaluate the design without provisioning a hosted service, the full G2
scope was built as a spike against a **local SQLite file**:
`_project/scripts/todo_db.py` (schema v1 + complete CLI) with
`tests/unit/scripts/test_todo_db.py` (41 tests covering every enforced
invariant). Database path: `<git root>/.todo-db/todo.sqlite` (gitignored);
override with `--db` / `TODO_DB_PATH`.

```bash
uv run --project _project/scripts -- python _project/scripts/todo_db.py import-yaml
uv run --project _project/scripts -- python _project/scripts/todo_db.py ready
uv run --project _project/scripts -- python _project/scripts/todo_db.py claim <id>
```

**Results of importing the real `_project/TODO` tree (129 files):**

- 118 items imported cleanly with work graphs, guardrails, and deferrals.
- **11 files in `planning/` carry `status: Completed`** (query-plan-capture
  02–12): completed work that never moved to DONE — fresh, live evidence of
  the status/directory drift class this spec eliminates (the spike's state
  machine makes that divergence unrepresentable).
- **51 dependency edges point at items absent from the open tree** (done or
  dangling) — silently tolerated by the YAML system, surfaced as explicit
  warnings here; under FK enforcement they cannot be created.
- **53 open deferrals** became a single queryable number
  (`stats.deferrals_by_resolution.open`) — the buried-deferral debt the
  forensic sweeps kept recovering manually, now permanently visible.
- `lint --all` found 39 mechanical findings across the 118 items (missing
  runnable verification, missing scope rules, evidence cited without a w0
  re-validation unit).
- The deferral gate, dependency gate, lease claims, and `check-scope` all
  fired correctly against real items via the CLI.

**Full-history import (2026-07-18, second round):** the importer now covers
`_project/DONE` as well, so the database holds the complete record and the
archive becomes deletable (G5). Results of importing **all 1,362 files**
(129 open + 1,233 archived, ~21s):

- **0 skipped.** Archive-lenient fallbacks absorb every legacy shape
  (247 `tasks:` structures and 93 `dependencies:` fields counted, not
  fatal; invalid archive work units dropped with warnings, never the item).
- **The open tree's 51 "dangling" dependencies collapse to 1**: 538 edges
  resolve against the full item set; the single survivor
  (`test-stdout-datagen` → `integrate-stdout-datagen`) is the only truly
  orphaned reference in the project's history. Answering the evaluation
  question directly: yes — the archive import validates them.
- **18 warnings total, each a real historical defect**: the 11
  Completed-in-`planning/` files; 4 status-drifted archive files (3 "Under
  Review", 1 "Not Started" *inside DONE* — among them
  `todo-sweep-completed-items-from-open-tree.yaml`, a drift-cleanup TODO
  that itself drifted); 2 genuine dependency cycles in legacy archive data
  (single-repo-migration phases 6/7 ↔ 5), rejected by the cycle check; and
  the 1 dangling edge.
- **629 open deferrals** across full history (53 from open items + 576
  buried in the archive) — the complete G4 sweep backlog, now one query.

Concurrency hardening applied in the same round (from PR review findings):
all check-then-act writes run under `BEGIN IMMEDIATE` (autocommit
connection + explicit write transactions, `busy_timeout=5000`), claim
acquisition is additionally a conditional UPDATE with a rowcount check, and
`defer` refuses terminal items on the CLI path (importer-only bypass for
historical archive deferrals).

**Thin wrapper + UAT (2026-07-18, third round).** The wrapper was built
TDD-first: `tests/unit/scripts/test_todo_wrapper.py` pins the contract
(10 tests written red), then the implementation turned them green —
`_project/scripts/todo` (7-line shim, works from any cwd, propagates gate
exit codes) and `.claude/skills/todo-db/SKILL.md` (the thin skill). The
contract tests enforce thinness structurally: ≤40 non-empty body lines,
every referenced `todo <cmd>` must exist in the CLI's handler table, the
mandatory workflow verbs must be present, and schema/validation vocabulary
is banned from the body — the wrapper cannot silently regrow prose duties.
The skill body landed at ~30 non-empty lines (vs ~600 lines of governing
prose in the legacy system). An 11th test is an automated UAT: the skill's
numbered workflow executed end-to-end through the shim (create → ready →
claim → ordered done-with-evidence → verify --run → defer →
complete-refused → promote → complete → export determinism → terminal-defer
refusal). All wrapper tests are `medium`-marked to stay out of the
budget-gated fast lane.

Live UAT against the real imported database (shim only): full import
(1,362/0/18), ready-queue ordering, a real work-order render for the
critical DuckLake credential-redaction item, claim contention correctly
refused for a second actor (exit 2), the deferral gate blocking `drop`
until dismissal, and `lint --all`/`export` at full scale. The UAT surfaced
and fixed one real defect: `check-scope` used `git diff HEAD`, which is
blind to untracked files, so brand-new out-of-scope files escaped the
check; it now unions in `git ls-files --others --exclude-standard`
(verified live: the wrapper's own four uncommitted files were correctly
flagged outside a claimed item's allowlist).

Note for cutover: `todo-db` is deliberately an unmanaged sibling of the
skill-synced `todo` skill during the spike; at G5 it is adopted into the
skill-sync source and replaces the legacy skill's tracker actions.

**Spike deviations from the DDL above** (fold back into the final design):
`items.category` column added so the import is lossless; scope matching
uses `fnmatch` semantics (`*` crosses `/`) pending the final glob contract;
no network/degraded-mode layer (local file); `BrokenPipeError` handled for
piped output. The spike is single-clone by construction — it validates the
enforcement design (G2), not the shared-visibility goal, which still
requires the hosted step after G1.

**Post-eval improvements (2026-07-18, fourth round — schema v2).** The
eval's tool findings were implemented TDD-first
(`tests/unit/scripts/test_todo_db_v2.py`, 15 tests written red):

- **Shared database across worktrees**: the default DB path now resolves
  through `git rev-parse --git-common-dir`, so every worktree of a clone
  shares the main repository's tracker (the eval exposed that per-worktree
  DBs fragment state into invisible islands).
- **Resume/recovery metadata**: `start` records `started_at`,
  `started_worktree`, and `started_branch` on the work unit (`done` stamps
  them implicitly if `start` was skipped, and never overwrites an earlier
  stamp). The work order renders in-progress units as
  `(resumable: branch X @ <worktree>, since T)`, so another agent can
  locate and recover partial work after a dead session — verified live
  across a real worktree pair. `start` is now explicitly optional for
  single-sitting units.
- **`check-scope` exempts `.todo-db/`** unconditionally (eval false
  positive on stale-gitignore worktrees).
- **`create --from -`** accepts a structured JSON payload on stdin as an
  alternative to flag-soup item creation.
- Schema v2 migration path: `connect` refuses an outdated DB with a
  `todo migrate` hint; migrations are additive and idempotent.

**Portability round (same day, TDD):** groundwork for using the tracker
outside BenchBox and under non-Claude harnesses (Codex, etc.):

- **Per-database config** (`todo config [key] [value]`, stored in `meta`):
  the two BenchBox-convention lint rules (`lint.require_w0_revalidation`,
  `lint.require_scope_rules`) are now opt-out per project, defaulting on.
- **Harness-neutral actor chain**: `TODO_ACTOR` (universal override) →
  `CLAUDE_SESSION_ID` → `CODEX_SESSION_ID` → `AGENT_SESSION_ID` →
  `user@host`. Lease/claim mechanics are actor-based and harness-blind.
- **Self-teaching gate errors**: every refusal now names its recovery
  command (`todo done ... --evidence`, `todo promote`/`todo dismiss`,
  `todo unblock`, `todo claim`, `todo sweep-stale`/`todo ready`), pinned
  by tests — the error messages are the harness-portable instruction
  layer, so an agent with no skill loaded is still steered by the CLI
  itself. Gate ordering fixed so "claim it first" precedes unit-level
  detail on never-started items.

## Head-to-head evaluation: legacy YAML vs DB tracker (2026-07-18)

**Durable evidence:** `_project/audits/todo-db-eval-2026-07-18.md` — the
exact prompts, verbatim harness counters, key audit output lines, and
replay instructions. The numbers below are bound to that artifact.

**Protocol.** Two isolated Opus subagents, each in its own git worktree,
received byte-identical work-item specs (a small `word_count.py` utility +
unit test, work units w1/w2, and two planted out-of-scope improvements
that "must be tracked as deferred follow-up work per the system's
conventions"). The only difference between the prompts was the assigned
tracking system: the legacy YAML stack (skill + `todo_cli.py` + schema +
validator) vs the DB tracker (thin `todo-db` skill + `todo` shim). Token
usage came from the harness's per-subagent counters; end states were
audited independently in each worktree (tests re-run, script behavior
probed, tracked-item state and queue visibility inspected) before the
worktrees were discarded. Caveats: n=1, so magnitudes are indicative; both
arms paid a similar environmental tax (the worktree base predated both
systems' tooling, so each provisioned its tracker first).

**Token burn.**

| Metric | Legacy YAML | DB tracker | Delta |
|---|---|---|---|
| Subagent tokens | 85,703 | 61,091 | −29% |
| Tool calls | 50 | 36 | −28% |
| Wall time | 8.4 min | 7.6 min | −9% |

The YAML arm's overhead went to reading the governing prose stack
(skill + references + 350-line schema + template) before acting,
hand-authoring the YAML entry, and the completion ceremony (status edits,
`sections` block, `git mv` to DONE, validate, check-graph, reindex). The
DB arm created the item with flags on one command and completed with one
gated command.

**Effectiveness.** Both agents produced correct, identical-behavior
implementations (2/2 tests passing, exact output format, independently
verified) and both executed their assigned lifecycle faithfully — the
YAML agent's execution was near-flawless by the legacy system's own
rules. The separation was structural:

| Dimension | YAML | DB |
|---|---|---|
| Code + test correct | pass | pass |
| Lifecycle executed per system rules | pass | pass (with per-unit evidence, which YAML has no field for) |
| Verification recorded in the tracker | fail (run but not captured) | pass (`verify --run` stamped) |
| Deferred follow-ups survivable | **fail (buried)** | **pass (promoted)** |

The decisive row reproduces the motivating failure class under
controlled conditions: the YAML agent recorded both follow-ups in
`deferred[]` — the system's official convention — and that block now
lives inside a DONE file, invisible to `ready` and `list` (audited: both
grep empty). The follow-ups reached the exact state that previously
required forensic sweeps #1181/#1195/#1210, *despite perfect agent
compliance*. The DB agent structurally could not lose them: `complete`
refused until each deferral was resolved, so both became standalone
planning items (`uat-word-count-multi-file`, `uat-word-count-json-output`)
visible in the ready queue with provenance links to the parent.

**Conclusion.** Same task, same model: the DB tracker was ~29% cheaper in
tokens and ~28% fewer tool calls while producing a strictly better end
state — evidence-stamped units, a recorded verification result, and zero
silently-lost deferred work versus two follow-ups already buried. The gap
is not agent skill; it is prose-enforced invariants vs code-enforced
invariants, demonstrated rather than argued.

## Cutover plan

- **G1 — host verification (before any build):** from a live remote session,
  create the candidate DB (Turso first), verify connect/query/write through
  the HTTPS proxy, verify from local env, record results in this spec.

  **G1 partial results (2026-07-18, live remote session):**
  - All three candidate control planes are **denied by the environment's
    network policy**: CONNECT to `api.turso.tech:443`,
    `console.neon.tech:443`, and `api.supabase.com:443` each returned a 403
    policy denial at the gateway (confirmed in agent-proxy relay logs).
  - Raw TCP egress on 5432 is blocked, confirming the spec's assumption
    that the Postgres wire protocol is not viable from remote sessions;
    HTTPS through the proxy is the sanctioned transport.
  - **New prerequisite for G1 completion (maintainer actions):**
    (a) add the chosen host's domains to the remote environment's network
    allowlist (for Turso: `api.turso.tech` and the org's `*.turso.io`
    database endpoint); (b) create the account/DB and provision the auth
    token into the environment config — both are account-holder actions an
    agent session cannot perform. Re-run the reachability probe afterwards
    to close G1.
- **G2 — CLI MVP:** schema DDL + `create/show/claim/start/done/defer/
  promote/dismiss/complete/ready/list/stats/export` + tests. No repo changes
  to the YAML system yet.
- **G3 — import:** script maps the 129 open TODO YAMLs onto the tables
  (fields → columns/rows; `tasks:`/`dependencies:` legacy forms handled by
  the importer, one-off). Dry-run report → maintainer eyeball → import.
- **G4 — deferred-debt sweep (one-time):** walk all 278 archived DONE
  `deferred:` blocks + 34 open-item blocks through `defer` then
  `promote`/`dismiss`, deduping against existing items. This is the last
  forensic sweep the project should ever need.
- **G5 — freeze & delete:** commit a final export snapshot; delete
  `_project/TODO/`, `_project/DONE/` (history keeps them), the five retired
  scripts, schema/template files; shrink `SKILL.md`; update `AGENTS.md`
  "Planning & TODOs" and `CLAUDE.md` pre-approved commands (`todo *`
  read commands auto-allowed; write commands per current policy).
- **G6 — export job:** nightly workflow + failure alerting; verify one
  cycle.

Rollback: before G5, the YAML tree is untouched — abort by discarding the
DB. After G5, `todo export` output + git history reconstruct the YAML tree.

## Open questions (gating)

1. Host choice pending G1 reachability results (Turso → Neon HTTP →
   Supabase REST, in that order of preference).
2. Should `todo lint` failures block `complete` (hard gate) or warn?
   Recommendation: warn for one month of usage, then hard-gate.
3. Where does the CLI live: `_project/scripts` (uv project) vs a separate
   small repo shared by other projects? Recommendation: start in-repo,
   extract only if a second consumer appears.
