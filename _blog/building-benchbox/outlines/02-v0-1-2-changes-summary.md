# BenchBox v0.1.2: Changes Summary

> Companion post to draft 01. This outline focuses on a simple, readable summary of what changed in v0.1.2.

**TL;DR**: v0.1.2 adds major capabilities across visualization, DataFrame coverage, platform support, and reliability. The post should summarize changes clearly, not narrate them.

---

## Metadata

```yaml
title: "BenchBox v0.1.2: changes summary"
series: building-benchbox
post_number: 2
type: release-notes
target_length: 900-1,300 words
tags: [benchbox, release, architecture, dataframe, sql, visualization, changelog]
meta_description: "Easy-to-read summary of BenchBox v0.1.2 changes across visualization, DataFrame support, platforms, and reliability."
```

---

## Thesis

> v0.1.2 introduced substantial changes to default output, execution coverage, platform support, and stability, and users need a concise upgrade-oriented summary.

---

## Outline

### 1. Release snapshot (~150 words)

- Open with release date and one-paragraph scope summary.
- Provide a short "what changed" list by area.
- Set expectation: practical summary and upgrade implications.

### 2. Visualization changes (~200 words)

- Plotly removed; ASCII chart rendering is now the default.
- Explain workflow impact for CLI, CI logs, and MCP tool responses.
- Call out trade-off explicitly (no default HTML/PNG/SVG path).

### 3. SQL and DataFrame coverage changes (~220 words)

- Explain DataFrame coverage expansion with explicit examples: TPC-H, TPC-DS, SSB, ClickBench, NYC Taxi, and TSBS DevOps.
- List DataFrame engines covered in the release summary: Polars, DuckDB DataFrame paths, DataFusion, PySpark, Pandas, Modin, Dask, and cuDF.
- Note practical implication: same benchmark can be run in SQL mode and DataFrame mode for comparison.
- Note validation implication: result-consistency checks become more important as coverage broadens.

### 4. Platform and benchmark additions (~220 words)

- Summarize notable SQL adapter additions with explicit examples: PostgreSQL, Trino, PrestoDB, Spark, Athena, Azure Synapse, Microsoft Fabric, Firebolt, and MotherDuck.
- Summarize open table format support additions: Delta Lake, Apache Iceberg, Apache Hudi, DuckLake, and Vortex.
- Mention benchmark-surface expansion including TPC-DI and broader suite coverage.
- Keep this section as concise bullets tied directly to upgrade impact.

### 5. Analysis and tuning tooling updates (~160 words)

- List additions in direct terms:
  - Physical tuning DDL generation improvements
  - Query plan capture and comparison updates
  - Cross-platform comparison workflow updates
- Add one short “why it matters” bullet: easier regression triage and repeatable optimization loops.

### 6. Reliability and release maturity behind the scenes (~250 words)

- Highlight critical fixes from v0.1.2 as enabling work:
  - TPC-DS generation stability
  - cloud adapter robustness
  - type safety campaign
  - non-interactive CLI behavior
- Explain release maturity signals:
  - clearer changelog structure
  - version consistency checks in CLI/docs
  - reproducible release automation story
- Make the point that "big feature releases" require operational discipline.

### 7. Trade-offs and known limitations (~120 words)

- Explicitly list trade-offs and limits:
  - HTML chart export removed in favor of ASCII-first defaults
  - complexity of supporting many platforms and benchmarks
  - ongoing need for tight validation and clear docs
- Keep language factual and concise.

### 8. Upgrade checklist and next steps (~120 words)

- Include 3-4 concrete checks:
  - Confirm version output.
  - Run one SQL smoke benchmark.
  - Run one DataFrame benchmark.
  - Confirm inline chart behavior in terminal/CI.
- End with a short pointer to changelog and docs links.

---

## Research Needs

- [ ] Pull concrete "before/after" CLI flow examples from v0.1.1 vs v0.1.2.
- [ ] Extract 2-3 representative PR/commit references that anchor key change claims.
- [ ] Verify all benchmark/platform count claims against current registries to avoid stale numbers.
- [ ] Gather one user-facing scenario combining run + plan comparison + charting in one concise walkthrough.
- [ ] Capture exact commands used in examples for reproducibility.

---

## Pairing Notes (with Post 01)

- Post 01 is the deep dive on one architectural decision (Plotly -> ASCII).
- Post 02 is a concise v0.1.2 release summary and can reference Post 01 for implementation detail.
- Cross-link strategy:
  - Post 02 links to Post 01 for ASCII charting implementation details.
  - Post 01 can link to Post 02 for release-level summary context.
