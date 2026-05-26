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
- [ ] Release canary freshness is green (latest `release-canary.yml` run is
      successful, within 48h, and its checked `develop` SHA is an ancestor of
      this release head)
- [ ] Ruleset drift is green in the latest release canary

### Release-required guarantee

`release-required-result` means this branch passed the fast test lane,
credential-free integration-not-slow suite, isolated exact-one-wheel package
install smoke, dependency upper-bound check, and release-branch curation check.
It does not cover live cloud credentials, stress suites, or long-running UAT.
Slow/resource-heavy coverage is enforced by the 48h release canary freshness
gate in `validate-base`, not by rerunning that suite on every release PR.

`release-canary.yml` runs the credential-free non-fast canary
`(slow or resource_heavy) and not (stress or live_integration)` and the
ruleset drift check against `docs/operations/repo-admin-settings.md`.
Scheduled runs execute from the default branch, then check out `develop` and
record the checked SHA in `release-canary-summary.json` for release-readiness.
The first release that introduces the workflow may run the same evidence inline
from `validate-base` until GitHub can run the canary from the default branch.
Emergency override requires repository variables
`RELEASE_READINESS_OVERRIDE_SHA` (exact release head SHA) and
`RELEASE_READINESS_OVERRIDE_REASON` (incident/approval record).

### After release-required checks are green

```bash
make release-finalize VERSION=X.Y.Z
```

`release-finalize` re-checks that the required `validate-base` and
`release-required-result` contexts are present and green before merge. If either
context is missing, pending, skipped, failed, or canceled, stop and fix the
release PR or ruleset/workflow contract before rerunning the command.

After that pre-merge check passes, `release-finalize` squash-merges this PR,
fast-forwards `main`, tags `vX.Y.Z`, and pushes the tag — which fires
`.github/workflows/release.yml`: `dependency-bounds` → `build` (with
`SOURCE_DATE_EPOCH` from the tag commit) → `publish` (PyPI trusted
publisher) → `github-release` → `test-installation` (cross-platform pip
install verification).

Push-to-main jobs are post-merge signals. They can fail after the tag has
already started publication; recovery is a patch release or incident process,
not treating the public tag as if it had been blocked.

`develop` is intentionally NOT modified by `release-finalize`. Dev-only
paths (`_project/`, `_blog/`, agent configs, etc.) live only on develop
by design (per A3 in `_project/decisions/single-repo-migration.md`).

If anything fails downstream, fix on a new branch, PR to `main`, squash-merge,
and bump to the next patch version (PyPI rejects re-uploads of an existing
version).

See `docs/operations/release-guide.md` for the full flow.
