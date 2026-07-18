---
id: 2026-07-10-141635-slow-live-integration-coverage-theater
date: 2026-07-10
status: open
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

# A `slow` + `live_integration` marked module can run in ZERO CI lanes while looking covered

## Finding
`tests/integration/test_ducklake_integration.py` is ~700 lines across 4 classes,
presenting as the adapter's live coverage. Resolving markers against every lane:
- Module marker: `slow`. Class `TestDuckLakeLiveConnection` (core in-process
  ATTACH: cursor scoping, force-recreate, platform_info) adds `live_integration`;
  `TestDuckLakePostgresCatalogLive` and `TestDuckLakeS3DataPathLive` add
  `live_integration` too. Only `TestDuckLakeSqliteCatalogLive` lacks it.
- Every default lane selects `not (slow or ... or live_integration)` (pr.yml
  fast, test.yml integration, nightly, develop-post-merge `make test-medium`).
  The `-m "slow"` jobs in pr.yml are FILE-SCOPED to other files (mutation,
  tpchavoc), never naming this module. release-canary/validate-main-pr run
  `-m "(slow or resource_heavy) and not (... live_integration)"`.
- Net: classes 1/3/4 (in-process ATTACH, Postgres, S3) run in NO lane at all.
  Class 2 (SQLite CLI e2e) runs ONLY at the main-release gate — never on the
  develop PR that merged it, nor nightly, nor post-merge. The adapter's core
  ATTACH/cursor/force-recreate behavior has zero live CI coverage; only the
  hermetic mock unit test (`tests/unit/platforms/test_ducklake_adapter.py`,
  `fast`) runs on the PR. #1082 and #1096 both merged via squash auto-merge
  with no human review and effectively no live-behavior gate.
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
- [ ] Make `_probe_extension` failures loud (warn/xfail) rather than a cached
      silent skip at the release gate.
