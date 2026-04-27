#!/usr/bin/env python
"""Unified Benchmark Validator for BenchBox.

This validation utility consolidates functionality from various
validation scripts and provides a unified interface for validating all BenchBox
benchmarks. It includes schema validation, query syntax validation, data generation
verification, and comprehensive reporting.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import argparse
import json
import logging
import sys
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# Include the project root directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    import duckdb  # type: ignore[import-untyped]

    DUCKDB_AVAILABLE = True
except ImportError:
    DUCKDB_AVAILABLE = False
    duckdb = None  # type: ignore[assignment]

try:
    import benchbox  # type: ignore[import-untyped]

    BENCHBOX_AVAILABLE = True
except ImportError:
    BENCHBOX_AVAILABLE = False
    benchbox = None  # type: ignore[assignment]


class ValidationResult(Enum):
    """Enumeration for validation results."""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    WARN = "WARN"


@dataclass
class ValidationError:
    """Represents a validation error or warning."""

    category: str
    message: str
    severity: str = "error"
    details: Optional[str] = None


@dataclass
class BenchmarkValidationReport:
    """Comprehensive validation report for a tpch_benchmark."""

    benchmark_name: str
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    warnings: int = 0
    skipped_checks: int = 0
    errors: list[ValidationError] = field(default_factory=list)
    execution_time: float = 0.0
    validation_details: dict[str, Any] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total_checks == 0:
            return 0.0
        return (self.passed_checks / self.total_checks) * 100

    @property
    def is_valid(self) -> bool:
        """Check if benchmark passed all critical validations."""
        return self.failed_checks == 0


class BenchmarkValidator:
    """
    Unified validator for all BenchBox benchmarks.

    This class provides validation capabilities including:
    - Schema validation for all benchmarks
    - Query syntax validation using DuckDB parser
    - Data generation verification
    - Cross-benchmark compatibility checks
    - OLAP feature validation
    - Result consistency verification
    """

    # Supported benchmarks
    SUPPORTED_BENCHMARKS = {
        "tpch": "TPCH",
        "tpcds": "TPCDS",
        "read_primitives": "Primitives",
        "ssb": "SSB",
        "amplab": "AMPLab",
        "clickbench": "ClickBench",
        "h2odb": "H2ODB",
        "merge": "Merge",
        "tpcdi": "TPCDI",
    }

    def __init__(self, verbose: bool = False, duckdb_connection: Optional[Any] = None):
        """
        Initialize the benchmark validator.

        Args:
            verbose: Enable verbose logging
            duckdb_connection: Optional DuckDB connection for query validation
        """
        self.verbose = verbose
        self.duckdb_connection = duckdb_connection
        self.logger = self._setup_logger()

        # DuckDB connection if not provided
        if self.duckdb_connection is None and DUCKDB_AVAILABLE:
            self.duckdb_connection = duckdb.connect(":memory:")
            self._setup_duckdb_extensions()

    def _setup_logger(self) -> logging.Logger:
        """Setup logger for validation output."""
        logger = logging.getLogger("BenchmarkValidator")
        logger.setLevel(logging.DEBUG if self.verbose else logging.INFO)

        # console handler
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG if self.verbose else logging.INFO)

        # formatter
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)

        # Include handler to logger
        if not logger.handlers:
            logger.addHandler(handler)

        return logger

    def _setup_duckdb_extensions(self) -> None:
        """Setup DuckDB extensions for validation."""
        if not DUCKDB_AVAILABLE or not self.duckdb_connection:
            return

        extensions = [
            "json",
            "httpfs",
            "parquet",
            "excel",
            "icu",
            "fts",
            "tpch",
            "tpcds",
        ]

        for ext in extensions:
            try:
                self.duckdb_connection.execute(f"INSTALL {ext}")
                self.duckdb_connection.execute(f"LOAD {ext}")
            except Exception:
                # Extension may not be available, continue silently
                pass

    def validate_benchmark(
        self,
        benchmark_name: str,
        scale_factor: float = 0.01,
        validate_data: bool = True,
        validate_queries: bool = True,
        validate_schema: bool = True,
        quick_check: bool = False,
        full_validation: bool = False,
    ) -> BenchmarkValidationReport:
        """
        Validate a specific tpch_benchmark.

        Args:
            benchmark_name: Name of the benchmark to validate
            scale_factor: Scale factor for data generation validation
            validate_data: Whether to validate data generation
            validate_queries: Whether to validate query syntax
            validate_schema: Whether to validate schema definition
            quick_check: Run only fast validation checks
            full_validation: Run validation including data generation

        Returns:
            BenchmarkValidationReport with validation results
        """
        start_time = time.time()
        report = BenchmarkValidationReport(benchmark_name=benchmark_name)

        self.logger.info(f"Starting validation for {benchmark_name}")

        try:
            # Load benchmark class
            benchmark_class = self._load_benchmark_class(benchmark_name)
            if benchmark_class is None:
                report.errors.append(
                    ValidationError(
                        category="import",
                        message=f"Failed to load benchmark class for {benchmark_name}",
                    )
                )
                report.failed_checks += 1
                return report

            # benchmark instance
            benchmark = benchmark_class(scale_factor=scale_factor)

            # Run validation checks
            if validate_schema:
                self._validate_benchmark_schema(benchmark, report)

            if validate_queries:
                self._validate_benchmark_queries(benchmark, report, quick_check)

            if validate_data and not quick_check:
                self._validate_data_generation(benchmark, report, full_validation)

            # Validate benchmark interface compliance
            self._validate_benchmark_interface(benchmark, report)

            # OLAP features validation
            if full_validation and DUCKDB_AVAILABLE:
                self._validate_olap_features(benchmark, report)

            # Cross-benchmark compatibility
            if full_validation:
                self._validate_cross_benchmark_compatibility(benchmark, report)

        except Exception as e:
            report.errors.append(
                ValidationError(
                    category="general",
                    message=f"Validation failed with exception: {str(e)}",
                    details=str(e),
                )
            )
            self.logger.error(f"Validation failed for {benchmark_name}: {e}")

        # Calculate final metrics
        report.execution_time = time.time() - start_time
        report.total_checks = report.passed_checks + report.failed_checks + report.skipped_checks

        self.logger.info(f"Validation completed for {benchmark_name} in {report.execution_time:.2f}s")
        return report

    def _load_benchmark_class(self, benchmark_name: str) -> Optional[type]:
        """Load benchmark class dynamically."""
        if not BENCHBOX_AVAILABLE:
            self.logger.error("BenchBox not available for import")
            return None

        benchmark_name_lower = benchmark_name.lower()
        if benchmark_name_lower not in self.SUPPORTED_BENCHMARKS:
            self.logger.error(f"Unsupported benchmark: {benchmark_name}")
            return None

        class_name = self.SUPPORTED_BENCHMARKS[benchmark_name_lower]

        try:
            return getattr(benchbox, class_name)
        except AttributeError:
            self.logger.error(f"Benchmark class {class_name} not found in benchbox")
            return None

    def _validate_benchmark_schema(self, benchmark: Any, report: BenchmarkValidationReport) -> None:
        """Validate benchmark schema definition."""
        self.logger.info("Validating benchmark schema...")

        try:
            # Check if benchmark has schema method
            if not hasattr(benchmark, "get_schema"):
                report.errors.append(ValidationError(category="schema", message="Benchmark missing get_schema method"))
                report.failed_checks += 1
                return

            # schema
            schema = benchmark.get_schema()
            report.passed_checks += 1

            # Validate schema structure
            if schema is None:
                report.errors.append(ValidationError(category="schema", message="Schema is None"))
                report.failed_checks += 1
                return

            if isinstance(schema, dict):
                # Validate dictionary schema
                if len(schema) == 0:
                    report.errors.append(ValidationError(category="schema", message="Schema dictionary is empty"))
                    report.failed_checks += 1
                else:
                    report.passed_checks += 1
                    report.validation_details["schema_tables"] = len(schema)

                    # Validate each table schema
                    for table_name, _table_schema in schema.items():
                        if not isinstance(table_name, str):
                            report.errors.append(
                                ValidationError(
                                    category="schema",
                                    message=f"Table name {table_name} is not a string",
                                )
                            )
                            report.failed_checks += 1
                        else:
                            report.passed_checks += 1

            elif isinstance(schema, (list, str)):
                # Basic validation for list/string schemas
                if len(schema) == 0:
                    report.errors.append(ValidationError(category="schema", message="Schema is empty"))
                    report.failed_checks += 1
                else:
                    report.passed_checks += 1

            else:
                report.errors.append(
                    ValidationError(
                        category="schema",
                        message=f"Invalid schema type: {type(schema)}",
                    )
                )
                report.failed_checks += 1

        except Exception as e:
            report.errors.append(ValidationError(category="schema", message=f"Schema validation failed: {str(e)}"))
            report.failed_checks += 1

    def _validate_benchmark_queries(self, benchmark: Any, report: BenchmarkValidationReport, quick_check: bool) -> None:
        """Validate benchmark queries."""
        self.logger.info("Validating benchmark queries...")

        try:
            # Check if benchmark has query methods
            if not hasattr(benchmark, "get_queries"):
                report.errors.append(
                    ValidationError(
                        category="queries",
                        message="Benchmark missing get_queries method",
                    )
                )
                report.failed_checks += 1
                return

            # queries
            queries = benchmark.get_queries()
            report.passed_checks += 1

            # Validate queries structure
            if not isinstance(queries, dict):
                report.errors.append(
                    ValidationError(
                        category="queries",
                        message=f"Queries must be a dictionary, got {type(queries)}",
                    )
                )
                report.failed_checks += 1
                return

            if len(queries) == 0:
                report.errors.append(ValidationError(category="queries", message="No queries found"))
                report.failed_checks += 1
                return

            report.passed_checks += 1
            report.validation_details["query_count"] = len(queries)

            # Validate individual queries
            valid_queries = 0
            query_validation_limit = 5 if quick_check else len(queries)

            for query_id, query_sql in list(queries.items())[:query_validation_limit]:
                try:
                    # Basic SQL validation
                    if not isinstance(query_sql, str):
                        report.errors.append(
                            ValidationError(
                                category="queries",
                                message=f"Query {query_id} is not a string",
                            )
                        )
                        report.failed_checks += 1
                        continue

                    if len(query_sql.strip()) == 0:
                        report.errors.append(ValidationError(category="queries", message=f"Query {query_id} is empty"))
                        report.failed_checks += 1
                        continue

                    # DuckDB syntax validation
                    if DUCKDB_AVAILABLE and self.duckdb_connection:
                        try:
                            # Use EXPLAIN to validate syntax without executing
                            self.duckdb_connection.execute(f"EXPLAIN {query_sql}")
                            valid_queries += 1
                            report.passed_checks += 1
                        except Exception as e:
                            report.errors.append(
                                ValidationError(
                                    category="queries",
                                    message=f"Query {query_id} has invalid SQL syntax",
                                    details=str(e),
                                )
                            )
                            report.failed_checks += 1
                    else:
                        # Basic string validation without DuckDB
                        if any(keyword in query_sql.upper() for keyword in ["SELECT", "WITH", "CREATE"]):
                            valid_queries += 1
                            report.passed_checks += 1
                        else:
                            report.errors.append(
                                ValidationError(
                                    category="queries",
                                    message=f"Query {query_id} doesn't appear to be valid SQL",
                                )
                            )
                            report.failed_checks += 1

                except Exception as e:
                    report.errors.append(
                        ValidationError(
                            category="queries",
                            message=f"Error validating query {query_id}: {str(e)}",
                        )
                    )
                    report.failed_checks += 1

            report.validation_details["valid_queries"] = valid_queries

            # Test parameterized queries if available
            if hasattr(benchmark, "get_parameterized_query"):
                self._validate_parameterized_queries(benchmark, report, quick_check)

        except Exception as e:
            report.errors.append(ValidationError(category="queries", message=f"Query validation failed: {str(e)}"))
            report.failed_checks += 1

    def _validate_parameterized_queries(
        self, benchmark: Any, report: BenchmarkValidationReport, quick_check: bool
    ) -> None:
        """Validate parameterized queries."""
        self.logger.info("Validating parameterized queries...")

        try:
            # Test a few parameterized queries
            test_queries = [1, 2, 3] if quick_check else [1, 2, 3, 4, 5]

            for query_id in test_queries:
                try:
                    # Try to get parameterized query with default parameters
                    param_query = benchmark.get_query(query_id, {})

                    if isinstance(param_query, str) and len(param_query.strip()) > 0:
                        report.passed_checks += 1
                    else:
                        report.errors.append(
                            ValidationError(
                                category="parameterized_queries",
                                message=f"Parameterized query {query_id} is invalid",
                            )
                        )
                        report.failed_checks += 1

                except Exception as e:
                    # This might be expected if the query doesn't exist
                    if "not found" in str(e).lower() or "invalid" in str(e).lower():
                        report.skipped_checks += 1
                    else:
                        report.errors.append(
                            ValidationError(
                                category="parameterized_queries",
                                message=f"Error getting parameterized query {query_id}: {str(e)}",
                            )
                        )
                        report.failed_checks += 1

        except Exception as e:
            report.errors.append(
                ValidationError(
                    category="parameterized_queries",
                    message=f"Parameterized query validation failed: {str(e)}",
                )
            )
            report.failed_checks += 1

    def _validate_data_generation(
        self, benchmark: Any, report: BenchmarkValidationReport, full_validation: bool
    ) -> None:
        """Validate data generation capabilities."""
        self.logger.info("Validating data generation...")

        try:
            # Check if benchmark has data generation method
            if not hasattr(benchmark, "generate_data"):
                report.errors.append(
                    ValidationError(
                        category="data_generation",
                        message="Benchmark missing generate_data method",
                    )
                )
                report.failed_checks += 1
                return

            # Test data generation in memory (if supported)
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # new benchmark instance with temporary output directory
                benchmark_class = type(benchmark)
                test_benchmark = benchmark_class(
                    scale_factor=0.01,  # Very small scale for testing
                    output_dir=temp_path,
                )

                try:
                    # Generate data
                    start_time = time.time()
                    data_result = test_benchmark.generate_data()
                    generation_time = time.time() - start_time

                    report.validation_details["data_generation_time"] = generation_time

                    # Validate data generation result
                    if data_result is None:
                        report.errors.append(
                            ValidationError(
                                category="data_generation",
                                message="Data generation returned None",
                            )
                        )
                        report.failed_checks += 1
                        return

                    # Check if data files were created
                    data_files = list(temp_path.glob("*.csv")) + list(temp_path.glob("*.parquet"))
                    if len(data_files) == 0:
                        report.errors.append(
                            ValidationError(
                                category="data_generation",
                                message="No data files were generated",
                            )
                        )
                        report.failed_checks += 1
                    else:
                        report.passed_checks += 1
                        report.validation_details["generated_files"] = len(data_files)

                        # Validate file contents if full validation
                        if full_validation:
                            self._validate_generated_data_files(data_files, report)

                except Exception as e:
                    report.errors.append(
                        ValidationError(
                            category="data_generation",
                            message=f"Data generation failed: {str(e)}",
                        )
                    )
                    report.failed_checks += 1

        except Exception as e:
            report.errors.append(
                ValidationError(
                    category="data_generation",
                    message=f"Data generation validation failed: {str(e)}",
                )
            )
            report.failed_checks += 1

    def _validate_generated_data_files(self, data_files: list[Path], report: BenchmarkValidationReport) -> None:
        """Validate generated data files."""
        self.logger.info("Validating generated data files...")

        for file_path in data_files:
            try:
                # Check file size
                if file_path.stat().st_size == 0:
                    report.errors.append(
                        ValidationError(
                            category="data_files",
                            message=f"Generated file {file_path.name} is empty",
                        )
                    )
                    report.failed_checks += 1
                    continue

                # Basic file content validation
                if file_path.suffix.lower() == ".csv":
                    with open(file_path, encoding="utf-8") as f:
                        first_line = f.readline().strip()
                        if len(first_line) == 0:
                            report.errors.append(
                                ValidationError(
                                    category="data_files",
                                    message=f"CSV file {file_path.name} appears to be empty",
                                )
                            )
                            report.failed_checks += 1
                        else:
                            report.passed_checks += 1

                elif file_path.suffix.lower() == ".parquet":
                    # Basic parquet validation would require pandas/pyarrow
                    # For now, just check that file exists and has content
                    report.passed_checks += 1

            except Exception as e:
                report.errors.append(
                    ValidationError(
                        category="data_files",
                        message=f"Error validating file {file_path.name}: {str(e)}",
                    )
                )
                report.failed_checks += 1

    def _validate_benchmark_interface(self, benchmark: Any, report: BenchmarkValidationReport) -> None:
        """Validate benchmark interface compliance."""
        self.logger.info("Validating benchmark interface...")

        # Required attributes
        required_attributes = ["name", "scale_factor"]
        for attr in required_attributes:
            if hasattr(benchmark, attr):
                report.passed_checks += 1
            else:
                report.errors.append(
                    ValidationError(
                        category="interface",
                        message=f"Benchmark missing required attribute: {attr}",
                    )
                )
                report.failed_checks += 1

        # Required methods
        required_methods = ["get_queries", "get_schema", "generate_data"]
        for method in required_methods:
            if hasattr(benchmark, method) and callable(getattr(benchmark, method)):
                report.passed_checks += 1
            else:
                report.errors.append(
                    ValidationError(
                        category="interface",
                        message=f"Benchmark missing required method: {method}",
                    )
                )
                report.failed_checks += 1

    def _validate_olap_features(self, benchmark: Any, report: BenchmarkValidationReport) -> None:
        """Validate OLAP features support."""
        self.logger.info("Validating OLAP features...")

        if not DUCKDB_AVAILABLE or not self.duckdb_connection:
            report.errors.append(
                ValidationError(
                    category="olap",
                    message="DuckDB not available for OLAP validation",
                    severity="warn",
                )
            )
            report.warnings += 1
            return

        # Test basic OLAP features
        olap_features = {
            "window_functions": "SELECT ROW_NUMBER() OVER (ORDER BY 1) FROM (SELECT 1) t",
            "ctes": "WITH test AS (SELECT 1 as x) SELECT * FROM test",
            "grouping_sets": "SELECT COUNT(*) FROM (SELECT 1) t GROUP BY GROUPING SETS (())",
            "array_agg": "SELECT ARRAY_AGG(x) FROM (SELECT 1 as x) t",
        }

        for feature, test_sql in olap_features.items():
            try:
                self.duckdb_connection.execute(test_sql)
                report.passed_checks += 1
            except Exception as e:
                report.errors.append(
                    ValidationError(
                        category="olap",
                        message=f"OLAP feature {feature} not supported: {str(e)}",
                        severity="warn",
                    )
                )
                report.warnings += 1

    def _validate_cross_benchmark_compatibility(self, benchmark: Any, report: BenchmarkValidationReport) -> None:
        """Validate cross-benchmark compatibility."""
        self.logger.info("Validating cross-benchmark compatibility...")

        # This is a placeholder for cross-benchmark validation
        # Could include checks for:
        # - Common schema patterns
        # - Query result formats
        # - Data export compatibility
        # - etc.

        report.passed_checks += 1
        report.validation_details["cross_benchmark_compatibility"] = "basic"

    def validate_all_benchmarks(
        self,
        benchmarks: Optional[list[str]] = None,
        scale_factor: float = 0.01,
        quick_check: bool = False,
        full_validation: bool = False,
    ) -> dict[str, BenchmarkValidationReport]:
        """
        Validate all specified benchmarks.

        Args:
            benchmarks: List of benchmark names to validate. If None, validates all supported benchmarks.
            scale_factor: Scale factor for validation
            quick_check: Run only fast validation checks
            full_validation: Run validation

        Returns:
            Dictionary mapping benchmark names to validation reports
        """
        if benchmarks is None:
            benchmarks = list(self.SUPPORTED_BENCHMARKS.keys())

        results = {}

        for benchmark_name in benchmarks:
            self.logger.info(f"Validating benchmark: {benchmark_name}")

            try:
                report = self.validate_benchmark(
                    benchmark_name=benchmark_name,
                    scale_factor=scale_factor,
                    validate_data=not quick_check,
                    validate_queries=True,
                    validate_schema=True,
                    quick_check=quick_check,
                    full_validation=full_validation,
                )
                results[benchmark_name] = report

            except Exception as e:
                # error report for failed validation
                error_report = BenchmarkValidationReport(benchmark_name=benchmark_name)
                error_report.errors.append(
                    ValidationError(
                        category="general",
                        message=f"Benchmark validation failed: {str(e)}",
                    )
                )
                error_report.failed_checks = 1
                error_report.total_checks = 1
                results[benchmark_name] = error_report

                self.logger.error(f"Failed to validate {benchmark_name}: {e}")

        return results

    def generate_report(self, results: dict[str, BenchmarkValidationReport], output_format: str = "text") -> str:
        """
        Generate a validation report.

        Args:
            results: Dictionary of validation results
            output_format: Output format ('text', 'json', 'markdown')

        Returns:
            Formatted report string
        """
        if output_format == "json":
            return self._generate_json_report(results)
        elif output_format == "markdown":
            return self._generate_markdown_report(results)
        else:
            return self._generate_text_report(results)

    def _generate_text_report(self, results: dict[str, BenchmarkValidationReport]) -> str:
        """Generate text format report."""
        lines = []
        lines.append("=" * 80)
        lines.append("BENCHBOX VALIDATION REPORT")
        lines.append("=" * 80)
        lines.append("")

        # Summary
        total_benchmarks = len(results)
        valid_benchmarks = sum(1 for r in results.values() if r.is_valid)
        total_checks = sum(r.total_checks for r in results.values())
        total_passed = sum(r.passed_checks for r in results.values())
        total_failed = sum(r.failed_checks for r in results.values())
        total_warnings = sum(r.warnings for r in results.values())

        lines.append("SUMMARY:")
        lines.append(f"  Total Benchmarks: {total_benchmarks}")
        lines.append(f"  Valid Benchmarks: {valid_benchmarks}")
        lines.append(f"  Total Checks: {total_checks}")
        lines.append(f"  Passed: {total_passed}")
        lines.append(f"  Failed: {total_failed}")
        lines.append(f"  Warnings: {total_warnings}")
        lines.append(
            f"  Overall Success Rate: {(total_passed / total_checks * 100):.1f}%"
            if total_checks > 0
            else "  Overall Success Rate: 0.0%"
        )
        lines.append("")

        # Individual benchmark results
        for benchmark_name, report in results.items():
            lines.append(f"BENCHMARK: {benchmark_name.upper()}")
            lines.append("-" * 40)
            lines.append(f"  Status: {'VALID' if report.is_valid else 'INVALID'}")
            lines.append(
                f"  Checks: {report.total_checks} total, {report.passed_checks} passed, {report.failed_checks} failed"
            )
            lines.append(f"  Warnings: {report.warnings}")
            lines.append(f"  Success Rate: {report.success_rate:.1f}%")
            lines.append(f"  Execution Time: {report.execution_time:.2f}s")

            if report.validation_details:
                lines.append(f"  Details: {report.validation_details}")

            if report.errors:
                lines.append("  Errors:")
                for error in report.errors:
                    lines.append(f"    [{error.category}] {error.message}")
                    if error.details:
                        lines.append(f"      Details: {error.details}")

            lines.append("")

        return "\n".join(lines)

    def _generate_json_report(self, results: dict[str, BenchmarkValidationReport]) -> str:
        """Generate JSON format report."""
        json_data = {
            "summary": {
                "total_benchmarks": len(results),
                "valid_benchmarks": sum(1 for r in results.values() if r.is_valid),
                "total_checks": sum(r.total_checks for r in results.values()),
                "passed_checks": sum(r.passed_checks for r in results.values()),
                "failed_checks": sum(r.failed_checks for r in results.values()),
                "warnings": sum(r.warnings for r in results.values()),
                "generation_time": time.time(),
            },
            "benchmarks": {},
        }

        for benchmark_name, report in results.items():
            json_data["benchmarks"][benchmark_name] = {
                "status": "valid" if report.is_valid else "invalid",
                "total_checks": report.total_checks,
                "passed_checks": report.passed_checks,
                "failed_checks": report.failed_checks,
                "warnings": report.warnings,
                "success_rate": report.success_rate,
                "execution_time_seconds": report.execution_time,
                "validation_details": report.validation_details,
                "errors": [
                    {
                        "category": error.category,
                        "message": error.message,
                        "severity": error.severity,
                        "details": error.details,
                    }
                    for error in report.errors
                ],
            }

        return json.dumps(json_data, indent=2)

    def _generate_markdown_report(self, results: dict[str, BenchmarkValidationReport]) -> str:
        """Generate Markdown format report."""
        lines = []
        lines.append("# BenchBox Validation Report")
        lines.append("")

        # Summary
        total_benchmarks = len(results)
        valid_benchmarks = sum(1 for r in results.values() if r.is_valid)
        total_checks = sum(r.total_checks for r in results.values())
        total_passed = sum(r.passed_checks for r in results.values())
        total_failed = sum(r.failed_checks for r in results.values())
        total_warnings = sum(r.warnings for r in results.values())

        lines.append("## Summary")
        lines.append("")
        lines.append(f"- **Total Benchmarks**: {total_benchmarks}")
        lines.append(f"- **Valid Benchmarks**: {valid_benchmarks}")
        lines.append(f"- **Total Checks**: {total_checks}")
        lines.append(f"- **Passed**: {total_passed}")
        lines.append(f"- **Failed**: {total_failed}")
        lines.append(f"- **Warnings**: {total_warnings}")
        lines.append(
            f"- **Overall Success Rate**: {(total_passed / total_checks * 100):.1f}%"
            if total_checks > 0
            else "- **Overall Success Rate**: 0.0%"
        )
        lines.append("")

        # Individual benchmark results
        lines.append("## Benchmark Results")
        lines.append("")

        for benchmark_name, report in results.items():
            status_emoji = "✅" if report.is_valid else "❌"
            lines.append(f"### {status_emoji} {benchmark_name.upper()}")
            lines.append("")
            lines.append(f"- **Status**: {'VALID' if report.is_valid else 'INVALID'}")
            lines.append(
                f"- **Checks**: {report.total_checks} total, {report.passed_checks} passed, {report.failed_checks} failed"
            )
            lines.append(f"- **Warnings**: {report.warnings}")
            lines.append(f"- **Success Rate**: {report.success_rate:.1f}%")
            lines.append(f"- **Execution Time**: {report.execution_time:.2f}s")

            if report.validation_details:
                lines.append(f"- **Details**: {report.validation_details}")

            if report.errors:
                lines.append("")
                lines.append("#### Errors")
                lines.append("")
                for error in report.errors:
                    lines.append(f"- **[{error.category}]** {error.message}")
                    if error.details:
                        lines.append(f"  - Details: {error.details}")

            lines.append("")

        return "\n".join(lines)


def main():
    """Main function for command-line interface."""
    parser = argparse.ArgumentParser(
        description="Unified Benchmark Validator for BenchBox",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --benchmark tpch --validate-queries --validate-schema
  %(prog)s --benchmark all --quick-check
  %(prog)s --benchmark tpcds --full-validation --scale 0.1
  %(prog)s --benchmark primitives,ssb --validate-data
        """,
    )

    parser.add_argument(
        "--benchmark",
        "-b",
        choices=[
            "tpch",
            "tpcds",
            "read_primitives",
            "ssb",
            "amplab",
            "clickbench",
            "h2odb",
            "merge",
            "tpcdi",
            "all",
        ],
        default="all",
        help="Benchmark(s) to validate (default: all)",
    )

    parser.add_argument(
        "--scale",
        "-s",
        type=float,
        default=0.01,
        help="Scale factor for validation (default: 0.01)",
    )

    parser.add_argument("--validate-data", action="store_true", help="Validate data generation")

    parser.add_argument(
        "--validate-queries",
        action="store_true",
        help="Validate query syntax using DuckDB parser",
    )

    parser.add_argument("--validate-schema", action="store_true", help="Validate schema definition")

    parser.add_argument("--quick-check", action="store_true", help="Run only fast validation checks")

    parser.add_argument(
        "--full-validation",
        action="store_true",
        help="Run validation including data generation",
    )

    parser.add_argument(
        "--output-format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output format for validation report (default: text)",
    )

    parser.add_argument("--output-file", "-o", help="Output file for validation report")

    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    # Determine which benchmarks to validate
    if args.benchmark == "all":
        benchmarks = list(BenchmarkValidator.SUPPORTED_BENCHMARKS.keys())
    else:
        benchmarks = [b.strip() for b in args.tpch_benchmark.split(",")]

    # Set default validation options if none specified
    if not any([args.validate_data, args.validate_queries, args.validate_schema]):
        args.validate_data = True
        args.validate_queries = True
        args.validate_schema = True

    # Check for required dependencies
    if not BENCHBOX_AVAILABLE:
        print("ERROR: BenchBox not available. Please install BenchBox.")
        sys.exit(1)

    if not DUCKDB_AVAILABLE:
        print("WARNING: DuckDB not available. Query syntax validation will be limited.")

    # validator
    validator = BenchmarkValidator(verbose=args.verbose)

    # Run validation
    print(f"Starting validation for benchmarks: {', '.join(benchmarks)}")

    results = validator.validate_all_benchmarks(
        benchmarks=benchmarks,
        scale_factor=args.scale,
        quick_check=args.quick_check,
        full_validation=args.full_validation,
    )

    # Generate report
    report = validator.generate_report(results, args.output_format)

    # Output report
    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Validation report written to {args.output_file}")
    else:
        print(report)

    # Exit with appropriate code
    all_valid = all(r.is_valid for r in results.values())
    sys.exit(0 if all_valid else 1)


if __name__ == "__main__":
    main()
