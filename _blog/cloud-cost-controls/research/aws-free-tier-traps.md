# AWS Free Tier Traps and Gotchas - Research Notes

**Purpose**: Research for Post #6 in the Cloud Cost Controls series
**Focus**: Common mistakes and hidden costs specific to analytics/benchmarking use cases
**Date**: 2026-02-01

---

## 1. AWS Organizations and Free Tier

### Free Tier Eligibility Rules

**Key finding**: When an account joins an AWS Organization, Free Tier behavior changes significantly.

- **Aggregated usage**: An Organization can only benefit from Free Tier offers from ONE account. AWS aggregates usage across all accounts in the Organization to calculate Free Tier consumption.
  - Source: [AWS Free Tier FAQs](https://aws.amazon.com/free/free-tier-faqs/)

- **Eligibility start date**: For Organizations, Free Tier eligibility for all member accounts begins on the day the *management account* was created, not each member account.
  - Source: [AWS re:Post - Free Tier in AWS Organizations](https://repost.aws/questions/QUBTMYiaJwS-utI527pmLDkw/free-tier-in-aws-organizations-sub-account)

- **Only management account gets alerts**: For organizations, the management (payer) account can opt in to receive Free Tier usage alerts, but these alerts are not available to individual member accounts.
  - Source: [Tracking Free Tier Usage - AWS Billing](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/tracking-free-tier-usage.html)

- **Leaving doesn't help**: Leaving an AWS Organization will NOT reactivate or extend Free Tier benefits. The Free Tier period is a one-time offer tied to the account's activation date, regardless of organizational status.
  - Source: [AWS re:Post - Free tier with AWS Organization](https://repost.aws/questions/QUaTAcIgG0SsOLNQZUz_m_ow/free-tier-with-aws-organization)

- **Anti-fraud rule**: You are NOT eligible for any Free Tier Offers if you or your entity creates more than one account to receive additional benefits.
  - Source: [AWS Free Tier Terms](https://aws.amazon.com/free/terms/)

### Management Account vs Member Account Differences

**Critical SCP limitation**: SCPs (Service Control Policies) don't affect users or roles in the management account. They affect ONLY member accounts.

- "SCPs cannot restrict the management account of the organization. So do not use a management account for anything other than setting up organizations."
  - Source: [Service control policies (SCPs) - AWS Organizations](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps.html)

**Implication for benchmarking**: If you run benchmarks in your management account, you cannot use SCPs to limit spending. Only IAM policies on individual users/roles are available.

### Free Plan Account Upgrades (Post-July 2025)

A Free Plan account automatically upgrades to Paid Plan if you:
- Join AWS Organizations
- Set up AWS Control Tower landing zone
- Join AWS Partner Network
- Create a Professional Services contract
- Enroll in an Enterprise Agreement
- Purchase AWS Skill Builder Team subscription
- Designate the account as HIPAA or SEC compliant

Source: [Choosing an AWS Free Tier plan - AWS Billing](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html)

---

## 2. Common Free Tier Traps

### Services That Appear Free But Have Hidden Costs

#### Data Transfer Charges
- **Free Tier allowance**: 100 GB/month data transfer out globally (not per-region), aggregated across all AWS services
- **After free limit**: ~$0.09/GB for first 10 TB/month, with tiered discounts
- **First 1 GB/month to internet is always free**
- Source: [AWS Global Network FAQs](https://aws.amazon.com/about-aws/global-infrastructure/global-network/faqs/)

**Gotcha**: "The moment data leaves AWS, you pay."
- Source: [Hidden Costs of AWS Free Tier - Medium](https://medium.com/@pranavpurohit73/the-hidden-costs-of-awss-free-tier-no-one-talks-about-80be49189c55)

#### Data Transfer Between AZs/Regions
- **Cross-AZ**: $0.01-$0.02/GB - common gotcha for high-availability architectures
- **Cross-region**: NOT covered by Free Tier
- Source: [AWS Data Transfer Costs - Medium](https://medium.com/@ismailkovvuru/aws-data-transfer-costs-explained-stop-hidden-charges-from-draining-your-cloud-budget-938cd8202a24)

#### NAT Gateway
- **Hourly charge**: $0.045/hour (~$32.85/month) even with zero traffic
- **Data processing**: $0.045/GB processed through NAT Gateway
- **Total for internet traffic**: $0.045/GB (NAT) + $0.09/GB (data transfer OUT) = $0.135/GB
- "NAT Gateway costs $0.045 per hour - that's about $32 a month even if no one uses it."
- Source: [AWS NAT Gateway Pricing 2025](https://clustercost.com/blog/aws-nat-gateway-pricing-2025/)

**Mitigation**: Use Gateway VPC endpoints for S3/DynamoDB (free, no data processing charges)

#### Elastic IPs
- **As of February 2024**: $0.005 per IP per hour for ALL public IPv4 addresses, whether attached or not
- **Monthly cost for idle EIP**: ~$3.60/month
- "You are charged for all Elastic IP addresses in your account, regardless of whether they are associated or disassociated"
- Source: [EC2 On-Demand Instance Pricing](https://aws.amazon.com/ec2/pricing/on-demand/)

#### EBS Volumes on Stopped Instances
- "EC2 instances accrue charges only when they're running. However, EBS volumes that are attached to instances continue to retain information and accrue charges, even when an instance is stopped."
- EBS charges are for provisioned storage, not used storage
- Source: [Stop EBS charges for stopped instances - AWS re:Post](https://repost.aws/knowledge-center/ebs-charge-stopped-instance)

**Gotcha**: "Free Tier covers compute hours, but EBS storage still costs money if you leave volumes behind."

#### CloudWatch Logs
- **Free Tier**: 5 GB ingestion/month
- **Reality**: "For many high-growth engineering teams, logging is a hidden cost gotcha that often represents up to 30% of an entire monthly AWS bill"
- **Default retention**: Logs accumulate forever unless you set retention rules
- "Most log groups have no retention limit by default"
- Source: [Amazon CloudWatch Logs pricing - Hykell](https://hykell.com/kb/platform-specific-guides/aws-cloudwatch-logs-pricing/)

#### EBS Snapshots
- **Billed separately from volumes**: Deleting a volume does NOT delete associated snapshots
- **Incremental storage**: Snapshots only store changed blocks, but can accumulate
- **Gotcha**: "Deleting a snapshot might not reduce your organization's data storage costs. Other snapshots might reference that snapshot's data."
- Source: [Understand EBS snapshot billing - AWS re:Post](https://repost.aws/knowledge-center/ebs-snapshot-billing)

### Regional Pricing Differences

**Key finding**: There are substantial differences in AWS pricing among regions - 30-70% price differences compared to the cheapest region.

| Region | Typical Price Index | Notes |
|--------|---------------------|-------|
| US East (N. Virginia) | Lowest | Best selection, most AZs |
| US East (Ohio) | Very low | Good alternative |
| US West (Oregon) | Very low | Good alternative |
| EU (Ireland) | Low | Cheapest in Europe |
| South America (Sao Paulo) | 131% of base | Most expensive |
| India | 93% of base | Cheapest for EC2 |

- "For EC2, India offers the lowest price index at 93%, while Brazil is the most expensive at 131% - a 38 percentage point difference"
- Source: [AWS Regional Pricing - Opsima](https://www.opsima.ai/blog/aws-regional-costs)

**Free Tier and regions**: Free Tier credits apply globally, aggregated across all regions. However:
- China (ZHY/BJS) regions: Free Tier not available
- GovCloud (US) regions: Free Tier not available (except certain services like Lambda)
- Source: [AWS Free Tier FAQs](https://aws.amazon.com/free/free-tier-faqs/)

### Multi-Region Deployment Gotcha

"Free Tier quotas apply per account, not per region. If you deploy in two regions, you burn double the hours."
- Source: [CloudOptimo - AWS Free Tier Isn't Unlimited](https://www.cloudoptimo.com/blog/aws-free-tier-isnt-unlimited-know-the-limits-before-you-get-billed/)

---

## 3. Analytics-Specific Gotchas

### Redshift Serverless and Free Tier

**Free Trial (not Free Tier)**: $300 credit for 90 days
- Only if you've NEVER used Redshift Serverless before
- Credit does NOT apply to serverless reservations (only on-demand RPUs)
- Source: [Amazon Redshift Free Trial](https://aws.amazon.com/redshift/free-trial/)

**Provisioned cluster alternative**: 2-month free trial of DC2.Large node (750 hours/month)
- Source: [Amazon Redshift Pricing](https://aws.amazon.com/redshift/pricing/)

**Cost control**: Use Max RPU setting to cap on-demand usage
- Source: [Billing for Amazon Redshift Serverless](https://docs.aws.amazon.com/redshift/latest/mgmt/serverless-billing.html)

### Athena Free Tier Limits

**No Athena-specific Free Tier for data scanning**

- Athena charges $5 per TB scanned, always
- 10 MB minimum charge per query
- Canceled queries are still charged for data scanned before cancellation
- DDL statements (CREATE/ALTER/DROP) are free
- Failed queries are not charged
- Source: [Amazon Athena Pricing](https://aws.amazon.com/athena/pricing/)

**Related free tiers that help**:
- Glue Data Catalog: First 1M objects + 1M operations/month free
- Lambda (for federated queries): 1M invocations + 400K GB-seconds free
- Source: [AWS Glue Pricing](https://aws.amazon.com/glue/pricing/)

**Cost optimization**: Parquet + partitioning can reduce costs 30-90%

### EMR and Free Tier

**EMR itself is NOT part of AWS Free Tier**

- Charges per-second with 1-minute minimum
- Pay for EMR price + underlying EC2/EKS costs
- "Amazon EMR pricing is simple and predictable: you pay a per-second rate for every second you use"
- Source: [Amazon EMR Pricing](https://aws.amazon.com/emr/pricing/)

**Partial relief**: S3 storage for EMR input/output may be covered by S3 Free Tier (5 GB)

### AWS Glue

**Data Catalog Free Tier (Always Free)**:
- First 1 million objects stored: FREE
- First 1 million requests/month: FREE
- Beyond: $1.00 per 100,000 objects; $1.00 per 1M requests
- Source: [AWS Glue Pricing](https://aws.amazon.com/glue/pricing/)

**ETL Jobs and Crawlers - NO Free Tier**:
- ETL jobs: $0.44 per DPU-hour (1-second billing, 1-minute minimum)
- Crawlers: $0.44 per DPU-hour (1-second billing, 10-minute minimum)
- Development endpoints: No timeout, minimum 2 DPU, default 5 DPU
- Source: [AWS Glue Pricing](https://aws.amazon.com/glue/pricing/)

**Gotcha**: "Development endpoints do not time out" - can accumulate charges indefinitely
- Source: [AWS Glue Cost Traps - XTIVIA](https://www.xtivia.com/blog/aws-glue-cost-traps-pitfalls-mistakes/)

### S3 Storage Accumulation

**Free Tier (12-month)**:
- 5 GB Standard storage
- 20,000 GET requests
- 2,000 PUT requests
- 100 GB data transfer out
- Source: [Free Cloud Object Storage - AWS](https://aws.amazon.com/free/storage/s3/)

**Post-July 2025 accounts**: $200 in credits (applies to S3), valid for 12 months

**Benchmark data accumulation problem**:
- "Even if your application stops using S3, the stored data remains until deleted"
- Beyond 5 GB: $0.023/GB/month for Standard storage
- DELETE requests are FREE
- Source: [S3 Pricing](https://aws.amazon.com/s3/pricing/)

**Mitigation**:
- Use lifecycle rules to auto-delete after N days
- Regularly audit bucket storage
- Clean up after benchmark runs

### RDS Free Tier Limitations

**Free Tier (12-month)**:
- 750 hours/month of db.t2.micro, db.t3.micro, or db.t4g.micro
- Single-AZ only (Multi-AZ NOT included)
- 20 GB General Purpose SSD storage
- 20 GB backup storage
- Source: [Amazon RDS and AWS Free Tier](https://aws.amazon.com/rds/free/)

**Critical limitation**: "You receive 750 Micro DB Instance hours for free across ALL Regions, not 750 hours per Region"

**T3/T4g CPU credits gotcha**: "Amazon RDS for MySQL T4g and T3 DB instances run in Unlimited mode, which means that you will be charged if your average CPU utilization over a rolling 24-hour period exceeds the baseline of the instance. CPU Credits are charged at $0.075 per vCPU-Hour."
- Source: [Amazon RDS Pricing](https://aws.amazon.com/rds/pricing/)

---

## 4. Mitigation Strategies

### Dedicated Member Accounts for Benchmarking

**Recommendation**: Use a dedicated member account (not management account) for benchmark workloads.

**Benefits**:
- SCPs can apply (unlike management account)
- Clear cost attribution
- Easier cleanup
- Budget alerts specific to benchmarking

**Setup**:
1. Create new member account in Organization
2. Apply SCPs to restrict expensive services
3. Set up budget alerts
4. Use IAM policies for additional controls

### Cost Allocation Tags

**Best practices for benchmarking**:
- Tag all benchmark resources with `Environment: benchmark` or `Project: tpc-h`
- Activate cost allocation tags in Billing console
- Tags take up to 24 hours to appear in Cost Explorer
- Tags are NOT retroactive - only apply to future costs
- Source: [Organizing and tracking costs using AWS cost allocation tags](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/cost-alloc-tags.html)

**Recommended tags for benchmarks**:
| Tag Key | Example Value | Purpose |
|---------|---------------|---------|
| Environment | benchmark | Filter benchmark costs |
| Project | tpc-h-sf10 | Track specific benchmark runs |
| Owner | joe@example.com | Accountability |
| CostCenter | research | Chargeback |
| AutoDelete | 7d | Cleanup automation |

**Enforcement**: Use SCPs to require tags on resource creation
- Source: [Best Practices for Tagging AWS Resources](https://docs.aws.amazon.com/whitepapers/latest/tagging-best-practices/building-a-cost-allocation-strategy.html)

### Budget Alerts for Free Tier Accounts

**Three monitoring options**:

1. **Free Tier Usage Alerts** (automatic):
   - Enabled by default for individual accounts
   - NOT enabled by default for management accounts (must opt in)
   - Notifies at 85% of each service's Free Tier limit
   - Source: [Tracking Free Tier Usage](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/tracking-free-tier-usage.html)

2. **AWS Budgets** (recommended):
   - First 2 budgets free (up to 60 budget days/month)
   - Additional budgets: $0.02/day
   - Can create "zero spend budget" template
   - Source: [AWS Budgets](https://aws.amazon.com/aws-cost-management/aws-budgets/)

3. **CloudWatch Billing Alarms**:
   - Must enable billing alerts first
   - Metric data stored in us-east-1 only
   - Represents worldwide charges
   - Cannot filter by service, account, or tags
   - Source: [Create a billing alarm - CloudWatch](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/monitor_estimated_charges_with_cloudwatch.html)

**Recommended setup for benchmarking**:
1. Enable Free Tier usage alerts
2. Create $0 or $1 budget with email notifications
3. Set up budget action at $5 threshold to attach deny policy

### Regular Cleanup Practices

**Checklist for benchmark cleanup**:
- [ ] Terminate EC2 instances
- [ ] Delete unattached EBS volumes
- [ ] Delete EBS snapshots
- [ ] Release unassociated Elastic IPs
- [ ] Empty and delete S3 buckets
- [ ] Delete Glue databases/tables
- [ ] Delete NAT Gateways
- [ ] Remove CloudWatch log groups (or set retention)
- [ ] Delete VPC endpoints
- [ ] Clean up IAM roles/policies created for benchmarks

**CLI command to find unassociated Elastic IPs**:
```bash
aws ec2 describe-addresses --query "Addresses[?AssociationId==null]"
```

**Tools for cleanup**:
- cloud-nuke (Gruntwork): Bulk-delete resources in test accounts
- AWS Nuke: Open-source alternative
- Custom scripts with resource tagging

---

## 5. Timeline Issues

### 12-Month Free Tier Expiration

**What happens at expiration**:
- "After your eligibility expires, you're charged at the standard AWS billing rates for usage"
- "If no action is taken, your resources will continue to run, and you'll be automatically billed"
- Source: [Avoiding unexpected charges after Free Tier - AWS Billing](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/avoid-charges-after-free-tier.html)

**Cannot extend**: "You can't extend your Free Tier eligibility after this time"

**Always Free continues**: Lambda, DynamoDB, S3 (certain operations) continue at Always Free limits

### Always-Free vs Time-Limited Services

**Always Free (continue indefinitely)**:
| Service | Always Free Limit |
|---------|-------------------|
| Lambda | 1M requests + 400K GB-seconds/month |
| DynamoDB | 25 GB storage + 200M requests/month |
| S3 | 5 GB Standard storage (first 12 months only, then $0) |
| API Gateway | 1M REST API calls/month |
| SQS | 1M requests/month |
| SNS | 1M publishes/month |
| CloudFront | 1 TB data out + 10M requests/month |
| Glue Data Catalog | 1M objects + 1M operations/month |

Source: [Free Cloud Computing Services - AWS Free Tier](https://aws.amazon.com/free/)

**12-Month Free (then charged)**:
| Service | 12-Month Limit |
|---------|----------------|
| EC2 | 750 hours/month t2.micro/t3.micro |
| RDS | 750 hours/month micro instances |
| S3 | 5 GB storage + 20K GET + 2K PUT |
| Data Transfer | 100 GB out/month |
| CloudWatch | 10 custom metrics + 10 alarms |

**Short-Term Trials** (separate from Free Tier):
| Service | Trial Details |
|---------|---------------|
| Redshift Serverless | $300 credit for 90 days |
| Redshift Provisioned | 750 hours DC2.Large for 2 months |
| SageMaker | 250 hours/month for 2 months |

### July 2025 Free Tier Changes

**For accounts created BEFORE July 15, 2025**:
- Traditional 12-month Free Tier still applies
- Always Free services continue

**For accounts created AFTER July 15, 2025**:
- Choose between Free Plan or Paid Plan at signup
- $100 in credits automatically
- Additional $100 for completing onboarding tasks
- Credits valid for 12 months
- Free Plan duration: 6 months (then must upgrade or close)
- Source: [AWS Replaces the Free Tier - Medium](https://neal-davis.medium.com/aws-replaces-the-free-tier-how-the-new-credit-based-system-works-72d73a63f7c5)

---

## 6. Concrete Examples - Dollar Amounts

### Scenario 1: Forgotten EC2 Instance After Free Tier

**Setup**: t3.micro instance (2 vCPU, 1 GB RAM) in us-east-1
- **During Free Tier**: $0/month (within 750 hours)
- **After Free Tier**: $0.0104/hour × 730 hours = **$7.59/month**
- **With 20 GB EBS**: +$2.00/month (gp3)
- **Total**: ~**$10/month** for "free" instance

### Scenario 2: Accidental Instance Type

**Mistake**: Launch t2.medium instead of t2.micro
- t2.medium: $0.0464/hour
- 10 days running: 240 hours × $0.0464 = **$11.14**
- Source: Community example in search results

### Scenario 3: NAT Gateway Left Running

**Setup**: NAT Gateway in VPC for 1 month
- Hourly: $0.045 × 730 = $32.85
- If 10 GB data processed: $0.045 × 10 = $0.45
- **Total**: ~**$33/month** for unused NAT Gateway

### Scenario 4: Elastic IPs Not Released

**Setup**: 5 unassociated Elastic IPs
- Per EIP: $0.005/hour × 730 = $3.65/month
- **Total**: ~**$18/month** for unused IPs

### Scenario 5: CloudWatch Log Explosion

**Setup**: Application logging without retention policy
- Ingestion beyond 5 GB: $0.50/GB
- 100 GB ingestion/month: $47.50
- Storage (accumulating): $0.03/GB/month
- After 6 months with 100 GB/month: 600 GB × $0.03 = **$18/month storage alone**

### Scenario 6: S3 Benchmark Data Accumulation

**Setup**: TPC-H SF10 data in Parquet (~2.3 GB) left in S3
- First 5 GB free (12 months)
- After Free Tier: 2.3 GB × $0.023 = **$0.05/month** (minimal)
- But SF100 (~23 GB): 23 GB × $0.023 = **$0.53/month**
- SF1000 (~230 GB): 230 GB × $0.023 = **$5.29/month**

### Scenario 7: Athena Query Loop

**Setup**: Debug script running 100 queries on 100 GB table
- Each query scans full table: 100 GB × $0.005/GB = $0.50
- 100 queries: **$50 in query costs**
- No per-session aggregate limit to stop it

### Scenario 8: Real-World Horror Story

**Example from search**: "Our 'Free Tier' AWS Setup Cost $2,300 in Month 2"
- Source: [Medium Article](https://medium.com/@the_unwritten_algorithm/our-free-tier-aws-setup-cost-2-300-in-month-2-aa8d110cf697)
- Common causes: Multiple instances, data transfer, services outside Free Tier

### Scenario 9: RDS Multi-AZ Mistake

**Setup**: Create RDS instance with Multi-AZ enabled
- Multi-AZ is NOT covered by Free Tier
- db.t3.micro Multi-AZ: ~$0.034/hour
- Monthly: $24.82 (instead of $0)

### Scenario 10: Glue Development Endpoint

**Setup**: Development endpoint for ETL debugging
- Minimum 2 DPU
- Default 5 DPU
- **Does not auto-terminate**
- 5 DPU × 24 hours × $0.44 = **$52.80/day**
- Left for a week: **$369.60**

---

## Summary: Key Takeaways for Analytics Benchmarking

### Top 5 Free Tier Traps

1. **Organizations kill Free Tier sharing**: Usage is aggregated across all accounts; eligibility starts from management account creation date
2. **Management accounts can't use SCPs**: Your primary cost control tool is unavailable
3. **EBS charges when EC2 stops**: Storage costs continue even for stopped instances
4. **NAT Gateway hourly charges**: $33/month for an idle NAT Gateway
5. **No Athena/EMR Free Tier**: Analytics query costs start immediately

### Top 5 Mitigation Strategies

1. **Use dedicated member account**: Get SCP protection, clear cost attribution
2. **Set up $0 budget immediately**: Get alerts before any charges
3. **Tag everything**: Enable cost tracking and cleanup automation
4. **Set lifecycle policies**: Auto-delete S3 objects, CloudWatch logs
5. **Audit weekly**: Check for orphaned resources (EIPs, volumes, snapshots)

### Analytics-Specific Recommendations

| Service | Free Tier Status | Recommendation |
|---------|------------------|----------------|
| Redshift Serverless | $300 trial only | Use trial, set Max RPU |
| Athena | None | Use partitioned Parquet, set byte limits |
| EMR | None | Use Spot instances, terminate promptly |
| Glue ETL | None | Avoid dev endpoints, use local testing |
| Glue Catalog | 1M objects free | Safe for metadata |
| S3 | 5 GB/12 months | Clean up after benchmarks |

---

## Sources

### AWS Documentation
- [AWS Free Tier FAQs](https://aws.amazon.com/free/free-tier-faqs/)
- [Confirming eligibility to use AWS Free Tier](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-eligibility.html)
- [AWS Free Tier Terms](https://aws.amazon.com/free/terms/)
- [Service control policies (SCPs) - AWS Organizations](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps.html)
- [Avoiding unexpected charges after Free Tier](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/avoid-charges-after-free-tier.html)
- [Tracking your AWS Free Tier usage](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/tracking-free-tier-usage.html)

### Pricing Pages
- [Amazon Redshift Pricing](https://aws.amazon.com/redshift/pricing/)
- [Amazon Athena Pricing](https://aws.amazon.com/athena/pricing/)
- [Amazon EMR Pricing](https://aws.amazon.com/emr/pricing/)
- [AWS Glue Pricing](https://aws.amazon.com/glue/pricing/)
- [S3 Pricing](https://aws.amazon.com/s3/pricing/)
- [EC2 On-Demand Instance Pricing](https://aws.amazon.com/ec2/pricing/on-demand/)

### Community Resources
- [CostGoat AWS Free Tier Reference](https://github.com/costgoat/aws-free-tier)
- [Hidden Costs of AWS Free Tier - Medium](https://medium.com/@pranavpurohit73/the-hidden-costs-of-awss-free-tier-no-one-talks-about-80be49189c55)
- [AWS Free Tier Trap 2025 - Medium](https://suyash-jain.medium.com/aws-free-tier-trap-2025-whats-really-free-what-s-not-1f4b0d33d23a)
- [AWS Replaces the Free Tier - Medium](https://neal-davis.medium.com/aws-replaces-the-free-tier-how-the-new-credit-based-system-works-72d73a63f7c5)
- [AWS Glue Cost Traps - XTIVIA](https://www.xtivia.com/blog/aws-glue-cost-traps-pitfalls-mistakes/)

### AWS re:Post Discussions
- [Free Tier in AWS Organizations Sub-Account](https://repost.aws/questions/QUBTMYiaJwS-utI527pmLDkw/free-tier-in-aws-organizations-sub-account)
- [Free tier with AWS Organization](https://repost.aws/questions/QUaTAcIgG0SsOLNQZUz_m_ow/free-tier-with-aws-organization)
- [Stop EBS charges for stopped instances](https://repost.aws/knowledge-center/ebs-charge-stopped-instance)

---

*Research compiled: 2026-02-01*
*For: Cloud Cost Controls series, Post #6*
