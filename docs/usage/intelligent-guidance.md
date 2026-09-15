<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Intelligent Guidance and Enhanced CLI

```{tags} intermediate, guide, cli
```

BenchBox's CLI provides intelligent guidance throughout the benchmarking process, making it easier to get appropriate results regardless of your system specifications or benchmarking experience.

## Overview

The intelligent guidance system analyzes your system resources and provides personalized recommendations for:

- **Database selection** with performance ratings
- **Scale factor optimization** based on available memory
- **Concurrency configuration** matched to CPU cores
- **Query subset recommendations** for efficient testing
- **Resource validation** to prevent issues

## Smart System Analysis

### Automatic Resource Detection

When you run `benchbox run`, the CLI automatically analyzes your system:

```bash
$ benchbox run

 BenchBox Interactive Setup
We\'ll guide you through selecting the appropriate configuration for your system.

Step 1 of 5: System Analysis
Analyzing your system resources to provide smart recommendations...
```

### System Profiling Output

```bash
┌─ System Profile ─┐
│ Component          │ Value                                    │
├────────────────────┼──────────────────────────────────────────┤
│ Operating System   │ Darwin 24.6.0                          │
│ Architecture       │ arm64                                   │
│ Python Version     │ 3.11.9                                 │
│ CPU Model          │ Apple M3 Pro                           │
│ CPU Cores          │ 12 physical, 12 logical               │
│ Memory             │ 36.0 GB total, 24.3 GB available     │
│ Disk Space         │ 245.2 GB available                    │
│ Available Databases│ duckdb, sqlite3                       │
└────────────────────┴──────────────────────────────────────────┘
```

### Personalized Recommendations

Based on your system specs, you'll receive tailored advice:

**High-Performance System:**
```bash
 System Recommendations
✅ High-memory system detected: You can run large benchmarks (scale 1.0+)
 Multi-core system: Concurrent execution recommended for faster results
 Setup: Your system can handle production-scale benchmarks!
```

**Standard Development System:**
```bash
 System Recommendations
 Mid-range system detected: Moderate benchmarks recommended (scale 0.1-1.0)
 Quad-core system: Light concurrency can improve performance
 Good Setup: Perfect for development and moderate benchmarking
```

## Database Selection

### Performance Ratings & Recommendations

The CLI now provides detailed database comparison with ratings:

```bash
Step 2 of 5: Database Selection
Selecting the best database for your benchmarks...

┌─ Available Databases ─┐
│ ID │ Database   │ Version │ Description                     │ OLAP │ Architecture   │ Status         │
├────┼────────────┼─────────┼─────────────────────────────────┼──────┼────────────────┼────────────────┤
│ 1  │ DuckDB     │ 1.3.1   │ In-memory analytical database   │ ✅    │ Columnar       │  Default     │
│ 2  │ ClickHouse │ 24.1    │ Columnar analytical database    │ ✅    │ Columnar       │ Available    │
│ 3  │ SQLite     │ 3.45.1  │ Lightweight file-based database │ ❌    │ Row-based      │ Available    │
└────┴────────────┴─────────┴─────────────────────────────────┴──────┴────────────────┴────────────────┘

Selection Guide:
• DuckDB: Columnar storage, in-memory processing, included by default
• ClickHouse: Columnar storage, client-server architecture
• SQLite: Row-based storage, single-threaded execution
• Cloud platforms (BigQuery, Snowflake, Databricks, Redshift) available with additional configuration

 Default: DuckDB (choice 1)
```

### Database Display Order

The system displays databases in this order (based on OLAP optimization):
1. **DuckDB** - Columnar, in-process, included by default
2. **ClickHouse** - Columnar, client-server architecture
3. **SQLite** - Row-based, single-threaded
4. **Cloud Platforms** - BigQuery, Snowflake, Databricks, Redshift (require configuration)

## Intelligent Benchmark Configuration

### Resource-Aware Scale Factor Selection

The CLI provides detailed resource estimates for each scale factor:

```bash
Scale Factor Selection
Available options: [0.01, 0.1, 1.0, 10.0]
• Recommended for your system: 0.1

Scale Factor Resource Estimates
┌───────┬─────────────┬─────────────┬──────────────────────┐
│ Scale │ Est. Memory │ Est. Time   │ Recommendation       │
├───────┼─────────────┼─────────────┼──────────────────────┤
│ 0.01  │ ~0.1GB      │ ~2min       │ ✅ Good for testing  │
│ 0.1   │ ~1.0GB      │ ~5min       │  Moderate load    │
│ 1.0   │ ~10.0GB     │ ~15min      │  Production       │
│ 10.0  │ ~100.0GB    │ ~60min      │ ⚠️️ May exceed memory │
└───────┴─────────────┴─────────────┴──────────────────────┘
```

### Scale Factor Recommendations by System

| System Memory | Recommended Scale | Use Case                         |
| ------------- | ----------------- | -------------------------------- |
| 32GB+         | 1.0+              | Production benchmarking          |
| 16-32GB       | 0.1-1.0           | Development and moderate testing |
| 8-16GB        | 0.01-0.1          | Testing and development          |
| <8GB          | 0.01              | Minimal testing only             |

### Concurrent Execution Optimization

The CLI analyzes your CPU cores and recommends appropriate concurrency:

```bash
Concurrency Options
• Recommended streams: 2 (based on 12 CPU cores)
Enable concurrent execution? [Y/n]: y
Number of concurrent streams [2]: 2
⚠️ Warning: 8 streams may exceed your 4 CPU cores
```

### Concurrency Recommendations by CPU

| CPU Cores | Recommended Streams | Performance Impact     |
| --------- | ------------------- | ---------------------- |
| 8+        | 2-4 streams         | Significant speedup    |
| 4-8       | 1-2 streams         | Moderate improvement   |
| <4        | 1 stream            | Sequential recommended |

## Real-Time Validation & Warnings

### Resource Validation

The CLI validates your selections against system capacity:

```bash
 INFO: This will use ~2.5GB of your 16GB memory
⚠️️ WARNING: This scale may require 18GB memory, but you have 16GB
❌ ERROR: Scale factor 10.0 requires 100GB memory (you have 8GB available)
```

### Performance Warnings

```bash
⚠️ Warning: 4 concurrent streams may exceed your 2 CPU cores
 Tip: Consider scale 0.01 for faster testing on this system
 Optimization: Concurrent execution will speed up this benchmark
```

## Configuration Summary & Preview

### Comprehensive Configuration Review

Before execution, see a complete summary:

```bash
 Configuration Summary
┌─────────────────┬──────────────────────────┐
│ Setting         │ Value                    │
├─────────────────┼──────────────────────────┤
│ Benchmark:      │ TPC-H                    │
│ Scale Factor:   │ 0.1                      │
│ Complexity:     │ Medium                   │
│ Concurrency:    │ 2 streams                │
│ Queries:        │ 22                       │
│ Est. Memory:    │ ~1.0GB                   │
│ Est. Time:      │ ~5 minutes               │
└─────────────────┴──────────────────────────┘
```

## Programmatic Access to Guidance Features

### Using Intelligent Features in Scripts

```python
from benchbox.cli.benchmarks import BenchmarkManager
from benchbox.cli.database import DatabaseManager
from benchbox.cli.system import SystemProfiler

# Get system-specific recommendations
profiler = SystemProfiler()
system_profile = profiler.get_system_profile()

# Get intelligent database recommendations
db_manager = DatabaseManager()
recommended_db = db_manager._get_recommended_database()
performance_rating = db_manager._get_performance_rating(recommended_db)

# Get smart benchmark configuration
bench_manager = BenchmarkManager()
recommended_scale = bench_manager._get_recommended_scale(
    bench_manager.benchmarks['tpch'],
    {'memory_gb': 16, 'cpu_cores': 8}
)

print(f"System: {system_profile.cpu_cores} cores, {system_profile.memory_total_gb}GB")
print(f"Recommended database: {recommended_db} ({performance_rating})")
print(f"Recommended scale for TPC-H: {recommended_scale}")
```

### Batch Processing with Smart Defaults

```python
from benchbox.cli.benchmarks import BenchmarkManager

def run_appropriate_benchmarks():
    """Run benchmarks with system-configured settings."""
    manager = BenchmarkManager()
    system_profile = manager._get_system_profile()

    benchmarks = ['tpch', 'tpcds', 'ssb']

    for benchmark_id in benchmarks:
        benchmark_info = manager.benchmarks[benchmark_id]

        # Get intelligent recommendations
        recommended_scale = manager._get_recommended_scale(benchmark_info, system_profile)
        recommended_queries = manager._get_recommended_query_subset(
            benchmark_info, recommended_scale, system_profile
        )

        print(f"Running {benchmark_id}:")
        print(f"  Scale: {recommended_scale}")
        print(f"  Queries: {recommended_queries or 'all'}")
        print(f"  Memory estimate: {manager._estimate_memory_usage(benchmark_info, recommended_scale):.1f}GB")
```

## Best Practices

### System Optimization Tips

1. **Start Small**: Always begin with recommended scale factors
2. **Monitor Resources**: Watch memory and CPU usage during execution
3. **Use Concurrent Execution**: Enable for multi-core systems
4. **Validate Configuration**: Review summary before starting long benchmarks

### Development Workflow

```bash
# Development cycle
benchbox run --benchmark primitives --scale 0.01  # Quick smoke test
benchbox run --benchmark tpch --scale 0.1                 # Moderate validation
benchbox run --benchmark tpcds --scale 0.01               # Complex benchmark test
```

### Production Benchmarking

```bash
# Production evaluation
benchbox run --benchmark tpch --scale 1.0      # Full TPC-H
benchbox run --benchmark tpcds --scale 1.0     # Full TPC-DS
```

The intelligent guidance features make BenchBox accessible to users of all experience levels while ensuring appropriate performance for any system configuration.
