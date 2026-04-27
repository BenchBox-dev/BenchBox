# The AWS Free Tier trap

> When "free" isn't free: AWS Organizations, analytics services with no Free Tier, and the hidden costs that surprise benchmark runners.

**Series**: Cloud Cost Controls for Benchmarking
**Post Number**: 6 (AWS Free Tier)
**Target Length**: 1,500-2,000 words (shorter, focused post)
**Status**: OUTLINE COMPLETE - READY FOR DRAFT

---

## Metadata

```yaml
title: "The AWS Free Tier trap"
slug: aws-free-tier-trap
series: cloud-cost-controls
post_number: 6
tags: [aws, free-tier, cost-management, organizations, benchmarking, gotchas]
```

---

## Thesis

> AWS Free Tier isn't per-account when you join an Organization, analytics services like Athena, Redshift Serverless, and EMR have no Free Tier at all, and common resources (NAT Gateways, Elastic IPs, EBS volumes) accumulate charges even when you think they're free. Here's what to watch for.

---

## Series context

This post complements the AWS cost controls post (#1) by covering preventive knowledge: what surprises catch benchmark runners before they set up controls.

| Trap | Impact |
|------|--------|
| Organizations aggregate Free Tier | Your "new" account isn't new |
| No analytics Free Tier | Athena, EMR, Glue ETL cost from day one |
| NAT Gateway hourly charge | $33/month for an idle NAT |
| Management account SCPs | Primary cost control tool unavailable |

---

## Outline

### 1. Introduction (~250 words)

**Hook**: "I set up a fresh AWS account for benchmarking, so I should have 12 months of Free Tier, right?" Not if your account joined an AWS Organization. Free Tier eligibility starts from the management account creation date, not yours.

**The problem**: Several aspects of AWS Free Tier surprise benchmark runners:
- Organizations aggregate Free Tier across all accounts
- Analytics services (Athena, EMR, Redshift Serverless) have no Free Tier
- Common resources charge even when "stopped" or "unused"
- Management accounts can't use SCPs (your primary cost control tool)

**What this post covers**:
1. How AWS Organizations affects Free Tier
2. Analytics services with no Free Tier
3. Resources that charge when you think they're free
4. Mitigation strategies for benchmark accounts

### 2. AWS Organizations and Free Tier (~400 words)

#### Free Tier is aggregated, not per-account

**Key finding**: An Organization can only benefit from Free Tier offers from ONE account. AWS aggregates usage across all accounts to calculate Free Tier consumption[^1].

**Eligibility starts from management account**: For Organizations, Free Tier eligibility for all member accounts begins on the day the management account was created, not each member account[^2].

**Example scenario**:
- Management account created: January 2024
- Member account created: January 2026
- Free Tier eligibility for member account: Expired (12 months from Jan 2024)

#### Leaving doesn't help

Leaving an AWS Organization will NOT reactivate or extend Free Tier benefits. The Free Tier period is a one-time offer tied to the account's activation date[^3].

#### Management account can't use SCPs

**Critical limitation**: SCPs (Service Control Policies) don't affect users or roles in the management account[^4]. They only affect member accounts.

**Implication for benchmarking**: If you run benchmarks in your management account, you cannot use SCPs to limit spending. Only IAM policies on individual users/roles are available.

**Recommendation**: Use a dedicated member account for benchmarks to get SCP protection.

#### Post-July 2025 changes

For accounts created after July 15, 2025:
- Free Plan: $200 in credits, 6-month duration
- Joining an Organization upgrades Free Plan to Paid Plan automatically[^5]

### 3. Analytics services with no Free Tier (~400 words)

**Common misconception**: "AWS has a Free Tier, so my analytics benchmarks are free."

**Reality**: Most analytics services have NO Free Tier:

| Service | Free Tier Status | Cost From Day One |
|---------|------------------|-------------------|
| Athena | None | $5/TB scanned[^6] |
| EMR | None | Per-second + EC2 costs[^7] |
| Redshift Serverless | $300 trial only (90 days) | After trial: RPU-hour billing |
| Glue ETL/Crawlers | None | $0.44/DPU-hour[^8] |
| Glue Data Catalog | 1M objects free (Always Free) | Safe for metadata |

#### Athena gotcha

100 queries on a 100GB table:
- Each query scans full table: 100 GB × $0.005/GB = $0.50
- 100 queries: **$50 in query costs**
- No per-session aggregate limit to stop it

**Mitigation**: Use partitioned Parquet data, set BytesScannedCutoffPerQuery in workgroup.

#### EMR gotcha

"EMR is just EC2, so Free Tier covers it."

No. EMR charges:
- EMR fee: Per-second with 1-minute minimum
- EC2 fee: Instance costs (may overlap Free Tier t2.micro, but EMR needs larger instances)
- Storage: EBS volumes for HDFS

#### Glue dev endpoint trap

Development endpoints for ETL debugging:
- Minimum 2 DPU, default 5 DPU
- **Does not auto-terminate**
- 5 DPU × 24 hours × $0.44 = **$52.80/day**
- Left for a week: **$369.60**[^9]

### 4. Resources that charge when "free" (~400 words)

#### NAT Gateway (most common trap)

**Trap**: "I'm not sending traffic, so it's free."

**Reality**:
- Hourly charge: $0.045/hour even with zero traffic
- Monthly cost: **~$33/month** for an idle NAT Gateway
- Plus: $0.045/GB data processing

**Mitigation**: Delete NAT Gateways when not needed. Use VPC endpoints for S3/DynamoDB (free).

#### Elastic IPs (changed February 2024)

**Trap**: "Elastic IPs are free if attached to a running instance."

**Reality (since February 2024)**:
- $0.005 per IP per hour for ALL public IPv4 addresses
- Whether attached or not
- Monthly cost: **~$3.65/month per EIP**
- 5 unassociated EIPs: **$18/month**

**Mitigation**: Release EIPs immediately after terminating instances.

#### EBS volumes on stopped instances

**Trap**: "I stopped the instance, so I'm not being charged."

**Reality**: EBS volumes charge for provisioned storage, not used storage[^10]:
- 20 GB gp3: ~$2/month
- Volumes persist until explicitly deleted

**Mitigation**: Delete volumes when terminating instances (or set up lifecycle automation).

#### CloudWatch Logs accumulation

**Trap**: "CloudWatch Logs has a Free Tier."

**Reality**:
- 5 GB ingestion/month free
- Default retention: **Never** (logs accumulate forever)
- Storage: $0.03/GB/month
- 6 months at 100 GB/month: 600 GB × $0.03 = **$18/month storage alone**

**Mitigation**: Set retention policies on log groups (7-30 days for benchmarks).

### 5. Concrete cost examples (~300 words)

**Scenario 1: "Free" EC2 after Free Tier expires**
- t3.micro: $0.0104/hour × 730 hours = $7.59/month
- Plus 20 GB EBS: $2/month
- **Total: ~$10/month** for "free" instance

**Scenario 2: NAT Gateway left running**
- Hourly: $0.045 × 730 = $32.85/month
- **Total: ~$33/month** for unused NAT

**Scenario 3: Athena debug loop**
- 100 queries on 100GB table
- **Total: $50** in query costs

**Scenario 4: S3 benchmark data accumulation**
- SF100 TPC-H (~23 GB Parquet)
- After Free Tier: 23 GB × $0.023 = **$0.53/month**
- SF1000 (~230 GB): **$5.29/month**

**Scenario 5: RDS Multi-AZ mistake**
- db.t3.micro with Multi-AZ enabled
- Multi-AZ is NOT covered by Free Tier
- **~$25/month** instead of $0

### 6. Mitigation strategies (~300 words)

#### Use dedicated member accounts

- Create member account in Organization for benchmarks
- SCPs can apply (unlike management account)
- Clear cost attribution
- Easier cleanup

#### Set up $0 budget immediately

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

#### Tag everything

| Tag Key | Example Value | Purpose |
|---------|---------------|---------|
| Environment | benchmark | Filter benchmark costs |
| Project | tpc-h-sf10 | Track specific runs |
| AutoDelete | 7d | Cleanup automation |

#### Weekly audit for orphaned resources

```bash
# Find unassociated Elastic IPs
aws ec2 describe-addresses --query "Addresses[?AssociationId==null]"

# Find unattached EBS volumes
aws ec2 describe-volumes --filters "Name=status,Values=available"

# Find log groups without retention
aws logs describe-log-groups --query "logGroups[?retentionInDays==null]"
```

#### Use cleanup tools

- **cloud-nuke** (Gruntwork): Bulk-delete resources in test accounts
- **AWS Nuke**: Open-source alternative
- Custom scripts with resource tagging

### 7. Conclusion (~150 words)

**Key takeaways**:

1. **Organizations aggregate Free Tier** across all accounts. Your "new" benchmark account may have no Free Tier left.

2. **Analytics services have no Free Tier**. Athena, EMR, and Glue ETL charge from day one.

3. **Management accounts can't use SCPs**. Use a dedicated member account for benchmarks.

4. **NAT Gateways, Elastic IPs, and EBS volumes** charge even when you think they're free.

5. **Set up $0 budget alerts immediately** and audit for orphaned resources weekly.

**The pattern**: Know what's actually free, set up alerts before you start, and clean up promptly.

---

## References

[^1]: [AWS Free Tier FAQs](https://aws.amazon.com/free/free-tier-faqs/) - AWS. Free Tier aggregation in Organizations.

[^2]: [Free Tier in AWS Organizations Sub-Account](https://repost.aws/questions/QUBTMYiaJwS-utI527pmLDkw/free-tier-in-aws-organizations-sub-account) - AWS re:Post. Eligibility start date.

[^3]: [Free tier with AWS Organization](https://repost.aws/questions/QUaTAcIgG0SsOLNQZUz_m_ow/free-tier-with-aws-organization) - AWS re:Post. Leaving doesn't restore eligibility.

[^4]: [Service control policies (SCPs)](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps.html) - AWS. SCPs don't affect management account.

[^5]: [Choosing an AWS Free Tier plan](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html) - AWS. Post-July 2025 changes.

[^6]: [Amazon Athena Pricing](https://aws.amazon.com/athena/pricing/) - AWS. $5/TB scanned.

[^7]: [Amazon EMR Pricing](https://aws.amazon.com/emr/pricing/) - AWS. Per-second billing.

[^8]: [AWS Glue Pricing](https://aws.amazon.com/glue/pricing/) - AWS. $0.44/DPU-hour.

[^9]: [AWS Glue Cost Traps](https://www.xtivia.com/blog/aws-glue-cost-traps-pitfalls-mistakes/) - XTIVIA. Dev endpoint trap.

[^10]: [Stop EBS charges for stopped instances](https://repost.aws/knowledge-center/ebs-charge-stopped-instance) - AWS re:Post. EBS charging behavior.

[^11]: [EC2 On-Demand Instance Pricing](https://aws.amazon.com/ec2/pricing/on-demand/) - AWS. February 2024 EIP pricing change.

---

*Outline created: 2026-02-01*
*Research completed: 2026-02-01*
*Status: OUTLINE COMPLETE - READY FOR DRAFT*
