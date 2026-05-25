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
that aggregates `ci-paths`, `content-guard`, `code-lint`, and `code-test`.
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
for release PR correctness. It aggregates the required fast lane,
integration-not-slow suite, isolated exact-one-wheel package smoke,
dependency upper-bound checks, and release-branch curation checks. It is
the ruleset context maintainers should use instead of individual matrix job
names such as `test-package (...)`.

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
this document before relying on release-required enforcement. Do not treat a
green `release-required-result` workflow run as mandatory unless the ruleset
also requires that context.

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
