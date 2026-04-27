# AWS Cost Control Tools Research

**Date**: 2026-01-22
**Purpose**: Evaluate existing tools for cost control to avoid reinventing the wheel

---

## Tools Evaluated

### 1. Budget Controls for AWS (awslabs)

**Source**: https://github.com/awslabs/budget-controls-for-aws

**What it does**:
- Tag-based resource governance
- AWS Config monitors for required tags
- Step Function orchestrates actions on budget breach
- Supports: EC2, RDS Aurora, SageMaker notebooks/domains, OpenSearch

**How it works**:
1. Deploy CloudFormation template
2. Set budget amount
3. Resources auto-tagged with `BudgetControlAction` = `Inform` | `Stop` | `Terminate`
4. At 80%: email alert
5. At 90%: execute actions based on tags

**Limitations**:
- Single-region deployment
- No Redshift Serverless support
- No Athena support
- No EMR Serverless support
- No service-specific usage limits (just stop/terminate)
- Actions execute once (can't prevent resource recreation)

**Verdict**: Good for EC2/RDS/SageMaker, but doesn't cover analytics services we need.

---

### 2. Cloud Custodian

**Source**: https://cloudcustodian.io/ | https://github.com/cloud-custodian/cloud-custodian

**What it does**:
- CNCF project, policy-as-code engine
- 200+ AWS resource types supported
- YAML DSL for policies
- Can run on Lambda, scheduled, or event-triggered

**Example policy**:
```yaml
policies:
  - name: stop-unused-ec2
    resource: ec2
    filters:
      - type: metrics
        name: CPUUtilization
        days: 4
        value: 0.5
        op: lt
    actions:
      - stop
```

**Capabilities**:
- Off-hours resource management
- Garbage collection of unused resources
- Tagging enforcement
- Cost optimization via termination/stopping

**Limitations**:
- Steeper learning curve
- Requires infrastructure setup (Lambda, CloudWatch Events)
- No native "daily spend cap" concept
- Doesn't use service-specific limit APIs (Redshift RPU, Athena bytes)

**Verdict**: Powerful but overkill for simple cost protection. Doesn't fill our specific gap.

---

### 3. cloud-nuke (Gruntwork)

**Source**: https://github.com/gruntwork-io/cloud-nuke

**What it does**:
- CLI tool to delete all resources in an account
- Time-based filtering (`--older-than 1h`)
- Used for test account cleanup

**Use case**: "We run cloud-nuke every 3 hours in the automated testing account and every 24 hours in the manual testing account. This cut our monthly spending in half."

**Safety features**:
- Dry-run by default
- Requires explicit `--no-dry-run` flag

**Limitations**:
- Nuclear option - deletes everything matching criteria
- Not for production
- Not granular cost control

**Verdict**: Good for test account cleanup, not for ongoing cost limits.

---

### 4. aws-nuke (rebuy-de)

**Source**: https://github.com/rebuy-de/aws-nuke

**What it does**:
- Similar to cloud-nuke but more comprehensive
- Configuration-file based
- Account alias required for safety

**Verdict**: Same category as cloud-nuke. Cleanup tool, not limit tool.

---

### 5. aws-spending-limits (Community)

**Source**: https://github.com/ryanpeach/aws-spending-limits

**What it does**:
- EventBridge + Step Functions + CodeBuild
- Triggers aws-nuke on budget threshold
- Automated cleanup when spending exceeds limit

**Status**: DRAFT - "Use at your own risk"

**Verdict**: Interesting concept but immature. Nuclear option triggered by budget.

---

### 6. AWS Budgets (Native)

**What it does**:
- Budget thresholds with alerts
- Budget Actions can:
  - Apply IAM policy
  - Apply SCP (member accounts only)
  - Run SSM documents (stop EC2)

**Limitations**:
- Alerts are reactive (spending already happened)
- Actions are coarse-grained (account-wide)
- No service-specific hard limits

**Verdict**: Essential layer but not sufficient alone.

---

## Gap Analysis

| Capability | Budget Controls | Cloud Custodian | Our Script |
|------------|----------------|-----------------|------------|
| Redshift Serverless RPU limits | ❌ | ❌ | ✅ |
| Athena per-query byte limits | ❌ | ❌ | ✅ |
| EMR Serverless max capacity | ❌ | ❌ | ✅ |
| Lambda concurrency limits | ❌ | ❌ | ✅ |
| EC2 stop/terminate | ✅ | ✅ | Via Budget Actions |
| RDS stop/terminate | ✅ | ✅ | ❌ |
| SageMaker control | ✅ | ✅ | ❌ |
| Daily per-service caps | ❌ | ❌ | ✅ |
| Budget Actions integration | ❌ | ❌ | ✅ |

---

## Conclusion

**Our script fills a real gap**: Analytics services (Redshift Serverless, Athena, EMR Serverless) have service-specific limit APIs that no existing tool leverages.

**Recommended approach**:
1. Use our script for analytics service limits
2. Use Budget Controls for AWS if you need EC2/RDS/SageMaker governance
3. Use Cloud Custodian if you need comprehensive policy engine
4. Use cloud-nuke for periodic test account cleanup

**Hybrid setup for benchmarking**:
```
Layer 1: aws_cost_limits.py --all (service-specific limits)
Layer 2: AWS Budgets alerts (early warning)
Layer 3: aws_cost_limits.py --budget --action deny-policy (emergency brake)
```

---

## Sources

- [Budget Controls for AWS - GitHub](https://github.com/awslabs/budget-controls-for-aws)
- [Budget Controls for AWS - AWS Blog](https://aws.amazon.com/blogs/aws-cloud-financial-management/introducing-budget-controls-for-aws-automatically-manage-your-cloud-costs/)
- [Cloud Custodian Documentation](https://cloudcustodian.io/docs/)
- [Cloud Custodian GitHub](https://github.com/cloud-custodian/cloud-custodian)
- [cloud-nuke GitHub](https://github.com/gruntwork-io/cloud-nuke)
- [cloud-nuke Blog - 85% Cost Reduction](https://blog.gruntwork.io/cloud-nuke-how-we-reduced-our-aws-bill-by-85-f3aced4e5876)
- [aws-spending-limits GitHub](https://github.com/ryanpeach/aws-spending-limits)

---

*Research completed: 2026-01-22*
