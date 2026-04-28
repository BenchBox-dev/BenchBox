# Cutting a BenchBox release

BenchBox releases follow a **version-branch flow** on a single repo
(`joeharris76/BenchBox`) with two long-lived branches: `develop` (dev work)
and `main` (release-only). This guide is the maintainer runbook.

## The flow (2 commands)

```bash
git checkout develop && git pull
make release-cut VERSION=X.Y.Z
# review the PR; wait for CI green
make release-finalize VERSION=X.Y.Z
```

That's the entire flow. The two Make targets do the rest.

### What `release-cut` does

1. Cuts a `vX.Y.Z` branch off `develop` (`develop` itself is never modified).
2. Bumps the 6 version sources via `scripts/update_version.py` and generates
   the CHANGELOG entry via `scripts/generate_changelog_entry.py`.
3. Opens `$EDITOR` on `CHANGELOG.md` for hand-curation. (Headless mode:
   refuses to skip the curation step rather than silently committing
   raw output.)
4. Curates the release branch — `git rm`'s the dev-only paths
   (`_project/`, `_blog/`, agent configs, dev-tooling root files; full
   list in the `release-cut:` Makefile target and gated by
   `scripts/check_release_curation.py`).
5. Commits a single `Release vX.Y.Z` commit on `vX.Y.Z`, pushes, and
   opens a PR against `main`.
6. Sweeps prior `v*` branches on origin (option-c lifecycle: keep until
   superseded, then auto-delete on the next `release-cut`).

### What `release-finalize` does

1. Finds the open release PR for `vX.Y.Z` and squash-merges it. (Ruleset
   `main-release-only` blocks the merge if `lint` or `test` aren't green;
   no local poller is needed.)
2. Fast-forwards `main` and tags `vX.Y.Z`.
3. Pushes the tag — which fires `.github/workflows/release.yml`:
   `dependency-bounds` → `build` (with `SOURCE_DATE_EPOCH` from the tag
   commit) → `publish` (PyPI trusted publisher) → `github-release` →
   `test-installation` (cross-platform pip install verification).
4. Leaves `develop` untouched. Dev-only paths persist on develop by
   design (per A3 in `_project/decisions/single-repo-migration.md`); the
   release squash on `main` does not need to be replayed onto develop.

## Recovering from common failures

- **CI fails on the release PR**: fix on a feature branch off `develop`,
  PR back to `develop`, then re-run `make release-cut` (the option-c
  sweep will delete the stale `vX.Y.Z` branch automatically).
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
  (D5 / A3 / A4 / A5, plus the 2026-04-27 amendment for the 2-command
  flow and the develop-not-modified rule).
