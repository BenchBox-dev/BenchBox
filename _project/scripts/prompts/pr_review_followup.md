You are actioning one stale bot/agent inline PR review comment for BenchBox.

Source:
- Repository: {repo}
- Base branch: {base}
- Merged PR: #{pr_number} {pr_title}
- PR URL: {pr_url}
- PR merged at: {pr_merged_at}
- Review comment: {comment_html_url}
- Comment id: {comment_id}
- Path: {comment_path}
- Line: current={comment_line}, original={comment_original_line}
- Commit: current={comment_commit_id}, original={comment_original_commit_id}

Required workflow:
1. Inspect the current repository state before editing. Do not assume the old PR diff still reflects the tree.
2. Decide whether the finding still requires action on the current branch.
3. If a fix is still required, make the smallest coherent fix and add/update focused regression coverage.
4. Run the narrowest relevant verification command. Use `uv run --` for Python tooling.
5. If no fix is currently required, leave files unchanged and explain the evidence.
6. Do not commit, push, open a PR, or reply on GitHub. The outer Make routine handles those steps.

Carry-over patterns from the completed PR-review follow-up TODOs:
- A stale GitHub thread is not enough evidence. Verify current behavior before fixing or dismissing.
- Some comments are already fixed by later merges; close those with concrete current-file evidence, not code churn.
- Historical DONE-item verification commands should stay executable when the comment identifies a real command defect.
- Comments on obsolete DONE verification commands can be closed as no-current-action only when the command is not reused
  and the current sweep/template captures the protocol hygiene lesson.
- Cross-check related blind-spots and weakened tests when the finding is about regression coverage.
- Prefer focused tests over broad rewrites.

Continuation and waiting:
- Preserve the local follow-up record before any wait or handoff. Its owner,
  batch identity/generation, declared members, pending worker heads, accepted
  integration receipts, final-PR binding, and explicit next action are the
  source of truth for resumption. Never infer completion from an empty PR or
  review list.
- Missing branches/workers, expired claims, conflict-resolution failures, and
  unavailable platform continuation remain explicit owned actions. Resume the
  recorded action only after re-validating the current head and readiness
  transaction.
- Use host scheduling/watch support only when monitoring authority was granted
  before the wait. Do not unconditionally stop and make the user reschedule a
  routine wait. Preserve `KEEP_IDLE` and `SHADOW_ONLY` as no-mutation modes.

Useful local references:
- `_project/DONE/main/active/codex-pr-review-followups-week-2026-05-01.yaml` (historical filename; the routine is now `pr-review-followups`)
- `_project/DONE/main/active/codex-pr-review-followups-week-2026-05-03.yaml` (historical filename; same)
- `_project/audits/pr-review-sweep-template.md`
- `_project/audits/codex-thread-rescan-week-2026-05-01.md` (historical rescan audit)

Diff hunk from the original PR comment:
```diff
{comment_diff_hunk}
```

Reviewer comment body:
```markdown
{comment_body}
```

Final response format:
- `Disposition: fixed` or `Disposition: no-current-action`
- `Evidence:` one short paragraph with files/tests checked
- `Verification:` command(s) run, or why verification was not applicable
