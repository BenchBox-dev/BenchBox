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
benchbox run --dry-run ./benchmark_runs/dryrun_previews --platform duckdb --benchmark tpch --scale 0.1

benchbox run --dry-run ./tuned_preview --platform duckdb --benchmark tpcds --scale 0.01 --tuning tuned

benchbox run --dry-run ./systematic_preview --platform duckdb --benchmark read_primitives --scale 0.01
```

### Seed Control in Dry Run

You can control the RNG seed used for parameter generation in TPC Power/Throughput test previews. This is useful at very small scales where certain seeds may cause dsqgen/qgen to fail parameterization.

```bash
benchbox run --dry-run ./preview_tpcds_seed7 --platform duckdb --benchmark tpcds --phases power --scale 0.01 --seed 7

benchbox run --dry-run ./preview_tpcds_thr9 --platform duckdb --benchmark tpcds --phases throughput --scale 0.01 --seed 9

benchbox run --dry-run ./preview_tpch_seed5 --platform duckdb --benchmark tpch --phases power --scale 0.01 --seed 5
```

If a specific seed cannot generate all queries at a tiny scale, the CLI preflight validation will fail fast and report example failures. Try a different seed or a slightly larger scale.

### Programmatic Usage

```python
from pathlib import Path
from benchbox.cli.dryrun import DryRunExecutor
from benchbox.cli.system import SystemProfiler
from benchbox.core.config import BenchmarkConfig
from benchbox.core.schemas import DatabaseConfig

output_dir = Path("./my_dry_run")
dry_run = DryRunExecutor(output_dir)

system_profile = SystemProfiler().get_system_profile()
db_config = DatabaseConfig(type="duckdb", name="DuckDB")
benchmark_config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=0.01)

result = dry_run.execute_dry_run(
    benchmark_config=benchmark_config,
    system_profile=system_profile,
    database_config=db_config,
)

print(f"Extracted {len(result.queries)} queries")
print(f"Estimated memory: {result.estimated_resources.get('estimated_memory_usage_mb')} MB")
```

## Output Structure

When you run a dry run, BenchBox creates an output directory:

```
dry_run_output/
├── <prefix>_<timestamp>.json                    # Complete configuration summary
├── <prefix>_<timestamp>.yaml                    # Human-readable configuration
├── <prefix>_queries_<timestamp>/                # Individual SQL query files
│   ├── query_1.sql
│   ├── query_2.sql
│   └── ...
├── <prefix>_ddl_<timestamp>.sql                 # DDL preview, when present
├── <prefix>_post_load_<timestamp>.sql           # Post-load statements, when present
└── <prefix>_schema_<timestamp>.sql              # Database schema definition
```

Timestamps use `%Y%m%d_%H%M%S`. The CLI derives `<prefix>` from the benchmark
and platform (for example `tpch_duckdb`); programmatic use defaults to
`dryrun`. DataFrame mode writes `<prefix>_dataframe_queries_<timestamp>/` and
a `.py` schema file instead. System profile and resource estimates are fields
inside the JSON/YAML output, not separate files.

### Summary Files

**`<prefix>_<timestamp>.json`** - Complete structured output (keys include `benchmark_config`, `database_config`, `system_profile`, `platform_config`, `queries`, `schema_sql`, `ddl_preview`, `post_load_statements`, `tuning_config`, `constraint_config`, `estimated_resources`, `query_preview`, `warnings`, and `timestamp`):
```json
{
  "benchmark_config": {
    "name": "tpch",
    "scale_factor": 0.01
  },
  "system_profile": {
    "os_name": "Darwin",
    "architecture": "arm64",
    "memory_total_gb": 16.0,
    "cpu_cores_physical": 10
  },
  "queries": {
    "1": "SELECT ... FROM lineitem WHERE ...",
    "2": "SELECT ... FROM supplier, nation ..."
  },
  "estimated_resources": {
    "estimated_data_size_mb": 8.0,
    "estimated_memory_usage_mb": 20.0,
    "estimated_runtime_minutes": 0.0
  }
}
```

**`<prefix>_<timestamp>.yaml`** - Human-readable format with the same sections.

### Query Files

Individual SQL files are saved in the `<prefix>_queries_<timestamp>/` directory. Files contain the generated SQL with no header comments:

**`<prefix>_queries_<timestamp>/query_1.sql`:**
```sql
SELECT "l_returnflag", "l_linestatus", SUM("l_quantity") AS "sum_qty", ... FROM "lineitem" WHERE "l_shipdate" <= CAST('1998-12-01' AS DATE) - INTERVAL '90' DAY GROUP BY "l_returnflag", "l_linestatus" ORDER BY "l_returnflag", "l_linestatus"
```

### Schema File

**`<prefix>_schema_<timestamp>.sql`** - Complete database schema (excerpt below is truncated; the file continues with all tables):
```sql
CREATE TABLE region (
    r_regionkey INTEGER NOT NULL,
    r_name CHAR(25) NOT NULL,
    r_comment VARCHAR(152)
);

CREATE TABLE nation (
    n_nationkey INTEGER NOT NULL,
    n_name CHAR(25) NOT NULL,
    n_regionkey INTEGER NOT NULL,
    n_comment VARCHAR(152)
);
```

## Console Output

The dry run prints a configuration summary, per-query previews, and the schema preview (excerpt):

```bash
$ benchbox run --dry-run ./preview --platform duckdb --benchmark tpch --scale 0.1

╭────────────────────────────────────────────╮
│ DRY RUN MODE - No queries will be executed │
╰────────────────────────────────────────────╯

Configuration Summary
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃ Category   ┃ Setting      ┃ Value         ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━┩
│ Benchmark  │ Name         │ tpch          │
│            │ Scale Factor │ 0.1           │
│ Database   │ Type         │ duckdb        │
│ System     │ CPU Cores    │ 10            │
│            │ Memory (GB)  │ 16.0          │
└────────────┴──────────────┴───────────────┘

PowerTest Stream Execution Preview

Query 1:
╭─────────────────── Query 1 ───────────────────╮
│ SELECT "l_returnflag", ...                    │
╰───────────────────────────────────────────────╯

... and 19 more queries

Schema Preview
╭────────────── Database Schema ────────────────╮
│ CREATE TABLE region ( ...                     │
╰───────────────────────────────────────────────╯
```

Saved preview files land in `./preview/`:
  ├── `<prefix>_<timestamp>.json` (configuration details, resource estimates embedded)
  ├── `<prefix>_<timestamp>.yaml` (human-readable config)
  ├── `<prefix>_queries_<timestamp>/` (one `.sql` file per query)
  └── `<prefix>_schema_<timestamp>.sql` (table definitions)

## Features

### Tuning Preview

When using `--tuning`, the dry run includes tuning configuration details:

```bash
benchbox run --dry-run ./tuned_preview \
  --platform duckdb \
  --benchmark tpcds \
  --scale 0.1 \
  --tuning tuned
```

Additional output includes a constraint table and per-table organization tunings (excerpt):

```
Tuning Configuration
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Constraint Type ┃ Enabled ┃ Configuration                     ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Primary Keys    │ True    │ Uniqueness: True, Nullable: False │
│ Foreign Keys    │ True    │ Referential Integrity: True       │
└─────────────────┴─────────┴───────────────────────────────────┘

Table Organization Tunings
┏━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Table    ┃ Tuning Type ┃ Columns                      ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ LINEITEM │ Sorting     │ L_ORDERKEY (INTEGER), ...    │
│ ORDERS   │ Sorting     │ O_ORDERKEY (INTEGER), ...    │
└──────────┴─────────────┴────────────────────────────────┘

DDL Preview (Tuning Clauses)

Table: supplier
  Tuning: Sort: ORDER BY S_SUPPKEY, S_NATIONKEY
```

### Cross-Platform Preview

Compare configurations across multiple platforms:

```bash
for platform in duckdb clickhouse-local databricks; do
  benchbox run --dry-run ./preview_${platform} \
    --platform ${platform} \
    --benchmark tpch \
    --scale 0.01
done

diff ./preview_duckdb/*_queries_*/query_1.sql ./preview_clickhouse-local/*_queries_*/query_1.sql
```

### Resource Scaling Analysis

Test different scale factors to understand resource requirements:

```bash
for scale in 0.001 0.01 0.1 1.0; do
  benchbox run --dry-run ./scale_${scale} \
    --platform duckdb \
    --benchmark tpch \
    --scale ${scale}

  cat ./scale_${scale}/*.json | jq '.estimated_resources.estimated_memory_usage_mb'
done
```

## Integration Patterns

### Pre-commit Validation

Create a git pre-commit hook for benchmark validation. Save the script below as `.git/hooks/pre-commit` (a bash script, starting with `#!/bin/bash`). It runs a dry run when staged changes touch `benchbox/`, and tests the critical benchmarks:

```bash

if git diff --cached --name-only | grep -q "benchbox/"; then
  echo "Running benchmark validation..."

  benchbox run --dry-run /tmp/validation_tpch \
    --platform duckdb --benchmark tpch --scale 0.001

  benchbox run --dry-run /tmp/validation_primitives \
    --platform duckdb --benchmark read_primitives --scale 0.01

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
benchbox run --dry-run ./docs/tpcds_queries \
  --platform duckdb \
  --benchmark tpcds \
  --scale 0.01

cat > ./docs/tpcds_benchmark.md << EOF
# TPC-DS Benchmark

Generated from dry run analysis on $(date).

## Queries
EOF

for query in ./docs/tpcds_queries/*_queries_*/*.sql; do
  echo "### $(basename $query .sql)" >> ./docs/tpcds_benchmark.md
  echo '```sql' >> ./docs/tpcds_benchmark.md
  head -20 "$query" >> ./docs/tpcds_benchmark.md
  echo '```' >> ./docs/tpcds_benchmark.md
  echo >> ./docs/tpcds_benchmark.md
done
```

### Configuration Testing

Test configurations across environments. Save the script below as `test_configurations.sh` (a bash script, starting with `#!/bin/bash`):

```bash

configurations=(
  "duckdb:tpch:0.01"
  "duckdb:tpcds:0.01"
  "duckdb:read_primitives:0.01"
  "sqlite:read_primitives:0.01"
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
from pathlib import Path

def validate_queries(dry_run_dir: str, dialect: str = "duckdb"):
    candidates = sorted(Path(dry_run_dir).glob("*_queries_*"))
    if not candidates:
        return
    queries_dir = candidates[0]

    print(f"Validating queries for {dialect} dialect...")

    for query_file in queries_dir.glob("*.sql"):
        print(f"  Checking {query_file.name}...", end="")

        with open(query_file, 'r') as f:
            content = f.read()

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
benchbox run --dry-run ./debug \
  --platform problematic_db \
  --benchmark complex_benchmark \
  --scale 1.0

cat ./debug/*.json | jq '.warnings'
```

**Query Issues:**
```bash
benchbox run --dry-run ./query_check \
  --platform target_platform \
  --benchmark tpch

for query in ./query_check/*_queries_*/*.sql; do
  echo "Validating $query..."
  sqlfluff lint "$query" --dialect duckdb
done
```

**Platform Compatibility:**
```bash
benchbox run --dry-run ./platform_test \
  --platform clickhouse-local \
  --benchmark tpch \
  --scale 0.01

diff ./platform_test/*_queries_*/query_1.sql ./reference/duckdb_query_1.sql
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

Primary class for executing dry runs (`benchbox.cli.dryrun.DryRunExecutor`). `output_dir` is the directory where dry run output is saved, and `execute_dry_run()` returns a `DryRunResult` with all preview information.

```python
class DryRunExecutor:
    def __init__(self, output_dir=None):
        pass

    def execute_dry_run(
        self,
        benchmark_config: BenchmarkConfig,
        system_profile: SystemProfile,
        database_config: DatabaseConfig | None,
    ) -> DryRunResult:
        pass
```

### DryRunResult

Result object containing all dry run information (`benchbox.core.schemas.DryRunResult`, a Pydantic model).

```python
class DryRunResult:
    timestamp: datetime
    benchmark_config: dict
    system_profile: dict
    database_config: dict
    platform_config: dict
    queries: dict[str, str]
    execution_mode: str
    schema_sql: str | None
    ddl_preview: dict | None
    post_load_statements: dict | None
    tuning_config: dict | None
    constraint_config: dict | None
    estimated_resources: dict | None
    query_preview: dict | None
    warnings: list
```

### estimated_resources

Resource requirement estimates (a plain dict, keys include):

```python
{
    "scale_factor": float,
    "estimated_data_size_mb": float,
    "estimated_memory_usage_mb": float,
    "estimated_runtime_minutes": float,
    "cpu_cores_available": int,
    "memory_gb_available": float,
}
```

The dry run feature is a powerful tool for development, testing, and production planning. Use it extensively to validate configurations, understand resource requirements, and ensure successful benchmark execution.
