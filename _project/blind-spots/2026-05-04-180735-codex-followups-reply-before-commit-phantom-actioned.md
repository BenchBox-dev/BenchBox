---
id: 2026-05-04-180735-codex-followups-reply-before-commit-phantom-actioned
date: 2026-05-04
status: actioned
finding_kind: bug-class
review_context: "/code review of PR #194 (codex-pr-review-followups routine) on chore/codex-pr-review-followups"
related_paths:
  - _project/scripts/codex_pr_review_followups.py
suggested_sweep: "audit other long-running orchestrators that post external state mutations before local commits land"
todo_id: null
---

# Reply-before-commit creates phantom-actioned comments if the routine dies mid-loop

## Finding

`run_action_loop` posts the GitHub reply marker (`benchbox-codex-review-followup-actioned`) to a Codex comment **inside the per-comment loop** (`reply_to_comment` at line 596), but the actual `git commit` of the codex-produced changes only happens later in `submit_changes` (line 546) after **all** comments are processed. If the routine crashes, is `Ctrl-C`'d, or `make pr-preflight` fails between the reply and the commit, the reply marker persists on GitHub while the diff is gone (working tree blown away by the next `worktree-claim`, or simply discarded). The next sweep skips the comment as "already actioned" and the fix never lands. There is no resumable checkpoint and no rollback of the marker reply.

The five-axis review (correctness/readability/architecture/security/performance) did not surface this because partial-failure recovery is an *operability* dimension — neither correctness nor architecture in isolation flag it.

## Why this matters

This is a class: **scripts that mutate external state (GitHub comments, Slack, Jira) ahead of the local commit that justifies the mutation**. The external system becomes the source of truth for "this work was done" while the actual artifact is ephemeral. Once the marker is on GitHub, no local recovery path exists — the operator has to manually delete the marker reply or hand-edit `has_action_marker` matching to ignore it.

Other orchestrators in the repo that post-then-mutate (or vice versa) should be audited for the same pattern: the bug is not in any one line of code, it's in the order of side effects.

## Suggested next steps

- [ ] Reorder `run_action_loop`: stage + commit per-comment locally *before* posting the GitHub reply, so the reply is the last write. A failure between commit and reply leaves a benign uncommented commit; a failure before the commit leaves nothing on GitHub.
- [ ] If a single batched commit is preferred for PR ergonomics, persist a local sidecar (`_project/iterate/codex-followups/<run-id>/state.json`) that records reply-posted-but-uncommitted comments, so a resume run can detect them and either retry the commit or post a corrective reply.
- [ ] Add a smoke test that simulates an exception thrown between `reply_to_comment` and `submit_changes` and asserts the system can be re-driven to a consistent state.
- [ ] Sweep other repo orchestrators (`make pr-fanout`, dev-loop post-merge revert workflow, etc.) for the same "external write before local commit" pattern.

## Triage log

- 2026-05-05: actioned — Reorder shipped: pr_review_followups.py:951-959 calls commit_changes_for_result BEFORE reply_to_comment with explicit phantom-actioned comment guard
