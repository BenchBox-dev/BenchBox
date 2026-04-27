# Cutting a BenchBox release

BenchBox releases follow a **version-branch flow** on a single repo
(`joeharris76/BenchBox`) with two long-lived branches: `develop` (dev work)
and `main` (release-only). This guide is the maintainer runbook.

## The flow

Every release follows seven steps. The Makefile encapsulates the
mechanical parts.

1. **Bump the version on `develop`**:
   ```bash
   git checkout develop && git pull
   make bump VERSION=X.Y.Z
   make changelog-draft VERSION=X.Y.Z   # optional helper
   ```
   Review the auto-drafted CHANGELOG entry, edit any awkward bullets,
   then commit on `develop` (or open a "release prep" PR).

2. **Cut the release branch**:
   ```bash
   make release-prepare VERSION=X.Y.Z
   ```
   This creates `vX.Y.Z` from `develop`, drops develop-only paths
   (`_project/`, `_blog/`, agent configs, dev tooling), commits a
   `Release vX.Y.Z` commit, pushes, and opens a PR against `main`.

3. **Review the PR**. Confirm `CHANGELOG.md` is correct and the curation
   diff looks like the expected release-shaped subset. CI must pass.

4. **Squash-merge** the PR on GitHub. `main` now has one new
   release-shaped commit.

5. **Tag and push**:
   ```bash
   git checkout main && git pull
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```
   The tag push triggers `.github/workflows/release.yml`, which builds
   the wheel and sdist with `SOURCE_DATE_EPOCH` from the tag commit,
   verifies content, and publishes to PyPI via the trusted publisher.

6. **Rebase `develop` onto `main`**:
   ```bash
   make release-rebase-develop VERSION=X.Y.Z
   ```
   This drops the commits that became the release squash, replaying
   only post-release dev work onto the new release-shaped `main`.

7. **(Next release)** delete the previous version branch when the next
   `make release-prepare` runs (option-c lifecycle: branches stay alive
   until superseded so a same-version hotfix can re-cut from them).

## Recovering from common failures

- **Required CI fails on the release PR**: fix on a feature branch off
  `develop`, PR back to `develop`, then re-run `make release-prepare`
  (delete the stale `vX.Y.Z` branch first if needed).
- **Wheel content is wrong**: adjust `pyproject.toml` / `MANIFEST.in`
  excludes on `develop`, then cut a patch release. PyPI rejects
  re-uploads of an existing version, so always bump.
- **`release.yml` fails after tag push**: investigate via `gh run view`,
  fix the underlying issue, bump to the next patch version, and re-cut.
  Do **not** force-push or re-tag; the tag is already public.

## Reference

- Makefile targets: `bump`, `changelog-draft`, `release-prepare`,
  `release-rebase-develop`.
- Workflow: `.github/workflows/release.yml`.
- Changelog generator: `scripts/generate_changelog_entry.py`.
- Architecture record: `_project/decisions/single-repo-migration.md`
  (D5 / A4 / A5).
