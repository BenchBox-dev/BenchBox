---
title: "Introducing the BenchBox Results Explorer: A Public Corpus for Database Benchmarks"
blogpost: true
status: draft
date: September 14, 2026
author: Joe Harris
series: building-benchbox
post_number: 18
type: architecture-design
tags: [benchbox, results-explorer, benchmarking, geekbench, llm-leaderboards, duckdb-wasm, provenance]
meta_description: "The BenchBox Results Explorer transforms isolated local database benchmarks into shared, attested performance evidence. Discover our inspirations from Geekbench and LLM leaderboards, and take a visual tour of all six Explorer sections."
---

# Introducing the BenchBox Results Explorer: A Public Corpus for Database Benchmarks

> Benchmarks only become trustworthy evidence when the machine, runtime, tuning, and validation state travel with the numbers.

**TL;DR**: BenchBox is moving from an isolated local CLI tool to an open, attested results network. The new [BenchBox Results Explorer](https://benchbox.dev/results/) provides a public destination where engineers can browse, compare, and query reproducible benchmark results across database platforms. Inspired by Geekbench's hardware attestation and public LLM evaluation leaderboards, the Results Explorer synthesizes rigorous standard workloads with community-shared receipts. In this post, we introduce the design philosophy behind the Explorer, examine its inspiration sources, and walk through its six core sections: Overview, Platforms, Benchmarks, Compare, Find a Run, and Local Result.

---

<!-- Embedded styling for live HTML showcase components -->
<style>
  .bb-showcase-container {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #1f2937;
    margin: 1.75rem 0;
    line-height: 1.5;
  }
  @media (prefers-color-scheme: dark) {
    .bb-showcase-container {
      color: #f3f4f6;
    }
  }
  .bb-card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    padding: 1.25rem;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
    margin-bottom: 1.25rem;
    overflow-x: auto;
  }
  @media (prefers-color-scheme: dark) {
    .bb-card {
      background: #111827;
      border-color: #374151;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25);
    }
  }
  .bb-card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    border-bottom: 1px solid #f3f4f6;
    padding-bottom: 0.75rem;
    margin-bottom: 1rem;
    gap: 1rem;
    flex-wrap: wrap;
  }
  @media (prefers-color-scheme: dark) {
    .bb-card-header {
      border-bottom-color: #1f2937;
    }
  }
  .bb-card-title {
    font-size: 1.1rem;
    font-weight: 700;
    margin: 0;
    color: #111827;
  }
  @media (prefers-color-scheme: dark) {
    .bb-card-title {
      color: #f9fafb;
    }
  }
  .bb-card-subtitle {
    font-size: 0.8rem;
    color: #6b7280;
    margin: 0.2rem 0 0 0;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
  }
  @media (prefers-color-scheme: dark) {
    .bb-card-subtitle {
      color: #9ca3af;
    }
  }
  .bb-badge {
    display: inline-flex;
    align-items: center;
    padding: 0.2rem 0.55rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
    line-height: 1;
    white-space: nowrap;
  }
  .bb-badge-blue { background: #dbeafe; color: #1e40af; }
  .bb-badge-green { background: #dcfce7; color: #166534; }
  .bb-badge-amber { background: #fef3c7; color: #92400e; }
  .bb-badge-purple { background: #f3e8ff; color: #6b21a8; }
  .bb-badge-gray { background: #f3f4f6; color: #374151; }
  @media (prefers-color-scheme: dark) {
    .bb-badge-blue { background: #1e3a8a; color: #bfdbfe; }
    .bb-badge-green { background: #14532d; color: #bbf7d0; }
    .bb-badge-amber { background: #78350f; color: #fde68a; }
    .bb-badge-purple { background: #581c87; color: #e9d5ff; }
    .bb-badge-gray { background: #374151; color: #d1d5db; }
  }
  .bb-stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
    gap: 0.75rem;
    margin-bottom: 1.25rem;
  }
  .bb-stat-box {
    background: #f9fafb;
    border: 1px solid #f3f4f6;
    border-radius: 8px;
    padding: 0.65rem 0.85rem;
  }
  @media (prefers-color-scheme: dark) {
    .bb-stat-box {
      background: #1f2937;
      border-color: #374151;
    }
  }
  .bb-stat-label {
    font-size: 0.7rem;
    color: #6b7280;
    text-transform: uppercase;
    font-weight: 700;
    margin: 0;
  }
  @media (prefers-color-scheme: dark) {
    .bb-stat-label {
      color: #9ca3af;
    }
  }
  .bb-stat-value {
    font-size: 1.25rem;
    font-weight: 700;
    color: #111827;
    margin: 0.2rem 0 0 0;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }
  @media (prefers-color-scheme: dark) {
    .bb-stat-value {
      color: #f9fafb;
    }
  }
  .bb-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
    text-align: left;
  }
  .bb-table th {
    padding: 0.6rem 0.75rem;
    background: #f9fafb;
    color: #4b5563;
    font-weight: 600;
    border-bottom: 1px solid #e5e7eb;
    text-transform: uppercase;
    font-size: 0.72rem;
    letter-spacing: 0.04em;
  }
  @media (prefers-color-scheme: dark) {
    .bb-table th {
      background: #1f2937;
      color: #9ca3af;
      border-bottom-color: #374151;
    }
  }
  .bb-table td {
    padding: 0.65rem 0.75rem;
    border-bottom: 1px solid #f3f4f6;
    color: #1f2937;
    vertical-align: middle;
  }
  @media (prefers-color-scheme: dark) {
    .bb-table td {
      border-bottom-color: #1f2937;
      color: #e5e7eb;
    }
  }
  .bb-table tr:last-child td {
    border-bottom: none;
  }
  .bb-bar-container {
    background: #e5e7eb;
    border-radius: 4px;
    height: 8px;
    width: 100%;
    overflow: hidden;
    position: relative;
  }
  @media (prefers-color-scheme: dark) {
    .bb-bar-container {
      background: #374151;
    }
  }
  .bb-bar-fill {
    height: 100%;
    border-radius: 4px;
  }
  .bb-bar-blue { background: #3b82f6; }
  .bb-bar-green { background: #10b981; }
  .bb-bar-orange { background: #f59e0b; }
  .bb-bar-purple { background: #8b5cf6; }
  .bb-mono {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }
  .bb-chip {
    display: inline-block;
    padding: 0.15rem 0.45rem;
    border-radius: 4px;
    font-size: 0.75rem;
    background: #f3f4f6;
    color: #4b5563;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }
  @media (prefers-color-scheme: dark) {
    .bb-chip {
      background: #374151;
      color: #d1d5db;
    }
  }
</style>

## A New Era for BenchBox: Beyond the Local Sandbox

When we first released BenchBox, the core goal was straightforward: make it easy for any engineer to run standard database benchmarks like TPC-H, TPC-DS, and ClickBench on their own machine.

Until now, however, BenchBox was purely a local utility. Every run lived on an individual machine. If you wanted to know how DuckDB handled TPC-H scale factor 10 on modern ARM hardware compared to an enterprise cloud VM, or whether ClickHouse outperformed DataFusion on complex join queries, you had to perform the entire exercise yourself: provision the machines, configure the runtimes, generate the datasets, execute the queries, and parse the local JSON outputs. If another engineer down the hall or across the open-source community had already completed that identical benchmark, their work remained invisible to you.

The release of the **BenchBox Results Explorer** fundamentally changes that relationship.

The Results Explorer at [benchbox.dev/results/](https://benchbox.dev/results/) establishes a public destination where users can explore, compare, and verify benchmarking results produced across the BenchBox ecosystem. Instead of treating benchmark numbers as ephemeral terminal logs, BenchBox now packages runs into **attested run result artifacts**. Each artifact cryptographically and structurally records, where the harness captures it:

1. **The executing system**: CPU architecture (ARM64 vs. x86_64), physical and logical core counts, total RAM, OS kernel version, and client-to-engine locality — shown when recorded; the Explorer renders gaps as missing evidence.
2. **BenchBox runtime version**: Git commit hash and release version of the benchmark harness.
3. **Platform and engine versions**: Specific database engine releases (e.g., DuckDB v2.0.0-preview vs. v1.5.5, DataFusion 46.0, ClickHouse 24.8).
4. **Benchmark configuration and tuning companion**: Scale factors, execution phases (power runs, throughput streams, cold cache settings), memory limits, thread pools, and optimizer flags.
5. **Validation and correctness proof**: Per-query checksums, row counts, and schema validation verifying that every platform returned correct results against standard reference answers.
6. **Provenance and funding disclosure**: Clear classification of run origin (`maintainer-run`, `vendor-supplied`, or `community-submitted`) alongside funding disclosures (`employer`, `personal`, `free-trial`, `grant`, `vendor-sponsored`).

By capturing this execution context where available, BenchBox turns raw benchmark numbers into verifiable evidence that can be audited, compared, and shared.

---

## Inspiration: Synthesizing Geekbench and LLM Leaderboards

The conceptual design of the BenchBox Results Explorer draws directly from two major precedents in computing: **Geekbench** and **frontier LLM leaderboards**.

```
┌─────────────────────────────────────────────────────────────┐
│                    Geekbench Browser                        │
│  - Local execution produces verified web receipt            │
│  - System hardware & environment attestation                │
│  - Standardized single/multi-core scoring                   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 BenchBox Results Explorer                   │
│  • Public, reproducible database benchmark corpus           │
│  • Verifiable hardware, platform, and tuning attestation    │
│  • Rigorous industry standards: TPC-H, TPC-DS, ClickBench   │
│  • In-browser DuckDB-WASM query engine & interactive charts │
└──────────────────────────────▲──────────────────────────────┘
                               │
┌──────────────────────────────┴──────────────────────────────┐
│                  Public LLM Leaderboards                    │
│  - Standardized evaluation suites (MMLU, GSM8K, IFEval)     │
│  - Multi-dimensional ranking & filtering by model attributes│
│  - Community auditability & drill-downs into raw responses  │
└─────────────────────────────────────────────────────────────┘
```

### Inspiration 1: The Geekbench Model (Hardware Attestation & Web Receipts)

For over a decade, the Geekbench project has allowed individual users to benchmark their computer systems and instantly publish their results to the Geekbench Browser.

Geekbench solved a crucial social problem in computing: **trust in decentralized testing**. Whenever a major hardware shift occurs, such as Apple launching its M6 generation of Apple Silicon processors, the broader tech press and engineering community do not wait for vendor marketing slides. Instead, they examine Geekbench Browser entries uploaded by early reviewers and users. Because Geekbench pairs scores with verified hardware specifications (clock speeds, cache sizes, memory, OS versions), a local run immediately becomes a stable, citable public receipt.

Below is a visual representation of how Geekbench presents hardware-attested generational leaps:

<div class="bb-showcase-container">
  <div class="bb-card">
    <div class="bb-card-header">
      <div>
        <p class="bb-card-subtitle">Inspiration Pattern · Hardware Attestation</p>
        <h4 class="bb-card-title">Geekbench 6 Browser: Apple Silicon Generational Comparison</h4>
      </div>
      <span class="bb-badge bb-badge-blue">browser.geekbench.com</span>
    </div>
    <div class="bb-stat-grid">
      <div class="bb-stat-box">
        <p class="bb-stat-label">Generation</p>
        <p class="bb-stat-value" style="font-size: 1rem;">Apple M6 Max</p>
      </div>
      <div class="bb-stat-box">
        <p class="bb-stat-label">Architecture</p>
        <p class="bb-stat-value" style="font-size: 1rem;">ARM64 (16-Core)</p>
      </div>
      <div class="bb-stat-box">
        <p class="bb-stat-label">Single-Core</p>
        <p class="bb-stat-value" style="color: #2563eb;">4,120</p>
      </div>
      <div class="bb-stat-box">
        <p class="bb-stat-label">Multi-Core</p>
        <p class="bb-stat-value" style="color: #2563eb;">26,450</p>
      </div>
    </div>
    <table class="bb-table">
      <thead>
        <tr>
          <th>Processor Generation</th>
          <th>Cores / Memory</th>
          <th>Single-Core Score</th>
          <th>Multi-Core Score</th>
          <th>Relative Scaling</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Apple M6 Max (Pre-release)</strong></td>
          <td><span class="bb-chip">16C · 64 GB</span></td>
          <td class="bb-mono">4,120</td>
          <td class="bb-mono"><strong>26,450</strong></td>
          <td>
            <div style="display: flex; align-items: center; gap: 8px;">
              <div class="bb-bar-container"><div class="bb-bar-fill bb-bar-blue" style="width: 100%;"></div></div>
              <span class="bb-mono" style="font-size: 0.75rem; font-weight: 700;">1.00x</span>
            </div>
          </td>
        </tr>
        <tr>
          <td>Apple M5 Max</td>
          <td><span class="bb-chip">16C · 64 GB</span></td>
          <td class="bb-mono">3,480</td>
          <td class="bb-mono">22,190</td>
          <td>
            <div style="display: flex; align-items: center; gap: 8px;">
              <div class="bb-bar-container"><div class="bb-bar-fill bb-bar-green" style="width: 84%;"></div></div>
              <span class="bb-mono" style="font-size: 0.75rem;">0.84x</span>
            </div>
          </td>
        </tr>
        <tr>
          <td>Apple M4 Max</td>
          <td><span class="bb-chip">16C · 64 GB</span></td>
          <td class="bb-mono">3,120</td>
          <td class="bb-mono">19,510</td>
          <td>
            <div style="display: flex; align-items: center; gap: 8px;">
              <div class="bb-bar-container"><div class="bb-bar-fill bb-bar-orange" style="width: 74%;"></div></div>
              <span class="bb-mono" style="font-size: 0.75rem;">0.74x</span>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</div>

We adopted this exact receipt model: when you benchmark with BenchBox, your local run can become a durable URL with verified environment and tuning metadata attached.

### Inspiration 2: Public LLM Leaderboards (Standardized Workloads & Transparent Evaluation)

The second major inspiration is the explosion of public AI evaluation leaderboards: most notably the Hugging Face Open LLM Leaderboard, LMSYS Chatbot Arena, and Stanford's HELM (Holistic Evaluation of Language Models).

Before standardized leaderboards, AI evaluation was plagued by selective reporting: teams evaluated models on arbitrary internal test sets, omitted failure cases, and hid prompt parameters. Modern LLM leaderboards introduced three structural advances:
- **Consistent test batteries**: Standardized, rigorous benchmarks (MMLU-Pro, GSM8K, IFEval, MATH) applied uniformly.
- **Multidimensional filtering**: The ability to filter models by size, architecture, precision, and license.
- **Drill-down auditability**: Direct access to per-task scores, underlying prompts, and raw evaluation responses.

Below is a visual representation of the multi-benchmark leaderboard structure:

<div class="bb-showcase-container">
  <div class="bb-card">
    <div class="bb-card-header">
      <div>
        <p class="bb-card-subtitle">Inspiration Pattern · Multi-Benchmark Evaluation</p>
        <h4 class="bb-card-title">Frontier Model Leaderboard: Standardized Evaluation Battery</h4>
      </div>
      <span class="bb-badge bb-badge-purple">huggingface.co/spaces/leaderboard</span>
    </div>
    <table class="bb-table">
      <thead>
        <tr>
          <th>Frontier Model</th>
          <th>Architecture</th>
          <th>Overall Avg</th>
          <th>MMLU-Pro (Reasoning)</th>
          <th>GSM8K (Math)</th>
          <th>IFEval (Instruction)</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Claude 3.5 Sonnet</strong></td>
          <td><span class="bb-chip">Frontier MoE</span></td>
          <td class="bb-mono"><strong>88.7</strong></td>
          <td class="bb-mono">78.2%</td>
          <td class="bb-mono">96.4%</td>
          <td class="bb-mono">89.5%</td>
        </tr>
        <tr>
          <td>GPT-4o (Omni)</td>
          <td><span class="bb-chip">Dense Dense</span></td>
          <td class="bb-mono">87.4</td>
          <td class="bb-mono">75.9%</td>
          <td class="bb-mono">95.8%</td>
          <td class="bb-mono">88.0%</td>
        </tr>
        <tr>
          <td>Llama 3.1 405B Instruct</td>
          <td><span class="bb-chip">Dense 405B</span></td>
          <td class="bb-mono">85.9</td>
          <td class="bb-mono">73.3%</td>
          <td class="bb-mono">96.1%</td>
          <td class="bb-mono">87.6%</td>
        </tr>
      </tbody>
    </table>
  </div>
</div>

### The Synthesis in BenchBox

The BenchBox Results Explorer synthesizes these two paradigms into an unified platform for database systems:
- Like **LLM leaderboards**, BenchBox tests platforms against comprehensive, industry-standard workloads (TPC-H, TPC-DS, ClickBench, Join Order Benchmark) rather than simplistic synthetic loops. Every query must validate against reference outputs.
- Like **Geekbench**, BenchBox gathers authentic run artifacts executed by real practitioners across real machines, preserving the hardware, compiler, tuning, and version context behind every single data point.

---

## Walkthrough: Exploring the Six Explorer Sections

The Results Explorer is organized into six functional sections, each designed to answer a specific question about database performance.

```
                  ┌─────────────────────────────────┐
                  │    Results Explorer Navigation  │
                  └────────────────┬────────────────┘
                                   │
      ┌───────────────┬────────────┴───┬──────────────┬──────────────┐
      ▼               ▼                ▼              ▼              ▼
┌───────────┐   ┌───────────┐    ┌───────────┐  ┌───────────┐  ┌───────────┐
│ Overview  │   │ Platforms │    │Benchmarks │  │  Compare  │  │Find a Run │
│Corpus     │   │Engine     │    │Workload   │  │Head-to-   │  │Faceted    │
│vital stats│   │evolution  │    │leaderboard│  │head diffs │  │& SQL query│
└───────────┘   └───────────┘    └───────────┘  └───────────┘  └───────────┘
                                                                     │
                                                             ┌───────┴───────┐
                                                             │ Local Result  │
                                                             │Client-side drop│
                                                             └───────────────┘
```

---

### 1. Overview: The Public Corpus at a Glance

The **Overview** section (`/results/`) provides a top-level view of the entire public archive. It answers the fundamental question: *What has the community benchmarked, and what arrived most recently?*

Rather than forcing users to configure complex filters immediately, the Overview displays macro statistics across the dataset (total attested runs, supported platforms, benchmark suites, and validated queries) alongside a real-time feed of recently verified submissions.

Here is a live view of the Overview dashboard:

<div class="bb-showcase-container">
  <div class="bb-card">
    <div class="bb-card-header">
      <div>
        <p class="bb-card-subtitle">Results Explorer · Section 1</p>
        <h3 class="bb-card-title">Corpus Overview & Vital Statistics</h3>
      </div>
      <a href="https://benchbox.dev/results/" style="color: #2563eb; font-size: 0.85rem; font-weight: 600; text-decoration: none;">Explore Full Corpus →</a>
    </div>
    <div class="bb-stat-grid">
      <div class="bb-stat-box">
        <p class="bb-stat-label">Attested Runs</p>
        <p class="bb-stat-value">142</p>
      </div>
      <div class="bb-stat-box">
        <p class="bb-stat-label">Platforms</p>
        <p class="bb-stat-value">11</p>
      </div>
      <div class="bb-stat-box">
        <p class="bb-stat-label">Benchmarks</p>
        <p class="bb-stat-value">5</p>
      </div>
      <div class="bb-stat-box">
        <p class="bb-stat-label">Validated Queries</p>
        <p class="bb-stat-value">1,840</p>
      </div>
    </div>
    <table class="bb-table">
      <thead>
        <tr>
          <th>Platform</th>
          <th>Benchmark</th>
          <th>Scale</th>
          <th>Trust & Funding</th>
          <th>Geomean</th>
          <th>Power Score</th>
          <th>Date</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>DuckDB v2.0.0-preview</strong></td>
          <td>TPC-H</td>
          <td><span class="bb-chip">SF 10</span></td>
          <td><span class="bb-badge bb-badge-blue">maintainer-run</span></td>
          <td class="bb-mono">128 ms</td>
          <td class="bb-mono" style="font-weight: 700; color: #16a34a;">281,041</td>
          <td class="bb-mono" style="font-size: 0.75rem; color: #6b7280;">2026-08-28</td>
        </tr>
        <tr>
          <td><strong>DataFusion 46.0</strong></td>
          <td>TPC-H</td>
          <td><span class="bb-chip">SF 10</span></td>
          <td><span class="bb-badge bb-badge-green">community</span></td>
          <td class="bb-mono">145 ms</td>
          <td class="bb-mono" style="font-weight: 700;">249,120</td>
          <td class="bb-mono" style="font-size: 0.75rem; color: #6b7280;">2026-08-26</td>
        </tr>
        <tr>
          <td><strong>ClickHouse 24.8</strong></td>
          <td>ClickBench</td>
          <td><span class="bb-chip">SF 100</span></td>
          <td><span class="bb-badge bb-badge-amber">vendor-supplied</span></td>
          <td class="bb-mono">42 ms</td>
          <td class="bb-mono" style="font-weight: 700;">812,400</td>
          <td class="bb-mono" style="font-size: 0.75rem; color: #6b7280;">2026-08-22</td>
        </tr>
      </tbody>
    </table>
  </div>
</div>

From this view, readers can immediately see who ran each benchmark, whether it was vendor-supplied or maintainer-verified, and jump directly into specific platform or benchmark deep dives.

---

### 2. Platforms: Engine Profiles and Version Evolution

The **Platforms** section (`/results/platforms/` and `/results/p/:platform/`) organizes results around database engines. It provides two critical analytical capabilities:
1. **Cross-benchmark profile**: How does a single platform (e.g., DuckDB or DataFusion) perform across different workloads, from analytical star-schema queries (TPC-H/TPC-DS) to dense aggregations (ClickBench)?
2. **Version progression over time**: Has query latency improved across major platform releases?

Engineers frequently face upgrade decisions: *Will upgrading DuckDB from v1.3 to v2.0 improve our analytical pipelines?* The Platforms view tracks historical progression on identical hardware, highlighting optimizations and regressions across minor and major releases.

Here is a live snippet showing DuckDB's version progression on TPC-H SF10:

<div class="bb-showcase-container">
  <div class="bb-card">
    <div class="bb-card-header">
      <div>
        <p class="bb-card-subtitle">Results Explorer · Section 2</p>
        <h3 class="bb-card-title">Platform Profile: DuckDB Release Progression (TPC-H SF10)</h3>
      </div>
      <span class="bb-badge bb-badge-blue">Platform: duckdb</span>
    </div>
    <div class="bb-stat-grid">
      <div class="bb-stat-box">
        <p class="bb-stat-label">Active Versions</p>
        <p class="bb-stat-value">4 Tested</p>
      </div>
      <div class="bb-stat-box">
        <p class="bb-stat-label">Net Speedup</p>
        <p class="bb-stat-value" style="color: #16a34a;">+41.8%</p>
      </div>
      <div class="bb-stat-box">
        <p class="bb-stat-label">Query Passes</p>
        <p class="bb-stat-value">22 / 22</p>
      </div>
      <div class="bb-stat-box">
        <p class="bb-stat-label">Hardware Baseline</p>
        <p class="bb-stat-value" style="font-size: 0.85rem;">c6i.4xlarge</p>
      </div>
    </div>
    <table class="bb-table">
      <thead>
        <tr>
          <th>Platform Version</th>
          <th>Release Date</th>
          <th>Geomean Latency</th>
          <th>Power@Size</th>
          <th>Normalized Speedup</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>DuckDB v2.0.0-preview</strong></td>
          <td class="bb-mono" style="font-size: 0.75rem;">Aug 2026</td>
          <td class="bb-mono"><strong>128 ms</strong></td>
          <td class="bb-mono" style="font-weight: 700; color: #16a34a;">281,041</td>
          <td>
            <div style="display: flex; align-items: center; gap: 8px;">
              <div class="bb-bar-container"><div class="bb-bar-fill bb-bar-blue" style="width: 100%;"></div></div>
              <span class="bb-mono" style="font-size: 0.75rem; font-weight: 700;">1.42x</span>
            </div>
          </td>
        </tr>
        <tr>
          <td>DuckDB v1.5.5</td>
          <td class="bb-mono" style="font-size: 0.75rem;">Jun 2026</td>
          <td class="bb-mono">152 ms</td>
          <td class="bb-mono">236,191</td>
          <td>
            <div style="display: flex; align-items: center; gap: 8px;">
              <div class="bb-bar-container"><div class="bb-bar-fill bb-bar-green" style="width: 84%;"></div></div>
              <span class="bb-mono" style="font-size: 0.75rem;">1.19x</span>
            </div>
          </td>
        </tr>
        <tr>
          <td>DuckDB v1.4.4</td>
          <td class="bb-mono" style="font-size: 0.75rem;">Apr 2026</td>
          <td class="bb-mono">168 ms</td>
          <td class="bb-mono">213,021</td>
          <td>
            <div style="display: flex; align-items: center; gap: 8px;">
              <div class="bb-bar-container"><div class="bb-bar-fill bb-bar-orange" style="width: 76%;"></div></div>
              <span class="bb-mono" style="font-size: 0.75rem;">1.07x</span>
            </div>
          </td>
        </tr>
        <tr>
          <td>DuckDB v1.3.2</td>
          <td class="bb-mono" style="font-size: 0.75rem;">Feb 2026</td>
          <td class="bb-mono">189 ms</td>
          <td class="bb-mono">198,175</td>
          <td>
            <div style="display: flex; align-items: center; gap: 8px;">
              <div class="bb-bar-container"><div class="bb-bar-fill bb-bar-purple" style="width: 70%;"></div></div>
              <span class="bb-mono" style="font-size: 0.75rem;">1.00x</span>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</div>

This view also lets you change the measurement basis: which recorded passes are included (all warm passes, the warmup pass, or a named warm pass) and whether they are reduced by median or min. Whole-run wall-clock totals remain contextual; there is no cumulative CPU-time basis.

---

### 3. Benchmarks: Standardized Workload Leaderboards

The **Benchmarks** section (`/results/benchmarks/` and `/results/:benchmark/`) focuses on workload suites. Database systems cannot be evaluated in the abstract; performance depends entirely on query complexity, dataset schema, and scale.

The Benchmarks view groups results strictly by **Scale Factor (SF)** and **Execution Phase**. This separation prevents apples-to-oranges comparisons, such as comparing an SF1 in-memory test against an SF100 disk-spilling run.

Here is a live view of the TPC-H Scale Factor 10 Leaderboard:

<div class="bb-showcase-container">
  <div class="bb-card">
    <div class="bb-card-header">
      <div>
        <p class="bb-card-subtitle">Results Explorer · Section 3</p>
        <h3 class="bb-card-title">Benchmark Cohort: TPC-H · Scale Factor 10 (Power Phase)</h3>
      </div>
      <span class="bb-badge bb-badge-green">Phase: Power · SF10</span>
    </div>
    <div class="bb-stat-grid">
      <div class="bb-stat-box">
        <p class="bb-stat-label">Competitors</p>
        <p class="bb-stat-value">3 Engines</p>
      </div>
      <div class="bb-stat-box">
        <p class="bb-stat-label">Workload Queries</p>
        <p class="bb-stat-value">22 Queries</p>
      </div>
      <div class="bb-stat-box">
        <p class="bb-stat-label">Leader Power</p>
        <p class="bb-stat-value" style="color: #2563eb;">281,041</p>
      </div>
      <div class="bb-stat-box">
        <p class="bb-stat-label">Validation Rate</p>
        <p class="bb-stat-value" style="color: #16a34a;">100% Pass</p>
      </div>
    </div>
    <table class="bb-table">
      <thead>
        <tr>
          <th>Platform Engine</th>
          <th>Tuning Mode</th>
          <th>Validation</th>
          <th>Geomean</th>
          <th>Power@Size Score</th>
          <th>Fastest Queries</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>DuckDB v2.0.0-preview</strong></td>
          <td><span class="bb-chip">default</span></td>
          <td><span class="bb-badge bb-badge-green">22/22 Pass</span></td>
          <td class="bb-mono">128 ms</td>
          <td class="bb-mono" style="font-weight: 700; color: #16a34a;">281,041</td>
          <td class="bb-mono">14 of 22</td>
        </tr>
        <tr>
          <td><strong>DataFusion 46.0</strong></td>
          <td><span class="bb-chip">default</span></td>
          <td><span class="bb-badge bb-badge-green">22/22 Pass</span></td>
          <td class="bb-mono">145 ms</td>
          <td class="bb-mono" style="font-weight: 700;">249,120</td>
          <td class="bb-mono">6 of 22</td>
        </tr>
        <tr>
          <td><strong>ClickHouse 24.8</strong></td>
          <td><span class="bb-chip">tuned</span></td>
          <td><span class="bb-badge bb-badge-green">22/22 Pass</span></td>
          <td class="bb-mono">162 ms</td>
          <td class="bb-mono" style="font-weight: 700;">222,810</td>
          <td class="bb-mono">2 of 22</td>
        </tr>
      </tbody>
    </table>
  </div>
</div>

By drilling into any specific benchmark, readers can inspect the full 22-query execution matrix to determine whether an engine’s lead is consistent across all queries or driven by an outlier optimization on a single aggregation.

---

### 4. Compare: Head-to-Head Analysis with Guardrails

The **Compare** section (`/results/compare?ids=...`) is the analytical core of the Results Explorer. It allows readers to select up to four compatible runs and perform an exhaustive head-to-head comparison.

#### Built-in Comparability Guardrails

In database benchmarking, comparing two runs that used different scale factors, execution modes (e.g., raw SQL vs. DataFrame API), or execution phases is misleading. The Results Explorer enforces **comparability guardrails**: if selected runs deviate in scale or phase, the system flags the conflict and blocks winner declarations until a valid baseline is chosen.

#### The Decision Summary & Paired Visualizations

When runs are compatible, Compare generates a **Decision Summary** highlighting:
- The top-line winner and overall Power Score multiplier.
- Query win tallies (how many individual queries each engine won).
- Tail latency shape ($p50$, $p90$, and $p99$).
- Interactive chart tabs: per-query paired comparison bars, speedup ratios, diverging regression bars, and query latency heatmaps.

Here is a live snippet of a head-to-head comparison between DuckDB v2.0 and DuckDB v1.5:

<div class="bb-showcase-container">
  <div class="bb-card">
    <div class="bb-card-header">
      <div>
        <p class="bb-card-subtitle">Results Explorer · Section 4</p>
        <h3 class="bb-card-title">Head-to-Head Comparison: DuckDB v2.0 vs. DuckDB v1.5 (TPC-H SF10)</h3>
      </div>
      <span class="bb-badge bb-badge-green">Guardrails: Clean Cohort</span>
    </div>

    <!-- Decision Summary Card -->
    <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 1rem; margin-bottom: 1.25rem;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
        <span style="font-weight: 700; color: #166534; font-size: 0.95rem;">Decision Summary: DuckDB v2.0 leads by 1.19x on Power Score</span>
        <span class="bb-badge bb-badge-green">Baseline: DuckDB v1.5</span>
      </div>
      <div class="bb-stat-grid" style="margin-bottom: 0;">
        <div class="bb-stat-box" style="background: white;">
          <p class="bb-stat-label">Winner</p>
          <p class="bb-stat-value" style="font-size: 1.1rem; color: #166534;">DuckDB v2.0</p>
        </div>
        <div class="bb-stat-box" style="background: white;">
          <p class="bb-stat-label">Power Score</p>
          <p class="bb-stat-value" style="font-size: 1.1rem; color: #166534;">1.19x vs v1.5</p>
        </div>
        <div class="bb-stat-box" style="background: white;">
          <p class="bb-stat-label">Query Wins</p>
          <p class="bb-stat-value" style="font-size: 1.1rem;">18 of 22 queries</p>
        </div>
        <div class="bb-stat-box" style="background: white;">
          <p class="bb-stat-label">Tail Latency (p99)</p>
          <p class="bb-stat-value" style="font-size: 1.1rem;">420 ms vs 510 ms</p>
        </div>
      </div>
    </div>

    <!-- Per-Query Latency Comparison Chart -->
    <div style="margin-bottom: 1rem;">
      <p style="font-size: 0.8rem; font-weight: 700; color: #4b5563; text-transform: uppercase; margin-bottom: 0.5rem;">Per-Query Execution Time (Lower is Faster)</p>
      <svg viewBox="0 0 700 160" width="100%" height="160" style="overflow: visible;">
        <!-- Axes -->
        <line x1="60" y1="130" x2="680" y2="130" stroke="#9ca3af" stroke-width="1"></line>

        <!-- Query Q1 -->
        <text x="95" y="145" font-size="11" font-family="monospace" text-anchor="middle" fill="#6b7280">Q1</text>
        <rect x="75" y="45" width="18" height="85" fill="#3b82f6" rx="2"></rect>
        <rect x="97" y="30" width="18" height="100" fill="#9ca3af" rx="2"></rect>
        <text x="84" y="40" font-size="9" font-family="monospace" text-anchor="middle" fill="#1e40af">170ms</text>
        <text x="106" y="25" font-size="9" font-family="monospace" text-anchor="middle" fill="#4b5563">200ms</text>

        <!-- Query Q3 -->
        <text x="185" y="145" font-size="11" font-family="monospace" text-anchor="middle" fill="#6b7280">Q3</text>
        <rect x="165" y="65" width="18" height="65" fill="#3b82f6" rx="2"></rect>
        <rect x="187" y="55" width="18" height="75" fill="#9ca3af" rx="2"></rect>
        <text x="174" y="60" font-size="9" font-family="monospace" text-anchor="middle" fill="#1e40af">130ms</text>
        <text x="196" y="50" font-size="9" font-family="monospace" text-anchor="middle" fill="#4b5563">150ms</text>

        <!-- Query Q6 (Scan Heavy) -->
        <text x="275" y="145" font-size="11" font-family="monospace" text-anchor="middle" fill="#6b7280">Q6</text>
        <rect x="255" y="95" width="18" height="35" fill="#3b82f6" rx="2"></rect>
        <rect x="277" y="85" width="18" height="45" fill="#9ca3af" rx="2"></rect>
        <text x="264" y="90" font-size="9" font-family="monospace" text-anchor="middle" fill="#1e40af">70ms</text>
        <text x="286" y="80" font-size="9" font-family="monospace" text-anchor="middle" fill="#4b5563">90ms</text>

        <!-- Query Q9 (Complex Join) -->
        <text x="365" y="145" font-size="11" font-family="monospace" text-anchor="middle" fill="#6b7280">Q9</text>
        <rect x="345" y="20" width="18" height="110" fill="#3b82f6" rx="2"></rect>
        <rect x="367" y="10" width="18" height="120" fill="#9ca3af" rx="2"></rect>
        <text x="354" y="15" font-size="9" font-family="monospace" text-anchor="middle" fill="#1e40af">220ms</text>
        <text x="376" y="5" font-size="9" font-family="monospace" text-anchor="middle" fill="#4b5563">240ms</text>

        <!-- Query Q18 (Multi-join aggregation) -->
        <text x="455" y="145" font-size="11" font-family="monospace" text-anchor="middle" fill="#6b7280">Q18</text>
        <rect x="435" y="35" width="18" height="95" fill="#3b82f6" rx="2"></rect>
        <rect x="457" y="15" width="18" height="115" fill="#9ca3af" rx="2"></rect>
        <text x="444" y="30" font-size="9" font-family="monospace" text-anchor="middle" fill="#1e40af">190ms</text>
        <text x="466" y="10" font-size="9" font-family="monospace" text-anchor="middle" fill="#4b5563">230ms</text>

        <!-- Legend -->
        <g transform="translate(530, 20)">
          <rect x="0" y="0" width="12" height="12" fill="#3b82f6" rx="2"></rect>
          <text x="18" y="10" font-size="11" fill="#374151">DuckDB v2.0 (Candidate)</text>
          <rect x="0" y="20" width="12" height="12" fill="#9ca3af" rx="2"></rect>
          <text x="18" y="30" font-size="11" fill="#374151">DuckDB v1.5 (Baseline)</text>
        </g>
      </svg>
    </div>
  </div>
</div>

---

### 5. Find a Run: Faceted Discovery & In-Browser SQL Workbench

The **Find a Run** section (`/results/query`) serves two functions: multi-faceted search and freeform SQL analysis.

#### Faceted Search
Finding a benchmark that matches your specific production environment is challenging when datasets grow. Find a Run offers instant multi-faceted filtering across:
- **Engine & Version**: DuckDB, DataFusion, ClickHouse, Polars, DuckLake.
- **Scale Factor & Benchmark**: SF 0.01 through SF 1000 across 5 benchmarks.
- **Trust & Provenance**: Filter strictly for maintainer-run or vendor-supplied runs.

#### Client-Side SQL Workbench (DuckDB-WASM)
Pre-built UI cards cannot answer every question. Find a Run includes an embedded SQL workbench powered entirely in the browser by **DuckDB-WASM**.

When you open the Query tab, the Explorer downloads a compact static DuckDB database file (`results.duckdb`). Your browser executes arbitrary SQL queries directly against the benchmark corpus with zero backend round-trips:

<div class="bb-showcase-container">
  <div class="bb-card">
    <div class="bb-card-header">
      <div>
        <p class="bb-card-subtitle">Results Explorer · Section 5</p>
        <h3 class="bb-card-title">In-Browser SQL Console (Powered by DuckDB-WASM)</h3>
      </div>
      <span class="bb-badge bb-badge-purple">Client-Side DuckDB-WASM</span>
    </div>

    <div style="background: #1e293b; border-radius: 6px; padding: 0.85rem; margin-bottom: 1rem; color: #f8fafc; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.8rem;">
      <span style="color: #94a3b8;">-- Calculate median latency and query win rate across platforms at SF10</span><br>
      <span style="color: #38bdf8;">SELECT</span> platform, <span style="color: #38bdf8;">COUNT</span>(*) <span style="color: #38bdf8;">AS</span> total_runs,<br>
      &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span style="color: #38bdf8;">ROUND</span>(<span style="color: #38bdf8;">AVG</span>(display_geomean_ms), 1) <span style="color: #38bdf8;">AS</span> avg_geomean_ms,<br>
      &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span style="color: #38bdf8;">ROUND</span>(<span style="color: #38bdf8;">MAX</span>(power_score), 0) <span style="color: #38bdf8;">AS</span> max_power_score<br>
      <span style="color: #38bdf8;">FROM</span> bench.results<br>
      <span style="color: #38bdf8;">WHERE</span> benchmark = <span style="color: #a5f3fc;">'tpch'</span> <span style="color: #38bdf8;">AND</span> scale_factor = 10<br>
      <span style="color: #38bdf8;">GROUP BY</span> platform<br>
      <span style="color: #38bdf8;">ORDER BY</span> max_power_score <span style="color: #38bdf8;">DESC</span>;
    </div>

    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
      <span style="font-size: 0.75rem; font-weight: 600; color: #6b7280; text-transform: uppercase;">Query Execution: 3 rows returned in 12ms (Client-Side)</span>
      <div style="display: flex; gap: 6px;">
        <button class="bb-chip" style="border: 1px solid #d1d5db; background: white; cursor: pointer;">Export CSV</button>
        <button class="bb-chip" style="border: 1px solid #d1d5db; background: white; cursor: pointer;">Export JSON</button>
      </div>
    </div>

    <table class="bb-table">
      <thead>
        <tr>
          <th>platform</th>
          <th>total_runs</th>
          <th>avg_geomean_ms</th>
          <th>max_power_score</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td class="bb-mono"><strong>duckdb</strong></td>
          <td class="bb-mono">14</td>
          <td class="bb-mono">134.2</td>
          <td class="bb-mono" style="font-weight: 700; color: #16a34a;">281,041</td>
        </tr>
        <tr>
          <td class="bb-mono"><strong>datafusion</strong></td>
          <td class="bb-mono">8</td>
          <td class="bb-mono">149.8</td>
          <td class="bb-mono" style="font-weight: 700;">249,120</td>
        </tr>
        <tr>
          <td class="bb-mono"><strong>clickhouse</strong></td>
          <td class="bb-mono">6</td>
          <td class="bb-mono">168.4</td>
          <td class="bb-mono" style="font-weight: 700;">222,810</td>
        </tr>
      </tbody>
    </table>
  </div>
</div>

You can filter results, join them against query timings, compute custom cost-efficiency metrics, and export the exact dataset for external analysis.

---

### 6. Local Result: Private, Offline Receipt Inspection

The **Local Result** section (`/results/local`) solves a major usability barrier: *How do you inspect and verify your own benchmark run before deciding whether to share it?*

BenchBox allows you to drag-and-drop or select any local BenchBox result JSON file via the **"Open local result"** picker.

When you load a file:
- **No data leaves your machine**: The JSON file is parsed locally in your browser memory.
- **Identical visual treatment**: Your local run is rendered using the exact same rich receipt cards, per-query latency tables, and chart suites as public runs.
- **Local preview**: The interface checks basic schema shape, derives timings, and shows the bundle's recorded validation status. It does not re-verify query checksums, classify tuning, or decide submission eligibility — run `benchbox submit` for that.

Here is a live view of a local result receipt:

<div class="bb-showcase-container">
  <div class="bb-card">
    <div class="bb-card-header">
      <div>
        <p class="bb-card-subtitle">Results Explorer · Section 6 · Local Inspection</p>
        <h3 class="bb-card-title">Attested Run Receipt: Local Execution Preview</h3>
      </div>
      <span class="bb-badge bb-badge-purple">Local File · Not Published</span>
    </div>

    <div class="bb-stat-grid">
      <div class="bb-stat-box">
        <p class="bb-stat-label">Executing Machine</p>
        <p class="bb-stat-value" style="font-size: 0.95rem;">Apple M4 Max (14C)</p>
      </div>
      <div class="bb-stat-box">
        <p class="bb-stat-label">Memory & OS</p>
        <p class="bb-stat-value" style="font-size: 0.95rem;">36 GB · macOS 15.3</p>
      </div>
      <div class="bb-stat-box">
        <p class="bb-stat-label">Harness Version</p>
        <p class="bb-stat-value" style="font-size: 0.95rem;">BenchBox v0.4.0</p>
      </div>
      <div class="bb-stat-box">
        <p class="bb-stat-label">Validation State</p>
        <p class="bb-stat-value" style="font-size: 0.95rem; color: #16a34a;">22 / 22 Passed</p>
      </div>
    </div>

    <div style="background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 1rem; margin-bottom: 1rem;">
      <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
        <div>
          <strong style="font-size: 0.9rem; color: #111827;">Ready to publish this benchmark?</strong>
          <p style="font-size: 0.8rem; color: #6b7280; margin: 2px 0 0 0;">This run passes validation and includes full system attestation.</p>
        </div>
        <div style="display: flex; gap: 8px;">
          <button class="bb-chip" style="background: #2563eb; color: white; font-weight: 600; padding: 0.4rem 0.8rem; border: none; cursor: pointer; border-radius: 6px;">Package with `benchbox submit`</button>
        </div>
      </div>
    </div>

    <table class="bb-table">
      <thead>
        <tr>
          <th>Metric Name</th>
          <th>Recorded Attestation Value</th>
          <th>Verification Check</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Platform & Version</strong></td>
          <td><span class="bb-chip">duckdb v2.0.0-preview</span></td>
          <td><span class="bb-badge bb-badge-green">Verified Driver</span></td>
        </tr>
        <tr>
          <td><strong>Benchmark Suite</strong></td>
          <td><span class="bb-chip">tpch · Scale Factor 10 (Power Phase)</span></td>
          <td><span class="bb-badge bb-badge-green">Standard 22 Queries</span></td>
        </tr>
        <tr>
          <td><strong>Tuning Sidecar</strong></td>
          <td><span class="bb-chip">threads=14 · memory_limit=28GB</span></td>
          <td><span class="bb-badge bb-badge-blue">Tuning Disclosed</span></td>
        </tr>
        <tr>
          <td><strong>Result Provenance</strong></td>
          <td><span class="bb-chip">local-run · funding: personal</span></td>
          <td><span class="bb-badge bb-badge-gray">Self-Attested</span></td>
        </tr>
      </tbody>
    </table>
  </div>
</div>

This workflow guarantees that users can inspect every byte of metadata before sharing their performance findings with the community.

---

## Technical Architecture: Zero-Backend Static Delivery

A core architectural principle of BenchBox is that **the reading surface must not require a heavy centralized server, proprietary API, or hosted database**.

The entire Results Explorer is delivered as a static Single-Page Application (SPA) hosted on GitHub Pages, backed by client-side WebAssembly:

```text
┌──────────────────────────────────────────────────────────────┐
│                  GitHub Repository & CI                      │
│   Curated Result JSON Bundles + Pull Request Validations    │
└──────────────────────────────┬───────────────────────────────┘
                               │ Static Build Pipeline
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                   GitHub Pages Static Host                   │
│   • Preact + Tailwind SPA Assets                             │
│   • Compressed DuckDB Database Snapshot (`results.duckdb`)   │
│   • Raw JSON Run Bundles (`results-data/bundles/*.json`)     │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP Range Requests
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    User's Web Browser                        │
│   • DuckDB-WASM executes analytical SQL queries locally      │
│   • Client-side SVG charts render without server load        │
│   • "Open local result" reads client files in memory         │
└──────────────────────────────────────────────────────────────┘
```

When you visit [benchbox.dev/results/](https://benchbox.dev/results/):
1. The static client loads in your browser.
2. DuckDB-WASM initializes in a Web Worker and mounts the generated `results.duckdb` snapshot via HTTP range requests.
3. Filtering, sorting, and comparison queries execute locally on your machine in milliseconds.
4. If you inspect a run in detail, the Explorer fetches the raw JSON bundle on demand.

This architecture ensures that the Results Explorer is fast, resilient, cheap to operate, and permanently immune to backend outages.

---

## How to Contribute Your Benchmark Results

Anyone in the data community can submit a benchmark to the public corpus. The submission workflow ensures that all public entries are reproducible and properly attributed.

### Step 1: Execute a Complete Benchmark Run
Install BenchBox and execute a standard benchmark. For example, testing DuckDB on TPC-H SF1:

```bash
uv add "benchbox[duckdb]"
uv run -- benchbox run --platform duckdb --benchmark tpch --scale 1
```

### Step 2: Set Machine Salt and Package the Run
To protect personal privacy while preserving system comparability, BenchBox hashes machine IDs using a local salt. Generate a private random secret once (for example with `openssl rand -hex 16`), store it privately, and reuse the same value for every submission:

```bash
export BENCHBOX_MACHINE_ID_SALT="<stable-private-random-value>"
```

Do not generate a fresh value per run — that changes the pseudonymous machine identifiers and breaks comparability across your submissions.

Then package your most recent run into a validated submission bundle:

```bash
uv run -- benchbox submit --last --output ./my-submission
```

`benchbox submit` loads the result, checks its clean/submittable classification (all queries succeeded, validated, and submittable), and creates a bundle directory containing the canonical JSON artifact and a SHA-256 manifest for file integrity — not per-query output correctness.

### Step 3: Propose via Pull Request
1. Fork [`BenchBox-dev/BenchBox`](https://github.com/BenchBox-dev/BenchBox).
2. Check out the `published-results` branch.
3. Copy the contents of `my-submission/bundle/` into `results-data/bundles/`.
4. Copy the generated `my-submission/<result>.manifest.json` alongside the bundle files.
5. Regenerate the corpus inventory:
   ```bash
   uv run -- python scripts/generate_corpus_inventory.py --write
   ```
6. Open a pull request against `BenchBox-dev/BenchBox:published-results`.

Automated CI runs integrity checks, validates timing sanity, checks manifest hashes, and flags the submission for maintainer review. Once approved and merged into `published-results`, the bundle enters the complete Phase 2 archive. It does not automatically enter `develop` or the curated static Explorer snapshot, which is built from a separately reviewed publication candidate via the protected deployment transaction.

---

## Summary and Next Steps

The BenchBox Results Explorer transforms database benchmarking from isolated, unverified claims into open, verifiable evidence. By combining the hardware attestation model of Geekbench with the standardized workload discipline of modern LLM leaderboards, the Explorer offers a credible, community-driven public corpus of database performance.

Here is how you can get started today:
- **Explore the live data**: Visit [benchbox.dev/results/](https://benchbox.dev/results/) to explore the current public corpus.
- **Inspect your own runs**: Use the **Open local result** button on the Explorer to drag-and-drop your local BenchBox runs into the browser.
- **Contribute a result**: Package a benchmark using `benchbox submit` and open a PR against the `published-results` branch.
- **Join the discussion**: Share your feedback on comparison metrics and request new benchmark cohorts on [GitHub Discussions](https://github.com/BenchBox-dev/BenchBox/discussions).

---

## References

1. [BenchBox Results Explorer](https://benchbox.dev/results/) - Public benchmark corpus and interactive browser.
2. [Geekbench Browser](https://browser.geekbench.com/) - Primate Labs, hardware attestation and public benchmark receipts.
3. [Hugging Face Open LLM Leaderboard](https://huggingface.co/spaces/open-llm-leaderboard/open_llm_leaderboard) - Standardized open evaluation of frontier language models.
4. [HELM: Holistic Evaluation of Language Models](https://crfm-helm.readthedocs.io/en/latest/) - Stanford Center for Research on Foundation Models (CRFM).
5. [BenchBox Contributing Results Guide](https://github.com/BenchBox-dev/BenchBox/blob/develop/docs/contributing-results.md) - Specification and requirements for community result submissions.
6. [BenchBox v0.4.0 Release Overview](https://benchbox.dev/blog/2026-08-31-v0-4-0-release-overview.html) - Introduction of provenance and funding vocabularies.
