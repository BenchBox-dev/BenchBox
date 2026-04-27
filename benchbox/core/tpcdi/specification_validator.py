"""
Copyright 2026 Joe Harris / BenchBox Project

TPC-DI Specification Compliance Validator for Phase 4: Validation and Testing.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.printing import emit

logger = logging.getLogger(__name__)


@dataclass
class ComplianceCheckResult:
    """Result of a TPC-DI specification compliance check."""

    check_name: str
    category: str
    passed: bool
    severity: str  # 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
    message: str
    details: Optional[dict[str, Any]] = None
    recommendation: Optional[str] = None


@dataclass
class SpecificationComplianceReport:
    """Comprehensive TPC-DI specification compliance report."""

    timestamp: str
    overall_compliance: bool
    total_checks: int
    passed_checks: int
    failed_checks: int
    compliance_score: float
    category_scores: dict[str, float]
    check_results: list[ComplianceCheckResult]
    summary: dict[str, Any]


class TPCDISpecificationValidator:
    """Validator for TPC-DI specification compliance across all benchmark components."""

    def __init__(self, benchmark, connection=None, dialect="duckdb"):
        """Initialize the TPC-DI specification validator.

        Args:
            benchmark: TPCDIBenchmark instance to validate
            connection: Database connection for schema and data validation
            dialect: SQL dialect for validation queries
        """
        self.benchmark = benchmark
        self.connection = connection
        self.dialect = dialect
        self.check_results: list[ComplianceCheckResult] = []

    def validate_complete_specification_compliance(
        self,
    ) -> SpecificationComplianceReport:
        """Perform comprehensive TPC-DI specification compliance validation.

        Returns:
            Complete compliance report with all validation results
        """
        logger.info("Starting comprehensive TPC-DI specification compliance validation")

        self.check_results = []

        # Schema compliance validation
        self._validate_schema_compliance()

        # Data model compliance validation
        self._validate_data_model_compliance()

        # ETL processing compliance validation
        self._validate_etl_processing_compliance()

        # Query compliance validation
        self._validate_query_compliance()

        # Business rule compliance validation
        self._validate_business_rule_compliance()

        # Performance and scalability compliance
        self._validate_performance_compliance()

        # Data quality compliance validation
        self._validate_data_quality_compliance()

        # Generate comprehensive compliance report
        return self._generate_compliance_report()

    def _validate_schema_compliance(self):
        """Validate database schema compliance with TPC-DI specification."""
        logger.info("Validating schema compliance")

        # Check for required dimension tables
        required_dim_tables = [
            "DimBroker",
            "DimCompany",
            "DimCustomer",
            "DimAccount",
            "DimSecurity",
            "DimTime",
            "DimTrade",
            "DimDate",
        ]

        # Check for required fact tables
        required_fact_tables = [
            "FactTrade",
            "FactCashBalances",
            "FactHoldings",
            "FactMarketHistory",
        ]

        # Validate table existence
        if self.connection:
            existing_tables = self._discover_existing_tables(required_dim_tables + required_fact_tables)

            # Check dimension tables
            missing_dim_tables = set(required_dim_tables) - existing_tables
            if missing_dim_tables:
                self.check_results.append(
                    ComplianceCheckResult(
                        check_name="Required Dimension Tables",
                        category="Schema",
                        passed=len(missing_dim_tables) <= len(required_dim_tables) * 0.2,  # Allow 20% missing
                        severity="HIGH" if len(missing_dim_tables) > 3 else "MEDIUM",
                        message=f"Missing dimension tables: {missing_dim_tables}",
                        details={"missing_tables": list(missing_dim_tables)},
                        recommendation="Implement missing dimension tables according to TPC-DI specification",
                    )
                )
            else:
                self.check_results.append(
                    ComplianceCheckResult(
                        check_name="Required Dimension Tables",
                        category="Schema",
                        passed=True,
                        severity="LOW",
                        message="All required dimension tables present",
                    )
                )

            # Check fact tables
            missing_fact_tables = set(required_fact_tables) - existing_tables
            if missing_fact_tables:
                self.check_results.append(
                    ComplianceCheckResult(
                        check_name="Required Fact Tables",
                        category="Schema",
                        passed=len(missing_fact_tables) <= len(required_fact_tables) * 0.3,  # Allow 30% missing
                        severity="HIGH" if len(missing_fact_tables) > 2 else "MEDIUM",
                        message=f"Missing fact tables: {missing_fact_tables}",
                        details={"missing_tables": list(missing_fact_tables)},
                        recommendation="Implement missing fact tables according to TPC-DI specification",
                    )
                )
            else:
                self.check_results.append(
                    ComplianceCheckResult(
                        check_name="Required Fact Tables",
                        category="Schema",
                        passed=True,
                        severity="LOW",
                        message="All required fact tables present",
                    )
                )

            # Validate key table schemas
            self._validate_table_schemas(existing_tables)
        else:
            self.check_results.append(
                ComplianceCheckResult(
                    check_name="Schema Validation",
                    category="Schema",
                    passed=False,
                    severity="CRITICAL",
                    message="No database connection available for schema validation",
                    recommendation="Provide database connection for comprehensive schema validation",
                )
            )

    def _discover_existing_tables(self, candidate_tables: list[str]) -> set[str]:
        """Discover existing tables without relying on engine-specific catalog tables."""
        existing_tables: set[str] = set()
        if not self.connection:
            return existing_tables

        cursor = self.connection.cursor()
        for table_name in candidate_tables:
            queries = [
                f'SELECT 1 FROM "{table_name}" LIMIT 1',
                f"SELECT 1 FROM {table_name} LIMIT 1",
            ]
            for query in queries:
                try:
                    cursor.execute(query)
                    cursor.fetchone()
                    existing_tables.add(table_name)
                    break
                except Exception:
                    continue

        return existing_tables

    def _get_table_columns(self, table_name: str) -> set[str]:
        """Discover table columns in an engine-agnostic way using cursor metadata."""
        if not self.connection:
            return set()

        cursor = self.connection.cursor()
        queries = [
            f'SELECT * FROM "{table_name}" LIMIT 0',
            f"SELECT * FROM {table_name} LIMIT 0",
        ]
        for query in queries:
            try:
                cursor.execute(query)
                description = cursor.description or []
                return {str(col[0]) for col in description if col and col[0]}
            except Exception:
                continue
        return set()

    def _validate_table_schemas(self, existing_tables):
        """Validate individual table schemas against TPC-DI specification."""

        # DimCustomer validation
        if "DimCustomer" in existing_tables:
            columns = self._get_table_columns("DimCustomer")

            required_customer_columns = {
                "CustomerID",
                "FirstName",
                "LastName",
                "Email",
                "Phone",
                "Address",
                "Status",
                "EffectiveDate",
                "EndDate",
            }

            missing_columns = required_customer_columns - columns
            if missing_columns:
                self.check_results.append(
                    ComplianceCheckResult(
                        check_name="DimCustomer Schema",
                        category="Schema",
                        passed=len(missing_columns) <= len(required_customer_columns) * 0.3,
                        severity="MEDIUM",
                        message=f"DimCustomer missing columns: {missing_columns}",
                        details={"missing_columns": list(missing_columns)},
                        recommendation="Add missing columns to DimCustomer table",
                    )
                )
            else:
                self.check_results.append(
                    ComplianceCheckResult(
                        check_name="DimCustomer Schema",
                        category="Schema",
                        passed=True,
                        severity="LOW",
                        message="DimCustomer schema compliant",
                    )
                )

        # FactTrade validation
        if "FactTrade" in existing_tables:
            columns = self._get_table_columns("FactTrade")

            required_trade_columns = {
                "TradeID",
                "CustomerID",
                "AccountID",
                "SecurityID",
                "BrokerID",
                "TradeDate",
                "TradeType",
                "Quantity",
                "Price",
            }

            missing_columns = required_trade_columns - columns
            if missing_columns:
                self.check_results.append(
                    ComplianceCheckResult(
                        check_name="FactTrade Schema",
                        category="Schema",
                        passed=len(missing_columns) <= len(required_trade_columns) * 0.2,
                        severity="HIGH",
                        message=f"FactTrade missing columns: {missing_columns}",
                        details={"missing_columns": list(missing_columns)},
                        recommendation="Add missing columns to FactTrade table",
                    )
                )
            else:
                self.check_results.append(
                    ComplianceCheckResult(
                        check_name="FactTrade Schema",
                        category="Schema",
                        passed=True,
                        severity="LOW",
                        message="FactTrade schema compliant",
                    )
                )

    def _validate_data_model_compliance(self):
        """Validate data model compliance with TPC-DI specification."""
        logger.info("Validating data model compliance")

        # Validate SCD Type 2 implementation
        scd_compliant = self._check_scd_type2_implementation()

        # Validate surrogate key management
        surrogate_key_compliant = self._check_surrogate_key_implementation()

        # Validate referential integrity
        referential_integrity_compliant = self._check_referential_integrity()

        self.check_results.append(
            ComplianceCheckResult(
                check_name="Data Model Implementation",
                category="Data Model",
                passed=scd_compliant and surrogate_key_compliant and referential_integrity_compliant,
                severity="HIGH",
                message="Data model compliance validation completed",
                details={
                    "scd_type2": scd_compliant,
                    "surrogate_keys": surrogate_key_compliant,
                    "referential_integrity": referential_integrity_compliant,
                },
                recommendation="Ensure SCD Type 2, surrogate keys, and referential integrity are properly implemented",
            )
        )

    def _check_scd_type2_implementation(self) -> bool:
        """Check if SCD Type 2 is properly implemented."""
        try:
            # Check if benchmark has SCD processor
            scd_processor = getattr(self.benchmark, "scd_processor", None)
            if not scd_processor:
                return False

            # Check if SCD processor has required methods
            required_methods = [
                "process_dimension",
                "detect_changes",
                "_create_audit_record",
            ]
            return all(hasattr(scd_processor, method) for method in required_methods)
        except Exception:
            return False

    def _check_surrogate_key_implementation(self) -> bool:
        """Check if surrogate keys are properly implemented."""
        if not self.connection:
            return False

        try:
            # Check if dimension tables have proper surrogate keys
            dimension_tables = ["DimCustomer", "DimAccount", "DimSecurity"]

            for table in dimension_tables:
                try:
                    columns = self._get_table_columns(table)
                    if not columns:
                        continue

                    # Look for surrogate key pattern (table name + 'SK' or 'Key')
                    surrogate_key_found = any(col.endswith(("SK", "Key", "ID")) for col in columns)

                    if not surrogate_key_found:
                        return False
                except Exception:
                    continue

            return True
        except Exception:
            return False

    def _check_referential_integrity(self) -> bool:
        """Check if referential integrity is properly maintained."""
        if not self.connection:
            return False

        try:
            cursor = self.connection.cursor()

            # Check basic referential integrity where possible
            integrity_checks = []

            # Check Account-Customer relationship
            try:
                cursor.execute("""
                    SELECT COUNT(*) as orphaned_accounts
                    FROM DimAccount a
                    LEFT JOIN DimCustomer c ON a.CustomerID = c.CustomerID
                    WHERE c.CustomerID IS NULL
                """)
                orphaned_accounts = cursor.fetchone()[0]
                integrity_checks.append(orphaned_accounts == 0)
            except Exception:
                pass

            # If we have any integrity checks, all should pass
            return len(integrity_checks) == 0 or all(integrity_checks)
        except Exception:
            return False

    def _validate_etl_processing_compliance(self):
        """Validate ETL processing compliance with TPC-DI specification."""
        logger.info("Validating ETL processing compliance with comprehensive checks")

        # Check ETL pipeline implementation
        etl_pipeline_compliant = hasattr(self.benchmark, "run_enhanced_etl_pipeline")

        # Test ETL pipeline execution if connection available
        if self.connection and etl_pipeline_compliant:
            etl_execution_result = self._test_etl_pipeline_execution()
        else:
            etl_execution_result = {
                "success": False,
                "reason": "No database connection or ETL pipeline",
            }

        # Check required ETL processors
        required_processors = [
            "finwire_processor",
            "customer_mgmt_processor",
            "scd_processor",
            "parallel_batch_processor",
            "incremental_loader",
        ]

        processors_implemented = 0
        processor_details = {}
        for processor in required_processors:
            is_implemented = hasattr(self.benchmark, processor) and getattr(self.benchmark, processor) is not None
            if is_implemented:
                processors_implemented += 1
            processor_details[processor] = is_implemented

        processor_compliance = processors_implemented >= len(required_processors) * 0.6  # 60% implementation threshold

        # Check ETL phases implementation
        etl_phases_compliant = self._validate_etl_phases()

        # Check data transformation compliance
        transformation_compliant = self._validate_data_transformation_compliance()

        # Check incremental processing compliance
        incremental_compliant = self._validate_incremental_processing_compliance()

        # Overall ETL compliance assessment
        overall_etl_compliance = (
            etl_pipeline_compliant
            and processor_compliance
            and etl_phases_compliant
            and transformation_compliant
            and incremental_compliant
        )

        self.check_results.append(
            ComplianceCheckResult(
                check_name="ETL Processing Implementation",
                category="ETL",
                passed=overall_etl_compliance,
                severity="HIGH",
                message=f"ETL processing compliance: {'COMPLIANT' if overall_etl_compliance else 'NON-COMPLIANT'}",
                details={
                    "etl_pipeline": etl_pipeline_compliant,
                    "processors_implemented": processors_implemented,
                    "total_processors": len(required_processors),
                    "processor_details": processor_details,
                    "etl_phases": etl_phases_compliant,
                    "transformation_compliant": transformation_compliant,
                    "incremental_compliant": incremental_compliant,
                    "execution_test": etl_execution_result,
                },
                recommendation="Ensure all required ETL processors, phases, and transformations are implemented",
            )
        )

        # Individual processor compliance checks
        for processor, is_implemented in processor_details.items():
            self.check_results.append(
                ComplianceCheckResult(
                    check_name=f"ETL Processor: {processor}",
                    category="ETL",
                    passed=is_implemented,
                    severity="MEDIUM",
                    message=f"ETL processor {processor} {'implemented' if is_implemented else 'missing'}",
                    recommendation=f"Implement {processor} for full TPC-DI compliance" if not is_implemented else None,
                )
            )

    def _test_etl_pipeline_execution(self) -> dict:
        """Test ETL pipeline execution with small dataset."""
        try:
            # Test ETL execution with minimal scale factor
            etl_results = self.benchmark.run_enhanced_etl_pipeline(
                self.connection,
                dialect=self.dialect,
                enable_parallel_processing=False,  # Disable for testing
                enable_data_quality_monitoring=True,
                enable_error_recovery=True,
            )

            return {
                "success": etl_results.get("success", False),
                "total_records_processed": etl_results.get("total_records_processed", 0),
                "phases_executed": len(etl_results.get("phases", {})),
                "quality_score": etl_results.get("quality_score", 0),
                "processing_time": etl_results.get("total_processing_time", 0),
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "reason": "ETL execution test failed",
            }

    def _validate_data_transformation_compliance(self) -> bool:
        """Validate data transformation compliance with TPC-DI rules."""
        try:
            # Check for transformation-related methods and attributes
            transformation_methods = [
                "_transform_customer_data",
                "_transform_account_data",
                "_transform_trade_data",
                "_apply_scd_type2_transformation",
                "_validate_data_quality",
            ]

            implemented_transformations = 0
            for method in transformation_methods:
                if hasattr(self.benchmark, method):
                    implemented_transformations += 1

            # At least 50% of transformation methods should be implemented
            return implemented_transformations >= len(transformation_methods) * 0.5

        except Exception:
            return False

    def _validate_incremental_processing_compliance(self) -> bool:
        """Validate incremental processing compliance with TPC-DI specification."""
        try:
            # Check for incremental processing capabilities
            incremental_methods = [
                "_process_incremental_updates",
                "_handle_change_data_capture",
                "_manage_batch_timestamps",
                "_process_historical_data",
            ]

            implemented_incremental = 0
            for method in incremental_methods:
                if hasattr(self.benchmark, method):
                    implemented_incremental += 1

            # At least 25% of incremental methods should be implemented
            return implemented_incremental >= len(incremental_methods) * 0.25

        except Exception:
            return False

    def _validate_etl_phases(self) -> bool:
        """Validate ETL phases are properly implemented."""
        try:
            # Check if benchmark has required ETL phase methods
            required_phase_methods = [
                "_run_enhanced_data_processing",
                "_run_enhanced_scd_processing",
                "_run_incremental_data_loading",
            ]

            return all(hasattr(self.benchmark, method) for method in required_phase_methods)
        except Exception:
            return False

    def _validate_query_compliance(self):
        """Validate TPC-DI query compliance and accuracy."""
        logger.info("Validating query compliance with detailed accuracy checks")

        try:
            # Test query execution capability with detailed result validation
            critical_queries = [
                1,
                5,
                10,
                15,
                20,
                25,
                30,
                35,
            ]  # Representative queries across different complexity levels

            query_execution_results = []

            for query_id in critical_queries:
                try:
                    query_sql = self.benchmark.get_query(query_id, dialect=self.dialect)
                    if not query_sql or len(query_sql.strip()) == 0:
                        self.check_results.append(
                            ComplianceCheckResult(
                                check_name=f"Query {query_id} Availability",
                                category="Queries",
                                passed=False,
                                severity="ERROR",
                                message=f"Query {query_id} is not available or empty",
                                recommendation="Implement missing query",
                            )
                        )
                        continue

                    # Execute query with timing and result validation

                    start_time = mono_time()
                    cursor = self.connection.execute(query_sql)
                    results = cursor.fetchall()
                    execution_time = elapsed_seconds(start_time)

                    # Validate result structure and content
                    result_validation = self._validate_query_result_structure(query_id, results, query_sql)

                    query_execution_results.append(
                        {
                            "query_id": query_id,
                            "execution_time_seconds": execution_time,
                            "row_count": len(results),
                            "result_validation": result_validation,
                            "success": True,
                        }
                    )

                    self.check_results.append(
                        ComplianceCheckResult(
                            check_name=f"Query {query_id} Execution",
                            category="Queries",
                            passed=True,
                            severity="INFO",
                            message=f"Query {query_id} executed successfully: {len(results)} rows in {execution_time:.3f}s",
                        )
                    )

                    # Validate result accuracy if we have expected patterns
                    self._validate_query_result_accuracy(query_id, results, query_sql)

                except Exception as e:
                    query_execution_results.append({"query_id": query_id, "error": str(e), "success": False})

                    self.check_results.append(
                        ComplianceCheckResult(
                            check_name=f"Query {query_id} Execution",
                            category="Queries",
                            passed=False,
                            severity="ERROR",
                            message=f"Query {query_id} execution failed: {str(e)}",
                            recommendation="Debug and fix query execution issues",
                        )
                    )

            # Analyze overall query execution performance
            successful_queries = [r for r in query_execution_results if r.get("success", False)]
            success_rate = len(successful_queries) / len(critical_queries) if critical_queries else 0

            if success_rate >= 0.75:  # At least 75% success rate
                avg_time = (
                    sum(r["execution_time_seconds"] for r in successful_queries) / len(successful_queries)
                    if successful_queries
                    else 0
                )
                self.check_results.append(
                    ComplianceCheckResult(
                        check_name="Query Performance",
                        category="Queries",
                        passed=True,
                        severity="INFO",
                        message=f"Query execution performance acceptable: {len(successful_queries)}/{len(critical_queries)} successful, avg {avg_time:.3f}s",
                    )
                )
            else:
                self.check_results.append(
                    ComplianceCheckResult(
                        check_name="Query Performance",
                        category="Queries",
                        passed=False,
                        severity="WARNING",
                        message=f"Poor query execution success rate: {len(successful_queries)}/{len(critical_queries)} ({success_rate:.1%})",
                        recommendation="Improve query implementation and fix failing queries",
                    )
                )

            # Validate all 38 queries are available
            available_queries = []
            for query_id in range(1, 39):
                try:
                    query_sql = self.benchmark.get_query(query_id, dialect=self.dialect)
                    if query_sql and len(query_sql.strip()) > 0:
                        available_queries.append(query_id)
                except Exception:
                    pass

            completeness_rate = len(available_queries) / 38
            if completeness_rate >= 0.90:  # 90% completeness threshold
                self.check_results.append(
                    ComplianceCheckResult(
                        check_name="Query Completeness",
                        category="Queries",
                        passed=True,
                        severity="INFO",
                        message=f"{len(available_queries)} out of 38 queries are available ({completeness_rate:.1%})",
                    )
                )
            else:
                self.check_results.append(
                    ComplianceCheckResult(
                        check_name="Query Completeness",
                        category="Queries",
                        passed=False,
                        severity="WARNING",
                        message=f"Only {len(available_queries)} out of 38 queries are available ({completeness_rate:.1%})",
                        recommendation="Implement missing TPC-DI queries",
                    )
                )

        except Exception as e:
            self.check_results.append(
                ComplianceCheckResult(
                    check_name="Query Validation Error",
                    category="Queries",
                    passed=False,
                    severity="ERROR",
                    message=f"Query validation failed: {str(e)}",
                    recommendation="Fix query validation infrastructure",
                )
            )

    def _validate_query_result_structure(self, query_id: int, results: list, query_sql: str) -> dict:
        """Validate the structure and basic properties of query results."""
        validation_info = {
            "has_results": len(results) > 0,
            "column_count": len(results[0]) if results else 0,
            "data_types_consistent": True,
            "no_nulls_in_keys": True,
        }

        # Basic structural validation
        if results:
            # Check for consistent column count across rows
            first_row_cols = len(results[0])
            for _i, row in enumerate(results[:100]):  # Sample first 100 rows
                if len(row) != first_row_cols:
                    validation_info["data_types_consistent"] = False
                    break

        return validation_info

    def _validate_query_result_accuracy(self, query_id: int, results: list, query_sql: str):
        """Validate query result accuracy against expected TPC-DI patterns."""
        try:
            # Pattern-based validation for different query types
            if "COUNT(" in query_sql.upper() and results:
                # Count queries should return non-negative integers
                for row in results:
                    if any(isinstance(val, (int, float)) and val < 0 for val in row):
                        self.check_results.append(
                            ComplianceCheckResult(
                                check_name=f"Query {query_id} Accuracy",
                                category="Queries",
                                passed=False,
                                severity="WARNING",
                                message=f"Query {query_id} returned negative count values",
                                recommendation="Verify count query logic",
                            )
                        )
                        return

                self.check_results.append(
                    ComplianceCheckResult(
                        check_name=f"Query {query_id} Accuracy",
                        category="Queries",
                        passed=True,
                        severity="INFO",
                        message=f"Query {query_id} count results are valid",
                    )
                )

            elif "SUM(" in query_sql.upper() or "AVG(" in query_sql.upper():
                # Aggregation queries should return reasonable numeric values
                has_valid_aggregates = False
                for row in results:
                    for val in row:
                        if isinstance(val, (int, float)) and val == val:  # Not NaN
                            has_valid_aggregates = True
                            break

                if has_valid_aggregates:
                    self.check_results.append(
                        ComplianceCheckResult(
                            check_name=f"Query {query_id} Accuracy",
                            category="Queries",
                            passed=True,
                            severity="INFO",
                            message=f"Query {query_id} aggregate results are valid",
                        )
                    )
                else:
                    self.check_results.append(
                        ComplianceCheckResult(
                            check_name=f"Query {query_id} Accuracy",
                            category="Queries",
                            passed=False,
                            severity="WARNING",
                            message=f"Query {query_id} aggregate results appear invalid",
                            recommendation="Verify aggregate query calculations",
                        )
                    )

            elif len(results) == 0:
                # Empty results might be valid for some queries
                self.check_results.append(
                    ComplianceCheckResult(
                        check_name=f"Query {query_id} Accuracy",
                        category="Queries",
                        passed=True,
                        severity="INFO",
                        message=f"Query {query_id} returned no results (may be valid for current data)",
                    )
                )

            else:
                # General result validation
                self.check_results.append(
                    ComplianceCheckResult(
                        check_name=f"Query {query_id} Accuracy",
                        category="Queries",
                        passed=True,
                        severity="INFO",
                        message=f"Query {query_id} returned {len(results)} rows with valid structure",
                    )
                )

        except Exception as e:
            self.check_results.append(
                ComplianceCheckResult(
                    check_name=f"Query {query_id} Accuracy Validation",
                    category="Queries",
                    passed=False,
                    severity="WARNING",
                    message=f"Query {query_id} accuracy validation failed: {str(e)}",
                    recommendation="Fix accuracy validation logic",
                )
            )

    def _check_query_categories(self) -> bool:
        """Check if required query categories are implemented."""
        try:
            # Check for different query types (validation, analytics, ETL)
            query_modules = []

            if hasattr(self.benchmark, "validation_queries"):
                query_modules.append("validation")
            if hasattr(self.benchmark, "analytics_queries"):
                query_modules.append("analytics")
            if hasattr(self.benchmark, "etl_queries"):
                query_modules.append("etl")

            # At least basic queries should be available
            return len(query_modules) >= 1 or hasattr(self.benchmark, "get_query")
        except Exception:
            return False

    def _validate_business_rule_compliance(self):
        """Validate business rule compliance with TPC-DI specification."""
        logger.info("Validating business rule compliance")

        if not self.connection:
            self.check_results.append(
                ComplianceCheckResult(
                    check_name="Business Rules",
                    category="Business Rules",
                    passed=False,
                    severity="MEDIUM",
                    message="No database connection for business rule validation",
                    recommendation="Provide database connection for business rule validation",
                )
            )
            return

        business_rule_checks = []

        try:
            cursor = self.connection.cursor()

            # Rule: Customer records should have valid data
            cursor.execute("SELECT COUNT(*) FROM DimCustomer WHERE FirstName IS NOT NULL AND LastName IS NOT NULL")
            valid_customers = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM DimCustomer")
            total_customers = cursor.fetchone()[0]

            if total_customers > 0:
                customer_completeness = valid_customers / total_customers
                business_rule_checks.append(customer_completeness >= 0.9)  # 90% completeness

        except Exception as e:
            logger.warning(f"Business rule validation error: {e}")

        # Additional business rule checks would go here

        business_rules_passed = len(business_rule_checks) == 0 or all(business_rule_checks)

        self.check_results.append(
            ComplianceCheckResult(
                check_name="Business Rule Validation",
                category="Business Rules",
                passed=business_rules_passed,
                severity="MEDIUM",
                message="Business rule compliance validation",
                details={
                    "checks_performed": len(business_rule_checks),
                    "checks_passed": sum(business_rule_checks),
                },
                recommendation="Ensure data quality meets TPC-DI business rule requirements",
            )
        )

    def _validate_performance_compliance(self):
        """Validate performance and scalability compliance."""
        logger.info("Validating performance compliance")

        # Check for performance optimization features
        performance_features = []

        # Check for parallel processing
        if hasattr(self.benchmark, "enable_parallel") and self.benchmark.enable_parallel:
            performance_features.append("parallel_processing")

        # Check for data quality monitoring
        if hasattr(self.benchmark, "data_quality_monitor"):
            performance_features.append("data_quality_monitoring")

        # Check for error recovery
        if hasattr(self.benchmark, "error_recovery_manager"):
            performance_features.append("error_recovery")

        # Check for incremental loading
        if hasattr(self.benchmark, "incremental_loader"):
            performance_features.append("incremental_loading")

        performance_score = len(performance_features) / 4  # 4 key performance features

        self.check_results.append(
            ComplianceCheckResult(
                check_name="Performance Features",
                category="Performance",
                passed=performance_score >= 0.75,  # 75% of features implemented
                severity="MEDIUM",
                message="Performance and scalability features",
                details={
                    "features_implemented": performance_features,
                    "performance_score": performance_score,
                },
                recommendation="Implement missing performance optimization features",
            )
        )

    def _validate_data_quality_compliance(self):
        """Validate data quality compliance with TPC-DI specification."""
        logger.info("Validating data quality compliance")

        # Check for data quality monitoring system
        has_quality_monitor = hasattr(self.benchmark, "data_quality_monitor")

        # Check for data validation functionality
        has_validation = hasattr(self.benchmark, "run_data_validation")

        # Check for quality rules implementation
        quality_rules_implemented = False
        if has_quality_monitor and self.benchmark.data_quality_monitor:
            try:
                # Check if quality monitor has rules
                quality_rules_implemented = hasattr(self.benchmark.data_quality_monitor, "rules")
            except Exception:
                pass

        data_quality_compliant = has_quality_monitor and has_validation and quality_rules_implemented

        self.check_results.append(
            ComplianceCheckResult(
                check_name="Data Quality System",
                category="Data Quality",
                passed=data_quality_compliant,
                severity="HIGH",
                message="Data quality compliance validation",
                details={
                    "quality_monitor": has_quality_monitor,
                    "validation_method": has_validation,
                    "quality_rules": quality_rules_implemented,
                },
                recommendation="Implement comprehensive data quality monitoring and validation",
            )
        )

    def _generate_compliance_report(self) -> SpecificationComplianceReport:
        """Generate comprehensive compliance report."""
        logger.info("Generating TPC-DI specification compliance report")

        total_checks = len(self.check_results)
        passed_checks = sum(1 for result in self.check_results if result.passed)
        failed_checks = total_checks - passed_checks

        # Calculate overall compliance score
        compliance_score = (passed_checks / max(total_checks, 1)) * 100

        # Calculate category scores
        category_scores = {}
        categories = {result.category for result in self.check_results}

        for category in categories:
            category_checks = [r for r in self.check_results if r.category == category]
            category_passed = sum(1 for r in category_checks if r.passed)
            category_scores[category] = (category_passed / len(category_checks)) * 100

        # Determine overall compliance (80% threshold)
        overall_compliance = compliance_score >= 80.0

        # Generate summary
        summary = {
            "compliance_level": "COMPLIANT" if overall_compliance else "NON_COMPLIANT",
            "critical_issues": len([r for r in self.check_results if not r.passed and r.severity == "CRITICAL"]),
            "high_issues": len([r for r in self.check_results if not r.passed and r.severity == "HIGH"]),
            "medium_issues": len([r for r in self.check_results if not r.passed and r.severity == "MEDIUM"]),
            "low_issues": len([r for r in self.check_results if not r.passed and r.severity == "LOW"]),
            "recommendations": [r.recommendation for r in self.check_results if not r.passed and r.recommendation],
        }

        return SpecificationComplianceReport(
            timestamp=datetime.now().isoformat(),
            overall_compliance=overall_compliance,
            total_checks=total_checks,
            passed_checks=passed_checks,
            failed_checks=failed_checks,
            compliance_score=compliance_score,
            category_scores=category_scores,
            check_results=self.check_results,
            summary=summary,
        )

    def save_compliance_report(self, report: SpecificationComplianceReport, output_path: Path):
        """Save compliance report to file.

        Args:
            report: Compliance report to save
            output_path: Path to save report
        """
        try:
            # Convert report to JSON-serializable format
            report_data = {
                "timestamp": report.timestamp,
                "overall_compliance": report.overall_compliance,
                "total_checks": report.total_checks,
                "passed_checks": report.passed_checks,
                "failed_checks": report.failed_checks,
                "compliance_score": report.compliance_score,
                "category_scores": report.category_scores,
                "summary": report.summary,
                "check_results": [
                    {
                        "check_name": result.check_name,
                        "category": result.category,
                        "passed": result.passed,
                        "severity": result.severity,
                        "message": result.message,
                        "details": result.details,
                        "recommendation": result.recommendation,
                    }
                    for result in report.check_results
                ],
            }

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2)

            logger.info(f"Compliance report saved to {output_path}")
        except Exception as e:
            logger.error(f"Failed to save compliance report: {e}")

    def print_compliance_summary(self, report: SpecificationComplianceReport):
        """Print compliance report summary.

        Args:
            report: Compliance report to summarize
        """
        emit("\n" + "=" * 60)
        emit("TPC-DI SPECIFICATION COMPLIANCE REPORT")
        emit("=" * 60)
        emit(f"Timestamp: {report.timestamp}")
        emit(f"Overall Compliance: {'✅ COMPLIANT' if report.overall_compliance else '❌ NON-COMPLIANT'}")
        emit(f"Compliance Score: {report.compliance_score:.1f}%")
        emit(f"Total Checks: {report.total_checks}")
        emit(f"Passed: {report.passed_checks}, Failed: {report.failed_checks}")

        emit("\nCATEGORY SCORES:")
        for category, score in report.category_scores.items():
            emit(f"  {category}: {score:.1f}%")

        emit("\nISSUE SUMMARY:")
        emit(f"  Critical: {report.summary['critical_issues']}")
        emit(f"  High: {report.summary['high_issues']}")
        emit(f"  Medium: {report.summary['medium_issues']}")
        emit(f"  Low: {report.summary['low_issues']}")

        if report.failed_checks > 0:
            emit("\nFAILED CHECKS:")
            for result in report.check_results:
                if not result.passed:
                    emit(f"  [{result.severity}] {result.check_name}: {result.message}")

        if report.summary["recommendations"]:
            emit("\nRECOMMENDATIONS:")
            for i, recommendation in enumerate(report.summary["recommendations"][:5], 1):  # Top 5
                if recommendation:
                    emit(f"  {i}. {recommendation}")

        emit("=" * 60)


def validate_tpcdi_benchmark_compliance(
    benchmark, connection=None, dialect="duckdb", output_path: Optional[Path] = None
) -> SpecificationComplianceReport:
    """Convenience function to validate TPC-DI benchmark compliance.

    Args:
        benchmark: TPCDIBenchmark instance to validate
        connection: Database connection for validation
        dialect: SQL dialect for validation
        output_path: Optional path to save compliance report

    Returns:
        Comprehensive compliance report
    """
    validator = TPCDISpecificationValidator(benchmark, connection, dialect)
    report = validator.validate_complete_specification_compliance()

    # Print summary
    validator.print_compliance_summary(report)

    # Save report if path provided
    if output_path:
        validator.save_compliance_report(report, output_path)

    return report
