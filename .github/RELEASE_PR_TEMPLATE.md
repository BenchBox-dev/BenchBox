## Release v<!-- bump version here -->

This PR was opened by `make release-prepare VERSION=X.Y.Z` from `develop`.
It cuts the release branch, drops maintainer paths (`_project/`, `_blog/`,
agent configs, dev-tooling root files), and queues the change for a
squash-merge into `main`. After merge, tag `main` to fire `release.yml`.

### Reviewer checklist

- [ ] CHANGELOG.md has an accurate `## [X.Y.Z] - YYYY-MM-DD` entry
- [ ] `pyproject.toml` and `benchbox/__init__.py` show the new version
- [ ] Documentation landing pages and `landing/` show the new version
- [ ] `_project/`, `_blog/`, agent config dirs, and dev-tooling root files
      were removed from this branch (verify with `git diff main...HEAD --stat`
      — the diff should look like a curated subtree, not arbitrary edits)
- [ ] No surprise file additions (the curation only *removes*)
- [ ] CI is green on this branch (Tests + Lint workflows must pass)

### After merge

```bash
git checkout main && git pull
git tag vX.Y.Z && git push origin vX.Y.Z   # triggers .github/workflows/release.yml
make release-rebase-develop VERSION=X.Y.Z   # rebase develop onto release-shaped main
```

The `release.yml` workflow runs `check-ci-passed` → `dependency-bounds` →
`build` (with `SOURCE_DATE_EPOCH` from the tag commit) → `publish` (PyPI
trusted publisher) → `github-release` → `test-installation` (cross-platform
pip install verification).

If anything fails downstream, fix on a new branch, PR to `main`, squash-merge,
and bump to the next patch version (PyPI rejects re-uploads of an existing
version).

See `docs/operations/release-guide.md` for the full flow.
