<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# TPC-DS Official Benchmark Guide

```{tags} advanced, guide, tpc-ds, validation
```

This guide provides systematic documentation for the TPC-DS official benchmark implementation in BenchBox, including the complete QphDS@Size metric calculation according to the TPC-DS specification.

## Overview

The TPC-DS official benchmark implementation provides a complete, certification-ready TPC-DS benchmark that meets all official TPC-DS specification requirements. It includes:

- **Complete benchmark execution** with all three phases
- **Official QphDS@Size metric calculation** using the geometric mean formula
- **Comprehensive reporting** and validation
- **TPC compliance framework** integration
- **Audit trail functionality** for certification readiness

### Key Features

- **TPC-DS Compliant**: Follows official TPC-DS specification
- **Complete Implementation**: Power, Throughput, and Maintenance Tests
- **Official Metrics**: QphDS@Size calculation with geometric mean
- **Multi-format Reporting**: Text, JSON, CSV, HTML reports
- **Validation Framework**: Comprehensive result validation
- **Error Handling**: Robust error handling and recovery
- **Scalable**: Supports any scale factor
- **Database Agnostic**: Works with multiple database systems

## Quick Start

### Basic Usage

```python
from benchbox.tpcds import TPCDSBenchmark

# Create benchmark instance
benchmark = TPCDSBenchmark(scale_factor=1.0, verbose=True)

# Run complete official benchmark
result = benchmark.run_official_benchmark(
    connection_string="your_database_connection_string",
    num_streams=2
)

# Access official metrics
print(f"QphDS@Size: {result.qphds_size:.2f}")
print(f"Power@Size: {result.power_size:.2f}")
print(f"Throughput@Size: {result.throughput_size:.2f}")
```

### Installation Requirements

```bash
# Install BenchBox with TPC-DS support
uv add benchbox[tpcds]

# Or install from source
git clone https://github.com/your-repo/benchbox
cd benchbox
uv pip install -e .[tpcds]
```

## TPC-DS Specification

The TPC-DS benchmark is the official Transaction Processing Performance Council decision support benchmark. It models the decision support functions of a retail product supplier.

### Key Characteristics

- **99 Queries**: Complex analytical queries with varying complexity
- **Three Test Phases**: Power, Throughput, and Maintenance Tests
- **Scale Factor**: Determines database size (SF=1 ≈ 1GB)
- **Multi-Stream**: Concurrent execution capability
- **Refresh Functions**: Data maintenance operations

### Official Metric

The **QphDS@Size** (Queries per Hour at Scale Factor) is the official composite metric calculated as:

```
QphDS@Size = sqrt(Power@Size × Throughput@Size)
```

Where:
- `Power@Size = 3600 × Scale_Factor / Power_Test_Time`
- `Throughput@Size = Num_Streams × 3600 × Scale_Factor / Throughput_Test_Time`

## Architecture

The TPC-DS official benchmark implementation consists of several key components:

### Core Components

```
benchbox/core/tpcds/
├── benchmark.py           # Main benchmark class
├── official_benchmark.py  # Official benchmark runner
├── reporting.py          # Comprehensive reporting
├── queries.py            # Query management
├── streams.py            # Stream management
├── generator.py          # Data generation
├── schema.py             # Database schema
└── c_tools.py            # C tool integration
```

### Class Hierarchy

```
TPCDSBenchmark
├── run_official_benchmark()
└── TPCDSOfficialBenchmark
    ├── run_complete_benchmark()
    ├── _run_power_test()
    ├── _run_throughput_test()
    ├── _run_maintenance_test()
    └── _calculate_official_metrics()
```

## Usage

### Complete Benchmark

```python
from benchbox.tpcds import TPCDSBenchmark

# Create benchmark with configuration
benchmark = TPCDSBenchmark(
    scale_factor=10.0,
    output_dir="/path/to/results",
    verbose=True,
    parallel=4
)

# Run complete benchmark
result = benchmark.run_official_benchmark(
    connection_string="postgresql://user:pass@host/db",
    num_streams=4,
    power_test=True,
    throughput_test=True,
    maintenance_test=True,
    result_validation=True,
    dialect="postgres"
)
```

### Individual Phases

```python
# Power Test only
result = benchmark.run_official_benchmark(
    connection_string="your_connection",
    power_test=True,
    throughput_test=False,
    maintenance_test=False
)

# Throughput Test only
result = benchmark.run_official_benchmark(
    connection_string="your_connection",
    num_streams=8,
    power_test=False,
    throughput_test=True,
    maintenance_test=False
)
```

### Custom Configuration

```python
# Advanced-level configuration
result = benchmark.run_official_benchmark(
    connection_string="your_connection",
    num_streams=6,
    refresh_functions=["RF1", "RF2"],
    data_maintenance=True,
    result_validation=True,
    dialect="mysql",
    output_dir="/custom/output/path"
)
```

## Configuration

### Benchmark Parameters

| Parameter      | Type     | Default     | Description              |
| -------------- | -------- | ----------- | ------------------------ |
| `scale_factor` | float    | 1.0         | Scale factor (1.0 ≈ 1GB) |
| `output_dir`   | str/Path | current dir | Output directory         |
| `verbose`      | bool     | False       | Enable verbose logging   |
| `parallel`     | int      | 1           | Parallel data generation |

### Official Benchmark Parameters

| Parameter           | Type     | Default        | Description          |
| ------------------- | -------- | -------------- | -------------------- |
| `connection_string` | str      | Required       | Database connection  |
| `num_streams`       | int      | 2              | Concurrent streams   |
| `power_test`        | bool     | True           | Run Power Test       |
| `throughput_test`   | bool     | True           | Run Throughput Test  |
| `maintenance_test`  | bool     | True           | Run Maintenance Test |
| `refresh_functions` | list     | ["RF1", "RF2"] | Refresh functions    |
| `data_maintenance`  | bool     | True           | Data maintenance ops |
| `result_validation` | bool     | True           | Result validation    |
| `dialect`           | str      | "standard"     | SQL dialect          |
| `output_dir`        | str/Path | None           | Custom output path   |

## Benchmark Phases

### 1. Power Test

The Power Test measures single-stream query processing power by executing all 99 TPC-DS queries sequentially.

```python
# Power Test execution
power_result = benchmark._run_power_test(connection_string, dialect)

# Access Power Test results
print(f"Execution Time: {power_result.execution_time:.2f}s")
print(f"Successful Queries: {len([q for q in power_result.queries if q.success])}")
print(f"Power@Size: {result.power_size:.2f}")
```

**Characteristics:**
- Sequential execution of all 99 queries
- Single database connection
- Measures database query processing capability
- Contributes to Power@Size metric

### 2. Throughput Test

The Throughput Test measures concurrent query processing capability by executing multiple streams of queries simultaneously.

```python
# Throughput Test execution
throughput_result = benchmark._run_throughput_test(connection_string, num_streams, dialect)

# Access Throughput Test results
print(f"Concurrent Streams: {num_streams}")
print(f"Total Queries: {len(throughput_result.queries)}")
print(f"Throughput@Size: {result.throughput_size:.2f}")
```

**Characteristics:**
- Multiple concurrent streams (default: 2)
- Each stream executes queries in different order
- Measures concurrent processing capability
- Contributes to Throughput@Size metric

### 3. Maintenance Test

> **⚠️ CRITICAL: Database Reload Required After Maintenance Test**
>
> The Maintenance Test permanently modifies database contents through INSERT, UPDATE, and DELETE
> operations on sales and inventory tables. After running the maintenance phase, you **must reload
> the database** before running power or throughput tests again. Failure to reload will result in
> incorrect benchmark results because queries will execute against modified data.
>
> **Proper workflow:** `generate` → `load` → `power` → `throughput` → `maintenance` → **[RELOAD before next power/throughput]**

The TPC-DS Maintenance Test simulates real-world data warehouse update operations by executing data modification statements (INSERT, UPDATE, DELETE) on sales and inventory tables. Unlike Power and Throughput Tests which only read data, **the Maintenance Test permanently changes database contents** by committing transactions that add, modify, and remove records.

#### What the Maintenance Test Does

TPC-DS maintenance operations simulate ongoing warehouse activity such as:
- **New sales transactions** arriving from retail channels
- **Customer returns** being processed
- **Inventory adjustments** based on physical counts
- **Data corrections** from source systems

The test executes a series of data modification operations across multiple tables, cycling through INSERT, UPDATE, and DELETE statements. Each operation modifies a portion of the database and is committed permanently.

#### Affected Tables

The Maintenance Test targets the following sales and inventory tables:

| Table             | Purpose                  | Operation Types        |
| ----------------- | ------------------------ | ---------------------- |
| `catalog_sales`   | Catalog channel sales    | INSERT, UPDATE, DELETE |
| `catalog_returns` | Catalog channel returns  | INSERT, UPDATE, DELETE |
| `web_sales`       | Web channel sales        | INSERT, UPDATE, DELETE |
| `web_returns`     | Web channel returns      | INSERT, UPDATE, DELETE |
| `store_sales`     | Store channel sales      | INSERT, UPDATE, DELETE |
| `store_returns`   | Store channel returns    | INSERT, UPDATE, DELETE |
| `inventory`       | Product inventory levels | INSERT, UPDATE, DELETE |

#### Data Volumes Modified

The amount of data modified depends on the scale factor and number of operations:

**Per-Operation Row Counts:**

| Operation Type | Rows Modified per SF | Example at SF=1 | Example at SF=10 |
| -------------- | -------------------- | --------------- | ---------------- |
| INSERT         | ~1,000               | ~1,000 rows     | ~10,000 rows     |
| UPDATE         | ~500                 | ~500 rows       | ~5,000 rows      |
| DELETE         | ~200                 | ~200 rows       | ~2,000 rows      |

**Default Configuration (4 operations):**

| Scale Factor | Total Rows Modified | INSERT Ops | UPDATE Ops | DELETE Ops |
| ------------ | ------------------- | ---------- | ---------- | ---------- |
| 0.1          | ~340 rows           | 2 ops      | 1 op       | 1 op       |
| 1.0          | ~3,400 rows         | 2 ops      | 1 op       | 1 op       |
| 10.0         | ~34,000 rows        | 2 ops      | 1 op       | 1 op       |
| 100.0        | ~340,000 rows       | 2 ops      | 1 op       | 1 op       |

*Note: The default configuration runs 4 operations that rotate through INSERT → UPDATE → DELETE → INSERT, affecting different tables in each operation.*

#### Why Database Reload Is Required

After running the Maintenance Test, **you must reload the database** before running Power or Throughput Tests again. Here's why:

1. **Data Changes Are Committed**: All INSERT, UPDATE, and DELETE operations are committed to the database. The modified data persists permanently.

2. **Query Results Will Differ**: Power and Throughput queries will execute against the modified dataset, producing different results than the baseline. Aggregate functions (SUM, COUNT, AVG) will calculate different values, and JOIN operations may match different rows.

3. **Not Idempotent**: Running the Maintenance Test multiple times modifies different data each time. There's no simple "undo" operation - you must restore from clean data.

4. **TPC Specification Requirement**: The official TPC-DS specification requires benchmarks run on consistent, unmodified datasets. Running Power/Throughput tests on post-maintenance data violates specification and produces invalid results.

#### Complete Code Example

Here's how to properly structure your benchmark workflow with database reload:

```python
from benchbox.tpcds import TPCDS
from benchbox.platforms.duckdb import DuckDBAdapter
from pathlib import Path

# Generate TPC-DS data
benchmark = TPCDS(scale_factor=1.0, output_dir=Path("./tpcds_data"))
benchmark.generate_data()

# Step 1: Run Power and Throughput tests on clean data
print("Step 1: Running Power and Throughput tests on clean database...")
adapter = DuckDBAdapter(database_path="tpcds.duckdb", force_recreate=True)

power_result = adapter.run_benchmark(benchmark, test_execution_type="power")
print(f"Power Test: {power_result.total_execution_time:.2f}s")

throughput_result = adapter.run_benchmark(benchmark, test_execution_type="throughput")
print(f"Throughput Test: {throughput_result.total_execution_time:.2f}s")

# Step 2: RELOAD database before Maintenance Test
# This ensures we start with clean data for maintenance operations
print("\n⚠️  Reloading database before Maintenance Test...")
adapter = DuckDBAdapter(database_path="tpcds.duckdb", force_recreate=True)

# Step 3: Run Maintenance Test (permanently modifies data)
print("\nStep 3: Running Maintenance Test (will modify database)...")
maintenance_result = adapter.run_benchmark(benchmark, test_execution_type="maintenance")
print(f"Maintenance Test: {maintenance_result.total_execution_time:.2f}s")
print(f"Operations executed: {maintenance_result.total_queries}")

# WARNING: Database now contains modified data
print("\n" + "=" * 70)
print("⚠️  WARNING: DATABASE HAS BEEN MODIFIED")
print("=" * 70)
print("The Maintenance Test permanently modified sales and inventory tables by:")
print(f"  • Inserting new sales/return/inventory records")
print(f"  • Updating existing records")
print(f"  • Deleting old records")
print()
print("To run Power or Throughput tests again, you MUST reload the database")
print("with fresh data. The current database contains modified data that will")
print("produce incorrect benchmark results.")
print("=" * 70)
```

#### CLI Usage

Run the Maintenance Test using the BenchBox CLI:

```bash
# Complete workflow with proper reload sequence
benchbox run \
  --platform duckdb \
  --benchmark tpcds \
  --scale 1.0 \
  --phases generate,load,power,throughput

# Reload database before maintenance
benchbox run \
  --platform duckdb \
  --benchmark tpcds \
  --scale 1.0 \
  --phases load,maintenance
```

#### Workflow Summary

```
✓ Correct:   generate → load → power → throughput → maintenance
✓ Correct:   generate → load → power → throughput → maintenance → [RELOAD] → power (if rerunning)
✗ Incorrect: generate → load → power → maintenance → throughput  ❌ (throughput runs on modified data!)
✗ Incorrect: generate → load → maintenance → power → throughput  ❌ (power/throughput run on modified data!)
```

**Key Principle**: Maintenance Test can run immediately after Power/Throughput (no reload needed before Maintenance). However, you **MUST reload** after Maintenance before running Power/Throughput again.

#### Access Maintenance Test Results

```python
# Run maintenance test
maintenance_result = adapter.run_benchmark(benchmark, test_execution_type="maintenance")

# Access detailed results
print(f"Total operations: {maintenance_result.total_queries}")
print(f"Total time: {maintenance_result.total_execution_time:.2f}s")
print(f"Average operation time: {maintenance_result.average_query_time:.2f}s")

# Individual operation timings
for query_result in maintenance_result.query_results:
    print(f"{query_result.query_id}: {query_result.execution_time:.3f}s")
```

**Characteristics:**
- Executes INSERT, UPDATE, DELETE operations across 7 tables
- Rotates through operation types (INSERT → UPDATE → DELETE)
- Modifies ~1,700 rows per operation at SF=1 (average)
- All operations are committed permanently
- Required for complete TPC-DS compliance testing

## Metrics and Calculations

### Official TPC-DS Metrics

The implementation calculates all official TPC-DS metrics according to the specification:

```python
# Access calculated metrics
result = benchmark.run_official_benchmark(connection_string)

print(f"Power@Size: {result.power_size:.2f} QphDS@Size")
print(f"Throughput@Size: {result.throughput_size:.2f} QphDS@Size")
print(f"QphDS@Size: {result.qphds_size:.2f} QphDS@Size")
```

### Calculation Details

#### Power@Size
```
Power@Size = (3600 × Scale_Factor) / Power_Test_Time
```

#### Throughput@Size
```
Throughput@Size = (Num_Streams × 3600 × Scale_Factor) / Throughput_Test_Time
```

#### QphDS@Size (Geometric Mean)
```
QphDS@Size = sqrt(Power@Size × Throughput@Size)
```

### Additional Metrics

The implementation also provides detailed metrics for each phase:

```python
# Power Test metrics
power_metrics = result.power_test.metrics
print(f"Average Query Time: {power_metrics['avg_query_time']:.3f}s")
print(f"Success Rate: {power_metrics['successful_queries'] / power_metrics['total_queries'] * 100:.1f}%")

# Throughput Test metrics
throughput_metrics = result.throughput_test.metrics
print(f"Queries per Stream: {throughput_metrics['queries_per_stream']}")
print(f"Concurrent Efficiency: {throughput_metrics.get('concurrent_efficiency', 'N/A')}")
```

## Reporting

The benchmark generates systematic reports in multiple formats automatically:

### Report Types

1. **Executive Summary** (`executive_summary.txt`)
   - High-level metrics and results
   - QphDS@Size and phase results
   - Overall benchmark status

2. **Detailed Analysis** (`detailed_analysis.txt`)
   - Phase-by-phase breakdown
   - Metric calculations
   - Performance analysis

3. **Query Analysis** (`query_analysis.txt`)
   - Query-level performance data
   - Execution times and statistics
   - Failure analysis

4. **JSON Export** (`benchmark_results.json`)
   - Machine-readable results
   - Complete data export
   - API integration ready

5. **CSV Export** (`query_results.csv`)
   - Spreadsheet-compatible format
   - Query execution data
   - Statistical analysis ready

6. **HTML Report** (`benchmark_report.html`)
   - Standalone report with formatted tables
   - Summary metrics and system information
   - Presentation ready

7. **Compliance Report** (`compliance_report.txt`)
   - TPC-DS compliance checklist
   - Validation results
   - Certification readiness

8. **Performance Summary** (`performance_summary.txt`)
   - Performance recommendations
   - Optimization suggestions
   - Benchmark insights

### Accessing Reports

```python
# Reports are automatically generated
result = benchmark.run_official_benchmark(connection_string)

# Reports location
reports_dir = benchmark.output_dir / "reports"
print(f"Reports generated in: {reports_dir}")

# List generated reports
for report_file in reports_dir.glob("*"):
    print(f"  - {report_file.name}")
```

### Custom Reporting

```python
from benchbox.core.tpcds.reporting import TPCDSReportGenerator

# Create custom report generator
generator = TPCDSReportGenerator(output_dir="/custom/path", verbose=True)

# Generate specific reports
reports = generator.generate_complete_report(result)
```

## Validation and Compliance

### Built-in Validation

The benchmark includes systematic validation to ensure TPC-DS compliance:

```python
# Validation is automatic
result = benchmark.run_official_benchmark(
    connection_string=connection_string,
    result_validation=True
)

# Check validation results
validation = result.validation_results
print(f"Overall Valid: {validation['overall_valid']}")
print(f"Power Test Valid: {validation['power_test_valid']}")
print(f"Throughput Test Valid: {validation['throughput_test_valid']}")
print(f"Maintenance Test Valid: {validation['maintenance_test_valid']}")

# Check for issues
if validation['issues']:
    print("Validation Issues:")
    for issue in validation['issues']:
        print(f"  - {issue}")
```

### Compliance Checklist

The validation framework checks:

- All 99 queries executed in Power Test
- Multi-stream execution in Throughput Test
- Refresh functions executed in Maintenance Test
- No query failures or errors
- Proper parameter generation
- Correct metric calculations
- Result data integrity
- Timing measurements accuracy

### Manual Validation

```python
# Access detailed validation information
for phase_name, phase_result in [
    ("Power Test", result.power_test),
    ("Throughput Test", result.throughput_test),
    ("Maintenance Test", result.maintenance_test)
]:
    if phase_result:
        success_rate = len([q for q in phase_result.queries if q.success]) / len(phase_result.queries)
        print(f"{phase_name}: {success_rate:.1%} success rate")
```

## Advanced-level Usage

### Custom Database Integration

```python
# Custom database connection handling
class CustomDatabaseBenchmark(TPCDSBenchmark):
    def run_official_benchmark(self, **kwargs):
        # Custom pre-processing
        self.setup_custom_database()

        # Run benchmark
        result = super().run_official_benchmark(**kwargs)

        # Custom post-processing
        self.cleanup_custom_database()

        return result
```

### Performance Tuning

```python
# Optimize for large scale factors
benchmark = TPCDSBenchmark(
    scale_factor=100.0,
    parallel=8,  # More parallel processes
    verbose=True
)

# Optimize for many streams
result = benchmark.run_official_benchmark(
    connection_string=connection_string,
    num_streams=16,  # High concurrency
    power_test=True,
    throughput_test=True,
    maintenance_test=False  # Skip if not needed
)
```

### Integration with CI/CD

```python
import sys

# CI/CD integration
def run_benchmark_ci():
    benchmark = TPCDSBenchmark(scale_factor=0.1, verbose=False)

    try:
        result = benchmark.run_official_benchmark(
            connection_string=os.getenv("DATABASE_URL"),
            num_streams=2,
            result_validation=True
        )

        # Check minimum performance threshold
        if result.qphds_size < 100:  # Example threshold
            print("Performance regression detected!")
            sys.exit(1)

        print(f"Benchmark passed: QphDS@Size = {result.qphds_size:.2f}")
        return True

    except Exception as e:
        print(f"Benchmark failed: {e}")
        sys.exit(1)
```

### Batch Processing

```python
# Run multiple benchmarks
scale_factors = [0.1, 1.0, 10.0]
results = []

for sf in scale_factors:
    benchmark = TPCDSBenchmark(scale_factor=sf)
    result = benchmark.run_official_benchmark(connection_string)
    results.append((sf, result.qphds_size))

# Analyze scaling behavior
for sf, qphds in results:
    print(f"Scale Factor {sf}: QphDS@Size = {qphds:.2f}")
```

## Troubleshooting

### Common Issues

#### 1. Database Connection Issues

```python
# Test connection before benchmark
try:
    result = benchmark.run_official_benchmark(connection_string)
except Exception as e:
    print(f"Connection failed: {e}")
    # Check connection string format
    # Verify database is running
    # Check credentials
```

#### 2. Memory Issues with Large Scale Factors

```python
# Optimize for large scale factors
benchmark = TPCDSBenchmark(
    scale_factor=100.0,
    parallel=1,  # Reduce parallel processes
    verbose=True
)

# Monitor memory usage
import psutil
print(f"Memory usage: {psutil.virtual_memory().percent}%")
```

#### 3. Query Timeouts

```python
# Increase timeout for slow queries
benchmark.timeout_seconds = 7200  # 2 hours
```

#### 4. Incomplete Results

```python
# Check for partial results
if not result.power_test or not result.throughput_test:
    print("Warning: Incomplete benchmark results")

# Check validation results
if result.validation_results.get('issues'):
    print("Validation issues found:")
    for issue in result.validation_results['issues']:
        print(f"  - {issue}")
```

### Debug Mode

```python
# Enable debug mode
import logging
logging.basicConfig(level=logging.DEBUG)

# Verbose benchmark execution
benchmark = TPCDSBenchmark(scale_factor=0.01, verbose=True)
result = benchmark.run_official_benchmark(connection_string)
```

### Error Recovery

```python
# Implement error recovery
def robust_benchmark_run(connection_string, max_retries=3):
    for attempt in range(max_retries):
        try:
            benchmark = TPCDSBenchmark(scale_factor=1.0, verbose=True)
            result = benchmark.run_official_benchmark(connection_string)
            return result
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                raise
            time.sleep(60)  # Wait before retry
```

## Best Practices

### 1. Scale Factor Selection

```python
# Choose appropriate scale factor
scale_factors = {
    "development": 0.01,    # ~10MB
    "testing": 0.1,         # ~100MB
    "small": 1.0,           # ~1GB
    "medium": 10.0,         # ~10GB
    "large": 100.0,         # ~100GB
    "enterprise": 1000.0    # ~1TB
}

benchmark = TPCDSBenchmark(scale_factor=scale_factors["testing"])
```

### 2. Resource Management

```python
# Proper resource management
with tempfile.TemporaryDirectory() as temp_dir:
    benchmark = TPCDSBenchmark(
        scale_factor=1.0,
        output_dir=temp_dir,
        verbose=True
    )

    try:
        result = benchmark.run_official_benchmark(connection_string)
        # Process results
    finally:
        # Cleanup is automatic with context manager
        pass
```

### 3. Performance Monitoring

```python
import time
import psutil

# Monitor benchmark performance
start_time = time.time()
start_memory = psutil.virtual_memory().used

result = benchmark.run_official_benchmark(connection_string)

end_time = time.time()
end_memory = psutil.virtual_memory().used

print(f"Benchmark time: {end_time - start_time:.2f}s")
print(f"Memory usage: {(end_memory - start_memory) / 1024 / 1024:.1f}MB")
```

### 4. Result Archival

```python
import json
from datetime import datetime

# Archive results for historical analysis
def archive_results(result):
    archive_data = {
        "timestamp": datetime.now().isoformat(),
        "qphds_size": result.qphds_size,
        "power_size": result.power_size,
        "throughput_size": result.throughput_size,
        "scale_factor": result.scale_factor,
        "configuration": result.configuration
    }

    with open(f"benchmark_archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", "w") as f:
        json.dump(archive_data, f, indent=2)
```

### 5. Continuous Benchmarking

```python
# Set up continuous benchmarking
def continuous_benchmark():
    benchmark = TPCDSBenchmark(scale_factor=1.0, verbose=False)

    baseline_qphds = 500.0  # Your baseline

    while True:
        result = benchmark.run_official_benchmark(connection_string)

        # Check for performance regression
        if result.qphds_size < baseline_qphds * 0.95:  # 5% tolerance
            alert_performance_regression(result)

        time.sleep(3600)  # Run every hour
```

## Conclusion

The TPC-DS official benchmark implementation provides a systematic, certification-ready solution for running TPC-DS benchmarks with official QphDS@Size metric calculation. The implementation follows TPC-DS specifications and includes extensive validation, reporting, and error handling capabilities.

For additional support:
- Review the integration tests in `tests/integration/test_tpcds_official_benchmark.py`
- Consult the TPC-DS specification at http://www.tpc.org/tpcds/

## References

- [TPC-DS Specification](http://www.tpc.org/tpcds/)
- [BenchBox Documentation](README.md)
- [TPC-DS Benchmark Overview](benchmarks/tpc-ds.md)
- [API Reference](../../reference/api-reference.md)
