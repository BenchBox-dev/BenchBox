# Use-Case Examples

**Real-world patterns for common BenchBox scenarios**

This directory contains complete, production-ready examples demonstrating how to solve specific real-world problems with BenchBox.

## Philosophy

- **Problem-focused**: Each example solves a specific real-world problem
- **Production-ready**: Copy-paste into your workflows
- **Best practices**: Demonstrates recommended patterns
- **Complete solutions**: End-to-end workflows, not fragments

## Available Use Cases

### 1. CI/CD Regression Testing ([ci_regression_test.py](ci_regression_test.py))
**Problem:** Automatically detect performance regressions in pull requests

**Solution:** Lightweight benchmark with baseline comparison

**Key Features:**
- Fast execution (< 30 seconds)
- Clear pass/fail criteria
- GitHub Actions integration
- Baseline management

**Usage:**
```bash
python use_cases/ci_regression_test.py --save-baseline baseline.json

python use_cases/ci_regression_test.py --baseline baseline.json
```

Generate the baseline once on the main branch with the first command. Run the second command in CI to test for regressions.

**See also:** [ci_regression_test_github.yml](ci_regression_test_github.yml) for GitHub Actions workflow

---

### 2. Platform Evaluation ([platform_evaluation.py](platform_evaluation.py))
**Problem:** Choose the right database platform for your workload

**Solution:** Systematic comparison across multiple platforms

**Key Features:**
- Side-by-side performance comparison
- Cost estimation
- Platform-specific notes
- Decision criteria

**Usage:**
```bash
python use_cases/platform_evaluation.py --platforms duckdb,sqlite

python use_cases/platform_evaluation.py --platforms duckdb,databricks,bigquery --dry-run
```

The first command evaluates local platforms. The second adds cloud platforms.

---

### 3. Incremental Tuning ([incremental_tuning.py](incremental_tuning.py))
**Problem:** Systematically optimize database performance

**Solution:** Iterative optimization workflow with tracking

**Key Features:**
- Round-by-round optimization
- Improvement tracking
- Multiple optimization strategies
- Tuning report generation

**Usage:**
```bash
python use_cases/incremental_tuning.py

python use_cases/incremental_tuning.py --scale 1.0
```

The first command runs the full tuning workflow. The second uses a custom scale factor.

---

### 4. Cost Optimization ([cost_optimization.py](cost_optimization.py))
**Problem:** Minimize cloud platform costs

**Solution:** Cost-saving strategies and estimates

**Key Features:**
- Dry-run validation
- Query subset selection
- Scale factor optimization
- Cost estimation by platform

**Usage:**
```bash
python use_cases/cost_optimization.py --platform bigquery --dry-run

python use_cases/cost_optimization.py
```

The first command previews costs. The second shows cost strategies.

---

## When to Use Each Pattern

**CI/CD Regression Testing**
- Pull request validation
- Nightly performance tests
- Release gate criteria
- SLA monitoring

**Platform Evaluation**
- Database migration decisions
- New project platform selection
- Cost vs performance trade-offs
- Vendor comparison

**Incremental Tuning**
- Performance optimization
- Query optimization
- Capacity planning
- Benchmarking tuning changes

**Cost Optimization**
- Cloud budget management
- Development cost reduction
- Test environment optimization
- POC/demo cost control

## Integration Patterns

### GitHub Actions
Add this step to `.github/workflows/performance.yml`.

```yaml
- name: Performance Test
  run: python use_cases/ci_regression_test.py --baseline baseline.json
```

### GitLab CI
Add this job to `.gitlab-ci.yml`.

```yaml
performance_test:
  script:
    - python use_cases/ci_regression_test.py --baseline baseline.json
```

### Jenkins
Add this stage to your `Jenkinsfile`.

```groovy
stage('Performance Test') {
    sh 'python use_cases/ci_regression_test.py --baseline baseline.json'
}
```

## Tips

1. **Start Simple**: Begin with ci_regression_test.py for quick wins
2. **Measure First**: Run platform_evaluation before migrations
3. **Iterate**: Use incremental_tuning for systematic optimization
4. **Watch Costs**: Use cost_optimization for cloud platforms
5. **Customize**: These are templates - adapt to your needs

## Next Steps

- **Feature Examples**: See [features/](../features/) for individual capabilities
- **Programmatic API**: See [programmatic/](../programmatic/) for library usage
- **Patterns**: See [PATTERNS.md](../PATTERNS.md) for workflow combinations

---

**Remember:** These examples are production-ready templates. Copy and modify them for your specific needs.
