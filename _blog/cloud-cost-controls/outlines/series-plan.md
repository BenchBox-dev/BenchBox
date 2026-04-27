# "Cloud Cost Controls for Benchmarking" Content Plan

**Concept**: Practical cost management strategies for running database benchmarks and experiments on cloud platforms
**Audience**: Data engineers, database developers, researchers running benchmarks on AWS/GCP/Azure
**Tone**: Direct, data-grounded, educational with concrete dollar amounts (per BenchBox Blog Style Guide v2.0)
**Length**: 1,500-2,500 words
**Cadence**: Bi-weekly during series launch, then as-needed

## Series vision

Benchmarking databases means spinning up expensive resources, and forgetting to turn them off. This series provides **battle-tested cost control strategies** for anyone running experiments on cloud platforms. We're not covering general FinOps; we're focused on the specific challenges of benchmarking workloads: bursty compute, large data volumes, and the "I'll delete that later" problem.

**Key differentiator**: Concrete dollar amounts, working CLI commands, and automation scripts for each cloud platform's analytics services, not general FinOps advice.

## Post template

### Structure

1. **The Problem** (~200 words)
   - Specific cost trap or challenge
   - Real-world scenario with dollar impact

2. **The Solution** (~800 words)
   - Step-by-step implementation
   - CLI commands or infrastructure-as-code
   - Configuration examples

3. **The Trade-offs** (~300 words)
   - What this approach costs you (flexibility, time, complexity)
   - When NOT to use this approach

4. **The Numbers** (~200 words)
   - Concrete cost comparisons
   - Before/after examples
   - Break-even analysis where applicable

5. **Implementation** (~400 words)
   - Ready-to-use scripts or configs
   - Links to tools/resources
   - Common pitfalls

### Metadata template

```yaml
title: "{Topic}: {Specific Technique}"
series: cloud-cost-controls
post_number: N
date: YYYY-MM-DD
tags: [cost-management, aws, benchmarking, {specific-service}, finops]
```

## Planned posts

| #   | Title                                         | Status       | Key Insight                                                         | Notes                                      |
| --- | --------------------------------------------- | ------------ | ------------------------------------------------------------------- | ------------------------------------------ |
| 1   | AWS cost controls for analytics benchmarks    | **DRAFTED**  | Service-specific limits + Budget Actions provide layered protection | Establishes pattern for series             |
| 2   | GCP cost controls for BigQuery benchmarking   | **DRAFTED**  | $6.25/TB on-demand; custom quotas + max_bytes_billed for control    | ~2,100 words; follows AWS pattern          |
| 3   | Snowflake credit controls for testing         | **DRAFTED**  | Resource monitors with suspend actions; 60s auto-suspend minimum    | ~2,300 words; credit-based controls        |
| 4   | Databricks cost controls for benchmarking     | **DRAFTED**  | Cluster policies, DBU limits; budgets don't stop spending (critical gap) | ~2,200 words                              |
| 5   | Azure Synapse and Fabric cost controls        | **DRAFTED**  | DWU caps, Fabric CU, pause/resume; budgets need automation          | ~2,200 words                              |
| 6   | The AWS Free Tier trap                        | **DRAFTED**  | Organizations aggregate Free Tier; no analytics Free Tier           | ~1,600 words                              |
| 7   | Budget Actions: the emergency brake you need  | IDEA         | IAM deny policies on budget threshold are the nuclear option        | When alerts aren't enough                  |
| 8   | Existing tools: what works and what doesn't   | IDEA         | Cloud Custodian, Budget Controls for AWS, cloud-nuke                | Tool comparison for cost control           |
| 9   | Multi-cloud cost governance patterns          | IDEA         | Common patterns across AWS/GCP/Azure/Snowflake                      | Series synthesis                           |

### Status definitions

- **DRAFTING**: Draft in progress (`drafts/`)
- **OUTLINE**: Full outline complete, ready for draft (`outlines/`)
- **PLANNED**: Concept defined, needs research and outline
- **IDEA**: Topic identified, needs scoping

## Key themes

### 1. Layered Defense
No single control is sufficient. Effective cost management requires:
- Service-specific limits (Redshift RPU, Athena bytes)
- Budget alerts (early warning)
- Budget actions (automatic response)
- Manual review cadence

### 2. Analytics Services Are Different
Traditional EC2/RDS cost advice doesn't apply to serverless analytics:
- Redshift Serverless charges per-RPU-hour, not instance-hour
- Athena charges per-TB scanned, regardless of query time
- EMR Serverless has worker-minute billing
- These require different controls than "turn off instances at night"

### 3. Existing Tools Have Gaps
Most cost control tools (Cloud Custodian, AWS Budget Controls) focus on:
- EC2 instances
- RDS databases
- General tagging/governance

They don't understand:
- Redshift Serverless usage limits API
- Athena workgroup byte caps
- EMR Serverless max capacity
- These require custom automation (which we provide)

### 4. Concrete Numbers, Not Vague Advice
Every post includes:
- Specific dollar amounts
- Hourly/daily/monthly cost calculations
- Break-even analysis
- "If you run X for Y hours, expect $Z"

## Series tone examples

**Good** (data-first, specific):
> "A Redshift Serverless workgroup at 4 RPU base capacity costs $1.44/hour whenever queries are running. An open connection left overnight accumulates $17.28 in charges."

**Good** (concrete, educational):
> "Athena charges $5 per terabyte scanned. A `SELECT *` on a 100GB table costs $0.50. A debug loop of 20 iterations reaches $10, with no per-session aggregate limit to stop it."

**Good** (factual, neutral):
> "When an account joins an AWS Organization, Free Tier eligibility ends immediately. This is worth knowing before setting up a dedicated benchmark account."

**Bad** (vague, no data):
> "Cloud costs can add up quickly, so it's important to monitor your spending and implement appropriate controls."

**Bad** (passive, no specifics):
> "Consider setting up budget alerts to stay informed about your spending patterns."

## Post #1 outline: AWS cost controls for analytics benchmarks

### The problem
Running TPC-H against Redshift Serverless, Athena, and EMR means navigating three pricing models simultaneously. How do we set up controls that match how each service charges?

### Key findings
1. **Service-specific limits are your first line of defense**
   - Redshift Serverless: 13 RPU-hours/day = ~$5/day max
   - Athena: 50GB per-query limit = ~$0.25/query max
   - EMR Serverless: Max capacity = bounded concurrent cost

2. **AWS Budgets alone aren't enough**
   - Alerts are reactive (damage already done)
   - Budget Actions can auto-respond but are coarse-grained

3. **The layered approach**
   - Layer 1: Service-specific hard limits
   - Layer 2: Budget alerts at 50%, 80%
   - Layer 3: Budget Actions (IAM deny) at 100%

4. **Existing tools don't cover analytics services**
   - Budget Controls for AWS: EC2, RDS, SageMaker, OpenSearch
   - Cloud Custodian: General tagging/policy
   - Our script: Redshift Serverless, Athena, EMR Serverless, Lambda

### Narrative arc
1. Start with the problem: Three analytics pricing models, no unified controls
2. Survey the landscape: What existing tools are available?
3. Identify the gap: Analytics services need custom controls
4. Present the solution: Layered defense with service-specific limits
5. Add the backstop: Budget Actions as account-wide circuit breaker
6. Conclude with working example: Complete setup with companion script

### Research completed
- [x] AWS Organizations / Free Tier interaction documented
- [x] Evaluated Budget Controls for AWS (awslabs)
- [x] Evaluated Cloud Custodian capabilities
- [x] Built aws_cost_limits.py companion script
- [x] Tested on AWS account
- [x] Documented pricing models for each analytics service

### Artifacts
- `scripts/aws_cost_limits.py` - Full script with CLI
- Cost calculation tables for each service
- Architecture diagram of layered defense
- Step-by-step setup commands

### Open questions
- Should we include the full script or link to GitHub?
- How much detail on the research into existing tools?
- Include GCP/Azure comparison or save for separate posts?

---

## Integration with BenchBox

This series directly supports BenchBox users:

1. **Pre-benchmark setup**: Run cost controls before `benchbox run --platform redshift-serverless`
2. **Cloud platform docs**: Link from platform documentation to relevant cost control post
3. **MCP integration**: Could add cost limit commands to BenchBox MCP server
4. **Community value**: Addresses a frequent challenge for anyone benchmarking on cloud

---

## Research sources

### Primary Research (Our Experience)
- AWS account 189864065035 setup and cost analysis
- Building and testing aws_cost_limits.py
- AWS Health notification on Free Tier expiration

### External Tools Evaluated
- [Budget Controls for AWS](https://github.com/awslabs/budget-controls-for-aws) - AWS Labs
- [Cloud Custodian](https://cloudcustodian.io/) - CNCF
- [cloud-nuke](https://github.com/gruntwork-io/cloud-nuke) - Gruntwork
- [aws-spending-limits](https://github.com/ryanpeach/aws-spending-limits) - Community

### AWS Documentation
- [AWS Budgets Actions](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-controls.html)
- [Redshift Serverless Usage Limits](https://docs.aws.amazon.com/redshift/latest/mgmt/serverless-usage-limits.html)
- [Athena Workgroup Settings](https://docs.aws.amazon.com/athena/latest/ug/workgroups-settings.html)
- [EMR Serverless Application Configuration](https://docs.aws.amazon.com/emr/latest/EMR-Serverless-UserGuide/application-capacity.html)

---

## Progress tracker

| Milestone | Status | Date |
|-----------|--------|------|
| Series plan created | Done | 2026-01-22 |
| Post #1 research | Done | 2026-01-22 |
| Post #1 outline | Done | 2026-01-22 |
| Post #1 draft | Done | 2026-01-22 |
| Post #2 (GCP) outline | Done | 2026-01-31 |
| Post #2 (GCP) research | Done | 2026-01-31 |
| Post #3 (Snowflake) outline | Done | 2026-01-31 |
| Post #3 (Snowflake) research | Done | 2026-01-31 |
| Post #2 draft | Done | 2026-01-31 |
| Post #3 draft | Done | 2026-01-31 |
| Post #4 (Databricks) research | Done | 2026-02-01 |
| Post #4 (Databricks) outline | Done | 2026-02-01 |
| Post #5 (Azure) research | Done | 2026-02-01 |
| Post #5 (Azure) outline | Done | 2026-02-01 |
| Post #6 (Free Tier) research | Done | 2026-02-01 |
| Post #6 (Free Tier) outline | Done | 2026-02-01 |
| Post #4 draft | Done | 2026-02-01 |
| Post #5 draft | Done | 2026-02-01 |
| Post #6 draft | Done | 2026-02-01 |
| Posts #1-6 critique | Done | 2026-02-01 |
| Posts #1-6 revisions | Done | 2026-02-01 |
| Series intro (Post 0) | Done | 2026-03-02 |
| Posts #1-6 second critique + fixes | Done | 2026-03-02 |

---

*Series created: 2026-01-22*
*Last updated: 2026-03-02 (second critique, series intro, and cross-cutting fixes)*
