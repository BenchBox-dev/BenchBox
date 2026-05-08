<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# TPC Test Result Validation System

```{tags} intermediate, guide, validation, tpc-h, tpc-ds
```

A systematic validation system for TPC benchmark test results that ensures compliance with official TPC specification requirements.

## Overview

The TPC Test Result Validation System provides:

- **Comprehensive Validation**: Validates all aspects of TPC test results including completeness, query execution, timing, data integrity, and metrics
- **Compliance Checking**: Ensures results meet official TPC specification requirements
- **Certification Readiness**: Validates certification requirements and generates readiness reports
- **Audit Trail**: Tracks all validation activities for reproducibility and compliance auditing
- **Multi-Benchmark Support**: Supports TPC-H, TPC-DS, TPC-DI, and other TPC benchmarks
- **Detailed Reporting**: Generates systematic validation reports with issue tracking and metrics

## Architecture

The validation system consists of several key components:

### Core Components

- **`TPCResultValidator`**: Main validation engine that coordinates all validation activities
- **`ValidationReport`**: Comprehensive report containing all validation results, issues, and metrics
- **`AuditTrail`**: Tracks all validation events for reproducibility and compliance auditing

### Validators

- **`CompletenessValidator`**: Ensures all required tests completed successfully
- **`QueryResultValidator`**: Validates query execution results and performance
- **`TimingValidator`**: Validates timing measurements and precision requirements
- **`DataIntegrityValidator`**: Validates data integrity during maintenance operations
- **`MetricsValidator`**: Validates metric calculations and statistical validity
- **`ComplianceChecker`**: Checks overall TPC compliance requirements
- **`CertificationChecker`**: Validates certification readiness and requirements

## Installation

The validation system is included in the BenchBox library:

```python
from benchbox.core.tpc_validation import TPCResultValidator, ValidationLevel
```

## Quick Start

### Basic Usage

```python
from benchbox.core.tpc_validation import TPCResultValidator, ValidationLevel

# Create validator
validator = TPCResultValidator()

# Prepare test results (see Test Results Format section)
test_results = {
    "benchmark_name": "TPC-H",
    "scale_factor": 1.0,
    "test_start_time": "2023-01-01T10:00:00Z",
    "test_end_time": "2023-01-01T11:00:00Z",
    "query_results": {
        "1": {
            "status": "success",
            "execution_time": 5.2,
            "row_count": 100,
            "results": [{"col1": "value1", "col2": "value2"}]
        }
    },
    "data_generation": {
        "generation_time": 120.5,
        "generated_tables": ["customer", "orders", "lineitem"]
    },
    "metrics": {
        "avg_query_time": 5.2,
        "total_query_time": 5.2
    }
}

# Validate results
report = validator.validate(test_results, ValidationLevel.STANDARD)

# Check results
print(f"Overall Result: {report.overall_result.value}")
print(f"Validation Score: {report.metrics.get('validation_score', 0):.1f}%")
print(f"Issues Found: {len(report.issues)}")
```

### Configuration

You can customize the validation behavior with configuration:

```python
config = {
    "validators": {
        "completeness": {
            "required_queries": {"TPC-H": list(range(1, 23))},
            "required_tables": ["customer", "orders", "lineitem"]
        },
        "timing": {
            "max_execution_time": 3600,
            "precision_threshold": 0.001
        },
        "certification": {
            "required_documentation": ["test_report", "environment_spec"],
            "performance_thresholds": {
                "avg_query_time": 30.0
            }
        }
    }
}

validator = TPCResultValidator(config)
```

## Test Results Format

The validation system expects test results in the following format:

```python
test_results = {
    # Required fields
    "benchmark_name": "TPC-H",  # Benchmark name (TPC-H, TPC-DS, TPC-DI)
    "scale_factor": 1.0,        # Scale factor used
    "test_start_time": "2023-01-01T10:00:00Z",  # ISO format timestamp
    "test_end_time": "2023-01-01T11:00:00Z",    # ISO format timestamp

    # Query execution results
    "query_results": {
        "1": {
            "status": "success",      # success, failed, timeout
            "execution_time": 5.2,    # Execution time in seconds
            "row_count": 100,         # Number of rows returned
            "results": [...],         # Optional: actual query results
            "error": "..."           # Optional: error message if failed
        }
    },

    # Data generation information
    "data_generation": {
        "generation_time": 120.5,   # Time to generate data in seconds
        "generated_tables": ["customer", "orders", "lineitem"]
    },

    # Calculated metrics
    "metrics": {
        "avg_query_time": 5.2,
        "total_query_time": 5.2,
        "queries_per_second": 0.19
    },

    # Optional: Maintenance operations (for TPC-DS, TPC-DI)
    "maintenance_operations": {
        "insert_operation": {
            "status": "success",
            "start_time": "2023-01-01T10:30:00Z",
            "end_time": "2023-01-01T10:35:00Z",
            "records_affected": 5000
        }
    },

    # Optional: ETL operations (for TPC-DI)
    "etl_operations": {
        "extract_customers": {
            "status": "success",
            "start_time": "2023-01-01T09:00:00Z",
            "end_time": "2023-01-01T09:15:00Z",
            "records_processed": 150000
        }
    },

    # Reproducibility information
    "reproducibility": {
        "seed": 12345,
        "timestamp": "2023-01-01T10:00:00Z",
        "environment": "test_env"
    },

    # Test isolation
    "test_isolation": {
        "isolated": True
    },

    # Documentation
    "documentation": {
        "test_report": "path/to/test_report.pdf",
        "environment_spec": "path/to/env_spec.json"
    }
}
```

## Validation Levels

The system supports three validation levels:

### ValidationLevel.BASIC
- Basic completeness checks
- Query execution validation
- Simple timing validation

### ValidationLevel.STANDARD
- All basic validations
- Data integrity validation
- Metrics validation
- Compliance checking

### ValidationLevel.CERTIFICATION
- All standard validations
- Certification readiness checks
- Enhanced documentation requirements
- Performance threshold validation

## Validation Results

### ValidationResult Enum
- `PASSED`: All validations passed
- `WARNING`: Validations passed with warnings
- `FAILED`: One or more validations failed
- `SKIPPED`: Validation was skipped

### ValidationReport
The `ValidationReport` contains:
- Overall validation result
- Individual validator results
- Detailed issues with levels (ERROR, WARNING, INFO)
- Calculated metrics
- Execution summary
- Audit trail
- Certification status

## Individual Validators

### CompletenessValidator
Validates that all required test components are present:
- Required queries executed
- Required tables generated
- Required maintenance operations completed
- Execution metadata present

### QueryResultValidator
Validates query execution results:
- All queries executed successfully
- Execution times within acceptable bounds
- Row counts reasonable
- Result data integrity
- Schema validation (if configured)

### TimingValidator
Validates timing measurements:
- Total test time reasonable
- Query execution times consistent
- Timing precision adequate
- Data generation timing reasonable

### DataIntegrityValidator
Validates data integrity during maintenance operations:
- Maintenance operations successful
- Referential integrity maintained
- Data consistency preserved
- Transaction isolation maintained

### MetricsValidator
Validates calculated metrics:
- Required metrics present
- Metric values within expected ranges
- Calculated metrics match reported values
- Statistical validity of results

### ComplianceChecker
Checks TPC compliance requirements:
- Benchmark-specific requirements (TPC-H: 22 queries, TPC-DS: 99 queries)
- Scale factor compliance
- Test isolation requirements
- Reproducibility requirements

### CertificationChecker
Validates certification readiness:
- Performance thresholds met
- Documentation complete
- Test completeness for certification
- Overall readiness assessment

## Integration with Existing Benchmarks

The validation system integrates smoothly with existing TPC benchmarks:

### TPC-H Integration

```python
from benchbox import TPCH
from benchbox.core.tpc_validation import TPCResultValidator

# Create benchmark
benchmark = TPCH(scale_factor=1.0)

# Run benchmark (collect results)
test_results = run_benchmark_and_collect_results(benchmark)

# Validate results
validator = TPCResultValidator()
report = validator.validate(test_results, ValidationLevel.STANDARD)
```

### TPC-DS Integration

```python
from benchbox.tpcds import TPCDSBenchmark
from benchbox.core.tpc_validation import TPCResultValidator

# Create benchmark
benchmark = TPCDSBenchmark(scale_factor=1.0)

# Run benchmark (collect results)
test_results = run_benchmark_and_collect_results(benchmark)

# Validate results with TPC-DS specific config
config = {
    "validators": {
        "completeness": {
            "required_queries": {"TPC-DS": list(range(1, 100))},
            "required_maintenance_ops": ["insert_sales", "update_inventory"]
        }
    }
}

validator = TPCResultValidator(config)
report = validator.validate(test_results, ValidationLevel.CERTIFICATION)
```

## Custom Validators

You can create custom validators for specific requirements:

```python
from benchbox.core.tpc_validation import BaseValidator, ValidationResult

class CustomBusinessRuleValidator(BaseValidator):
    def validate(self, test_results, report):
        # Custom validation logic
        query_results = test_results.get("query_results", {})

        if len(query_results) < 5:
            report.add_issue(
                "ERROR",
                f"Minimum 5 queries required, found {len(query_results)}",
                {"query_count": len(query_results)},
                self.name
            )
            return ValidationResult.FAILED

        return ValidationResult.PASSED

# Use custom validator
validator = TPCResultValidator()
validator.validators.append(CustomBusinessRuleValidator("custom_business_rules"))
```

## Report Management

### Saving Reports

```python
from pathlib import Path

# Save validation report
validator.save_report(report, Path("validation_report.json"))

# Save to specific directory
report_dir = Path("validation_reports")
report_dir.mkdir(exist_ok=True)
validator.save_report(report, report_dir / "tpch_validation.json")
```

### Loading Reports

```python
# Load validation report
loaded_report = validator.load_report(Path("validation_report.json"))

# Access report data
print(f"Report ID: {loaded_report.validation_id}")
print(f"Overall Result: {loaded_report.overall_result.value}")
```

### Report Analysis

```python
# Get issues by level
errors = report.get_issues_by_level("ERROR")
warnings = report.get_issues_by_level("WARNING")

# Get issues by validator
timing_issues = report.get_issues_by_validator("timing")
compliance_issues = report.get_issues_by_validator("compliance")

# Access metrics
validation_score = report.metrics.get("validation_score", 0)
total_queries = report.execution_summary.get("total_queries", 0)
success_rate = report.execution_summary.get("success_rate", 0)
```

## Examples

### Basic Example

```python
from benchbox.core.tpc_validation import create_sample_test_results, TPCResultValidator

# Create sample test results
test_results = create_sample_test_results()

# Validate
validator = TPCResultValidator()
report = validator.validate(test_results)

# Print results
print(f"Result: {report.overall_result.value}")
print(f"Issues: {len(report.issues)}")
```

### Certification Example

```python
# Configure for certification
config = {
    "validators": {
        "certification": {
            "required_documentation": ["test_report", "environment_spec"],
            "performance_thresholds": {
                "avg_query_time": 30.0
            }
        }
    }
}

validator = TPCResultValidator(config)
report = validator.validate(test_results, ValidationLevel.CERTIFICATION)

print(f"Certification Status: {report.certification_status}")
```

### Multi-Benchmark Suite

```python
# Run validation suite across multiple benchmarks
benchmarks = ["TPC-H", "TPC-DS", "TPC-DI"]
suite_results = {}

for benchmark in benchmarks:
    test_results = run_benchmark(benchmark)
    report = validator.validate(test_results)
    suite_results[benchmark] = report

# Generate compliance summary
compliance_summary = {
    benchmark: {
        "compliant": len(report.get_issues_by_level("ERROR")) == 0,
        "score": report.metrics.get("validation_score", 0)
    }
    for benchmark, report in suite_results.items()
}
```

## Best Practices

### 1. Configuration Management
- Use configuration files for complex validation setups
- Store benchmark-specific configurations separately
- Version control your validation configurations

### 2. Error Handling
- Always check validation results before proceeding
- Handle validation failures gracefully
- Log validation issues for debugging

### 3. Performance Considerations
- Use appropriate validation levels for your use case
- Consider caching validation results for repeated runs
- Profile validation performance for large test suites

### 4. Compliance Tracking
- Save validation reports for audit trails
- Track compliance over time
- Generate regular compliance summaries

### 5. Integration
- Integrate validation into your CI/CD pipeline
- Use validation results to gate releases
- Monitor validation trends over time

## Troubleshooting

### Common Issues

1. **Missing Required Fields**
   - Ensure all required fields are present in test results
   - Check field names and formats match specifications

2. **Timing Validation Failures**
   - Verify timestamp formats are ISO 8601 compliant
   - Check for reasonable execution times
   - Ensure timing consistency across measurements

3. **Query Result Validation Issues**
   - Verify all queries completed successfully
   - Check row counts and result formats
   - Validate error handling for failed queries

4. **Compliance Failures**
   - Check benchmark-specific requirements
   - Verify all required queries are present
   - Ensure maintenance operations are included where required

### Debug Mode

Enable debug logging for detailed validation information:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

validator = TPCResultValidator()
report = validator.validate(test_results)
```

## API Reference

### TPCResultValidator
- `__init__(config=None)`: Create validator with optional configuration
- `validate(test_results, validation_level=ValidationLevel.STANDARD)`: Validate test results
- `save_report(report, output_path)`: Save validation report to file
- `load_report(input_path)`: Load validation report from file
- `create_default_config()`: Create default configuration

### ValidationReport
- `add_issue(level, message, details=None, validator_name="")`: Add validation issue
- `get_issues_by_level(level)`: Get issues by severity level
- `get_issues_by_validator(validator_name)`: Get issues by validator
- `to_dict()`: Convert report to dictionary for serialization

### BaseValidator
- `validate(test_results, report)`: Perform validation (abstract method)
- `_check_required_fields(data, required_fields)`: Check for required fields

## Contributing

To contribute to the TPC validation system:

1. Create new validators by inheriting from `BaseValidator`
2. Add benchmark-specific validation rules
3. Extend the configuration system
4. Add new validation levels
5. Improve error reporting and diagnostics

## License

This validation system is part of the BenchBox library and follows the same license terms.
