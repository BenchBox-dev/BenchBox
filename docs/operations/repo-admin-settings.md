# Repository admin settings runbook

Single source of truth for the GitHub-side admin state that the dev-loop
workflows depend on. The CI workflows, branch protection, and auto-revert
all rely on settings that live outside the repository tree, so they need
to be documented here so they can be re-applied after a transfer, restored
after accidental drift, or reviewed during incident triage.

This document tracks current state. Each change is also captured in a dated
record under `_project/decisions/` for audit history; this file is the
"what is currently configured" view.

## Required workflow permissions

```text
default_workflow_permissions: read
can_approve_pull_request_reviews: true
```

The default token permission is intentionally read-only. The
`develop-post-merge.yml` `auto-revert-on-failure` job declares
`contents: write`, `issues: write`, `pull-requests: write` at the job level
to scope writes narrowly. `can_approve_pull_request_reviews: true` lets the
workflow request review on the auto-revert PR from the original PR author
when the GraphQL lookup populates the field.

Verify:

```bash
gh api repos/BenchBox-dev/BenchBox/actions/permissions/workflow
```

Apply (admin only):

```bash
gh api -X PUT repos/BenchBox-dev/BenchBox/actions/permissions/workflow \
  -f default_workflow_permissions=read \
  -F can_approve_pull_request_reviews=true
```

History:

- Toggled `can_approve_pull_request_reviews` from `false` to `true` on
  2026-04-30 during Step 4 implementation. Recorded in
  `_project/decisions/dev-loop-auto-revert-fork-test-2026-04-30.md`.

## Branch ruleset — `develop`

Ruleset name: `develop-squash-only` (id `15611785`), targets
`refs/heads/develop`.

Required status checks:

```text
- ci-required-result
- Results Explorer browser gate
- ruleset-drift
```

A code-PR `synchronize` is not one Develop PR run. The same head SHA also
starts Results Explorer browser tests, PR base guard, auto-merge revocation,
the unconditional `develop-refresh-shadow` observational workflow, and
ruleset-drift (plus path-filtered siblings such as extension-smoke and
gitignore lint). Documentation (`docs.yml`) only starts when the diff touches
its own path filter (`benchbox/**`, `docs/**`, `examples/**`, and similar) —
for example a `tests/**`-only PR does not start it. Split runner minutes from
wall minutes by workflow when judging savings; the next-slowest sibling can
dominate remaining wall time after `pr.yml` jobs are skipped.

`ci-required-result` is the umbrella job in `.github/workflows/pr.yml`
that aggregates the required-lane jobs: `ci-paths`, `content-guard`,
`code-lint`, `code-test`, `correctness-gate`, `plan-capture-gate`,
`medium-test` (added 2026-07-11, #1139 — the medium tier now gates code
PRs pre-merge via the same umbrella, no ruleset change needed),
`explorer-tokens`, `audit-sha`, `package-smoke`, and `dependency-audit`.

`Results Explorer browser gate` (added 2026-08-03) is the umbrella job in
`.github/workflows/results-explorer-browser.yml`. It is required because the
Chromium full-suite job's own name has claimed to block since it was written,
while the ruleset required only `ci-required-result` — so the full `e2e/` suite
gated nothing. The gate job, not the Chromium job, holds the required context:
the browser jobs are conditional, and GitHub keeps a PR unmergeable forever
waiting on a required check that never reports. The gate runs `if: always()`,
passes when Chromium succeeded or when no explorer-relevant path changed, and
fails closed if change detection itself broke. Firefox and WebKit stay advisory
and are deliberately absent from its `needs`.
Branch protection deliberately keys off the umbrella so the path-aware
classifier can skip subordinate jobs without making the protected check
disappear. The classifier fails closed: any path not on the
`safe-content` allowlist in `.github/path-filters.yml` (including unknown
top-level paths) routes through `code-lint` + `code-test`.

Other ruleset properties to preserve:

```text
strict_required_status_checks_policy: true
required_linear_history: true
non_fast_forward: true
required_pull_request_reviews:    squash-only PRs
deletion: blocked
bypass_actors: (none)
```

Current-base checks are required because instruction budgets and other
repository-wide invariants are not additive per PR. Without the strict policy,
two PRs can each pass against the same older base and exceed an invariant when
merged in sequence. The tradeoff is deliberate: when `develop` advances, an
otherwise-green PR must refresh its required checks before it can merge.

`refresh-shadow` (added with the strict-base refresh shadow rollout) is the
observational job in `.github/workflows/develop-refresh-shadow.yml`. It is
**not a required** context. It classifies exact `develop` refreshes using the
trusted base copy of `scripts/pr_refresh_certification.py` and publishes a
bounded artifact. It cannot skip Develop PR lanes, cannot satisfy
`ci-required-result`, and does not change auto-merge or ruleset 15611785.
`.github/workflows/pr.yml` also uploads `pr-certification-identity` and
`pr-certification-lanes` artifacts so a later activation gate can bind a full
run to a specific head, base, merge tree, workflow fingerprint, and lane
set. Missing artifacts fail closed to `full_required`.

Verify:

```bash
gh api repos/BenchBox-dev/BenchBox/rulesets/15611785 --jq '
  {
    target: .target,
    enforcement: .enforcement,
    bypass_actors: [.bypass_actors[]?.actor_type],
    required_checks: [
      .rules[]
      | select(.type == "required_status_checks")
      | .parameters.required_status_checks[]?.context
    ],
    strict_base: (
      .rules[]
      | select(.type == "required_status_checks")
      | .parameters.strict_required_status_checks_policy
    ),
    linear_history: any(.rules[]; .type == "required_linear_history"),
    non_fast_forward: any(.rules[]; .type == "non_fast_forward"),
    deletion: any(.rules[]; .type == "deletion"),
    merge_queue: any(.rules[]; .type == "merge_queue")
  }'
```

### Native Merge Queue Configuration (Post-v0.4.0)

When Native Merge Queue is activated on `develop-squash-only` (ruleset id `15611785`), the following rule parameters govern queue operations:

```json
{
  "type": "merge_queue",
  "parameters": {
    "check_response_timeout_minutes": 60,
    "grouping_strategy": "ALLGREEN",
    "max_entries_to_build": 5,
    "max_entries_to_merge": 1,
    "merge_method": "SQUASH",
    "min_entries_to_merge": 1,
    "min_entries_to_merge_wait_minutes": 0
  }
}
```

- **Speculative Integration:** `max_entries_to_build: 5` evaluates up to 5 concurrent pull requests speculatively without serializing check waits.
- **Atomic Squash:** `merge_method: SQUASH` preserves the single-commit linear history invariant.
- **Soundness Gate:** Soundness PRs are withheld from auto-enqueue by `auto_merge_soundness_paths.py` and require CODEOWNERS approval before entry.
- **Rollback:** Disable the `merge_queue` rule object in ruleset `15611785` to immediately revert to standard squash merges.

### Soundness-path review enforcement (enforced; operational caution)

Live verification on 2026-07-21 shows that `develop-squash-only` (ruleset id
`15611785`) is `active` and its `pull_request` rule has
`require_code_owner_review: true`, with `required_approving_review_count: 0`
and no bypass actors. This current live state supersedes the 2026-07-18
retirement note, which was based on the rule not yet being applied.

The soundness gate, as operated:

- `SOUNDNESS_PREFIXES` in `_project/scripts/auto_merge_soundness_paths.py`
  (mirrored 1:1 into `.github/CODEOWNERS`, lockstep pinned by
  `tests/unit/test_auto_merge_soundness_paths.py`) classifies the
  soundness-critical surface: comparators/parsers
  (`benchbox/core/equivalence/**`, `benchbox/core/query_plans/parsers/**`,
  `benchbox/core/**/validation.py`), the oracle-adjacent surface
  (`benchbox/core/expected_results/**`,
  `benchbox/platforms/base/result_capture.py`, the `benchbox/sql_compat/`
  rule-dispatch core), and the gate machinery itself (the predicate,
  `.github/workflows/auto-merge-on-open.yml`, and the PyPI-publishing
  `.github/workflows/release.yml`).
- `make pr-open` no longer arms auto-merge at all; `make pr-ready` (or
  `make pr-open READY=1`) does, so a PR cannot merge while a follow-up commit
  is still being written. Arming at creation stranded three commits in one
  session, two of them the fixes for their own review findings.
- `make pr-open` also refuses when `origin/develop` is not an ancestor of
  `HEAD` (open-stale). Absorb current develop with `make pr-refresh` (one
  PR at a time). `STALE=1` is the explicit escape. `pr-open` must not merge
  `develop` itself; that would turn `pr-fanout` into a refresh storm. See
  `_project/decisions/behind-pr-occurrence-2026-08-16.md`.
- `.github/workflows/auto-merge-on-open.yml` is **revoke-only**: it never
  arms on any event (bare `gh pr create` does not auto-arm, and the
  historical `ready_for_review` arm point — which never fired once, drafts
  being unused — was deleted per
  `_project/decisions/auto-merge-policy-consolidation-2026-08-06.md`, D2).
  `opened` / `reopened` / `synchronize` / `labeled` re-evaluate revocation
  only (soundness paths or the hold label). The soundness check unions the
  base-ref predicate with the PR checkout copy so a gate widened mid-flight
  still revokes and a PR cannot weaken its own gate.
- Durable holds every layer honours: **draft** (job/sweep skip) and label
  **`no-auto-merge`** (`make pr-arm-auto-merge` / `pr-ready` refuse to arm;
  workflow disables; nightly green-unmerged sweep never enables auto-merge
  and does not classify the label as stranded). See
  `docs/operations/pr-triage.md` "Durable auto-merge holds".
- The Makefile arming path WITHHOLDS squash auto-merge for PRs touching those
  paths, and `auto-merge-on-open.yml` revokes it on a later push that newly
  touches them. CI cannot catch a change that redefines the oracle it
  validates against, so these PRs must not merge hands-free.
- The active ruleset now supplies the repo-layer control; the owner must still
  review and merge manually because the current single-owner account cannot
  approve its own PR. Adding a second code-owner or changing the PR identity
  model would remove that operational deadlock; alternatively, an admin must
  remove the live rule before it blocks a soundness-path release.

`scripts/ruleset_drift_check.py` now imports the shared
`review_enforcement_findings` predicate and treats a missing or false
`require_code_owner_review` as a **blocking** finding through
`DEVELOP_REVIEW_RULE_ENFORCED = True`. The daily `release-canary.yml` run and
`validate-release-pr.yml` bootstrap use the same path. The standalone check is
available for an immediate live verification:

```bash
gh api repos/BenchBox-dev/BenchBox/rules/branches/develop \
  | uv run --project _project/scripts -- python _project/scripts/ruleset_review_enforcement.py --rules-file -
```

The predicate deliberately does not assert `required_approving_review_count`:
that setting is branch-wide and would gate every develop PR. The checker
reports drift; it does not make the current single-owner self-approval rule
operable. Treat a green drift check as evidence of configuration, not proof
that a soundness-path PR is mergeable under the current identity model.

The review predicate and its blocking/default-plus-explicit-override behavior
are covered by `tests/unit/release/test_ruleset_review_enforcement.py` and
`tests/unit/release/test_ruleset_drift_review_coverage.py`.

History:

- Switched required status check from
  `["lint", "test (ubuntu-latest, 3.12)"]` to `["ci-required-result"]` on
  2026-04-30 as Step 3a w7. Recorded in
  `_project/decisions/dev-loop-path-filter-smoke-test-2026-04-30.md`
  with full before/after JSON.

## Branch ruleset — `release`

Ruleset name: `release-only`, targets `refs/heads/release`.

Release-only branch. Direct pushes are not allowed; releases land via the
`release-cut` / `release-finalize` Make targets documented in
`release-guide.md`.

Required status checks:

```text
- validate-base
- release-required-result
```

`validate-base` is the branch-shape guard in
`.github/workflows/validate-release-pr.yml`. It allows only release branches
matching `vX.Y.Z` with an optional suffix.

`release-required-result` is the umbrella job in `.github/workflows/test.yml`
for release PR correctness. It aggregates the required fast lane, the bounded
real-result correctness gate (`make test-correctness-gate`), credential-free
integration-not-slow suite, isolated exact-one-wheel package smoke, dependency
upper-bound checks, and release-branch curation checks. It is the ruleset
context maintainers should use instead of individual matrix job names such as
`test-package (...)`.

Other ruleset properties to preserve:

```text
strict_required_status_checks_policy: false
required_linear_history: true
non_fast_forward: true
deletion: blocked
bypass_actors: (none)
```

Verify (ruleset id varies; list and inspect):

```bash
gh api repos/BenchBox-dev/BenchBox/rulesets --jq '.[] | {id, name, target}'
gh api repos/BenchBox-dev/BenchBox/rulesets/<release-ruleset-id> --jq '
  {
    target: .target,
    enforcement: .enforcement,
    bypass_actors: [.bypass_actors[]?.actor_type],
    required_checks: [
      .rules[]
      | select(.type == "required_status_checks")
      | .parameters.required_status_checks[]?.context
    ],
    strict_base: (
      .rules[]
      | select(.type == "required_status_checks")
      | .parameters.strict_required_status_checks_policy
    ),
    linear_history: any(.rules[]; .type == "required_linear_history"),
    non_fast_forward: any(.rules[]; .type == "non_fast_forward"),
    deletion: any(.rules[]; .type == "deletion")
  }'
```

If live GitHub ruleset state differs from this runbook, update the ruleset or
this document before relying on release-required enforcement. Do not treat green
`validate-base` and `release-required-result` workflow runs as mandatory unless
the ruleset also requires both contexts.

## Tag creation and release-environment protections

Tracked by the `release-tag-publish-hardening` TODO. `.github/workflows/release.yml`
now has a `verify-tag-on-release` job that asserts the triggering ref (tag push
or `workflow_dispatch`) is `release` or an ancestor of it before build/publish
run, and the real-PyPI `Publish to PyPI` step additionally requires
`startsWith(github.ref, 'refs/tags/v')`. Those are workflow-level (tooling)
controls. The two sections below are the remaining repo-admin-layer half of
the fix — "who can create a `v*` tag at all" and "does the `pypi`
environment require a human approval" — neither of which the develop-PR
`GITHUB_TOKEN` can read or write (no `administration` scope) — only an
admin PAT can.

### Tag creation restricted to release flow (enforced)

Current control: a GitHub tag-protection ruleset targeting `refs/tags/v*` that
restricts tag *creation* to the release automation identity / specific
maintainer actors, mirroring how `develop-squash-only` restricts pushes to
`refs/heads/develop`. Today, `verify-tag-on-release` stops a stray tag from
reaching build/publish only if the tagged commit isn't on `release` — it does
nothing to stop someone with push access from creating a `v*` tag *on* a
release commit out of band (e.g. re-tagging an old release commit, or tagging a
version out of sequence). A tag-creation ruleset is the layer that closes
that gap by restricting who may create the tag in the first place.

Verify (list rulesets and look for one whose `conditions.ref_name.include`
targets `refs/tags/v*` with `target: "tag"`):

```bash
gh api repos/BenchBox-dev/BenchBox/rulesets --jq '.[] | {id, name, target, conditions}'
```

Live verification on 2026-07-21 shows `v-tag-restricted` (ruleset id
`18774756`) is `active`, targets `refs/tags/v*`, carries a `creation` rule,
and has the release-finalize bypass actor `User:57046` with `bypass_mode:
always`. The bypass is required for `make release-finalize` to push its tag;
confirm it remains scoped to that identity.

The ruleset was applied by an admin on 2026-07-10. No PR-side admin mutation is
required; the commands below remain as historical context for the original
application:

```bash
gh api -X POST repos/BenchBox-dev/BenchBox/rulesets \
  -f name='v-tag-restricted' \
  -f target='tag' \
  -f enforcement='active' \
  -f 'conditions[ref_name][include][]=refs/tags/v*' \
  -f 'conditions[ref_name][exclude][]=' \
  -f 'rules[][type]=creation'
# Restricting the actor list further (e.g. to a release-bot identity) needs
# a bypass_actors / rules payload tailored to who should retain the ability
# to tag; draft that with the admin before applying, this is a starting
# point, not the final payload.
```

Why this can't be applied by the write-task's own PR: same as the
soundness-path section above — the develop-PR `GITHUB_TOKEN` has no
`administration` scope to read or write repository rulesets.

Drift detection (landed 2026-07-05, tag-and-pypi-environment-admin-hardening
w3): `_project/scripts/ruleset_review_enforcement.py` carries a
`tag_protection_findings()` predicate and an enforced `TAG_RULESET_ENFORCED`
flag. Feed it the live tag rulesets to check:

```bash
# Fetch each ruleset in full (the list endpoint omits conditions/rules,
# which the predicate correctly treats as "not protected"):
ids=$(gh api repos/BenchBox-dev/BenchBox/rulesets --jq '.[].id')
for id in $ids; do gh api repos/BenchBox-dev/BenchBox/rulesets/$id; done \
  | jq -s '.' \
  | uv run -- python _project/scripts/ruleset_review_enforcement.py --rulesets-file -
```

While `TAG_RULESET_ENFORCED` is `False` (until the POST above lands), a
missing/incomplete `v*`-tag ruleset prints as `WARNING (non-blocking):` and
exits 0 — the check ships before the admin acts without going red. The
predicate flags a ruleset that is not `active`; whose `ref_name.include`
does not cover `refs/tags/v*` (or `~ALL`) under GitHub's fnmatch ref-glob
semantics (an `include`/`exclude` of `refs/tags/*` counts the same as the
literal `refs/tags/v*`, not just a byte-identical string); that lacks a
`creation` rule; or whose `bypass_actors` is explicitly `[]` (a
structurally-valid ruleset with zero bypass actors would itself block
`make release-finalize`'s `git push origin v$(VERSION)`, bricking releases —
that is a finding, not just an advisory). A NON-empty `bypass_actors` list is
not a structural failure (a bypass path is REQUIRED so `make release-finalize`
can still tag) — instead it prints a `CONFIRM before enforcing:` line listing
the bypass actors; verify that list is the release identity only (not a broad
Write/Admin role). An explicit `enforce_tag_rule=False` call remains available
for migration fixtures, but the live default is blocking.

Wired into CI (landed alongside the fnmatch/bypass-empty hardening above):
`scripts/ruleset_drift_check.py`'s `tag_creation_findings()` calls
`tag_protection_findings()`/`tag_bypass_advisory()` against every ruleset
`release-canary.yml`'s `ruleset-drift` job already fetches (the same
`RULESET_DRIFT_TOKEN`-authenticated full-ruleset listing used for the
`develop-squash-only`/`release-only` checks — no second API call), so
the daily canary run itself surfaces tag-ruleset drift as a blocking finding,
with no dependency on
`release-canary-scheduled-activation` beyond the canary running at all.

Live-state note:

```text
# Tag-creation ruleset live state
# checked: 2026-07-21  by: joeharris76 (admin)
# ruleset id: 18774756  enforcement: active  conditions.ref_name.include: [refs/tags/v*]
# rules: [creation]  bypass_actors: [User:57046 (always)]
```

Applied 2026-07-10: `v-tag-restricted` (id 18774756) is live and active. The
bypass list is a single `User` actor (57046, the release-finalize identity) —
confirmed to be the release identity only, not a broad Write/Admin role, which
is what `release-finalize`'s `git push origin v$(VERSION)` needs to still
succeed. With this confirmed, `TAG_RULESET_ENFORCED` in
`_project/scripts/ruleset_review_enforcement.py` is flipped to `True`, so a
future regression (ruleset deleted, made inactive, ref narrowed, creation rule
dropped, or bypass emptied) becomes a blocking drift finding instead of a
warning.

### `pypi` environment required-reviewers gate (configured; observed 2026-08-10)

`release.yml`'s `publish` job already scopes the real-PyPI publish to the
GitHub `environment: pypi` (and `test-pypi` for the test-PyPI path), which
is the correct native mechanism for a required-reviewers/human-approval
gate on publish. The workflow file alone does not prove the `pypi`
environment has `required_reviewers` configured on the repo side — only a
live environments API read does. GitHub enforces the gate at deployment time
when it is configured. `scripts/ruleset_drift_check.py` reads that API in the
existing release-canary drift job and fails closed when the environment,
required-reviewers rule, reviewer identity, admin-bypass posture, or
self-review posture differs from the pin below. The check reuses
`RULESET_DRIFT_TOKEN`, which therefore needs environment-read visibility as
well as full ruleset visibility.

Verify:

```bash
gh api repos/BenchBox-dev/BenchBox/environments/pypi \
  --jq '{name, can_admins_bypass, protection_rules: [.protection_rules[] | {type, prevent_self_review, reviewers: [.reviewers[]?.reviewer.login]}]}'
```

Live verification on 2026-08-10 (command above) shows the `pypi` environment
already carries a required-reviewers gate:

```text
# pypi environment live state
# checked: 2026-08-10  by: joeharris76 (admin)
# command: gh api repos/BenchBox-dev/BenchBox/environments/pypi --jq '{name, can_admins_bypass, protection_rules: [.protection_rules[] | {type, prevent_self_review, reviewers: [.reviewers[]?.reviewer.login]}]}'
# observed: {"name":"pypi","can_admins_bypass":true,"protection_rules":[{"reviewers":["joeharris76"],"type":"required_reviewers","prevent_self_review":false}]}
# type: required_reviewers  reviewer login(s): joeharris76  (User id 57046)
# can_admins_bypass: true  prevent_self_review: false  wait_timer: null  deployment_branch_policy: null
```

No admin mutation required for this gate — it is already configured. The
`can_admins_bypass: true` + `prevent_self_review: false` pair is the accepted
single-admin / self-review posture for this repo (one maintainer is both the
required reviewer and an admin who can still approve or bypass their own
deployment). The release canary continuously detects a removed rule, emptied
or replaced reviewer set, deleted environment, or changed bypass/self-review
flag. Re-run the verify command above for operator diagnosis when the canary
reports drift.

`test-pypi` intentionally has no protection rules (lower friction for dry-run
publish paths). Observed on 2026-08-05:

```bash
gh api repos/BenchBox-dev/BenchBox/environments/test-pypi --jq '{name, protection_rules}'
# {"name":"test-pypi","protection_rules":[]}
```

That empty gate is accepted by design; do not copy the real-PyPI
`required_reviewers` rule onto `test-pypi` unless a future policy change
explicitly wants the same friction on the test path.

Historical re-apply reference (admin only, if the live verify ever shows the
gate missing):

```bash
gh api -X PUT repos/BenchBox-dev/BenchBox/environments/pypi \
  -f 'reviewers[][type]=User' \
  -f 'reviewers[][id]=57046'
```

## Release canary and ruleset drift

Release readiness has one scheduled/manual canary:

```text
workflow: .github/workflows/release-canary.yml
schedule: daily at 08:00 UTC
freshness_sla: 48h
blocking_suite: (slow or resource_heavy) and not (stress or live_integration)
advisory_suites: stress, live_integration, live cloud credentials
```

Long-running UAT is an advisory campaign. Release readiness requires the
blocking release canary; see `docs/operations/release-guide.md` "UAT matrix
campaign evidence (advisory)" for the optional UAT report.

`validate-release-pr.yml` keeps the required context name `validate-base`, but
that job now also runs `scripts/release_readiness_check.py` for release PRs.
It fails when the latest completed `release-canary.yml` run is missing, red,
older than 48 hours, or when the tested `develop` SHA recorded in the canary
summary artifact is not an ancestor of the release PR head. Scheduled canary
runs execute from the default branch, then check out `develop` before running
release evidence and recording `commit_sha` in `release-canary-summary.json`.
For the first release that introduces `release-canary.yml`, before GitHub can
run the workflow from the default branch, `validate-base` runs the same
non-fast canary suite and ruleset drift check inline as bootstrap evidence.

Ruleset drift is checked for every develop PR by
`develop-ruleset-drift.yml` and independently by `release-canary.yml`. The PR
workflow uses `pull_request_target`, checks out only the trusted base SHA, and
never executes pull-request-head code with the admin-visible token. Its
`ruleset-drift` job is a required `develop-squash-only` context, so drift blocks
the next merge instead of waiting for the scheduled canary. The script parses this runbook for
`develop-squash-only` and `release-only`, then compares live GitHub
rulesets for required status check contexts, strict-base settings, bypass
actors, linear history, non-fast-forward protection, deletion protection, and
target refs. For `develop-squash-only`, it also applies the shared
`review_enforcement_findings` predicate and treats a missing or false
`require_code_owner_review` as a blocking finding through
`DEVELOP_REVIEW_RULE_ENFORCED = True`. The
Both workflows must use the repository secret `RULESET_DRIFT_TOKEN`
with enough ruleset write/admin visibility for the API to expose
`bypass_actors`; the default `GITHUB_TOKEN` is intentionally not used for this
check. If GitHub API access fails, the canary is red; release PRs then fail on
stale/red canary evidence instead of silently trusting comments.
`validate-release-pr.yml`'s bootstrap invocation (~line 115) runs the identical
script with the identical token, so the same review-rule coverage is reachable
from both CI call sites without a separate code path.

### Scheduled activation of `release-canary.yml` (RESOLVED 2026-07-08)

> **RESOLVED 2026-07-08 by the default-branch switch (Decision A,
> `branch-default-switch-to-develop`).** The GitHub default branch is now
> `develop` (`gh api repos/BenchBox-dev/BenchBox --jq .default_branch` →
> `develop`). GitHub runs `on.schedule` workflows from the **default** branch's
> copy, so every develop-authored scheduled workflow now registers and fires
> directly — the "land it on `main`" problem below no longer exists. Verified
> 2026-07-08 via the Actions list-workflows API: `release-canary.yml`
> (id 309070628), `phase3-promotion-review.yml`, and
> `orphaned-commit-detector.yml` are now registered (26 workflows, up from 19).
> Activation options (a)/(b)/(c) and the "Admin steps (w2)" below are
> **superseded** and retained only as history. The `nightly.yml`
> `scheduled-workflow-liveness` guard now runs from `develop` directly (no
> "until its file lands on `main`" caveat). The canary's first scheduled run is
> expected **RED** on the broken 0.3.0 PyPI release (see
> `release-recovery-v0-3-1`) — that is the canary working, not a regression.

Historical live state observed 2026-07-05 (release-canary-scheduled-activation TODO, w0):

- `git ls-tree origin/main --name-only .github/workflows/` does **not**
  contain `release-canary.yml` — the file exists only on `develop`.
- The Actions list-workflows API returns 19 registered workflows and
  release-canary is not among them (a workflow absent from the default
  branch with zero historical runs is never registered), so its
  `on.schedule` cron has **never fired** and none of its jobs
  (pypi-latest-installability, ruleset-drift, credential-free-non-fast,
  plus the release-canary-result aggregator) has ever executed.
- Same class, second instance: `phase3-promotion-review.yml` (quarterly
  cron `0 9 1-7 1,4,7,10 *`) is also on `develop` but absent from
  `origin/main`, so its schedule has never fired either. The liveness
  guard below will name it alongside release-canary; the admin should
  land it on `main` in the same pass (or deliberately remove its
  schedule and record that decision here). Its `review` job now checks out
  `develop` explicitly via a `PHASE3_REVIEW_REF` env var (the same
  `RELEASE_CANARY_REF` shell pattern release-canary.yml uses), so landing
  the file on `main` does not leave a scheduled run checking out `main`'s
  stripped tree (no `_project/` or `scripts/phase2_metrics.py`) by default.
- Same class, third instance (#1020 review): `orphaned-commit-detector.yml`
  (weekly cron `0 7 * * 1`) is also on `develop` but absent from
  `origin/main`, so its schedule has never fired either — only its
  path-filtered `push: branches: [develop]` trigger can run, on the cadence
  of detector/allowlist edits rather than weekly. It already hardcodes
  `ref: develop` on its checkout step (the same shell pattern as
  release-canary.yml/phase3-promotion-review.yml), so it is safe to land on
  `main` as-is whenever the admin does the next pass for this class of fix —
  no `main`-relative edits needed first.

GitHub runs `on.schedule` workflows only from the default branch (historically
`main`; **now `develop` as of 2026-07-08** — see the RESOLVED note above, which
makes the options below historical).
Activation options considered (w1):

- **(a) Admin lands the current `release-canary.yml` on `main` out-of-band**
  (cherry-pick/push through the documented admin flow; `main` is
  push-restricted, so admin-only). Fastest path; content on `main` then
  goes stale between release-cuts unless (c) also holds.
- **(b) Wait for the next release-cut to carry it.** Zero extra action, but
  the canary stays dead until v0.3.1 ships — the exact window it guards.
- **(c) Keep `main`'s copy a minimal stable scheduled shell that checks out
  `develop` for current logic.** The file already follows this shape: the
  test and drift jobs check out `develop` via `RELEASE_CANARY_REF`, and
  pypi-latest-installability needs no checkout at all. Only future
  *workflow-structure* edits (job graph, permissions, schedule) need
  re-landing on `main`; test/drift *content* tracks `develop` automatically.

**Recommendation (recorded 2026-07-05): (a) + (c) together** — land the
current `develop` copy of `release-canary.yml` on `main` once (it already is
the (c) shell), keep logic on `develop`.

Admin steps (w2 — maintainer action, never an agent push):

1. Land `develop`'s `.github/workflows/release-canary.yml` on `main` via the
   admin/release flow.
2. Confirm registration: the workflow appears in
   `gh api repos/BenchBox-dev/BenchBox/actions/workflows --jq '.workflows[].path'`.
3. Trigger `workflow_dispatch` (or wait for the next 08:00 UTC cron) and
   record the run URL here as proof-of-life.
4. **Expected first result: RED** — pypi-latest-installability correctly
   fails on the broken 0.3.0 PyPI release (`ModuleNotFoundError: pandas` on
   clean install). That is the canary working; cross-link the red run in
   `release-recovery-v0-3-1` as live pressure for the recovery release. Do
   not weaken the canary to get a green first run.

Once the canary is live, the `scheduled-workflow-liveness` job in
`nightly.yml` (added 2026-07-05, executes once its copy reaches `main`)
asserts daily that every workflow in the `develop` tree declaring
`on.schedule` has a recent run of `event=schedule` within a
cadence-derived window (3 days for daily crons, up to 100 days for
quarterly ones), so this dead-scheduled-workflow class cannot recur
silently. Deliberate consequence: a scheduled workflow newly authored on
`develop` reads red in that guard until its file lands on `main`.

Emergency override is intentionally explicit and SHA-scoped. Admins may set
both repository variables below, then remove them after the release:

```text
RELEASE_READINESS_OVERRIDE_SHA: exact release PR head SHA
RELEASE_READINESS_OVERRIDE_REASON: incident or approval record
```

The override is recorded in the `validate-base` job summary. Do not use it for
routine canary failures; fix the non-fast canary, ruleset drift, or GitHub API
access and let the canary return to green.

## Repository labels

The `develop-post-merge.yml` auto-revert job creates these labels on
demand if they do not exist:

- `incident:develop-red` — used on the auto-revert PR.
- `incident:develop-red-revert-conflict` — used on the manual-action
  issue when the revert path cannot complete (revert conflict, push
  failure, PR-creation failure).

The on-demand `gh label create … || true` in the workflow means a fresh
clone or transfer does not need the labels pre-created. They will appear
the first time develop goes red.

Verify:

```bash
gh label list --search incident
```

## Re-applying after a transfer or restore

The 2026-08-21 cutover to org `BenchBox-dev` is documented in
`docs/operations/github-org-transfer.md` (gates G0–G7b, Pages
serving-only vs publish, exclusive Pages domain lock: do not click
org Verify before G4, org `protected_domain` verification after G4,
environment `deployment-branch` policies, `RULESET_DRIFT_TOKEN`
authentication, and **never recreate** `joeharris76/BenchBox`). Follow
that runbook for an ownership transfer. The numbered restore below is
the subset that still applies after a backup restore or ruleset wipe
**without** changing owners.

If the repo is restored from backup or the rules drift without a
transfer, re-apply in this order:

1. Workflow permissions (`gh api -X PUT … actions/permissions/workflow`).
2. Develop ruleset — recreate `develop-squash-only` with the required
   contexts list above. The ruleset id will change; update this file
   and the `Makefile`/`scripts/` references that hard-code it. Prefer
   resolving the live ruleset **by name** (`develop-squash-only`) in
   workflows; do not treat a stale numeric id as authority.
3. Verify with the `gh api … rulesets/<id> --jq …` command above.
4. Push a no-op commit to develop and confirm `develop-post-merge.yml`
   produces a `metrics` artifact and the lint + fast-test jobs are green.
   This validates that workflow permissions are correct end-to-end.

## Out-of-scope

This runbook covers only the GitHub admin state that the dev-loop
workflows depend on. Other GitHub settings (collaborators, secrets,
webhooks, Pages, environments, deploy keys) are out of scope here.
Keep them in their own runbook if they grow load-bearing.
