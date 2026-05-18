---
title: "BenchBox v0.3.0: fixing JoinOrder and expanding sketch coverage"
series: building-benchbox
post_number: 13
type: release-notes
tags: [benchbox, release, joinorder, mcp, prompts, sketch-functions, read-primitives, write-primitives]
status: OUTLINE
---

# Outline: BenchBox v0.3.0 release overview

---

## Recommendation

Make this the release announcement, not a tour of every changed component. v0.3.0 has two primary
changes and one smaller website addition:

1. **A user-raised JoinOrder benchmark bug got fixed**: `joinorder` now means the real IMDb 2013
   Join Order Benchmark dataset at SF=1, with all 113 JOB SQL queries, reference cardinalities,
   provenance notes, and result-bundle dataset identity fields.
2. **Approximate and sketch benchmarking coverage expands**: `read_primitives` and
   `write_primitives` cover more approximate aggregate and sketch workflows, including
   platform-specific validation and locally reproducible sketch measurements.
3. **The landing site now includes an agent prompt composer**: `/prompts/` helps visitors turn
   benchmark choices into copyable coding-agent instructions. It belongs in the announcement, not
   as a standalone post.

Release machinery belongs in maintainer notes or the release guide, not in this reader-facing
release post. Do not include it in the headline, title, TL;DR, "At a glance" table, or body.

Do not discuss Results Explorer in the release announcement.

---

## Audience

- Existing BenchBox users deciding whether to upgrade from v0.2.1.
- Database engineers who care about benchmark comparability and data provenance.
- Users evaluating approximate aggregate and sketch-function behavior across engines.
- Data engineers who want a safe copy-paste path for asking a coding agent to run BenchBox.

---

## Thesis

v0.3.0 fixes a benchmark comparability problem and deepens approximate/sketch workload coverage.
It also adds a prompt-composer page that makes agent-assisted benchmarking easier to start from the
landing site.

---

## Evidence Matrix

| Claim | Evidence to cite | Reader impact |
| --- | --- | --- |
| A user-raised `joinorder` correctness/comparability issue is fixed by moving to IMDb 2013 JOB data at SF=1 only | `CHANGELOG.md`, `README.md:916`, `docs/reference/api-reference.md:239`; confirm user report link before draft | Upgrade is breaking for old synthetic assumptions, but comparability improves |
| All 113 JOB SQL queries are covered | `CHANGELOG.md`, `benchbox/core/joinorder/queries.py:3`, `tests/unit/core/joinorder/test_query_coverage.py:17` | Users can run the full optimizer workload rather than a small subset |
| Dataset identity is now attached to manifest-backed results | `CHANGELOG.md`, `benchbox/core/joinorder/data_manifest.toml:1` | Published results can carry dataset version and hash context |
| Approximate/sketch benchmark coverage is broader | `CHANGELOG.md`, `docs/benchmarks/read-primitives-approximate-functions.md`, `docs/benchmarks/write-primitives-sketch-functions.md` | Users get more coverage for approximate aggregates, sketch storage size, and engine-specific validation |
| `/prompts/` is a static landing route, not a new runtime API | `_project/decisions/landing-prompts-route.md:41`, `_project/decisions/landing-prompts-route.md:46`, `landing/prompts/index.html:84` | Visitors can move from interest to a correct benchmark instruction faster |
| Prompt platform inclusion is registry-derived, not hand-curated | `_project/decisions/landing-prompts-route.md:12`, `landing/prompts/catalog.yaml:7`, `tests/unit/landing/test_landing_quickstarts.py:80` | Promptable platforms track runtime support instead of website curation |
| Managed-cloud prompts start safely | `_project/decisions/landing-prompts-route.md:90`, `_project/decisions/landing-prompts-route.md:99`, `_project/decisions/landing-prompts-route.md:107` | Agents should check setup and dry-run before live billable work |

---

## Proposed Structure

### 1. Opening: this release fixes real benchmark friction (~250 words)

Start with the user-facing reason this release matters. v0.2.1 expanded the catalog. v0.3.0 fixes
an important benchmark-comparability problem, extends approximate/sketch coverage, and adds a
prompt-composer page for agent-assisted starts.

Draft direction:

- "BenchBox v0.3.0 is about making benchmark claims more honest and easier to reproduce."
- Lead with the user-raised JoinOrder fix.
- Put approximate/sketch coverage second.
- Mention `/prompts/` as a useful starting point, not as a pillar equal to JoinOrder.
- Avoid claiming "stable" or "production-ready" unless release verification explicitly supports it.

### 2. At a glance (~250 words)

Use a compact table.

| Area | What changed | Why it matters |
| --- | --- | --- |
| JoinOrder fix | `joinorder` now uses the real IMDb 2013 JOB data at SF=1 | Fixes a user-raised comparability problem |
| JoinOrder query coverage | 113 JOB SQL query IDs plus cardinality and predicate checks | Runs the optimizer workload readers expect |
| Dataset identity | Manifest-backed results include dataset version and hashes | Published bundles can be audited later |
| Approximate reads | `read_primitives` adds approximate aggregate coverage | Users can test approximate behavior without hand-written one-offs |
| Sketch writes | `write_primitives` adds sketch persist, merge, requery, storage-size, and sweep coverage | Users can measure more of the sketch lifecycle |
| Agent prompts | `/prompts/` emits copyable CLI/MCP agent instructions | Visitors get a safer starting point for agent-assisted benchmarking |

### 3. JoinOrder: a user-raised benchmark fix (~350 words)

This is the teaser for the dedicated JoinOrder post (#14). End with a link to it. Cover the
user-visible change and the breaking-change framing here; leave methodology, provenance depth,
no-small-scale tradeoff, and dataset lineage to #14.

- This was raised by a user as a benchmark correctness/comparability issue; confirm the public
  issue or discussion link before drafting.
- `joinorder` now means the real IMDb 2013 Join Order Benchmark dataset at `--scale 1`.
- The old synthetic generator becomes `joinorder_synthetic` and is not part of the released
  benchmark list.
- Be direct about the tradeoff: no small public `joinorder` scale in this step. That is a deliberate
  comparability choice, not an oversight.
- Avoid internal phrasing such as "public path," "uniformly random," or cache directory names.

### 4. Dataset provenance and result identity (~200 words)

Keep this narrow: what identity fields land in the result bundle. Push the *why* and the
redistribution discussion to #14. If this section starts repeating #14, cut it and link.

- Point to `DATA-LICENSE.md` style provenance notes for real-world benchmark datasets.
- Explain `dataset_version`, `manifest_hash`, and `data_archive_hash` in plain language:
  - which dataset
  - which manifest contract
  - which archive content
- Important limitation: hashes identify the data contract; they do not make benchmark methodology
  universal. Hardware, versions, platform config, and query selection still matter.

### 5. Approximate and sketch coverage (~350 words)

This is the second major change. Keep it practical and avoid turning it into a vendor or
engine comparison post.

- `read_primitives` adds approximate aggregate query coverage.
- DataFrame implementations add sketch-backed approximate count/quantile paths where supported.
- `write_primitives` adds sketch persist/merge/query paths.
- Storage-size validation matters because persisted sketches are not just about latency; state size
  is part of the tradeoff.
- Parameter sweeps help users compare size, accuracy, and latency settings rather than guessing.
- Keep cloud-engine claims scoped to what has actually been verified in the final changelog.

### 6. Prompt composer: an agent-benchmarking starting point (~250 words)

Consolidate the useful material from the former prompt-composer outline here. Do not make this a
standalone post, and do not over-explain the implementation.

Use the public language so readers can find the page:

- Nav label: **Instruct an agent**
- Page H1: **Instruct a coding agent to use BenchBox**
- URL: `/prompts/`

Frame the feature:

- The CLI, Python, and MCP surfaces already give agents enough to run BenchBox. The page makes the
  high-quality agent flow easier to start from the landing site.
- A visitor chooses goal, surface, interface, deployment model, platform, benchmark, and scale.
- The page emits a copyable agent prompt; it adds an MCP config block when MCP is selected and
  cloud-safety guidance when managed cloud is selected.
- The default path should be safe local DuckDB + TPC-H at SF 0.01.
- Platform inclusion comes from runtime registry metadata, with hand-authored YAML reserved for
  labels, safety copy, and presentation corrections.
- MCP tool and prompt names are validated so the page does not ask agents to call stale tools.
- Managed-cloud prompts start with dependency/status checks and dry-runs, do not ask users to
  paste secrets, and tell the agent to stop and summarize missing credentials.
- It deliberately does not add a `benchbox prompts` CLI, MCP prompt-rendering tool, public JSON API,
  or recipe mode.

### 7. Also in v0.3.0 (~150 words)

Use a compact bullet list for changes that matter but do not anchor this post.

Candidates from the final changelog:

- `ValidationQuery.platform_overrides`.
- PySpark sketch DataFrame support.
- Any release-gate fixes that are still present in the final changelog when v0.3.0 is cut.

Rule for drafting: include only claims that remain in the final v0.3.0 changelog. Do not copy the
whole changelog into the post.

### 8. Try it yourself (~150 words)

Proposed commands:

```bash
uv add "benchbox[duckdb]"
uv run benchbox run --platform duckdb --benchmark tpch --scale 0.01
```

Prompt composer:

```text
https://benchbox.dev/prompts/
```

JoinOrder command should be included only with a caveat that it uses the full IMDb 2013 JOB dataset
at SF=1:

```bash
uv run benchbox run --platform duckdb --benchmark joinorder --scale 1
```

Add a short note that the dataset is downloaded and verified on first use. Do not include internal
cache paths.

---

## Drafting Risks

| Risk | Mitigation |
| --- | --- |
| Overstating v0.3.0 as generally stable | Tie claims to specific release evidence and tests |
| Making legal claims about IMDb redistribution | Use the phrase "provenance and redistribution risk are documented"; do not say "fully cleared" |
| Turning `/prompts/` into an API announcement | Say it is a static landing route, not a new CLI/MCP/runtime API |
| Giving the prompt composer too much weight | Keep it to one compact section and one "At a glance" row |
| Burying breaking change impact | Put JoinOrder behavior change in the TL;DR and "At a glance" table |
| Turning release machinery into reader-facing news | Keep release mechanics out of the title, TL;DR, and at-a-glance table |
| Results Explorer creeping into scope | Do not discuss Results Explorer in the post |

---

## Follow-Up Research Before Draft

- Confirm the final v0.3.0 changelog after release branch cut.
- Confirm the user report or discussion that raised the JoinOrder issue, and cite it if public.
- Verify current `/prompts/` URL, nav label, H1, default prompt, MCP output, and managed-cloud
  safety output before publishing.
- Confirm the final changelog does not list Results Explorer as a shipped v0.3.0 feature.
- Check final release date, tag URL, and PyPI package metadata once v0.3.0 is cut.
