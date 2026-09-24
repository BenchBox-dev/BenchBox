# Require public-site visual acceptance before merging into develop

Date: 2026-09-24
Status: Decision recorded; enforcement is pending implementation.

## Decision

Choose **option 3**: make public-site visual acceptance a required check for
changes merging into `develop`. A changed capture must be fixed or receive the
existing explicit, exact-head maintainer approval before merge. Keep the
current visual comparison scope and its fail-closed exact-base-SHA rule while
building the required check. This decision does not itself change the workflow
or the hosted ruleset.

## Evidence and rationale

The [documentation failure triage](../analysis/docs-failure-triage-2026-09-17.md)
classified 119 visual job failures among 164 failed Documentation runs from
2026-08-23 through 2026-09-16. About 100 were real differences on pages the
PR changed; sampled PRs merged without a recorded approval. The subsequent
2026-09-17 through 2026-09-24 measurement recorded in the tracker found 21
visual failures among 23 failed documentation PR runs. The link repair reduced
linkcheck failures to two, leaving visual comparison as the dominant cause.

## Alternatives considered

Filtering the visual job to site-rendered paths would still run it for the
page-changing PRs that caused most of the failures. It would also accept the
risk of missing a rendered-site input omitted from the path list. Keeping the
current advisory policy accepts roughly 70 red runs per 25 days with no
required response. A required check makes the observed differences actionable.

The cost is longer or blocked merges for intentional page changes until a
maintainer reviews diagnostics and approves the exact head. Baseline producer
gaps can also block a PR until the exact protected baseline is recovered. The
implementation must retain a practical approval and recovery path; it must not
turn a missing baseline or an absent workflow run into a pass.

## Implementation boundary

### Prior art

[`results-explorer-browser.yml`](../../.github/workflows/results-explorer-browser.yml)
uses an always-reporting gate around conditional browser jobs. Extend that
pattern for visual acceptance; do not require a conditional job directly.
[`docs.yml`](../../.github/workflows/docs.yml) already provides the assembled
site, visual capture, exact-base lookup, and protected baseline producer. Keep
those contracts rather than introducing another visual harness.

The live `develop-squash-only` ruleset currently requires
`ci-required-result`, `Results Explorer browser gate`, and `ruleset-drift`.
Making visual acceptance required needs an explicit update to that ruleset and
its drift policy. Adding the current `Public-site visual regression` job as a
required context directly would strand unrelated PRs: `docs.yml` has a PR
path filter and no `merge_group` trigger. Follow the existing always-reporting
browser gate pattern in [repo admin settings](../../docs/operations/repo-admin-settings.md):
an aggregate visual context must report on every PR and merge group, and fail
closed when comparison is applicable but did not run or could not establish its
exact baseline. Preserve all current visual inputs; any future exclusion must
name the rendered-site input it removes and the resulting coverage loss.

The no-baseline-bound-to-base-SHA failures are a distinct baseline-supply
problem within that implementation, not a reason to loosen comparison. The
protected `develop` push is the sole baseline producer today, and its dropped
event can leave a new base SHA without an artifact. Provide a bounded,
automated way to produce or recover the protected exact-SHA artifact before
requiring the check. Preserve SHA binding, manifest validation, and the ban on
promoting PR diagnostics into baselines. The current manual recovery command is
`gh workflow run docs.yml --ref develop`.

The required-check rollout must prove that ordinary PRs report a successful
non-applicable result, site-changing PRs report the visual result, and merge
groups cannot bypass it. It must also update the ruleset documentation and
drift guard with the hosted ruleset change. Until then, visual acceptance
remains advisory in the live repository.
