# Codex Thread Rescan - Week Ending 2026-05-01

Rescan date: 2026-05-01

Scope:

- PR range: #19 through #94.
- API source: `gh api repos/joeharris76/BenchBox/pulls/<pr>/comments`.
- Author filter: `chatgpt-codex-connector[bot]`.
- Current result: 27 inline review comments across 18 PRs.

The original TODO inventory listed 26 comments. The current API scan also
returns PR #72, which is stale against the current repository state and is
recorded below as already-fixed/no-current-action.

## Resolved By w1-w13

| PR | Thread | Current disposition | Fix |
| --- | --- | --- | --- |
| #59 | [Replace full YAML node when stamping frontmatter fields](https://github.com/joeharris76/BenchBox/pull/59#discussion_r3164438197) | Fixed by replacing the full top-level YAML node and adding a malformed-sequence regression. | [6e54796f0](https://github.com/joeharris76/BenchBox/commit/6e54796f0) |
| #67 | [Scope secondary PR comment probe to merged develop PRs](https://github.com/joeharris76/BenchBox/pull/67#discussion_r3168098547) | Fixed by scoping the Step 0 secondary probe to merged `develop` PRs with a bounded limit. | [cb22fae6b](https://github.com/joeharris76/BenchBox/commit/cb22fae6b) |
| #67 | [Restrict PR-tier job-count check to develop-targeted runs](https://github.com/joeharris76/BenchBox/pull/67#discussion_r3168098551) | Fixed by adding a `baseRefName == develop` guard before selecting the PR workflow run. | [8ddbbf673](https://github.com/joeharris76/BenchBox/commit/8ddbbf673) |
| #70 | [Start Step 5 window after both Step 4 and Step 3a land](https://github.com/joeharris76/BenchBox/pull/70#discussion_r3168890227) | Fixed by documenting the later-of Step 3a and Step 4 merge timestamps; Step 4 remains later, so `2026-05-30` stays correct. | [bcb6f347e](https://github.com/joeharris76/BenchBox/commit/bcb6f347e) |
| #71 | [Expand BENCHBOX_TEST_LOCK_DIR before removing test.lock](https://github.com/joeharris76/BenchBox/pull/71#discussion_r3169224322) | Fixed by resolving the Make target lock path through the same expanduser-equivalent logic as pytest. | [fe393e748](https://github.com/joeharris76/BenchBox/commit/fe393e748) |
| #73 | [Guard against dirty worktree before forced release reset](https://github.com/joeharris76/BenchBox/pull/73#discussion_r3169372557) | Fixed by refusing dirty `worktree-release` without `FORCE=1` and adding a staged-change regression. | [42fa9e119](https://github.com/joeharris76/BenchBox/commit/42fa9e119) |
| #73 | [Treat `.benchbox` as ignorable when claiming free pool slots](https://github.com/joeharris76/BenchBox/pull/73#discussion_r3169372563) | Fixed by filtering harmless `.benchbox/` scratch paths while keeping `claim_in_progress` blocking. | [a8fcbcb10](https://github.com/joeharris76/BenchBox/commit/a8fcbcb10) |
| #78 | [Exit on INT/TERM in claim trap](https://github.com/joeharris76/BenchBox/pull/78#discussion_r3170491244) | Fixed by splitting EXIT cleanup from INT/TERM handlers that clean up and exit nonzero. | [ec356e1db](https://github.com/joeharris76/BenchBox/commit/ec356e1db) |
| #80 | [Avoid hard-coding repository ruleset IDs](https://github.com/joeharris76/BenchBox/pull/80#discussion_r3170714532) | Fixed by resolving current-repo develop-targeting rulesets dynamically before reading required checks. | [3a2c983a8](https://github.com/joeharris76/BenchBox/commit/3a2c983a8) |
| #81 | [Record first failing completion as red detection time](https://github.com/joeharris76/BenchBox/pull/81#discussion_r3170954637) | Fixed by using the earliest non-null failed lint/fast-test completion timestamp and adding a jq fixture. | [465cdb506](https://github.com/joeharris76/BenchBox/commit/465cdb506) |
| #83 | [Restore `last_updated` to a full date-time value](https://github.com/joeharris76/BenchBox/pull/83#discussion_r3171491441) | Fixed by changing Step 5 metadata to a full ISO date-time. | [9904ce52e](https://github.com/joeharris76/BenchBox/commit/9904ce52e) |
| #86 | [Handle persistent snapshot mismatch without infinite spinner](https://github.com/joeharris76/BenchBox/pull/86#discussion_r3171854306) | Fixed by keeping the one-shot retry and rendering a recoverable error after a persistent mismatch; strict cold-load row counts were restored with `toHaveCount`. | [d362529f2](https://github.com/joeharris76/BenchBox/commit/d362529f2) |
| #93 | [Permit `auth login` to prompt even with env token set](https://github.com/joeharris76/BenchBox/pull/93#discussion_r3172049089) | Fixed by making `auth login` use the explicit prompt/store path while leaving env precedence intact elsewhere. | [6fd915bec](https://github.com/joeharris76/BenchBox/commit/6fd915bec) |

## Already-Fixed By Earlier Merges

| PR | Thread | Current disposition |
| --- | --- | --- |
| #56 | [Normalize date keys before sorting findings list](https://github.com/joeharris76/BenchBox/pull/56#discussion_r3163448331) | Already fixed: `cmd_list()` sorts through `fmt_date(...)`, and listing mixed quoted/unquoted YAML dates is covered by `test_sweep_list_handles_mixed_yaml_date_scalars`. |
| #64 | [Match gitignore rules with gitignore semantics](https://github.com/joeharris76/BenchBox/pull/64#discussion_r3164775959) | Already fixed: `.github/workflows/gitignore-lint.yml` uses `git check-ignore -z -v --no-index --stdin`. |
| #64 | [Verify reused PR base before enabling auto-merge](https://github.com/joeharris76/BenchBox/pull/64#discussion_r3164775961) | Already fixed: `make pr-open` reuses only open PRs matching `--base develop --head "$CURRENT"`. |
| #66 | [Query merge-queue eligibility from a real merge-queue signal](https://github.com/joeharris76/BenchBox/pull/66#discussion_r3167971492) | Already fixed: Step 0 no longer aliases merge-queue feasibility to `.has_issues`. |
| #66 | [Fix invalid Python syntax in lock-path verification command](https://github.com/joeharris76/BenchBox/pull/66#discussion_r3167971500) | Already fixed: the Step 1 command no longer contains the invalid conditional import expression. |
| #66 | [Use a supported JSON field when listing workflow runs](https://github.com/joeharris76/BenchBox/pull/66#discussion_r3167971503) | Already fixed: Step 3 lists run IDs with `gh run list` and fetches job details with `gh run view`. |
| #66 | [Remove machine-specific Makefile path from verification](https://github.com/joeharris76/BenchBox/pull/66#discussion_r3167971507) | Already fixed: Step 6 no longer references `/Users/joe/Developer/BenchBox/Makefile`. |
| #70 | [Preserve content-guard failure when exiting aggregator](https://github.com/joeharris76/BenchBox/pull/70#discussion_r3168890222) | Already fixed: current `ci-required-result` exits immediately on content-guard failure instead of letting later output reset the status. |
| #72 | [Handle single-workflow path when counting grep matches](https://github.com/joeharris76/BenchBox/pull/72#discussion_r3169133012) | No current action: both `.github/workflows/test.yml` and `.github/workflows/pr.yml` exist, and the three affected verification commands currently return `3`, `2`, and `3`. |
| #75 | [Replace non-portable ERR trap in claim rollback](https://github.com/joeharris76/BenchBox/pull/75#discussion_r3170340636) | Already fixed: `worktree-claim-attempt` uses POSIX `EXIT` / `INT` / `TERM` traps, not a bash-only `ERR` trap. |
| #75 | [Remove 200-item cap from PR state lookup](https://github.com/joeharris76/BenchBox/pull/75#discussion_r3170340639) | Already fixed: pool status and sweep use `--limit 1000` plus per-branch fallback behavior. |
| #76 | [Replace non-POSIX ERR trap in claim recipe](https://github.com/joeharris76/BenchBox/pull/76#discussion_r3170399355) | Already fixed by the same POSIX trap migration noted for PR #75. |
| #76 | [Remove fixed PR list cap from stale sweep lookup](https://github.com/joeharris76/BenchBox/pull/76#discussion_r3170399359) | Already fixed by the same `--limit 1000` pool status/sweep update noted for PR #75. |
| #79 | [Include deleted files in path classifier diff](https://github.com/joeharris76/BenchBox/pull/79#discussion_r3170617850) | Already fixed: `scripts/path_filter_decision.py` uses `--diff-filter=ACDMRT`, including deletions. |

## Still Actionable

No current Codex inline review thread from the #19-#94 rescan remains
actionable after w1-w13 and the earlier merges above.

## Blind-Spot Cross-Check

| Finding | Status | Audit disposition |
| --- | --- | --- |
| `2026-04-29-143205-react-key-collision-class` | open | Out of scope for this Codex-thread sweep; it concerns dashboard React key collision review, not the PR #19-#94 Codex inline threads. |
| `2026-04-30-114719-separable-dev-loop-decisions` | open | Out of scope; it is a planning-framework note for dev-loop TODO design. Step 5/6 decision-gate work already carries the relevant separation. |
| `2026-04-30-114720-pr-ci-cost-leverage` | open | Out of scope; it is a dev-loop planning metric note, already represented by Step 3/Step 5 measurement TODOs. |
| `2026-04-30-114721-global-test-lock-cpu-protection` | open | Out of scope; w2 fixed `test-unlock` path expansion without changing the global-lock policy this finding protects. |
| `2026-04-30-114722-queue-single-point-failure` | open | Out of scope until Step 6 is activated; Step 5 still gates whether queue infrastructure is built. |
| `2026-04-30-114723-queue-dwell-contract` | open | Out of scope until Step 6 is activated; Step 5 measurement remains the decision gate. |
| `2026-04-30-114724-post-merge-safety-tension` | open | Out of scope; this is a Step 4/Step 6 architecture tension, not an unresolved Codex inline comment. |
| `2026-04-30-143500-pool-disk-accounting` | actioned | Folded into prior worktree-pool follow-up work; no additional action for this sweep. |
| `2026-04-30-143501-four-worktree-creation-paths` | actioned | Partially actioned with remaining deprecation cleanup tracked separately; no Codex-thread action here. |
| `2026-04-30-143502-half-claimed-state-invisible` | actioned | Folded into prior pool status/claim marker work; w4/w5 preserve marker behavior and signal cleanup. |
| `2026-04-30-143503-no-pool-stale-sweep` | actioned | Folded into existing stale-sweep/pool status work; no additional action for this sweep. |
| `2026-04-30-143504-gh-failure-vs-no-pr` | actioned | Folded into existing pool status unknown-state handling; no additional action for this sweep. |
| `2026-04-30-143505-pool-lock-claim-only` | actioned | Folded into existing broader pool lock coverage; no additional action for this sweep. |
| `2026-04-30-214358-pool-size-not-codified-as-contract` | open | Out of scope; it is a separate pool invariant hardening idea and remains open as a blind-spot. |
| `2026-04-30-214359-claim-orchestrator-false-failure` | open | Still actionable but already filed as a blind-spot. This session reproduced the symptom when the first claim printed `WORKTREE_PATH` but `make` exited nonzero; promote separately if it becomes current sprint work. |
| `2026-05-01-103000-hosted-submit-no-local-validate-preflight` | open | Out of scope; this hosted-submit validation contract question is not one of the PR #19-#94 Codex inline threads. |
| `2026-05-01-103001-published-results-validator-no-per-bundle-test` | open | Out of scope; this validator contract-test gap is not one of the PR #19-#94 Codex inline threads. |
| `2026-05-01-103002-explorer-cold-load-test-coverage-weakened` | open | Folded into w9 by restoring strict cold-load row-count assertions with `toHaveCount`; the blind-spot remains open until separately triaged. |
| `2026-05-01-130000-codex-followups-todo-misses-coverage-downgrades` | open | Folded into this sweep. w9 restored strict cold-load row-count assertions with `toHaveCount` and this audit adds the requested blind-spot cross-check step. |

Notes:

- The blind-spot files referenced inside
  `2026-05-01-130000-codex-followups-todo-misses-coverage-downgrades`
  are present in this worktree. `103002` was folded into w9; `103000`
  and `103001` remain separate open blind-spots outside this Codex-thread
  sweep.
- No new TODO was created from this audit because the only still-actionable
  non-Codex items are already tracked as open blind-spots.
