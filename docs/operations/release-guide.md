# Cutting a BenchBox release

BenchBox releases follow a **version-branch flow** on a single repo
(`joeharris76/BenchBox`) with two long-lived branches: `develop` (dev work)
and `main` (release-only). This guide is the maintainer runbook.

## The flow (2 commands)

```bash
git checkout develop && git pull
make release-cut VERSION=X.Y.Z
# review the PR; wait for validate-base and release-required-result
make release-finalize VERSION=X.Y.Z
```

That's the entire flow. The two Make targets do the rest.

## Pre-merge release-required contract

Release PRs target `main` and must be opened from branches accepted by
`.github/workflows/validate-main-pr.yml` (`vX.Y.Z`, optionally with a suffix).
Before a release PR can merge, the `main-release-only` ruleset must require:

- `validate-base`
- `release-required-result`

`release-required-result` is the stable umbrella check in
`.github/workflows/test.yml`. A green result means the release PR branch passed:

- the required fast lane, `test (ubuntu-latest, 3.12)`;
- the bounded real-result correctness gate, `make test-correctness-gate`
  (`DuckDB x TPC-H` at SF=1 with the pinned reference qgen seed, through
  generate/load/execute with EXACT stored answer-set row-count validation of the
  18 answer-stable TPC-H queries; Q11/Q16/Q18/Q20 are excluded for answer-set
  boundary sensitivity, and validation is cardinality-level, not value-level);
- the credential-free integration-not-slow suite:
  `tests/integration -m "integration and not (slow or stress or resource_heavy or live_integration)"`;
- isolated exact-one-wheel package build/install smoke;
- dependency upper-bound checks;
- release-branch curation checks that confirm dev-only paths are absent.

It does **not** guarantee the full stress matrix, live cloud credentials, or
long-running UAT. Slow/resource-heavy coverage is enforced through the
freshness-based release canary below, not by rerunning that suite on every
release PR.

## Release canary and ruleset drift

Release PRs also depend on the `validate-base` workflow's release-readiness
steps. That workflow queries the latest completed `release-canary.yml` run,
reads the canary summary artifact, and fails the release PR when the canary is
missing, red, older than 48 hours, or when the tested `develop` SHA recorded in
the artifact is not an ancestor of the release PR head. The only bootstrap
exception is the first release that introduces `release-canary.yml` before the
workflow exists on the default branch; in that case `validate-base` runs the
same non-fast canary suite and ruleset drift check inline, then later releases
return to the scheduled/manual canary evidence path.

`release-canary.yml` runs daily and on manual dispatch. Scheduled runs execute
from the default branch, but the workflow checks out `develop` before running
release evidence and records that checked SHA in `release-canary-summary.json`.
Its blocking canary suite is the credential-free non-fast family:
`(slow or resource_heavy) and not (stress or live_integration)`. The same
workflow also runs `scripts/ruleset_drift_check.py` against
`docs/operations/repo-admin-settings.md`, so ruleset drift makes the canary red
instead of silently invalidating release assumptions. The ruleset drift check
must use `RULESET_DRIFT_TOKEN`, a repository secret with enough ruleset
visibility to expose bypass actors; the default `GITHUB_TOKEN` is insufficient
for that part of the contract.

Stress tests, live cloud integrations, and long-running UAT remain advisory
until their credential, cost, and flake policies are stable enough to make
them release-blocking.

Emergency override is admin-only: set repository variables
`RELEASE_READINESS_OVERRIDE_SHA` to the exact release PR head SHA and
`RELEASE_READINESS_OVERRIDE_REASON` to the incident/approval record. Remove
both variables after the release. API outages, stale canaries, or ruleset drift
must not be bypassed with an undocumented local change.

### What `release-cut` does

1. Cuts a `vX.Y.Z` branch off `develop` (`develop` itself is never modified).
2. Bumps the 6 version sources via `scripts/update_version.py` and generates
   the CHANGELOG entry via `scripts/generate_changelog_entry.py --since-ref
   origin/main`. The release note boundary is the current release branch patch
   delta against `main`, not `git log origin/main..HEAD` ancestry and not the
   latest tag reachable from `develop`, because `release-finalize`
   intentionally does not replay release commits onto `develop`.
3. Opens `$EDITOR` on `CHANGELOG.md` for hand-curation. (Headless mode:
   refuses to skip the curation step rather than silently committing
   raw output.)
4. Curates the release branch — `git rm`'s the dev-only and deferred
   release paths (`_project/`, `_blog/`, results explorer/data, agent
   configs, dev-tooling root files; full list in the `release-cut:`
   Makefile target and gated by `scripts/check_release_curation.py`).
   For v0.3.0, `landing/` and `docs/blog/` stay in the release tree so
   `/prompts/` and promoted release posts ship; `results-explorer/`,
   `results-data/`, and explorer/results-data workflows do not.
5. Commits a single `Release vX.Y.Z` commit on `vX.Y.Z`, pushes, and
   opens a PR against `main`.
6. Sweeps prior `v*` branches on origin (option-c lifecycle: keep until
   superseded, then auto-delete on the next `release-cut`).

### What `release-finalize` does

1. Finds the open release PR for `vX.Y.Z`.
2. Checks the required PR status list once and refuses to continue unless
   both `validate-base` and `release-required-result` are present and green.
   Missing means the ruleset/workflow contract is broken; pending means wait
   in GitHub Actions and rerun the command. `release-finalize` does not poll.
3. Squash-merges the PR. (Ruleset `main-release-only` also blocks the merge
   unless `validate-base` and `release-required-result` are green.)
4. Fast-forwards `main` and tags `vX.Y.Z`.
5. Pushes the tag — which fires `.github/workflows/release.yml`:
   `dependency-bounds` → `build` (with `SOURCE_DATE_EPOCH` from the tag
   commit) → `publish` (PyPI trusted publisher) → `github-release` →
   `test-installation` (cross-platform pip install verification).
6. Leaves `develop` untouched. Dev-only paths persist on develop by
   design (per A3 in `_project/decisions/single-repo-migration.md`); the
   release squash on `main` does not need to be replayed onto develop.

Push-to-main jobs are post-merge signals. They may still start when `main`
advances, but they are not pre-publish evidence: the tag push follows the
successful release PR merge and `.github/workflows/release.yml` begins from
that public tag. If a post-merge `main` check fails after the tag is pushed,
handle it as a patch release or incident; do not treat the already-published
release as if it had been blocked.

## Recovering from common failures

- **`validate-base` or `release-required-result` is missing**: stop. The
  `main-release-only` ruleset or release workflow contract is out of sync;
  do not finalize until both stable required contexts exist.
- **`validate-base` or `release-required-result` is pending or failed**: wait
  for GitHub Actions or fix on a feature branch off `develop`, PR back to
  `develop`, then re-run `make release-cut` (the option-c sweep will delete
  the stale `vX.Y.Z` branch automatically).
- **Release canary is missing, stale, or red**: inspect the latest
  `release-canary.yml` run. If the non-fast canary failed, fix through
  `develop`; if ruleset drift failed, update the live GitHub ruleset or this
  runbook so they match. Use the emergency override variables only with an
  explicit incident/approval record.
- **Wheel content is wrong**: adjust `pyproject.toml` / `MANIFEST.in`
  excludes on `develop`, then cut a patch release. PyPI rejects
  re-uploads of an existing version, so always bump.
- **`release.yml` fails after tag push**: investigate via `gh run view`,
  fix the underlying issue, bump to the next patch version, and re-cut.
  Do **not** force-push or re-tag; the tag is already public.

## Reference

- Makefile targets: `release-cut`, `release-finalize`.
- Workflow: `.github/workflows/release.yml`.
- Canary workflow: `.github/workflows/release-canary.yml`.
- Release-readiness gate: `scripts/release_readiness_check.py`.
- Ruleset drift gate: `scripts/ruleset_drift_check.py`.
- Curation drift guard: `scripts/check_release_curation.py` (runs in
  `lint.yml` on every PR).
- Version updater: `scripts/update_version.py`.
- Changelog generator: `scripts/generate_changelog_entry.py`.
- Architecture record: `_project/decisions/single-repo-migration.md`
  (D5 / A3 / A4 / A5, plus the amendments for the 2-command flow, the
  develop-not-modified rule, and the v0.3.0 release-scope curation).
