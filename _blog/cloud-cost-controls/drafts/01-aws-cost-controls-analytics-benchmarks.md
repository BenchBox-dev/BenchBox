# AWS cost controls for analytics benchmarks

*Part 1 of the Cloud Cost Controls for Benchmarking series*

> Layered cost guardrails for Redshift Serverless, Athena, and EMR Serverless, using service-specific APIs that existing tools don't cover.

**TL;DR**: AWS analytics services each have usage-limit APIs that no existing cost-control tool wraps. Combining Redshift Serverless usage limits, Athena workgroup byte caps, and EMR Serverless max capacity with AWS Budget Actions creates layered protection suited to bursty benchmark workloads. We walk through the setup and provide a companion script.

*For series methodology, pricing scope, and cross-platform comparison, see the [series introduction](00-series-intro.md).*

---

## Why analytics benchmarks need different cost controls

Running TPC-H against AWS analytics services means navigating three pricing models simultaneously:

| Service             | Pricing model                    | Unit                | Example cost                                           |
| ------------------- | -------------------------------- | ------------------- | ------------------------------------------------------ |
| Redshift Serverless | Per-second billing (60s minimum) | RPU-hours           | 8 RPU base = costs accumulate whenever queries run[^1] |
| Athena              | Per-query scan volume            | $5/TB scanned       | `SELECT *` on 100GB = $0.50 per query[^2]              |
| EMR Serverless      | Per-worker-second                | $0.052624/vCPU-hour | 100 workers at 4 vCPU = ~$21/hour[^3]                  |

Traditional cost advice ("turn off instances at night") doesn't apply here. These services are serverless: they charge per-use, scale automatically, and have no instance to stop. A debug loop of 100 Athena queries can reach $50 before you notice. A forgotten Redshift connection accumulates RPU-hours in the background.

Standard AWS budget alerts don't help either. By the time you receive a notification, the spend has already occurred. Budget alerts are reactive; benchmark workloads need preventive controls.

We needed something different: controls that match how each service actually charges, applied at the service level before costs accumulate.

**A note on AWS Organizations**: When an account joins an AWS Organization, Free Tier eligibility is affected in ways that often surprise benchmark runners[^4]. We cover this in detail in Post 6 of this series, "The AWS Free Tier trap."

---

## What we evaluated

We looked at existing cost-control tools to see if any covered analytics services:

| Tool                        | Source    | What it covers                          | Gap for analytics benchmarks                                |
| --------------------------- | --------- | --------------------------------------- | ----------------------------------------------------------- |
| Budget Controls for AWS[^5] | AWS Labs  | EC2, RDS Aurora, SageMaker, OpenSearch  | No Redshift Serverless, Athena, or EMR Serverless           |
| Cloud Custodian[^6]         | CNCF      | 200+ resource types, off-hours policies | No service-specific usage limits (RPU-hours, bytes scanned) |
| cloud-nuke[^7]              | Gruntwork | Bulk-delete resources in test accounts  | All-or-nothing; no granular per-service controls            |
| AWS Budgets (native)        | AWS       | Account-wide spend alerts and actions   | No hard caps on individual services; alerts only            |

The gap is clear: AWS analytics services each expose their own usage-limit APIs. Redshift Serverless has `create-usage-limit`[^8], Athena has `BytesScannedCutoffPerQuery`[^9], and EMR Serverless has `maximumCapacity`. No existing tool wraps these APIs, yet they provide exactly the per-service hard caps that budget alerts lack.

IAM deny policies alone aren't sufficient either. A deny policy blocks creation of *new* resources, but a running Redshift workgroup continues accumulating RPU-hours regardless of IAM restrictions. Service-specific limits that halt operations mid-flight are needed alongside IAM controls.

---

## Layered cost controls

Our approach uses three layers, each addressing a different failure mode:

```text
+-----------------------------------------------------------+
|  Layer 3: Budget actions (account-wide backstop)          |
|  - IAM deny policy attached when budget threshold hit     |
|  - Blocks creation of new expensive resources             |
+-----------------------------------------------------------+
|  Layer 2: Budget alerts (early warning)                   |
|  - Email notifications at 50% and 80% of monthly budget  |
|  - Forecasted spend alerts                                |
+-----------------------------------------------------------+
|  Layer 1: Service-specific limits (hard caps)             |
|  - Redshift: Daily RPU-hour limit, deactivates workgroup  |
|  - Athena: Per-query byte scan cutoff, cancels query      |
|  - EMR Serverless: Max vCPU/memory capacity               |
+-----------------------------------------------------------+
```

**Why layers matter for benchmarks**:

- **Layer 1** bounds cost per-service per-day. A single benchmark run can't exceed the limit, regardless of how many queries execute or how long they take.
- **Layer 2** provides lead time. If cumulative spend trends above expectations, you get notified with time to adjust.
- **Layer 3** is the circuit breaker. When unexpected charges occur from services outside your controlled set, the budget action prevents further resource creation.

This pattern adapts to other clouds, GCP, Snowflake, and Azure each have analogous service-level controls, which we'll cover in follow-on posts.

---

## Service-specific limits

### Redshift Serverless

**Pricing model**: Per-second billing with a 60-second minimum[^1]. Base capacity starts at 8 RPU; costs accumulate whenever queries execute against the workgroup.

**Control**: The usage limits API offers three configurable breach actions[^8]:

- `log`, Record the breach to SYS_QUERY_HISTORY (default, no enforcement)
- `emit-metric`, Send a CloudWatch metric for alerting
- `deactivate`, Stop the workgroup entirely

```bash
$ aws redshift-serverless create-usage-limit \
    --resource-arn "arn:aws:redshift-serverless:us-east-1:123456789:workgroup/benchmark-wg" \
    --usage-type serverless-compute \
    --amount 13 \
    --period daily \
    --breach-action deactivate
```

**Behavior**: When daily RPU-hour consumption reaches the limit, the workgroup deactivates. All subsequent queries fail until the next billing period resets the counter (or you manually raise the limit).

**Trade-off for benchmarking**: A long benchmark run may be interrupted mid-execution. Size the limit above your expected workload. As a planning baseline, a single TPC-H SF10 power run on an 8-RPU workgroup typically consumes 2-4 RPU-hours. A 13 RPU-hour daily limit (roughly 3x a typical run) provides headroom for multiple runs plus debugging without leaving the workgroup uncapped.

### Athena

**Pricing model**: $5 per TB scanned[^2]. There is no native daily aggregate limit, controls are per-query only. Federated queries have a 10MB minimum charge regardless of actual scan volume.

**Control**: Workgroup configuration with `BytesScannedCutoffPerQuery`[^9]:

```bash
$ aws athena update-work-group \
    --work-group benchmarks \
    --configuration-updates '{
      "BytesScannedCutoffPerQuery": 53687091200,
      "EnforceWorkGroupConfiguration": true
    }'
```

This sets a 50GB per-query scan limit (53,687,091,200 bytes). The `EnforceWorkGroupConfiguration` flag ensures the limit applies even if individual queries attempt to override it.

**Behavior**: Queries that would scan more than 50GB are canceled immediately. Note that canceled queries are still charged for data scanned *before* cancellation[^9],the limit prevents runaway scans but isn't free.

**Trade-off for benchmarking**: Large unpartitioned table scans will fail against this limit. For TPC-H data, storing in columnar format (Parquet) with appropriate partition keys reduces scan volume significantly, AWS reports up to 75% cost reduction compared to CSV[^2]. We recommend creating a dedicated workgroup for benchmarks with an appropriate limit rather than modifying the default workgroup.

### EMR Serverless

**Pricing model**: Auto-scales by default. $0.052624 per vCPU-hour plus $0.0057785 per GB-hour for memory[^3], with 1-minute minimum billing per worker. At full scale, 100 workers with 4 vCPU each costs approximately $21 per hour.

**Control**: Application maximum capacity:

```bash
$ aws emr-serverless update-application \
    --application-id $APP_ID \
    --maximum-capacity '{"cpu": "8 vCPU", "memory": "32 GB"}'
```

**Behavior**: The application won't provision resources beyond the specified maximums. Jobs requesting more capacity will queue until resources become available or fail if they can't execute within the constraint.

**Trade-off for benchmarking**: Benchmark jobs that require parallelism beyond the cap will run slower (or not at all). Size the cap to your benchmark's actual requirements, for TPC-H at moderate scale factors, 8 vCPU is usually sufficient for sequential query execution.

### Lambda (supplementary)

For benchmark orchestration that uses Lambda functions:

```bash
$ aws lambda put-function-concurrency \
    --function-name benchmark-orchestrator \
    --reserved-concurrent-executions 10
```

This caps concurrent executions at 10. Excess invocations receive 429 throttle errors. Lambda's per-invocation cost is low ($0.0000166667/GB-second), but unbounded concurrency can still accumulate meaningful charges in burst scenarios.

---

## Budget actions as account-wide backstop

Service-specific limits cover the analytics services we're benchmarking, but they don't help with:

- EC2 instances (no native spending limit API)
- Services without usage-limit APIs (DynamoDB on-demand, Glue jobs, etc.)
- Unanticipated charges from services outside the benchmark scope

AWS Budget Actions fill this gap by automatically attaching an IAM deny policy when spend reaches a threshold.

**Creating the budget**:

```bash
$ aws budgets create-budget \
    --account-id $ACCOUNT_ID \
    --budget '{
      "BudgetName": "BenchmarkBudget",
      "BudgetLimit": {"Amount": "50", "Unit": "USD"},
      "BudgetType": "COST",
      "TimeUnit": "MONTHLY"
    }'
```

**The deny policy** (attached automatically at threshold):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Deny",
    "Action": [
      "ec2:RunInstances",
      "rds:CreateDBInstance",
      "redshift-serverless:CreateWorkgroup",
      "sagemaker:CreateNotebookInstance",
      "bedrock:InvokeModel"
    ],
    "Resource": "*"
  }]
}
```

After creating the budget and policy, a budget action links them:

- Create the deny policy in IAM
- Create a budget action that attaches the policy to your IAM user/role when actual spend reaches the threshold (e.g., 80% of monthly budget)
- The policy blocks *creation* of new expensive resources

**Important limitation**: This policy doesn't stop existing resources from charging. A running Redshift workgroup continues accumulating RPU-hours even after the deny policy is attached. This is why Layer 1 (service-specific limits) is the primary control, budget actions serve as the backstop for services that lack their own limit APIs.

---

## Putting it together

With all three layers configured, the complete setup for a $50/month benchmark budget looks like this:

```bash
# Layer 1: Service-specific limits
$ python scripts/aws_cost_limits.py --all --daily-spend 5

# Layer 2: Budget with email alerts at 50% and 80%
$ python scripts/aws_cost_limits.py --budget \
    --monthly-limit 50 \
    --email you@example.com

# Layer 3: IAM deny policy at 80% of budget
$ python scripts/aws_cost_limits.py --budget \
    --action deny-policy \
    --threshold 80
```

The companion script ([`scripts/aws_cost_limits.py`](https://github.com/benchbox/benchbox/blob/main/scripts/aws_cost_limits.py)) automates the AWS CLI calls described above for Redshift Serverless, Athena, EMR Serverless, and Lambda.

**Resulting protection**:

| Service             | Daily limit               | Enforcement            |
| ------------------- | ------------------------- | ---------------------- |
| Redshift Serverless | RPU-hour cap              | Workgroup deactivates  |
| Athena              | Per-query byte cap (50GB) | Query canceled         |
| EMR Serverless      | Max vCPU/memory           | Won't scale beyond cap |
| Lambda              | Concurrent execution cap  | Throttled (429)        |
| **Account-wide**    | **$50/month**             | **IAM deny at 80%**    |

Service limits bound per-day costs for each analytics service independently. The budget action catches charges from any service not covered by specific limits. Together, they make it unlikely that a benchmark session exceeds the monthly budget.

Apply these controls before running benchmarks. Use `benchbox run --dry-run ./preview --platform redshift --benchmark tpch` to validate configuration without incurring charges.

---

## Limitations

**What these controls don't cover**:

- **Data transfer**: Outbound transfer charges accumulate separately and have no usage-limit API.
- **S3 storage**: No per-bucket spending cap exists. Data generated during benchmarks persists until explicitly deleted.
- **Services without limit APIs**: DynamoDB on-demand, Glue jobs, and others lack configurable usage caps.
- **Root user actions**: The root user bypasses IAM policies entirely.

**AWS Organizations considerations**:

- If the benchmark account is the Organization *management* account, SCPs (Service Control Policies) don't apply to it. IAM policies on individual users/roles are the only control available.
- We recommend using a dedicated *member* account for benchmark workloads, where both IAM policies and SCPs provide defense in depth.

**When to use different approaches**:

| Scenario                          | Recommended approach                                 |
| --------------------------------- | ---------------------------------------------------- |
| Individual benchmarking           | Service-specific limits + budget actions (this post) |
| Team sandbox accounts             | Budget Controls for AWS[^5] + SCPs                   |
| Production benchmark environments | Cloud Custodian[^6] + organizational governance      |

---

## Conclusions

AWS analytics services charge per-use, RPU-hours, terabytes scanned, vCPU-hours, not per-instance. Standard cost advice and existing tools don't cover their specific usage-limit APIs.

**Key takeaways**:

1. Each AWS analytics service exposes its own usage-limit API. No existing cost-control tool wraps them, they require custom automation.
2. Layered defense (service limits → budget alerts → budget actions) provides both per-service precision and an account-wide backstop.
3. Service-specific limits are the primary control because they halt operations proactively. Budget actions are reactive and can't stop existing resources from charging.
4. The companion script [`scripts/aws_cost_limits.py`](https://github.com/benchbox/benchbox/blob/main/scripts/aws_cost_limits.py) automates setup for Redshift Serverless, Athena, EMR Serverless, and Lambda.

**Next steps**:

- Review your current service configurations: `python scripts/aws_cost_limits.py --list`
- Set limits appropriate to your benchmark workloads before the next run
- We'd welcome feedback on additional services to support, [open an issue](https://github.com/benchbox/benchbox/issues) to discuss

**Next in series**: GCP cost controls for BigQuery benchmarking, slot reservations, query quotas, and flat-rate pricing for predictable benchmark costs.

---

## References

[^1]: [Amazon Redshift Pricing](https://aws.amazon.com/redshift/pricing/), AWS. RPU-hour pricing, per-second billing with 60-second minimum.

[^2]: [Amazon Athena Pricing](https://aws.amazon.com/athena/pricing/), AWS. $5/TB scanned, 10MB minimum for federated queries, Parquet savings up to 75%.

[^3]: [Amazon EMR Pricing](https://aws.amazon.com/emr/pricing/), AWS. EMR Serverless: $0.052624/vCPU-hour, $0.0057785/GB-hour, 1-minute minimum.

[^4]: [AWS Free Tier FAQs](https://aws.amazon.com/free/free-tier-faqs/), AWS. Free Tier eligibility ends when an account joins an Organization.

[^5]: [Budget Controls for AWS](https://github.com/awslabs/budget-controls-for-aws), AWS Labs. Supports EC2, RDS Aurora, SageMaker, OpenSearch.

[^6]: [Cloud Custodian](https://cloudcustodian.io/), CNCF. Policy engine for 200+ AWS resource types.

[^7]: [cloud-nuke](https://github.com/gruntwork-io/cloud-nuke), Gruntwork. CLI tool for bulk-deleting resources in test accounts.

[^8]: [create-usage-limit, AWS CLI](https://docs.aws.amazon.com/cli/latest/reference/redshift-serverless/create-usage-limit.html), AWS. Breach action options: log, emit-metric, deactivate.

[^9]: [Configure data usage controls, Amazon Athena](https://docs.aws.amazon.com/athena/latest/ug/workgroups-setting-control-limits-cloudwatch.html), AWS. BytesScannedCutoffPerQuery, minimum 10MB.

---

*Questions or feedback? [Open an issue](https://github.com/benchbox/benchbox/issues) or join the discussion.*

---

**Status**: Draft
**Word Count**: 2295
**Created**: 2026-01-22
**Series**: Cloud Cost Controls for Benchmarking (Post 1: AWS)
