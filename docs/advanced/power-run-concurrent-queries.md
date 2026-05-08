<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Power Run Iterations and Concurrent Query Execution

```{tags} advanced, guide, tpc-h, performance
```

Comprehensive guide to BenchBox's execution modes for benchmark testing with statistical confidence and throughput analysis.

## Overview

BenchBox provides two execution modes:

- **Power Run Iterations**: Execute multiple test iterations sequentially to gather statistical confidence and eliminate outliers
- **Concurrent Query Execution**: Execute queries in parallel to test throughput, scalability, and multi-user scenarios

These features are essential for:
- Production performance evaluation
- Database stress testing
- Scalability analysis
- Statistical confidence in benchmark results
- Regression testing with confidence intervals

## Power Run Iterations

### What are Power Run Iterations?

Power Run Iterations execute the same benchmark test multiple times with **different query orderings per iteration**, providing statistical analysis of performance consistency. This approach:

- **Eliminates outliers** from single-run measurements
- **Provides confidence intervals** for benchmark results
- **Detects performance variance** and consistency issues
- **Enables statistical comparison** between configurations
- **Follows TPC specifications** with proper stream permutations (each iteration uses different stream_id)
- **Tests different query interaction patterns** to stress query optimizers

### Key Benefits

1. **Statistical Confidence**: Get mean, median, standard deviation, and confidence intervals
2. **Performance Consistency**: Identify systems with high variance in query times
3. **Outlier Detection**: Automatically identify and handle anomalous runs
4. **Regression Testing**: Compare performance changes with statistical significance
5. **Professional Reporting**: Generate publication-quality benchmark reports

### Configuration Options

```yaml
# benchbox.yaml
execution:
  power_run:
    iterations: 5                          # Number of test iterations to run
    warm_up_iterations: 2                  # Warm-up runs (excluded from statistics)
    timeout_per_iteration_minutes: 90      # Maximum time per iteration
    fail_fast: false                       # Stop on first failure vs. continue
    collect_metrics: true                  # Collect detailed performance metrics
```

### Usage Examples

#### Basic Power Run Setup

```python
from benchbox.utils import PowerRunExecutor, ExecutionConfigHelper
from benchbox import TPCH

# Configure power run settings
config_helper = ExecutionConfigHelper()
config_helper.enable_power_run_iterations(
    iterations=5,           # 5 test iterations
    warm_up_iterations=2    # 2 warm-up iterations
)

# Create benchmark
tpch = TPCH(scale_factor=0.1)

# Execute power runs
power_executor = PowerRunExecutor()

def create_power_test():
    from benchbox.core.tpch.power_test import TPCHPowerTest
    return TPCHPowerTest(
        benchmark=tpch,
        connection_string="duckdb:test.db",
        scale_factor=0.1
    )

result = power_executor.execute_power_runs(create_power_test)

# Statistical analysis
print(f"Average Power@Size: {result.avg_power_at_size:.2f}")
print(f"Std Deviation: {result.power_at_size_stdev:.2f}")
print(f"Confidence: {result.iterations_successful}/{result.iterations_completed}")
```

#### Advanced-level Statistical Analysis

```python
import numpy as np
from scipy import stats

# Get power@size values from all iterations
power_values = [iter_result.power_at_size for iter_result in result.iteration_results]

# Calculate confidence interval (95%)
confidence_level = 0.95
degrees_freedom = len(power_values) - 1
sample_mean = np.mean(power_values)
sample_standard_error = stats.sem(power_values)

confidence_interval = stats.t.interval(
    confidence_level,
    degrees_freedom,
    sample_mean,
    sample_standard_error
)

print(f"95% Confidence Interval: {confidence_interval[0]:.2f} - {confidence_interval[1]:.2f}")
print(f"Coefficient of Variation: {(result.power_at_size_stdev / result.avg_power_at_size) * 100:.1f}%")
```

### Performance Profiles for Power Runs

BenchBox provides pre-configured profiles configured for different testing scenarios:

#### Quick Profile
- **Use Case**: Rapid development testing
- **Iterations**: 1 (no statistical analysis)
- **Warm-up**: 0 iterations
- **Timeout**: 30 minutes
- **Best For**: Development, unit testing

#### Standard Profile
- **Use Case**: Balanced performance testing
- **Iterations**: 3 + 1 warm-up
- **Timeout**: 60 minutes per iteration
- **Best For**: Regular performance evaluation

#### Thorough Profile
- **Use Case**: Comprehensive analysis
- **Iterations**: 5 + 2 warm-up
- **Timeout**: 120 minutes per iteration
- **Best For**: Production evaluation, research

#### Stress Profile
- **Use Case**: Maximum statistical confidence
- **Iterations**: 10 + 3 warm-up
- **Timeout**: 180 minutes per iteration
- **Best For**: Official benchmarking, publications

## Concurrent Query Execution

### What is Concurrent Query Execution?

Concurrent Query Execution runs multiple query streams simultaneously to test:

- **Throughput performance** under multi-user load
- **Scalability characteristics** as load increases
- **Resource contention** behavior
- **Multi-threading efficiency** of database engines
- **Real-world performance** with concurrent users

### Key Benefits

1. **Throughput Measurement**: Queries per second under concurrent load
2. **Scalability Testing**: Performance scaling with concurrent streams
3. **Resource Analysis**: CPU, memory, I/O utilization under load
4. **Multi-User Simulation**: Real-world concurrent access patterns
5. **Bottleneck Identification**: Find system limitations and contention points

### Configuration Options

```yaml
execution:
  concurrent_queries:
    enabled: true                          # Enable concurrent execution
    max_concurrent: 4                      # Maximum concurrent streams
    query_timeout_seconds: 600             # Individual query timeout
    stream_timeout_seconds: 7200           # Total stream timeout
    retry_failed_queries: true             # Retry failed queries
    max_retries: 5                         # Maximum retry attempts
```

### Usage Examples

#### Basic Concurrent Execution

```python
from benchbox.utils import ConcurrentQueryExecutor, ExecutionConfigHelper
from benchbox import TPCH

# Configure concurrent execution
config_helper = ExecutionConfigHelper()
config_helper.enable_concurrent_queries(max_concurrent=4)

# Create benchmark
tpch = TPCH(scale_factor=0.1)

# Execute concurrent queries
concurrent_executor = ConcurrentQueryExecutor()

def create_throughput_test(stream_id):
    from benchbox.core.tpch.throughput_test import TPCHThroughputTest
    return TPCHThroughputTest(
        benchmark=tpch,
        connection_string=f"duckdb:stream_{stream_id}.db",
        num_streams=1,  # Each executor handles one stream
        verbose=False
    )

result = concurrent_executor.execute_concurrent_queries(create_throughput_test)

# Throughput analysis
print(f"Throughput: {result.throughput_queries_per_second:.2f} queries/sec")
print(f"Success Rate: {result.queries_successful}/{result.queries_executed}")
print(f"Concurrent Streams: {len(result.stream_results)}")
```

#### Scalability Analysis

```python
# Test scalability across different concurrency levels
concurrency_levels = [1, 2, 4, 8, 16]
throughput_results = {}

for level in concurrency_levels:
    print(f"\nTesting with {level} concurrent streams...")

    config_helper.get_concurrent_queries_settings().max_concurrent = level
    result = concurrent_executor.execute_concurrent_queries(
        create_throughput_test,
        num_streams=level
    )

    throughput_results[level] = {
        'throughput': result.throughput_queries_per_second,
        'success_rate': result.queries_successful / result.queries_executed,
        'avg_duration': result.total_duration / level
    }

# Analyze scalability
print(f"\n Scalability Analysis:")
print(f"{'Streams':<8} {'Throughput':<12} {'Success Rate':<12} {'Scalability':<12}")
print("-" * 50)

base_throughput = throughput_results[1]['throughput']
for level, metrics in throughput_results.items():
    scalability = metrics['throughput'] / base_throughput
    print(f"{level:<8} {metrics['throughput']:<12.2f} "
          f"{metrics['success_rate']:<12.1%} {scalability:<12.2f}x")
```

## System Optimization

### Automatic Resource-Based Configuration

BenchBox automatically optimizes execution settings based on available system resources:

```python
import psutil
from benchbox.utils import ExecutionConfigHelper

config_helper = ExecutionConfigHelper()

# Auto-optimize based on system specs
cpu_cores = psutil.cpu_count()
memory_gb = psutil.virtual_memory().total / (1024**3)

config_helper.optimize_for_system(cpu_cores=cpu_cores, memory_gb=memory_gb)

# View configured settings
summary = config_helper.get_execution_summary()
print(f"Optimized for {cpu_cores} cores, {memory_gb:.1f}GB RAM:")
print(f"- Max concurrent streams: {summary['concurrent_queries']['max_streams']}")
print(f"- Power run timeout: {summary['power_run']['settings']['timeout_per_iteration_minutes']} min")
```

### Optimization Rules

**CPU Core Optimization:**
- `max_concurrent = min(8, max(2, cpu_cores // 4))`
- Prevents over-subscription of CPU resources
- Scales appropriately from 2-core to 32+ core systems

**Memory Optimization:**
- **< 8GB**: Extended timeouts (120min power, 600s queries)
- **8-16GB**: Standard timeouts (60min power, 300s queries)
- **> 16GB**: Reduced timeouts (45min power, 180s queries)

**Storage Optimization:**
- SSD systems: Higher concurrency, shorter timeouts
- HDD systems: Lower concurrency, longer timeouts
- Network storage: Conservative settings with retries

## Comprehensive Testing Workflow

### Production Evaluation Workflow

```python
from benchbox import TPCH
from benchbox.utils import ExecutionConfigHelper, PowerRunExecutor, ConcurrentQueryExecutor

# 1. System Analysis and Optimization
config_helper = ExecutionConfigHelper()
config_helper.apply_performance_profile('thorough')  # Comprehensive testing

import psutil
config_helper.optimize_for_system(
    cpu_cores=psutil.cpu_count(),
    memory_gb=psutil.virtual_memory().total / (1024**3)
)

# 2. Benchmark Setup
tpch = TPCH(scale_factor=1.0)  # Production scale

# 3. Power Run Testing (Statistical Confidence)
print("Phase 1: Power Run Analysis")
power_executor = PowerRunExecutor(config_helper.config_manager)

def create_power_test():
    from benchbox.core.tpch.power_test import TPCHPowerTest
    return TPCHPowerTest(
        benchmark=tpch,
        connection_string="duckdb:production_test.db",
        scale_factor=1.0,
        warm_up=True,
        validation=True
    )

power_result = power_executor.execute_power_runs(create_power_test)

print(f" Single-Stream Performance:")
print(f"  Average: {power_result.avg_power_at_size:.2f} Power@Size")
print(f"  Std Dev: {power_result.power_at_size_stdev:.2f}")
print(f"  Range: {power_result.min_power_at_size:.2f} - {power_result.max_power_at_size:.2f}")

# 4. Concurrent Query Testing (Throughput Analysis)
print("\nPhase 2: Concurrent Throughput Analysis")
concurrent_executor = ConcurrentQueryExecutor(config_helper.config_manager)

def create_throughput_test(stream_id):
    from benchbox.core.tpch.throughput_test import TPCHThroughputTest
    return TPCHThroughputTest(
        benchmark=tpch,
        connection_string=f"duckdb:throughput_stream_{stream_id}.db",
        num_streams=1,
        verbose=False
    )

concurrent_result = concurrent_executor.execute_concurrent_queries(create_throughput_test)

print(f" Multi-Stream Performance:")
print(f"  Throughput: {concurrent_result.throughput_queries_per_second:.2f} queries/sec")
print(f"  Success Rate: {concurrent_result.queries_successful}/{concurrent_result.queries_executed}")
print(f"  Concurrent Streams: {len(concurrent_result.stream_results)}")

# 5. Comprehensive Analysis
efficiency = concurrent_result.throughput_queries_per_second / (power_result.avg_power_at_size / 3600)
print(f"\n Performance Analysis:")
print(f"  Single-stream efficiency: {power_result.avg_power_at_size:.2f} Power@Size")
print(f"  Multi-stream efficiency: {efficiency:.2f}x scaling")
print(f"  Performance consistency: ±{power_result.power_at_size_stdev:.1f} Power@Size")
```

## Best Practices

### Power Run Iterations

1. **Iteration Count Selection**:
   - Development: 1-3 iterations
   - Performance evaluation: 3-5 iterations
   - Official benchmarking: 5-10 iterations

2. **Warm-up Iterations**:
   - Always include 1-2 warm-up iterations
   - Warm-up eliminates cold-start effects
   - Excluded from statistical calculations

3. **Timeout Configuration**:
   - Small scale factors: 30-60 minutes
   - Large scale factors: 60-180 minutes
   - Factor in system performance characteristics

4. **Statistical Analysis**:
   - Calculate confidence intervals for comparisons
   - Use coefficient of variation to assess consistency
   - Report both mean and median values

### Concurrent Query Execution

1. **Concurrency Selection**:
   - Start with `CPU cores / 4` for initial testing
   - Scale up to find appropriate concurrent level
   - Monitor system resource utilization

2. **Resource Monitoring**:
   - Watch for CPU over-subscription
   - Monitor memory usage and swapping
   - Check I/O bottlenecks and disk utilization

3. **Timeout Management**:
   - Set generous timeouts for initial testing
   - Adjust based on observed query execution times
   - Include retry logic for transient failures

4. **Result Interpretation**:
   - Linear scaling indicates good parallelization
   - Sub-linear scaling suggests resource contention
   - Throughput decrease indicates over-subscription

### System Optimization

1. **Resource Assessment**:
   - Use system profiling before configuration
   - Consider available vs. total memory
   - Account for other system processes

2. **Environment Configuration**:
   - Disable unnecessary background processes
   - Set appropriate database configuration
   - Ensure adequate temporary disk space

3. **Validation**:
   - Always validate configurations before execution
   - Test with smaller scale factors first
   - Monitor resource usage during execution

## TPC Specification Compliance

BenchBox ensures compliance with official TPC specifications for query ordering in both power and throughput tests.

### Power Run Compliance

Each power run iteration uses a **different stream permutation** to ensure varied query interaction patterns:

```python
# Iteration 0: Uses TPC-H stream 0 permutation [14, 2, 9, 20, 6, 17, 18, 8, 21, 13, 3, 22, 16, 4, 11, 15, 1, 10, 19, 5, 7, 12]
# Iteration 1: Uses TPC-H stream 1 permutation [21, 3, 18, 5, 11, 7, 6, 20, 17, 12, 16, 15, 13, 10, 2, 8, 14, 19, 9, 22, 1, 4]
# Iteration 2: Uses TPC-H stream 2 permutation [6, 17, 14, 16, 19, 10, 9, 2, 15, 8, 5, 22, 12, 7, 13, 18, 1, 4, 20, 3, 11, 21]

config = PowerRunSettings()
config.iterations = 5  # Each iteration uses different stream (0, 1, 2, 3, 4)
```

### Concurrent Query Compliance

Each concurrent stream uses a **different permutation** as mandated by TPC specifications:

```python
# Stream 0: TPC-H permutation[0] or TPC-DS stream 0 permutation
# Stream 1: TPC-H permutation[1] or TPC-DS stream 1 permutation
# Stream 2: TPC-H permutation[2] or TPC-DS stream 2 permutation

config = ConcurrentQueriesSettings()
config.max_concurrent = 4  # Each stream gets different permutation (0, 1, 2, 3)
```

### Why TPC Compliance Matters

1. **Valid Comparisons**: Results comparable to official TPC publications
2. **Optimizer Testing**: Different orderings stress different optimization paths
3. **Statistical Validity**: Varied patterns provide meaningful performance statistics
4. **Research Validity**: Academic research can rely on specification-compliant results

### Verification

Check result compliance:
```python
# Verify first query in TPC-H power test uses stream permutation
assert result.query_results[0]['query_id'] == 14  # Stream 0 starts with query 14
assert result.query_results[0]['stream_id'] == 0   # Stream ID recorded
assert result.query_results[0]['position'] == 1    # Position in permutation
```

For detailed compliance documentation, see: `_project/TPC_SPECIFICATION_COMPLIANCE.md`

## Troubleshooting

### Common Issues

**Power Run Failures:**
- **Memory exhaustion**: Reduce scale factor or increase timeout
- **High variability**: Check for system interference or thermal throttling
- **Iteration failures**: Enable detailed logging to identify specific issues

**Concurrent Execution Problems:**
- **Deadlocks**: Reduce concurrency level or enable retries
- **Resource contention**: Lower concurrent stream count
- **Timeout errors**: Increase timeout values or optimize queries

**Configuration Issues:**
- **Invalid settings**: Use validation before execution
- **System limitations**: Apply auto-optimization for current hardware
- **Profile conflicts**: Reset to default before applying new profiles

### Performance Optimization Tips

1. **Database Configuration**:
   - Optimize memory allocation (75% of available RAM)
   - Enable appropriate number of worker threads
   - Configure temporary storage on fast disks

2. **System Tuning**:
   - Disable CPU frequency scaling during tests
   - Set high-performance power profile
   - Minimize background process interference

3. **Test Environment**:
   - Use dedicated systems for benchmarking
   - Ensure consistent thermal conditions
   - Minimize network and disk I/O interference

This systematic approach to power run iterations and concurrent query execution provides professional-grade benchmarking capabilities with statistical rigor and real-world relevance.
