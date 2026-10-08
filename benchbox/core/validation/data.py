# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from benchbox.utils.clock import elapsed_seconds, mono_time

logger = logging.getLogger(__name__)


class ValidationStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


@dataclass
class RowCountDiscrepancy:
    table_name: str
    expected_count: int
    actual_count: int
    difference: int
    percentage_diff: float
    tolerance_exceeded: bool
    status: ValidationStatus = ValidationStatus.FAILED

    @property
    def is_significant(self) -> bool:
        return self.tolerance_exceeded

    def __str__(self) -> str:
        return (
            f"Table '{self.table_name}': expected {self.expected_count:,}, "
            f"actual {self.actual_count:,} ({self.percentage_diff:+.2f}%)"
        )


@dataclass
class ValidationResult:
    is_valid: bool = True
    total_tables: int = 0
    passed_tables: int = 0
    failed_tables: int = 0
    warning_tables: int = 0
    skipped_tables: int = 0

    discrepancies: list[RowCountDiscrepancy] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    execution_time: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    def add_discrepancy(self, discrepancy: RowCountDiscrepancy) -> None:
        self.discrepancies.append(discrepancy)

        if discrepancy.status == ValidationStatus.FAILED:
            self.failed_tables += 1
            self.is_valid = False
        elif discrepancy.status == ValidationStatus.WARNING:
            self.warning_tables += 1
        elif discrepancy.status == ValidationStatus.PASSED:
            self.passed_tables += 1

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.is_valid = False

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def get_significant_discrepancies(self) -> list[RowCountDiscrepancy]:
        return [d for d in self.discrepancies if d.is_significant]

    def get_summary(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "total_tables": self.total_tables,
            "passed_tables": self.passed_tables,
            "failed_tables": self.failed_tables,
            "warning_tables": self.warning_tables,
            "skipped_tables": self.skipped_tables,
            "total_discrepancies": len(self.discrepancies),
            "significant_discrepancies": len(self.get_significant_discrepancies()),
            "execution_time_seconds": self.execution_time,
        }

    def __str__(self) -> str:
        summary = self.get_summary()
        return (
            f"Validation {'PASSED' if self.is_valid else 'FAILED'}: "
            f"{summary['passed_tables']}/{summary['total_tables']} tables passed"
        )


class DataValidator:
    def __init__(
        self,
        platform_adapter,
        tolerance_percent: float = 0.1,
        absolute_tolerance: int = 100,
    ):
        self.platform_adapter = platform_adapter
        self.tolerance_percent = tolerance_percent
        self.absolute_tolerance = absolute_tolerance
        self.logger = logging.getLogger(f"{self.__class__.__name__}")

        self.large_table_threshold = 10_000_000
        self.use_approximate_for_large = True

    def validate_row_counts(self, expected_counts: dict[str, int]) -> ValidationResult:
        start_time = mono_time()
        result = ValidationResult()
        result.total_tables = len(expected_counts)

        self.logger.info(f"Starting row count validation for {result.total_tables} tables")

        try:
            temp_conn = self.platform_adapter.create_connection(**self.platform_adapter.platform_config)
            try:
                actual_counts = self.get_actual_row_counts(temp_conn, list(expected_counts.keys()))
            finally:
                self.platform_adapter.close_connection(temp_conn)
        except Exception as e:
            result.add_error(f"Failed to retrieve actual row counts: {e}")
            return result

        for table_name, expected_count in expected_counts.items():
            if table_name not in actual_counts:
                result.add_error(f"Table '{table_name}' not found in database")
                result.skipped_tables += 1
                continue

            actual_count = actual_counts[table_name]
            discrepancy = self._create_discrepancy(table_name, expected_count, actual_count)
            result.add_discrepancy(discrepancy)

        result.execution_time = elapsed_seconds(start_time)

        self._log_validation_results(result)
        return result

    def get_actual_row_counts(self, connection: Any, table_names: list[str]) -> dict[str, int]:
        row_counts = {}

        for table_name in table_names:
            try:
                count = self._get_table_row_count(connection, table_name)
                row_counts[table_name] = count
                self.logger.debug(f"Table '{table_name}': {count:,} rows")

            except Exception as e:
                self.logger.error(f"Failed to count rows for table '{table_name}': {e}")
                raise

        return row_counts

    def _get_table_row_count(self, connection: Any, table_name: str) -> int:
        platform = self.platform_adapter.platform_name.lower()

        if self.use_approximate_for_large:
            approx_count = self._try_approximate_count(connection, table_name, platform)
            if approx_count is not None and approx_count > self.large_table_threshold:
                self.logger.info(f"Using approximate count for large table '{table_name}': {approx_count:,} rows")
                return approx_count

        count_query = self._get_count_query(table_name, platform)
        cursor = connection.cursor()
        cursor.execute(count_query)
        result = cursor.fetchone()

        if result is None:
            raise ValueError(f"Count query returned no results for table '{table_name}'")

        return int(result[0])

    def _try_approximate_count(self, connection: Any, table_name: str, platform: str) -> Optional[int]:
        try:
            cursor = connection.cursor()

            if platform == "postgresql":
                query = f"""
                SELECT n_tup_ins - n_tup_del as approx_count
                FROM pg_stat_user_tables
                WHERE relname = '{table_name}'
                """
                cursor.execute(query)
                result = cursor.fetchone()
                return int(result[0]) if result and result[0] is not None else None

            elif platform == "mysql":
                query = f"""
                SELECT table_rows
                FROM information_schema.tables
                WHERE table_name = '{table_name}'
                AND table_schema = DATABASE()
                """
                cursor.execute(query)
                result = cursor.fetchone()
                return int(result[0]) if result and result[0] is not None else None

            elif platform == "snowflake":
                query = f"""
                SELECT row_count
                FROM information_schema.tables
                WHERE table_name = UPPER('{table_name}')
                """
                cursor.execute(query)
                result = cursor.fetchone()
                return int(result[0]) if result and result[0] is not None else None

            elif platform == "bigquery":
                dataset_id = self.platform_adapter.platform_config.get("dataset_id", "benchbox")
                query = f"""
                SELECT row_count
                FROM `{dataset_id}.__TABLES__`
                WHERE table_id = '{table_name}'
                """
                cursor.execute(query)
                result = cursor.fetchone()
                return int(result[0]) if result and result[0] is not None else None

            elif platform == "redshift":
                query = f"""
                SELECT SUM(rows)
                FROM stv_tbl_perm
                WHERE name = '{table_name}'
                """
                cursor.execute(query)
                result = cursor.fetchone()
                return int(result[0]) if result and result[0] is not None else None

            elif platform in {"clickhouse", "clickhouse-local", "clickhouse-server"}:
                query = f"""
                SELECT SUM(rows)
                FROM system.parts
                WHERE table = '{table_name}' AND active = 1
                """
                cursor.execute(query)
                result = cursor.fetchone()
                return int(result[0]) if result and result[0] is not None else None

            return None

        except Exception as e:
            self.logger.debug(f"Approximate count failed for '{table_name}': {e}")
            return None

    def _get_count_query(self, table_name: str, platform: str) -> str:
        quoted_table = self._quote_identifier(table_name, platform)

        if platform in {"clickhouse", "clickhouse-local", "clickhouse-server"} or platform == "duckdb":
            return f"SELECT COUNT(*) FROM {quoted_table}"
        else:
            return f"SELECT COUNT(*) FROM {quoted_table}"

    def _quote_identifier(self, identifier: str, platform: str) -> str:
        if platform == "bigquery" or platform in ["mysql"]:
            return f"`{identifier}`"
        elif platform in ["postgresql", "redshift", "snowflake"]:
            return f'"{identifier}"'
        elif platform in {"clickhouse", "clickhouse-local", "clickhouse-server"}:
            return identifier
        else:
            return identifier

    def _create_discrepancy(self, table_name: str, expected_count: int, actual_count: int) -> RowCountDiscrepancy:
        difference = actual_count - expected_count

        if expected_count > 0:
            percentage_diff = (difference / expected_count) * 100
        else:
            percentage_diff = float("inf") if actual_count > 0 else 0.0

        tolerance_exceeded = self._is_tolerance_exceeded(expected_count, actual_count, difference, abs(percentage_diff))

        if difference == 0:
            status = ValidationStatus.PASSED
        elif tolerance_exceeded:
            status = ValidationStatus.FAILED
        else:
            status = ValidationStatus.WARNING

        return RowCountDiscrepancy(
            table_name=table_name,
            expected_count=expected_count,
            actual_count=actual_count,
            difference=difference,
            percentage_diff=percentage_diff,
            tolerance_exceeded=tolerance_exceeded,
            status=status,
        )

    def _is_tolerance_exceeded(
        self,
        expected_count: int,
        actual_count: int,
        difference: int,
        percentage_diff: float,
    ) -> bool:
        if expected_count <= self.absolute_tolerance * 10:
            return abs(difference) > self.absolute_tolerance

        return percentage_diff > self.tolerance_percent

    def _log_validation_results(self, result: ValidationResult) -> None:
        from .shared.logging import log_row_count_summary

        log_row_count_summary(result, log=self.logger)

    def compare_row_counts(
        self, expected_counts: dict[str, int], actual_counts: dict[str, int]
    ) -> list[RowCountDiscrepancy]:
        discrepancies = []

        for table_name, expected_count in expected_counts.items():
            if table_name in actual_counts:
                actual_count = actual_counts[table_name]
                discrepancy = self._create_discrepancy(table_name, expected_count, actual_count)
                discrepancies.append(discrepancy)
            else:
                discrepancy = RowCountDiscrepancy(
                    table_name=table_name,
                    expected_count=expected_count,
                    actual_count=0,
                    difference=-expected_count,
                    percentage_diff=-100.0,
                    tolerance_exceeded=True,
                    status=ValidationStatus.FAILED,
                )
                discrepancies.append(discrepancy)

        return discrepancies

    def get_table_exists_status(self, table_names: list[str]) -> dict[str, bool]:
        status = {}

        temp_conn = self.platform_adapter.create_connection(**self.platform_adapter.platform_config)
        try:
            for table_name in table_names:
                try:
                    quoted_name = self._quote_identifier(table_name, self.platform_adapter.platform_name.lower())
                    query = f"SELECT 1 FROM {quoted_name} LIMIT 1"
                    cursor = temp_conn.cursor()
                    cursor.execute(query)
                    cursor.fetchone()
                    status[table_name] = True

                except Exception:
                    status[table_name] = False
        finally:
            self.platform_adapter.close_connection(temp_conn)

        return status

    def validate_data_integrity(self, validation_queries: dict[str, str]) -> ValidationResult:
        result = ValidationResult()
        result.total_tables = len(validation_queries)

        temp_conn = self.platform_adapter.create_connection(**self.platform_adapter.platform_config)
        try:
            for check_name, query in validation_queries.items():
                try:
                    cursor = temp_conn.cursor()
                    cursor.execute(query)
                    query_result = cursor.fetchone()

                    if query_result is None:
                        result.add_error(f"Integrity check '{check_name}' returned no results")
                        continue

                    check_passed = bool(query_result[0]) if query_result[0] is not None else False

                    if check_passed:
                        result.passed_tables += 1
                    else:
                        result.failed_tables += 1
                        result.add_error(f"Integrity check '{check_name}' failed")

                except Exception as e:
                    result.add_error(f"Integrity check '{check_name}' error: {e}")
                    result.failed_tables += 1
        finally:
            self.platform_adapter.close_connection(temp_conn)

        return result
