---
id: 2026-04-30-143501-four-worktree-creation-paths
date: 2026-04-30
status: actioned
finding_kind: scope-creep
review_context: "/code review of PR #73 (Step 2: worktree pool)"
related_paths:
  - Makefile
  - CLAUDE.md
  - AGENTS.md
suggested_sweep: "After one release with worktree-add deprecated, remove it and reduce the surface to two paths"
todo_id: remove-worktree-add-deprecated-alias
---

# Four worktree creation paths now coexist; agents must learn which to use when

## Finding

After Step 2 lands, four ways to create a worktree exist:

1. Raw `git worktree add` (always available, not Makefile-mediated)
2. `make worktree-add BRANCH=...` (deprecated; one-release compatibility path)
3. `make worktree-claim BRANCH=...` (preferred; pool-managed)
4. `make worktree-pool-init` (one-time bootstrap)

A new agent reading the docs has to learn which path applies when. The
deprecation notice on `worktree-add` is good, but the underlying churn
isn't measured, and the help text didn't surface the lifecycle clearly.

## Why this matters

Discovery cost compounds across every new session and every new
contributor. The Makefile is one of the first places someone looks
for "what should I run?", and four creation paths with subtle
ownership boundaries produces ambiguity rather than ergonomics.

## Suggested next steps

- [x] Restructure `make help` to group worktree commands by lifecycle
      (preferred pool path vs deprecated legacy path) instead of
      listing them flat (this PR).
- [x] CLAUDE.md and AGENTS.md prose explicitly call out
      `worktree-claim` as the preferred path for new write sessions.
- [x] After one release with the deprecation notice live, remove
      `make worktree-add` and the corresponding docs paragraphs.
      Track via a one-shot follow-up TODO at deprecation deadline.
      (Done: removed in PR for `remove-worktree-add-deprecated-alias`,
      one release after v0.3.0 (2026-05-20); PR #73 merged 2026-04-30.)
