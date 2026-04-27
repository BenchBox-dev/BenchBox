# "Free Trial Benchmarking" Content Plan

**Concept**: Hands-on guides for maximizing free trial value on commercial analytics platforms supported by BenchBox, with concrete methodology for running meaningful benchmarks before credits expire.

**Audience**: Data engineers, analytics practitioners, and technical evaluators assessing cloud data platforms during free trial periods.

**Tone**: Helpful, practical, time-conscious. We share what we learned running BenchBox on each platform's free tier, with concrete numbers and reproducible commands.

**Length**: 1,500-2,500 words per post (Tutorial/How-To type)

**Cadence**: Weekly during series launch (8 posts over 2 months), then as platforms update their free offerings.

---

## Series Vision

Evaluating a cloud data platform during a free trial requires strategy. Credits expire, features are gated, and the learning curve eats into evaluation time. This series provides **battle-tested playbooks** for each commercial platform BenchBox supports: what you get for free, what to avoid, and exactly how to run meaningful TPC-H/TPC-DS benchmarks before your trial ends.

**Key differentiator**: BenchBox eliminates the setup tax. Each post shows how to go from trial signup to benchmark results in hours, not days:
- **MCP exploration** to preview runs before spending credits
- **Automated setup** (schema creation, data loading, platform tuning)
- **Start small, scale up** methodology to avoid wasted credits on failed runs
- **Result file workflow** for reproducibility and comparison

Not "here's how to sign up" tutorials, but "here's how to extract maximum benchmarking value from your limited trial using BenchBox."

---

## Post Template

### Structure

1. **What You Get** (~300 words)
   - Trial duration and credit amount
   - Key limitations (features, capacity, regions)
   - What happens when trial ends

2. **Explore with MCP** (~300 words)
   - "Which benchmarks can I run on {platform}?" - confirm availability
   - "What would a TPC-H SF1 run look like?" - preview before spending credits
   - "Is my {platform} configuration valid?" - catch issues early
   - Example prompts and responses for this platform

3. **The Game Plan** (~400 words)
   - Start small: SF0.01 to validate setup, then scale up
   - Recommended progression: SF0.01 → SF1 → SF10 (if credits allow)
   - BenchBox handles schema creation, data loading, and tuning automatically

4. **BenchBox Setup** (~300 words)
   - Platform-specific configuration
   - Authentication and connection details
   - Tuning profile recommendations (BenchBox applies common optimizations)

5. **Running the Benchmarks** (~500 words)
   - Exact commands with expected output
   - Credit consumption per scale factor
   - Scaling up: increase compute size, then data size

6. **Reproducing and Comparing** (~300 words)
   - Keep a working directory of result JSON files
   - "Show me my recent {platform} runs" - find previous results
   - "Compare my SF1 and SF10 runs" - track scaling behavior
   - Share result files for reproducibility

7. **Trial Traps to Avoid** (~200 words)
   - Common mistakes that waste credits
   - Features that cost more than expected
   - Cleanup checklist before trial ends

### Metadata Template

```yaml
title: "Free trial benchmarking: {Platform}"
series: free-trial-benchmarking
post_number: N
date: YYYY-MM-DD
tags: [benchmarking, benchbox, tutorial, {platform}, free-trial, {cloud-provider}]
```

---

## Planned Posts

| # | Post | Status | Purpose |
|---|------|--------|---------|
| 0 | **Series intro: Free trials for cloud analytics in 2026** | PLANNED | Overview of all trials, comparison table, series roadmap |

### Platform-Specific Posts

| # | Platform | Credits/Duration | Status | Key Insight |
|---|----------|------------------|--------|-------------|
| 1 | Snowflake | $400/30 days | PLANNED | Auto-suspend is critical; small warehouses stretch credits further |
| 2 | Databricks | $400/14 days | PLANNED | Personal email limits hurt; business email unlocks full trial |
| 3 | BigQuery | $300 + 1TB/mo free | PLANNED | Permanent free tier means ongoing testing possible |
| 4 | MotherDuck | 10 CU-hrs/mo free | PLANNED | Permanent free tier; DuckDB compatibility enables local+cloud |
| 5 | Redshift Serverless | $300/90 days | PLANNED | Longer trial = more methodical testing possible |
| 6 | Starburst Galaxy | $500/30 days | PLANNED | Generous credits; Trino compatibility for federated testing |
| 7 | ClickHouse Cloud | $300/30 days | PLANNED | Per-minute billing; auto-stop essential |
| 8 | Microsoft Fabric | 64 CU/60 days | PLANNED | No upfront credits; capacity-based throttling |
| 9 | Firebolt | $200/30 days | PLANNED | FBU system requires understanding before starting |

---

## Post #0 Outline: Series Introduction

### Title
"Free trials for cloud analytics in 2026: A benchmarker's guide"

### Thesis
> Cloud analytics platforms offer generous free trials, but each has different constraints. Here's what you get, how long you have, and how to run meaningful benchmarks before time or credits run out.

### Structure

**1. The Landscape** (~400 words)
- 9 commercial platforms with meaningful free trials
- Three constraint models: credit-limited, capacity-limited, hybrid
- Why benchmarking during trials matters (validate before committing)

**2. The Comparison Table** (~200 words)

| Platform | Credits | Duration | Constraint Type | Best For |
|----------|---------|----------|-----------------|----------|
| Starburst Galaxy | $500 | 30 days | Credit | Federated queries, Trino evaluation |
| Snowflake | $400 | 30 days | Credit | General OLAP, broad feature set |
| Databricks | $400 | 14 days | Credit | Spark workloads, ML integration |
| ClickHouse Cloud | $300 | 30 days | Credit | Real-time analytics, high insert rates |
| BigQuery | $300 + 1TB/mo | 90 days + ongoing | Hybrid | Long-term testing, GCP integration |
| Redshift Serverless | $300 | 90 days | Credit | AWS integration, methodical evaluation |
| Firebolt | $200 | 30 days | Credit | Sub-second analytics, gaming/adtech |
| Microsoft Fabric | 64 CU | 60 days | Capacity | Microsoft ecosystem, Power BI |
| MotherDuck | 10 CU-hrs/mo | Ongoing | Capacity | DuckDB cloud, local+cloud hybrid |

**3. The BenchBox Approach** (~400 words)
- Start small (SF0.01), validate setup, then scale
- MCP exploration before spending credits
- Result files as reproducible artifacts
- Platform-neutral methodology for fair comparison

**4. Series Roadmap** (~200 words)
- What each platform post covers
- Recommended reading order (by use case, not post number)
- How to request additional platforms

**5. Quick Start** (~200 words)
- Install BenchBox
- Connect the MCP server
- Ask: "Which cloud platforms can I benchmark today?"

### Metadata

```yaml
title: "Free trials for cloud analytics in 2026: A benchmarker's guide"
series: free-trial-benchmarking
post_number: 0
date: YYYY-MM-DD
tags: [benchmarking, benchbox, tutorial, cloud, free-trial, comparison]
```

### Stretch Posts (If Platform Trials Available)

| Platform | Notes |
|----------|-------|
| Azure Synapse | $200/30 days Azure credit (shared with other services) |
| Google Dataproc | $300/90 days GCP credit (shared with other services) |
| Athena | No dedicated trial; AWS Free Plan credits can be used |
| EMR Serverless | No dedicated trial; AWS Free Plan credits can be used |
| AWS Glue | 1M free DPU-hours (generous for testing) |

---

## Key Themes

### 1. BenchBox Gets You Started Quickly

Time is the real constraint. Most trials give you 14-30 days, but learning curves eat into that window. BenchBox accelerates the setup phase:
- **Automated data generation**: No manual CSV wrangling or schema creation
- **Platform tuning applied automatically**: Common optimizations (sort keys, clustering, partitioning) built into each platform adapter
- **MCP exploration**: Use `dry_run` and `validate_config` to preview runs before spending credits
- **Day 1 to benchmarks**: Account setup → first results in hours, not days

### 2. Start Small, Then Scale Up

Don't burn credits on failed runs. The BenchBox workflow:
1. **Validate at SF0.01**: Tiny dataset confirms connectivity, schema, and queries work
2. **Baseline at SF1**: Meaningful performance data with minimal credit spend
3. **Scale compute first**: Increase warehouse/cluster size to find compute-bound queries
4. **Scale data second**: Move to SF10 or SF100 to find data-volume-sensitive queries
5. **Credits vs. capacity**: Know whether your platform runs out of dollars (Snowflake, Databricks) or throttles capacity (Fabric, MotherDuck free tier)

### 3. Keep Results, Enable Reproduction

BenchBox result files are the unit of reproducibility:
- **JSON result files**: Every run produces a complete record (config, timings, validation)
- **Working directory**: Keep `benchmark_runs/results/` organized by platform and date
- **MCP analysis**: Use `get_results` to inspect any previous run, `compare_results` to diff runs
- **Share for collaboration**: Result files are self-contained; others can reproduce your findings

### 4. Platform-Neutral, Single-Platform Focus

Each post focuses on maximizing value from ONE platform's trial. We don't declare winners. Readers running multiple trials can compare their own results using BenchBox's standardized methodology.

---

## Series Tone Examples

**Good** (start small, scale up):
> "Before spending Snowflake credits, ask: 'What would a TPC-H SF0.01 run on Snowflake look like?' The MCP previews the execution plan. Once that validates, scale to SF1. BenchBox handles warehouse tuning automatically."

**Good** (BenchBox accelerates setup):
> "Databricks trials expire in 14 days. BenchBox gets you from account creation to first benchmark results in under an hour: `benchbox run --platform databricks --benchmark tpch --scale 0.01` creates tables, loads data, and applies Delta Lake tuning in one command."

**Good** (reproducible results):
> "Keep your result files in a working directory. When you scale from SF1 to SF10, ask: 'Compare my SF1 and SF10 runs and flag queries with more than 20% difference.' The MCP loads both result files and highlights data-volume-sensitive queries."

**Good** (MCP exploration):
> "Before committing to a full TPC-DS run, ask: 'How many queries are in TPC-DS, and what would running just queries 1, 3, and 7 cost in credits?' The MCP shows the 99-query breakdown and estimates resource consumption for your subset."

**Bad** (advocacy):
> "Snowflake's trial is stingy compared to competitors. You should start with BigQuery instead."

**Bad** (vague):
> "Make sure to manage your credits carefully and plan your testing accordingly."

---

## Research Summary

**Full research document**: [`research/platform-research.md`](../research/platform-research.md)

### Research Status (All Posts)

| Post | Platform | Trial | Pricing | BenchBox | Ready |
|------|----------|-------|---------|----------|-------|
| 0 | Intro | Done | Done | N/A | **Yes** |
| 1 | Snowflake | Done | Done | Done | **Yes** |
| 2 | Databricks | Done | Done | Done | **Yes** |
| 3 | BigQuery | Done | Done | Done | **Yes** |
| 4 | MotherDuck | Done | Done | Done | **Yes** |
| 5 | Redshift | Done | Done | Done | **Yes** |
| 6 | Starburst | Done | Partial | Done | **Yes** |
| 7 | ClickHouse | Done | Done | Done | **Yes** |
| 8 | Fabric | Done | Done | Done | **Yes** |
| 9 | Firebolt | Done | Partial | Done | **Yes** |

### Free Trial Comparison Table

| Platform | Credits | Duration | Constraint | $/Day |
|----------|---------|----------|------------|-------|
| Starburst Galaxy | $500 | 30 days | Credit | $16.67 |
| Snowflake | $400 | 30 days | Credit | $13.33 |
| Databricks | $400 | 14 days | Credit | $28.57 |
| BigQuery | $300 + 1TB/mo | 90 days + ongoing | Hybrid | $3.33 |
| Redshift Serverless | $300 | 90 days | Credit | $3.33 |
| ClickHouse Cloud | $300 | 30 days | Credit | $10.00 |
| Firebolt | $200 | 30 days | Credit | $6.67 |
| Microsoft Fabric | 64 CU | 60 days | Capacity | N/A |
| MotherDuck | 10 CU-hrs/mo | Ongoing | Capacity | N/A |

### Pricing Model Quick Reference

| Platform | Unit | Rate | Billing |
|----------|------|------|---------|
| Snowflake | Credit | $2-4/credit | Per-second (60s min) |
| Databricks | DBU | $0.15-0.55/DBU | Per-second |
| BigQuery | TB scanned | $6.25/TB | Per-query |
| MotherDuck | CU-hour | ~$0.25/CU-hr | Per-second |
| Redshift | RPU-hour | $0.36-0.60/RPU-hr | Per-second (60s min) |
| Starburst | Credit | Contact sales | Per-hour |
| ClickHouse | Compute | Per-minute | Per-minute |
| Fabric | CU | ~$0.18/CU-hr | Per-minute |
| Firebolt | FBU | Varies by region | Per-second |

### Stretch Posts (If Platform Trials Available)

| Platform | Credits | Duration | Notes |
|----------|---------|----------|-------|
| Azure Synapse | $200 | 30 days | Shared across all Azure services |
| Google Dataproc | $300 | 90 days | Shared across all GCP services |
| Athena | N/A | N/A | AWS Free Plan credits can be used |
| EMR Serverless | N/A | N/A | AWS Free Plan credits can be used |
| AWS Glue | 1M DPU-hrs | Ongoing | Generous free tier for testing |

---

## Integration with BenchBox

This series directly supports BenchBox users:

1. **Onboarding path**: New users can follow these guides to run their first cloud benchmarks
2. **Platform documentation**: Links from `docs/platforms/` to relevant trial guide
3. **Reproducible commands**: Every post uses `benchbox run` with exact flags
4. **Result comparison**: Readers can compare their results using MCP tools

### BenchBox MCP Workflow (Featured in Every Post)

Each post demonstrates the MCP-first workflow using natural language prompts. The AI assistant calls BenchBox tools behind the scenes.

**Before spending credits** (explore and validate):

| Prompt | What Happens |
|--------|--------------|
| "Which cloud platforms does BenchBox support?" | Shows available platforms, dependencies, configuration requirements |
| "What's in the TPC-H benchmark?" | Lists all 22 queries with descriptions |
| "What would a TPC-H SF1 run on Snowflake look like?" | Previews execution plan, estimates resource consumption |
| "Can I run TPC-DS on my current Databricks setup?" | Validates configuration, flags missing dependencies |

**After CLI execution** (analyze and compare):

| Prompt | What Happens |
|--------|--------------|
| "Show me my recent Snowflake benchmark runs" | Lists result files with timestamps and configurations |
| "What were the results of my last TPC-H run?" | Displays per-query timings, validation status, summary metrics |
| "Compare my SF1 and SF10 runs, flag anything over 20% different" | Side-by-side comparison highlighting regressions and improvements |
| "Why was Q21 6x slower in the DataFrame run?" | Retrieves query text, explains execution differences |

This conversational workflow surfaces in the post template sections:
- **Explore with MCP**: Pre-run validation
- **Reproducing and Comparing**: Post-run analysis

---

## Publishing Recommendation

### Recommendation: **Publish on the BenchBox blog**

**Rationale:**

1. **Tutorial/How-To content type**: The BenchBox Blog Style Guide explicitly lists "Tutorial/How-To" as a core content type for the BenchBox blog, with "Helpful, step-by-step, encouraging" tone.

2. **BenchBox-centric methodology**: Every post demonstrates BenchBox commands, configuration, and workflow. The content is fundamentally about using BenchBox on various platforms.

3. **Platform-neutral stance**: The series does NOT compare platforms or declare winners. Each post focuses on maximizing value from ONE platform's trial. This aligns with BenchBox's "Neutral on Platforms" voice requirement.

4. **Educational, not opinionated**: The content shares practical learnings ("here's what we discovered running TPC-H on Snowflake's trial"), not opinions ("Snowflake is better than Databricks").

5. **Community value**: Free trial optimization is a common challenge for data engineers evaluating platforms. Publishing under BenchBox positions the project as helpful to the broader community.

This series avoids platform-vs-platform opinions, vendor criticism, and "which should I choose?" takes. Each post stands alone as "how to benchmark Platform X during its free trial."

---

---

## Research Notes (Not for Publication)

### Key Sources by Platform

**Snowflake**: Official docs cover warehouse sizing (1-512 credits/hr), auto-suspend best practices (5-10 min), 60s billing minimum. Gen2 warehouses 1.25-1.35x credits but faster.

**Databricks**: Personal email limits (50 DBU/hr, no GPU) are the critical gotcha. All-Purpose compute is 3-4x more expensive than Jobs compute. Azure standard tier retiring Oct 2026.

**BigQuery**: Unique permanent free tier (1TB/mo) makes ongoing testing possible. LIMIT clause does NOT reduce bytes scanned. Partitioning/clustering can reduce costs 30-90%.

**MotherDuck**: Feb 2025 pricing update separated platform fee ($25-100/mo) from usage. Free tier (10 CU-hrs, 10GB) is generous for small-scale testing. Storage overage blocks queries.

**Redshift Serverless**: 90-day trial is longest. RPU rates vary significantly by region ($0.36-0.60/RPU-hr). Open transactions continue consuming RPUs (critical trap).

**Starburst Galaxy**: Most generous credits ($500) but specific $/credit rates require sales contact. Uses Trino protocol, same connector works.

**ClickHouse Cloud**: Jan 2025 pricing changes (~30% increase). Per-minute billing, idle timeout configurable. 20-30s resume time after idling.

**Fabric**: Capacity-based (throttled not stopped). 1 CU = 2 Spark VCores or 0.383 SQL VCores. Spark autoscale billing available (0.5 CU-hr per job).

**Firebolt**: FBU system (S=8, M=16 FBU). Per-second billing while engine running. Regional pricing differences (US vs non-US).

### Gaps Remaining

- Starburst specific credit-to-dollar rates (contact sales required)
- Firebolt specific $/FBU by region (pricing page lookup)
- Actual TPC-H credit consumption (requires running benchmarks on each platform)

### Counterarguments to Address

1. "Why not just use the pricing calculator?" - Calculators don't account for trial limitations, learning curve, or common mistakes
2. "Trials are just marketing" - True, but real evaluation still requires strategy to maximize value
3. "Just run locally with DuckDB" - Valid for learning, but doesn't test cloud-specific features (scaling, concurrency, managed infrastructure)

---

*Series created: 2026-01-30*
*Last updated: 2026-01-31*
*Research completed: 2026-01-31*
