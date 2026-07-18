# Evidence record: YAML-vs-DB tracker head-to-head evaluation (2026-07-18)

Compact, durable record backing the "Head-to-head evaluation" section of
`_project/specs/todo-db-tracker.md`. Contains the exact agent prompts, the
harness usage counters, and the key lines of the independent end-state
audits, so the claims are verifiable and the experiment is replayable.

## Environment pins

- Repo: joeharris76/BenchBox. Spec/tooling under evaluation as merged in
  PR #1212 (`develop` @ `a296177e`).
- Both subagents: Claude Opus, isolated git worktrees, worktree base
  `7550c423` (35 commits behind `develop` at run time — predates both
  systems' tooling, so **each arm provisioned its own tracker into its
  worktree first**; the environmental tax was symmetric).
- Orchestration: two `Agent` calls (model=opus, isolation=worktree),
  launched in parallel from the same session. Token/tool-call/duration
  figures are the harness's per-subagent usage counters, reported verbatim.

## Prompts (verbatim; the only differences are the tracking-system blocks)

### Arm A — legacy YAML system

```
You are implementing one small tracked work item in the BenchBox repo, using the repo's **legacy YAML TODO system** end-to-end. Work only inside your current worktree. Do NOT commit, do NOT push, do NOT open PRs. Use only the legacy YAML TODO system for tracking (not the DB tracker / `todo-db` skill / `_project/scripts/todo` shim).

Tracking system to use faithfully:
- Skill: `.claude/skills/todo/SKILL.md` and `.claude/skills/todo/references/structure.md`
- Schema: `_project/TODO_SCHEMA.yaml`, template `_project/TODO_ENTRY_TEMPLATE.yaml`
- CLI: `uv run --project _project/scripts -- python _project/scripts/todo_cli.py <cmd>`
- Validator: `uv run --project _project/scripts -- python _project/scripts/validate_todo.py <file>`
Follow the system's full lifecycle: create the item as a planning entry, move it when you start work, track work-unit statuses, record out-of-scope work per the system's conventions, complete the item per the system (including whatever moves/validation/indexing it prescribes).

The work item spec:
- id/slug: `uat-word-count-util`; title: "Add a word-count utility script"; worktree grouping: `main`; priority: Low
- description: Add `_project/scripts/word_count.py`, a CLI that prints line, word, and character counts for a single file passed as its only argument, in the exact format `lines=<n> words=<n> chars=<n>`. Add a unit test at `tests/unit/scripts/test_word_count.py` (pytest markers: `unit` and `medium`) covering a normal file and an empty file. Run the test to verify it passes (`uv run -- python -m pytest tests/unit/scripts/test_word_count.py -q`).
- Work breakdown: w1 = implement the script; w2 = add the test and verify it passes.
- During implementation you notice two improvements that are OUT OF SCOPE for this item and must be tracked as deferred follow-up work per the system's conventions: (a) support for multiple input files, (b) a `--json` output mode.

Do the complete lifecycle: record the item, implement it, run the test, keep statuses current, record both out-of-scope follow-ups so they cannot be lost, and complete the item per the system.

Final message must report: (1) the absolute path of your worktree; (2) the lifecycle steps you performed, in order; (3) the final path and status of the tracked item; (4) exactly how and where the two deferred follow-ups are recorded; (5) the test run result. Leave all changes uncommitted in the worktree.
```

### Arm B — DB tracker spike

```
You are implementing one small tracked work item in the BenchBox repo, using the repo's **DB-backed TODO tracker spike** end-to-end. Work only inside your current worktree. Do NOT commit, do NOT push, do NOT open PRs. Use only the DB tracker for tracking (not the legacy YAML TODO system / `todo_cli.py` / `_project/TODO` files).

Tracking system to use faithfully:
- Skill: `.claude/skills/todo-db/SKILL.md`
- Entry point: `_project/scripts/todo` (the shim; run it from the repo root of your worktree). The tracker database is created automatically under `.todo-db/` in your worktree.
Follow the system's full lifecycle as the skill describes: create the item, claim it, track work-unit statuses with evidence, record out-of-scope work per the system's conventions, verify, and complete the item per the system.

The work item spec:
- id/slug: `uat-word-count-util`; title: "Add a word-count utility script"; worktree grouping: `main`; priority: Low
- description: Add `_project/scripts/word_count.py`, a CLI that prints line, word, and character counts for a single file passed as its only argument, in the exact format `lines=<n> words=<n> chars=<n>`. Add a unit test at `tests/unit/scripts/test_word_count.py` (pytest markers: `unit` and `medium`) covering a normal file and an empty file. Run the test to verify it passes (`uv run -- python -m pytest tests/unit/scripts/test_word_count.py -q`).
- Work breakdown: w1 = implement the script; w2 = add the test and verify it passes.
- During implementation you notice two improvements that are OUT OF SCOPE for this item and must be tracked as deferred follow-up work per the system's conventions: (a) support for multiple input files, (b) a `--json` output mode.

Do the complete lifecycle: record the item, implement it, run the test, keep statuses current, record both out-of-scope follow-ups so they cannot be lost, and complete the item per the system.

Final message must report: (1) the absolute path of your worktree; (2) the lifecycle steps you performed, in order; (3) the final status of the tracked item in the tracker; (4) exactly how and where the two deferred follow-ups are recorded; (5) the test run result. Leave all changes uncommitted in the worktree.
```

## Harness usage counters (verbatim)

| Arm | subagent_tokens | tool_uses | duration_ms |
|---|---|---|---|
| A: legacy YAML | 85,703 | 50 | 501,458 |
| B: DB tracker | 61,091 | 36 | 455,159 |

## Independent end-state audit (key output lines, verbatim)

Audits were run by the orchestrating session in each worktree after the
agents finished, before the worktrees were removed.

Arm B (DB), tracker end state:

```
$ TODO_DB_PATH=<worktree>/.todo-db/todo.sqlite ... todo_db.py stats
"deferrals_by_resolution": { "promoted": 2 }
"items_by_state": { "done": 1, "planning": 2 }
$ ... todo_db.py show uat-word-count-util --json  (condensed)
state: done | units: [('w1','done',evidence=True), ('w2','done',evidence=True)]
deferrals: [(1,'promoted','uat-word-count-multi-file'), (2,'promoted','uat-word-count-json-output')]
$ uv run -- python -m pytest tests/unit/scripts/test_word_count.py -q
2 passed
$ uv run -- python _project/scripts/word_count.py <2-line probe file>
lines=2 words=4 chars=24
```

Arm A (YAML), tracked-item end state:

```
$ ls _project/DONE/main/uat-word-count-util.yaml            # exists
status: "Completed"    completed_date: "2026-07-18"
$ validate_todo.py _project/DONE/main/uat-word-count-util.yaml
valid
$ deferred: block contains 2 entries (multi-file, --json)
$ todo_cli.py ready | grep -i "word.count|multi.file|json"  -> no matches (exit 1)
$ todo_cli.py list  | grep -ci "word-count"                 -> 0
$ uv run -- python -m pytest tests/unit/scripts/test_word_count.py -q
2 passed
$ uv run -- python _project/scripts/word_count.py <2-line probe file>
lines=2 words=4 chars=24
```

Interpretation: both implementations correct and equivalent; both
lifecycles executed faithfully per their system's own rules; Arm A's two
deferrals ended buried in a DONE file's `deferred[]` (invisible to
`ready`/`list`); Arm B's two deferrals were forced through the `complete`
gate into standalone planning items visible in the ready queue.

## Replay instructions

Launch two isolated Opus subagents with the prompts above, verbatim, from
a session on a BenchBox checkout at or after `a296177e`. Audit each
worktree with the commands in the audit section. Expected qualitative
result: identical implementation quality; deferral survivability differs
by system (buried vs promoted). Token magnitudes are n=1 and will vary;
the structural end-state difference should not.

## Caveats

- n=1 per arm; treat token/tool-call magnitudes as indicative.
- Worktree base predated both systems' tooling; both arms paid a
  provisioning tax (Arm A materialized `_project/` from `develop`; Arm B
  copied the shim + `todo_db.py` + `pyproject.toml`).
- Arm B's `check-scope` flagged its own provisioned tracker files (old
  base lacked the `.todo-db/` gitignore entry) — recorded as a tool
  finding (self-state exemption) in the session, not a scoring factor.
