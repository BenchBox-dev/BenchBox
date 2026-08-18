<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Examples

```{tags} beginner, guide, python-api
```

Practical code examples for common BenchBox usage patterns, database integrations, and performance testing scenarios.

> ⚠️ **IMPORTANT: Documentation Snippets vs. Runnable Examples**
>
> **This page contains *simplified code snippets* for documentation and explanation purposes.**
> - These snippets may be incomplete or use simplified APIs for clarity
> - They are intended to illustrate concepts, not necessarily run as-is
> - Copy-pasting may require adjustments
>
> **For *complete, tested, runnable code*, use the Examples Directory:**
> - **[Examples Directory Guide](examples-directory.md)** - 40+ runnable examples organized by difficulty
> - **[Getting Started Examples](../../examples/getting_started/README.md)** - Zero to working in 5 minutes
> - **[Feature Examples](../../examples/features/README.md)** - Learn specific capabilities
> - **[Use Case Patterns](../../examples/use_cases/README.md)** - Real-world solutions
> - **[Notebook Examples](../../examples/notebooks/README.md)** - Interactive platform guides
> - **[Configuration Templates](../../examples/tunings/README.md)** - Platform setup and tuning
> - **[Workflow Patterns](../../examples/programmatic/README.md)** - 8 proven patterns
>
> **Quick Decision:**
> - Need to **understand a concept**? → Read snippets on this page
> - Need to **run working code**? → Use files in `examples/` directory

---

##  Basic Usage Examples

### Getting Started Scripts

The repository now ships focused "Hello World" scripts under
`examples/getting_started/`. They complement (not replace) the advanced
`examples/unified_runner.py` entry point. Start with the DuckDB scripts
for a zero-configuration success case and move to the cloud examples
when you are ready to supply credentials. Available local examples:

- `duckdb_tpch_power.py` - TPC-H analytical benchmark (22 queries)
- `duckdb_tpcds_power.py` - TPC-DS complex queries (99 queries)
- `duckdb_nyctaxi.py` - NYC Taxi trip analytics (25 queries on real data)
- `duckdb_tsbs_devops.py` - TSBS DevOps time-series (18 monitoring queries)

See `examples/getting_started/README.md` for the progressive walkthrough. All
scripts accept `--dry-run OUTPUT_DIR` so you can export JSON/YAML
previews without generating data or running queries.

### Complete DuckDB Example (Recommended)

This example shows the complete workflow using DuckDB, the recommended database for BenchBox:

```python
import duckdb
from benchbox import TPCH
import time

# Setup DuckDB connection (in-memory for speed)
conn = duckdb.connect(":memory:")

# Initialize TPC-H benchmark
tpch = TPCH(scale_factor=0.01)  # 10MB dataset

# Generate data
print("Generating TPC-H data...")
data_files = tpch.generate_data()
print(f"Generated {len(data_files)} tables")

# Create database schema
ddl = tpch.get_create_tables_sql()
conn.execute(ddl)

# Load data using DuckDB's efficient CSV reader
print("Loading data into DuckDB...")
for file_path in data_files:
    table_name = file_path.stem
    conn.execute(f"""
        INSERT INTO {table_name}
        SELECT * FROM read_csv('{file_path}', delimiter='|', header=false)
    """)
    print(f"  Loaded {table_name}")

# Run queries and measure performance
print("\nExecuting TPC-H queries:")
for query_id in range(1, 6):  # First 5 queries
    query_sql = tpch.get_query(query_id)

    start_time = time.time()
    result = conn.execute(query_sql).fetchall()
    execution_time = time.time() - start_time

    print(f"Query {query_id}: {execution_time * 1000:.1f} ms ({len(result)} rows)")

conn.close()
print("Benchmark complete!")
```

### Simple TPC-H Example

```python
from benchbox import TPCH
import time

# Initialize benchmark
tpch = TPCH(scale_factor=0.01)  # 10MB dataset

# Generate data
print("Generating TPC-H data...")
start_time = time.time()
data_files = tpch.generate_data()
generation_time = time.time() - start_time

print(f"Generated {len(data_files)} tables in {generation_time:.2f} seconds")
for file_path in data_files:
    table_name = file_path.stem  # Get filename without extension
    file_size = file_path.stat().st_size / (1024 * 1024)  # MB
    print(f"  {table_name}: {file_size:.2f} MB")

# Get sample queries
print("\nSample queries:")
for query_id in [1, 3, 6]:
    query = tpch.get_query(query_id)
    print(f"Query {query_id}: {len(query)} characters")
```

### Multiple Benchmarks Comparison

```python
from benchbox import TPCH, SSB, ReadPrimitives

# Initialize different benchmarks
benchmarks = {
    "TPC-H": TPCH(scale_factor=0.01),
    "SSB": SSB(scale_factor=0.01),
    "Primitives": ReadPrimitives(scale_factor=0.001)
}

# Compare characteristics
print("Benchmark Comparison:")
print(f"{'Benchmark':<12} {'Queries':<8} {'Tables':<8} {'Purpose'}")
print("-" * 50)

for name, benchmark in benchmarks.items():
    queries = benchmark.get_queries()
    schema = benchmark.get_schema()
    table_count = len(schema) if isinstance(schema, list) else len(schema.keys())

    if name == "TPC-H":
        purpose = "Decision Support"
    elif name == "SSB":
        purpose = "Star Schema OLAP"
    else:
        purpose = "Primitive Operations"

    print(f"{name:<12} {len(queries):<8} {table_count:<8} {purpose}")
```

### Query Translation Example

```python
from benchbox import TPCH

tpch = TPCH(scale_factor=0.01)

# Get original query
original_query = tpch.get_query(1)
print("Original Query (ANSI SQL):")
print(original_query[:200] + "...\n")

# Translate to different dialects (using supported platforms)
dialects = ["duckdb", "clickhouse", "snowflake", "bigquery"]

for dialect in dialects:
    translated = tpch.get_query(1, dialect=dialect)
    print(f"{dialect.upper()} version:")
    print(translated[:150] + "...\n")
```

---

## Selective Query Execution

During development and debugging, running full benchmark suites is time-prohibitive. The `--queries` parameter enables selective execution of specific queries in user-defined order, dramatically accelerating development workflows.

### CLI Usage

```bash
# Run single query for debugging (5 seconds vs 11 minutes for full TPC-H)
benchbox run --platform duckdb --benchmark tpch --queries "6" --phases power

# Run multiple queries in specific order
benchbox run --platform postgres --benchmark tpch --queries "1,6,17" --phases power

# Debug failing query with verbose output
benchbox run --platform duckdb --benchmark tpcds --queries "42" --verbose --phases power

# Test critical production queries only
benchbox run --platform clickhouse-local --benchmark tpch --queries "1,6,12,17" --phases power
```

### Programmatic Usage

The CLI `--queries` parameter maps to `query_subset` in the programmatic API:

```python
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox import TPCH

# Initialize benchmark and adapter
tpch = TPCH(scale_factor=0.01)
adapter = DuckDBAdapter()

# Load data
adapter.load_benchmark_data(tpch)

# Configure selective query execution
run_config = {
    "query_subset": ["1", "6", "17"],  # Only run these queries
    "timeout": 60,
    "verbose": True
}

# Execute subset
results = adapter.run_standard_queries(tpch, run_config)

# Process results
for result in results:
    print(f"Query {result['query_id']}: {result['execution_time']:.2f}s")
```

### Use Cases

**Rapid Development**: Test single queries during optimization work (130× faster iteration for TPC-H).

**Regression Testing**: Focus on production-critical queries without running entire suites.

**Debugging**: Isolate failing queries with verbose logging and detailed output.

**TPC Compliance Note**: Using `--queries` breaks official TPC-H/TPC-DS compliance by overriding stream permutations. Suitable for development and internal testing, not for official benchmark reporting.

---

## Power Run and Concurrent Query Examples

BenchBox provides advanced execution modes for systematic performance testing with statistical confidence and throughput analysis.

### Power Run Iterations Example

Execute multiple test iterations to gather statistical confidence:

```python
from benchbox import TPCH
from benchbox.utils import PowerRunExecutor, ExecutionConfigHelper
import tempfile
from pathlib import Path

# Configure power run iterations
config_helper = ExecutionConfigHelper()
config_helper.enable_power_run_iterations(
    iterations=5,           # Run 5 test iterations
    warm_up_iterations=2    # Plus 2 warm-up iterations (excluded from stats)
)

# Set up TPC-H benchmark
tpch = TPCH(scale_factor=0.01)

# Create power run executor
power_executor = PowerRunExecutor()

# Factory function to create power test instances
def create_power_test():
    # Create temporary database for each test
    with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False) as tmp_db:
        db_path = tmp_db.name

    from benchbox.core.tpch.power_test import TPCHPowerTest
    return TPCHPowerTest(
        benchmark=tpch,
        connection_string=f"duckdb:{db_path}",
        scale_factor=0.01,
        verbose=True,
        warm_up=True,
        validation=True
    )

# Execute power runs with multiple iterations
print("Starting power run with multiple iterations...")
result = power_executor.execute_power_runs(create_power_test, scale_factor=0.01)

# Display statistical results
print(f"\nPower Run Results:")
print(f"Total iterations: {result.iterations_completed}")
print(f"Successful iterations: {result.iterations_successful}")
print(f"Warm-up iterations: {result.warm_up_iterations}")
print(f"Total duration: {result.total_duration:.3f}s")
print(f"\nStatistical Analysis:")
print(f"Average Power@Size: {result.avg_power_at_size:.2f}")
print(f"Median Power@Size: {result.median_power_at_size:.2f}")
if result.power_at_size_stdev:
    print(f"Standard Deviation: {result.power_at_size_stdev:.2f}")
print(f"Min Power@Size: {result.min_power_at_size:.2f}")
print(f"Max Power@Size: {result.max_power_at_size:.2f}")

# Access individual iteration results
print(f"\n Per-Iteration Results:")
for i, iteration in enumerate(result.iteration_results, 1):
    print(f"Iteration {i}: Power@Size={iteration.power_at_size:.2f}, "
          f"Duration={iteration.duration:.3f}s, Success={iteration.success}")
```

### Concurrent Query Execution Example

Execute queries concurrently to test throughput and scalability:

```python
from benchbox import TPCH
from benchbox.utils import ConcurrentQueryExecutor, ExecutionConfigHelper
import tempfile

# Configure concurrent queries
config_helper = ExecutionConfigHelper()
config_helper.enable_concurrent_queries(
    max_concurrent=3  # Run 3 concurrent streams
)

# Set up benchmark
tpch = TPCH(scale_factor=0.01)

# Create concurrent query executor
concurrent_executor = ConcurrentQueryExecutor()

# Factory function to create query executor for each stream
def create_throughput_test(stream_id):
    # Create separate database for each stream
    with tempfile.NamedTemporaryFile(suffix=f"_stream_{stream_id}.duckdb", delete=False) as tmp_db:
        stream_db_path = tmp_db.name

    from benchbox.core.tpch.throughput_test import TPCHThroughputTest
    return TPCHThroughputTest(
        benchmark=tpch,
        connection_factory=lambda: f"duckdb:{stream_db_path}",
        scale_factor=0.01,
        num_streams=1,  # Each executor handles one stream
        verbose=True
    )

# Execute concurrent queries
print("Starting concurrent query execution...")
result = concurrent_executor.execute_concurrent_queries(
    create_throughput_test,
    num_streams=3
)

# Display throughput results
print(f"\nConcurrent Query Results:")
print(f"Max concurrent streams: {result.max_concurrent}")
print(f"Total queries executed: {result.queries_executed}")
print(f"Successful queries: {result.queries_successful}")
print(f"Failed queries: {result.queries_failed}")
print(f"Total duration: {result.total_duration:.3f}s")
print(f"Throughput: {result.throughput_queries_per_second:.2f} queries/sec")

# Per-stream analysis
print(f"\n Per-Stream Results:")
for i, stream_result in enumerate(result.stream_results):
    stream_id = stream_result.get('stream_id', i)
    queries_successful = stream_result.get('queries_successful', 0)
    queries_executed = stream_result.get('queries_executed', 0)
    duration = stream_result.get('duration', 0)
    print(f"Stream {stream_id}: {queries_successful}/{queries_executed} successful, "
          f"Duration: {duration:.3f}s")
```

### Performance Profile Example

Use pre-configured performance profiles for different testing scenarios:

```python
from benchbox.utils import ExecutionConfigHelper

config_helper = ExecutionConfigHelper()

# Show all available profiles
profiles = ['quick', 'standard', 'thorough', 'stress']

for profile_name in profiles:
    profile_config = config_helper.create_performance_profile(profile_name)
    power_config = profile_config['power_run']
    concurrent_config = profile_config['concurrent_queries']

    print(f"\n{profile_name.title()} Profile:")
    print(f"  Power run iterations: {power_config['iterations']} "
          f"(+{power_config['warm_up_iterations']} warm-up)")
    print(f"  Timeout per iteration: {power_config['timeout_per_iteration_minutes']} minutes")
    print(f"  Concurrent queries: {'enabled' if concurrent_config['enabled'] else 'disabled'}")
    if concurrent_config['enabled']:
        print(f"  Max concurrent streams: {concurrent_config['max_concurrent']}")

# Apply a profile
print(f"\nApplying 'thorough' profile...")
config_helper.apply_performance_profile('thorough')

# View current settings
summary = config_helper.get_execution_summary()
print(f"Current power run settings: {summary['power_run']['total_iterations']} total iterations")
print(f"Current concurrent settings: {summary['concurrent_queries']['max_streams']} max streams")
```

### System Optimization Example

Automatically optimize settings based on system resources:

```python
import psutil
from benchbox.utils import ExecutionConfigHelper

# Create config helper
config_helper = ExecutionConfigHelper()

# Get system specifications
cpu_cores = psutil.cpu_count()
memory_gb = psutil.virtual_memory().total / (1024**3)

print(f"System specs: {cpu_cores} CPU cores, {memory_gb:.1f}GB RAM")

# Apply system optimization
print("Optimizing configuration for system resources...")
config_helper.optimize_for_system(cpu_cores=cpu_cores, memory_gb=memory_gb)

# Show configured settings
summary = config_helper.get_execution_summary()

print(f"\nOptimized Settings:")
print(f"Power Run:")
print(f"  - Timeout per iteration: {summary['power_run']['settings']['timeout_per_iteration_minutes']} minutes")
print(f"  - Total estimated duration: {summary['power_run']['estimated_duration_minutes']} minutes")

print(f"Concurrent Queries:")
print(f"  - Max concurrent streams: {summary['concurrent_queries']['settings']['max_concurrent']}")
print(f"  - Query timeout: {summary['concurrent_queries']['settings']['query_timeout_seconds']} seconds")

print(f"General:")
print(f"  - Max workers: {summary['general']['max_workers']}")
print(f"  - Memory limit: {summary['general']['memory_limit_gb']}GB")
```

### Configuration Management Example

Load, modify, and save execution configurations:

```python
from benchbox.cli.config import ConfigManager
from benchbox.utils import ExecutionConfigHelper, create_sample_execution_config
from pathlib import Path

# Create sample configuration file
sample_path = Path("sample_benchbox_config.yaml")
print(f"Creating sample configuration at: {sample_path}")
create_sample_execution_config(sample_path)

# Load configuration
config_manager = ConfigManager(config_path=sample_path)
config_helper = ExecutionConfigHelper(config_manager)

# Modify power run settings
print("Configuring custom power run settings...")
power_settings = config_helper.get_power_run_settings()
power_settings.iterations = 7
power_settings.warm_up_iterations = 2
power_settings.timeout_per_iteration_minutes = 90
config_helper.update_power_run_settings(power_settings)

# Modify concurrent query settings
print("Configuring custom concurrent query settings...")
concurrent_settings = config_helper.get_concurrent_queries_settings()
concurrent_settings.enabled = True
concurrent_settings.max_concurrent = 4
concurrent_settings.query_timeout_seconds = 450
config_helper.update_concurrent_queries_settings(concurrent_settings)

# Validate configuration
print("Validating configuration...")
is_valid = config_helper.validate_execution_config()
if is_valid:
    print("✅ Configuration is valid")

    # Save configuration
    config_helper.save_config()
    print(f"✅ Configuration saved to {sample_path}")
else:
    print("❌ Configuration validation failed")

# Display execution summary
summary = config_helper.get_execution_summary()
print(f"\nExecution Summary:")
print(f"Power Run: {summary['power_run']['total_iterations']} total iterations, "
      f"{summary['power_run']['estimated_duration_minutes']} min estimated")
print(f"Concurrent: {'enabled' if summary['concurrent_queries']['enabled'] else 'disabled'}, "
      f"{summary['concurrent_queries']['max_streams']} max streams")

# Cleanup
sample_path.unlink(missing_ok=True)
```

### Complete Workflow Example

Combine all features for systematic performance testing:

```python
from benchbox import TPCH
from benchbox.utils import ExecutionConfigHelper, PowerRunExecutor, ConcurrentQueryExecutor
import tempfile

# Initialize configuration
config_helper = ExecutionConfigHelper()

# Apply appropriate profile based on testing goals
config_helper.apply_performance_profile('standard')  # Balanced testing

# Optimize for current system
import psutil
cpu_cores = psutil.cpu_count()
memory_gb = psutil.virtual_memory().total / (1024**3)
config_helper.optimize_for_system(cpu_cores, memory_gb)

# Set up benchmark
tpch = TPCH(scale_factor=0.01)

print("Starting systematic benchmark testing...")

# 1. Power Run Testing (Multiple iterations for statistical confidence)
print("\nPhase 1: Power Run Testing")
power_executor = PowerRunExecutor(config_helper.config_manager)

def create_power_test():
    from benchbox.core.tpch.power_test import TPCHPowerTest
    with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False) as tmp:
        return TPCHPowerTest(benchmark=tpch, connection_string=f"duckdb:{tmp.name}",
                           scale_factor=0.01, warm_up=True, validation=True)

power_result = power_executor.execute_power_runs(create_power_test)

print(f"Power Run Results:")
print(f"  - Average Power@Size: {power_result.avg_power_at_size:.2f}")
print(f"  - Std Deviation: {power_result.power_at_size_stdev:.2f}")
print(f"  - Confidence: {power_result.iterations_successful}/{power_result.iterations_completed} iterations")

# 2. Concurrent Query Testing (Throughput and scalability)
print("\nPhase 2: Concurrent Query Testing")
concurrent_executor = ConcurrentQueryExecutor(config_helper.config_manager)

def create_throughput_test(stream_id):
    from benchbox.core.tpch.throughput_test import TPCHThroughputTest
    with tempfile.NamedTemporaryFile(suffix=f"_stream_{stream_id}.duckdb", delete=False) as tmp:
        return TPCHThroughputTest(benchmark=tpch, connection_factory=lambda: f"duckdb:{tmp.name}",
                                num_streams=1, verbose=False)

concurrent_result = concurrent_executor.execute_concurrent_queries(create_throughput_test)

print(f"Concurrent Query Results:")
print(f"  - Throughput: {concurrent_result.throughput_queries_per_second:.2f} queries/sec")
print(f"  - Success Rate: {concurrent_result.queries_successful}/{concurrent_result.queries_executed}")
print(f"  - Concurrent Streams: {len(concurrent_result.stream_results)}")

# 3. Comprehensive Analysis
print("\n Phase 3: Performance Analysis")
print(f"Benchmark Summary:")
print(f"  - Scale Factor: 0.01")
print(f"  - Single Stream Performance: {power_result.avg_power_at_size:.2f} Power@Size")
print(f"  - Multi Stream Throughput: {concurrent_result.throughput_queries_per_second:.2f} queries/sec")
print(f"  - Performance Consistency: ±{power_result.power_at_size_stdev:.2f} Power@Size")
print(f"  - Total Test Duration: {power_result.total_duration + concurrent_result.total_duration:.1f}s")

print("\n✅ Comprehensive benchmark testing completed!")
```

---

## Dry Run Examples

The dry run feature allows you to preview benchmark configurations, queries, and resource estimates without executing them. This is essential for development, debugging, and documentation.

### Basic Dry Run Preview

```python
from benchbox.cli.dryrun import DryRunExecutor
from benchbox.cli.system import SystemProfiler
from benchbox.cli.database import DatabaseConfig
from benchbox.core.config import BenchmarkConfig

# Setup and execute dry run
dry_run = DryRunExecutor(Path("./preview"))
result = dry_run.execute_dry_run(
    benchmark_config=BenchmarkConfig(name="tpch", scale_factor=0.01),
    system_profile=SystemProfiler().get_system_profile(),
    database_config=DatabaseConfig(platform="duckdb")
)

print(f"Extracted {len(result.queries)} queries")
print(f"Memory estimate: {result.resource_estimates.estimated_memory_mb} MB")
```

**Full example:** `examples/dry_run/basic_dry_run.py`

### CLI Dry Run Examples

```bash
# Basic TPC-H dry run
benchbox run --dry-run ./tpch_preview \
  --platform duckdb \
  --benchmark tpch \
  --scale 0.1

# Dry run with tuning enabled
benchbox run --dry-run ./tpcds_tuned_preview \
  --platform duckdb \
  --benchmark tpcds \
  --scale 0.01 \
  --tuning

# Preview multiple benchmarks
for benchmark in tpch tpcds ssb primitives; do
  echo "Previewing $benchmark..."
  benchbox run --dry-run ./preview_${benchmark} \
    --platform duckdb \
    --benchmark $benchmark \
    --scale 0.001
done
```

### Dry Run Output Analysis

```python
import json
from pathlib import Path

def analyze_dry_run_output(dry_run_dir: str):
    with open(Path(dry_run_dir) / "summary.json", 'r') as f:
        summary = json.load(f)

    # Extract key information
    system = summary["system_profile"]
    benchmark = summary["benchmark_config"]

    print(f"System: {system['os']} ({system['memory_gb']:.1f} GB)")
    print(f"Benchmark: {benchmark['name']} (scale: {benchmark['scale_factor']})")

    # Analyze queries
    queries_dir = Path(dry_run_dir) / "queries"
    if queries_dir.exists():
        query_files = list(queries_dir.glob("*.sql"))
        print(f"Extracted {len(query_files)} queries")

        # Analyze complexity for first few queries
        for query_file in query_files[:3]:
            with open(query_file, 'r') as f:
                content = f.read()
                joins = content.upper().count('JOIN')
                complexity = "High" if joins > 3 else "Medium" if joins > 1 else "Low"
                print(f"  {query_file.name}: {joins} joins, complexity: {complexity}")

# Usage: analyze_dry_run_output("./tpch_preview")
```

**Full example:** `examples/dry_run/analyze_dry_run_output.py`

### Query Extraction and Validation

```python
from pathlib import Path
import subprocess

def validate_extracted_queries(dry_run_dir: str, target_dialect: str = "duckdb"):
    """Basic validation of extracted SQL queries."""
    queries_dir = Path(dry_run_dir) / "queries"
    valid_queries = 0

    for query_file in queries_dir.glob("*.sql"):
        with open(query_file, 'r') as f:
            content = f.read()

        # Basic checks
        if (content.strip() and
            'SELECT' in content.upper() and
            content.count('(') == content.count(')')):
            valid_queries += 1
            print(f"✅ {query_file.name}")
        else:
            print(f"❌ {query_file.name} has issues")

    print(f"Valid queries: {valid_queries}/{len(list(queries_dir.glob('*.sql')))}")

def lint_with_sqlfluff(dry_run_dir: str):
    """Lint queries with sqlfluff (requires: pip install sqlfluff)."""
    queries_dir = Path(dry_run_dir) / "queries"
    for query_file in queries_dir.glob("*.sql"):
        result = subprocess.run([
            "sqlfluff", "lint", str(query_file), "--dialect", "duckdb"
        ], capture_output=True)
        status = "✅" if result.returncode == 0 else "⚠️️"
        print(f"{status} {query_file.name}")
```

**Full example:** `examples/dry_run/query_validation.py`

### Documentation Generation with Dry Run

```python
import subprocess
import json
from pathlib import Path

def generate_benchmark_documentation(benchmark_name: str, output_dir: str = "./docs"):
    """Generate benchmark documentation from dry run output."""
    dry_run_dir = f"./temp_dry_run_{benchmark_name}"

    # Execute dry run
    subprocess.run([
        "benchbox", "run", "--dry-run", dry_run_dir,
        "--platform", "duckdb", "--benchmark", benchmark_name, "--scale", "0.01"
    ], check=True)

    # Load results and generate markdown
    with open(Path(dry_run_dir) / "summary.json", 'r') as f:
        summary = json.load(f)

    doc_content = [
        f"# {benchmark_name.upper()} Benchmark Documentation",
        f"Generated from BenchBox dry run analysis.\n",
        "## Overview",
        f"- **Query Count**: {len(summary.get('queries', {}))}",
        f"- **Table Count**: {len(summary.get('schema_info', {}).get('tables', {}))}"
    ]

    # Add resource requirements if available
    if "resource_estimates" in summary:
        resources = summary["resource_estimates"]
        doc_content.extend([
            "\n## Resource Requirements",
            f"- **Memory**: ~{resources.get('estimated_memory_mb', 'N/A')} MB",
            f"- **Storage**: ~{resources.get('estimated_storage_mb', 'N/A')} MB"
        ])

    # Write documentation
    doc_file = Path(output_dir) / f"{benchmark_name.lower()}_benchmark.md"
    doc_file.parent.mkdir(parents=True, exist_ok=True)
    doc_file.write_text('\n'.join(doc_content))

    # Cleanup
    import shutil
    shutil.rmtree(dry_run_dir)

    return doc_file

# Generate docs for multiple benchmarks
for benchmark in ["tpch", "primitives", "ssb"]:
    generate_benchmark_documentation(benchmark, "./generated_docs")
```

**Full example:** `examples/dry_run/documentation_generator.py`

### CI/CD Integration with Dry Run

```python
import subprocess
import json
import sys
from pathlib import Path

def validate_benchmark_changes():
    """Validate critical benchmarks using dry run in CI/CD."""
    critical_benchmarks = [
        {"name": "tpch", "scale": 0.001},
        {"name": "primitives", "scale": 0.001},
        {"name": "ssb", "scale": 0.001}
    ]

    validation_results = []

    for benchmark in critical_benchmarks:
        print(f"Validating {benchmark['name']}...")
        dry_run_dir = f"./ci_validation_{benchmark['name']}"

        try:
            # Run dry run
            subprocess.run([
                "benchbox", "run", "--dry-run", dry_run_dir,
                "--platform", "duckdb",
                "--benchmark", benchmark['name'],
                "--scale", str(benchmark['scale'])
            ], capture_output=True, text=True, check=True)

            # Validate results
            with open(Path(dry_run_dir) / "summary.json", 'r') as f:
                summary = json.load(f)

            queries = summary.get('queries', {})
            schema_info = summary.get('schema_info', {})

            validation_passed = (
                len(queries) > 0 and
                len(schema_info.get('tables', {})) > 0 and
                'resource_estimates' in summary
            )

            validation_results.append({
                "benchmark": benchmark['name'],
                "passed": validation_passed
            })

            status = "✅" if validation_passed else "❌"
            print(f"  {status} {len(queries)} queries, {len(schema_info.get('tables', {}))} tables")

        except Exception as e:
            validation_results.append({"benchmark": benchmark['name'], "passed": False})
            print(f"  ❌ Error: {e}")
        finally:
            # Cleanup
            import shutil
            if Path(dry_run_dir).exists():
                shutil.rmtree(dry_run_dir)

    # Check results
    passed = all(r['passed'] for r in validation_results)
    print(f"Validation {'✅ PASSED' if passed else '❌ FAILED'}")
    return passed

if __name__ == "__main__":
    sys.exit(0 if validate_benchmark_changes() else 1)
```

**Full example:** `examples/dry_run/ci_validation.py`

---

## Database Integration Examples

### DuckDB Complete Example

```python
import duckdb
from benchbox import TPCH
import time

def benchmark_duckdb_tpch():
    """Complete TPC-H benchmark with DuckDB."""

    # Setup
    conn = duckdb.connect(":memory:")
    tpch = TPCH(scale_factor=0.1)  # 100MB dataset

    print("Setting up TPC-H benchmark with DuckDB...")

    # Generate data
    print("1. Generating data...")
    data_files = tpch.generate_data()

    # Create schema
    print("2. Creating tables...")
    schema_sql = tpch.get_create_tables_sql()
    for statement in schema_sql.split(';'):
        if statement.strip():
            conn.execute(statement)

    # Load data
    print("3. Loading data...")
    for file_path in data_files:
    table_name = file_path.stem  # Get filename without extension
        start_load = time.time()
        conn.execute(f"""
            INSERT INTO {table_name}
            SELECT * FROM read_csv('{file_path}', header=false, delimiter='|')
        """)
        load_time = time.time() - start_load

        # Get row count
        row_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        print(f"   {table_name}: {row_count:,} rows ({load_time:.2f}s)")

    # Run benchmark queries
    print("4. Running TPC-H queries...")
    results = {}

    for query_id in range(1, 23):
        print(f"   Running Query {query_id}...", end="")

        query_sql = tpch.get_query(query_id)
        start_time = time.time()

        try:
            result = conn.execute(query_sql).fetchall()
            execution_time = time.time() - start_time
            results[query_id] = {
                "execution_time": execution_time,
                "row_count": len(result),
                "success": True
            }
            print(f" {execution_time:.3f}s ({len(result)} rows)")

        except Exception as e:
            results[query_id] = {
                "execution_time": None,
                "error": str(e),
                "success": False
            }
            print(f" FAILED: {e}")

    # Summary
    successful_queries = [q for q, r in results.items() if r["success"]]
    total_time = sum(r["execution_time"] for r in results.values() if r["success"])

    print(f"\nSummary:")
    print(f"  Successful queries: {len(successful_queries)}/22")
    print(f"  Total execution time: {total_time:.2f}s")
    print(f"  Average per query: {total_time/len(successful_queries):.3f}s")

    return results

# Run the benchmark
if __name__ == "__main__":
    results = benchmark_duckdb_tpch()
```

> **📁 Complete, tested example:** See [`examples/getting_started/local/duckdb_tpch_power.py`](../../examples/getting_started/local/duckdb_tpch_power.py) for a production-ready DuckDB example with CLI support and error handling.
>
> **📁 Additional benchmark examples:**
> - [`examples/getting_started/local/duckdb_nyctaxi.py`](../../examples/getting_started/local/duckdb_nyctaxi.py) - NYC Taxi trip analytics (real-world data patterns)
> - [`examples/getting_started/local/duckdb_tsbs_devops.py`](../../examples/getting_started/local/duckdb_tsbs_devops.py) - TSBS DevOps time-series benchmark

### ClickHouse Integration Example

> **Note**: For PostgreSQL/MySQL integration examples, see the [Development Roadmap](../development/roadmap.md) - platform adapters are planned.

```python
from clickhouse_driver import Client
from benchbox import TPCH
from pathlib import Path

def setup_clickhouse_tpch(host: str = 'localhost', port: int = 9000):
    """Setup TPC-H benchmark in ClickHouse."""

    # Connect to ClickHouse
    client = Client(host=host, port=port)

    tpch = TPCH(scale_factor=0.01)

    try:
        # Generate data
        print("Generating TPC-H data...")
        data_files = tpch.generate_data()

        # Create database
        print("Creating ClickHouse database...")
        client.execute("CREATE DATABASE IF NOT EXISTS benchbox")
        client.execute("USE benchbox")

        # Create tables
        print("Creating ClickHouse schema...")
        schema_sql = tpch.get_create_tables_sql(dialect="clickhouse")
        for statement in schema_sql.split(';'):
            if statement.strip():
                client.execute(statement)

        # Load data
        print("Loading data into ClickHouse...")
        for file_path in data_files:
            table_name = file_path.stem  # Get filename without extension
            print(f"  Loading {table_name}...")

            # ClickHouse optimized CSV loading
            with open(file_path, 'rb') as f:
                client.execute(
                    f"INSERT INTO {table_name} FORMAT CSV",
                    f.read()
                )

            # Get row count
            row_count = client.execute(f"SELECT COUNT(*) FROM {table_name}")[0][0]
            print(f"    {row_count:,} rows loaded")

        # Optimize tables
        print("Optimizing tables...")
        for file_path in data_files:
            table_name = file_path.stem
            client.execute(f"OPTIMIZE TABLE {table_name} FINAL")

        print("ClickHouse TPC-H setup complete!")

        # Test a query
        print("Testing Query 1...")
        query_1 = tpch.get_query(1, dialect="clickhouse")
        result = client.execute(query_1)
        print(f"Query 1 returned {len(result)} rows")

    except Exception as e:
        print(f"Error: {e}")
        raise

# Usage
if __name__ == "__main__":
    setup_clickhouse_tpch(host='localhost', port=9000)
```

> **📁 Complete, tested example:** For database-specific integration patterns, see platform examples in [`examples/getting_started/cloud/`](../../examples/getting_started/cloud/) (Databricks and BigQuery with credential handling) and platform configuration templates in [`examples/tunings/`](../../examples/tunings/) (production-ready YAML configs).

### SQLite Example with Performance Measurement

```python
import sqlite3
from benchbox import TPCH
import time
import csv

def benchmark_sqlite_tpch():
    """TPC-H benchmark with SQLite and performance measurement."""

    # Setup
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    tpch = TPCH(scale_factor=0.01)

    # Generate and load data
    print("Setting up TPC-H in SQLite...")
    data_files = tpch.generate_data()

    # Create tables
    schema_sql = tpch.get_create_tables_sql()
    cursor.executescript(schema_sql)

    # Load data with progress tracking
    total_rows = 0
    for file_path in data_files:
    table_name = file_path.stem  # Get filename without extension
        print(f"Loading {table_name}...", end="")
        start_time = time.time()

        with open(file_path, 'r') as f:
            reader = csv.reader(f, delimiter='|')

            # Get column info
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [col[1] for col in cursor.fetchall()]
            placeholders = ','.join(['?' for _ in columns])

            # Insert data
            rows_inserted = 0
            for row in reader:
                # Handle empty values
                row = [None if x == '' else x for x in row]
                cursor.execute(f"INSERT INTO {table_name} VALUES ({placeholders})", row)
                rows_inserted += 1

            load_time = time.time() - start_time
            total_rows += rows_inserted
            print(f" {rows_inserted:,} rows ({load_time:.2f}s)")

    print(f"Total: {total_rows:,} rows loaded")

    # Create indexes
    print("Creating indexes...")
    index_commands = [
        "CREATE INDEX idx_lineitem_orderkey ON lineitem(l_orderkey)",
        "CREATE INDEX idx_orders_custkey ON orders(o_custkey)",
        "CREATE INDEX idx_customer_nationkey ON customer(c_nationkey)"
    ]

    for cmd in index_commands:
        cursor.execute(cmd)

    conn.commit()

    # Run subset of queries (SQLite may not support all TPC-H features)
    test_queries = [1, 3, 6, 12]  # Simpler queries that work well with SQLite
    results = {}

    print("Running selected TPC-H queries...")
    for query_id in test_queries:
        print(f"  Query {query_id}...", end="")

        try:
            query_sql = tpch.get_query(query_id, dialect="sqlite")

            start_time = time.time()
            cursor.execute(query_sql)
            result = cursor.fetchall()
            execution_time = time.time() - start_time

            results[query_id] = {
                "execution_time": execution_time,
                "row_count": len(result),
                "success": True
            }
            print(f" {execution_time:.3f}s ({len(result)} rows)")

        except Exception as e:
            results[query_id] = {
                "error": str(e),
                "success": False
            }
            print(f" FAILED: {e}")

    conn.close()
    return results

# Run benchmark
if __name__ == "__main__":
    results = benchmark_sqlite_tpch()
```

> **📁 Complete, tested example:** For platform-specific examples with CLI support and error handling, see files in [`examples/getting_started/`](../../examples/getting_started/) (beginner-friendly walkthroughs) and [`examples/features/`](../../examples/features/) (focused feature demonstrations).

---

##  Performance Testing Examples

### Comprehensive Performance Analysis

```python
from benchbox import TPCH, ReadPrimitives
import time
import psutil
import statistics

class PerformanceBenchmark:
    def __init__(self):
        self.results = {}

    def measure_resource_usage(self, func):
        """Decorator to measure CPU and memory usage."""
        def wrapper(*args, **kwargs):
            # Initial measurements
            process = psutil.Process()
            initial_memory = process.memory_info().rss / 1024 / 1024  # MB
            initial_cpu_percent = process.cpu_percent()

            start_time = time.time()
            result = func(*args, **kwargs)
            end_time = time.time()

            # Final measurements
            final_memory = process.memory_info().rss / 1024 / 1024  # MB
            final_cpu_percent = process.cpu_percent()

            return {
                "result": result,
                "execution_time": end_time - start_time,
                "memory_used_mb": final_memory - initial_memory,
                "cpu_percent": final_cpu_percent
            }
        return wrapper

    def run_query_performance_test(self, benchmark, connection, query_ids, iterations=5):
        """Run performance test for specific queries."""
        results = {}

        for query_id in query_ids:
            print(f"Testing Query {query_id} ({iterations} iterations)...")
            query_results = []

            for i in range(iterations):
                query_sql = benchmark.get_query(query_id)

                # Measure execution
                start_time = time.time()
                cursor = connection.execute(query_sql)
                result = cursor.fetchall()
                execution_time = time.time() - start_time

                query_results.append({
                    "iteration": i + 1,
                    "execution_time": execution_time,
                    "row_count": len(result)
                })

            # Calculate statistics
            times = [r["execution_time"] for r in query_results]
            results[query_id] = {
                "iterations": query_results,
                "avg_time": statistics.mean(times),
                "min_time": min(times),
                "max_time": max(times),
                "std_dev": statistics.stdev(times) if len(times) > 1 else 0,
                "row_count": query_results[0]["row_count"]
            }

            print(f"  Avg: {results[query_id]['avg_time']:.3f}s ± {results[query_id]['std_dev']:.3f}s")

        return results

    def run_scale_factor_analysis(self, benchmark_class, scale_factors, connection_factory):
        """Test performance across different scale factors."""
        scale_results = {}

        for sf in scale_factors:
            print(f"Testing scale factor {sf}...")

            # Initialize benchmark
            benchmark = benchmark_class(scale_factor=sf)

            # Generate data and measure time
            start_time = time.time()
            data_files = benchmark.generate_data()
            generation_time = time.time() - start_time

            # Calculate total data size
            total_size = sum(f.stat().st_size for f in data_files.values()) / 1024 / 1024  # MB

            # Setup database connection
            conn = connection_factory()

            # Load data
            start_time = time.time()
            # ... load data into connection ...
            load_time = time.time() - start_time

            # Test representative queries
            query_results = self.run_query_performance_test(
                benchmark, conn, [1, 3, 6], iterations=3
            )

            scale_results[sf] = {
                "data_generation_time": generation_time,
                "data_size_mb": total_size,
                "data_load_time": load_time,
                "query_performance": query_results
            }

            conn.close()

        return scale_results

# Usage example
def run_systematic_analysis():
    """Run systematic performance analysis."""
    benchmark_tool = PerformanceBenchmark()

    # Test different scale factors
    scale_factors = [0.001, 0.01, 0.1]

    def create_duckdb_connection():
        import duckdb
        return duckdb.connect(":memory:")

    print("Running scale factor analysis...")
    results = benchmark_tool.run_scale_factor_analysis(
        TPCH, scale_factors, create_duckdb_connection
    )

    # Print summary
    print("\nScale Factor Analysis Results:")
    print(f"{'Scale Factor':<12} {'Data Size':<10} {'Gen Time':<10} {'Load Time':<10} {'Avg Query':<10}")
    print("-" * 60)

    for sf, data in results.items():
        avg_query_time = statistics.mean([
            q["avg_time"] for q in data["query_performance"].values()
        ])
        print(f"{sf:<12} {data['data_size_mb']:<10.1f} {data['data_generation_time']:<10.2f} {data['data_load_time']:<10.2f} {avg_query_time:<10.3f}")

if __name__ == "__main__":
    run_systematic_analysis()
```

> **📁 Complete, tested example:** See [`examples/features/result_analysis.py`](../../examples/features/result_analysis.py) for programmatic result analysis with metrics aggregation, statistical comparisons, and automated reporting.

### Regression Testing Example

```python
from benchbox import ReadPrimitives
import json
import time
from pathlib import Path

class RegressionTester:
    def __init__(self, baseline_file: str = "performance_baseline.json"):
        self.baseline_file = Path(baseline_file)
        self.baseline_data = self.load_baseline()

    def load_baseline(self):
        """Load performance baseline from file."""
        if self.baseline_file.exists():
            with open(self.baseline_file, 'r') as f:
                return json.load(f)
        return {}

    def save_baseline(self, data):
        """Save performance baseline to file."""
        with open(self.baseline_file, 'w') as f:
            json.dump(data, f, indent=2)

    def create_baseline(self, connection_factory):
        """Create new performance baseline."""
        print("Creating performance baseline...")

        read_primitives = ReadPrimitives(scale_factor=0.01)
        baseline_data = {}

        # Test performance-critical queries
        critical_queries = [
            "aggregation_basic",
            "join_inner_simple",
            "filter_selective",
            "sort_large_result"
        ]

        conn = connection_factory()

        # Setup data
        self._setup_primitives_data(primitives, conn)

        # Measure baseline performance
        for query_id in critical_queries:
            print(f"  Measuring {query_id}...")

            times = []
            for _ in range(5):  # 5 iterations for baseline
                query_sql = primitives.get_query(query_id)

                start_time = time.time()
                result = conn.execute(query_sql).fetchall()
                execution_time = time.time() - start_time
                times.append(execution_time)

            baseline_data[query_id] = {
                "avg_time": sum(times) / len(times),
                "min_time": min(times),
                "max_time": max(times),
                "row_count": len(result)
            }

            print(f"    Baseline: {baseline_data[query_id]['avg_time']:.3f}s")

        self.baseline_data = baseline_data
        self.save_baseline(baseline_data)
        conn.close()

        print("Baseline created and saved.")
        return baseline_data

    def run_regression_test(self, connection_factory, threshold=0.15):
        """Run regression test against baseline."""
        if not self.baseline_data:
            raise ValueError("No baseline data available. Create baseline first.")

        print("Running regression test...")

        read_primitives = ReadPrimitives(scale_factor=0.01)
        conn = connection_factory()

        # Setup data
        self._setup_primitives_data(primitives, conn)

        regressions = []
        improvements = []

        for query_id, baseline in self.baseline_data.items():
            print(f"  Testing {query_id}...")

            # Measure current performance
            times = []
            for _ in range(3):  # 3 iterations for regression test
                query_sql = primitives.get_query(query_id)

                start_time = time.time()
                result = conn.execute(query_sql).fetchall()
                execution_time = time.time() - start_time
                times.append(execution_time)

            current_avg = sum(times) / len(times)
            baseline_avg = baseline["avg_time"]

            # Calculate change
            change_percent = (current_avg - baseline_avg) / baseline_avg * 100

            print(f"    Current: {current_avg:.3f}s (baseline: {baseline_avg:.3f}s, change: {change_percent:+.1f}%)")

            # Check for regression or improvement
            if change_percent > threshold * 100:
                regressions.append({
                    "query_id": query_id,
                    "baseline_time": baseline_avg,
                    "current_time": current_avg,
                    "change_percent": change_percent
                })
            elif change_percent < -threshold * 100:
                improvements.append({
                    "query_id": query_id,
                    "baseline_time": baseline_avg,
                    "current_time": current_avg,
                    "change_percent": change_percent
                })

        conn.close()

        # Report results
        print(f"\nRegression Test Results:")
        print(f"  Threshold: ±{threshold*100:.0f}%")

        if regressions:
            print(f"  REGRESSIONS DETECTED ({len(regressions)}):")
            for reg in regressions:
                print(f"    {reg['query_id']}: {reg['change_percent']:+.1f}% slower")

        if improvements:
            print(f"  IMPROVEMENTS DETECTED ({len(improvements)}):")
            for imp in improvements:
                print(f"    {imp['query_id']}: {abs(imp['change_percent']):.1f}% faster")

        if not regressions and not improvements:
            print(f"  ✅ NO SIGNIFICANT CHANGES")

        return {
            "regressions": regressions,
            "improvements": improvements,
            "has_regressions": len(regressions) > 0
        }

    def _setup_primitives_data(self, primitives, conn):
        """Setup primitives data in connection."""
        # Generate and load data
        data_files = primitives.generate_data()

        # Create schema
        schema_sql = primitives.get_create_tables_sql()
        for statement in schema_sql.split(';'):
            if statement.strip():
                conn.execute(statement)

        # Load data
        for file_path in data_files:
    table_name = file_path.stem  # Get filename without extension
            conn.execute(f"""
                INSERT INTO {table_name}
                SELECT * FROM read_csv('{file_path}', header=false, delimiter='|')
            """)

# Usage example
def run_regression_testing():
    """Run regression testing workflow."""

    def create_duckdb_connection():
        import duckdb
        return duckdb.connect(":memory:")

    tester = RegressionTester()

    # Create baseline if it doesn't exist
    if not tester.baseline_data:
        tester.create_baseline(create_duckdb_connection)

    # Run regression test
    results = tester.run_regression_test(create_duckdb_connection)

    # Exit with error code if regressions detected (for CI/CD)
    import sys
    if results["has_regressions"]:
        print("REGRESSION TEST FAILED")
        sys.exit(1)
    else:
        print("REGRESSION TEST PASSED")
        sys.exit(0)

if __name__ == "__main__":
    run_regression_testing()
```

> **📁 Complete, tested example:** See [`examples/use_cases/ci_regression_test.py`](../../examples/use_cases/ci_regression_test.py) for a production-ready CI/CD testing script with error handling, logging, and CLI support.

---

## Advanced-level Usage Examples

### Custom Query Analysis

```python
from benchbox import TPCDS, QueryAnalyzer
import re

def analyze_tpcds_queries():
    """Analyze TPC-DS queries for complexity and features."""

    tpcds = TPCDS(scale_factor=0.01)
    analyzer = QueryAnalyzer()

    # Get all queries
    queries = tpcds.get_queries()

    # Analyze each query
    analysis_results = {}

    for query_id, query_sql in queries.items():
        print(f"Analyzing Query {query_id}...")

        # Extract SQL features
        features = analyzer.extract_features(query_sql)
        complexity = analyzer.calculate_complexity(query_sql)

        # Custom analysis
        line_count = len(query_sql.split('\n'))
        table_count = len(re.findall(r'\bFROM\s+(\w+)', query_sql, re.IGNORECASE))
        join_count = len(re.findall(r'\bJOIN\b', query_sql, re.IGNORECASE))
        subquery_count = len(re.findall(r'\(\s*SELECT', query_sql, re.IGNORECASE))

        analysis_results[query_id] = {
            "features": features,
            "complexity_score": complexity,
            "line_count": line_count,
            "table_count": table_count,
            "join_count": join_count,
            "subquery_count": subquery_count
        }

    # Summary statistics
    complexities = [r["complexity_score"] for r in analysis_results.values()]
    join_counts = [r["join_count"] for r in analysis_results.values()]

    print(f"\nTPC-DS Query Analysis Summary:")
    print(f"  Total queries: {len(queries)}")
    print(f"  Average complexity: {sum(complexities)/len(complexities):.1f}")
    print(f"  Average joins per query: {sum(join_counts)/len(join_counts):.1f}")

    # Most complex queries
    complex_queries = sorted(
        analysis_results.items(),
        key=lambda x: x[1]["complexity_score"],
        reverse=True
    )[:5]

    print(f"\nMost complex queries:")
    for query_id, analysis in complex_queries:
        print(f"  Query {query_id}: complexity {analysis['complexity_score']}, "
              f"{analysis['join_count']} joins, {analysis['subquery_count']} subqueries")

    return analysis_results

if __name__ == "__main__":
    analyze_tpcds_queries()
```

### Multi-Database Comparison

```python
from benchbox import TPCH
import duckdb
import sqlite3
import concurrent.futures
import statistics

def compare_databases():
    """Compare TPC-H performance across different databases."""

    # Database setup functions
    def setup_duckdb():
        conn = duckdb.connect(":memory:")
        return conn, "duckdb"

    def setup_sqlite():
        conn = sqlite3.connect(":memory:")
        return conn, "sqlite"

    database_setups = [setup_duckdb, setup_sqlite]

    # Initialize benchmark
    tpch = TPCH(scale_factor=0.01)
    data_files = tpch.generate_data()

    # Test queries (subset that works on all databases)
    test_queries = [1, 3, 6, 12]

    results = {}

    for setup_func in database_setups:
        conn, db_name = setup_func()
        print(f"Testing {db_name.upper()}...")

        try:
            # Setup schema
            schema_sql = tpch.get_create_tables_sql(dialect=db_name)
            if db_name == "sqlite":
                conn.executescript(schema_sql)
            else:
                for statement in schema_sql.split(';'):
                    if statement.strip():
                        conn.execute(statement)

            # Load data (simplified for demo)
            load_data_for_database(conn, db_name, data_files)

            # Run queries
            db_results = {}
            for query_id in test_queries:
                print(f"  Query {query_id}...", end="")

                query_sql = tpch.get_query(query_id, dialect=db_name)

                # Run multiple times for average
                times = []
                for _ in range(3):
                    start_time = time.time()
                    if db_name == "duckdb":
                        result = conn.execute(query_sql).fetchall()
                    else:  # sqlite
                        cursor = conn.cursor()
                        cursor.execute(query_sql)
                        result = cursor.fetchall()
                    execution_time = time.time() - start_time
                    times.append(execution_time)

                avg_time = statistics.mean(times)
                db_results[query_id] = {
                    "avg_time": avg_time,
                    "row_count": len(result)
                }
                print(f" {avg_time:.3f}s")

            results[db_name] = db_results

        except Exception as e:
            print(f"  Error with {db_name}: {e}")
            results[db_name] = {"error": str(e)}

        finally:
            conn.close()

    # Compare results
    print(f"\nDatabase Comparison Results:")
    print(f"{'Query':<8} {'DuckDB':<10} {'SQLite':<10} {'Speedup':<10}")
    print("-" * 40)

    for query_id in test_queries:
        if ("duckdb" in results and query_id in results["duckdb"] and
            "sqlite" in results and query_id in results["sqlite"]):

            duckdb_time = results["duckdb"][query_id]["avg_time"]
            sqlite_time = results["sqlite"][query_id]["avg_time"]
            speedup = sqlite_time / duckdb_time

            print(f"Q{query_id:<7} {duckdb_time:<10.3f} {sqlite_time:<10.3f} {speedup:<10.1f}x")

    return results

def load_data_for_database(conn, db_name, data_files):
    """Load data into database (simplified version)."""
    if db_name == "duckdb":
        for file_path in data_files:
    table_name = file_path.stem  # Get filename without extension
            conn.execute(f"""
                INSERT INTO {table_name}
                SELECT * FROM read_csv('{file_path}', header=false, delimiter='|')
            """)
    elif db_name == "sqlite":
        # Simplified SQLite loading (in practice, would use proper CSV loading)
        import csv
        for file_path in data_files:
    table_name = file_path.stem  # Get filename without extension
            with open(file_path, 'r') as f:
                reader = csv.reader(f, delimiter='|')
                # Get column count
                cursor = conn.cursor()
                cursor.execute(f"PRAGMA table_info({table_name})")
                column_count = len(cursor.fetchall())
                placeholders = ','.join(['?' for _ in range(column_count)])

                # Insert rows (limit for demo)
                for i, row in enumerate(reader):
                    if i >= 1000:  # Limit for demo
                        break
                    row = [None if x == '' else x for x in row]
                    cursor.execute(f"INSERT INTO {table_name} VALUES ({placeholders})", row)
                conn.commit()

if __name__ == "__main__":
    compare_databases()
```

> **📁 Complete, tested example:** See [`examples/features/multi_platform.py`](../../examples/features/multi_platform.py) for multi-platform benchmarking and [`examples/use_cases/platform_evaluation.py`](../../examples/use_cases/platform_evaluation.py) for comprehensive platform evaluation.

---

## CI/CD Integration Examples

### GitHub Actions Workflow

```yaml
# .github/workflows/performance-test.yml
name: Performance Regression Tests

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  performance-test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'

    - name: Install dependencies
      run: |
        uv add benchbox duckdb
        uv pip install -r requirements-test.txt

    - name: Run performance regression tests
      run: |
        uv run -- python scripts/run_performance_tests.py

    - name: Upload performance results
      uses: actions/upload-artifact@v3
      if: always()
      with:
        name: performance-results
        path: performance_results.json
```

### Performance Test Script for CI/CD

```python
#!/usr/bin/env python3
"""
Performance regression test script for CI/CD pipelines.
Usage: uv run -- python scripts/run_performance_tests.py
"""

import json
import sys
import time
from pathlib import Path
from benchbox import ReadPrimitives
import duckdb

def run_performance_tests():
    """Run performance tests suitable for CI/CD."""

    # Configuration
    CI_SCALE_FACTOR = 0.001  # Very small for fast CI runs
    REGRESSION_THRESHOLD = 0.20  # 20% regression threshold
    BASELINE_FILE = "baseline_performance.json"
    RESULTS_FILE = "performance_results.json"

    print("Starting BenchBox performance regression tests...")

    # Initialize benchmark
    read_primitives = ReadPrimitives(scale_factor=CI_SCALE_FACTOR)

    # Setup database
    conn = duckdb.connect(":memory:")
    setup_database(primitives, conn)

    # Define critical queries for regression testing
    critical_queries = [
        "aggregation_basic",
        "join_inner_simple",
        "filter_selective",
        "sort_small_result"
    ]

    # Run tests
    current_results = {}
    print(f"Running {len(critical_queries)} critical queries...")

    for query_id in critical_queries:
        print(f"  Testing {query_id}...", end="")

        # Warm up
        query_sql = primitives.get_query(query_id)
        conn.execute(query_sql).fetchall()

        # Measure performance (3 iterations)
        times = []
        for _ in range(3):
            start_time = time.time()
            result = conn.execute(query_sql).fetchall()
            execution_time = time.time() - start_time
            times.append(execution_time)

        avg_time = sum(times) / len(times)
        current_results[query_id] = {
            "avg_time": avg_time,
            "row_count": len(result),
            "timestamp": time.time()
        }

        print(f" {avg_time:.3f}s ✅")

    conn.close()

    # Load baseline if it exists
    baseline_path = Path(BASELINE_FILE)
    if baseline_path.exists():
        with open(baseline_path, 'r') as f:
            baseline_results = json.load(f)

        print(f" Comparing against baseline from {baseline_path}...")
        regressions = check_regressions(current_results, baseline_results, REGRESSION_THRESHOLD)

        if regressions:
            print(f"PERFORMANCE REGRESSIONS DETECTED:")
            for reg in regressions:
                print(f"  - {reg['query_id']}: {reg['change_percent']:+.1f}% slower")

            # Save results and exit with failure
            save_results(current_results, RESULTS_FILE, regressions)
            sys.exit(1)
        else:
            print(f"✅ No significant performance regressions detected")
    else:
        print(f"No baseline found. Creating new baseline at {baseline_path}")
        with open(baseline_path, 'w') as f:
            json.dump(current_results, f, indent=2)

    # Save current results
    save_results(current_results, RESULTS_FILE)
    print(f" Performance tests completed successfully!")

def setup_database(primitives, conn):
    """Setup database with primitives data."""
    # Generate data
    data_files = primitives.generate_data()

    # Create schema
    schema_sql = primitives.get_create_tables_sql()
    for statement in schema_sql.split(';'):
        if statement.strip():
            conn.execute(statement)

    # Load data
    for file_path in data_files:
    table_name = file_path.stem  # Get filename without extension
        conn.execute(f"""
            INSERT INTO {table_name}
            SELECT * FROM read_csv('{file_path}', header=false, delimiter='|')
        """)

def check_regressions(current_results, baseline_results, threshold):
    """Check for performance regressions."""
    regressions = []

    for query_id, current in current_results.items():
        if query_id in baseline_results:
            baseline = baseline_results[query_id]

            current_time = current["avg_time"]
            baseline_time = baseline["avg_time"]

            change_percent = (current_time - baseline_time) / baseline_time * 100

            if change_percent > threshold * 100:
                regressions.append({
                    "query_id": query_id,
                    "baseline_time": baseline_time,
                    "current_time": current_time,
                    "change_percent": change_percent
                })

    return regressions

def save_results(results, filename, regressions=None):
    """Save test results to file."""
    output = {
        "results": results,
        "summary": {
            "total_queries": len(results),
            "avg_execution_time": sum(r["avg_time"] for r in results.values()) / len(results),
            "has_regressions": regressions is not None and len(regressions) > 0
        }
    }

    if regressions:
        output["regressions"] = regressions

    with open(filename, 'w') as f:
        json.dump(output, f, indent=2)

if __name__ == "__main__":
    run_performance_tests()
```

> **📁 Complete, tested example:** See [`examples/use_cases/ci_regression_test.py`](../../examples/use_cases/ci_regression_test.py) for a production-ready CI/CD performance testing script with baseline comparison, threshold detection, and exit code reporting.

---

## Custom Benchmark Examples

### Simple Custom Benchmark

```python
from benchbox.base import BaseBenchmark
from pathlib import Path
from typing import Dict, Union
import csv

class SimpleBenchmark(BaseBenchmark):
    """Simple custom benchmark for demonstration."""

    def __init__(self, scale_factor: float = 1.0, output_dir: Path = None):
        super().__init__(scale_factor, output_dir)
        self._queries = {
            "simple_count": "SELECT COUNT(*) FROM test_table",
            "simple_sum": "SELECT SUM(value) FROM test_table",
            "simple_avg": "SELECT AVG(value) FROM test_table WHERE category = 'A'"
        }

    def generate_data(self) -> Dict[str, Path]:
        """Generate simple test data."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Generate test_table data
        test_file = self.output_dir / "test_table.csv"
        row_count = int(1000 * self.scale_factor)

        with open(test_file, 'w', newline='') as f:
            writer = csv.writer(f)

            for i in range(row_count):
                category = 'A' if i % 3 == 0 else 'B' if i % 3 == 1 else 'C'
                value = i * 1.5
                writer.writerow([i, category, value])

        return {"test_table": test_file}

    def get_queries(self) -> Dict[Union[int, str], str]:
        """Get all benchmark queries."""
        return self._queries.copy()

    def get_query(self, query_id: Union[int, str]) -> str:
        """Get specific query."""
        if query_id not in self._queries:
            raise ValueError(f"Query '{query_id}' not found")
        return self._queries[query_id]

    def get_create_tables_sql(self) -> str:
        """Get DDL for benchmark tables."""
        return """
        CREATE TABLE test_table (
            id INTEGER,
            category VARCHAR(10),
            value DOUBLE
        );
        """

# Usage example
def test_custom_benchmark():
    """Test the custom benchmark."""
    import duckdb

    # Initialize custom benchmark
    benchmark = SimpleBenchmark(scale_factor=0.1)

    # Generate data
    data_files = benchmark.generate_data()
    print(f"Generated {len(data_files)} data files")

    # Setup database
    conn = duckdb.connect(":memory:")

    # Create tables
    ddl = benchmark.get_create_tables_sql("duckdb")
    conn.execute(ddl)

    # Load data
    for file_path in data_files:
    table_name = file_path.stem  # Get filename without extension
        conn.execute(f"""
            INSERT INTO {table_name}
            SELECT * FROM read_csv('{file_path}', header=false)
        """)

    # Run queries
    queries = benchmark.get_queries()
    for query_id, query_sql in queries.items():
        result = conn.execute(query_sql).fetchall()
        print(f"{query_id}: {result[0][0]}")

    conn.close()

if __name__ == "__main__":
    test_custom_benchmark()
```

---

## See Also

- [Getting Started](getting-started.md) - Basic setup and usage
- [API Reference](../reference/api-reference.md) - Complete API documentation
- [Configuration](configuration.md) - Configuration options
- [Benchmarks](../benchmarks/index.md) - Individual benchmark documentation

---

*These examples provide practical patterns for using BenchBox in real-world scenarios. Adapt them to your specific needs and requirements.*
