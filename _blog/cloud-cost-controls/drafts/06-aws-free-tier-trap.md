# The AWS Free Tier trap

*Part 6 of the Cloud Cost Controls for Benchmarking series*

> When "free" isn't free: AWS Organizations, analytics services with no Free Tier, and the hidden costs that surprise benchmark runners.

**TL;DR**: AWS Free Tier isn't independent per-member-account once you join an Organization: usage and effective benefits are organization-scoped. Most analytics services (Athena, EMR, Redshift Serverless) have no Free Tier at all. And common resources like NAT Gateways and Elastic IPs charge even when you think they're free.

*For series methodology, pricing scope, and cross-platform comparison, see the [series introduction](00-series-intro.md).*

---

## The surprise: your "new" account isn't new

"I set up a fresh AWS account for benchmarking, so I should have 12 months of Free Tier, right?"

Often not, if your account joined an AWS Organization.

In Organizations, Free Tier usage is aggregated at the payer (management) account level for billing purposes[^1]. While each member account's Free Tier eligibility is based on its own creation date, the usage allowances (e.g., 750 hours of t2.micro) are shared across all accounts in the Organization, not allocated independently to each one. In practice, that means a newly created benchmark member account may have little or no usable Free Tier runway if other accounts have already consumed the allowance.

| Scenario | Free Tier Status |
|----------|------------------|
| Standalone account created January 2026 | 12 months of Free Tier |
| Member account created January 2026 in an existing Organization | **May have reduced or no effective Free Tier runway** |

### Free Tier is aggregated, not per-account

An Organization can only benefit from Free Tier offers from ONE account. AWS aggregates usage across all accounts to calculate consumption[^2].

**Example**: If your Organization has 5 member accounts, and the Free Tier allows 750 hours of t2.micro per month, those 750 hours are shared across all 5 accounts, not 750 hours each.

### Leaving doesn't help

Leaving an AWS Organization does not create a new Free Tier window. Free Tier plans are time-bound and one-time for an account plan lifecycle[^3][^10].

### Management accounts can't use SCPs

Here's a critical limitation for cost control: Service Control Policies (SCPs) don't affect users or roles in the management account[^4]. They only affect member accounts.

**What this means**: If you run benchmarks in your management account, you cannot use SCPs to limit spending. Only IAM policies on individual users/roles are available, and those are easier to misconfigure.

**Recommendation**: Use a dedicated member account for benchmarks. You get SCP protection, clear cost attribution, and easier cleanup.

---

## Analytics services have no Free Tier

The most common misconception we encounter: "AWS has a Free Tier, so my analytics benchmarks are free."

Most analytics services have NO Free Tier:

| Service | Free Tier Status | Cost From Day One |
|---------|------------------|-------------------|
| Athena | **None** | $5/TB scanned[^5] |
| EMR | **None** | Per-second + EC2 costs[^6] |
| Redshift Serverless | $300 trial only (90 days) | After trial: RPU-hour billing |
| Glue ETL/Crawlers | **None** | $0.44/DPU-hour[^7] |
| Glue Data Catalog | 1M objects free (Always Free) | Safe for metadata |

### Athena: no per-session limit

Athena charges $5 per TB scanned. There's no Free Tier and no per-session aggregate limit.

**The scenario**: Debug script running 100 queries on a 100GB table:
- Each query scans full table: 100 GB × $0.005/GB = $0.50
- 100 queries: **$50 in query costs**
- Nothing stops this automatically

**Mitigation**: Use `BytesScannedCutoffPerQuery` in your workgroup settings, and store data in partitioned Parquet format.

### EMR: not covered by EC2 Free Tier

"EMR is just EC2, so Free Tier covers it."

No. EMR charges two separate fees:
- **EMR fee**: Per-second with 1-minute minimum
- **EC2 fee**: Instance costs (and EMR typically needs larger instances than t2.micro)

The Free Tier t2.micro hours don't make a dent in typical EMR workloads.

### Glue interactive sessions trap

Glue interactive sessions (which replaced the now-deprecated development endpoints) can also accumulate charges:

- Default 5 DPU for Spark sessions
- Sessions time out after idle period (configurable, default 60 minutes)
- 5 DPU × $0.44/DPU-hour = **$2.20/hour** while active
- A full day of forgotten sessions: **$52.80**

The idle timeout helps, but if you're actively iterating on ETL logic, the session stays alive. Monitor active sessions in the Glue console and terminate when done.

---

## Resources that charge when "free"

Several AWS resources charge even when you think they're stopped or unused.

### NAT Gateway: the most common trap

**Trap**: "I'm not sending traffic, so the NAT Gateway is free."

**Reality**:
- Hourly charge: $0.045/hour even with zero traffic
- Data processing: $0.045/GB
- Monthly cost: **~$33/month** for an idle NAT Gateway

NAT Gateways are required for private subnets to access the internet (for package updates, etc.), so they're easy to create and forget.

**Mitigation**: Delete NAT Gateways when not needed. Use VPC endpoints for S3 and DynamoDB (free, no data processing charges).

### Elastic IPs: changed February 2024

**Trap**: "Elastic IPs are free if attached to a running instance."

**Reality (since February 2024)**:
- $0.005 per IP per hour for ALL public IPv4 addresses
- Whether attached to an instance or not
- Monthly cost: **~$3.65/month per EIP**
- 5 unassociated EIPs: **$18/month**[^8]

This changed in February 2024. Previously, EIPs attached to running instances were free. Now all public IPv4 addresses are charged.

**Mitigation**: Release EIPs immediately after terminating instances. Use IPv6 where possible.

### EBS volumes on stopped instances

**Trap**: "I stopped the instance, so I'm not being charged."

**Reality**: EBS volumes charge for provisioned storage, not instance state[^9]:
- 20 GB gp3: ~$2/month
- Volumes persist until explicitly deleted
- Snapshots also accumulate charges

**Mitigation**: Delete volumes when terminating instances. Set up lifecycle policies or cleanup scripts.

### CloudWatch Logs: infinite retention by default

**Trap**: "CloudWatch Logs has a Free Tier."

**Reality**:
- 5 GB ingestion/month free
- **Default retention: Never** (logs accumulate forever)
- Storage: $0.03/GB/month
- After 6 months at 100 GB/month ingestion: 600 GB × $0.03 = **$18/month in storage alone**

**Mitigation**: Set retention policies on all log groups (7-30 days for benchmarks).

---

## Concrete cost examples

### Scenario 1: "Free" EC2 after Free Tier expires

- t3.micro: $0.0104/hour × 730 hours = $7.59/month
- Plus 20 GB EBS: $2/month
- **Total: ~$10/month** for what you thought was a free instance

### Scenario 2: NAT Gateway left running

- Hourly: $0.045 × 730 hours = $32.85/month
- 10 GB data processed: $0.45
- **Total: ~$33/month** for an unused NAT Gateway

### Scenario 3: Athena debug loop

- 100 queries on 100GB table
- **Total: $50** in query costs
- No automatic limit to stop it

### Scenario 4: S3 benchmark data accumulation

- TPC-H SF100 (~23 GB Parquet) left in S3
- After Free Tier: 23 GB × $0.023 = **$0.53/month**
- TPC-H SF1000 (~230 GB): **$5.29/month**

Not huge, but it accumulates across multiple benchmark runs if you don't clean up.

### Scenario 5: RDS Multi-AZ mistake

- Create RDS db.t3.micro with Multi-AZ enabled
- Multi-AZ is NOT covered by Free Tier
- **~$25/month** instead of $0

The UI checkbox is easy to miss.

---

## Post-July 2025 changes

For accounts created after July 15, 2025, AWS uses a different model:

- **Free Plan**: $200 in credits, 6-month duration
- **Paid Plan**: Standard pay-as-you-go

Joining an AWS Organization automatically upgrades a Free Plan account to Paid Plan[^10]. This means new accounts get less runway than the traditional 12-month Free Tier.

If your account was created before July 15, 2025, the traditional Free Tier rules still apply. Check your account's plan type in the AWS Billing console under "Free Tier" to confirm which model applies to you.

---

## Mitigation strategies

### 1. Use dedicated member accounts

Create a member account in your Organization specifically for benchmarks:
- SCPs can apply (unlike management account)
- Clear cost attribution
- Easier cleanup
- Budget alerts specific to benchmarking

### 2. Set up $0 budget immediately

```bash
aws budgets create-budget \
  --account-id $ACCOUNT_ID \
  --budget '{
    "BudgetName": "ZeroSpendAlert",
    "BudgetLimit": {"Amount": "1", "Unit": "USD"},
    "BudgetType": "COST",
    "TimeUnit": "MONTHLY"
  }'
```

Get alerts before any significant charges accumulate.

### 3. Tag everything

| Tag Key | Example Value | Purpose |
|---------|---------------|---------|
| Environment | benchmark | Filter benchmark costs |
| Project | tpc-h-sf10 | Track specific runs |
| Owner | you@example.com | Accountability |
| AutoDelete | 7d | Cleanup automation |

Tags enable cost tracking in Cost Explorer and support cleanup automation.

### 4. Weekly audit for orphaned resources

```bash
# Find unassociated Elastic IPs
aws ec2 describe-addresses --query "Addresses[?AssociationId==null]"

# Find unattached EBS volumes
aws ec2 describe-volumes --filters "Name=status,Values=available"

# Find log groups without retention
aws logs describe-log-groups --query "logGroups[?retentionInDays==null]"
```

Run these checks weekly, or set up CloudWatch alarms for them.

### 5. Use cleanup tools

- **cloud-nuke** (Gruntwork): Bulk-delete resources in test accounts, Go-based CLI
- **aws-nuke** (ekristen): Actively maintained fork for targeted resource cleanup
- Custom scripts with resource tagging

These tools are designed for test and sandbox accounts. For dedicated benchmark accounts, periodic cleanup runs can catch forgotten resources. Always review the dry-run output before executing deletions.

---

## Analytics-specific recommendations

For analytics benchmarks, accept that you'll pay from day one: Athena, EMR, and Glue ETL have no Free Tier at all. Before running anything, set up the service-specific limits from [Post 1 (AWS cost controls)](01-aws-cost-controls-analytics-benchmarks.md): Redshift Serverless usage limits, Athena workgroup byte caps, and EMR Serverless max capacity. Clean up benchmark data in S3 after each run to avoid ongoing storage charges.

---

## Limitations

- Free Tier policy details can change; always verify your current account/organization state in AWS Billing before assuming eligibility.
- List-price examples do not include enterprise discounts, Savings Plans, or private pricing agreements.
- This post focuses on common benchmark failure modes, not every AWS service-specific edge case.
- Control recommendations assume you can use member accounts and IAM role-based access; management-account constraints may require additional governance work.

---

## Conclusions

**Key takeaways**:

1. **Organizations aggregate Free Tier** across all accounts. Your "new" benchmark account may have no Free Tier left if the management account is old.

2. **Analytics services have no Free Tier**. Athena, EMR, and Glue ETL charge from the first query.

3. **Management accounts can't use SCPs**. Use a dedicated member account for benchmarks to get SCP protection.

4. **NAT Gateways, Elastic IPs, and EBS volumes** charge even when you think they're free or stopped.

5. **Set up $0 budget alerts immediately** and audit for orphaned resources weekly.

The pattern: Know what's actually free, set up alerts before you start, and clean up promptly.

---

## Series summary

This post concludes our core platform coverage of cost controls for benchmarking. The series has covered:

1. **AWS**: Redshift Serverless usage limits, Athena workgroup caps, Budget Actions
2. **GCP**: BigQuery maximum_bytes_billed, custom quotas, Pub/Sub automation
3. **Snowflake**: Resource monitors with suspend actions, auto-suspend configuration
4. **Databricks**: Cluster policies (the only platform where budgets don't stop spending)
5. **Azure**: Synapse pause/resume, Fabric capacity controls, data processing limits
6. **AWS Free Tier**: Organizations aggregation, analytics services with no Free Tier

The consistent pattern across all platforms: layered defense with service-specific limits as your primary control, aggregate budgets as early warning, and account-wide backstops for unexpected charges.

Future posts may explore multi-cloud governance patterns and deeper dives into specific cost scenarios.

---

## References

[^1]: [AWS Free Tier FAQs](https://aws.amazon.com/free/free-tier-faqs/), AWS. Free Tier usage in Organizations is aggregated.

[^2]: [Managing costs with AWS Organizations](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_introduction.html), AWS. Organization-level billing and account structure context.

[^3]: [Choosing an AWS Free Tier plan](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html), AWS. Free plan/Paid plan model and duration.

[^4]: [Service control policies (SCPs)](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps.html), AWS. SCPs don't affect management account.

[^5]: [Amazon Athena Pricing](https://aws.amazon.com/athena/pricing/), AWS. $5/TB scanned.

[^6]: [Amazon EMR Pricing](https://aws.amazon.com/emr/pricing/), AWS. Per-second billing.

[^7]: [AWS Glue Pricing](https://aws.amazon.com/glue/pricing/), AWS. $0.44/DPU-hour.

[^8]: [EC2 On-Demand Instance Pricing](https://aws.amazon.com/ec2/pricing/on-demand/), AWS. February 2024 EIP pricing change.

[^9]: [Amazon EBS Pricing](https://aws.amazon.com/ebs/pricing/), AWS. EBS is billed for provisioned storage regardless of instance running state.

[^10]: [Choosing an AWS Free Tier plan](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html), AWS. Post-July 2025 changes.

---

*Questions or feedback? [Open an issue](https://github.com/benchbox/benchbox/issues) or join the discussion.*

---

**Status**: First Draft
**Word Count**: 2193
**Created**: 2026-02-01
**Series**: Cloud Cost Controls for Benchmarking (Post 6: AWS Free Tier)
