# Cloud cost controls for benchmarking

> Practical cost guardrails for running database benchmarks on AWS, GCP, Azure, Snowflake, and Databricks, with concrete dollar amounts and working CLI commands.

**TL;DR**: Cloud analytics services charge per-use (RPU-hours, terabytes scanned, credits, capacity units), not per-instance. Standard cost advice doesn't apply. This series covers service-specific cost controls for each major platform, following a consistent layered-defense pattern: hard limits at the service level, budget alerts for early warning, and account-wide backstops for unexpected charges.

---

## Who this series is for

Data engineers, database developers, and researchers running analytical benchmarks on cloud platforms. If you've ever been surprised by a cloud bill after a benchmark session, this series is for you.

We focus on the specific challenges of benchmarking workloads: bursty compute, large data volumes, and the "I'll delete that later" problem. This is not general FinOps advice.

---

## Series methodology

Each post follows a consistent approach:

- **Scope**: Cost-control configuration patterns for benchmark workflows, not formal performance benchmark reports.
- **Execution model**: BenchBox CLI with explicit phases (`load,power`) in non-interactive mode. Apply cost controls before running `benchbox run`.
- **Cost figures**: Modeled from vendor list prices in cited references, not invoice exports from a single account. List prices are illustrative public rates for primary US regions as of early 2026. Confirm regional pricing before running benchmarks.
- **Validation basis**: All CLI commands and configuration syntax validated against cited vendor documentation.

We use a layered defense pattern across all platforms:

1. **Layer 1: Service-specific limits** (hard caps that halt operations proactively)
2. **Layer 2: Budget alerts** (early warning when spend trends above expectations)
3. **Layer 3: Account-wide backstops** (circuit breakers for unexpected charges)

The relative strength of each layer varies by platform. Some platforms (Snowflake, AWS) offer native enforcement at all layers. Others (Databricks) have informational-only budgets, making Layer 1 critical.

---

## The posts

| # | Post | Platform | Key Insight |
|---|------|----------|-------------|
| 1 | [AWS cost controls for analytics benchmarks](01-aws-cost-controls-analytics-benchmarks.md) | Redshift Serverless, Athena, EMR Serverless | Service-specific usage-limit APIs that no existing tool wraps, plus Budget Actions as account-wide backstop |
| 2 | [GCP cost controls for BigQuery benchmarking](02-gcp-bigquery-cost-controls.md) | BigQuery | `maximum_bytes_billed` per query, custom quotas per project, Pub/Sub automation for budget enforcement |
| 3 | [Snowflake credit controls for testing](03-snowflake-credit-controls.md) | Snowflake | Resource monitors with suspend actions; 60-second auto-suspend minimum; right-sizing as cost lever |
| 4 | [Databricks cost controls for benchmarking](04-databricks-cost-controls.md) | Databricks | The only platform where budgets are purely informational; cluster policies become your primary defense |
| 5 | [Azure Synapse and Fabric cost controls](05-azure-synapse-fabric-cost-controls.md) | Synapse, Fabric | No auto-pause for dedicated pools; data processing limits for serverless; budget enforcement requires Logic Apps |
| 6 | [The AWS Free Tier trap](06-aws-free-tier-trap.md) | AWS (general) | Organizations aggregate Free Tier; analytics services have no Free Tier at all |

---

## Cross-platform comparison

| Aspect | AWS Redshift | GCP BigQuery | Snowflake | Databricks | Azure Synapse | Azure Fabric |
|--------|--------------|--------------|-----------|------------|---------------|--------------|
| Pricing unit | RPU-hours | Bytes scanned | Credits | DBU + cloud VM | DWU-hours / TB scanned | Capacity units |
| Can budget stop spending? | Yes (IAM deny) | Custom (Pub/Sub) | Yes (suspend) | **No** | Custom (Logic App) | Custom (Logic App) |
| Per-service hard limit | Usage limit API | max_bytes_billed + quota | Resource monitor | Cluster policy | Data processing limit (serverless) | None |
| Auto-shutdown | Manual | N/A | 60s minimum | Auto-termination | Manual (dedicated) | Manual |
| Minimum billing | 60 seconds | None | 60 seconds | Per-second | 1 hour (dedicated) | 1 minute |

---

## Reading guide

**New to cloud benchmarking?** Start with Post 1 (AWS) for the full layered-defense walkthrough, then read the post for your platform.

**Looking for a specific platform?** Jump directly to the relevant post. Each is self-contained.

**Setting up a benchmark account?** Read Post 6 (Free Tier trap) first to avoid common billing surprises.

All benchmark execution in this series uses BenchBox CLI. Use `benchbox run --dry-run` to validate configuration before incurring charges.

---

*Questions or feedback? [Open an issue](https://github.com/benchbox/benchbox/issues) or join the discussion.*

---

**Status**: Draft
**Created**: 2026-03-02
**Series**: Cloud Cost Controls for Benchmarking (Series Introduction)
