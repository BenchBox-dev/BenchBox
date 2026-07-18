---
id: 2026-07-10-141635-slow-live-integration-coverage-theater
date: 2026-07-10
status: actionable
finding_kind: missed-axis
review_context: "ducklake deep review / CI-lane coverage audit (origin/develop 7b6d1eef4)"
related_paths:
  - tests/integration/test_ducklake_integration.py
  - .github/workflows/pr.yml
  - .github/workflows/develop-post-merge.yml
  - .github/workflows/release-canary.yml
suggested_sweep: "for each large integration test module, resolve its module+class markers against every CI lane's -m expression and confirm at least one lane selects it"
todo_id: null
---

# DuckLake live integration classes can run in ZERO CI lanes while looking covered

## Finding
`tests/integration/test_ducklake_integration.py` is a large four-class module,
presenting as the adapter's live coverage. Resolving its current markers against
the configured lanes:
- The module is marked `integration` and `slow`. `TestDuckLakeLiveConnection`
  (core in-process ATTACH: cursor scoping, force-recreate, platform_info),
  `TestDuckLakePostgresCatalogLive`, and `TestDuckLakeS3DataPathLive` add
  `live_integration`; only `TestDuckLakeSqliteCatalogLive` lacks it.
- The develop PR fast/medium lanes, credential-free integration lane, nightly
  integration lane, and develop-post-merge `make test-medium` all exclude
  `slow` and/or `live_integration`. The named `-m "slow"` PR steps are
  file-scoped to other modules and never select this file.
- Net: 8 of the module's 9 tests (the in-process ATTACH, Postgres, and S3
  classes) still run in no configured CI lane. The SQLite CLI test is selected
  only by the release non-fast canary because it lacks `live_integration`; it
  is not covered by the develop PR, nightly, or post-merge lanes. The
  adapter's core live ATTACH behavior therefore still has zero live CI
  coverage; the PR only runs the hermetic mock unit test.
- Amplifier: `_probe_extension(...)` is cached for the test process. A transient
  extension-repository failure can cache `False` for later tests in that process.
  The probe is deliberately lazy and runs from `setup_method`, so deselected
  tests do not pay the install/load cost; however, the release gate can still
  silently skip the SQLite class if its first live probe fails.

## Why this matters
Marker taxonomies make "a test exists" and "a test runs in CI" two different
facts, and the gap is invisible unless you resolve module+class markers against
each lane's `-m` expression. A reviewer who sees a large live test file assumes
coverage; the fast-lane exclusion policy silently makes it theater. The failure
mode is asymmetric: it looks MORE covered than an obviously-missing test, so it
evades the "where are the tests?" prompt.

## Suggested next steps
- [ ] Add a CI meta-check (or lint-markers extension) that fails if any
      integration test module is selected by zero configured lanes.
- [ ] Give the extension-only in-process ATTACH class a marker that a real lane
      runs (it needs no external service), so core adapter behavior is gated.
- [ ] Make `_probe_extension` failures visible as an explicit skip/health
      result rather than a cached silent skip in a gate that is meant to prove
      live coverage.

## Triage log

- 2026-07-18: actionable — Rechecked against origin/develop 8a7ee88e0 on 2026-07-18: current marker collection selects 8 of 9 DuckLake tests in no configured CI lane; only the non-live SQLite test reaches the release non-fast canary; revised the record to match current lane behavior.
