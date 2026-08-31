---
title: "BenchBox v0.4.0: new org, DuckLake, and result provenance"
series: building-benchbox
post_number: 15
type: release-notes
tags: [benchbox, release, github-org, ducklake, results-explorer, provenance, mcp]
status: DRAFTED
---

# Outline: BenchBox v0.4.0 release overview

## Purpose

Release announcement in the post-13 overview shape: what shipped, why it
matters, how to try it, then what breaks. Not a GitHub-release-notes page
and not a tour of the Results Explorer. The Explorer deep dive is post 16.

## Audience

- Existing BenchBox users deciding whether to upgrade from v0.3.1.
- Data engineers evaluating lakehouse formats who want a reproducible DuckLake path.
- Readers arriving from the Results Explorer who want to know what the tool behind it does.

## Thesis

v0.4.0 moves BenchBox out of a personal GitHub account into its own
organization, gives published results a vocabulary for who ran them and who
paid, and adds DuckLake as a beta platform.

## Governing constraints

Satisfy these by omission or by stating the affirmative scope once. Do not
render them as "This is Y. This is not X."

- Do **not** say the Results Explorer launches, goes live, or is new. Phase 1
  launched 2026-04-04; the README has linked `benchbox.dev/results/` since
  v0.2.1. v0.4.0 is the first tagged release whose changelog names the
  preview, and provenance and funding labels now appear in it. Nothing stronger.
- Do **not** write that bundled TPC-H generators "now support macOS 15" or
  "were rebuilt to support macOS 15". Shipped darwin-arm64 `dbgen`/`qgen`
  still carry `LC_BUILD_VERSION minos 26.0`. Write the exec-probe fallback:
  slower first run, not a binary fix.
- Do **not** put the two BREAKING shims in the title, opening, or thesis.
  They get one at-a-glance row and a late "Changed behavior" table.
- Do **not** state the community ranking exclusion without the vendor
  inclusion and the anti-self-application safeguard.
- Do **not** tell readers to re-export to fix Throughput@Size. The remedy is
  a rerun on v0.4.0.
- Do **not** imply a foundation, new governance, or a new maintainer team.
- Do **not** use Title Case after the colon. Follow post 13: sentence case.
- Companion filename in this worktree:
  `./16-results-explorer-qualifies-comparisons.md`. Do not retarget the
  older handoff name `16-results-explorer-sharing-reliable-results.md`.
- Smoke commands use `--scale 0.01`. TPC-H SF1 is the DuckLake *validation*
  scale, not the try-it scale.
- Prefer `uv run -- benchbox` for flag-heavy commands.

## Evidence boundary

- Shipped code and package: tag `refs/tags/v0.4.0` and PyPI 0.4.0.
- Release date in the post: **August 27, 2026** (changelog/tag). GitHub
  published the release page on August 28; do not turn that into a timezone
  essay.
- Complete accounting: `develop` changelog, labeled as a post-publication
  accounting correction. The tag and package were not changed.
- Explorer figures: deployed snapshot checked August 28, 2026, SHA-256
  `83cf3c7ffe56ad6f89c53944e66d9c18aa794d3985c89ae87588fb57a2398863`
  (138 rows, all `maintainer-run`, funding `unspecified`).
- Hero image: live `https://benchbox.dev/results/` capture after the DuckDB
  snapshot initialized, saved as `../images/results_explorer_preview.png`.
  Alt text must describe what the image actually shows.

## Structure and word budget

Target: 1,200-1,500 words. Analog is post 13, not the union of posts 8 and 9.
No "Release highlights" list that duplicates At a glance. No mandatory
"Bottom line" or "Quick upgrade checks" headings; use "Try it yourself"
and "Changed behavior to be aware of".

1. Opening and TL;DR (~200 words): org, provenance, DuckLake. Connective
   sentence once. Hero screenshot. Companion link.
2. At a glance: 8-row Area / What changed / Why it matters table.
3. A new home: BenchBox-dev (~200 words).
4. Provenance labels, and where to see them (~250 words). Full ranking
   policy. `--funding` values. Hand off to post 16.
5. DuckLake beta (~250 words). 6 combinations, 4 validated at TPC-H SF1,
   SQLite not one of them. Local smoke at 0.01, then catalog/data_path flags.
6. Corrections worth knowing (~200 words): throughput rerun; dead
   `BENCHBOX_TUNING_ENABLED`; `--tuning auto` constraints-only on SQL.
7. Other notable changes (~120 words).
8. Changed behavior to be aware of: migration table including
   `get_adapter("clickhouse")` and `clickhouse:local`.
9. Try it yourself: version, DuckDB smoke with `--funding personal`,
   clickhouse-local dry-run, DuckLake 0.01, Explorer URL.
10. References section, not SHA footnotes.

## Editorial risks

| Risk | Mitigation |
| --- | --- |
| Calling the Explorer new or launched | April 2026 + v0.2.1 README link; this release names the preview and adds labels |
| Half ranking policy | Ranked: maintainer-run, CI, vendor-supplied. Not ranked: community. Vendor label cannot be self-applied |
| Changelog macOS 15 sentence | Exec-probe fallback; `minos 26.0` still on shipped binaries |
| Re-export as throughput fix | Rerun on v0.4.0 |
| Org move as governance | Ownership and namespace only |
| Explorer swallows the post | Labels, policy, 138/138 caveat, one screenshot, link to 16 |
| SF1 as default try-it | Smoke at 0.01 |
| Synthetic contributor thanks | Maintainer-driven cycle unless a named handle is verified |
| In-tree outline reintroducing launch language | This outline is the source of truth for the next edit pass |
