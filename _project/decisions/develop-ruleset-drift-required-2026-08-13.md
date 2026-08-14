# Decision: require live ruleset drift evidence on develop PRs

Date: 2026-08-13
Status: Implemented in repository; live ruleset activation follows this PR.

## Context

The `develop-squash-only` ruleset previously drifted to
`strict_required_status_checks_policy: false`. The repository corrected the
live value and added a daily/release canary, but a later admin change could
still recreate the same stale-base merge window before the next canary.

The drift script needs `RULESET_DRIFT_TOKEN` because the default workflow token
cannot expose bypass actors. Running pull-request code with that token would be
unsafe.

## Decision

Add `develop-ruleset-drift.yml` on `pull_request_target` and make its
`ruleset-drift` job a required context for `develop-squash-only`.

The workflow checks out `github.event.pull_request.base.sha`, never the PR head,
uses read-only repository permissions, and runs the trusted base copy of the
existing fail-closed drift script. Evidence is retained for 30 days. The daily
canary remains an independent release gate.

## Activation sequence

1. Merge the workflow, tests, runbook, and this decision record.
2. Add `ruleset-drift` to ruleset 15611785's required status checks while
   preserving strict-base enforcement and every other rule.
3. Verify the next develop PR reports the required context from trusted base
   code and that the drift script sees the updated live ruleset.

The context cannot be required before the workflow exists on the base branch;
doing so would deadlock the introducing PR.
