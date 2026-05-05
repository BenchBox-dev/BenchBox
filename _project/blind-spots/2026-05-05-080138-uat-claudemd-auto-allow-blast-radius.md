---
id: 2026-05-05-080138-uat-claudemd-auto-allow-blast-radius
date: 2026-05-05
status: open
finding_kind: scope-creep
review_context: "/code review of PR #205 (UAT framework W2-W11)"
related_paths:
  - CLAUDE.md
  - tests/uat/_cli.py
suggested_sweep: "audit the entire CLAUDE.md Pre-approved Commands section: which entries are local-only/idempotent vs. potentially-remote/billable? Tag accordingly."
todo_id: null
---

# CLAUDE.md auto-allow grants UAT targets without local-vs-cloud differentiation

## Finding
PR #205 adds a single line to CLAUDE.md's Pre-approved Commands:

```
- **UAT framework** (operator targets; see `docs/operations/uat-framework.md`):
  `make uat-cell PLATFORM=* BENCHMARK=* SCALE=*`, `make uat-stress`,
  `make uat-stress PLATFORM=* BENCHMARK=* SCALE=*`, `make uat-sweep CONFIG=*`,
  `make uat-execute CONFIG=*`, `make uat-validate RESULTS_DIR=* OUTPUT_TSV=*`,
  `make uat-package CONFIG=* SUBMISSIONS_DIR=* RESULTS=*`,
  `make uat-explorer-smoke BUNDLES_DIR=* OUTPUT_DIR=* LOG_DIR=*`,
  `make uat-report CELLS_JSONL=* OUTPUT_TSV=*`
```

These targets call into `tests/uat/_cli.py`, which calls `benchbox run`.
`benchbox run` accepts `--platform snowflake|databricks|motherduck|...` —
all of which are billable cloud platforms. A subagent invoking
`make uat-cell PLATFORM=snowflake BENCHMARK=tpcds SCALE=1.0` without a
prompt could rack up substantial cost. The five-axis review caught
"this is correct code" but missed the operational blast radius the
CLAUDE.md change unlocks.

## Why this matters
The CLAUDE.md Pre-approved Commands section has been growing
file-by-file without an explicit local-vs-cloud policy. Many existing
entries (`make test-*`, `git status`, `gh pr view`) are idempotent and
free. UAT targets straddle the line: `make uat-validate` is local and
idempotent; `make uat-cell PLATFORM=snowflake` is potentially-billable.
Granting both under the same banner is a category error.

## Suggested next steps
- [ ] Audit the existing Pre-approved Commands section and tag each
      entry as `local-only`, `local-stateful` (writes/deletes files),
      or `potentially-remote-billable`.
- [ ] For UAT specifically, narrow the auto-allow: leave
      `uat-validate`, `uat-report`, `uat-explorer-smoke` (local only)
      auto-allowed; require prompt for `uat-cell`, `uat-stress`,
      `uat-sweep`, `uat-execute` (any of which can hit cloud platforms
      via `--platform`).
- [ ] Add a doc note in `docs/operations/uat-framework.md` flagging
      which targets can hit billable cloud platforms.
