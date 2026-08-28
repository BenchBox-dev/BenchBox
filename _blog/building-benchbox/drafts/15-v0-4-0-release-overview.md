---
title: "BenchBox v0.4.0: new home, DuckLake, provenance"
series: building-benchbox
post_number: 15
type: release-notes
tags: [benchbox, release, ducklake, results-explorer, provenance, mcp]
meta_description: "BenchBox v0.4.0 moves to BenchBox-dev, launches the Results Explorer preview, adds DuckLake beta, and explains breaking migrations and metric corrections."
status: draft
---

# BenchBox v0.4.0: new home, DuckLake, provenance

BenchBox has a new GitHub home at [`BenchBox-dev/BenchBox`](https://github.com/BenchBox-dev/BenchBox). v0.4.0 was tagged on August 27, 2026 and published on August 28.[^release] The release also launches a curated Results Explorer preview, adds provenance and funding labels, and introduces DuckLake as a beta platform.

**TL;DR**: Check two breaking migrations before upgrading. The bare `clickhouse` platform selector and the `databricks-connect` install extra are gone. If you published TPC-H or TPC-DS Throughput@Size values from an earlier release, rerun the benchmark with v0.4.0. Re-exporting the old bundle will not correct its stored metric.

## Before upgrading

Most users can upgrade without changing commands. These are the exceptions:

| Previous use | v0.4.0 action |
| --- | --- |
| `--platform clickhouse` | Choose `clickhouse-local`, `clickhouse-server`, or `clickhouse-cloud` |
| `ch` shorthand | No change required; it now selects `clickhouse-local` |
| `benchbox[databricks-connect]` | Use `benchbox[cloud-spark-databricks]` |
| Earlier TPC-H or TPC-DS Throughput@Size | Rerun with v0.4.0 |

The ClickHouse change removes ambiguity about deployment mode. Passing bare `clickhouse` now raises an error that names the three replacements. The Databricks change only renames the BenchBox extra; it still installs the upstream `databricks-connect` package.

The throughput correction is more important for published data. Earlier TPC-H and TPC-DS result versions understated Throughput@Size by 22x and 99x because the calculation did not include every executed query. Historical bundles remain unchanged as records of what those versions produced. Re-exporting a bundle reuses its stored value, so a corrected figure requires a new run.[^changelog][^metrics]

## A public Results Explorer preview

v0.4.0 launches the [Results Explorer preview](https://benchbox.dev/results/). It provides benchmark leaderboards, per-query timings, result details, comparison tools, and a SQL workbench over the published snapshot.

The word *preview* matters. This is a curated set of results, not a complete or certified ranking. The interface separates results that can be displayed, compared, and ranked, and it explains exclusion reasons when a row does not qualify. The companion post, [How the Results Explorer qualifies comparisons](./16-results-explorer-qualifies-comparisons.md), covers that model and its limitations.

Results can now record who produced a run, its trust label, and disclosed funding. The Explorer shows those fields in rankings, comparisons, and result details. The vocabulary includes maintainer, CI, community, and vendor sources, but the launch snapshot is not yet diverse: all 138 rows are labeled `maintainer-run`, with funding `unspecified`.[^snapshot] Provenance fields make those gaps visible; they do not fill them.

## DuckLake joins as a beta platform

DuckLake stores table data as Parquet while keeping catalog metadata in a SQL database. BenchBox now runs it with `--platform ducklake`.[^ducklake]

The catalog and data location are independent choices. A DuckDB, SQLite, or PostgreSQL catalog can be paired with local or S3-backed Parquet data, giving six possible combinations. Four documented deployment modes passed TPC-H scale-factor-1 correctness validation: local, local catalog with S3 data, PostgreSQL catalog with local data, and PostgreSQL catalog with S3 data. SQLite catalogs are supported, but they were not one of those four validated modes. We are keeping the beta label visible rather than extrapolating those four runs to every combination, scale, and benchmark.

DuckLake requires DuckDB 1.3 or later. Its first run also needs network access to install the DuckLake extension. Install and try the local path with:

```bash
uv add "benchbox[ducklake]"
uv run benchbox run --platform ducklake --benchmark tpch --scale 0.01
```

BenchBox reuses an existing catalog by default. `--force` rebuilds catalog state and local data, but it does not recursively delete an S3 data prefix.

## A new organization, not a new project name

The repository, issue and release tooling, CI, and package metadata now point to the `BenchBox-dev` organization. The repository name, PyPI project, and `benchbox.dev` domain are unchanged. Old GitHub repository URLs redirect, so updating a local remote is useful but not urgent:

```bash
git remote set-url origin https://github.com/BenchBox-dev/BenchBox.git
```

This is an ownership and namespace move. It does not, by itself, announce a foundation, a new governance model, or a new maintainer team.

## Also in v0.4.0

- Local MCP clients can use `benchbox-mcp --transport streamable-http`; existing stdio integrations are unchanged. Authenticated non-local deployments support persistent jobs, but shared production deployment remains deferred and unsupported.[^mcp]
- BenchBox now probes bundled TPC data-generation tools before selecting them. If the host loader rejects a bundled binary, BenchBox compiles a compatible tool from source. On affected Macs, that means a slower first run rather than a repaired bundled binary.
- Secret redaction now covers more DuckLake, MotherDuck, export, and MCP paths. Backend-provided exception text can still repeat values, so credentials should not be placed in values a backend may echo.
- Write and Transaction Primitives now detect staged data from the wrong scale factor and rebuild it automatically.

Thanks to everyone who tested release candidates, reported problems, and helped make the release accounting more accurate. You can [browse the Explorer](https://benchbox.dev/results/), read the [full release notes](https://github.com/BenchBox-dev/BenchBox/releases/tag/v0.4.0), or [open an issue](https://github.com/BenchBox-dev/BenchBox/issues) if a result or migration note needs correction.

[^release]: [BenchBox 0.4.0 release](https://github.com/BenchBox-dev/BenchBox/releases/tag/v0.4.0), published August 28, 2026. The release tag and changelog entry are dated August 27.
[^changelog]: [BenchBox changelog at the post-publication accounting correction](https://github.com/BenchBox-dev/BenchBox/blob/7e76199d9e9a0a83266454d44a66a976876e4fc9/CHANGELOG.md#040---2026-08-27).
[^metrics]: [TPC metric derivation at v0.4.0](https://github.com/BenchBox-dev/BenchBox/blob/v0.4.0/benchbox/core/results/metrics.py).
[^snapshot]: [Deployed Results Explorer DuckDB snapshot](https://benchbox.dev/results/data/results.duckdb), read August 28, 2026.
[^ducklake]: [DuckLake platform documentation for v0.4.0](https://github.com/BenchBox-dev/BenchBox/blob/v0.4.0/docs/platforms/ducklake.md).
[^mcp]: [MCP server reference for v0.4.0](https://github.com/BenchBox-dev/BenchBox/blob/v0.4.0/docs/reference/mcp.md).
