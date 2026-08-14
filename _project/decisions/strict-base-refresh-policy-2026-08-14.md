# Decision: strict-base refresh safety contract

Date: 2026-08-14
Status: Accepted for planning. This record is the current merge-policy
authority for the refresh program. It does not activate skip behavior.
Observed tip: `origin/develop` `c78e17af25ffe927f42485182bed51e74b87faeb`
at 2026-08-14T12:39:16Z.

Related: PR #1708 (strict current-base lock); #1539 / #1541 (stale-green
budget overshoot); #1722 and
`_project/decisions/develop-ruleset-drift-required-2026-08-13.md` (third
required context); tracker sequence `strict-base-refresh-00` through
`strict-base-refresh-07b`; superseded
`dev-loop-step-6-queue-decision-gate-3`.

## Decision

Keep GitHub's strict current-base rule as the race lock. Treat refresh CI as
a latency optimization inside that lock, not as a replacement for it.

Two properties must stay distinct:

1. **Repository-wide and static combined-tree invariants.** Absolute,
   non-additive inventories and static analysis of the merged tree. This
   repository-wide property is what #1539 / #1541 needed. Lint, typecheck,
   import layering, complexity, and the existing `code-lint` drift guards
   speak to this property. The residual risk is explicit: they do not prove
   runtime or test-lane behavior.
2. **Full behavioral integration.** Equivalence to every currently required
   test lane on the combined tree: fast tests, medium tests, correctness,
   plan-capture, and explorer/browser jobs when those surfaces apply.
   Residual risk: even this property does not prove live-cloud or unrun
   platforms.

No workflow may skip or satisfy a required check from this record. This
item authorizes no skip. Later TODOs may collect shadow evidence and
measure cost. Only
`strict-base-refresh-06-activation-decision-and-selected-path-handoff` may
choose exactly one of `SHADOW_ONLY`, `REDUCED_FAST_REFRESH`, or
`NATIVE_MERGE_QUEUE`. Reduced refresh and a native merge queue are mutually
exclusive. A privileged merge steward remains rejected unless a later
decision explicitly reopens it with a stronger trust model.

## Live snapshot (revalidated 2026-08-14T12:39:16Z)

Query live required contexts. Do not copy a dated pair from an older plan.

Ruleset `develop-squash-only` id `15611785`:

| Field | Live value |
|---|---|
| `enforcement` | `active` |
| `updated_at` | `2026-08-13T21:53:24.534-04:00` |
| `strict_required_status_checks_policy` | `true` |
| Required contexts | `Results Explorer browser gate`, `ci-required-result`, `ruleset-drift` |
| Merge methods | squash only |
| Linear history / non-fast-forward / deletion | present |
| Bypass actors | none |
| Code-owner review | required; approving-review count 0 |

Repository `joeharris76/BenchBox`:

| Field | Live value |
|---|---|
| Owner | user `joeharris76` (id 57046) |
| Visibility | public |
| Merge buttons | squash on; merge-commit and rebase off |
| Auto-merge | allowed |
| Automatically update PR branches | off |
| Delete head branch on merge | on |

A GitHub merge queue is unavailable while the public repository stays
user-owned. Transfer and queue enablement are operator-only actions for
TODO 05 / 07b. This item changes no hosted setting.

## Incident the lock already closes

PR #1541 passed at `active_bytes=15947` against base `d1f7cbcd`. PR #1539
then advanced `develop` to 15,990 bytes. Because strict required checks were
off, #1541 kept a stale green and merged a 98-byte delta, producing 16,088
bytes. The combined tree only needed `make agent-instructions-check`. PR
#1708 turned the lock on. Refresh work exists because that lock now forces
current-base checks, not because the race is still open.

Seventeen `develop` merges landed after the 2026-08-13 14:30:01Z ruleset
update through this snapshot, including #1708 itself and #1722, which added
`ruleset-drift` as the third required context.

## Unavoidable versus avoidable work

Unavoidable after `develop` moves:

- GitHub's current-base race lock.
- Conflict-free proof that the feature head is an exact merge of a
  previously certified head with the current base.
- Repository-wide and static combined-tree invariants on that tree.
- Any required lane whose risk domain is touched by both the PR delta and
  the intervening base delta.

Avoidable if, and only if, a later activation decision authorizes it:

- Re-running authored-head fast, medium, correctness, and plan-capture
  lanes when the only new commit is an exact `develop` merge and those
  domains do not overlap.
- Re-running Chromium when Explorer surfaces are quiet on both sides.

`make pr-refresh` already produces the exact two-parent merge
(`git merge --no-edit origin/develop`) and warns that refreshing several
PRs at once is self-defeating (`Makefile` `pr-refresh`). That workflow is
the intended refresh shape. Rebases, conflict resolutions, extra edits, and
chained refreshes are not that shape.

## Synchronize fan-out on develop PRs

A `pull_request` synchronize is not one workflow. Live topology:

| Workflow | Event | Always reports? |
|---|---|---|
| `pr.yml` (`Develop PR`, umbrella `ci-required-result`) | `pull_request` → `develop` | yes |
| `results-explorer-browser.yml` (`Results Explorer browser gate`) | `pull_request` → `develop`/`release` | yes; Chromium is path-gated inside |
| `develop-ruleset-drift.yml` (`ruleset-drift`) | `pull_request_target` → `develop` | yes; trusted base checkout |
| `auto-merge-on-open.yml` | `pull_request` opened/reopened/synchronize/labeled | yes; revoke-only |
| `pr-base-guard.yml` | `pull_request` opened/reopened/synchronize/edited | yes |
| `docs.yml` | `pull_request` → `develop`/`release` with path filter | no; still ~6–7 wall-min on code refreshes |
| `extension-smoke.yml`, `gitignore-lint.yml` | path-filtered `pull_request` → `develop` | no |

Latency and runner-minute claims must use this whole-event fan-out
(TODO 04). A `pr.yml`-only 5-minute target is not an acceptance criterion
until Documentation and the other always-on jobs are accounted for.

## Classifier contract for later implementation

TODO 01 must implement a fail-closed classifier. This record binds the
trust boundary; it does not ship the script.

Permit a later reduced-refresh consideration only when every condition
holds:

- Same repository; never a fork head.
- Event is a synchronize of the current PR head.
- Inspection uses `pull_request.head.sha` and the event base SHA, never
  checkout `HEAD` or GitHub's synthetic `refs/pull/N/merge`.
- Feature head has exactly two parents: parent 1 is the previous feature
  tip, parent 2 is the event's current base.
- `git merge-tree --write-tree parent1 parent2` equals the feature-head
  tree exactly.
- Parent 1 carries a trusted full certification: latest required Check
  Runs, not the combined Status API, all succeeded, and the Actions run
  fingerprint matches the then-current required workflows.
- One refresh only. A head whose parent 1 was itself a refresh is full CI.
- No self-change of classifier, shadow workflow, required-result
  aggregation, browser-gate, ruleset-drift, or path-filter machinery.
- Semantic, runtime, CI, workflow, security, generated-data, merge-driver,
  and unknown-evidence cases fall back to full CI.

Shadow workflows (TODO 02) may classify and record. They must not skip
jobs, write contents, execute PR code, or emit a required context.

## Activation, rollback, and operators

TODO 06 is the only activation gate. It must re-query live required
contexts, apply coverage-based thresholds from replay and latency
evidence, and authorize exactly one path. No skip is implied by a green
shadow report.

Rollback for repository-only changes is a workflow revert. Because this
record never mutates ruleset 15611785, revert restores today's full-refresh
policy without an admin operation. Classifier failures must already select
full mode, so a partial deploy stays safe.

Operator-only actions, none of which this item performs:

- Change ruleset 15611785, its required contexts, strictness, merge
  methods, or bypass actors.
- Transfer the repository to an organization.
- Enable, configure, or disable a GitHub merge queue.
- Grant a bot or app merge or bypass authority.

## Reconciliation of the legacy queue gate

`dev-loop-step-6-queue-decision-gate-3` asked BUILD versus native merge
queue versus a custom steward, and assumed the earlier measurement window
could decide. `_project/decisions/dev-loop-measurement-2026-08-10.md`
already recorded REASSESS. Strict current-base enforcement is now live,
and a steward is rejected here.

That item is superseded by this record and by TODOs 05–07. It must remain
blocked or dropped so it cannot launch an implementation path in parallel.
Native merge queue remains a later option only through TODO 05's
operator-ready assessment and TODO 06's explicit `NATIVE_MERGE_QUEUE`
choice.

## Policy review against the required cases

| Case | What this contract requires |
|---|---|
| Replay of #1539 then #1541 | First merge advances the budget; the second PR is `BEHIND`. After an exact refresh, repository-wide invariants run on the combined tree and must fail the 16,088-byte total. Full test lanes are not required to catch it. |
| Cross-module runtime interaction | `develop` changes a helper; the PR only calls it. Path domains need not overlap. Residual risk: static invariants and `ty` may catch a signature break; they do not prove runtime behavior. Full behavioral integration remains the only property that covers that class. Reduced refresh may not claim it. |
| Missing or failed prior required check | Classifier and any later skip path fail closed to full CI. Neutral, skipped, cancelled, or absent Check Runs on parent 1 are not a certification. |
| Repository transfer / native queue | Operator-only. TODO 05 assesses; TODO 06 may select `NATIVE_MERGE_QUEUE`; TODO 07b executes only after explicit approval. This record does not transfer the repo or enable a queue. |

## What this item does not do

- No skip, no required-context change, no ruleset mutation.
- No new workflow, classifier, or Makefile target.
- No claim that lint or typecheck is full behavioral integration.
- No claim that reduced refresh closes the stale-green race. The race lock
  is already on.

## Prior art

| Concept | Decision | Path |
|---|---|---|
| Exact merge refresh and one-at-a-time warning | reuse | `Makefile` `pr-refresh` |
| Trusted required-context drift enforcement | reuse | `_project/decisions/develop-ruleset-drift-required-2026-08-13.md` |
| Live develop ruleset and current-base rationale | extend | `docs/operations/repo-admin-settings.md` |
| Native queue versus steward gate | supersede | `dev-loop-step-6-queue-decision-gate-3` |
| Path-aware job skip that still emits umbrellas | reuse later, do not replace | `.github/path-filters.yml`, `scripts/path_filter_decision.py` |
