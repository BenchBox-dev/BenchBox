<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# BenchBox Benchmark Validator

The unified benchmark validator is a comprehensive tool for validating all BenchBox benchmarks. It consolidates functionality from various validation scripts and provides a unified interface for schema validation, query syntax validation, data generation verification, and comprehensive reporting.

## Features

### Core Validation Capabilities
- **Schema Validation**: Validates benchmark schema definitions and structure
- **Query Syntax Validation**: Uses DuckDB parser for real SQL validation
- **Data Generation Verification**: Tests data generation with configurable scale factors
- **Interface Compliance**: Ensures benchmarks follow the BenchBox interface
- **OLAP Feature Validation**: Tests support for advanced OLAP features
- **Cross-benchmark Compatibility**: Validates compatibility across benchmarks

### Reporting
- **Multiple Output Formats**: Text, JSON, and Markdown reports
- **Comprehensive Metrics**: Success rates, execution times, detailed error reporting
- **Configurable Validation Levels**: Quick check, standard validation, or full validation

### Command Line Interface
- **Flexible Benchmark Selection**: Validate individual benchmarks or all at once
- **Configurable Scale Factors**: Test with different data sizes
- **Selective Validation**: Choose which validation types to run
- **Output Control**: Save reports to files or display on console

## Installation & Dependencies

### Required Dependencies
```bash
pip install benchbox  # The BenchBox library
```

### Optional Dependencies
```bash
pip install duckdb    # For enhanced query syntax validation
```

## Usage

### Command Line Usage

#### Basic Usage
```bash
# Validate all benchmarks with default settings
python tests/utilities/benchmark_validator.py

# Validate specific benchmark
python tests/utilities/benchmark_validator.py --benchmark tpch

# Multiple benchmarks
python tests/utilities/benchmark_validator.py --benchmark tpch,tpcds
```

#### Validation Options
```bash
# Quick validation (fast checks only)
python tests/utilities/benchmark_validator.py --benchmark tpch --quick-check

# Full validation (includes data generation)
python tests/utilities/benchmark_validator.py --benchmark tpch --full-validation

# Schema validation only
python tests/utilities/benchmark_validator.py --benchmark tpch --validate-schema

# Query validation only
python tests/utilities/benchmark_validator.py --benchmark tpch --validate-queries
```

#### Scale Factor and Output
```bash
# Custom scale factor
python tests/utilities/benchmark_validator.py --benchmark tpch --scale 0.1

# JSON output
python tests/utilities/benchmark_validator.py --benchmark tpch --output-format json

# Save to file
python tests/utilities/benchmark_validator.py --benchmark tpch --output-file validation_report.txt

# Markdown report
python tests/utilities/benchmark_validator.py --benchmark tpch --output-format markdown --output-file report.md
```

### Python API Usage

#### Basic Validation
```python
from tests.utilities.benchmark_validator import BenchmarkValidator

# Create validator
validator = BenchmarkValidator(verbose=True)

# Validate single benchmark
report = validator.validate_benchmark(
    benchmark_name='tpch',
    scale_factor=0.01,
    quick_check=True
)

print(f"Valid: {report.is_valid}")
print(f"Success Rate: {report.success_rate:.1f}%")
```

#### Comprehensive Validation
```python
# Validate multiple benchmarks
results = validator.validate_all_benchmarks(
    benchmarks=['tpch', 'tpcds', 'primitives'],
    scale_factor=0.01,
    full_validation=True
)

# Generate report
report = validator.generate_report(results, 'markdown')
print(report)
```

#### Custom Validation
```python
# Schema validation only
schema_report = validator.validate_benchmark(
    benchmark_name='tpch',
    validate_schema=True,
    validate_queries=False,
    validate_data=False
)

# Query validation with custom DuckDB connection
import duckdb
conn = duckdb.connect(':memory:')
validator = BenchmarkValidator(duckdb_connection=conn)
```

## Validation Types

### Schema Validation
- Validates presence of required schema methods
- Checks schema structure and format
- Validates table definitions
- Ensures schema is not empty

### Query Validation
- Validates presence of query methods
- Checks query structure and format
- Uses DuckDB parser for SQL syntax validation
- Tests parameterized queries if available
- Validates query count and completeness

### Data Generation Validation
- Tests data generation methods
- Validates generated file presence and format
- Checks file sizes and basic content
- Validates data generation with different scale factors

### Interface Compliance
- Validates required attributes (name, scale_factor, etc.)
- Checks required methods (get_queries, get_schema, generate_data)
- Ensures proper inheritance from BaseBenchmark
- Validates configuration handling

### OLAP Feature Validation
- Tests window functions support
- Validates CTE (Common Table Expression) support
- Checks grouping sets and aggregation functions
- Tests array functions and advanced SQL features

## Supported Benchmarks

The validator supports all BenchBox benchmarks:
- **TPC-H**: `tpch`
- **TPC-DS**: `tpcds`
- **Primitives**: `primitives`
- **SSB**: `ssb`
- **AMPLab**: `amplab`
- **ClickBench**: `clickbench`
- **H2O.ai Database Benchmark**: `h2odb`
- **Merge**: `merge`
- **TPC-DI**: `tpcdi`

## Report Formats

### Text Report
```
================================================================================
BENCHBOX VALIDATION REPORT
================================================================================

SUMMARY:
  Total Benchmarks: 2
  Valid Benchmarks: 2
  Total Checks: 25
  Passed: 23
  Failed: 2
  Warnings: 0
  Overall Success Rate: 92.0%

BENCHMARK: TPCH
----------------------------------------
  Status: VALID
  Checks: 15 total, 14 passed, 1 failed
  Warnings: 0
  Success Rate: 93.3%
  Execution Time: 2.34s
  Details: {'schema_tables': 8, 'query_count': 22}
```

### JSON Report
```json
{
  "summary": {
    "total_benchmarks": 2,
    "valid_benchmarks": 2,
    "total_checks": 25,
    "passed_checks": 23,
    "failed_checks": 2,
    "warnings": 0
  },
  "benchmarks": {
    "tpch": {
      "status": "valid",
      "total_checks": 15,
      "passed_checks": 14,
      "failed_checks": 1,
      "success_rate": 93.3,
      "execution_time": 2.34
    }
  }
}
```

### Markdown Report
```markdown
# BenchBox Validation Report

## Summary
- **Total Benchmarks**: 2
- **Valid Benchmarks**: 2
- **Overall Success Rate**: 92.0%

## Benchmark Results

### TPCH
- **Status**: VALID
- **Success Rate**: 93.3%
- **Execution Time**: 2.34s
```

## Error Handling

The validator provides comprehensive error handling and reporting:

### Error Categories
- **import**: Issues with benchmark imports
- **schema**: Schema validation errors
- **queries**: Query validation errors
- **data_generation**: Data generation errors
- **interface**: Interface compliance errors
- **olap**: OLAP feature validation errors

### Error Severity Levels
- **error**: Critical errors that cause validation failure
- **warn**: Warnings that don't cause validation failure
- **info**: Informational messages

## Performance Considerations

### Quick Check Mode
- Validates only essential functionality
- Skips data generation
- Limits query validation to first 5 queries
- Typically completes in under 10 seconds

### Standard Validation
- Validates all core functionality
- Includes basic data generation tests
- Validates all queries
- Typically completes in 30-60 seconds

### Full Validation
- Comprehensive validation including data generation
- OLAP feature testing
- Cross-benchmark compatibility checks
- May take several minutes for large benchmarks

## Troubleshooting

### Common Issues

#### DuckDB Not Available
```
WARNING: DuckDB not available. Query syntax validation will be limited.
```
**Solution**: Install DuckDB with `pip install duckdb`

#### BenchBox Not Available
```
ERROR: BenchBox not available. Please install BenchBox.
```
**Solution**: Install BenchBox or ensure it's in your Python path

#### Data Generation Failures
```
[data_generation] Data generation failed: [error details]
```
**Solution**: Check scale factor, available disk space, and benchmark-specific requirements

### Verbose Logging
Use `--verbose` flag for detailed logging:
```bash
python tests/utilities/benchmark_validator.py --benchmark tpch --verbose
```

## Integration

The validator is designed to integrate with:
- **CI/CD Pipelines**: Use exit codes for automated testing
- **Testing Frameworks**: Import and use programmatically
- **Monitoring Systems**: JSON output for automated processing
- **Documentation Systems**: Markdown output for reports

## Examples

See `examples/validate_benchmarks.py` for practical usage examples.

## Contributing

When adding new validation features:
1. Add validation method to `BenchmarkValidator` class
2. Update `validate_benchmark` method to call new validation
3. Add appropriate error handling and reporting
4. Update documentation and examples
5. Add tests for new functionality

## License

This validator is part of the BenchBox project and follows the same license terms.
