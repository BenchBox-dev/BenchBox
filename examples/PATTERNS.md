# Common BenchBox Patterns

**Reusable workflow patterns for common use cases**

This guide shows proven patterns for common benchmarking workflows. Each pattern includes complete code examples, explanations, and best practices. Copy and adapt these patterns for your specific needs.

---

## Table of Contents

1. [Pattern 1: Quick Local Testing](#pattern-1-quick-local-testing)
2. [Pattern 2: Cloud Dry-Run Workflow](#pattern-2-cloud-dry-run-workflow)
3. [Pattern 3: Production Benchmarking](#pattern-3-production-benchmarking)
4. [Pattern 4: Performance Regression Testing](#pattern-4-performance-regression-testing)
5. [Pattern 5: Multi-Platform Evaluation](#pattern-5-multi-platform-evaluation)
6. [Pattern 6: Incremental Performance Tuning](#pattern-6-incremental-performance-tuning)
7. [Pattern 7: Targeted Query Testing](#pattern-7-targeted-query-testing)
8. [Pattern 8: Cost-Optimized Cloud Testing](#pattern-8-cost-optimized-cloud-testing)

---

## Pattern 1: Quick Local Testing

**When to use:** Fast iteration during development, testing integrations, learning BenchBox

**Time:** 1-5 minutes

**Cost:** Free (local execution)

### Overview

Use DuckDB with minimal data to test changes quickly without cloud costs or setup complexity.

### Complete Example

```python
"""Quick local testing pattern for fast iteration."""

from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH

def quick_test():
    """Run TPC-H at tiny scale for rapid testing."""

    # Use very small scale for speed
    benchmark = TPCH(
        scale_factor=0.01,  # ~10MB data, generates in seconds
        output_dir="./benchmark_runs/quick_test",
        verbose=True,
    )

    # Generate data (cached after first run)
    data_files = benchmark.generate_data()
    print(f"✓ Generated {len(data_files)} data files")

    # Use in-memory database for maximum speed
    adapter = DuckDBAdapter(database_path=":memory:")

    # Run benchmark
    results = adapter.run_benchmark(benchmark, test_execution_type="power")

    # Check success
    success = results.successful_queries == results.total_queries
    print(f"✓ {'PASS' if success else 'FAIL'}: {results.successful_queries}/{results.total_queries} queries succeeded")
    print(f"✓ Total time: {results.total_execution_time:.2f}s")

    return success

if __name__ == "__main__":
    raise SystemExit(0 if quick_test() else 1)
```

### Key Points

- **Scale Factor 0.01**: Generates ~10MB data in seconds
- **In-Memory**: Use `:memory:` for fastest execution
- **Caching**: Data generation is cached, subsequent runs are instant
- **Exit Code**: Return 0/1 for CI integration

### Variations

**Even Faster (2-3 specific queries):**
```python
# Run only queries 1 and 6 for 10-second tests
results = adapter.run_benchmark(
    benchmark,
    test_execution_type="power",
    query_subset=["1", "6"]
)
```

**Persistent Database (for reuse):**
```python
# Save database to reuse across runs
adapter = DuckDBAdapter(database_path="./test_databases/tpch_sf001.duckdb")
```

### Common Issues

- **Data regeneration**: Use `force_regenerate=False` (default) to use cached data
- **Memory usage**: SF 0.01 uses <100MB RAM; increase cautiously
- **Query failures**: Check `results.failed_queries` for details

---

## Pattern 2: Cloud Dry-Run Workflow

**When to use:** Before cloud execution, validating configuration, previewing costs

**Time:** 1-3 minutes

**Cost:** Free (no cloud execution)

### Overview

Preview exactly what will run on cloud platforms without spending credits or requiring active credentials.

### Complete Example

```python
"""Cloud dry-run pattern to preview before execution."""

from pathlib import Path
from benchbox.core.config import BenchmarkConfig, DatabaseConfig
from benchbox.examples import execute_example_dry_run

def preview_bigquery_benchmark():
    """Preview TPC-H benchmark on BigQuery without execution."""

    # Define benchmark configuration
    benchmark_config = BenchmarkConfig(
        name="tpch",
        display_name="TPC-H Power Test",
        scale_factor=1.0,  # Preview at production scale
        options={
            "enable_preflight_validation": True,
        },
        test_execution_type="power",
    )

    # Define BigQuery platform configuration
    database_config = DatabaseConfig(
        type="bigquery",
        name="benchbox_tpch",
        options={
            "project_id": "${BIGQUERY_PROJECT}",  # Shows required env vars
            "dataset": "benchbox_benchmarks",
            "location": "US",
        },
    )

    # Execute dry-run (no cloud resources created)
    output_dir = Path("./dry_run_preview/bigquery_tpch_sf1")
    execute_example_dry_run(
        benchmark_config=benchmark_config,
        database_config=database_config,
        output_dir=output_dir,
        filename_prefix="bigquery_tpch",
    )

    print(f"\n✓ Dry-run complete! Preview artifacts in: {output_dir}")
    print("  - Configuration: bigquery_tpch.json")
    print("  - Configuration: bigquery_tpch.yaml")
    print("  - Queries: bigquery_tpch_queries_*/*.sql")
    print("  - Schema: bigquery_tpch_schema_*.sql")
    print("\nReview before running for real!")

if __name__ == "__main__":
    preview_bigquery_benchmark()
```

### Output Artifacts

Dry-run creates these files for review:

```
dry_run_preview/bigquery_tpch_sf1/
├── bigquery_tpch.json              # Configuration + metadata
├── bigquery_tpch.yaml              # Human-readable config
├── bigquery_tpch_queries_20250112_143022/
│   ├── query_01.sql
│   ├── query_02.sql
│   └── ... (all 22 queries)
└── bigquery_tpch_schema_20250112_143022.sql  # DDL statements
```

### Key Benefits

1. **Preview Queries**: Review SQL before execution
2. **Verify Configuration**: Check all settings are correct
3. **Cost Estimation**: Use query files with platform cost estimators
4. **No Credentials**: Works without active cloud credentials
5. **Documentation**: Artifacts serve as execution documentation

### Using Dry-Run Outputs

**Cost Estimation (BigQuery):**
```bash
# Use BigQuery CLI to estimate query costs
bq query --dry_run < dry_run_preview/bigquery_tpch_sf1/bigquery_tpch_queries_*/query_01.sql
```

**Schema Review:**
```bash
# Review schema DDL before creating tables
cat dry_run_preview/bigquery_tpch_sf1/bigquery_tpch_schema_*.sql
```

**Approval Workflow:**
```bash
# Check in dry-run artifacts for team review
git add dry_run_preview/bigquery_tpch_sf1/
git commit -m "Add BigQuery TPC-H benchmark preview for approval"
```

---

## Pattern 3: Production Benchmarking

**When to use:** Official performance evaluation, comparing databases, publication-quality results

**Time:** 30 minutes - 2+ hours

**Cost:** Cloud costs apply

### Overview

Run benchmarks at realistic scales with proper tuning for accurate, reproducible results.

### Complete Example

```python
"""Production benchmarking pattern with full configuration."""

from pathlib import Path
import json
from datetime import datetime
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH

def production_benchmark():
    """Run TPC-H benchmark at production scale with tuning."""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(f"./benchmark_runs/production/tpch_sf10_{timestamp}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Production scale (10GB dataset)
    benchmark = TPCH(
        scale_factor=10.0,
        output_dir=output_dir / "data",
        force_regenerate=False,  # Use cached data if available
        verbose=True,
    )

    print(f"Generating TPC-H data at scale factor 10.0...")
    data_files = benchmark.generate_data()
    print(f"✓ Generated {len(data_files)} data files")

    # Load tuning configuration
    tuning_path = Path("examples/tunings/duckdb/tpch_tuned.yaml")

    # Create persistent database with tuning
    db_path = output_dir / "tpch_sf10_tuned.duckdb"
    adapter = DuckDBAdapter(
        database_path=str(db_path),
        force_recreate=True,
        tuning_config=tuning_path,  # Apply optimizations
    )

    print(f"\nRunning TPC-H power test (22 queries)...")
    results = adapter.run_benchmark(
        benchmark,
        test_execution_type="power"
    )

    # Save detailed results
    results_file = output_dir / "results.json"
    with open(results_file, 'w') as f:
        json.dump({
            "timestamp": timestamp,
            "benchmark": "TPC-H",
            "scale_factor": 10.0,
            "platform": "DuckDB",
            "tuning": "tuned",
            "total_queries": results.total_queries,
            "successful_queries": results.successful_queries,
            "failed_queries": results.failed_queries,
            "total_execution_time": results.total_execution_time,
            "average_query_time": results.average_query_time,
            "queries": [
                {
                    "query_num": q.query_num,
                    "execution_time": q.execution_time,
                    "status": q.status,
                }
                for q in results.query_results
            ]
        }, f, indent=2)

    # Print summary
    print(f"\n{'='*60}")
    print(f"PRODUCTION BENCHMARK RESULTS")
    print(f"{'='*60}")
    print(f"Benchmark:      TPC-H SF 10.0")
    print(f"Platform:       DuckDB (tuned)")
    print(f"Queries:        {results.successful_queries}/{results.total_queries} succeeded")
    print(f"Total Time:     {results.total_execution_time:.2f}s")
    print(f"Average/Query:  {results.average_query_time:.2f}s")
    print(f"Database:       {db_path}")
    print(f"Results:        {results_file}")
    print(f"{'='*60}\n")

    return results.successful_queries == results.total_queries

if __name__ == "__main__":
    raise SystemExit(0 if production_benchmark() else 1)
```

### Best Practices

1. **Use Realistic Scale**: SF 1.0 = 1GB, SF 10 = 10GB, SF 100 = 100GB
2. **Apply Tuning**: Use tuned configurations for accurate performance
3. **Save Everything**: Database, results, configuration, logs
4. **Include Metadata**: Timestamp, versions, system info
5. **Multiple Runs**: Run 3-5 times and report median

### Scale Factor Guidelines

| Scale Factor | Data Size | Use Case          |
| ------------ | --------- | ----------------- |
| 1            | 1 GB      | Tiny testing      |
| 10           | 10 GB     | Small production  |
| 100          | 100 GB    | Medium production |
| 1000         | 1 TB      | Large production  |

---

## Pattern 4: Performance Regression Testing

**When to use:** CI/CD pipelines, pull request validation, continuous monitoring

**Time:** 5-10 minutes per run

**Cost:** Minimal (small scale)

### Overview

Detect performance regressions automatically by comparing against baseline results.

### Complete Example

```python
"""Performance regression testing pattern for CI/CD."""

import json
import sys
from pathlib import Path
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH

def load_baseline(baseline_file: Path) -> dict:
    """Load baseline performance results."""
    with open(baseline_file) as f:
        return json.load(f)

def run_regression_test(baseline_file: Path, threshold: float = 0.10):
    """
    Run benchmark and compare against baseline.

    Args:
        baseline_file: Path to baseline results JSON
        threshold: Maximum allowed slowdown (0.10 = 10%)

    Returns:
        True if no regressions detected
    """
    # Load baseline
    baseline = load_baseline(baseline_file)
    baseline_time = baseline["total_execution_time"]

    print(f"Baseline time: {baseline_time:.2f}s")
    print(f"Regression threshold: {threshold*100:.0f}%")
    print()

    # Run current benchmark (small scale for speed)
    benchmark = TPCH(
        scale_factor=0.1,  # Quick but representative
        output_dir="./ci_test_data",
        force_regenerate=False,
    )

    benchmark.generate_data()

    adapter = DuckDBAdapter(database_path=":memory:")
    results = adapter.run_benchmark(benchmark, test_execution_type="power")

    current_time = results.total_execution_time

    # Calculate regression
    slowdown = (current_time - baseline_time) / baseline_time

    print(f"Current time: {current_time:.2f}s")
    print(f"Change: {slowdown*100:+.1f}%")

    # Check for regression
    if slowdown > threshold:
        print(f"\n❌ REGRESSION DETECTED: {slowdown*100:.1f}% slower than baseline!")
        print(f"   Threshold: {threshold*100:.0f}%")
        return False
    else:
        print(f"\n✓ No regression detected")
        return True

def create_baseline(output_file: Path):
    """Create new baseline results file."""
    benchmark = TPCH(
        scale_factor=0.1,
        output_dir="./ci_test_data",
        force_regenerate=False,
    )

    benchmark.generate_data()
    adapter = DuckDBAdapter(database_path=":memory:")
    results = adapter.run_benchmark(benchmark, test_execution_type="power")

    baseline = {
        "total_execution_time": results.total_execution_time,
        "average_query_time": results.average_query_time,
        "scale_factor": 0.1,
        "benchmark": "TPC-H",
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(baseline, f, indent=2)

    print(f"✓ Created baseline: {output_file}")

if __name__ == "__main__":
    baseline_file = Path(".github/baselines/tpch_sf01.json")

    if "--create-baseline" in sys.argv:
        create_baseline(baseline_file)
        sys.exit(0)

    success = run_regression_test(baseline_file, threshold=0.15)
    sys.exit(0 if success else 1)
```

### GitHub Actions Integration

```yaml
# .github/workflows/performance-regression.yml
name: Performance Regression Check

on: [pull_request]

jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          uv pip install benchbox

      - name: Run regression test
        run: |
          python examples/ci/regression_test.py
        env:
          BASELINE_FILE: .github/baselines/tpch_sf01.json
          THRESHOLD: "0.15"  # 15% slowdown threshold

      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: benchmark-results
          path: ./ci_test_data/
```

### Key Considerations

- **Small Scale**: Use SF 0.1 for 5-10 minute CI runs
- **Threshold**: 10-15% allows for normal variance
- **Baseline Storage**: Commit baseline to git or artifact storage
- **Multiple Runs**: Average 3 runs to reduce noise
- **Fail Fast**: Run regression tests before expensive tests

---

## Pattern 5: Multi-Platform Evaluation

**When to use:** Choosing between databases, migration decisions, cost-performance analysis

**Time:** 1-2 hours

**Cost:** Multiple platform costs

### Overview

Run the same benchmark on multiple platforms to compare performance, cost, and capabilities.

### Complete Example

```bash
#!/bin/bash
# Multi-platform comparison script

SCALE_FACTOR="1.0"
OUTPUT_DIR="./platform_comparison_$(date +%Y%m%d)"

echo "Running TPC-H SF $SCALE_FACTOR on multiple platforms..."
echo "Output directory: $OUTPUT_DIR"
echo

# Platform 1: DuckDB (local baseline)
echo "=== Running on DuckDB ==="
python examples/unified_runner.py \
  --platform duckdb \
  --benchmark tpch \
  --scale $SCALE_FACTOR \
  --phases power \
  --tuning tuned \
  --output-dir "$OUTPUT_DIR/duckdb" \
  --formats json,csv,html

# Platform 2: ClickHouse (self-hosted)
echo "=== Running on ClickHouse ==="
python examples/unified_runner.py \
  --platform clickhouse-server \
  --benchmark tpch \
  --scale $SCALE_FACTOR \
  --phases power \
  --tuning tuned \
  --output-dir "$OUTPUT_DIR/clickhouse-server" \
  --formats json,csv,html

# Platform 3: Databricks (cloud)
echo "=== Running on Databricks ==="
python examples/unified_runner.py \
  --platform databricks \
  --benchmark tpch \
  --scale $SCALE_FACTOR \
  --phases power \
  --tuning tuned \
  --output-dir "$OUTPUT_DIR/databricks" \
  --formats json,csv,html

# Generate comparison report
python - <<EOF
import json
from pathlib import Path

platforms = ["duckdb", "clickhouse-server", "databricks"]
results = {}

for platform in platforms:
    result_file = Path("$OUTPUT_DIR") / platform / "results.json"
    if result_file.exists():
        with open(result_file) as f:
            results[platform] = json.load(f)

print("\n" + "="*70)
print("MULTI-PLATFORM COMPARISON RESULTS")
print("="*70)
print(f"{'Platform':<15} {'Queries':<10} {'Total Time':<15} {'Avg/Query':<15}")
print("-"*70)

for platform in platforms:
    if platform in results:
        r = results[platform]
        print(f"{platform.title():<15} "
              f"{r['successful_queries']}/{r['total_queries']:<10} "
              f"{r['total_execution_time']:.2f}s{'':<10} "
              f"{r['average_query_time']:.2f}s")

print("="*70)
EOF

echo
echo "✓ Comparison complete! Results in: $OUTPUT_DIR"
echo "  - View HTML reports in each platform directory"
echo "  - Compare JSON results for detailed analysis"
```

### Analysis Script

```python
"""Analyze multi-platform comparison results."""

import json
from pathlib import Path
from typing import Dict, List

def load_platform_results(base_dir: Path) -> Dict[str, dict]:
    """Load results from all platforms."""
    results = {}
    for platform_dir in base_dir.iterdir():
        if platform_dir.is_dir():
            result_file = platform_dir / "results.json"
            if result_file.exists():
                with open(result_file) as f:
                    results[platform_dir.name] = json.load(f)
    return results

def compare_platforms(results: Dict[str, dict]) -> None:
    """Generate comparison analysis."""

    # Find fastest platform
    fastest = min(results.items(), key=lambda x: x[1]["total_execution_time"])

    print("\n🏆 WINNER: {} ({:.2f}s total)".format(
        fastest[0].title(),
        fastest[1]["total_execution_time"]
    ))

    # Compare relative performance
    print("\n📊 RELATIVE PERFORMANCE (vs fastest):")
    for platform, data in sorted(results.items(),
                                  key=lambda x: x[1]["total_execution_time"]):
        relative = data["total_execution_time"] / fastest[1]["total_execution_time"]
        print(f"  {platform.title():<15} {relative:.2f}x  ({data['total_execution_time']:.2f}s)")

    # Query-by-query comparison
    print("\n📈 QUERY-BY-QUERY COMPARISON:")
    print(f"{'Query':<8} " + " ".join(f"{p.title():<10}" for p in results.keys()))
    print("-" * (8 + 11 * len(results)))

    # Get all query numbers
    query_nums = sorted(set(
        q["query_num"]
        for data in results.values()
        for q in data.get("queries", [])
    ))

    for qnum in query_nums:
        times = [
            next((q["execution_time"] for q in results[p].get("queries", [])
                  if q["query_num"] == qnum), None)
            for p in results.keys()
        ]
        print(f"Q{qnum:<7} " + " ".join(
            f"{t:.2f}s    " if t else "N/A       "
            for t in times
        ))

if __name__ == "__main__":
    import sys
    base_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./platform_comparison_latest")
    results = load_platform_results(base_dir)
    compare_platforms(results)
```

---

## Pattern 6: Incremental Performance Tuning

**When to use:** Optimizing database performance, understanding tuning impact

**Time:** 30 minutes - 2 hours

**Cost:** Depends on platform

### Overview

Systematically test different tuning configurations to find optimal performance.

### Complete Example

```python
"""Incremental performance tuning pattern."""

import json
from pathlib import Path
from dataclasses import dataclass
from typing import List
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH

@dataclass
class TuningResult:
    """Results from one tuning configuration."""
    name: str
    config_file: str
    total_time: float
    avg_time: float
    successful_queries: int

def run_tuning_experiment(
    tuning_configs: List[tuple[str, Path]],
    scale_factor: float = 1.0
) -> List[TuningResult]:
    """
    Run benchmark with multiple tuning configurations.

    Args:
        tuning_configs: List of (name, config_file_path) tuples
        scale_factor: Benchmark scale factor

    Returns:
        List of tuning results
    """
    results = []

    # Generate data once (reused for all configurations)
    benchmark = TPCH(
        scale_factor=scale_factor,
        output_dir="./tuning_experiment_data",
        force_regenerate=False,
    )
    data_files = benchmark.generate_data()
    print(f"✓ Generated {len(data_files)} data files\n")

    # Test each configuration
    for name, config_file in tuning_configs:
        print(f"Testing configuration: {name}")
        print(f"Config file: {config_file}")

        # Create fresh database with this configuration
        adapter = DuckDBAdapter(
            database_path=f"./tuning_test_{name}.duckdb",
            force_recreate=True,
            tuning_config=config_file if config_file else None,
        )

        # Run benchmark
        benchmark_results = adapter.run_benchmark(
            benchmark,
            test_execution_type="power"
        )

        # Record results
        result = TuningResult(
            name=name,
            config_file=str(config_file) if config_file else "none",
            total_time=benchmark_results.total_execution_time,
            avg_time=benchmark_results.average_query_time,
            successful_queries=benchmark_results.successful_queries,
        )
        results.append(result)

        print(f"  Total time: {result.total_time:.2f}s")
        print(f"  Avg/query: {result.avg_time:.2f}s")
        print()

    return results

def analyze_tuning_results(results: List[TuningResult]) -> None:
    """Analyze and display tuning experiment results."""

    # Sort by performance
    sorted_results = sorted(results, key=lambda x: x.total_time)
    baseline = sorted_results[-1]  # Slowest (usually notuning)
    fastest = sorted_results[0]

    print("="*70)
    print("TUNING EXPERIMENT RESULTS")
    print("="*70)
    print(f"{'Configuration':<20} {'Total Time':<15} {'Speedup':<15} {'Status'}")
    print("-"*70)

    for result in sorted_results:
        speedup = baseline.total_time / result.total_time
        status = "✓" if result.successful_queries == 22 else f"✗ ({result.successful_queries}/22)"
        print(f"{result.name:<20} {result.total_time:<14.2f}s {speedup:<14.2f}x {status}")

    print("="*70)
    print(f"\n🏆 Best configuration: {fastest.name}")
    print(f"   Improvement: {baseline.total_time / fastest.total_time:.2f}x faster than baseline")
    print(f"   Time saved: {baseline.total_time - fastest.total_time:.2f}s")

if __name__ == "__main__":
    # Define tuning configurations to test
    tuning_configs = [
        ("notuning", Path("examples/tunings/duckdb/tpch_notuning.yaml")),
        ("pk_only", None),  # Would use custom config with only PKs
        ("pk_fk", None),    # Would use custom config with PKs + FKs
        ("full_tuned", Path("examples/tunings/duckdb/tpch_tuned.yaml")),
    ]

    # Note: Replace None with actual custom config files
    # This example shows the pattern; adapt for your configs

    results = run_tuning_experiment(tuning_configs, scale_factor=1.0)
    analyze_tuning_results(results)
```

### Tuning Progression

Test configurations in this order to understand impact:

1. **No Tuning**: Baseline performance
2. **Primary Keys Only**: Measure PK impact
3. **Primary Keys + Foreign Keys**: Add referential integrity
4. **Add Partitioning**: Test partitioning benefit
5. **Add Sorting**: Combine sorting with partitioning
6. **Full Tuning**: All optimizations enabled

---

## Pattern 7: Targeted Query Testing

**When to use:** Debugging slow queries, optimizing specific workloads, smoke testing

**Time:** 1-5 minutes

**Cost:** Minimal

### Overview

Run only specific queries for rapid testing and debugging without full benchmark overhead.

### Complete Example

```python
"""Targeted query testing pattern for specific queries."""

from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH

def test_specific_queries(query_numbers: list[str]):
    """
    Run only specified TPC-H queries.

    Args:
        query_numbers: List of query numbers as strings (e.g., ["1", "6", "12"])
    """
    print(f"Testing queries: {', '.join(f'Q{q}' for q in query_numbers)}\n")

    # Small scale for fast iteration
    benchmark = TPCH(
        scale_factor=0.1,
        output_dir="./query_testing",
        force_regenerate=False,
    )

    benchmark.generate_data()

    adapter = DuckDBAdapter(database_path=":memory:")

    # Run only specified queries
    results = adapter.run_benchmark(
        benchmark,
        test_execution_type="power",
        query_subset=query_numbers,
    )

    # Display results
    print("QUERY RESULTS:")
    print(f"{'Query':<10} {'Status':<10} {'Time (s)':<12}")
    print("-" * 32)

    for query_result in results.query_results:
        status = "✓ PASS" if query_result.status == "success" else "✗ FAIL"
        print(f"Q{query_result.query_num:<9} {status:<10} {query_result.execution_time:<12.3f}")

    print("-" * 32)
    print(f"Total: {results.successful_queries}/{len(query_numbers)} passed")
    print(f"Time: {results.total_execution_time:.2f}s")

    return results.successful_queries == len(query_numbers)

# Common query subsets for different purposes

def smoke_test():
    """Quick smoke test: run 2 fast queries."""
    return test_specific_queries(["1", "6"])

def aggregation_test():
    """Test aggregation performance."""
    return test_specific_queries(["1", "3", "5", "6", "12"])

def join_test():
    """Test join performance."""
    return test_specific_queries(["2", "3", "4", "7", "8", "9"])

def complex_query_test():
    """Test most complex queries."""
    return test_specific_queries(["2", "9", "17", "20", "21"])

if __name__ == "__main__":
    import sys

    if "--smoke" in sys.argv:
        success = smoke_test()
    elif "--aggregation" in sys.argv:
        success = aggregation_test()
    elif "--joins" in sys.argv:
        success = join_test()
    elif "--complex" in sys.argv:
        success = complex_query_test()
    elif "--queries" in sys.argv:
        # Custom query list: --queries 1,6,12
        idx = sys.argv.index("--queries")
        queries = sys.argv[idx + 1].split(",")
        success = test_specific_queries(queries)
    else:
        print("Usage: python pattern.py [--smoke|--aggregation|--joins|--complex|--queries 1,6,12]")
        sys.exit(1)

    sys.exit(0 if success else 1)
```

### Common Query Subsets

**Fast Queries (< 1 second each):**
- Query 1: Simple aggregation
- Query 6: Simple filter + aggregation

**Representative Sample (5 queries, 5-10 seconds):**
- Queries 1, 3, 6, 12, 14

**Join-Heavy Queries:**
- Queries 2, 5, 7, 8, 9, 11, 13, 15, 16, 19, 21

**Slowest Queries:**
- Queries 2, 9, 17, 20, 21, 22

---

## Pattern 8: Cost-Optimized Cloud Testing

**When to use:** Learning cloud platforms, budget-conscious testing, CI/CD on cloud

**Time:** 5-10 minutes

**Cost:** < $1 typically

### Overview

Minimize cloud costs while still getting useful benchmark results through careful configuration.

### Complete Example

```python
"""Cost-optimized cloud benchmarking pattern."""

import os
from pathlib import Path
from benchbox.core.config import BenchmarkConfig, DatabaseConfig
from benchbox.core.runner.runner import run_benchmark_lifecycle, LifecyclePhases, ValidationOptions
from benchbox.core.system import SystemProfiler
from benchbox.platforms.databricks import DatabricksAdapter

def cost_optimized_databricks_test():
    """
    Run TPC-H on Databricks with minimal cost.

    Cost optimization strategies:
    1. Smallest warehouse size (2X-Small)
    2. Smallest scale factor (0.01)
    3. Query subset (5 queries instead of 22)
    4. Auto-stop enabled (default)
    """

    # Verify credentials
    if not os.environ.get("DATABRICKS_TOKEN"):
        print("❌ Error: DATABRICKS_TOKEN environment variable not set")
        return False

    # Configure for minimum cost
    benchmark_config = BenchmarkConfig(
        name="tpch",
        display_name="TPC-H Cost-Optimized Test",
        scale_factor=0.01,  # ~10MB data (negligible storage cost)
        queries=["1", "3", "6", "12", "14"],  # 5 fast queries
        options={
            "force_regenerate": False,
        },
        test_execution_type="power",
    )

    # Use smallest warehouse
    database_config = DatabaseConfig(
        type="databricks",
        name="benchbox_cost_test",
        options={
            "host": os.environ["DATABRICKS_HOST"],
            "http_path": os.environ["DATABRICKS_HTTP_PATH"],
            "access_token": os.environ["DATABRICKS_TOKEN"],
            "catalog": "main",
            "schema": "benchbox_tiny_test",
            # Warehouse should be 2X-Small or serverless
        },
    )

    profiler = SystemProfiler()
    system_profile = profiler.get_system_profile()

    # Create adapter
    adapter = DatabricksAdapter(
        host=os.environ["DATABRICKS_HOST"],
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        access_token=os.environ["DATABRICKS_TOKEN"],
        catalog="main",
        schema="benchbox_tiny_test",
    )

    print("🔧 Cost Optimization Settings:")
    print(f"  - Scale factor: {benchmark_config.scale_factor} (~10MB)")
    print(f"  - Queries: {len(benchmark_config.queries)} of 22")
    print(f"  - Warehouse: Use 2X-Small or serverless")
    print(f"  - Estimated cost: < $0.50 USD")
    print()

    # Run benchmark
    results = run_benchmark_lifecycle(
        benchmark_config=benchmark_config,
        database_config=database_config,
        system_profile=system_profile,
        platform_adapter=adapter,
        phases=LifecyclePhases(generate=True, load=True, execute=True),
        validation_opts=ValidationOptions(),
    )

    # Display results
    print("\n✓ Test complete!")
    print(f"  Queries: {results.successful_queries}/{len(benchmark_config.queries)} succeeded")
    print(f"  Time: {results.total_execution_time:.2f}s")
    print(f"  Estimated cost: < $0.50 USD")

    # Cleanup reminder
    print("\n💡 Cost-saving tip: Drop schema when done:")
    print(f"   DROP SCHEMA main.benchbox_tiny_test CASCADE;")

    return results.successful_queries == len(benchmark_config.queries)

if __name__ == "__main__":
    success = cost_optimized_databricks_test()
    raise SystemExit(0 if success else 1)
```

### Cost-Saving Strategies

1. **Scale Factor**: Run first with 1 (1GB) to confirm setup
2. **Warehouse Size**: Use smallest available (2X-Small, XS, etc.)
3. **Auto-Stop**: Ensure warehouse auto-stops after idle time
4. **Serverless**: Use serverless warehouses when available
5. **Cleanup**: Drop schemas/datasets after testing

---

## Next Steps

- **INDEX.md**: Find examples by goal, platform, or experience level
- **README.md**: Quick navigation and overview
- **Documentation**: See [../docs/usage/examples.md](../docs/usage/examples.md) for detailed guides

---

**Have a pattern to contribute?** Submit a PR with your pattern following this format!
