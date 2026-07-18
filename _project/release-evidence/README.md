# Release evidence

Committed, machine-readable release-gate evidence. One file per release
cycle: `uat-gate-summary.json`, written by `make uat-gate-check` from the
three release-gate stage sweeps (see `docs/operations/uat-framework.md`
"Release-gate re-run" and `docs/operations/release-guide.md`).

Conventions:

- The **operator** reviews and commits the evidence file deliberately after
  `make uat-gate-check` exits 0 — sweeps and the gate-check never write to
  the git tree themselves.
- `scripts/release_readiness_check.py` reads this file (green verdict,
  clean tree, ancestor-of-release-head, ≤21 days old) as a required release
  gate on release PRs.
- Like the rest of `_project/`, this directory lives on `develop` only and
  is curated out of release branches by `make release-cut`.
- Each release cycle overwrites the file; history is the git log.
