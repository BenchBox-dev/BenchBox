---
title: "BenchBox v0.4.0: new home, DuckLake, provenance"
series: building-benchbox
post_number: 15
type: release-notes
tags: [benchbox, release, ducklake, results-explorer, provenance, mcp]
status: DRAFTED
---

# Outline: BenchBox v0.4.0 release overview

## Purpose

Help existing users upgrade safely, then explain the three reader-facing additions: the move to
the `BenchBox-dev` GitHub organization, the Results Explorer preview, and DuckLake beta support.

## Audience

- Existing BenchBox users upgrading from v0.3.1.
- Users of the retired bare `clickhouse` selector or `databricks-connect` extra.
- Data engineers interested in DuckLake or published benchmark evidence.

## Thesis

BenchBox v0.4.0 gives the project a new GitHub home, launches a curated Results Explorer preview,
adds provenance labels, and introduces DuckLake as a beta platform. The release also contains two
small but breaking migrations and one metric correction that requires a rerun rather than a
re-export.

## Evidence boundary

- Shipped code and package behavior: fully qualified tag `refs/tags/v0.4.0` and PyPI 0.4.0.
- Publication: GitHub release published August 28, 2026; the tag commit was created August 27 in
  US Eastern time.
- Complete release accounting: current `develop` changelog, explicitly labeled as a
  post-publication accounting correction. The tag and package were not changed.
- Explorer figures: deployed `results.duckdb` snapshot checked August 28, 2026, captured as SHA-256
  `83cf3c7ffe56ad6f89c53944e66d9c18aa794d3985c89ae87588fb57a2398863`.
- Avoid claims about governance, certification, production-hosted MCP, or broad contribution
  availability.

## Structure and word budget

Target: 900-1,000 words.

### 1. Opening and TL;DR, 100 words

- Open with the new GitHub organization.
- Say the release was tagged August 27 and published August 28.
- Name the Explorer preview, provenance labels, and DuckLake beta.

### 2. Before upgrading, 180 words

Put the action items before feature detail.

| Previous use | v0.4.0 action |
| --- | --- |
| `--platform clickhouse` | Choose `clickhouse-local`, `clickhouse-server`, or `clickhouse-cloud` |
| `ch` | No change required; it now selects `clickhouse-local` |
| `benchbox[databricks-connect]` | Use `benchbox[cloud-spark-databricks]` |
| Historical TPC-H or TPC-DS Throughput@Size | Rerun with v0.4.0; re-exporting preserves the old stored metric |

### 3. Results Explorer and provenance, 180 words

- Present the Explorer as a v0.4.0 curated-preview launch.
- Link to the Explorer root because direct client routes depend on static-host routing.
- State that it is not a complete or certified ranking.
- Explain the three producer sources (`internal`, `community`, and `vendor`), their trust-label
  mappings, the reserved `verified` label, and the community ranking restriction.
- Current snapshot caveat: all 138 rows are `maintainer-run` with funding `unspecified`.
- Link to Post 16 for the eligibility and comparability model.

### 4. DuckLake beta, 220 words

- Define DuckLake: Parquet table data plus catalog metadata in a SQL database.
- Three catalog backends and two data locations form six possible combinations.
- Four documented modes passed TPC-H SF1 correctness validation. SQLite is supported but was not
  one of those four validated modes.
- Require DuckDB 1.3 or later; first extension install needs network access.
- Mention catalog reuse and `--force`, without implying cloud object deletion.

### 5. New project home, 100 words

- Repository, issue tooling, CI, and package metadata use `BenchBox-dev/BenchBox`.
- Old repository URLs redirect; the PyPI name and domain are unchanged.
- Describe this as an ownership and namespace move, not a governance change.

### 6. Other changes, 140 words

- Local streamable HTTP for MCP; stdio unchanged; shared production deployment unsupported.
- Bundled TPC-H and TPC-DS tools are probed and compiled from source if incompatible. The bundled
  TPC-H generators were also rebuilt to support macOS 15.
- Expanded secret redaction, with the residual backend-error caveat.

### 7. Try it and thanks, 80 words

- Install and run DuckLake beta.
- Link to release notes and the Explorer.
- Invite browsing, corrections, and issue reports. Keep the results CTA browse-only.

## Editorial risks

- Do not call the Explorer certified, reliable, complete, or a universal leaderboard.
- Do not use `origin/release..HEAD` as release authority.
- Do not say re-exporting fixes historical Throughput@Size values.
- Do not imply all six DuckLake combinations were validated.
- Do not claim all links moved or that project governance changed.
- Keep the results CTA browse-first. The public contribution page and Explorer invite submissions,
  while the corpus README says contributions are closed and the public guide still names the old
  repository. Describe that inconsistency instead of claiming the public instructions are closed.
