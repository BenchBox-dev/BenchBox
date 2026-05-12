# Data Compression in BenchBox

```{tags} intermediate, guide, data-generation
```

BenchBox provides comprehensive data compression support to reduce storage requirements and improve I/O performance during benchmark data generation.

## Overview

The compression system offers:
- **6-8x storage reduction** for typical benchmark data
- **Multiple compression algorithms** (Gzip, Zstd, or no compression)
- **Streaming compression** without intermediate uncompressed files
- **Transparent integration** with existing data generators
- **Configurable compression levels** for performance tuning

## Quick Start

### CLI Usage

Enable compression with command-line options:

```bash
# Basic compression (uses zstd by default)
benchbox run --platform duckdb --benchmark tpch --compression zstd

# Specify compression type and level
benchbox run --platform duckdb --benchmark tpch --compression gzip:9

# Use zstd with custom level for maximum compression
benchbox run --platform snowflake --benchmark tpcds --compression zstd:19

# Disable compression
benchbox run --platform duckdb --benchmark tpch --compression none
```

### Programmatic Usage

```python
from benchbox.core.ssb.benchmark import SSBBenchmark

# Create benchmark with compression
benchmark = SSBBenchmark(
    scale_factor=1.0,
    output_dir="./data",
    compress_data=True,
    compression_type='zstd',
    compression_level=5
)

# Generate compressed data
data_files = benchmark.generate_data()
# Files will be saved as .zst files with automatic compression
```

## Compression Types

### Zstd (Default, Recommended)
- **Best overall performance** and compression ratio
- **Compression levels**: 1-22 (default: 3)
- **Typical ratios**: 6-10:1 for benchmark data
- **Use case**: Default choice for most scenarios

```bash
benchbox run --platform duckdb --benchmark tpch --compression zstd
```

### Gzip (Universal Compatibility)
- **Widely supported** across platforms
- **Compression levels**: 1-9 (default: 6)
- **Typical ratios**: 5-8:1 for benchmark data
- **Use case**: Maximum compatibility requirements

```bash
benchbox run --platform duckdb --benchmark tpch --compression gzip
```

### None (No Compression)
- **Standard uncompressed files**
- **Use case**: When compression is not desired or supported

```bash
benchbox run --platform duckdb --benchmark tpch --compression none
```

## Performance Results

Based on testing with SSB benchmark data:

| Compression | File Size | Compression Ratio | Space Savings |
|-------------|-----------|-------------------|---------------|
| None        | 215,514 bytes | 1.00:1 | 0% |
| Gzip        | 32,730 bytes  | 6.58:1 | 85% |
| Zstd        | 26,944 bytes  | 8.00:1 | 87.5% |

## Compression Levels

### Gzip Levels (1-9)
- **Level 1**: Fastest compression, lower ratio
- **Level 6**: Default, good balance
- **Level 9**: Maximum compression, slower

```bash
# Fast compression
benchbox run --platform duckdb --benchmark tpch --compression gzip:1

# Maximum compression
benchbox run --platform duckdb --benchmark tpch --compression gzip:9
```

### Zstd Levels (1-22)
- **Level 1**: Fastest compression
- **Level 3**: Default, excellent balance
- **Level 19**: Maximum compression (higher levels exist but take 10x+ longer)

```bash
# Fast compression
benchbox run --platform duckdb --benchmark tpch --compression zstd:1

# High compression
benchbox run --platform duckdb --benchmark tpch --compression zstd:15
```

## Supported Generators

Compression is available across all BenchBox data generators. The following generators use the `CompressionMixin` for streaming compression during data generation:

- **TPC-H, TPC-DS, SSB** - Compression supported since v0.1.2
- **CoffeeShop, AMPLab, H2O.db** - Compression supported since v0.1.2
- **TSBS DevOps** - Compression support added in v0.2.1
- **FlightData** - Compression support added in v0.2.1
- **NYC Taxi** (Yellow, Green, and HVFHV downloaders) - Compression support added in v0.2.1

All generators that support compression write a `_datagen_manifest.json` with compression metadata and per-table row counts.

`joinorder` is fixed-size canonical data rather than a generated CSV workload:
BenchBox downloads a compressed, manifest-verified Parquet package for
`joinorder-imdb-2013-v1` and accepts only `--scale 1`.

## Integration with Data Generators

### Adding Compression Support to New Generators

To add compression support to a custom data generator:

```python
from benchbox.utils.compression_mixin import CompressionMixin

class MyDataGenerator(CompressionMixin):
    def __init__(self, scale_factor=1.0, output_dir=None, **kwargs):
        # Initialize compression mixin
        super().__init__(**kwargs)

        self.scale_factor = scale_factor
        self.output_dir = Path(output_dir) if output_dir else Path.cwd()

    def generate_data(self):
        """Generate data with optional compression."""
        # Get compressed filename
        filename = self.get_compressed_filename("data.csv")
        file_path = self.output_dir / filename

        # Open file with compression if enabled
        with self.open_output_file(file_path, "wt") as f:
            writer = csv.writer(f)
            # Write data...

        # Print compression report if enabled
        if self.should_use_compression():
            files = {"data": file_path}
            self.print_compression_report(files)

        return {"data": str(file_path)}
```

### Benchmark Integration

To integrate compression into benchmark classes:

```python
class MyBenchmark(BaseBenchmark):
    def __init__(self, scale_factor=1.0, **config):
        super().__init__(scale_factor, **config)

        # Pass compression settings to data generator
        self.data_generator = MyDataGenerator(
            scale_factor=scale_factor,
            output_dir=self.output_dir,
            compress_data=config.get('compress_data', False),
            compression_type=config.get('compression_type', 'zstd'),
            compression_level=config.get('compression_level', None)
        )
```

## Platform Adapter Support

Platform adapters automatically detect and load compressed data files. During data loading, BenchBox inspects each file's extension (e.g., `.zst`, `.gz`) using `detect_compression()` and passes the appropriate compression codec to the reader. No user configuration is required -- compressed files generated by `benchbox run --compression zstd` are loaded transparently on subsequent runs.

### How It Works

- **DuckDB, DataFusion, ClickHouse**: Native support for zstd-compressed files via their built-in readers.
- **Spark-based platforms** (Apache Spark, LakeSail): BenchBox detects compression from the file extension and sets the Spark CSV reader's `compression` option automatically. This is required because some engines (notably LakeSail/Sail) default to `UNCOMPRESSED` and do not auto-detect compression from file extensions.
- **DataFrame platforms** (Polars, Pandas, cuDF): Compression is handled by the underlying library's reader (e.g., Polars natively reads `.csv.zst` files).

## Advanced Usage

### Custom Compression Levels by Use Case

```bash
# CI/CD environments - prioritize speed
benchbox run --platform duckdb --benchmark tpch --compression zstd:1

# Storage-constrained environments - prioritize size
benchbox run --platform duckdb --benchmark tpch --compression zstd:19

# Production benchmarking - balanced performance
benchbox run --platform duckdb --benchmark tpch --compression zstd  # Uses default level 3
```

### Dry Run with Compression

Preview compression settings without execution:

```bash
benchbox run --platform duckdb --benchmark tpch --scale 1.0 \
  --compression zstd:5 --dry-run ./preview
```

### Environment Variables

Set compression defaults via environment variables:

```bash
export BENCHBOX_COMPRESS_DATA=true
export BENCHBOX_COMPRESSION_TYPE=zstd
export BENCHBOX_COMPRESSION_LEVEL=5

benchbox run --platform duckdb --benchmark tpch
```

## Best Practices

### When to Use Compression

**✅ Recommended for:**
- Large scale factors (≥1.0)
- Storage-constrained environments
- CI/CD pipelines
- Network file systems
- Repeated benchmark runs

**❌ Consider avoiding for:**
- Very small datasets (scale < 0.1)
- Platforms that don't support compressed files
- Time-critical scenarios where compression overhead matters

### Compression Type Selection

**Use Zstd when:**
- You want the best compression ratio and speed
- Storage space is a primary concern
- You're using modern systems

**Use Gzip when:**
- You need maximum compatibility
- Downstream tools only support gzip
- You're working with legacy systems

**Use None when:**
- Dataset is very small
- Platform adapters don't support decompression
- Debugging file contents manually

### Performance Tuning

**For Speed:**
```bash
benchbox run --platform duckdb --benchmark tpch --compression zstd:1
```

**For Size:**
```bash
benchbox run --platform duckdb --benchmark tpch --compression zstd:15
```

**For Balance:**
```bash
benchbox run --platform duckdb --benchmark tpch --compression zstd  # Uses default level 3
```

## Troubleshooting

### Common Issues

**"zstandard library not available"**
```bash
# Install zstandard
uv pip install zstandard
# or
pip install zstandard
```

**"Compressed file not found"**
- Check that `--compress-data` flag was used during generation
- Verify file extensions (.gz, .zst)
- Ensure compression completed successfully

**"Decompression failed"**
- File may be corrupted during transfer
- Check compression/decompression compatibility
- Verify sufficient disk space

### Debug Mode

Enable verbose logging to troubleshoot compression:

```bash
benchbox run --platform duckdb --benchmark tpch --compress-data --verbose
```

### File Verification

Verify compressed file integrity:

```python
from benchbox.utils.compression import CompressionManager

manager = CompressionManager()
compression_type = manager.detect_compression(Path("data.csv.gz"))
compressor = manager.get_compressor(compression_type)

# Test decompression
try:
    with compressor.open_for_read(Path("data.csv.gz"), 'rt') as f:
        content = f.read(100)  # Read first 100 characters
    print("File is valid")
except Exception as e:
    print(f"File is corrupted: {e}")
```

## API Reference

### CompressionManager

```python
from benchbox.utils.compression import CompressionManager

manager = CompressionManager()

# Get available compressors
compressors = manager.get_available_compressors()

# Get specific compressor
compressor = manager.get_compressor('zstd', level=5)

# Detect compression type
compression_type = manager.detect_compression(Path("file.csv.gz"))

# Get compression statistics
info = manager.get_compression_info(original_file, compressed_file)
```

### CompressionMixin

```python
from benchbox.utils.compression_mixin import CompressionMixin

class MyGenerator(CompressionMixin):
    # Mixin methods available:
    # - get_compressed_filename(filename) -> str
    # - open_output_file(path, mode) -> file_object
    # - compress_existing_file(path) -> Path
    # - should_use_compression() -> bool
    # - print_compression_report(files) -> None
```

### CLI Options

```bash
--compression TYPE[:LEVEL]   # Compression: zstd, zstd:9, gzip:6, none
                             # Examples: --compression zstd
                             #           --compression zstd:15
                             #           --compression gzip:9
                             #           --compression none
```

## Examples Repository

For more examples, see the `/examples` directory:

- `examples/duckdb_tpch_compressed.py` - TPC-H with compression
- `examples/compression_performance.py` - Performance testing
- `examples/multi_benchmark_compression.py` - Multiple benchmarks with compression
