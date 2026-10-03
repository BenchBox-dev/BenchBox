# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ValidationLevel(Enum):
    STRICT = "strict"
    STANDARD = "standard"
    LOOSE = "loose"


class ComparisonStatus(Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    PARTIAL_MATCH = "partial_match"
    ERROR = "error"


@dataclass
class ValidationResult:
    is_valid: bool
    status: ComparisonStatus = ComparisonStatus.MATCH
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.is_valid

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.is_valid = False
        if self.status == ComparisonStatus.MATCH:
            self.status = ComparisonStatus.MISMATCH

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)
        if self.status == ComparisonStatus.MATCH:
            self.status = ComparisonStatus.PARTIAL_MATCH

    def merge(self, other: ValidationResult) -> ValidationResult:
        if not other.is_valid:
            self.is_valid = False
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        self.metrics.update(other.metrics)
        self.details.update(other.details)
        if other.status == ComparisonStatus.MISMATCH:
            self.status = ComparisonStatus.MISMATCH
        elif other.status == ComparisonStatus.PARTIAL_MATCH and self.status == ComparisonStatus.MATCH:
            self.status = ComparisonStatus.PARTIAL_MATCH
        elif other.status == ComparisonStatus.ERROR:
            self.status = ComparisonStatus.ERROR
        return self

    @classmethod
    def success(cls, metrics: dict[str, Any] | None = None) -> ValidationResult:
        return cls(is_valid=True, status=ComparisonStatus.MATCH, metrics=metrics or {})

    @classmethod
    def failure(cls, error: str, metrics: dict[str, Any] | None = None) -> ValidationResult:
        return cls(
            is_valid=False,
            status=ComparisonStatus.MISMATCH,
            errors=[error],
            metrics=metrics or {},
        )

    @classmethod
    def error(cls, error: str) -> ValidationResult:
        return cls(
            is_valid=False,
            status=ComparisonStatus.ERROR,
            errors=[error],
        )


@dataclass
class ValidationConfig:
    level: ValidationLevel = ValidationLevel.STANDARD
    float_tolerance: float = 1e-6
    float_abs_tolerance: float = 1e-10
    ignore_column_order: bool = True
    ignore_row_order: bool = True
    ignore_case: bool = False
    null_equals_null: bool = True


DEFAULT_CONFIG = ValidationConfig()


def validate_row_count(
    actual_rows: int,
    expected_rows: int,
    *,
    tolerance_percent: float = 0.0,
) -> ValidationResult:
    metrics = {
        "actual_rows": actual_rows,
        "expected_rows": expected_rows,
    }

    if actual_rows == expected_rows:
        return ValidationResult.success(metrics)

    if tolerance_percent > 0 and expected_rows > 0:
        deviation = abs(actual_rows - expected_rows) / expected_rows * 100
        metrics["deviation_percent"] = deviation
        if deviation <= tolerance_percent:
            result = ValidationResult.success(metrics)
            result.add_warning(
                f"Row count {actual_rows} differs from expected {expected_rows} "
                f"by {deviation:.2f}% (within {tolerance_percent}% tolerance)"
            )
            return result

    return ValidationResult.failure(
        f"Row count mismatch: got {actual_rows}, expected {expected_rows}",
        metrics,
    )


def validate_column_names(
    actual_columns: list[str],
    expected_columns: list[str],
    *,
    config: ValidationConfig | None = None,
) -> ValidationResult:
    cfg = config or DEFAULT_CONFIG
    metrics = {
        "actual_columns": actual_columns,
        "expected_columns": expected_columns,
    }

    if cfg.ignore_case:
        actual_set = {c.lower() for c in actual_columns}
        expected_set = {c.lower() for c in expected_columns}
    else:
        actual_set = set(actual_columns)
        expected_set = set(expected_columns)

    if actual_set == expected_set:
        if cfg.ignore_column_order:
            return ValidationResult.success(metrics)
        if cfg.ignore_case:
            actual_ordered = [c.lower() for c in actual_columns]
            expected_ordered = [c.lower() for c in expected_columns]
        else:
            actual_ordered = actual_columns
            expected_ordered = expected_columns
        if actual_ordered == expected_ordered:
            return ValidationResult.success(metrics)
        result = ValidationResult.success(metrics)
        result.add_warning(f"Column order differs: got {actual_columns}, expected {expected_columns}")
        return result

    missing = expected_set - actual_set
    extra = actual_set - expected_set

    errors = []
    if missing:
        errors.append(f"Missing columns: {sorted(missing)}")
    if extra:
        errors.append(f"Extra columns: {sorted(extra)}")

    return ValidationResult.failure("; ".join(errors), metrics)


def fuzzy_float_compare(
    actual: float,
    expected: float,
    *,
    rel_tolerance: float = 1e-6,
    abs_tolerance: float = 1e-10,
) -> bool:
    if actual == expected:
        return True

    import math

    if math.isnan(actual) and math.isnan(expected):
        return True
    if math.isnan(actual) or math.isnan(expected):
        return False
    if math.isinf(actual) and math.isinf(expected):
        return (actual > 0) == (expected > 0)
    if math.isinf(actual) or math.isinf(expected):
        return False

    diff = abs(actual - expected)
    threshold = max(rel_tolerance * abs(expected), abs_tolerance)
    return diff <= threshold


def _convert_to_polars(df: Any) -> Any:
    try:
        import polars as pl
    except ImportError as e:
        raise ImportError("Polars is required for DataFrame comparison") from e

    if isinstance(df, (pl.DataFrame, pl.LazyFrame)):
        if isinstance(df, pl.LazyFrame):
            return df.collect()
        return df

    try:
        import pandas as pd

        if isinstance(df, pd.DataFrame):
            return pl.from_pandas(df)
    except ImportError:
        pass

    if isinstance(df, dict):
        return pl.DataFrame(df)

    if isinstance(df, list) and len(df) > 0 and isinstance(df[0], dict):
        return pl.DataFrame(df)

    raise TypeError(f"Cannot convert {type(df).__name__} to Polars DataFrame")


def compare_dataframes(
    actual: Any,
    expected: Any,
    *,
    config: ValidationConfig | None = None,
) -> ValidationResult:
    cfg = config or DEFAULT_CONFIG

    try:
        actual_df = _convert_to_polars(actual)
        expected_df = _convert_to_polars(expected)
    except (ImportError, TypeError) as e:
        return ValidationResult.error(f"Cannot compare DataFrames: {e}")

    result = ValidationResult.success()

    actual_rows = len(actual_df)
    expected_rows = len(expected_df)
    result.metrics["actual_rows"] = actual_rows
    result.metrics["expected_rows"] = expected_rows

    if actual_rows != expected_rows:
        result.add_error(f"Row count mismatch: got {actual_rows}, expected {expected_rows}")
        return result

    actual_cols = actual_df.columns
    expected_cols = expected_df.columns
    col_result = validate_column_names(actual_cols, expected_cols, config=cfg)
    result.merge(col_result)

    if not col_result.is_valid and cfg.level != ValidationLevel.LOOSE:
        return result

    if cfg.level == ValidationLevel.LOOSE:
        return result

    common_cols = list(set(actual_cols) & set(expected_cols))
    if not common_cols:
        result.add_error("No common columns to compare")
        return result

    actual_sorted, expected_sorted = _prepare_sorted_dataframes(actual_df, expected_df, common_cols, cfg, result)

    mismatches = _compare_columns(actual_sorted, expected_sorted, common_cols, cfg, result)

    if mismatches:
        for msg in mismatches:
            result.add_error(msg)
        result.metrics["column_mismatches"] = len(mismatches)

    return result


def _prepare_sorted_dataframes(
    actual_df: Any,
    expected_df: Any,
    common_cols: list[str],
    cfg: ValidationConfig,
    result: ValidationResult,
) -> tuple[Any, Any]:
    if cfg.ignore_row_order:
        try:
            actual_sorted = actual_df.select(common_cols).sort(common_cols)
            expected_sorted = expected_df.select(common_cols).sort(common_cols)
        except Exception as e:
            result.add_warning(f"Could not sort DataFrames for comparison: {e}")
            actual_sorted = actual_df.select(common_cols)
            expected_sorted = expected_df.select(common_cols)
    else:
        actual_sorted = actual_df.select(common_cols)
        expected_sorted = expected_df.select(common_cols)
    return actual_sorted, expected_sorted


def _compare_columns(
    actual_sorted: Any,
    expected_sorted: Any,
    common_cols: list[str],
    cfg: ValidationConfig,
    result: ValidationResult,
) -> list[str]:
    import polars as pl

    mismatches = []
    for col in common_cols:
        actual_col = actual_sorted.get_column(col)
        expected_col = expected_sorted.get_column(col)

        if actual_col.dtype != expected_col.dtype:
            if actual_col.dtype.is_numeric() and expected_col.dtype.is_numeric():
                result.add_warning(f"Column '{col}' has different types: {actual_col.dtype} vs {expected_col.dtype}")
            else:
                mismatches.append(f"Column '{col}' type mismatch: {actual_col.dtype} vs {expected_col.dtype}")
                continue

        if actual_col.dtype.is_float():
            mismatch = _compare_float_column(actual_sorted, actual_col, expected_col, col, cfg, pl)
        else:
            mismatch = _compare_exact_column(actual_col, expected_col, col, cfg)

        if mismatch:
            mismatches.append(mismatch)

    return mismatches


def _compare_float_column(
    actual_sorted: Any, actual_col: Any, expected_col: Any, col: str, cfg: ValidationConfig, pl: Any
) -> str | None:
    diff = (actual_col - expected_col).abs()
    rel_threshold = expected_col.abs() * cfg.float_tolerance
    threshold = rel_threshold.fill_null(cfg.float_abs_tolerance)
    threshold = (
        pl.when(threshold < cfg.float_abs_tolerance)
        .then(pl.lit(cfg.float_abs_tolerance))
        .otherwise(threshold)
        .alias("threshold")
    )
    threshold_series = actual_sorted.select(threshold).to_series()

    actual_null = actual_col.is_null()
    expected_null = expected_col.is_null()
    value_match = (diff <= threshold_series) | (actual_null & expected_null)
    if not value_match.all():
        mismatch_count = (~value_match).sum()
        return f"Column '{col}': {mismatch_count} value mismatches"
    return None


def _compare_exact_column(actual_col: Any, expected_col: Any, col: str, cfg: ValidationConfig) -> str | None:
    if cfg.null_equals_null:
        match = (actual_col == expected_col) | (actual_col.is_null() & expected_col.is_null())
    else:
        match = actual_col == expected_col
    if not match.all():
        mismatch_count = (~match).sum()
        return f"Column '{col}': {mismatch_count} value mismatches"
    return None


def compare_with_sql(
    dataframe_result: Any,
    sql_result: Any,
    *,
    query_id: str | None = None,
    config: ValidationConfig | None = None,
) -> ValidationResult:
    result = compare_dataframes(dataframe_result, sql_result, config=config)

    if query_id:
        result.details["query_id"] = query_id
        if not result.is_valid:
            result.errors = [f"[{query_id}] {e}" for e in result.errors]
            result.warnings = [f"[{query_id}] {w}" for w in result.warnings]

    return result


def validate_query_result(
    result: Any,
    *,
    expected_rows: int | None = None,
    expected_columns: list[str] | None = None,
    query_id: str | None = None,
    config: ValidationConfig | None = None,
) -> ValidationResult:
    cfg = config or DEFAULT_CONFIG
    validation = ValidationResult.success()

    try:
        df = _convert_to_polars(result)
    except (ImportError, TypeError) as e:
        return ValidationResult.error(f"Cannot validate result: {e}")

    actual_rows = len(df)
    actual_cols = df.columns

    validation.metrics["actual_rows"] = actual_rows
    validation.metrics["actual_columns"] = actual_cols

    if expected_rows is not None:
        row_result = validate_row_count(actual_rows, expected_rows)
        validation.merge(row_result)

    if expected_columns is not None:
        col_result = validate_column_names(actual_cols, expected_columns, config=cfg)
        validation.merge(col_result)

    if query_id:
        validation.details["query_id"] = query_id
        if not validation.is_valid:
            validation.errors = [f"[{query_id}] {e}" for e in validation.errors]

    return validation


class DataFrameValidator:
    def __init__(self, config: ValidationConfig | None = None):
        self.config = config or DEFAULT_CONFIG
        self.results: list[ValidationResult] = []

    def validate(
        self,
        actual: Any,
        expected: Any,
        *,
        query_id: str | None = None,
    ) -> ValidationResult:
        result = compare_dataframes(actual, expected, config=self.config)
        if query_id:
            result.details["query_id"] = query_id
        self.results.append(result)
        return result

    def validate_row_count(
        self,
        result: Any,
        expected_rows: int,
        *,
        query_id: str | None = None,
    ) -> ValidationResult:
        try:
            df = _convert_to_polars(result)
            actual_rows = len(df)
        except (ImportError, TypeError) as e:
            return ValidationResult.error(f"Cannot get row count: {e}")

        validation = validate_row_count(actual_rows, expected_rows)
        if query_id:
            validation.details["query_id"] = query_id
        self.results.append(validation)
        return validation

    def summary(self) -> dict[str, Any]:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.is_valid)
        failed = total - passed
        all_errors = [e for r in self.results for e in r.errors]
        all_warnings = [w for r in self.results for w in r.warnings]

        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / total if total > 0 else 1.0,
            "error_count": len(all_errors),
            "warning_count": len(all_warnings),
            "is_valid": failed == 0,
        }

    def reset(self) -> None:
        self.results.clear()
