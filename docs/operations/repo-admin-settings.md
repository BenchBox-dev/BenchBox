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
gh api repos/joeharris76/BenchBox/actions/permissions/workflow
```

Apply (admin only):

```bash
gh api -X PUT repos/joeharris76/BenchBox/actions/permissions/workflow \
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
```

`ci-required-result` is the umbrella job in `.github/workflows/pr.yml`
that aggregates the required-lane jobs: `ci-paths`, `content-guard`,
`code-lint`, `code-test`, `correctness-gate`, `plan-capture-gate`,
`medium-test` (added 2026-07-11, #1139 — the medium tier now gates code
PRs pre-merge via the same umbrella, no ruleset change needed),
`explorer-tokens`, `audit-sha`, `package-smoke`, and `dependency-audit`.
Branch protection deliberately keys off the umbrella so the path-aware
classifier can skip subordinate jobs without making the protected check
disappear. The classifier fails closed: any path not on the
`safe-content` allowlist in `.github/path-filters.yml` (including unknown
top-level paths) routes through `code-lint` + `code-test`.

Other ruleset properties to preserve:

```text
strict_required_status_checks_policy: false
required_linear_history: true
non_fast_forward: true
required_pull_request_reviews:    squash-only PRs
deletion: blocked
bypass_actors: (none)
```

Verify:

```bash
gh api repos/joeharris76/BenchBox/rulesets/15611785 --jq '
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

### Soundness-path review enforcement (pending admin action)

The `develop-squash-only` ruleset's `pull_request` rule must require a code-owner
review so a PR touching the CODEOWNERS-owned soundness paths cannot be
squash-merged with zero approvals. The authoritative path list is
`SOUNDNESS_PREFIXES` in `_project/scripts/auto_merge_soundness_paths.py`
(mirrored 1:1 into `.github/CODEOWNERS`); as of `soundness-surface-widening`
it covers the comparators/parsers (`benchbox/core/equivalence/**`,
`benchbox/core/query_plans/parsers/**`, `benchbox/core/**/validation.py`),
the oracle-adjacent surface (`benchbox/core/expected_results/**`,
`benchbox/platforms/base/result_capture.py`, the `benchbox/sql_compat/`
rule-dispatch core), and the review-gate machinery itself
(`_project/scripts/auto_merge_soundness_paths.py`,
`.github/workflows/auto-merge-on-open.yml`, `.github/workflows/release.yml`).
The self-protection entries matter because in-workflow checks are
attacker-controlled for same-repo PRs (GitHub runs the PR's own copy of a
`pull_request`-triggered workflow); this CODEOWNERS + ruleset layer is the
durable control. The auto-merge code side already withholds auto-merge
enablement for those paths, but withholding is only a precondition — without
this ruleset requirement a soundness-path PR can still be squash-merged
manually. Tracked by the `auto-merge-review-gate-admin-enforcement` TODO.

Target state:

```text
require_code_owner_review: true
```

`required_approving_review_count` is deliberately NOT part of the target state:
GitHub's `pull_request` rule applies that count to EVERY PR against the branch, not
just CODEOWNERS-matched paths, so requiring `>= 1` would gate every develop PR
instead of just soundness-path ones — defeating the fast squash-auto-merge default.
`require_code_owner_review: true` is independently sufficient: GitHub still requires
an owner's approval on a PR that touches a CODEOWNERS-matched soundness path
regardless of the count setting.

Live state at this writing: `require_code_owner_review: false` — not yet enforced.
Applying it is a deferred repo-admin action: the develop-PR `GITHUB_TOKEN` has no
`administration` scope, so it can neither read nor write the ruleset; only an admin
PAT can.

As of `ruleset-drift-check-review-rule-coverage`, this predicate is now wired into
`scripts/ruleset_drift_check.py`'s `compare_ruleset` (see "Ruleset drift is checked
by `scripts/ruleset_drift_check.py`" below) — the daily `release-canary.yml` run and
`validate-main-pr.yml`'s bootstrap invocation both surface a missing
`require_code_owner_review` as a finding automatically, using the
`RULESET_DRIFT_TOKEN` those workflows already fetch rulesets with. **Decision:
WARN-until-enforced** — while the live state above says `false`, that finding is
prefixed `WARNING (non-blocking):` in the canary's findings/JSON output and does
**not** fail the canary or the exit code (`scripts/ruleset_drift_check.py`'s
`DEVELOP_REVIEW_RULE_ENFORCED = False`). This avoids the canary going permanently
red before the admin PUT below lands. Once this section's "Live state" is updated
to `require_code_owner_review: true`, flip `DEVELOP_REVIEW_RULE_ENFORCED` to `True`
(a one-line change) so the same gap starts failing the canary if it ever regresses.

The manual, one-off verify command below still works standalone (e.g. to check
current live state without waiting for the next canary run):

```bash
gh api repos/joeharris76/BenchBox/rules/branches/develop \
  | uv run --project _project/scripts -- python _project/scripts/ruleset_review_enforcement.py --rules-file -
```

The predicate exits non-zero and names the offending field while review enforcement
is missing, and exits zero once the ruleset requires a code-owner review. Its pinned
logic is guarded by `tests/unit/release/test_ruleset_review_enforcement.py`, and the
merged drift-checker behaviour (WARN-until-enforced, develop-only scoping) is
guarded by `tests/unit/release/test_ruleset_drift_review_coverage.py`, both in the
required fast lane.

Apply (admin only — the deferred action that closes the gap):

```bash
# Fetch the current ruleset, set the pull_request rule parameter
#   require_code_owner_review: true
# then PUT it back.
gh api repos/joeharris76/BenchBox/rulesets/15611785 > /tmp/develop-ruleset.json
# edit /tmp/develop-ruleset.json (pull_request rule parameters), then:
gh api -X PUT repos/joeharris76/BenchBox/rulesets/15611785 --input /tmp/develop-ruleset.json
```

After applying, re-run the Verify command (expect exit 0) and confirm a zero-approval
soundness-path PR can no longer be squash-merged.

**Order of operations (the flag flip is coupled to this PUT — do it second, never first):**

1. Apply the PUT above so the live `develop-squash-only` ruleset actually carries
   `require_code_owner_review: true`, and update this section's "Live state" line to `true`.
2. Only then flip the one-line constant in `scripts/ruleset_drift_check.py:47`:

   ```diff
   -DEVELOP_REVIEW_RULE_ENFORCED = False
   +DEVELOP_REVIEW_RULE_ENFORCED = True
   ```

Flipping the constant **before** step 1 turns the (still-live) missing-review gap from a
`WARNING (non-blocking):` finding into a blocking one, which reddens **both** the daily
`release-canary.yml` run **and** `validate-main-pr.yml`'s drift-check on every real develop
PR until the PUT lands. Done in the correct order, the flip's own CI is green (the live
ruleset already satisfies the rule). No test changes are required: `compare_ruleset`'s
`enforce_review_rule` parameter is exercised in both `False`/`True` modes by
`tests/unit/release/test_ruleset_drift_review_coverage.py`, so the constant's value does
not itself make any unit test pass or fail.

History:

- Switched required status check from
  `["lint", "test (ubuntu-latest, 3.12)"]` to `["ci-required-result"]` on
  2026-04-30 as Step 3a w7. Recorded in
  `_project/decisions/dev-loop-path-filter-smoke-test-2026-04-30.md`
  with full before/after JSON.

## Branch ruleset — `main`

Ruleset name: `main-release-only`, targets `refs/heads/main`.

Release-only branch. Direct pushes are not allowed; releases land via the
`release-cut` / `release-finalize` Make targets documented in
`release-guide.md`.

Required status checks:

```text
- validate-base
- release-required-result
```

`validate-base` is the branch-shape guard in
`.github/workflows/validate-main-pr.yml`. It allows only release branches
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
gh api repos/joeharris76/BenchBox/rulesets --jq '.[] | {id, name, target}'
gh api repos/joeharris76/BenchBox/rulesets/<main-ruleset-id> --jq '
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
now has a `verify-tag-on-main` job that asserts the triggering ref (tag push
or `workflow_dispatch`) is `main` or an ancestor of it before build/publish
run, and the real-PyPI `Publish to PyPI` step additionally requires
`startsWith(github.ref, 'refs/tags/v')`. Those are workflow-level (tooling)
controls. The two sections below are the remaining repo-admin-layer half of
the fix — "who can create a `v*` tag at all" and "does the `pypi`
environment require a human approval" — neither of which the develop-PR
`GITHUB_TOKEN` can read or write (no `administration` scope), same
constraint as the soundness-path review enforcement gap above.

### Tag creation restricted to release flow (pending admin action)

Target state: a GitHub tag-protection ruleset targeting `refs/tags/v*` that
restricts tag *creation* to the release automation identity / specific
maintainer actors, mirroring how `develop-squash-only` restricts pushes to
`refs/heads/develop`. Today, `verify-tag-on-main` stops a stray tag from
reaching build/publish only if the tagged commit isn't on `main` — it does
nothing to stop someone with push access from creating a `v*` tag *on* a
main commit out of band (e.g. re-tagging an old main commit, or tagging a
version out of sequence). A tag-creation ruleset is the layer that closes
that gap by restricting who may create the tag in the first place.

Verify (list rulesets and look for one whose `conditions.ref_name.include`
targets `refs/tags/v*` with `target: "tag"`):

```bash
gh api repos/joeharris76/BenchBox/rulesets --jq '.[] | {id, name, target, conditions}'
```

Live state at time of writing (2026-07-03): no ruleset with `target: "tag"`
exists. The only ruleset whose name resembles this (`v-release-branches-minimal`,
id `15611787`) targets *branches* matching `refs/heads/v*`, not tags — it is
unrelated to tag creation. Any collaborator with push access can create a
`v*` tag today.

Apply (admin only):

```bash
gh api -X POST repos/joeharris76/BenchBox/rulesets \
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
w3): `_project/scripts/ruleset_review_enforcement.py` now carries a
`tag_protection_findings()` predicate and a `TAG_RULESET_ENFORCED`
warn-until-applied flag, mirroring `ruleset_drift_check.py`'s
`DEVELOP_REVIEW_RULE_ENFORCED`. Feed it the live tag rulesets to check:

```bash
# Fetch each ruleset in full (the list endpoint omits conditions/rules,
# which the predicate correctly treats as "not protected"):
ids=$(gh api repos/joeharris76/BenchBox/rulesets --jq '.[].id')
for id in $ids; do gh api repos/joeharris76/BenchBox/rulesets/$id; done \
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
the bypass actors; verify that list is the release identity only (not a
broad Write/Admin role) before flipping the flag. After applying the
ruleset and confirming the bypass list, flip `TAG_RULESET_ENFORCED = True`
(a one-line change, tested by `test_ruleset_drift_review_coverage.py`) so
the gap becomes blocking.

Wired into CI (landed alongside the fnmatch/bypass-empty hardening above):
`scripts/ruleset_drift_check.py`'s `tag_creation_findings()` calls
`tag_protection_findings()`/`tag_bypass_advisory()` against every ruleset
`release-canary.yml`'s `ruleset-drift` job already fetches (the same
`RULESET_DRIFT_TOKEN`-authenticated full-ruleset listing used for the
`develop-squash-only`/`main-release-only` checks — no second API call), so
the daily canary run itself surfaces tag-ruleset drift under the same
WARN-until-applied gating as the develop review rule, with no dependency on
`release-canary-scheduled-activation` beyond the canary running at all.

Live-state note (fill in after applying — do not leave blank):

```text
# Tag-creation ruleset live state
# checked: 2026-07-10  by: joeharris76 (admin)
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

### `pypi` environment required-reviewers gate (verify/pending admin action)

`release.yml`'s `publish` job already scopes the real-PyPI publish to the
GitHub `environment: pypi` (and `test-pypi` for the test-PyPI path), which
is the correct native mechanism for a required-reviewers/human-approval
gate on publish. The workflow file alone does not prove the `pypi`
environment has `required_reviewers` configured on the repo side.

Verify:

```bash
gh api repos/joeharris76/BenchBox/environments/pypi
```

Check the response's `protection_rules` array for an entry with
`type: "required_reviewers"` and a non-empty `reviewers` list.

Live state at time of writing: not independently re-verified in this
session (no `gh`/network access available in this sandbox to call the API).
No prior record of `required_reviewers` being configured for the `pypi`
environment exists elsewhere in this repo's admin history
(`_project/decisions/`), so treat it as unconfirmed/likely absent until an
admin runs the verify command above and records the result here.

Apply (admin only, if the verify command shows no `required_reviewers`
rule):

```bash
gh api -X PUT repos/joeharris76/BenchBox/environments/pypi \
  -f 'reviewers[][type]=User' \
  -f 'reviewers[][id]=<github-user-id-of-approver>'
```

Repeat for the `test-pypi` environment only if the same gate is desired
there (lower risk by design; optional).

After applying (or confirming already applied), record the positive
confirmation here — do not leave this section silent about live state.

## Release canary and ruleset drift

Release readiness has one scheduled/manual canary:

```text
workflow: .github/workflows/release-canary.yml
schedule: daily at 08:00 UTC
freshness_sla: 48h
blocking_suite: (slow or resource_heavy) and not (stress or live_integration)
advisory_suites: stress, live_integration, live cloud credentials
```

Long-running UAT is no longer advisory: release readiness also requires
committed UAT release-gate evidence — see `docs/operations/release-guide.md`
"UAT release-gate evidence (required)".

`validate-main-pr.yml` keeps the required context name `validate-base`, but
that job now also runs `scripts/release_readiness_check.py` for release PRs.
It fails when the latest completed `release-canary.yml` run is missing, red,
older than 48 hours, or when the tested `develop` SHA recorded in the canary
summary artifact is not an ancestor of the release PR head. Scheduled canary
runs execute from the default branch, then check out `develop` before running
release evidence and recording `commit_sha` in `release-canary-summary.json`.
For the first release that introduces `release-canary.yml`, before GitHub can
run the workflow from the default branch, `validate-base` runs the same
non-fast canary suite and ruleset drift check inline as bootstrap evidence.

Ruleset drift is checked by `scripts/ruleset_drift_check.py` inside
`release-canary.yml`. The script parses this runbook for
`develop-squash-only` and `main-release-only`, then compares live GitHub
rulesets for required status check contexts, strict-base settings, bypass
actors, linear history, non-fast-forward protection, deletion protection, and
target refs. For `develop-squash-only` only, it also imports
`review_enforcement_findings` from
`_project/scripts/ruleset_review_enforcement.py` (see "Soundness-path review
enforcement" above) and surfaces a missing code-owner-review rule as a
`WARNING (non-blocking):`-prefixed finding — visible in the job summary and
JSON output, but not yet failing the canary (WARN-until-enforced; flips to
blocking via `DEVELOP_REVIEW_RULE_ENFORCED` once the admin PUT lands). The
workflow must use the repository secret `RULESET_DRIFT_TOKEN`
with enough ruleset write/admin visibility for the API to expose
`bypass_actors`; the default `GITHUB_TOKEN` is intentionally not used for this
check. If GitHub API access fails, the canary is red; release PRs then fail on
stale/red canary evidence instead of silently trusting comments.
`validate-main-pr.yml`'s bootstrap invocation (~line 115) runs the identical
script with the identical token, so the same review-rule coverage is reachable
from both CI call sites without a separate code path.

### Scheduled activation of `release-canary.yml` (RESOLVED 2026-07-08)

> **RESOLVED 2026-07-08 by the default-branch switch (Decision A,
> `branch-default-switch-to-develop`).** The GitHub default branch is now
> `develop` (`gh api repos/joeharris76/BenchBox --jq .default_branch` →
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
   `gh api repos/joeharris76/BenchBox/actions/workflows --jq '.workflows[].path'`.
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

If the repo is transferred, restored from backup, or the rules drift,
re-apply in this order:

1. Workflow permissions (`gh api -X PUT … actions/permissions/workflow`).
2. Develop ruleset — recreate `develop-squash-only` with the required
   contexts list above. The ruleset id will change; update this file
   and the `Makefile`/`scripts/` references that hard-code it.
3. Verify with the `gh api … rulesets/<id> --jq …` command above.
4. Push a no-op commit to develop and confirm `develop-post-merge.yml`
   produces a `metrics` artifact and the lint + fast-test jobs are green.
   This validates that workflow permissions are correct end-to-end.

## Out-of-scope

This runbook covers only the GitHub admin state that the dev-loop
workflows depend on. Other GitHub settings (collaborators, secrets,
webhooks, Pages, environments, deploy keys) are out of scope here.
Keep them in their own runbook if they grow load-bearing.
