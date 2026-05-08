<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# TPC Patterns Usage Guide

```{tags} intermediate, guide, tpc-h, tpc-ds, data-generation
```

This guide explains how to use the TPC patterns and utilities provided in `benchbox.core.tpc_patterns` for running TPC-H and TPC-DS benchmarks with proper stream execution, parameter management, and result aggregation.

## Overview

The `tpc_patterns` module provides common test execution patterns and utilities that are shared between TPC-H and TPC-DS implementations. It follows TPC specification requirements for:

- **Stream independence and isolation**: Each stream runs independently with its own parameters
- **Proper query parameter generation**: Deterministic parameter generation with seeds
- **Concurrent execution management**: Thread-safe concurrent query execution
- **Result aggregation and validation**: Comprehensive result collection and validation

## Core Components

### 1. StreamExecutor
Manages concurrent query stream execution with proper isolation.

```python
from benchbox.core.tpc_patterns import StreamExecutor, create_tpc_stream_configs

# Create connection factory
def connection_factory():
    return create_database_connection()

# Create stream executor
executor = StreamExecutor(connection_factory, max_concurrent_streams=4)

# Create stream configurations
stream_configs = create_tpc_stream_configs(
    num_streams=2,
    query_ids=[1, 2, 3, 4, 5],
    base_seed=42,
    permutation_mode="tpc_standard"
)

# Execute streams
results = executor.execute_streams(stream_configs, query_executor)
```

### 2. QueryPermutator
Creates TPC-compliant query permutations for stream execution.

```python
from benchbox.core.tpc_patterns import QueryPermutator, PermutationConfig

# Create permutation configuration
config = PermutationConfig(
    mode="tpc_standard",  # or "random", "sequential"
    seed=42,
    ensure_unique=True
)

# Create permutator
permutator = QueryPermutator(config)

# Generate permutation
query_ids = [1, 2, 3, 4, 5]
permuted = permutator.generate_permutation(query_ids)
```

### 3. ParameterManager
Handles query parameter substitution with deterministic seeding.

```python
from benchbox.core.tpc_patterns import ParameterManager

# Create parameter manager
manager = ParameterManager(base_seed=42)

# Generate parameters
params = manager.generate_parameters(
    query_id=1,
    stream_id=0,
    scale_factor=1.0
)
```

### 4. TransactionManager
Manages database transactions and isolation levels.

```python
from benchbox.core.tpc_patterns import TransactionManager

# Create transaction manager
transaction_manager = TransactionManager(connection)

# Use transaction context
with transaction_manager.transaction(isolation_level="READ_COMMITTED", timeout=30.0):
    # Execute queries within transaction
    cursor = connection.execute("SELECT * FROM table")
    results = connection.fetchall(cursor)
```

### 5. TestRunner
Provides common test execution patterns.

```python
from benchbox.core.tpc_patterns import TestRunner

# Create test runner
runner = TestRunner(connection_factory)

# Run single query test
result = runner.run_single_query_test(query_id=1, query_executor=executor)

# Run sequential test
results = runner.run_sequential_test([1, 2, 3], query_executor=executor)

# Run concurrent test
results = runner.run_concurrent_test(stream_configs, query_executor=executor)
```

### 6. ErrorHandler
Standardized error handling with retry policies.

```python
from benchbox.core.tpc_patterns import ErrorHandler, RetryPolicy

# Create error handler
handler = ErrorHandler(
    retry_policy=RetryPolicy.EXPONENTIAL_BACKOFF,
    max_retries=3
)

# Handle errors
context = {'query_id': 1, 'stream_id': 0, 'retry_count': 0}
should_retry = handler.handle_error(exception, context)
```

### 7. ProgressTracker
Tracks test progress and provides logging.

```python
from benchbox.core.tpc_patterns import ProgressTracker

# Create progress tracker
tracker = ProgressTracker(total_items=100, description="Processing queries")

# Update progress
tracker.update(completed=1, item_description="Query 1 completed")

# Get summary
summary = tracker.get_summary()
```

### 8. ResultAggregator
Combines results from multiple streams/queries.

```python
from benchbox.core.tpc_patterns import ResultAggregator

# Create aggregator
aggregator = ResultAggregator()

# Add results
aggregator.add_stream_result(stream_result)
aggregator.add_query_result(query_result)

# Get aggregated results
results = aggregator.get_aggregated_results()
```

## Usage Patterns

### Pattern 1: Simple Sequential Execution

```python
from benchbox.core.tpc_patterns import TestRunner, create_basic_query_executor
from benchbox import TPCH

# Create benchmark
benchmark = TPCH(scale_factor=1.0)

# Create connection factory
def connection_factory():
    return create_database_connection()

# Create query executor
query_executor = create_basic_query_executor(benchmark)

# Create test runner
runner = TestRunner(connection_factory)

# Run sequential test
results = runner.run_sequential_test([1, 2, 3, 4, 5], query_executor)
```

### Pattern 2: Concurrent Stream Execution

```python
from benchbox.core.tpc_patterns import (
    StreamExecutor, create_tpc_stream_configs, create_basic_query_executor
)
from benchbox import TPCH

# Create benchmark
benchmark = TPCH(scale_factor=1.0)

# Create connection factory
def connection_factory():
    return create_database_connection()

# Create query executor
query_executor = create_basic_query_executor(benchmark)

# Create stream configurations
stream_configs = create_tpc_stream_configs(
    num_streams=4,
    query_ids=list(range(1, 23)),  # TPC-H queries 1-22
    base_seed=42,
    permutation_mode="tpc_standard"
)

# Execute streams
executor = StreamExecutor(connection_factory, max_concurrent_streams=4)
results = executor.execute_streams(stream_configs, query_executor)
```

### Pattern 3: Custom Query Execution with Validation

```python
from benchbox.core.tpc_patterns import (
    TestRunner, create_basic_query_executor, create_validation_function
)

# Create validation function
expected_results = {
    1: {"row_count": 4},
    2: {"row_count": 460},
    3: {"row_count": 10}
}
validator = create_validation_function(expected_results)

# Run validation test
results = runner.run_validation_test(
    query_ids=[1, 2, 3],
    query_executor=query_executor,
    validator=validator
)
```

### Pattern 4: Custom Parameter Generation

```python
from benchbox.core.tpc_patterns import ParameterManager

class CustomParameterManager(ParameterManager):
    def _generate_query_parameters(self, query_id, rng, scale_factor):
        # Custom parameter generation logic
        params = super()._generate_query_parameters(query_id, rng, scale_factor)

        # Add custom parameters
        params.update({
            'custom_param1': rng.randint(1, 100),
            'custom_param2': rng.choice(['A', 'B', 'C']),
            'date_range': f"{rng.randint(1990, 2020)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        })

        return params

# Use custom parameter manager
manager = CustomParameterManager(base_seed=42)
params = manager.generate_parameters(query_id=1, stream_id=0)
```

## Configuration Options

### Stream Configuration

```python
from benchbox.core.tpc_patterns import StreamConfig, PermutationConfig, RetryPolicy

stream_config = StreamConfig(
    stream_id=0,
    query_ids=[1, 2, 3, 4, 5],
    permutation_config=PermutationConfig(
        mode="tpc_standard",
        seed=42,
        ensure_unique=True
    ),
    parameter_seed=1042,
    isolation_level="READ_COMMITTED",
    timeout=300.0,  # 5 minutes
    retry_policy=RetryPolicy.EXPONENTIAL_BACKOFF,
    max_retries=3
)
```

### Permutation Configuration

```python
from benchbox.core.tpc_patterns import PermutationConfig

# Sequential permutation
config = PermutationConfig(mode="sequential")

# Random permutation with seed
config = PermutationConfig(mode="random", seed=42)

# TPC standard permutation
config = PermutationConfig(mode="tpc_standard", seed=42, ensure_unique=True)
```

## Result Structure

### Query Result

```python
{
    'query_id': 1,
    'stream_id': 0,
    'execution_time': 0.125,
    'status': 'completed',
    'error': None,
    'row_count': 4,
    'retry_count': 0,
    'parameters': {...}
}
```

### Aggregated Results

```python
{
    'total_streams': 2,
    'total_queries': 10,
    'successful_queries': 9,
    'failed_queries': 1,
    'success_rate': 0.9,
    'total_execution_time': 2.5,
    'average_execution_time': 0.25,
    'min_execution_time': 0.1,
    'max_execution_time': 0.5,
    'stream_statistics': {
        0: {
            'total_queries': 5,
            'successful_queries': 5,
            'failed_queries': 0,
            'total_execution_time': 1.2,
            'status': 'completed'
        },
        1: {
            'total_queries': 5,
            'successful_queries': 4,
            'failed_queries': 1,
            'total_execution_time': 1.3,
            'status': 'completed'
        }
    },
    'query_results': [...]
}
```

## Error Handling

The module provides systematic error handling with retry policies:

- **NONE**: No retries
- **FIXED_DELAY**: Fixed delay between retries
- **LINEAR_BACKOFF**: Increasing delay (1s, 2s, 3s, ...)
- **EXPONENTIAL_BACKOFF**: Exponential delay (1s, 2s, 4s, 8s, ...)

Retryable errors are automatically detected based on common patterns like:
- Connection timeouts
- Network errors
- Database locks
- Temporary failures

## Performance Considerations

1. **Connection Pooling**: Use connection pooling to reduce connection overhead
2. **Concurrent Streams**: Limit concurrent streams based on database capacity
3. **Memory Management**: Monitor memory usage for large result sets
4. **Timeout Configuration**: Set appropriate timeouts for long-running queries
5. **Retry Strategy**: Choose appropriate retry policies for your environment

## Best Practices

1. **Use Deterministic Seeds**: Always use seeds for reproducible results
2. **Proper Transaction Management**: Use appropriate isolation levels
3. **Monitor Progress**: Use progress tracking for long-running tests
4. **Validate Results**: Implement proper result validation
5. **Error Logging**: Enable systematic logging for debugging
6. **Resource Cleanup**: Ensure connections are properly closed

## Integration with Existing Benchmarks

The TPC patterns can be easily integrated with existing TPC-H and TPC-DS benchmarks:

```python
# With TPC-H
from benchbox import TPCH
from benchbox.core.tpc_patterns import create_basic_query_executor

benchmark = TPCH(scale_factor=1.0)
query_executor = create_basic_query_executor(benchmark)

# With TPC-DS
from benchbox.tpcds import TPCDSBenchmark
from benchbox.core.tpc_patterns import create_basic_query_executor

benchmark = TPCDSBenchmark(scale_factor=1.0)
query_executor = create_basic_query_executor(benchmark)
```

This provides a consistent interface for both benchmarks while maintaining their specific implementations.
