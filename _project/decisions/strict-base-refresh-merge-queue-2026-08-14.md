# Assessment: native merge queue and repository transfer

Date: 2026-08-14
Status: Assessment only. No organization was created, no repository was
transferred, and no hosted setting was changed.
Observed tip: `origin/develop` `4ce41fe87440731ed7b0375fe8fad2dabb958664`.
Live owner probe: `User false`.

Related: `_project/decisions/strict-base-refresh-policy-2026-08-14.md`;
TODOs `strict-base-refresh-05` and `07b`; GitHub merge-queue availability
docs (public organization-owned repositories, or private Enterprise Cloud).

## Verdict

**DEFER.**

- **GO** is not authorized by this record. Transfer and queue enablement
  remain operator-only.
- **NO_GO** for treating transfer as a same-day zero-risk operation, and
  **NO_GO** for combining a native queue with a privileged custom steward.
- Native merge queue is the stronger long-term integration validator **if**
  the operator accepts an organization transfer and a `merge_group` rehearsal.
  It is not available while `joeharris76/BenchBox` stays user-owned.

This assessment does not select the program path. TODO 06 still chooses
exactly one of `SHADOW_ONLY`, `REDUCED_FAST_REFRESH`, or
`NATIVE_MERGE_QUEUE`.

## Live availability

| Fact | Live value | Consequence |
|---|---|---|
| Owner type | User `joeharris76` | Merge queue unavailable |
| Visibility | public / not private | Queue would become available after an organization transfer |
| Squash | allowed; ruleset squash-only | Compatible with a squash merge queue |
| Auto-merge | allowed | `gh pr merge` can enqueue after transfer |
| `merge_group` workflows | none | Required contexts would never report on a queue today |
| Bypass actors | none on `develop-squash-only` | Must stay none |

Official rule: a pull request merge queue is available in any public
repository owned by an organization. A user-owned public repository cannot
enable one.

## Transfer-sensitive inventory (read-only)

Queried 2026-08-14. Names only; secret values were not read.

| Surface | Live state | Transfer risk |
|---|---|---|
| Pages | `has_pages=true`; `build_type=workflow`; `html_url=https://benchbox.dev/` | Custom domain must be re-verified |
| CNAME | `docs/CNAME` is `benchbox.dev`; Pages `cname=benchbox.dev`; `www.benchbox.dev` on the certificate | DNS and GitHub Pages domain ownership can drop during transfer |
| HTTPS | certificate approved, expires 2026-10-29; HTTPS enforced | Re-issue after domain re-association |
| Actions secret names | `CODECOV_TOKEN`, `RULESET_DRIFT_TOKEN`, `TODO_DB_RO_AUTH_TOKEN`, `TODO_DB_URL`, `TODO_EXPORT_PR_TOKEN` | Recreate in the destination; `RULESET_DRIFT_TOKEN` is required for bypass-actor visibility |
| Actions variable | none | Low |
| Ruleset | `15611785` develop-squash-only; `19149459` release-only; `15611787` v-release-branches-minimal; `18774756` tag | Re-bind IDs and required contexts after transfer |
| Environment | `github-pages` (branch policy); `pypi` (required reviewers); `test-pypi` | Reviewer IDs and environment protection must be rebuilt |
| Webhook / app hook | none listed | Low today; re-check at transfer time |
| Package API | not readable with the current token (`read:packages` missing) | Operator must inventory GHCR/npm packages before transfer |
| OIDC subject | `repo:joeharris76/BenchBox` | Cloud trust policies that pin this subject break until updated |
| Clone / badge / docs URLs | `https://github.com/joeharris76/BenchBox` appears in handoffs, fixtures, and SQLGlot notes | Redirect usually works; pin updates still needed for OIDC and some badges |
| Pages environment | `github-pages` | Workflow `docs.yml` deploys via Pages; confirm the destination org can publish |

No workflow file in this assessment diff may change. `merge_group` support is
a later 07b job, not this item.

## Required-context `merge_group` map

A merge queue runs `merge_group: checks_requested`. If a required context
does not report on that event, the PR sits in the queue forever.

| Required context | Workflow today | Has `merge_group`? | 07b work |
|---|---|---|---|
| `ci-required-result` | `.github/workflows/pr.yml` | no | Add `merge_group` and classify the merge-group SHA |
| `Results Explorer browser gate` | `.github/workflows/results-explorer-browser.yml` | no | Always-report gate on `merge_group`; Chromium when explorer paths apply |
| `ruleset-drift` | `.github/workflows/develop-ruleset-drift.yml` | no | Trusted base checkout on the merge-group base; do not run PR-head code |

Auto-merge, soundness withholding, and Codex review today assume a branch
head plus `pull_request` events. A queue changes that:

- `make pr-ready` / `gh pr merge --squash --auto` should enqueue, not
  squash immediately.
- `.github/workflows/auto-merge-on-open.yml` stays revoke-only.
- Soundness paths must still withhold hands-free enqueue.
- `develop-post-merge` remains a separate tip safety net after the squash
  lands. It is not a substitute for `merge_group` required checks.

## Comparison

| Option | Race lock | Integration proof | Maintenance | Operator cost |
|---|---|---|---|---|
| Shadow-only | Current strict checks | Full CI on every refresh | Classifier only | None |
| Reduced fast refresh | Current strict checks | Lint/type + invariants; tests waived when exact-merge | Custom skip aggregator | None, but permanent skip-logic risk |
| Native merge queue after organization transfer | Queue + current base + predecessors | One `merge_group` full validation per group | GitHub-native | Transfer + `merge_group` + CNAME/secret/environment rebuild |

Reduced refresh and native queue remain mutually exclusive. A steward is
rejected.

Native queue is safer than reduced refresh for behavioral integration. It
does **not** eliminate final CI: it relocates the full combined-tree run
onto the merge group. Shadow-only is safer than either skip or a rushed
transfer.

## Operator sequence (not executed)

1. Operator creates or names a free GitHub organization and confirms
   Pages, billing, and ownership.
2. Inventory packages, apps, and any webhook added after this snapshot.
3. Land `merge_group` coverage for all three required contexts on a
   feature branch **before** transfer, so the destination can enable the
   queue without a deadlock.
4. Freeze merging. Transfer the repository. Re-verify Pages, CNAME,
   HTTPS, secrets, variables, rulesets, environments, OIDC subject,
   packages, and app installations.
5. Enable merge queue on `develop` with squash, no bypass, conservative
   grouping, only-merge-non-failing, bounded timeout.
6. Canary: one docs PR, one code PR, one soundness-path PR (must not
   auto-enqueue).
7. Rollback drill: disable the queue and confirm strict branch checks
   still block stale heads.

Abort if any required context is missing on a `merge_group` run, if Pages
or CNAME fail, or if a secret/environment cannot be rebuilt.

## Rollback

- Queue disable is an operator ruleset change and restores ordinary PR
  merges under the existing strict current-base lock.
- Transfer rollback (org → user) is possible but re-breaks merge queue
  availability and can re-disturb Pages/CNAME. Treat transfer as
  one-way unless the operator has already rehearsed the domain.
- This assessment changes no hosted state, so reverting the markdown is
  the only rollback for this PR.

## What TODO 06 should take from this

Prefer **SHADOW_ONLY** unless the operator has already approved transfer.
Prefer **NATIVE_MERGE_QUEUE** over permanent reduced refresh if that
approval exists and `merge_group` rehearsal is green. Do not select
**REDUCED_FAST_REFRESH** as a way to avoid a transfer discussion; that is
a different safety property.
