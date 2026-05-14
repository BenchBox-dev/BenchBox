---
develop_sha: 1241ed9da6073984b305b6d287883243c538e0f9
---

# Phase 4 API Surface Retro Audit

Date: 2026-05-14

Source TODO: `migration-phase-api-surface-gate`

Scope: surfaces introduced by the Phase-4 migration commit
`f9d08d38b` (`Migration: populate develop branch from private working tree
(Phase 4 w4)`) and post-migration follow-ups through `HEAD` on the audit
branch.

Commands used:

```bash
git diff f9d08d38b^ f9d08d38b -- benchbox/cli/
git log --oneline f9d08d38b..HEAD -- benchbox/cli/
git diff f9d08d38b^ f9d08d38b --name-only -- 'benchbox/**/__init__.py'
git grep -nE '@click\.(command|group)|@[^.]+\.command|@[^.]+\.group' -- benchbox/cli/commands benchbox/cli
git grep -nE '@click\.(command|group)|@[^.]+\.command|@[^.]+\.group' f9d08d38b^ -- benchbox/cli/commands benchbox/cli
git grep -nE 'from benchbox\.cli\.(submit_auth|submit_service|platform_readiness)|import benchbox\.cli\.(submit_auth|submit_service|platform_readiness)|from benchbox\.core\.explorer_pipeline|import benchbox\.core\.explorer_pipeline' -- . ':(exclude)_project/DONE/**' ':(exclude)_project/TODO/**'
```

## Executive Summary

Phase 4 did introduce public-ish surface as a side effect of a bulk import.
Most of it is now either deliberate or already retired:

- `benchbox auth ...` is a real user-facing hosted-submission credential
  surface. It was introduced in the migration window, then materially
  hardened by PR #93. Keep it.
- `benchbox explorer ...` is the unresolved accidental surface. It is owned by
  `explorer-cli-surface-adr` and `explorer-cli-surface-migration`; no additional
  TODO is needed here.
- `benchbox.core.explorer_pipeline` is the matching import surface for the same
  Explorer publishing concern. The ADR/migration pair owns it too.
- `benchbox.release` was introduced during migration but deleted by Phase 6
  (`8ffe73bce`, PR #22). No action remains.
- `benchbox.cli.submit_auth`, `benchbox.cli.submit_service`, and
  `benchbox.cli.platform_readiness` are internal implementation modules used by
  CLI commands and tests. They are not exported as package API; keep them as
  internal modules.

No new sibling TODOs were filed by this audit. The only unapproved current
surface already has owner TODOs.

## CLI Surface Inventory

| Command path | Introduced by | Current status | Intended audience | Discrete review? | Classification | Action |
| --- | --- | --- | --- | --- | --- | --- |
| `benchbox auth` | `f9d08d38b` added `benchbox/cli/commands/auth.py` and registration | Current | End users submitting hosted results | Partially. Follow-up PR #93 hardened hosted submit auth and related tests. | Approved public CLI | Keep. |
| `benchbox auth login` | `f9d08d38b` | Current | End users/CI storing hosted-submission tokens | PR #93 follow-up | Approved public CLI | Keep. |
| `benchbox auth status` | `f9d08d38b` | Current | End users/CI checking token availability | PR #93 follow-up | Approved public CLI | Keep. |
| `benchbox auth refresh` | `f9d08d38b` | Current | End users rotating hosted-submission tokens | PR #93 follow-up | Approved public CLI | Keep. |
| `benchbox auth logout` | `f9d08d38b` | Current | End users removing hosted-submission tokens | PR #93 follow-up | Approved public CLI | Keep. |
| `benchbox explorer` | `f9d08d38b` added `benchbox/cli/commands/explorer.py` and registration | Current | Maintainer/CI static-site publishing, not benchmark users | No discrete design PR; ADR PR #415 opened from this batch | Unapproved public CLI | Move out of `benchbox` via `explorer-cli-surface-migration`. |
| `benchbox explorer build` | `f9d08d38b` | Current | Maintainer/CI static read-model publishing | No discrete design PR; ADR PR #415 opened from this batch | Unapproved public CLI | Move to `_project/scripts/explorer_publish.py` per ADR. |
| `benchbox explorer build-contract` | `f9d08d38b` | Current, hidden | JS fixture/build contract reader | No discrete design PR; ADR PR #415 opened from this batch | Internal contract command in wrong CLI namespace | Move with publisher script. |
| `benchbox explorer build-comparison` | `f9d08d38b` | Removed before current `HEAD` | Precomputed comparison artifact generation | Removed during Explorer contract simplification | Retired | No action. |

No other current `@click.command` or `@click.group` entry point was newly
introduced by the Phase-4 migration window. Post-migration CLI commits modified
existing commands (`submit`, `results`, `platforms`, `run`, etc.) but did not
add another current command group comparable to `auth` or `explorer`.

## Python Import Surface Inventory

| Import surface | Introduced by | Current importers | Classification | Action |
| --- | --- | --- | --- | --- |
| `benchbox.core.explorer_pipeline` package and submodules | `f9d08d38b` | `benchbox/cli/commands/explorer.py`, Explorer pipeline tests, `tests/unit/core/test_platform_labels.py` | Public-looking package API for maintainer-only publishing code | Move to `_project/scripts/explorer_pipeline/` via `explorer-cli-surface-migration`. |
| `benchbox.cli.submit_auth` | `f9d08d38b` | `benchbox/cli/commands/auth.py`, `benchbox/cli/commands/submit.py`, `benchbox/cli/submit_service.py`, hosted-submission tests | Internal CLI implementation module for approved hosted submission surface | Keep; no package-level export. |
| `benchbox.cli.submit_service` | `f9d08d38b` | `benchbox/cli/commands/submit.py`, hosted-submission tests | Internal CLI implementation module for approved hosted submission surface | Keep; no package-level export. |
| `benchbox.cli.platform_readiness` | `f9d08d38b` | `benchbox/cli/platform.py`, platform CLI tests | Internal CLI implementation module for the existing `benchbox platforms` group | Keep; no package-level export. |
| `benchbox.release` | `f9d08d38b` | None at current `HEAD`; directory deleted | Obsolete migration/release tooling namespace | Already deleted by Phase 6 PR #22; no action. |

## Follow-up Routing

| Finding | Owner |
| --- | --- |
| Remove/hide `benchbox explorer` and move publisher internals | `explorer-cli-surface-adr` + `explorer-cli-surface-migration` |
| Prevent repeat bulk-import surface smuggling in Phases 8 and 9 | `migration-phase-api-surface-gate` updates Phase 8/9 TODOs and `_project/specs/migration-api-surface-gate.md` |

No additional sibling TODO is needed from this audit.
