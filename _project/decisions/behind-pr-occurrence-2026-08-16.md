# Decision: why green develop PRs go BEHIND

Date: 2026-08-16
Status: Accepted. This record restates the #1751 diagnosis after adversarial
review. It does not change workflows, Makefile merge behavior, GitHub
settings, required contexts, or the blocked 07a/07b items.
Observed tip: `origin/develop` `44e35d65cee44575f083abb13592d43cbe958bc8`.

Related: `_project/decisions/strict-base-refresh-policy-2026-08-14.md`;
`_project/decisions/strict-base-refresh-activation-2026-08-14.md` (SHADOW_ONLY);
`_project/decisions/auto-merge-policy-consolidation-2026-08-06.md`;
PR #1751; tracker `behind-pr-occurrence-01-pr-open-currency` and
`behind-pr-occurrence-02-throughput-measurement`.

## Decision

Two distinct ways a develop PR becomes `mergeStateStatus: BEHIND` must stay
separate:

1. **open-stale.** The branch does not contain current `origin/develop` at
   `make pr-open`. #1751 was this case: `#1749` merged at 22:45:45Z and the
   PR opened at 22:54:06Z from `#1748`. There was no green-and-current
   window.
2. **In-flight interarrival.** The branch is current at open, the required
   gate runs (~20–31 min; profile #1734, `medium-test` wall), and another
   develop merge lands before or just after first green. Open-time currency
   cannot close this.

The binding constraint is **required-gate duration versus develop merge
interarrival** under `strict_required_status_checks_policy: true`.
`SHADOW_ONLY` remains the selected refresh path. This item does not reopen
`07a` or `07b`.

## Live revalidation (2026-08-16)

| Surface | Live value |
|---|---|
| Ruleset `15611785` | `strict_required_status_checks_policy: true` |
| Required contexts | `Results Explorer browser gate`, `ci-required-result`, `ruleset-drift` |
| `allow_auto_merge` | true |
| `allow_update_branch` | false — GitHub's "Always suggest updating pull request branches" affordance, **not** an automatic updater |
| `delete_branch_on_merge` | true |
| Merge queue | Unavailable on this user-owned public repository |
| `07a` / `07b` | planning, still blocked on `strict-base-refresh-06` |
| #1751 | OPEN; created 2026-08-16T22:54:06Z; auto-merge not armed |

## Incident clock (#1751)

| When (UTC) | Event |
|---|---|
| Worktree create | Branched from `#1748` (`4bfec5c49`) |
| 22:45:45 | `#1749` merged to `develop` |
| 22:50:42 | Feature commit authored |
| 22:54:06 | `#1751` opened — already one commit behind |
| 23:13:53 | `ci-required-result` green |
| 23:17:04 | `#1750` merged — second commit behind |

`#1749` is sufficient for the initial `BEHIND`. `#1750` only deepened it.
Auto-merge withhold and `allow_update_branch` did not produce that state.

`make pr-open` already `git fetch`es `origin/develop` for path filters. It
does not test ancestry and does not refuse a behind head. `make pr-refresh`
already absorbs `origin/develop` with an exact merge and warns that
refreshing several PRs at once is self-defeating.

## Accepted and rejected mechanisms

| Mechanism | Verdict | Why |
|---|---|---|
| `make pr-refresh` (one PR at a time) | **reuse** | Intended absorb. Policy-blessed. |
| Fail `pr-open` when `origin/develop` is not an ancestor of `HEAD` | **accept for 01** | Would have absorbed `#1749`. Does not keep a PR current for the whole gate. Must not silently merge inside `pr-open` (that would turn `pr-fanout` into a refresh storm). |
| Flip `allow_update_branch` | **reject** | Suggestion affordance, not an updater. Would absorb neither intervening commit. |
| Update every open develop PR when `develop` moves | **reject** | Refresh storm. `Makefile` `pr-refresh` acts on the current worktree's branch only and refuses to run on `develop`/`main`/`release`; it holds no lock against concurrent invocation from other worktrees, so avoiding bulk refresh is convention here, not enforcement. |
| Arm auto-merge at `pr-open` | **reject as the fix for this class** | Would not have saved #1751 (already behind). Reintroduces merge-before-follow-up (`#1503`/`#1521`/`#1531`). `make pr-ready` stays the only local arm path. |
| Unblock `07a` or `07b` from this item | **reject** | `06` selected `SHADOW_ONLY`. Measurement lives in 02; a later activation, not this record, may unblock one path. |
| `refresh-shadow` as a branch updater | **reject** | Observational only. Not a required context. Cannot skip lanes or update heads. |
| `develop-post-merge.yml` | **reuse as post-land net** | Catches stale-green after merge. Does not make a live PR mergeable. |

## Residual risk

An ancestry gate at open (01) still loses to a develop merge that lands
during the next full required gate. That residual is the throughput
deficit `SHADOW_ONLY` accepted: "No required-gate saving. Refresh tax
remains." Only `07a` (cheaper exact refresh) or `07b` (merge queue) can
close it, and only after 02 measures gate duration against interarrival
and live `shadow_eligible` yield.

## Follow-ons

- `behind-pr-occurrence-01-pr-open-currency` implements the fail-closed
  ancestry check. Escape hatch: `make pr-refresh` or explicit `STALE=1`.
- `behind-pr-occurrence-02-throughput-measurement` measures the
  interarrival residual and may **recommend** keep-`SHADOW_ONLY`, later
  `07a`, or later `07b`. It must not unblock those items.

## Rollback

Delete this markdown. No GitHub setting or workflow changes to reverse.
