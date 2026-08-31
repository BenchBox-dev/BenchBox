---
title: "Announcing the BenchBox Results Explorer preview"
blogpost: true
status: draft
date: August 31, 2026
author: Joe Harris
series: building-benchbox
post_number: 16
type: architecture-design
tags: [benchbox, results-explorer, benchmarking, methodology, provenance, duckdb-wasm]
meta_description: "Explore public BenchBox results, compare per-query evidence, inspect provenance, query the dataset, and submit a complete validated community benchmark run."
---

# Announcing the BenchBox Results Explorer preview

**TL;DR**: The [BenchBox Results Explorer](https://benchbox.dev/results/) turns public result bundles into browsable benchmark evidence. You can find runs by benchmark and scale, compare per-query timings, inspect recorded methodology and provenance, query the public snapshot with SQL, and download the underlying bundles. The experience draws on Geekbench and public AI evaluation leaderboards. Contributors can upload a complete validated run through the hosted service or package it for a `published-results` pull request.

---

![The BenchBox Results Explorer preview, showing published benchmark results and controls for building a comparison](../images/results_explorer_preview.png)

BenchBox has produced structured result files since its earliest releases. Those files work well for the person who ran the benchmark: the CLI can summarize them, render charts, and retain the data needed for later inspection. They become harder to use when someone else wants to answer a simple question such as, "Which published TPC-H runs used the same scale and phase as mine?"

The Results Explorer gives those files a public reading surface. Open [benchbox.dev/results/](https://benchbox.dev/results/) to browse the curated preview, select runs, inspect the context recorded with each result, and work with the same public data behind the pages. BenchBox v0.4.0 is the first tagged release to name the preview.[^release] The first static Explorer became reachable in April 2026.[^launch] For the wider release, see [BenchBox v0.4.0: new org, DuckLake, and result provenance](../published/15-v0-4-0-release-overview.md).

The current site is a curated preview rather than a complete or certified ranking. That scope lets us test the browsing, comparison, and contribution workflows while keeping each published number connected to reviewable evidence. The story behind the preview starts with the products that inspired it, moves through the choice to build a separate public site, and ends with the ways readers and contributors can use it today.

## Inspiration: public results need a destination

The first inspiration was the Geekbench Browser. A local Geekbench run can become a public result that another person can browse, organize, and share.[^geekbench] The product makes an important transition feel ordinary: a benchmark starts as an artifact on one machine and becomes a stable page that other people can inspect.

That pattern maps well to BenchBox because it joins three reader actions in one flow: give each result a durable public URL, make comparison an obvious next step, and keep the public page connected to the run that produced it. We borrowed those interaction ideas without adopting Geekbench's scoring model or its focus on consumer devices.

Public AI evaluation projects provided a second set of references. The Open LLM Leaderboard presents an interactive table with sorting, filtering, model search, and pinned comparisons.[^open-llm] HELM supplied a related lesson about evaluation context: its framework standardizes benchmarks and metrics, exposes individual prompts and responses, and publishes leaderboards across models and benchmarks.[^helm]

Database benchmarks need a version of that experience that preserves workload context because benchmark, scale factor, execution phase, query coverage, and recorded run details all affect what a timing means. BenchBox combines the familiar browse-and-compare flow with per-query evidence and methodology so readers can interpret each timing within its workload.

These references gave us a practical design direction: give each result a stable page, make comparison a first-class action, and let readers inspect how the evaluation was produced.

## Why we created a separate Explorer

A directory of JSON bundles is an evidence store, but it is not a good discovery interface. Readers would need to clone a repository, learn the schema, and write code before they could find two runs that measured the same benchmark at the same scale. CLI charts solve a different problem because they begin with files already present on the user's machine.

The Explorer closes the gap between "BenchBox produced a result" and "another person can find, interpret, and challenge that result." It provides public navigation across benchmarks and platforms, stable links for sharing, and a visual route from a summary table to per-query timings and run details. That route also makes a benchmark discussion easier to ground in a specific, downloadable artifact instead of a detached screenshot.

We also wanted the preview to fit the infrastructure BenchBox already operates. The build pipeline transforms curated bundles into static assets, including a DuckDB snapshot and downloadable JSON. DuckDB-WASM runs queries in the browser, so the read path does not require an application server, account system, or hosted database. GitHub Pages serves the site, while the browser performs the interactive analysis.

```text
curated result bundles -> static build -> results.duckdb -> Explorer pages and Query
                                  `-> JSON bundles -> individual downloads
```

This architecture keeps the public evidence portable. A reader can use the prepared views, query the snapshot directly, or leave the site with the canonical bundle.

The submission paths use the same canonical bundle and keep the static read architecture intact. A hosted upload can publish through the BenchBox ingest service, while the pull-request path uses GitHub identity, review, and CI validation to add a bundle to the community archive. Browsing the Explorer still depends only on the generated static assets.

## Four ways to use the Explorer

The pages are organized around questions a benchmark reader is likely to ask.

### Find a relevant comparison

Start with a benchmark, then choose the scale factor and phase that match your question. Scale factor describes the benchmark's data size, while a phase identifies the kind of execution, such as a sequential power run. Keeping those fields attached to the result prevents unrelated timings from collapsing into one list.

The platform-by-query matrix shows where behavior changes across a workload. A headline aggregate can tell you that two runs differ overall. The matrix shows whether the difference is broad or concentrated in a few queries.

Ranked views group results by benchmark, scale, phase, and sufficient timing coverage, and each visible row explains its standing in that scope.

### Understand why two runs differ

Select compatible runs and open Compare. The page pairs per-query timings with recorded platform version, execution mode, tuning, validation, environment, run date, and cost. When a field is absent, the page marks it as not recorded, preserving the distinction between known matches and missing evidence. This context lets readers weigh comparisons that span SQL and DataFrame implementations or different platform versions.

### Audit one published result

Open a result detail page to inspect its benchmark, scale, phase, test type, query timings, validation state, tuning mode, provenance, disclosed funding, and hardware details when recorded. The page is a readable receipt for the run rather than a replacement for the source artifact.

Use **Download bundle** to take the canonical JSON outside the site. The bundle can support an independent analysis, an issue report, or a local corroborating run. Exact timings will still depend on hardware, software versions, configuration, and background load, but the recorded parameters provide a concrete starting point.

### Ask a new question with SQL

The Query page opens a SQL workbench over the same DuckDB snapshot used by the Explorer. Built-in pages cover common paths, but a public dataset will always prompt questions we did not anticipate.

You can filter the snapshot, inspect available columns, count results by benchmark or validation state, and export filtered rows as CSV or JSON. For example:

```sql
SELECT benchmark, validation_status, COUNT(*) AS result_count
FROM bench.results
GROUP BY benchmark, validation_status
ORDER BY benchmark, validation_status;
```

This turns the Explorer from a fixed collection of charts into an analysis surface that readers can extend without waiting for a new page.

## Submit your own result

BenchBox supports two submission destinations. `--service` uploads a canonical bundle to the hosted ingest API, while `--output` creates a local package for the `published-results` pull-request flow. Both begin with the same complete benchmark result and public-submission privacy prerequisite. The [hosted submission guide](https://benchbox.dev/docs/guides/hosted-submission.html) covers the service workflow, while the [current contribution guide source](https://github.com/BenchBox-dev/BenchBox/blob/develop/docs/contributing-results.md) contains the full pull-request contract, and the sequence below shows both paths.

First, install BenchBox with the extra for your platform and run a complete benchmark suite. This example uses DuckDB and TPC-H at scale factor 0.01:

```bash
uv add benchbox --extra duckdb
uv run -- benchbox run --platform duckdb --benchmark tpch --scale 0.01
```

Before the first public submission, set `BENCHBOX_MACHINE_ID_SALT` to a stable, private, non-empty random value. BenchBox uses the salt to pseudonymize retained public identifiers, and `benchbox submit` refuses to package a public contribution when the value is absent. Store it in a secret manager or protected local environment configuration. Reuse it for later submissions, and never commit it or paste it into a pull request.

```bash
export BENCHBOX_MACHINE_ID_SALT="<stable-private-random-value>"
```

Preview the bundle that would be submitted:

```bash
uv run -- benchbox submit --last --service --dry-run
```

For the hosted path, authenticate once, then upload the latest result. The default `--wait` behavior returns after the service publishes or rejects the submission, and `benchbox results --submitted` lists the recorded hosted submissions.

```bash
uv run -- benchbox auth login
uv run -- benchbox submit --last --service
uv run -- benchbox results --submitted
```

Hosted upload is optional. To use the public pull-request workflow instead, write the package to a local directory:

```bash
uv run -- benchbox submit --last --output ./submission
```

If the latest result is not the one you want, list exact paths with `uv run -- benchbox results --paths --limit 25` and pass the selected result file to `benchbox submit`.

The generated PR package contains the canonical result under `submission/bundle/`, any captured plan or tuning companions, a per-bundle manifest with a SHA-256 hash, and contribution instructions. Inspect those files before publishing them.

Fork [`BenchBox-dev/BenchBox`](https://github.com/BenchBox-dev/BenchBox), check out its `published-results` branch, and copy `submission/bundle/*` into `results-data/bundles/`. Copy `submission/<result>.manifest.json` alongside the bundle files. Community submissions belong directly under `results-data/bundles/`, not its `vendor/` directory.

Regenerate the corpus inventory:

```bash
uv run -- python scripts/generate_corpus_inventory.py --write
```

Commit the bundle, manifest, and inventory, then open a pull request against `BenchBox-dev/BenchBox:published-results` with this title shape:

```text
results: <benchmark> <platform> sf<scale>
```

CI checks the schema, manifest hash, timing sanity, metadata, and inventory drift, then posts a summary for maintainer review. After merge, the bundle enters the complete Phase 2 archive. Promotion into the curated Explorer snapshot is a separate reviewed step. A promoted community result carries its provenance label and remains outside ranked tables under the current policy.

## What the preview is teaching us

A useful public results site needs several levels of inspection working together. The benchmark page helps readers discover relevant runs, while Compare keeps per-query evidence and recorded differences together. A result page provides a stable receipt, and raw downloads plus the SQL workbench let readers continue the analysis elsewhere. Each surface answers a different question without forcing every visitor to learn the result schema first.

The static architecture has also been a useful constraint. It lets us improve the public reading experience without putting an authenticated service on the Explorer's read path. The repository, CI checks, and generated snapshot remain visible parts of the system, so changes to the public corpus leave a review trail.

Curation shapes the usefulness of each comparison: depth within the same benchmark, scale, and phase gives readers enough evidence to understand what was measured. The preview helps us identify which benchmarks, platforms, and scales the community wants to deepen next, along with the context fields that matter most during review.

## Try it yourself

Open the [Results Explorer](https://benchbox.dev/results/) and follow one result from summary to source:

1. Choose a benchmark, scale, and phase.
2. Select two compatible runs and open Compare.
3. Open one result page and download its bundle.
4. Use Query to answer a question the built-in views do not cover.
5. Submit a complete validated local run through the hosted service or PR path when you are ready to contribute.

Start a [BenchBox discussion](https://github.com/BenchBox-dev/BenchBox/discussions) if an important comparison question remains hard to answer. Feedback on missing context is especially useful during the preview.

## References

[^release]: [BenchBox changelog: v0.4.0](https://github.com/BenchBox-dev/BenchBox/blob/develop/CHANGELOG.md#040---2026-08-27) - BenchBox, August 27, 2026
[^launch]: [BenchBox results platform strategy](https://github.com/BenchBox-dev/BenchBox/blob/develop/docs/development/benchbox-results-platform-strategy.md) - BenchBox, Phase 1 launched April 4, 2026
[^geekbench]: [Geekbench Browser](https://browser.geekbench.com/) - Primate Labs, accessed August 31, 2026
[^open-llm]: [Open LLM Leaderboard README](https://huggingface.co/spaces/open-llm-leaderboard/open_llm_leaderboard/blob/main/README.md) - Hugging Face, accessed August 31, 2026
[^helm]: [Holistic Evaluation of Language Models](https://crfm-helm.readthedocs.io/en/latest/) - Stanford CRFM, accessed August 31, 2026
