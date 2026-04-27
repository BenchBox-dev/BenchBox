# ClickHouse Local Mode

```{tags} intermediate, guide, clickhouse, local-platform
```

BenchBox supports ClickHouse in two deployment targets, plus a separate first-class cloud platform:

- **Local Mode**: Uses chDB for in-process ClickHouse execution
- **Server Mode**: Connects to an external ClickHouse server
- **ClickHouse Cloud**: Separate first-class platform → see [ClickHouse Cloud](clickhouse-cloud.md)

```{note}
**ClickHouse Cloud** is now a first-class platform (`--platform clickhouse-cloud`), not a deployment mode. This follows the pattern established by MotherDuck and Starburst.
```

## Overview

ClickHouse Local Mode uses [chDB](https://github.com/chdb-io/chdb), the official in-process ClickHouse engine, to run ClickHouse queries directly in Python without requiring a separate ClickHouse server installation.

### Key Benefits

- **Zero Server Setup**: No ClickHouse server installation required
- **Native Performance**: In-process execution eliminates IPC overhead
- **Development Friendly**: Perfect for testing, development, and quick analysis
- **Same SQL Compatibility**: Full ClickHouse SQL dialect support
- **Easy Installation**: Single `uv add chdb` command

## Installation

### Prerequisites

- Python 3.10+
- Supported platforms: macOS and Linux (x86_64 and ARM64)

### Install chDB

```bash
# Install chDB for ClickHouse local mode support
uv add chdb

# Verify installation
uv run -- python -c "import chdb; print(chdb.chdb_version())"
```

### Install BenchBox with ClickHouse Support

```bash
# Install BenchBox (if not already installed)
uv add benchbox

# Sync project dependencies
uv sync --group dev
```

## Usage

### Basic Usage

```bash
# Run TPC-H benchmark in ClickHouse local mode
benchbox run --platform clickhouse-local --benchmark tpch --scale 0.01

# Run with custom data path
benchbox run --platform clickhouse-local --benchmark tpch --scale 0.01 \
  --platform-option data_path=/tmp/benchmark_data

# Compare with server mode
benchbox run --platform clickhouse-server --benchmark tpch --scale 0.01 \
  --platform-option host=localhost \
  --platform-option port=9000
```

### CLI Arguments

#### Platform Selection
- `--platform clickhouse-local` - Use ClickHouse local mode via chDB
- `--platform clickhouse-server` - Use ClickHouse server (see [ClickHouse Server](clickhouse-server.md))
- `--platform clickhouse-cloud` - Use ClickHouse Cloud (see [ClickHouse Cloud](clickhouse-cloud.md))

```{deprecated} v0.2.0
The legacy colon syntax (`clickhouse:local`, `clickhouse:server`) and bare `clickhouse` selector still work but emit deprecation warnings. Use the first-class names above. See [Migration Guide](clickhouse-migration.md).
```

#### Local Mode Specific Arguments
- `--platform-option data_path=PATH` - Optional data path for file operations

#### Server Mode Arguments
- `--platform-option host=HOST` - ClickHouse server host
- `--platform-option port=PORT` - ClickHouse server port
- `--platform-option username=USER` - Username for server authentication
- `--platform-option password=PASS` - Password for server authentication
- `--platform-option secure=true` - Use TLS connection

## Performance Characteristics

### Local Mode
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

### Use Local Mode When:
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
benchbox run --platform clickhouse-local --benchmark tpch --scale 0.01

# Medium scale for testing
benchbox run --platform clickhouse-local --benchmark tpch --scale 1.0
```

### ClickBench Benchmark
```bash
# Run ClickBench analytical queries
benchbox run --platform clickhouse-local --benchmark clickbench
```

### Custom Data Directory
```bash
# Use specific directory for generated data
benchbox run --platform clickhouse-local --benchmark tpch --scale 0.1 \
  --platform-option data_path=/path/to/benchmark/data
```

## Troubleshooting

### Common Issues and Solutions

#### 1. chDB Not Installed
```
Error: ClickHouse local mode requires chDB but it is not installed.
```

**Solution:**
```bash
uv add chdb
```

#### 2. Platform Not Supported
```
Error: chDB installation failed or not compatible with your platform
```

**Solution:**
- Ensure you're on macOS or Linux (x86_64/ARM64)
- Ensure your environment is synced with `uv sync --group dev`
- Check Python version: `uv run -- python --version` (3.10+ required)

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
Queries running slower than expected in local mode
```

**Solution:**
- Local mode is optimized for small-medium datasets
- For large datasets or maximum performance, use server mode
- Consider data partitioning or smaller scale factors

### Getting Help

1. **Check Installation**: Verify chDB is properly installed
   ```bash
   uv run -- python -c "import chdb; print('chDB version:', chdb.chdb_version())"
   ```

2. **Verbose Output**: Run with verbose logging
   ```bash
   benchbox run --platform clickhouse-local --benchmark tpch --scale 0.01 -v
   ```

3. **Compare Deployments**: Test both platforms to isolate issues
   ```bash
   # Test local mode
   benchbox run --platform clickhouse-local --benchmark tpch --scale 0.01

   # Test server mode (if available)
   benchbox run --platform clickhouse-server --benchmark tpch --scale 0.01
   ```

## Advanced Usage

### Performance Tuning

While local mode has fewer tuning options than server mode, you can optimize performance:

```bash
# Use appropriate scale factors
benchbox run --platform clickhouse-local --benchmark tpch --scale 0.1

# Monitor memory usage during execution
top -p $(pgrep -f benchbox)
```

### Integration with Other Tools

```bash
# Export results for analysis
benchbox run --platform clickhouse-local --benchmark tpch --scale 0.01 --output results.json

# Run multiple benchmarks
for benchmark in tpch tpcds ssb; do
  echo "Running $benchmark..."
  benchbox run --platform clickhouse-local --benchmark "$benchmark" --scale 0.01
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

Local mode supports all standard formats:
- CSV, TSV (tab-separated)
- Parquet (future enhancement)
- JSON (future enhancement)

### Limitations

- **Single Process**: No multi-process parallelism
- **Memory Bounds**: Limited by available system memory
- **No Clustering**: Single-node execution only
- **No Replication**: No built-in data redundancy

## Switching Between Platforms

### From Server to Local

```bash
# Server mode command
benchbox run --platform clickhouse-server --benchmark tpch --scale 0.01 \
  --platform-option host=localhost \
  --platform-option port=9000

# Local mode equivalent
benchbox run --platform clickhouse-local --benchmark tpch --scale 0.01
```

### From Local to Server

```bash
# Current local mode command
benchbox run --platform clickhouse-local --benchmark tpch --scale 0.01

# Server mode equivalent (requires ClickHouse server)
benchbox run --platform clickhouse-server --benchmark tpch --scale 0.01 \
  --platform-option host=localhost \
  --platform-option port=9000
```

For full migration details from the legacy `clickhouse` selector, see the [Migration Guide](clickhouse-migration.md).

## Contributing

To contribute to ClickHouse local mode support:

1. **Testing**: Run the ClickHouse local mode test suite
   ```bash
   uv run -- python -m pytest tests/unit/platforms/test_clickhouse_local.py -q
   ```

2. **Development**: Set up development environment
   ```bash
   uv sync --group dev
   uv add chdb
   ```

3. **Bug Reports**: Include system information and chDB version
   ```bash
   uv run -- python -c "import chdb, platform; print(f'chDB: {chdb.chdb_version()}, Platform: {platform.platform()}')"
   ```

## References

- [chDB Official Repository](https://github.com/chdb-io/chdb)
- [ClickHouse Documentation](https://clickhouse.com/docs)
- [BenchBox Platform Documentation](index.md)
- [TPC-H Benchmark Guide](../benchmarks/tpch.md)
