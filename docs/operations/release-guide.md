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
- the integration-not-slow suite:
  `tests/integration -m "integration and not slow and not stress"`;
- isolated exact-one-wheel package build/install smoke;
- dependency upper-bound checks;
- release-branch curation checks that confirm dev-only paths are absent.

It does **not** guarantee live cloud credentials, stress suites, long-running
UAT, or full slow/resource-heavy coverage. Those remain explicit manual,
scheduled, or follow-up gates until separate release canary work makes them
blocking.

### What `release-cut` does

1. Cuts a `vX.Y.Z` branch off `develop` (`develop` itself is never modified).
2. Bumps the 6 version sources via `scripts/update_version.py` and generates
   the CHANGELOG entry via `scripts/generate_changelog_entry.py`.
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
   `release-required-result` is present and green. Missing means the
   ruleset/workflow contract is broken; pending means wait in GitHub
   Actions and rerun the command. `release-finalize` does not poll.
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

- **`release-required-result` is missing**: stop. The
  `main-release-only` ruleset or `.github/workflows/test.yml` contract is
  out of sync; do not finalize until the stable required context exists.
- **`release-required-result` is pending or failed**: wait for GitHub
  Actions or fix on a feature branch off `develop`, PR back to `develop`,
  then re-run `make release-cut` (the option-c sweep will delete the stale
  `vX.Y.Z` branch automatically).
- **Wheel content is wrong**: adjust `pyproject.toml` / `MANIFEST.in`
  excludes on `develop`, then cut a patch release. PyPI rejects
  re-uploads of an existing version, so always bump.
- **`release.yml` fails after tag push**: investigate via `gh run view`,
  fix the underlying issue, bump to the next patch version, and re-cut.
  Do **not** force-push or re-tag; the tag is already public.

## Reference

- Makefile targets: `release-cut`, `release-finalize`.
- Workflow: `.github/workflows/release.yml`.
- Curation drift guard: `scripts/check_release_curation.py` (runs in
  `lint.yml` on every PR).
- Version updater: `scripts/update_version.py`.
- Changelog generator: `scripts/generate_changelog_entry.py`.
- Architecture record: `_project/decisions/single-repo-migration.md`
  (D5 / A3 / A4 / A5, plus the amendments for the 2-command flow, the
  develop-not-modified rule, and the v0.3.0 release-scope curation).
