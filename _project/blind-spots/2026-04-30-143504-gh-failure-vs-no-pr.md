---
id: 2026-04-30-143504-gh-failure-vs-no-pr
date: 2026-04-30
status: actioned
finding_kind: framework-gap
review_context: "/code review of PR #73 (Step 2: worktree pool)"
related_paths:
  - Makefile
suggested_sweep: "If state=unknown ever appears in pool-status, check gh auth status and rate limit before assuming the pool is broken"
todo_id: null
---

# `gh pr view` exit codes conflate "no PR" with "API failure"

## Finding

`worktree-pool-status` originally called `gh pr view <branch>` per slot
and treated empty output as "no PR yet → claimed". This was correct for
freshly-claimed slots, but conflated the same outcome with legitimate
failures: `gh` auth expired, rate limit exhausted, network timeout. All
three returned empty `.state` and rendered as `claimed`, hiding real
infrastructure problems behind ordinary state.

## Why this matters

State machines that swallow API failures into normal states leave
operators flying blind during incidents. The framework-gap is "API
output and infrastructure failure share an exit-code channel" — solved
by distinguishing the lookup-failed case explicitly.

## Suggested next steps

- [x] Replace per-slot `gh pr view` with a single up-front `gh pr list`,
      then awk-lookup per slot (also closes Consider #4).
- [x] If the up-front `gh pr list` returns no data (empty stdout),
      report state=`unknown` for all otherwise-claimed slots rather
      than silently rendering as `claimed`.
- [x] When any slot is `unknown`, `worktree-pool-status` prints a
      footer hint: "state=unknown — `gh pr list` returned no data.
      Check `gh auth status` and `gh api rate_limit` to recover."
      The hint surfaces the recovery commands so the operator
      doesn't need to remember them.
