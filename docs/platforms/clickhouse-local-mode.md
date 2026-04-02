# ClickHouse Local Mode

```{tags} intermediate, guide, clickhouse, embedded-platform
```

BenchBox supports ClickHouse in two deployment modes, plus a separate first-class cloud platform:

- **Local Mode**: Uses chDB for in-process ClickHouse engine (default)
- **Server Mode**: Connects to an external ClickHouse server
- **ClickHouse Cloud**: Separate first-class platform → see [ClickHouse Cloud](clickhouse-cloud.md)

```{note}
**ClickHouse Cloud** is now a first-class platform (`--platform clickhouse-cloud`), not a deployment mode. This follows the pattern established by MotherDuck and Starburst.
```

## Overview

ClickHouse Local Mode uses [chDB](https://github.com/chdb-io/chdb), the official embedded ClickHouse engine, to run ClickHouse queries directly in Python without requiring a separate ClickHouse server installation.

### Key Benefits

- **Zero Server Setup**: No ClickHouse server installation required
- **Native Performance**: In-process execution eliminates IPC overhead
- **Development Friendly**: Perfect for testing, development, and quick analysis
- **Same SQL Compatibility**: Full ClickHouse SQL dialect support
- **Easy Installation**: Single `pip install chdb` command

## Installation

### Prerequisites

- Python 3.10+
- Supported platforms: macOS and Linux (x86_64 and ARM64)

### Install chDB

```bash
# Install chDB for embedded mode support
pip install chdb

# Verify installation
python -c "import chdb; print(chdb.chdb_version())"
```

### Install BenchBox with ClickHouse Support

```bash
# Install BenchBox (if not already installed)
uv add benchbox

# Or with pip
pip install benchbox
```

## Usage

### Basic Usage

```bash
# Run TPC-H benchmark in embedded mode
benchbox run tpch --platform=clickhouse --mode=local --scale-factor=0.01

# Run with custom data path
benchbox run tpch --platform=clickhouse --mode=local --data-path=/tmp/benchmark_data

# Compare with server mode
benchbox run tpch --platform=clickhouse --mode=server --host=localhost --port=9000
```

### CLI Arguments

#### Mode Selection
- `--mode=local` - Use embedded ClickHouse via chDB
- `--mode=server` - Use ClickHouse server (default)

#### Embedded Mode Specific Arguments
- `--data-path=PATH` - Optional data path for file operations

#### Server Mode Arguments (not used in embedded mode)
- `--host=HOST` - ClickHouse server host
- `--port=PORT` - ClickHouse server port
- `--user=USER` - Username for server authentication
- `--password=PASS` - Password for server authentication
- `--secure` - Use TLS connection

## Performance Characteristics

### Embedded Mode
- **Memory Usage**: Lower baseline memory (~50-200MB)
- **Startup Time**: No network connection setup required
- **Query Execution**: Columnar engine for analytical workloads
- **Scalability**: Suited for small to medium datasets (< 10GB)
- **Concurrency**: Single-process, sequential query execution

### Server Mode
- **Memory Usage**: Higher baseline (server overhead)
- **Startup Time**: Network connection overhead
- **Query Execution**: Same columnar engine, distributed architecture available
- **Scalability**: Designed for large datasets (TB+)
- **Concurrency**: Multi-client support, parallel query execution

## When to Use Each Mode

### Use Embedded Mode When:
- **Development & Testing**: Quick benchmark development and validation
- **CI/CD Pipelines**: Automated testing without infrastructure setup
- **Data Analysis**: Interactive data exploration and analysis
- **Prototyping**: Rapid benchmark prototyping and iteration
- **Small to Medium Data**: Datasets under 10GB
- **Single-User Scenarios**: Personal analysis and development

### Use Server Mode When:
- **Production Benchmarking**: Large-scale production environment testing
- **Large Datasets**: Working with multi-TB datasets
- **Multi-User Access**: Shared benchmark environments
- **Enterprise Deployments**: Integration with existing ClickHouse infrastructure
- **Performance Testing**: Maximum throughput and scalability testing
- **Cluster Configurations**: Testing distributed ClickHouse setups


## Examples

### TPC-H Benchmark
```bash
# Small scale for development
benchbox run tpch --platform=clickhouse --mode=local --scale-factor=0.01

# Medium scale for testing
benchbox run tpch --platform=clickhouse --mode=local --scale-factor=1.0
```

### ClickBench Benchmark
```bash
# Run ClickBench analytical queries
benchbox run clickbench --platform=clickhouse --mode=local
```

### Custom Data Directory
```bash
# Use specific directory for generated data
benchbox run tpch \
  --platform=clickhouse \
  --mode=local \
  --scale-factor=0.1 \
  --data-path=/path/to/benchmark/data
```

## Troubleshooting

### Common Issues and Solutions

#### 1. chDB Not Installed
```
Error: ClickHouse local mode requires chDB but it is not installed.
```

**Solution:**
```bash
pip install chdb
```

#### 2. Platform Not Supported
```
Error: chDB installation failed or not compatible with your platform
```

**Solution:**
- Ensure you're on macOS or Linux (x86_64/ARM64)
- Try upgrading pip: `pip install --upgrade pip`
- Check Python version: `python --version` (3.8+ required)

#### 3. Memory Issues with Large Datasets
```
Error: Memory limit exceeded or system running out of memory
```

**Solution:**
- Use smaller scale factors for testing
- Switch to server mode for large datasets
- Monitor system memory usage

#### 4. Query Performance Issues
```
Queries running slower than expected in embedded mode
```

**Solution:**
- Embedded mode is optimized for small-medium datasets
- For large datasets or maximum performance, use server mode
- Consider data partitioning or smaller scale factors

### Getting Help

1. **Check Installation**: Verify chDB is properly installed
   ```bash
   python -c "import chdb; print('chDB version:', chdb.chdb_version())"
   ```

2. **Verbose Output**: Run with verbose logging
   ```bash
   benchbox run tpch --platform=clickhouse --mode=local --verbose
   ```

3. **Compare Modes**: Test both modes to isolate issues
   ```bash
   # Test embedded mode
   benchbox run tpch --platform=clickhouse --mode=local --scale-factor=0.01

   # Test server mode (if available)
   benchbox run tpch --platform=clickhouse --mode=server --scale-factor=0.01
   ```

## Advanced Usage

### Performance Tuning

While embedded mode has fewer tuning options than server mode, you can optimize performance:

```bash
# Use appropriate scale factors
benchbox run tpch --platform=clickhouse --mode=local --scale-factor=0.1

# Monitor memory usage during execution
top -p $(pgrep -f benchbox)
```

### Integration with Other Tools

```bash
# Export results for analysis
benchbox run tpch --platform=clickhouse --mode=local --output=json > results.json

# Run multiple benchmarks
for benchmark in tpch tpcds ssb; do
  echo "Running $benchmark..."
  benchbox run $benchmark --platform=clickhouse --mode=local --scale-factor=0.01
done
```

## Technical Details

### Architecture

- **chDB Integration**: Uses official ClickHouse local engine
- **Connection Management**: Persistent connection maintains table state
- **Query Execution**: Direct SQL execution without network overhead
- **Result Processing**: Native Python data type conversion
- **Error Handling**: Comprehensive error messages with resolution guidance

### File Formats

Embedded mode supports all standard formats:
- CSV, TSV (tab-separated)
- Parquet (future enhancement)
- JSON (future enhancement)

### Limitations

- **Single Process**: No multi-process parallelism
- **Memory Bounds**: Limited by available system memory
- **No Clustering**: Single-node execution only
- **No Replication**: No built-in data redundancy

## Migration Guide

### From Server to Embedded Mode

```bash
# Old server mode command
benchbox run tpch --platform=clickhouse --host=localhost --port=9000

# New embedded mode equivalent
benchbox run tpch --platform=clickhouse --mode=local
```

### From Embedded to Server Mode

```bash
# Current embedded mode command
benchbox run tpch --platform=clickhouse --mode=local

# Server mode equivalent (requires ClickHouse server)
benchbox run tpch --platform=clickhouse --mode=server --host=localhost --port=9000
```

## Contributing

To contribute to ClickHouse local mode support:

1. **Testing**: Run the embedded mode test suite
   ```bash
   pytest tests/unit/platforms/test_clickhouse_local.py -v
   ```

2. **Development**: Set up development environment
   ```bash
   pip install -e .[dev]
   pip install chdb
   ```

3. **Bug Reports**: Include system information and chDB version
   ```bash
   python -c "import chdb, platform; print(f'chDB: {chdb.chdb_version()}, Platform: {platform.platform()}')"
   ```

## References

- [chDB Official Repository](https://github.com/chdb-io/chdb)
- [ClickHouse Documentation](https://clickhouse.com/docs)
- [BenchBox Platform Documentation](index.md)
- [TPC-H Benchmark Guide](../benchmarks/tpch.md)
