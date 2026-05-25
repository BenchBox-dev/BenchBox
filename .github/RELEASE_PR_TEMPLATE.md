## Release v<!-- bump version here -->

This PR was opened by `make release-cut VERSION=X.Y.Z` from `develop`.
It cuts the release branch, bumps the version sources, generates the
CHANGELOG entry, drops maintainer paths (`_project/`, `_blog/`, agent
configs, dev-tooling root files), and queues the change for a
squash-merge into `main`.

### Reviewer checklist

- [ ] CHANGELOG.md has an accurate `## [X.Y.Z] - YYYY-MM-DD` entry
- [ ] `pyproject.toml` and `benchbox/__init__.py` show the new version
- [ ] Documentation landing pages and `landing/` show the new version
- [ ] `_project/`, `_blog/`, agent config dirs, and dev-tooling root files
      were removed from this branch (verify with `git diff main...HEAD --stat`
      — the diff should look like a curated subtree, not arbitrary edits)
- [ ] No surprise file additions (the curation only *removes*)
- [ ] `validate-base` is green for this release branch
- [ ] `release-required-result` is green on this branch

### Release-required guarantee

`release-required-result` means this branch passed the fast test lane,
integration-not-slow suite, isolated exact-one-wheel package install smoke,
dependency upper-bound check, and release-branch curation check. It does
not cover live cloud credentials, stress suites, long-running UAT, or full
slow/resource-heavy coverage.

### After release-required checks are green

```bash
make release-finalize VERSION=X.Y.Z
```

`release-finalize` squash-merges this PR, fast-forwards `main`, tags
`vX.Y.Z`, and pushes the tag — which fires `.github/workflows/release.yml`:
`dependency-bounds` → `build` (with `SOURCE_DATE_EPOCH` from the tag
commit) → `publish` (PyPI trusted publisher) → `github-release` →
`test-installation` (cross-platform pip install verification).

`develop` is intentionally NOT modified by `release-finalize`. Dev-only
paths (`_project/`, `_blog/`, agent configs, etc.) live only on develop
by design (per A3 in `_project/decisions/single-repo-migration.md`).

If anything fails downstream, fix on a new branch, PR to `main`, squash-merge,
and bump to the next patch version (PyPI rejects re-uploads of an existing
version).

See `docs/operations/release-guide.md` for the full flow.
