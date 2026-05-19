<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Data Generation

```{tags} intermediate, guide, data-generation
```

BenchBox provides systematic data generation capabilities for all supported benchmarks. This guide covers both basic data generation concepts and the advanced smart data generation features that optimize performance and developer productivity.

## Overview

Data generation in BenchBox is designed to be:
- **Scalable**: Generate data from small test datasets to production-scale benchmarks
- **Intelligent**: Automatically validate and skip regeneration when valid data exists
- **Fast**: Optimized generation algorithms and caching
- **Reliable**: Comprehensive error handling and validation
- **Flexible**: Support for different output formats and directories

## Basic Data Generation

### Simple Generation

All benchmarks support a consistent `generate_data()` interface:

```python
from benchbox import TPCH, TPCDS

# Generate TPC-H data
tpch = TPCH(scale_factor=0.1)
tables = tpch.generate_data()
print(f"Generated {len(tables)} TPC-H tables")

# Generate TPC-DS data
tpcds = TPCDS(scale_factor=0.1)
tables = tpcds.generate_data()
print(f"Generated {len(tables)} TPC-DS tables")
```

### Scale Factor Configuration

Scale factors control the amount of data generated:

```python
# Development and testing - small datasets
benchmark = TPCH(scale_factor=0.001)  # ~1MB data

# CI/CD pipelines - fast execution
benchmark = TPCH(scale_factor=0.01)   # ~10MB data

# Performance testing - moderate size
benchmark = TPCH(scale_factor=0.1)    # ~100MB data

# Production validation - full scale
benchmark = TPCH(scale_factor=1.0)    # ~1GB data
```

### Output Directory Management

Control where data files are generated:

```python
from pathlib import Path

# Default location (current directory)
benchmark = TPCH(scale_factor=0.1)

# Custom directory
benchmark = TPCH(
    scale_factor=0.1,
    output_dir="./benchmark-data/tpch"
)

# Temporary directory for testing
import tempfile
temp_dir = tempfile.mkdtemp()
benchmark = TPCH(scale_factor=0.01, output_dir=temp_dir)
```

### Parallel Generation

Speed up data generation with parallel processing:

```python
# Use multiple processes for faster generation
benchmark = TPCH(
    scale_factor=1.0,
    parallel=4  # Use 4 parallel processes
)
tables = benchmark.generate_data()
```

## Smart Data Generation

BenchBox includes intelligent data generation that validates existing data and automatically skips regeneration when valid data is present.

### How Smart Generation Works

Smart generation follows this process:

1. **Check for existing data files** in the output directory
2. **Validate row counts** against expected values for the scale factor
3. **Verify file integrity** and minimum size requirements
4. **Handle platform-specific differences** (e.g., TPC-H minimum scale factors)
5. **Skip generation** if valid data exists, or regenerate if needed

### Default Behavior (Smart Generation)

Smart validation is enabled by default and works transparently:

```python
from benchbox import TPCH

# First run - no data exists, will generate
benchmark = TPCH(scale_factor=1.0, output_dir="./data")
tables = benchmark.generate_data()
# Output: ⚠️️ Data validation failed, generating TPC-H data...

# Second run - valid data exists, will skip
benchmark2 = TPCH(scale_factor=1.0, output_dir="./data")
tables2 = benchmark2.generate_data()
# Output: ✅ Valid TPC-H data found, skipping generation
```

### Force Regeneration

When you need to regenerate data regardless of existing files:

```python
# Force regeneration even if valid data exists
benchmark = TPCH(
    scale_factor=1.0,
    output_dir="./data",
    force_regenerate=True
)
tables = benchmark.generate_data()
# Output: ⚠️️ Force regeneration requested, generating data...
```

### Verbose Validation Reports

Enable detailed validation information:

```python
benchmark = TPCH(
    scale_factor=1.0,
    output_dir="./data",
    verbose=True
)
tables = benchmark.generate_data()
```

**Successful validation output:**
```
✅ Valid TPC-H data found for scale factor 1.0
✅ Data validation PASSED
   Validated 8 tables
   Total data size: 1.2 GB
   Skipping data generation
```

**Failed validation output:**
```
⚠️️  Data validation failed for scale factor 1.0
❌ Data validation FAILED
   Row count mismatches:
     customer: expected 150,000, found 75,000
     lineitem: expected 6,001,215, found 3,000,000
   Issues:
     - Table customer: expected ~150000 rows, found 75000 rows
     - Table lineitem: expected ~6001215 rows, found 3000000 rows
   Generating TPC-H data...
```

## Benchmark-Specific Generation

### TPC-H Data Generation

TPC-H uses the official dbgen tool for standards-compliant data:

```python
from benchbox import TPCH

# Standard generation
tpch = TPCH(scale_factor=1.0)
tables = tpch.generate_data()

# Expected tables and approximate row counts (SF=1.0)
tables_info = {
    'customer': 150_000,
    'lineitem': 6_001_215,
    'nation': 25,          # Fixed size
    'orders': 1_500_000,
    'part': 200_000,
    'partsupp': 800_000,
    'region': 5,           # Fixed size
    'supplier': 10_000
}
```

**TPC-H specific features:**
- Minimum scale factor of 0.1 (dbgen limitation)
- Fixed-size dimension tables (nation, region)
- Standards-compliant data distribution

### CoffeeShop Data Generation

The CoffeeShop benchmark has been rewritten to align with the public reference
generator. It now produces three tables (`dim_locations`, `dim_products`, and
`order_lines`) with an exploded fact table that averages 1.5 lines per order.

```python
from benchbox import CoffeeShop

# Reference-aligned generator (small scale for development)
coffeeshop = CoffeeShop(scale_factor=0.001)
data_files = coffeeshop.generate_data()
print(data_files["order_lines"])  # Path to generated CSV file
```

Scale factors map directly to order counts using the approved formula
`order_count = 50_000_000 * scale_factor`. The table below outlines the
recommended operating ranges:

| Scale Factor | Orders Generated | Approx. Order Lines | Approx. Size |
|--------------|-----------------|---------------------|--------------|
| 0.001        | 50,000          | ~75,000             | ~5 MB        |
| 0.01         | 500,000         | ~750,000            | ~50 MB       |
| 0.1          | 5,000,000       | ~7,500,000          | ~500 MB      |
| 1.0          | 50,000,000      | ~75,000,000         | ~5 GB        |

**CoffeeShop specific highlights:**
- Seasonal (monthly) weighting, regional bias, and linear growth trend.
- Deterministic order-line explosion following the 60/30/5/4/1 distribution.
- Vendored seed files for locations and products ensure deterministic IDs and pricing windows.
- Default output directories align with the BenchBox data layout (`benchmark_runs/datagen/coffeeshop_{format_scale_factor(scale)}` regardless of whether you use the high-level `CoffeeShop` wrapper or instantiate the generator directly) and honour optional compression settings.
- Query suite updated (``SA*``, ``PR*``, ``TR*``, ``TM*``, ``QC*``) to operate exclusively on the new schema.
- Repeated runs with the same inputs overwrite the existing CSV files deterministically, ensuring identical table contents across regenerations.
- Seed CSVs are vendored verbatim from `JosueBogran/coffeeshopdatageneratorv2` (MIT licensed, commit ``2a99993b6bca94c0bc04fae7c695e86cd152add1``) and verified via SHA256 checksums in the unit test suite.

### TPC-DS Data Generation

TPC-DS uses the official dsdgen tool for complex analytical data:

```python
from benchbox import TPCDS

# Standard generation
tpcds = TPCDS(scale_factor=1.0)
tables = tpcds.generate_data()

# TPC-DS generates 24 tables with complex relationships
print(f"Generated {len(tables)} TPC-DS tables")
```

**TPC-DS specific features:**
- 24 interconnected tables
- Complex dimension and fact table relationships
- Time-series data with seasonal patterns
- Advanced-level query generation integration
- **Streaming output** via `-FILTER Y` flag (see below)

#### TPC-DS Streaming Generation

BenchBox includes patched dsdgen binaries that support streaming data to stdout,
enabling efficient compression pipelines:

```bash
# Generate table directly to compressed file
dsdgen -TABLE ship_mode -SCALE 1 -FILTER Y | zstd > ship_mode.dat.zst

# Generate with fixed seed for reproducibility
dsdgen -TABLE date_dim -SCALE 1 -FILTER Y -RNGSEED 12345 | gzip > date_dim.dat.gz
```

This streaming capability reduces disk I/O and memory usage for large-scale data
generation. See [TPC-DS Streaming Data Generation](../benchmarks/tpc-ds.md#streaming-data-generation)
for detailed examples.

### Primitives Benchmark - Shared TPC-H Data

The Read Primitives benchmark automatically shares data with TPC-H to avoid duplication:

```python
from benchbox import ReadPrimitives

# Read Primitives automatically uses TPC-H data
read_primitives = ReadPrimitives(scale_factor=0.1)
tables = read_primitives.generate_data()
```

**How Primitives Data Sharing Works:**

1. **Automatic Path Selection**: Primitives defaults to the same data directory as TPC-H (`tpch_sf*`), not a separate `primitives_sf*` directory
2. **Shared Data Files**: Primitives uses TPC-H tables (customer, orders, lineitem, etc.) directly
3. **No Duplication**: One set of TPC-H data serves both benchmarks, saving disk space and generation time
4. **Manifest Compatibility**: Primitives accepts TPC-H manifests without modification

**Benefits of Data Sharing:**

- **Disk Space Savings**: Eliminates duplicate TPC-H data (saves GBs for larger scale factors)
- **Faster Setup**: If TPC-H data exists, Primitives uses it immediately without regeneration
- **Consistency**: Both benchmarks use identical data, ensuring comparable results

**Example - Shared Data Usage:**

```python
from benchbox import TPCH, Primitives

# Generate TPC-H data once
tpch = TPCH(scale_factor=1.0)  # Data goes to: data/tpch_sf1.0/
tpch_tables = tpch.generate_data()

# Primitives automatically uses the same data
read_primitives = ReadPrimitives(scale_factor=1.0)  # Also uses: data/tpch_sf1.0/
prim_tables = read_primitives.generate_data()  # No regeneration needed!

# Both benchmarks share the same table files
assert tpch_tables['customer'] == prim_tables['customer']  # Same file path
```

**Custom Output Paths:**

You can still use custom paths for isolated Primitives data:

```python
# Isolated Primitives data (won't share with TPC-H)
read_primitives = ReadPrimitives(
    scale_factor=0.1,
    output_dir="./custom-primitives-data"
)
tables = read_primitives.generate_data()  # Generates fresh TPC-H data here
```

### Other Benchmarks

```python
# SSB (Star Schema Benchmark)
from benchbox import SSB
ssb = SSB(scale_factor=1.0)
tables = ssb.generate_data()
```

## Data Validation

### Automatic Validation

Smart generation automatically validates:

- **File existence**: All required table files present
- **Row counts**: Match expected values for scale factor
- **File sizes**: Meet minimum size requirements
- **Data integrity**: Files are readable and non-empty

### Manual Validation

Access validation directly for custom workflows:

```python
from benchbox.utils.data_validation import BenchmarkDataValidator

# Create validator for specific benchmark
validator = BenchmarkDataValidator("tpch", scale_factor=1.0)

# Validate a data directory
result = validator.validate_data_directory("./data")

# Check results
if result.valid:
    print("✅ Data is valid")
    print(f"Validated {len(result.tables_validated)} tables")
else:
    print(f"❌ Validation failed: {len(result.issues)} issues")
    for issue in result.issues:
        print(f"  - {issue}")

# Print detailed report
validator.print_validation_report(result, verbose=True)
```

### Custom Validation Rules

For advanced validation scenarios:

```python
# Check if regeneration is needed
should_regenerate, result = validator.should_regenerate_data("./data")

if should_regenerate:
    print("Data needs regeneration:")
    for issue in result.issues:
        print(f"  - {issue}")
else:
    print("Existing data is valid")

# Force regeneration programmatically
force_regen = len(result.row_count_mismatches) > 0
benchmark = TPCH(scale_factor=1.0, force_regenerate=force_regen)
```

## Performance Optimization

### Smart Generation Benefits

Smart data generation avoids regenerating valid data:

- **Initial run**: Full data generation (time depends on scale factor, hardware, and CPU cores)
- **Subsequent runs**: Validation only - checks existing files and skips generation if valid

This provides significant time savings for iterative development workflows, CI/CD pipelines, and repeated benchmark runs regardless of scale factor.

### Parallel Processing

Use parallel generation for large scale factors:

```python
import multiprocessing

# Use all available CPU cores
cores = multiprocessing.cpu_count()
benchmark = TPCH(scale_factor=10.0, parallel=cores)
tables = benchmark.generate_data()
```

### Caching Strategies

Organize data for maximum reuse:

```bash
# Organize by benchmark and scale factor
./benchmark-data/
  ├── tpch/
  │   ├── sf-0.01/    # Small datasets for quick testing
  │   ├── sf-0.1/     # Medium datasets for CI/CD
  │   ├── sf-1.0/     # Large datasets for performance testing
  │   └── sf-10.0/    # Production-scale datasets
  └── tpcds/
      ├── sf-0.01/
      └── sf-1.0/
```

## Configuration Options

### Constructor Parameters

All benchmarks support these common parameters:

```python
benchmark = TPCH(
    scale_factor=1.0,           # Data scale factor
    output_dir="./data",        # Output directory
    verbose=True,               # Show detailed output
    force_regenerate=False,     # Skip smart validation
    parallel=1                  # Parallel generation processes
)
```

### Environment Variables

Control behavior globally via environment variables:

```bash
# Force regeneration for all benchmarks
export BENCHBOX_FORCE_REGENERATE=true

# Enable verbose output
export BENCHBOX_VERBOSE=true

# Set default output directory
export BENCHBOX_DATA_DIR=./benchmark_runs/datagen
```

### Platform-Specific Settings

Some platforms have special considerations:

```python
# ClickHouse - handles large scale factors efficiently
benchmark = TPCH(scale_factor=100.0, platform="clickhouse")

# DuckDB - configured for analytical workloads
benchmark = TPCH(scale_factor=10.0, platform="duckdb")
```

## Advanced-level Usage

### Data Format Conversion

Generate data in different formats:

```python
# Generate standard delimited files
tpch = TPCH(scale_factor=0.1)
tables = tpch.generate_data()

# Convert to Parquet (if pyarrow available)
for table_name, file_path in tables.items():
    parquet_path = file_path.with_suffix('.parquet')
    # Conversion code here
```

### Custom Data Directories

Implement custom directory structures:

```python
from pathlib import Path
from datetime import datetime

# Timestamp-based directories
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
data_dir = Path(f"./runs/{timestamp}/tpch_sf1")

benchmark = TPCH(scale_factor=1.0, output_dir=data_dir)
tables = benchmark.generate_data()
```

### Integration with CI/CD

Cache data between runs:

```yaml
# GitHub Actions example
- name: Cache benchmark data
  uses: actions/cache@v3
  with:
    path: ./benchmark-data
    key: benchbox-data-${{ runner.os }}-${{ hashFiles('**/benchmark-config.yaml') }}

- name: Generate benchmark data
  run: |
    python -c "
    from benchbox import TPCH
    tpch = TPCH(scale_factor=0.01, output_dir='./benchmark-data/tpch')
    tpch.generate_data()
    "
```

## Error Handling

### Common Issues and Solutions

#### Scale Factor Mismatches

**Problem**: Existing data was generated with different scale factor
```python
# Solution 1: Use matching scale factor
benchmark = TPCH(scale_factor=0.5)  # Match existing data

# Solution 2: Force regeneration with new scale factor
benchmark = TPCH(scale_factor=1.0, force_regenerate=True)
```

#### Missing or Corrupted Files

**Problem**: Some data files are missing or corrupted
```python
# Smart generation automatically detects and regenerates
benchmark = TPCH(scale_factor=1.0, verbose=True)
tables = benchmark.generate_data()
# Output: "Missing files detected, regenerating all data"
```

#### Permission Errors

**Problem**: Cannot read/write data files
```bash
# Fix directory permissions
chmod 755 ./data
chown $USER:$USER ./data
```

#### Disk Space Issues

**Problem**: Not enough space for large scale factors
```python
# Check required space before generation
def estimate_data_size(benchmark, scale_factor):
    base_size_mb = {
        'tpch': 1000,    # ~1GB for SF=1.0
        'tpcds': 2000,   # ~2GB for SF=1.0
    }
    return base_size_mb.get(benchmark, 1000) * scale_factor

required_mb = estimate_data_size('tpch', 10.0)
print(f"Required space: ~{required_mb}MB")
```

### Debug Mode

Enable detailed debugging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

benchmark = TPCH(scale_factor=1.0, verbose=True)
tables = benchmark.generate_data()
# Shows detailed generation and validation steps
```

## Best Practices

### Development Workflow

1. **Start Small**: Use scale factors 0.001-0.01 during development
2. **Cache Aggressively**: Reuse generated data when possible
3. **Validate Early**: Test with small datasets before scaling up
4. **Monitor Resources**: Track memory and disk usage

```python
# Development pattern
def setup_benchmark(scale_factor=0.01):
    """Setup benchmark with smart caching."""
    data_dir = Path("./dev-cache") / f"tpch-sf{scale_factor}"
    return TPCH(scale_factor=scale_factor, output_dir=data_dir, verbose=True)

# Use in development
tpch = setup_benchmark()  # Uses cache if available
tables = tpch.generate_data()
```

### Production Deployment

1. **Pre-generate Data**: Generate data during deployment, not runtime
2. **Validate Integrity**: Always validate data before benchmarks
3. **Monitor Performance**: Track generation time and data quality
4. **Plan Storage**: Estimate storage requirements for scale factors

```python
# Production pattern
def setup_production_benchmark(scale_factor=1.0):
    """Setup production benchmark with validation."""
    data_dir = Path("/opt/benchmark-data") / f"tpch-sf{scale_factor}"

    benchmark = TPCH(
        scale_factor=scale_factor,
        output_dir=data_dir,
        verbose=True,
        parallel=multiprocessing.cpu_count()
    )

    # Pre-validate or generate
    tables = benchmark.generate_data()

    # Additional validation
    validator = BenchmarkDataValidator("tpch", scale_factor)
    result = validator.validate_data_directory(data_dir)

    if not result.valid:
        raise RuntimeError(f"Data validation failed: {result.issues}")

    return benchmark, tables
```

### Testing Strategy

1. **Unit Tests**: Test generation with small scale factors
2. **Integration Tests**: Validate full benchmark workflows
3. **Performance Tests**: Measure generation performance
4. **Regression Tests**: Detect data quality changes

```python
import pytest
import tempfile

def test_data_generation():
    """Test basic data generation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        benchmark = TPCH(scale_factor=0.001, output_dir=temp_dir)
        tables = benchmark.generate_data()

        # Validate results
        assert len(tables) == 8
        for table_path in tables.values():
            assert table_path.exists()
            assert table_path.stat().st_size > 0

def test_smart_generation():
    """Test smart generation skip logic."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # First generation
        benchmark1 = TPCH(scale_factor=0.001, output_dir=temp_dir)
        tables1 = benchmark1.generate_data()

        # Second generation should skip
        benchmark2 = TPCH(scale_factor=0.001, output_dir=temp_dir, verbose=True)
        tables2 = benchmark2.generate_data()

        # Should return same tables
        assert tables1.keys() == tables2.keys()
```

## Supported Benchmarks

Data generation support by benchmark:

| Benchmark      | Smart Generation | Row Validation | Parallel Support | Notes                     |
| -------------- | ---------------- | -------------- | ---------------- | ------------------------- |
| **TPC-H**      | ✅ Full           | ✅ Yes          | ✅ Yes            | Official dbgen tool       |
| **TPC-DS**     | ✅ Full           | ✅ Yes          | ✅ Yes            | Official dsdgen tool      |
| **Read Primitives** | ✅ Full           | ✅ Yes          | ✅ Yes            | Shares TPC-H data         |
| **SSB**        | ⚠️️ Basic          | ❌ No           | ✅ Yes            | Will be improved          |
| **ClickBench** | ⚠️️ Basic          | ❌ No           | ❌ No             | External data             |
| **Join Order** | ✅ Downloaded      | ✅ Hashes/rows   | ❌ No             | Canonical IMDb JOB data, `SF=1` only |
| **Others**     | ⚠️️ Basic          | ❌ No           | ❌ No             | Being improved            |

## Future Enhancements

Planned data generation improvements:

- **Checksum Validation**: Verify data integrity using file checksums
- **Schema Validation**: Check table structure and column types
- **Compression Support**: Handle compressed data files (.gz, .bz2)
- **Remote Data**: Support cloud-stored benchmark datasets
- **Incremental Updates**: Update only changed tables
- **Cross-Platform Sync**: Share data between database platforms
- **Format Conversion**: Auto-convert between CSV, Parquet, etc.
- **Resource Estimation**: Predict generation time and space requirements

## Troubleshooting

### Performance Issues

```python
# Monitor generation performance
import time

start_time = time.time()
benchmark = TPCH(scale_factor=1.0, verbose=True, parallel=4)
tables = benchmark.generate_data()
generation_time = time.time() - start_time

print(f"Generated {len(tables)} tables in {generation_time:.2f} seconds")
print(f"Average: {generation_time/len(tables):.2f}s per table")
```

### Memory Issues

```python
# For large scale factors, monitor memory usage
import psutil

def monitor_generation():
    process = psutil.Process()

    print(f"Memory before: {process.memory_info().rss / 1024**2:.1f} MB")

    benchmark = TPCH(scale_factor=10.0, parallel=2)
    tables = benchmark.generate_data()

    print(f"Memory after: {process.memory_info().rss / 1024**2:.1f} MB")
    return tables
```

### Validation Issues

```python
# Debug validation problems
from benchbox.utils.data_validation import BenchmarkDataValidator

validator = BenchmarkDataValidator("tpch", scale_factor=1.0)
result = validator.validate_data_directory("./data")

# Detailed analysis
if not result.valid:
    print("Validation Issues:")
    print(f"Missing tables: {result.missing_tables}")
    print(f"Row count mismatches: {result.row_count_mismatches}")
    print(f"File size issues: {[f for f, size in result.file_size_info.items() if size == 0]}")
```

Data generation in BenchBox is designed to be powerful, intelligent, and developer-friendly. The smart generation features ensure appropriate performance while maintaining data integrity and standards compliance.
