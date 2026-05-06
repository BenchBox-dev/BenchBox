---
id: 2026-05-06-093948-skill-sync-lock-review-opacity
date: 2026-05-06
status: actioned
finding_kind: framework-gap
review_context: "Blind-Spot Follow-Up Sweep review of PRs #220, #222-#225, #227-#229"
related_paths:
  - skill-sync.lock
  - .claude/skills/
  - /Users/joe/.skill-sync/skills
suggested_sweep: "Use make skill-sync-lock-audit TODO=<todo.yaml> CHECK=1 on skill PRs to expose content hash changes and catch out-of-scope skill files."
todo_id: null
---
# Skill-sync lock diffs hide and bundle skill changes

## Finding
Skill PRs in the follow-up sweep often changed only `skill-sync.lock` in git while the reviewable skill text lived in the ignored `.claude/skills/` mirror and the external `/Users/joe/.skill-sync/skills` source tree. Exact TODO verification commands that grep `.claude/skills/...` fail in a clean worktree until `make skill-sync` materializes the ignored mirror. Because the source tree is global, later `make skill-sync` runs also swept unrelated in-flight skill edits into `skill-sync.lock` (for example, blog/todo hashes appeared in PRs whose source TODOs were scoped to code/sqlglot work).

## Why this matters
A reviewer cannot reliably tell from the PR diff which skill prose is landing, and unrelated skill changes can be recorded under the wrong TODO/PR. That weakens scope discipline and makes verification depend on untracked local state rather than the commit under review.

## Suggested next steps
- [x] Add a skill-sync lock audit helper that converts hash changes into `skill/file` paths.
- [x] Add a TODO-scope check mode that fails when changed skill files are outside `scope_limit.only_modify` skill paths.
- [x] Add a `make skill-sync-lock-audit` wrapper so reviewers can run the guard without remembering script arguments.

## Triage log
- 2026-05-06: actioned in follow-up PR via `_project/scripts/skill_sync_lock_audit.py` and `make skill-sync-lock-audit`.
