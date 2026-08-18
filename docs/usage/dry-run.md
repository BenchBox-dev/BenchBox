<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Dry Run Mode

```{tags} intermediate, guide, cli
```

The BenchBox dry run feature provides a powerful preview capability that allows you to validate configurations, extract queries, estimate resources, and troubleshoot issues without executing actual benchmarks.

## Overview

Dry run mode is essential for:

- **Configuration Validation** - Verify all parameters are set correctly
- **Query Preview** - Review SQL queries before execution
- **Resource Planning** - Understand memory and storage requirements
- **Debugging** - Troubleshoot benchmark setup issues
- **Documentation** - Generate examples and query references
- **Development** - Test changes without running full benchmarks

## Quick Start

### Basic CLI Usage

```bash
# Preview TPC-H benchmark configuration and queries
benchbox run --dry-run ./benchmark_runs/dryrun_previews --platform duckdb --benchmark tpch --scale 0.1

# Preview with tuning configurations
benchbox run --dry-run ./tuned_preview --platform duckdb --benchmark tpcds --scale 0.01 --tuning

# Preview multiple output formats
benchbox run --dry-run ./systematic_preview --platform duckdb --benchmark primitives --scale 0.001

### Seed Control in Dry Run

You can control the RNG seed used for parameter generation in TPC Power/Throughput test previews. This is useful at very small scales where certain seeds may cause dsqgen/qgen to fail parameterization.

```bash
# TPC-DS Power Test preview with seed
benchbox run --dry-run ./preview_tpcds_seed7 --platform duckdb --benchmark tpcds --phases power --scale 0.01 --seed 7

# TPC-DS Throughput Test preview with base seed
benchbox run --dry-run ./preview_tpcds_thr9 --platform duckdb --benchmark tpcds --phases throughput --scale 0.01 --seed 9

# TPC-H Power Test preview with seed
benchbox run --dry-run ./preview_tpch_seed5 --platform duckdb --benchmark tpch --phases power --scale 0.01 --seed 5
```

If a specific seed cannot generate all queries at a tiny scale, the CLI preflight validation will fail fast and report example failures. Try a different seed or a slightly larger scale.
```

### Programmatic Usage

```python
from benchbox.cli.dryrun import DryRunExecutor
from benchbox.cli.system import SystemProfiler
from benchbox.cli.database import DatabaseConfig
from benchbox.core.config import BenchmarkConfig
from pathlib import Path

# Setup dry run
output_dir = Path("./my_dry_run")
dry_run = DryRunExecutor(output_dir)

# Configure components
profiler = SystemProfiler()
system_profile = profiler.get_system_profile()

db_config = DatabaseConfig(
    platform="duckdb",
    connection_params={"database": ":memory:"},
    dialect="duckdb"
)

benchmark_config = BenchmarkConfig(
    name="tpch",
    scale_factor=0.01,
    platform="duckdb"
)

# Execute dry run
result = dry_run.execute_dry_run(
    benchmark_config=benchmark_config,
    system_profile=system_profile,
    database_config=db_config
)

print(f"Extracted {len(result.queries)} queries")
print(f"Generated schema with {len(result.schema_info.get('tables', {}))} tables")
print(f"Memory estimate: {result.resource_estimates.estimated_memory_mb} MB")
```

## Output Structure

When you run a dry run, BenchBox creates an output directory:

```
dry_run_output/
├── summary.json              # Complete configuration summary
├── summary.yaml              # Human-readable configuration
├── system_profile.json       # System information
├── queries/                  # Individual SQL query files
│   ├── query_1.sql
│   ├── query_2.sql
│   └── ...
├── schema.sql                # Database schema definition
└── resource_estimates.json   # Memory and performance estimates
```

### Summary Files

**summary.json** - Complete structured output:
```json
{
  "timestamp": "2025-01-15T14:30:22.123456",
  "benchmark_config": {
    "name": "tpch",
    "scale_factor": 0.1,
    "platform": "duckdb"
  },
  "system_profile": {
    "os": "Darwin 24.6.0",
    "architecture": "arm64",
    "memory_gb": 36.0,
    "cpu_cores": 12
  },
  "database_config": {
    "platform": "duckdb",
    "dialect": "duckdb",
    "connection": ":memory:"
  },
  "queries": {
    "1": "SELECT ... FROM lineitem WHERE ...",
    "2": "SELECT ... FROM supplier, nation ..."
  },
  "schema_info": {
    "tables": {
      "lineitem": {"row_count": 600572, "columns": 16},
      "orders": {"row_count": 150000, "columns": 9}
    }
  },
  "resource_estimates": {
    "estimated_memory_mb": 256,
    "estimated_storage_mb": 100,
    "estimated_runtime_minutes": 3.2
  }
}
```

**summary.yaml** - Human-readable format:
```yaml
timestamp: 2025-01-15T14:30:22.123456
benchmark_config:
  name: tpch
  scale_factor: 0.1
  platform: duckdb
system_profile:
  os: Darwin 24.6.0
  architecture: arm64
  memory_gb: 36.0
  cpu_cores: 12
# ... continues ...
```

### Query Files

Individual SQL files are saved in the `queries/` directory:

**queries/query_1.sql:**
```sql
-- TPC-H Query 1: Pricing Summary Report
-- This query reports the amount of business that was billed, shipped, and returned.

SELECT
    l_returnflag,
    l_linestatus,
    SUM(l_quantity) AS sum_qty,
    SUM(l_extendedprice) AS sum_base_price,
    SUM(l_extendedprice * (1 - l_discount)) AS sum_disc_price,
    SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge,
    AVG(l_quantity) AS avg_qty,
    AVG(l_extendedprice) AS avg_price,
    AVG(l_discount) AS avg_disc,
    COUNT(*) AS count_order
FROM
    lineitem
WHERE
    l_shipdate <= DATE '1998-12-01' - INTERVAL '90' DAY
GROUP BY
    l_returnflag,
    l_linestatus
ORDER BY
    l_returnflag,
    l_linestatus;
```

### Schema File

**schema.sql** - Complete database schema:
```sql
-- TPC-H Database Schema
-- Generated by BenchBox Dry Run

CREATE TABLE nation (
    n_nationkey  INTEGER,
    n_name       CHAR(25),
    n_regionkey  INTEGER,
    n_comment    VARCHAR(152)
);

CREATE TABLE region (
    r_regionkey  INTEGER,
    r_name       CHAR(25),
    r_comment    VARCHAR(152)
);

-- ... continues with all tables ...

-- Indexes (if tuning enabled)
CREATE INDEX idx_lineitem_shipdate ON lineitem(l_shipdate);
CREATE INDEX idx_orders_orderdate ON orders(o_orderdate);
-- ... continues ...
```

## Console Output

The dry run provides rich, formatted console output:

```bash
$ benchbox run --dry-run ./preview --platform duckdb --benchmark tpch --scale 0.1

DRY RUN MODE - Preview Only (No Execution)
Output Directory: ./preview

┌─ System Profile ─┐
│ Component     │ Value                    │
├───────────────┼──────────────────────────┤
│ OS            │ Darwin 24.6.0           │
│ Architecture  │ arm64                   │
│ CPU Cores     │ 12 physical, 12 logical │
│ Memory        │ 36.0 GB total           │
│ Python        │ 3.13.5                  │
└───────────────┴──────────────────────────┘

┌─ Database Configuration ─┐
│ Parameter     │ Value                    │
├───────────────┼──────────────────────────┤
│ Platform      │ duckdb                   │
│ Connection    │ :memory:                 │
│ Dialect       │ duckdb                   │
│ OLAP Support  │ ✅                        │
└───────────────┴──────────────────────────┘

┌─ Benchmark Configuration ─┐
│ Parameter          │ Value                    │
├────────────────────┼──────────────────────────┤
│ Name              │ TPC-H                    │
│ Scale Factor      │ 0.1                      │
│ Estimated Data    │ 100 MB                   │
│ Query Count       │ 22                       │
│ Complexity        │ Medium                   │
└────────────────────┴──────────────────────────┘

 Extracted 22 queries:
  ✅ Query 1: Pricing Summary Report Query
  ✅ Query 2: Minimum Cost Supplier Query
  ✅ Query 3: Shipping Priority Query
  ✅ Query 4: Order Priority Checking Query
  ✅ Query 5: Local Supplier Volume Query
  ... (truncated)

 Generated schema with 8 tables:
  ✅ customer (150,000 rows, 8 columns)
  ✅ lineitem (600,572 rows, 16 columns)
  ✅ nation (25 rows, 4 columns)
  ✅ orders (150,000 rows, 9 columns)
  ✅ part (20,000 rows, 9 columns)
  ✅ partsupp (80,000 rows, 5 columns)
  ✅ region (5 rows, 3 columns)
  ✅ supplier (1,000 rows, 7 columns)

 Resource Estimates:
  • Memory Required: ~256 MB
  • Storage Required: ~100 MB
  • Estimated Runtime: 2-5 minutes
  • Queries with Joins: 15/22
  • Complex Queries: 8/22

 Saved complete preview to: ./preview/
  ├── summary.json (configuration details)
  ├── summary.yaml (human-readable config)
  ├── queries/ (22 SQL files)
  ├── schema.sql (table definitions)
  └── resource_estimates.json
```

## Features

### Tuning Preview

When using `--tuning`, the dry run includes tuning configuration details:

```bash
benchbox run --dry-run ./tuned_preview \
  --platform duckdb \
  --benchmark tpcds \
  --scale 0.1 \
  --tuning
```

Additional output includes:

```
┌─ Tuning Configuration ─┐
│ Parameter              │ Value     │
├────────────────────────┼───────────┤
│ Tuning Enabled         │ ✅         │
│ Primary Keys           │ ✅         │
│ Foreign Keys           │ ✅         │
│ Partitioning           │ Applied   │
│ Clustering             │ Applied   │
│ Distribution Keys      │ Applied   │
│ Sort Keys              │ Applied   │
└────────────────────────┴───────────┘

 Applied Tunings:
  ✅ lineitem: PARTITION BY (l_shipdate), CLUSTER BY (l_orderkey)
  ✅ orders: PARTITION BY (o_orderdate), CLUSTER BY (o_custkey)
  ✅ customer: DISTRIBUTE BY (c_nationkey)
  ✅ supplier: DISTRIBUTE BY (s_nationkey)
```

### Cross-Platform Preview

Compare configurations across multiple platforms:

```bash
# Preview for multiple platforms
for platform in duckdb clickhouse-local databricks; do
  benchbox run --dry-run ./preview_${platform} \
    --platform ${platform} \
    --benchmark tpch \
    --scale 0.01
done

# Compare extracted queries
diff ./preview_duckdb/queries/query_1.sql ./preview_clickhouse-local/queries/query_1.sql
```

### Resource Scaling Analysis

Test different scale factors to understand resource requirements:

```bash
# Test multiple scale factors
for scale in 0.001 0.01 0.1 1.0; do
  benchbox run --dry-run ./scale_${scale} \
    --platform duckdb \
    --benchmark tpch \
    --scale ${scale}

  # Extract memory estimates
  cat ./scale_${scale}/resource_estimates.json | jq '.estimated_memory_mb'
done
```

## Integration Patterns

### Pre-commit Validation

Create a git pre-commit hook for benchmark validation:

```bash
#!/bin/bash
# .git/hooks/pre-commit
# Validate benchmark changes with dry run

if git diff --cached --name-only | grep -q "benchbox/"; then
  echo "Running benchmark validation..."

  # Test critical benchmarks
  benchbox run --dry-run /tmp/validation_tpch \
    --platform duckdb --benchmark tpch --scale 0.001

  benchbox run --dry-run /tmp/validation_primitives \
    --platform duckdb --benchmark primitives --scale 0.001

  if [ $? -eq 0 ]; then
    echo "✅ Benchmark validation passed"
    rm -rf /tmp/validation_*
  else
    echo "❌ Benchmark validation failed"
    exit 1
  fi
fi
```

### Documentation Generation

Generate benchmark documentation from dry run output:

```bash
# Generate query documentation
benchbox run --dry-run ./docs/tpcds_queries \
  --platform duckdb \
  --benchmark tpcds \
  --scale 0.01

# Create markdown documentation
cat > ./docs/tpcds_benchmark.md << EOF
# TPC-DS Benchmark

Generated from dry run analysis on $(date).

## Queries
EOF

# Add query documentation
for query in ./docs/tpcds_queries/queries/*.sql; do
  echo "### $(basename $query .sql)" >> ./docs/tpcds_benchmark.md
  echo '```sql' >> ./docs/tpcds_benchmark.md
  head -20 "$query" >> ./docs/tpcds_benchmark.md
  echo '```' >> ./docs/tpcds_benchmark.md
  echo >> ./docs/tpcds_benchmark.md
done
```

### Configuration Testing

Test configurations across environments:

```bash
#!/bin/bash
# test_configurations.sh

configurations=(
  "duckdb:tpch:0.01"
  "duckdb:tpcds:0.01"
  "duckdb:primitives:0.001"
  "sqlite:primitives:0.001"
)

for config in "${configurations[@]}"; do
  IFS=':' read -r database benchmark scale <<< "$config"

  echo "Testing $database + $benchmark (scale $scale)..."

  if benchbox run --dry-run "/tmp/test_${database}_${benchmark}" \
    --platform "$database" \
    --benchmark "$benchmark" \
    --scale "$scale"; then
    echo "✅ Configuration valid"
  else
    echo "❌ Configuration failed"
  fi

  rm -rf "/tmp/test_${database}_${benchmark}"
done
```

### Query Validation

Validate extracted queries with external tools:

```python
import subprocess
from pathlib import Path

def validate_queries(dry_run_dir: str, dialect: str = "duckdb"):
    """Validate extracted SQL queries."""

    queries_dir = Path(dry_run_dir) / "queries"
    if not queries_dir.exists():
        return

    print(f"Validating queries for {dialect} dialect...")

    for query_file in queries_dir.glob("*.sql"):
        print(f"  Checking {query_file.name}...", end="")

        # Basic validation
        with open(query_file, 'r') as f:
            content = f.read()

        # Check for common issues
        issues = []
        if not content.strip():
            issues.append("Empty query")
        if content.upper().count('SELECT') == 0:
            issues.append("No SELECT statement")
        if content.count('(') != content.count(')'):
            issues.append("Unbalanced parentheses")

        if not issues:
            print(" ✅")
        else:
            print(f" ❌ ({', '.join(issues)})")

# Usage
validate_queries("./my_dry_run", "duckdb")
```

## Troubleshooting

### Common Issues

**"No queries extracted"**
- Check if benchmark name is correct
- Verify benchmark supports the specified scale factor
- Try a different scale factor (some benchmarks have minimum scales)

**"Schema generation failed"**
- Ensure database platform is supported
- Check if benchmark has schema definitions
- Try without tuning options first

**"Resource estimates unavailable"**
- Some benchmarks don't support resource estimation
- Check if benchmark has proper metadata
- Estimates are approximate and may not be available for all benchmarks

### Debugging with Dry Run

**Configuration Issues:**
```bash
# Test configuration without execution
benchbox run --dry-run ./debug \
  --platform problematic_db \
  --benchmark complex_benchmark \
  --scale 1.0

# Check the output files for issues
cat ./debug/summary.json | jq '.errors // "No errors"'
```

**Query Issues:**
```bash
# Preview queries for syntax validation
benchbox run --dry-run ./query_check \
  --platform target_platform \
  --benchmark tpch

# Validate SQL syntax externally
for query in ./query_check/queries/*.sql; do
  echo "Validating $query..."
  # Use your preferred SQL validator
  sqlfluff lint "$query" --dialect duckdb
done
```

**Platform Compatibility:**
```bash
# Test platform-specific configurations
benchbox run --dry-run ./platform_test \
  --platform clickhouse-local \
  --benchmark tpch \
  --scale 0.01

# Check for platform-specific SQL differences
diff ./platform_test/queries/query_1.sql ./reference/duckdb_query_1.sql
```

## Best Practices

### Development Workflow

1. **Start with Dry Run** - Always use dry run to validate configuration before executing
2. **Test Scale Factors** - Use small scale factors (0.001-0.01) for development
3. **Validate Queries** - Check extracted queries for syntax and logic issues
4. **Resource Planning** - Use estimates to plan execution environment
5. **Cross-Platform Testing** - Test configurations across target platforms

### Performance Optimization

1. **Resource Estimates** - Use memory and storage estimates to right-size environments
2. **Query Analysis** - Identify complex queries that may need optimization
3. **Schema Tuning** - Review tuning configurations before applying to production
4. **Scaling Validation** - Test resource scaling with different scale factors

### Production Deployment

1. **Configuration Validation** - Validate all configurations in staging environment
2. **Resource Provisioning** - Use dry run estimates for capacity planning
3. **Query Review** - Review all queries for security and performance
4. **Documentation** - Generate documentation from dry run output
5. **Monitoring Setup** - Use estimates to configure monitoring thresholds

## API Reference

### DryRunExecutor

Primary class for executing dry runs.

```python
class DryRunExecutor:
    def __init__(self, output_dir: Optional[Path] = None):
        """Initialize dry run executor.

        Args:
            output_dir: Directory to save dry run output
        """

    def execute_dry_run(
        self,
        benchmark_config: BenchmarkConfig,
        system_profile: SystemProfile,
        database_config: DatabaseConfig
    ) -> DryRunResult:
        """Execute dry run.

        Returns:
            DryRunResult with all preview information
        """
```

### DryRunResult

Result object containing all dry run information.

```python
@dataclass
class DryRunResult:
    timestamp: datetime
    benchmark_config: Dict[str, Any]
    system_profile: Dict[str, Any]
    database_config: Dict[str, Any]
    queries: Dict[str, str]
    schema_info: Dict[str, Any]
    resource_estimates: ResourceEstimates
    tuning_config: Optional[Dict[str, Any]]
```

### ResourceEstimates

Resource requirement estimates.

```python
@dataclass
class ResourceEstimates:
    estimated_memory_mb: int
    estimated_storage_mb: int
    estimated_runtime_minutes: float
    complexity_score: int
    join_count: int
    subquery_count: int
```

The dry run feature is a powerful tool for development, testing, and production planning. Use it extensively to validate configurations, understand resource requirements, and ensure successful benchmark execution.
