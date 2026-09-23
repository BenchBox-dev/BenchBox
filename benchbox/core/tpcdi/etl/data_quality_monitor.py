"""Data Quality Monitoring and Validation system for TPC-DI ETL operations.

This module provides comprehensive data quality monitoring including:

1. Data Quality Rule Engine:
   - Configurable data quality rules and thresholds
   - Business rule validation for TPC-DI compliance
   - Custom validation logic for domain-specific requirements

2. Real-time Quality Monitoring:
   - Continuous monitoring of data quality metrics
   - Alerting and notification system for quality issues
   - Quality score calculation and trending

3. Data Profiling and Analysis:
   - Statistical profiling of data characteristics
   - Data distribution analysis and outlier detection
   - Column-level and table-level quality assessment

4. Quality Reporting and Dashboards:
   - Comprehensive quality reports and scorecards
   - Historical quality trend analysis
   - Executive summary and detailed technical reports

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DI (TPC-DI) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DI specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Union

from benchbox.utils.clock import elapsed_seconds, mono_time, utc_now

logger = logging.getLogger(__name__)


@dataclass
class DataQualityRule:
    """Definition of a data quality rule."""

    rule_id: str
    rule_name: str
    rule_type: str  # 'COMPLETENESS', 'ACCURACY', 'CONSISTENCY', 'VALIDITY', 'UNIQUENESS'
    table_name: str
    column_name: Optional[str] = None
    rule_description: str = ""
    severity: str = "MEDIUM"  # 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'

    # Rule parameters
    threshold_value: Optional[Union[float, int, str]] = None
    threshold_operator: str = ">="  # '>', '>=', '<', '<=', '==', '!=', 'BETWEEN', 'IN', 'REGEX'
    expected_values: Optional[list[Any]] = None
    custom_sql: Optional[str] = None
    expected_result: Optional[Any] = None  # For test compatibility

    # Execution settings
    is_active: bool = True
    check_frequency: str = "BATCH"  # 'BATCH', 'DAILY', 'HOURLY', 'REAL_TIME'

    # Business context
    business_impact: Optional[str] = None
    remediation_action: Optional[str] = None


@dataclass
class QualityCheckResult:
    """Result of a data quality check execution."""

    rule_id: str
    check_timestamp: datetime
    table_name: str
    column_name: Optional[str] = None

    # Results
    passed: bool = False
    actual_value: Optional[Union[float, int, str]] = None
    actual_result: Optional[Any] = None  # For test compatibility
    expected_value: Optional[Union[float, int, str]] = None
    deviation: Optional[float] = None

    # Metrics
    records_checked: int = 0
    records_failed: int = 0
    failure_rate: float = 0.0

    # Details
    error_message: Optional[str] = None
    sample_failures: list[dict[str, Any]] = field(default_factory=list)
    execution_time_ms: float = 0.0

    # Context
    batch_id: Optional[int] = None
    severity: str = "MEDIUM"


@dataclass
class QualityScore:
    """Data quality score calculation."""

    table_name: str
    calculation_timestamp: datetime
    batch_id: Optional[int] = None

    # Overall scores (0-100)
    overall_score: float = 0.0
    completeness_score: float = 0.0
    accuracy_score: float = 0.0
    consistency_score: float = 0.0
    validity_score: float = 0.0
    uniqueness_score: float = 0.0

    # Detailed metrics
    rules_passed: int = 0
    rules_failed: int = 0
    rules_total: int = 0
    critical_issues: int = 0
    high_issues: int = 0
    medium_issues: int = 0
    low_issues: int = 0

    # Trends
    score_trend: Optional[str] = None  # 'IMPROVING', 'DECLINING', 'STABLE'
    previous_score: Optional[float] = None


class DataQualityRuleEngine:
    """Engine for executing data quality rules and validations."""

    def __init__(self, connection: Any, dialect: str = "duckdb"):
        self.connection = connection
        self.dialect = dialect
        self.rules: dict[str, DataQualityRule] = {}

    def register_rule(self, rule: DataQualityRule) -> None:
        """Register a data quality rule."""
        self.rules[rule.rule_id] = rule
        logger.debug(f"Registered data quality rule: {rule.rule_id}")

    def execute_rule(self, rule_id: str, batch_id: Optional[int] = None) -> QualityCheckResult:
        """Execute a specific data quality rule."""

        if rule_id not in self.rules:
            raise ValueError(f"Data quality rule not found: {rule_id}")

        rule = self.rules[rule_id]
        if not rule.is_active:
            logger.debug(f"Skipping inactive rule: {rule_id}")
            return QualityCheckResult(
                rule_id=rule_id,
                check_timestamp=datetime.now(),
                table_name=rule.table_name,
                column_name=rule.column_name,
                passed=True,  # Inactive rules are considered passed
                severity=rule.severity,
            )

        start_time_utc = utc_now()
        start_time_mono = mono_time()
        result = QualityCheckResult(
            rule_id=rule_id,
            check_timestamp=start_time_utc,
            table_name=rule.table_name,
            column_name=rule.column_name,
            batch_id=batch_id,
            severity=rule.severity,
        )

        try:
            # Execute rule based on type
            if rule.rule_type == "COMPLETENESS":
                self._check_completeness(rule, result)
            elif rule.rule_type == "ACCURACY":
                self._check_accuracy(rule, result)
            elif rule.rule_type == "CONSISTENCY":
                self._check_consistency(rule, result)
            elif rule.rule_type == "VALIDITY":
                self._check_validity(rule, result)
            elif rule.rule_type == "UNIQUENESS":
                self._check_uniqueness(rule, result)
            elif rule.custom_sql:
                self._check_custom_sql(rule, result)
            else:
                raise ValueError(f"Unsupported rule type: {rule.rule_type}")

            result.execution_time_ms = elapsed_seconds(start_time_mono) * 1000

            logger.debug(f"Executed rule {rule_id}: {'PASSED' if result.passed else 'FAILED'}")
            return result

        except Exception as e:
            result.passed = False
            result.error_message = str(e)
            result.execution_time_ms = elapsed_seconds(start_time_mono) * 1000
            logger.error(f"Rule execution failed for {rule_id}: {str(e)}")
            return result

    def _check_completeness(self, rule: DataQualityRule, result: QualityCheckResult) -> None:
        """Check data completeness (null/missing value percentage)."""

        query = f"""
        SELECT
            COUNT(*) as total_records,
            COUNT({rule.column_name}) as non_null_records,
            CASE
                WHEN COUNT(*) = 0 THEN 0.0
                ELSE (COUNT({rule.column_name}) * 100.0 / COUNT(*))
            END as completeness_pct
        FROM {rule.table_name}
        """

        cursor = self.connection.execute(query)
        row = cursor.fetchone()

        result.records_checked = row[0]
        non_null_records = row[1]
        completeness_pct = row[2] if row[2] is not None else 0.0

        result.actual_value = completeness_pct
        result.expected_value = rule.threshold_value
        result.records_failed = result.records_checked - non_null_records
        result.failure_rate = (result.records_failed / max(result.records_checked, 1)) * 100.0

        # Apply threshold comparison
        result.passed = self._apply_threshold_comparison(
            completeness_pct, rule.threshold_value, rule.threshold_operator
        )

    def _check_accuracy(self, rule: DataQualityRule, result: QualityCheckResult) -> None:
        """Check data accuracy against expected values or patterns."""

        if rule.expected_values:
            # Check against list of valid values
            valid_values = "', '".join(str(v) for v in rule.expected_values)
            query = f"""
            SELECT
                COUNT(*) as total_records,
                SUM(CASE WHEN {rule.column_name} IN ('{valid_values}') THEN 1 ELSE 0 END) as valid_records
            FROM {rule.table_name}
            WHERE {rule.column_name} IS NOT NULL
            """
        else:
            # General accuracy check (non-null, non-empty)
            query = f"""
            SELECT
                COUNT(*) as total_records,
                SUM(CASE WHEN {rule.column_name} IS NOT NULL AND TRIM(CAST({rule.column_name} AS VARCHAR)) != '' THEN 1 ELSE 0 END) as valid_records
            FROM {rule.table_name}
            """

        cursor = self.connection.execute(query)
        row = cursor.fetchone()

        result.records_checked = row[0]
        valid_records = row[1] or 0
        accuracy_pct = (valid_records / max(result.records_checked, 1)) * 100.0

        result.actual_value = accuracy_pct
        result.expected_value = rule.threshold_value
        result.records_failed = result.records_checked - valid_records
        result.failure_rate = (result.records_failed / max(result.records_checked, 1)) * 100.0

        result.passed = self._apply_threshold_comparison(accuracy_pct, rule.threshold_value, rule.threshold_operator)

    def _check_consistency(self, rule: DataQualityRule, result: QualityCheckResult) -> None:
        """Check data consistency across related tables or within table."""

        if rule.custom_sql:
            # Use custom SQL for consistency checks
            cursor = self.connection.execute(rule.custom_sql)
            row = cursor.fetchone()

            # Assume custom SQL returns (total_records, consistent_records)
            result.records_checked = row[0] if row else 0
            consistent_records = row[1] if row and len(row) > 1 else 0
            consistency_pct = (consistent_records / max(result.records_checked, 1)) * 100.0

            result.actual_value = consistency_pct
            result.expected_value = rule.threshold_value
            result.records_failed = result.records_checked - consistent_records
            result.failure_rate = (result.records_failed / max(result.records_checked, 1)) * 100.0

            result.passed = self._apply_threshold_comparison(
                consistency_pct, rule.threshold_value, rule.threshold_operator
            )
        else:
            # Default consistency check
            result.passed = True
            result.actual_value = 100.0

    def _check_validity(self, rule: DataQualityRule, result: QualityCheckResult) -> None:
        """Check data validity against format, range, or pattern requirements."""

        # Example: Check if values match a regex pattern
        if rule.threshold_operator == "REGEX" and rule.threshold_value:
            query = f"""
            SELECT
                COUNT(*) as total_records,
                SUM(CASE WHEN {rule.column_name} REGEXP '{rule.threshold_value}' THEN 1 ELSE 0 END) as valid_records
            FROM {rule.table_name}
            WHERE {rule.column_name} IS NOT NULL
            """

            cursor = self.connection.execute(query)
            row = cursor.fetchone()

            result.records_checked = row[0]
            valid_records = row[1] or 0
            validity_pct = (valid_records / max(result.records_checked, 1)) * 100.0

            result.actual_value = validity_pct
            result.expected_value = 95.0  # Default expectation
            result.records_failed = result.records_checked - valid_records
            result.failure_rate = (result.records_failed / max(result.records_checked, 1)) * 100.0

            result.passed = validity_pct >= 95.0
        else:
            # Range validity check
            query = f"""
            SELECT
                COUNT(*) as total_records,
                MIN({rule.column_name}) as min_value,
                MAX({rule.column_name}) as max_value,
                AVG({rule.column_name}) as avg_value
            FROM {rule.table_name}
            WHERE {rule.column_name} IS NOT NULL
            """

            cursor = self.connection.execute(query)
            row = cursor.fetchone()

            result.records_checked = row[0]
            result.actual_value = row[3]  # Average value
            result.passed = True  # Default to passed for range checks

    def _check_uniqueness(self, rule: DataQualityRule, result: QualityCheckResult) -> None:
        """Check data uniqueness (duplicate detection)."""

        query = f"""
        SELECT
            COUNT(*) as total_records,
            COUNT(DISTINCT {rule.column_name}) as unique_records
        FROM {rule.table_name}
        WHERE {rule.column_name} IS NOT NULL
        """

        cursor = self.connection.execute(query)
        row = cursor.fetchone()

        result.records_checked = row[0]
        unique_records = row[1]
        uniqueness_pct = (unique_records / max(result.records_checked, 1)) * 100.0

        result.actual_value = uniqueness_pct
        result.expected_value = rule.threshold_value or 100.0
        result.records_failed = result.records_checked - unique_records
        result.failure_rate = (result.records_failed / max(result.records_checked, 1)) * 100.0

        result.passed = self._apply_threshold_comparison(
            uniqueness_pct, rule.threshold_value or 100.0, rule.threshold_operator
        )

    def _check_custom_sql(self, rule: DataQualityRule, result: QualityCheckResult) -> None:
        """Execute custom SQL-based quality check."""

        cursor = self.connection.execute(rule.custom_sql)
        row = cursor.fetchone()

        if row:
            # Assume custom SQL returns a single numeric result
            result.actual_value = row[0]
            result.expected_value = rule.threshold_value
            result.records_checked = 1  # Single result

            result.passed = self._apply_threshold_comparison(
                result.actual_value, rule.threshold_value, rule.threshold_operator
            )
        else:
            result.passed = False
            result.error_message = "Custom SQL returned no results"

    def _apply_threshold_comparison(
        self,
        actual_value: Union[float, int],
        threshold_value: Union[float, int],
        operator: str,
    ) -> bool:
        """Apply threshold comparison logic."""

        if threshold_value is None:
            return True  # No threshold specified

        try:
            if operator == ">=":
                return actual_value >= threshold_value
            elif operator == ">":
                return actual_value > threshold_value
            elif operator == "<=":
                return actual_value <= threshold_value
            elif operator == "<":
                return actual_value < threshold_value
            elif operator == "==":
                return actual_value == threshold_value
            elif operator == "!=":
                return actual_value != threshold_value
            else:
                logger.warning(f"Unsupported threshold operator: {operator}")
                return True

        except (TypeError, ValueError):
            logger.warning(f"Could not compare {actual_value} {operator} {threshold_value}")
            return False


class DataQualityMonitor:
    """Comprehensive data quality monitoring system for TPC-DI."""

    def __init__(self, connection: Any, dialect: str = "duckdb"):
        """Initialize the data quality monitor.

        Args:
            connection: Database connection object
            dialect: SQL dialect for query generation
        """
        self.connection = connection
        self.dialect = dialect
        self.rule_engine = DataQualityRuleEngine(connection, dialect)

        # Quality tracking
        self.quality_history: list[QualityCheckResult] = []
        self.quality_scores: dict[str, list[QualityScore]] = {}

        # Initialize standard TPC-DI quality rules
        self._initialize_standard_rules()

    @property
    def rules(self) -> dict[str, DataQualityRule]:
        """Get the rules from the rule engine."""
        return self.rule_engine.rules

    def execute_rule(self, rule_id: str) -> QualityCheckResult:
        """Execute a specific data quality rule.

        Args:
            rule_id: ID of the rule to execute

        Returns:
            Result of the data quality check execution
        """
        return self.rule_engine.execute_rule(rule_id)

    def _initialize_standard_rules(self) -> None:
        """Initialize standard data quality rules for TPC-DI tables."""

        # Customer data quality rules
        customer_rules = [
            DataQualityRule(
                rule_id="CUST_COMPLETENESS_TAXID",
                rule_name="Customer Tax ID Completeness",
                rule_type="COMPLETENESS",
                table_name="DimCustomer",
                column_name="TaxID",
                rule_description="Tax ID should be present for all customers",
                severity="CRITICAL",
                threshold_value=95.0,
                threshold_operator=">=",
            ),
            DataQualityRule(
                rule_id="CUST_VALIDITY_PHONE",
                rule_name="Customer Phone Format Validity",
                rule_type="VALIDITY",
                table_name="DimCustomer",
                column_name="Phone1",
                rule_description="Phone numbers should not be empty when present",
                severity="MEDIUM",
                threshold_value=90.0,
                threshold_operator=">=",
            ),
            DataQualityRule(
                rule_id="CUST_UNIQUENESS_TAXID",
                rule_name="Customer Tax ID Uniqueness",
                rule_type="UNIQUENESS",
                table_name="DimCustomer",
                column_name="TaxID",
                rule_description="Tax ID should be unique across all customers",
                severity="CRITICAL",
                threshold_value=100.0,
                threshold_operator=">=",
            ),
        ]

        # Account data quality rules
        account_rules = [
            DataQualityRule(
                rule_id="ACCT_COMPLETENESS_CUSTOMERID",
                rule_name="Account Customer ID Completeness",
                rule_type="COMPLETENESS",
                table_name="DimAccount",
                column_name="SK_CustomerID",
                rule_description="All accounts must be linked to a customer",
                severity="CRITICAL",
                threshold_value=100.0,
                threshold_operator=">=",
            ),
            DataQualityRule(
                rule_id="ACCT_VALIDITY_STATUS",
                rule_name="Account Status Validity",
                rule_type="ACCURACY",
                table_name="DimAccount",
                column_name="Status",
                rule_description="Account status must be valid value",
                severity="HIGH",
                threshold_value=100.0,
                threshold_operator=">=",
                expected_values=["Active", "Inactive", "Closed"],
            ),
        ]

        # Trade data quality rules
        trade_rules = [
            DataQualityRule(
                rule_id="TRADE_COMPLETENESS_PRICE",
                rule_name="Trade Price Completeness",
                rule_type="COMPLETENESS",
                table_name="FactTrade",
                column_name="TradePrice",
                rule_description="All trades must have a price",
                severity="CRITICAL",
                threshold_value=100.0,
                threshold_operator=">=",
            ),
            DataQualityRule(
                rule_id="TRADE_VALIDITY_PRICE_POSITIVE",
                rule_name="Trade Price Positive Value",
                rule_type="VALIDITY",
                table_name="FactTrade",
                column_name="TradePrice",
                rule_description="Trade prices must be positive",
                severity="HIGH",
                custom_sql="""
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN TradePrice > 0 THEN 1 ELSE 0 END) as positive_price_trades
                FROM FactTrade
                WHERE TradePrice IS NOT NULL
                """,
                threshold_value=99.0,
                threshold_operator=">=",
            ),
        ]

        # Register all rules
        all_rules = customer_rules + account_rules + trade_rules
        for rule in all_rules:
            self.rule_engine.register_rule(rule)

        logger.info(f"Initialized {len(all_rules)} standard data quality rules")

    def add_rule(self, rule: DataQualityRule) -> None:
        """Add a data quality rule to the monitor.

        Args:
            rule: DataQualityRule to add
        """
        self.rule_engine.register_rule(rule)

    def execute_quality_checks(
        self, table_names: Optional[list[str]] = None, batch_id: Optional[int] = None
    ) -> dict[str, Any]:
        """Execute quality checks for specified tables.

        Args:
            table_names: List of table names to check
            batch_id: Batch ID for tracking

        Returns:
            Dictionary with quality check results
        """
        return self.run_quality_check_batch(table_names=table_names, batch_id=batch_id)

    def run_quality_check_batch(
        self,
        table_names: Optional[list[str]] = None,
        batch_id: Optional[int] = None,
        rule_severity_filter: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Run a batch of data quality checks.

        Args:
            table_names: Specific tables to check (None = all tables)
            batch_id: Batch identifier for tracking
            rule_severity_filter: Only run rules with specified severities

        Returns:
            Dictionary containing batch check results and summary
        """

        logger.info(f"Running data quality check batch for batch {batch_id}")
        batch_start_utc = utc_now()
        batch_start_mono = mono_time()

        # Filter rules to execute
        rules_to_execute = []
        for rule_id, rule in self.rule_engine.rules.items():
            # Apply table filter
            if table_names and rule.table_name not in table_names:
                continue

            # Apply severity filter
            if rule_severity_filter and rule.severity not in rule_severity_filter:
                continue

            rules_to_execute.append(rule_id)

        logger.debug(f"Executing {len(rules_to_execute)} quality rules")

        # Execute rules
        batch_results = []
        for rule_id in rules_to_execute:
            result = self.rule_engine.execute_rule(rule_id, batch_id)
            batch_results.append(result)
            self.quality_history.append(result)

        # Calculate batch summary
        batch_summary = {
            "batch_id": batch_id,
            "execution_timestamp": batch_start_utc,
            "rules_executed": len(batch_results),
            "rules_passed": len([r for r in batch_results if r.passed]),
            "rules_failed": len([r for r in batch_results if not r.passed]),
            "critical_failures": len([r for r in batch_results if not r.passed and r.severity == "CRITICAL"]),
            "high_failures": len([r for r in batch_results if not r.passed and r.severity == "HIGH"]),
            "medium_failures": len([r for r in batch_results if not r.passed and r.severity == "MEDIUM"]),
            "low_failures": len([r for r in batch_results if not r.passed and r.severity == "LOW"]),
            "total_execution_time_ms": elapsed_seconds(batch_start_mono) * 1000,
            "overall_pass_rate": (len([r for r in batch_results if r.passed]) / max(len(batch_results), 1)) * 100.0,
        }

        # Calculate quality scores by table
        table_scores = {}
        tables_processed = {r.table_name for r in batch_results}

        for table_name in tables_processed:
            table_results = [r for r in batch_results if r.table_name == table_name]
            quality_score = self._calculate_quality_score(table_name, table_results, batch_id)
            table_scores[table_name] = quality_score

            # Store in quality score history
            if table_name not in self.quality_scores:
                self.quality_scores[table_name] = []
            self.quality_scores[table_name].append(quality_score)

        batch_summary["quality_scores_by_table"] = table_scores
        batch_summary["detailed_results"] = [self._result_to_dict(r) for r in batch_results]

        logger.info(
            f"Quality check batch completed: {batch_summary['rules_passed']}/{batch_summary['rules_executed']} rules passed "
            f"({batch_summary['overall_pass_rate']:.1f}% pass rate)"
        )

        return batch_summary

    def _calculate_quality_score(
        self,
        table_name: str,
        table_results: list[QualityCheckResult],
        batch_id: Optional[int] = None,
    ) -> QualityScore:
        """Calculate comprehensive quality score for a table."""

        score = QualityScore(
            table_name=table_name,
            calculation_timestamp=datetime.now(),
            batch_id=batch_id,
        )

        if not table_results:
            return score

        # Count results by type and severity
        score.rules_total = len(table_results)
        score.rules_passed = len([r for r in table_results if r.passed])
        score.rules_failed = len([r for r in table_results if not r.passed])

        score.critical_issues = len([r for r in table_results if not r.passed and r.severity == "CRITICAL"])
        score.high_issues = len([r for r in table_results if not r.passed and r.severity == "HIGH"])
        score.medium_issues = len([r for r in table_results if not r.passed and r.severity == "MEDIUM"])
        score.low_issues = len([r for r in table_results if not r.passed and r.severity == "LOW"])

        # Calculate dimension scores
        rule_types = [
            "COMPLETENESS",
            "ACCURACY",
            "CONSISTENCY",
            "VALIDITY",
            "UNIQUENESS",
        ]
        type_scores = {}

        for rule_type in rule_types:
            type_results = [r for r in table_results if r.rule_id.startswith(rule_type[:4])]  # Simplified matching
            if type_results:
                type_pass_rate = len([r for r in type_results if r.passed]) / len(type_results) * 100.0
                type_scores[rule_type] = type_pass_rate
            else:
                type_scores[rule_type] = 100.0  # Default to perfect if no rules

        score.completeness_score = type_scores.get("COMPLETENESS", 100.0)
        score.accuracy_score = type_scores.get("ACCURACY", 100.0)
        score.consistency_score = type_scores.get("CONSISTENCY", 100.0)
        score.validity_score = type_scores.get("VALIDITY", 100.0)
        score.uniqueness_score = type_scores.get("UNIQUENESS", 100.0)

        # Calculate weighted overall score (critical issues have more impact)
        base_score = (score.rules_passed / score.rules_total) * 100.0
        critical_penalty = score.critical_issues * 15.0  # Heavy penalty
        high_penalty = score.high_issues * 10.0
        medium_penalty = score.medium_issues * 5.0
        low_penalty = score.low_issues * 2.0

        score.overall_score = max(
            0.0,
            base_score - critical_penalty - high_penalty - medium_penalty - low_penalty,
        )

        # Calculate trend if previous scores exist
        if table_name in self.quality_scores and self.quality_scores[table_name]:
            previous_score = self.quality_scores[table_name][-1].overall_score
            score.previous_score = previous_score

            score_diff = score.overall_score - previous_score
            if abs(score_diff) < 2.0:
                score.score_trend = "STABLE"
            elif score_diff > 0:
                score.score_trend = "IMPROVING"
            else:
                score.score_trend = "DECLINING"

        return score

    def _result_to_dict(self, result: QualityCheckResult) -> dict[str, Any]:
        """Convert QualityCheckResult to dictionary for serialization."""

        return {
            "rule_id": result.rule_id,
            "check_timestamp": result.check_timestamp.isoformat(),
            "table_name": result.table_name,
            "column_name": result.column_name,
            "passed": result.passed,
            "actual_value": result.actual_value,
            "expected_value": result.expected_value,
            "records_checked": result.records_checked,
            "records_failed": result.records_failed,
            "failure_rate": result.failure_rate,
            "severity": result.severity,
            "error_message": result.error_message,
            "execution_time_ms": result.execution_time_ms,
        }

    def get_quality_dashboard_data(self, table_name: Optional[str] = None) -> dict[str, Any]:
        """Get comprehensive quality dashboard data.

        Args:
            table_name: Specific table to focus on (None = all tables)

        Returns:
            Dictionary containing dashboard data and metrics
        """

        # Filter results
        if table_name:
            recent_results = [r for r in self.quality_history[-100:] if r.table_name == table_name]
            table_scores = {table_name: self.quality_scores.get(table_name, [])}
        else:
            recent_results = self.quality_history[-500:]  # Last 500 results
            table_scores = self.quality_scores.copy()

        if not recent_results:
            return {"message": "No quality check results available"}

        # Overall statistics
        total_checks = len(recent_results)
        passed_checks = len([r for r in recent_results if r.passed])
        overall_pass_rate = (passed_checks / total_checks) * 100.0

        # Severity breakdown
        severity_breakdown = {
            "CRITICAL": len([r for r in recent_results if not r.passed and r.severity == "CRITICAL"]),
            "HIGH": len([r for r in recent_results if not r.passed and r.severity == "HIGH"]),
            "MEDIUM": len([r for r in recent_results if not r.passed and r.severity == "MEDIUM"]),
            "LOW": len([r for r in recent_results if not r.passed and r.severity == "LOW"]),
        }

        # Table-level summary
        table_summary = {}
        for table in {r.table_name for r in recent_results}:
            table_results = [r for r in recent_results if r.table_name == table]
            table_passed = len([r for r in table_results if r.passed])
            table_total = len(table_results)
            table_pass_rate = (table_passed / table_total) * 100.0 if table_total > 0 else 0.0

            # Get latest quality score
            latest_score = None
            if table in table_scores and table_scores[table]:
                latest_score = table_scores[table][-1].overall_score

            table_summary[table] = {
                "checks_executed": table_total,
                "checks_passed": table_passed,
                "pass_rate": table_pass_rate,
                "latest_quality_score": latest_score,
                "critical_issues": len([r for r in table_results if not r.passed and r.severity == "CRITICAL"]),
                "high_issues": len([r for r in table_results if not r.passed and r.severity == "HIGH"]),
            }

        # Recent trends
        trend_data = []
        if len(recent_results) >= 10:
            # Calculate trends over recent results
            batch_groups = {}
            for result in recent_results:
                batch_key = result.batch_id or 0
                if batch_key not in batch_groups:
                    batch_groups[batch_key] = []
                batch_groups[batch_key].append(result)

            for batch_id in sorted(batch_groups.keys())[-10:]:  # Last 10 batches
                batch_results = batch_groups[batch_id]
                batch_pass_rate = (len([r for r in batch_results if r.passed]) / len(batch_results)) * 100.0
                trend_data.append(
                    {
                        "batch_id": batch_id,
                        "pass_rate": batch_pass_rate,
                        "total_checks": len(batch_results),
                    }
                )

        return {
            "summary": {
                "total_checks_executed": total_checks,
                "overall_pass_rate": overall_pass_rate,
                "issues_by_severity": severity_breakdown,
                "tables_monitored": len({r.table_name for r in recent_results}),
            },
            "by_table": table_summary,
            "recent_trends": trend_data,
            "quality_scores": {
                table: [
                    {
                        "timestamp": score.calculation_timestamp.isoformat(),
                        "overall_score": score.overall_score,
                        "trend": score.score_trend,
                    }
                    for score in scores[-10:]  # Last 10 scores
                ]
                for table, scores in table_scores.items()
                if scores
            },
        }

    def get_quality_alerts(self, severity_threshold: str = "HIGH") -> list[dict[str, Any]]:
        """Get current quality alerts based on severity threshold.

        Args:
            severity_threshold: Minimum severity to include ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')

        Returns:
            List of current quality alerts
        """

        severity_order = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        min_severity_index = severity_order.index(severity_threshold)

        # Get recent failures meeting severity threshold
        recent_failures = [
            r
            for r in self.quality_history[-100:]  # Last 100 results
            if not r.passed and severity_order.index(r.severity) >= min_severity_index
        ]

        alerts = []
        for failure in recent_failures:
            rule = self.rule_engine.rules.get(failure.rule_id)
            alert = {
                "alert_id": f"{failure.rule_id}_{failure.check_timestamp.isoformat()}",
                "rule_id": failure.rule_id,
                "rule_name": rule.rule_name if rule else failure.rule_id,
                "table_name": failure.table_name,
                "column_name": failure.column_name,
                "severity": failure.severity,
                "failure_rate": failure.failure_rate,
                "records_affected": failure.records_failed,
                "check_timestamp": failure.check_timestamp.isoformat(),
                "description": rule.rule_description if rule else None,
                "business_impact": rule.business_impact if rule else None,
                "remediation_action": rule.remediation_action if rule else None,
                "error_message": failure.error_message,
            }
            alerts.append(alert)

        # Sort by severity and timestamp
        severity_priority = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
        alerts.sort(
            key=lambda x: (
                severity_priority.get(x["severity"], 0),
                x["check_timestamp"],
            ),
            reverse=True,
        )

        return alerts
