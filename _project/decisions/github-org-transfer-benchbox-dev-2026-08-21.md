# Decision: Transfer BenchBox to GitHub organization `BenchBox-dev`

Date: 2026-08-21
Status: Accepted for planning and pre-transfer in-repo work. Transfer itself
is operator-only and remains behind gates G0+G1+G2+G3.
Destination: `https://github.com/BenchBox-dev/BenchBox`
Source: `https://github.com/joeharris76/BenchBox`

Related: `_project/decisions/strict-base-refresh-policy-2026-08-14.md`;
`_project/decisions/strict-base-refresh-merge-queue-2026-08-14.md`;
`_project/decisions/strict-base-refresh-activation-2026-08-14.md`
(`SHADOW_ONLY`); `docs/operations/repo-admin-settings.md`;
`docs/operations/github-org-transfer.md`.

This record authorizes transferring repository **ownership** to org
`BenchBox-dev`. It does **not** authorize native merge queue, `merge_group`
workflows, reduced-refresh skips, or un-dropping
`strict-base-refresh-07b-native-merge-queue-migration`.

## Decision

Transfer `joeharris76/BenchBox` to `BenchBox-dev/BenchBox`. Keep the
repository name. Keep squash-only develop, strict current-base checks, and
`bypass_actors: none` on `develop-squash-only`. Keep CODEOWNERS
`@joeharris76` and the `pypi` environment reviewer `User:57046`.

Do not change `benchbox/core/joinorder/data_manifest.toml` `url` (it is
inside `manifest_hash`) or `_DEFAULT_ANSWERS_BASE_URL` (published wheels
hardcode it). GitHub Releases redirects from the old owner/name are a
shipped-artifact availability dependency. Never recreate
`joeharris76/BenchBox`.

Owner-agnostic CI hardening lands **before** transfer. Public URL
retargeting lands **after** hosted rebuild.

## Non-goals

- Native merge queue, `merge_group`, reduced-refresh skip paths.
- Moving `textcharts`, `skill-sync`, or `skill-sync-skills`.
- Adding develop ruleset bypass actors to relieve CODEOWNERS self-approval.
- Renaming Turso (`benchbox-todo-joeharris76...`), PyPI project `benchbox`,
  or domain `benchbox.dev`.
- Rewriting published blog permalinks.

## Prior-decision reconciliation

| Record | Relation |
|---|---|
| strict-base-refresh-policy | Transfer remains operator-only. This record does not mutate ruleset 15611785 before transfer. |
| strict-base-refresh-merge-queue assessment | Reuse inventory. Do not execute its queue path. Destination is now `BenchBox-dev`. |
| SHADOW_ONLY activation | Still governs. `07b` stays dropped. Availability of merge queue after transfer is not authorization. |
| repo-admin-settings | Extend via `docs/operations/github-org-transfer.md`. |
| future-state index / support-tier freeze | Out of scope. |

## Review disposition (Claude + Agy, 2026-08-21)

Accepted: transfer-fragile `GITHUB_REPOSITORY` tests; JoinOrder URL is
identity; Pages `curl` is serving-only; shadow workflow must resolve
`develop-squash-only` by name not id `15611785`; org-level
`benchbox.dev` verification before transfer; `admin:org` and PAT policy;
Actions `allowed_actions=all`; environment JSON rebuild including
`github-pages` release-only branch policy; pin-update avoids soundness
paths; never change answers default URL; issue template is wrong user
**and** `main`; `ruleset-drift` keys by name not ID; PyPI dual-register
on the existing `benchbox` project is the primary G2 path.

Rebutted: adding `User:57046` or `OrganizationAdmin` bypass on
`develop-squash-only`. Live policy is `bypass_actors: none`. This program
preserves that gate.

## Gates

```text
G0  Org hardening + admin:org + benchbox.dev org verification + PAT policy
G1  Decision/runbook + owner-agnostic CI merged
G2  PyPI + TestPyPI trusted publishers for BenchBox-dev/BenchBox
G3  Merge freeze + ruleset/env JSON snapshot + written operator GO
G4  Transfer
G5  Hosted rebuild (capability, not names-only); Pages serving-only
G6  Pin-update PR (no soundness paths)
G7  Redirects, downloads, scheduled workflows, Codecov, ruleset-drift
G7b First post-transfer push to release proves Pages publish path
```

Agents may complete G1 (and G6 after G5). G0, G2–G5, and G7b are
operator. Completing an operator-gated TODO without its gate is a defect.

## Abort

Abort G0 if `BenchBox-dev` is not empty of a `BenchBox` repo or the
operator is not org admin. Abort G3 if a release is in flight or
`incident:develop-red` is open. Abort G4 if dest `full_name` is wrong.
Abort G5 if `benchbox.dev` stops serving. Do not leave the custom domain
unverified overnight.

## Rollback

Phase 1/6 PRs revert on `develop`. Transfer org→user is last resort
(Pages flaps twice). Queue disable is N/A (must not be enabled).
