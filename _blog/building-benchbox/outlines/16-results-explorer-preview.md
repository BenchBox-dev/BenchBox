---
title: "Announcing the BenchBox Results Explorer preview"
series: building-benchbox
post_number: 16
type: architecture-design
tags: [benchbox, results-explorer, benchmarking, methodology, provenance, duckdb-wasm]
status: DRAFTED
---

# Outline: Announcing the BenchBox Results Explorer preview

## Purpose

Announce the Results Explorer preview named in BenchBox v0.4.0 and explain the product decisions behind it. This post gives four topics distinct narrative jobs, in this order:

1. The inspiration we took from Geekbench and public AI evaluation leaderboards.
2. Why BenchBox needed a public results site in addition to CLI output and result files.
3. How readers can use the Explorer to answer practical comparison and audit questions.
4. How contributors can upload a complete result through the hosted service or package it for the public pull-request workflow.

Keep the existing comparability article as a separate WIP engineering deep dive (post 17). Do not publish or link to it from this announcement without explicit approval, and do not inherit its gate-by-gate structure or corpus-correction narrative.

## Audience

- Data engineers looking for public benchmark evidence they can inspect rather than a single score.
- BenchBox users who want to share a run or compare it with published results.
- Open-source maintainers interested in a static, contribution-friendly results site.
- Readers familiar with hardware or AI leaderboards who want to understand how BenchBox adapts those patterns for database benchmarks.

## Thesis

The Results Explorer turns BenchBox result bundles into a public place where readers can find comparable runs, inspect the context behind each number, and contribute new evidence. Geekbench and AI evaluation leaderboards inspired the familiar browse-and-compare experience; BenchBox adds benchmark-specific scope, per-query detail, downloadable bundles, visible provenance, hosted submission, and a pull-request contribution path.

## Post type and length

Architecture/Design preview announcement, 1,800-2,200 words. Follow the series beats without forcing every heading to use the template label:

- Opening: 150-200 words
- Inspiration / What We Tried: 300-400 words
- Why we built it / The Problem: 250-350 words
- What We Built and reader value: 450-600 words
- Submit your own result: 425-550 words
- What We Learned and preview scope: 200-300 words
- Try It Yourself: 100-150 words

## Evidence boundary

- Preview and v0.4.0 framing: `CHANGELOG.md` section `[0.4.0]`, especially “Results Explorer preview” and “Result provenance and funding labels.” Use the changelog’s exact bound: a curated set of results, not a complete or certified ranking.
- Launch history: `docs/development/benchbox-results-platform-strategy.md:27-33`. Phase 1 launched on April 4, 2026; v0.4.0 is the first tagged release whose changelog names the preview. Announce the preview without claiming the website first became reachable in v0.4.0.
- Geekbench inspiration: strategy reference matrix at `docs/development/benchbox-results-platform-strategy.md:486-493`; cite [Geekbench Browser](https://browser.geekbench.com/) as a primary external source in the draft.
- AI evaluation inspiration: cite primary sources rather than treating every AI leaderboard as the same product. Use [Hugging Face Open LLM Leaderboard](https://huggingface.co/spaces/open-llm-leaderboard/open_llm_leaderboard) for public model evaluation tables and [Stanford HELM](https://crfm.stanford.edu/helm/) for evaluation context and transparent scenario reporting. Verify the exact UI claims against the live sources at draft time. Do not add Chatbot Arena unless its distinct pairwise, human-preference methodology is relevant to a specific sentence.
- Explorer architecture and product intent: `docs/development/benchbox-results-platform-strategy.md`, especially Product Intent, Revised UX Surfaces, and Phase 1 Architecture.
- Current Explorer behavior: released `v0.4.0` source plus the live Explorer and deployed snapshot. Date every corpus count and re-read it at draft time.
- Submission flows: `docs/reference/cli/submit.md`, `docs/guides/hosted-submission.md`, `docs/contributing-results.md`, `results-data/README.md`, `benchbox/cli/commands/submit.py`, and `.github/workflows/validate-submission.yml` on the current release branch.
- Submission privacy prerequisite: `benchbox/core/results/anonymization.py:115-165` and `docs/development/adr/adr-published-identifier-field-set.md:87-130`. `benchbox submit` requires a stable, private, non-empty `BENCHBOX_MACHINE_ID_SALT` before the first public submission.
- Environment disclosure: describe hardware, driver, tuning, validation, and related fields as visible **when recorded**. Missing fields remain visible as missing evidence. Do not claim every bundle contains a complete environment.

## Proposed structure

### Opening: the preview has a public home (~175 words)

- Open with the news: BenchBox v0.4.0 names the Results Explorer preview at `https://benchbox.dev/results/`.
- State the reader outcome in the first paragraph: browse benchmark results, compare selected runs per query, inspect methodology and provenance, query the public snapshot, and download the underlying bundle.
- Set the bound once: the site contains a curated preview, not a complete or certified ranking.
- Briefly preview the four threads in their actual section order: inspiration, reason, value, contribution.
- Link the release overview (post 15) for the wider v0.4.0 changes. Keep post 17 unpublished and unlinked.

Proposed TL;DR direction:

> BenchBox’s Results Explorer preview turns public result bundles into browsable comparisons with per-query detail, methodology, provenance, and downloadable evidence. The experience draws on Geekbench and public AI evaluation leaderboards, while keeping database benchmark, scale, phase, and recorded environment context visible. Contributors can upload a complete validated run through the hosted service or package it for a `published-results` pull request.

### 1. Inspiration: familiar public results, adapted for databases (~350 words)

Keep this capability-led and distinguish the references rather than flattening them into one leaderboard model.

**Geekbench Browser**

- Stable result-detail pages give each run a public URL.
- A visible comparison flow lets readers move from one result to a side-by-side view.
- The browser separates a locally produced result from the public place where others can inspect it.
- BenchBox adopts those interaction patterns, not Geekbench’s scoring model or consumer-device assumptions.

**Public AI evaluation leaderboards**

- Open LLM Leaderboard demonstrates the value of a public evaluation table that can be filtered and traced to a named evaluation setup.
- HELM demonstrates the value of keeping scenarios, metrics, and methodological context attached to evaluation results.
- BenchBox applies those lessons to database workloads: readers choose a benchmark, scale, and phase, then inspect per-query evidence and recorded run context rather than relying on one universal score.

Close with the positive synthesis:

> These references made the desired experience familiar: give every result a stable page, make comparison a first-class action, and keep the evaluation context close to the number.

Add primary-source footnotes for every external product characterization.

### 2. Why we created the Explorer: result files need a public reading surface (~300 words)

Start with the gap between producing evidence and making it useful to someone else.

- BenchBox already produced canonical result bundles and CLI charts. Those artifacts are useful to the person who ran the benchmark, but a directory of JSON files does not help a new reader discover which runs share a benchmark, scale, and phase.
- A public site provides the missing reading surface: browse across benchmarks, find relevant runs, share stable links, and inspect methodology without first cloning the repository or learning the result schema.
- A static read path was enough for the preview. The build turns curated bundles into a DuckDB snapshot and downloadable JSON, and DuckDB-WASM queries the snapshot in the browser. This keeps browsing available without an application API or account system.
- The contribution paths use the same canonical bundle. Hosted upload serves contributors who want a direct service workflow, while GitHub identity, pull-request review, and CI validation support repository contributions. Neither path couples browsing to an authenticated service.

Reader outcome to state explicitly:

> The Explorer closes the gap between “BenchBox produced a result” and “another person can find, interpret, and challenge that result.”

### 3. How readers get value today (~550 words)

Organize this around reader jobs, not component names.

#### Find a relevant comparison

- Open a benchmark page and select the scale factor and phase that match the question.
- Use the platform-by-query matrix to see where query behavior differs instead of reducing the workload to one headline number.
- Ranked tables include results only within the shared benchmark, scale, phase, and timing-coverage scope used by that view. State the scope plainly; do not use `cohort-aware`.

#### Understand why two results differ

- Select runs and open Compare.
- The comparison view shows per-query timings and keeps recorded differences in platform version, execution mode, tuning, validation, environment, date, and cost visible.
- Describe these fields as present when recorded. A missing driver version or incomplete environment remains visible as missing evidence rather than being silently filled.
- Summarize the visible comparison context at announcement depth. Do not link to WIP post 17.

#### Audit one published run

- Open the stable result page to inspect benchmark, scale, phase, test type, validation, tuning, provenance, funding, and hardware details when recorded.
- Download the canonical JSON bundle to inspect the evidence outside the site.
- Use the recorded parameters as the starting point for a local corroborating run; do not promise identical timings across different hardware and background load.

#### Ask a question of the public dataset

- Open Query and run SQL over the same DuckDB snapshot used by the pages.
- Use one compact example in the draft, such as counting results by benchmark and validation status.
- Frame the workbench as a reader capability: answer a question that the built-in views do not yet expose.

### 4. How to submit your own results (~500 words)

Make both current destinations clear. Hosted `--service` upload and local `--output` PR packaging use the same canonical bundle. Link the hosted submission guide for the service workflow and the current `docs/contributing-results.md` source for the full pull-request contract.

#### Prepare a complete validated run

- Install the appropriate platform extra.
- Run the complete benchmark suite rather than a selected query subset.
- Use a stable environment and retain plans or tuning companions when intentionally captured.

```bash
uv add "benchbox[duckdb]"
uv run -- benchbox run --platform duckdb --benchmark tpch --scale 0.01
```

#### Configure the public-submission salt

Before the first public `benchbox submit`, set `BENCHBOX_MACHINE_ID_SALT` to a stable, private, non-empty random value. Store and reuse it through a secret manager or protected local environment configuration. Do not commit it or paste it into the pull request.

```bash
export BENCHBOX_MACHINE_ID_SALT="<stable-private-random-value>"
```

Explain why in one sentence: the salt pseudonymizes retained public identifiers, and `benchbox submit` refuses to package a public contribution when it is absent.

#### Preview and choose a destination

```bash
uv run -- benchbox submit --last --service --dry-run
```

- Hosted path: authenticate with `uv run -- benchbox auth login`, upload with `uv run -- benchbox submit --last --service`, and track with `uv run -- benchbox results --submitted`.
- PR path: package with `uv run -- benchbox submit --last --output ./submission`, then inspect the generated bundle and manifest.

- The package contains the canonical result under `submission/bundle/`, optional plan and tuning companions, a per-bundle manifest with a SHA-256 hash, and contribution instructions.
- Use `uv run -- benchbox results --paths --limit 25` when the latest result is not the one to submit.

#### Open the data pull request

- Fork `BenchBox-dev/BenchBox`.
- Copy `submission/bundle/*` into `results-data/bundles/` and copy the per-bundle manifest alongside it. Community contributors do not write under `results-data/bundles/vendor/`.
- Regenerate the inventory:

```bash
uv run -- python scripts/generate_corpus_inventory.py --write
```

- Open the PR against `published-results` with title `results: <benchmark> <platform> sf<scale>`.
- CI checks schema conformance, manifest hash, timing sanity, metadata, and inventory drift, then posts a summary for review.
- After merge, the bundle enters the complete Phase 2 archive. Appearance in the curated Explorer preview requires a separate reviewed promotion. When promoted, community submissions carry their provenance label and remain outside ranked tables under the current policy.

### 5. What the preview teaches us (~250 words)

- A useful public results site needs enough context to support interpretation, and it should keep absent context visible.
- Stable pages, per-query comparison, raw downloads, and a query workbench serve different reader questions; none replaces the others.
- A static read path keeps browsing portable while hosted and pull-request contribution paths serve different contributor needs.
- Corpus curation is part of the product. Keep this concise and avoid the zero-query withdrawal and detailed eligibility history reserved for WIP post 17.
- Name the current open question positively: which benchmarks, platforms, and scales should the community help deepen next?

### 6. Try it yourself (~125 words)

Use direct imperatives:

1. Open `https://benchbox.dev/results/`.
2. Choose a benchmark, scale, and phase.
3. Select two compatible results and open Compare.
4. Open one detail page and download its bundle.
5. Open Query and inspect the public data with SQL.
6. Submit a complete local result through the hosted service or package it for the pull-request path when you are ready to contribute.

Close by inviting feedback through BenchBox Discussions and contributions through either documented submission path.

## Drafting risks

| Risk | Mitigation |
| --- | --- |
| Calling the preview a new v0.4.0 launch | Say v0.4.0 names the preview; Phase 1 became reachable in April 2026 |
| Turning inspiration into unsupported product history | Use primary-source footnotes and distinguish Geekbench, Open LLM Leaderboard, and HELM |
| Repeating or exposing WIP post 17 | Keep eligibility mechanics and corpus correction detail out of the announcement; do not publish or link the WIP post |
| Claiming complete environment data | Use “when recorded” and keep missing fields visible |
| Describing ranked tables with the coined term `cohort-aware` | State the actual shared benchmark, scale, phase, and timing scope |
| Giving an incomplete submit path | Include `BENCHBOX_MACHINE_ID_SALT`, hosted auth/upload/tracking, PR manifest placement, inventory regeneration, and the target branch |
| Implying archive merge guarantees Explorer appearance | State the separate reviewed promotion step |
| Making submission instructions dominate the architecture story | Keep the complete workflows to one section and link their current guides |
| Platform advocacy | Describe reader actions and recorded evidence without winner verdicts |

## Follow-up research before drafting

- Re-read the deployed Explorer and current snapshot on the drafting date; update every corpus count and screenshot.
- Verify Geekbench Browser, Open LLM Leaderboard, and HELM claims against their primary pages and record access dates in footnotes.
- Run the complete submission example in a disposable environment with a temporary private salt and confirm package paths and output text.
- Confirm the hosted submission guide and current `docs/contributing-results.md` source still agree with the CLI and `published-results` workflow on contribution availability and branch target.
- Confirm the current trust-label and ranking policy from `docs/contributing-results.md` and the released Explorer pipeline.
- Test every public URL in the draft, including the Explorer, submission guides, repository, Discussions, and external inspiration sources.
