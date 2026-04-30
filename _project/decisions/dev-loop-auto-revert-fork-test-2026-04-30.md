# Dev-Loop Auto-Revert Smoke Test - 2026-04-30

## Summary

Step 4 W6 was validated against a disposable GitHub mirror because GitHub
does not allow `joeharris76` to fork `joeharris76/BenchBox` into the same user
account, and this account has no organization target for a true fork.

Result: the normal auto-revert path works. A known-bad `develop` SHA opened a
revert PR with the expected branch, title, body, and `incident:develop-red`
label. The smoke also exposed a workflow-file edge case; the workflow now
falls back to a manual-action issue if the revert branch push or PR creation
fails.

## Repositories

| Purpose | Repository |
| --- | --- |
| Canonical repo | `https://github.com/joeharris76/BenchBox` |
| Smoke mirror | `https://github.com/joeharris76/benchbox-dev-loop-smoke-20260430` |

Fork attempt:

```text
gh repo fork joeharris76/BenchBox --fork-name BenchBox-dev-loop-smoke-20260430 --clone=false --remote=false
failed to fork: joeharris76/BenchBox cannot be forked. A single user account cannot own both a parent and fork.
```

The mirror is public and intentionally left in place while the Step 4 PR is
reviewed.

## Required Repository Setting

The smoke mirror was configured with:

```json
{"can_approve_pull_request_reviews":true,"default_workflow_permissions":"read"}
```

The canonical repository was updated to the same workflow permission setting:

```text
before: {"can_approve_pull_request_reviews":false,"default_workflow_permissions":"read"}
after:  {"can_approve_pull_request_reviews":true,"default_workflow_permissions":"read"}
```

This keeps the default `GITHUB_TOKEN` permission read-only unless a job requests
more specific permissions, while allowing this workflow's job-level
`pull-requests: write` and `contents: write` token to create the revert PR.

## Attempt 1 - Workflow-File Edge Case

The mirror initially did not index workflows until a workflow file changed on
its new default branch, so the first known-bad SHA also included a harmless
comment in `.github/workflows/develop-post-merge.yml`.

| Field | Value |
| --- | --- |
| Failing SHA | `35dd478645e5ed34b5b21d33e625bab8e88ddef5` |
| Workflow run | `https://github.com/joeharris76/benchbox-dev-loop-smoke-20260430/actions/runs/25188963360` |
| Result | `auto-revert-on-failure` failed before this branch's fix |

Key log excerpt:

```text
remote rejected auto-revert/35dd478645e5
refusing to allow a GitHub App to create or update workflow `.github/workflows/develop-post-merge.yml` without `workflows` permission
```

Fix added in branch commit `ced04d057`: if the revert branch push fails, or if
`gh pr create` fails after the branch is pushed, the workflow opens a
manual-action issue labeled `incident:develop-red-revert-conflict` instead of
failing without an incident artifact.

## Attempt 2 - Normal Revert PR Path

The second known-bad SHA only added `benchbox/_dev_loop_smoke_bad.py` with a
syntax error. It did not touch workflow files.

| Field | Value |
| --- | --- |
| Clean baseline SHA | `ced04d057d84f05e1e0dc2e5ce984f095b51225d` |
| Failing SHA | `cff5c591941c989cd0c3003d552142d93489e238` |
| Workflow run | `https://github.com/joeharris76/benchbox-dev-loop-smoke-20260430/actions/runs/25189439117` |
| Revert PR | `https://github.com/joeharris76/benchbox-dev-loop-smoke-20260430/pull/1` |
| Revert branch | `auto-revert/cff5c591941c` |
| Label | `incident:develop-red` |

Job results:

```text
lint: failure in 37s
fast-test: success in 8m36s
auto-revert-on-failure: success in 13s
metrics: success in 6s
```

Auto-revert log excerpt:

```text
[auto-revert/cff5c591941c d0af4034] Revert "test: force develop post-merge failure"
1 file changed, 2 deletions(-)
delete mode 100644 benchbox/_dev_loop_smoke_bad.py
Opened revert PR: https://github.com/joeharris76/benchbox-dev-loop-smoke-20260430/pull/1
Set output 'auto-revert-pr-opened-at'
Set output 'auto-revert-pr-url'
```

Revert PR excerpt:

```text
Title: Revert commit cff5c591941c (commit cff5c591941c) - develop went red post-merge
Head: auto-revert/cff5c591941c
Base: develop
Labels: incident:develop-red

Failing SHA: `cff5c591941c989cd0c3003d552142d93489e238`
Failing run: https://github.com/joeharris76/benchbox-dev-loop-smoke-20260430/actions/runs/25189439117
Originating PR: https://github.com/joeharris76/benchbox-dev-loop-smoke-20260430/actions/runs/25189439117
```

The synthetic failing commit had no associated pull request, so there was no
review request. That is expected for this smoke setup; production squash commits
from PRs should populate `associatedPullRequests`.

Metrics artifact excerpt:

```json
{
  "post_merge_red": true,
  "develop_red_detected_at": "2026-04-30T21:09:37Z",
  "auto_revert_pr_opened_at": "2026-04-30T21:17:55Z",
  "time_to_revert_pr_seconds": 498,
  "ci_runner_minutes": 9.433333333333334,
  "auto_revert_pr_url": "https://github.com/joeharris76/benchbox-dev-loop-smoke-20260430/pull/1",
  "conflict_issue_url": null
}
```

## Notes

- The workflow conclusion is still `failure` because the post-merge lint job
  correctly failed. The success condition for W6 is that the auto-revert job
  creates the incident artifact, not that the red develop run turns green.
- Node.js 20 deprecation warnings appeared for current GitHub actions
  dependencies (`actions/checkout@v4`, `actions/setup-python@v5`,
  `astral-sh/setup-uv@v4`, `actions/upload-artifact@v4`). They did not affect
  the smoke result.
- The mirror can be deleted after the Step 4 PR is reviewed.
