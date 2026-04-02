"""TPC-DI ETL transformation engine for data processing and business logic application.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DI (TPC-DI) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DI specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import gc
import logging
import multiprocessing
import multiprocessing as mp
import re
import threading
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Any, Callable, Optional, cast

import pandas as pd
import psutil

from benchbox.utils.clock import elapsed_seconds, mono_time

# Configure logging
logger = logging.getLogger(__name__)

# Performance optimization constants
DEFAULT_CHUNK_SIZE = 10000
VECTORIZE_THRESHOLD = 1000  # Minimum rows to use vectorized operations
PARALLEL_THRESHOLD = 100000  # Minimum rows to use parallel processing
MEMORY_THRESHOLD = 0.85  # Memory usage threshold for chunking

# TPC-DI specific constants
TPCDI_DATE_FORMAT = "%Y-%m-%d"
TPCDI_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_CREDIT_RATING = 10
MIN_CREDIT_RATING = 1
DEFAULT_BATCH_ID = 1
_VECTOR_DATETIME_TYPES = {"DATE", "DATETIME", "TIMESTAMP"}
_VECTOR_NUMERIC_TYPES = {"BIGINT", "INT", "INTEGER", "FLOAT", "DOUBLE"}


class TransformationRule(ABC):
    """Abstract base class for transformation rules."""

    @abstractmethod
    def apply(self, data: pd.DataFrame) -> pd.DataFrame:
        """Apply the transformation rule to input data.

        Args:
            data: Input dataframe to transform

        Returns:
            Transformed dataframe
        """
        ...

    def apply_streaming(self, data_chunks: Iterator[pd.DataFrame]) -> Iterator[pd.DataFrame]:
        """Apply the transformation rule to streaming data chunks.

        Args:
            data_chunks: Iterator of dataframe chunks to transform

        Yields:
            Transformed dataframe chunks
        """
        for chunk in data_chunks:
            yield self.apply(chunk)


class DataTypeTransformation(TransformationRule):
    """Handles data type conversions and casting operations for TPC-DI data."""

    def __init__(
        self,
        type_mappings: dict[str, str],
        date_formats: Optional[dict[str, str]] = None,
    ) -> None:
        """Initialize with column type mappings.

        Args:
            type_mappings: Dictionary mapping column names to target types
            date_formats: Optional dict mapping column names to date format strings
        """
        self.type_mappings = type_mappings
        self.date_formats = date_formats or {}

    def apply(self, data: pd.DataFrame) -> pd.DataFrame:
        """Apply data type transformations with TPC-DI specific handling.

        Args:
            data: Input dataframe

        Returns:
            Dataframe with converted types
        """
        if data.empty:
            return data

        result = data.copy()

        # Use vectorized operations for large datasets
        use_vectorized = len(data) >= VECTORIZE_THRESHOLD

        if use_vectorized:
            logger.debug(f"Using vectorized type conversion for {len(data)} rows")
            result = self._apply_vectorized_conversions(result)
        else:
            # Standard column-by-column conversion
            for column, target_type in self.type_mappings.items():
                if column not in result.columns:
                    logger.warning(f"Column {column} not found in data")
                    continue

                try:
                    result[column] = self._convert_column(result[column], target_type, column)
                except Exception as e:
                    logger.error(f"Failed to convert column {column} to {target_type}: {e}")
                    # Mark invalid data for quality tracking
                    result[f"{column}_invalid"] = True

        return result

    def _apply_vectorized_conversions(self, data: pd.DataFrame) -> pd.DataFrame:
        """Apply vectorized type conversions for better performance."""
        result = data.copy()
        datetime_cols = self._get_vectorized_columns(
            lambda col, dtype: dtype.upper() in _VECTOR_DATETIME_TYPES and col in result.columns
        )
        numeric_cols = self._get_vectorized_columns(
            lambda col, dtype: dtype.upper() in _VECTOR_NUMERIC_TYPES and col in result.columns
        )
        string_cols = self._get_vectorized_columns(
            lambda col, dtype: (dtype.upper().startswith("VARCHAR") or dtype.upper() == "TEXT")
            and col in result.columns
        )

        self._apply_vectorized_conversion_group(result, datetime_cols, "datetime", self._convert_vectorized_datetime)
        self._apply_vectorized_conversion_group(result, numeric_cols, "numeric", self._convert_vectorized_numeric)
        self._apply_vectorized_conversion_group(result, string_cols, "string", self._convert_vectorized_string)
        return result

    def _get_vectorized_columns(self, predicate: Callable[[str, str], bool]) -> list[str]:
        return [col for col, dtype in self.type_mappings.items() if predicate(col, dtype)]

    def _apply_vectorized_conversion_group(
        self,
        result: pd.DataFrame,
        columns: list[str],
        group_name: str,
        converter: Callable[[pd.Series, str], pd.Series],
    ) -> None:
        for col in columns:
            try:
                result[col] = converter(result[col], self.type_mappings[col].upper())
            except Exception as e:
                logger.warning(f"Vectorized {group_name} conversion failed for {col}: {e}")
                result[col] = self._convert_column(result[col], self.type_mappings[col], col)

    @staticmethod
    def _convert_vectorized_datetime(series: pd.Series, target_type: str) -> pd.Series:
        parsed = pd.to_datetime(series, errors="coerce")
        return parsed.dt.date if target_type == "DATE" else parsed

    @staticmethod
    def _convert_vectorized_numeric(series: pd.Series, target_type: str) -> pd.Series:
        numeric = pd.to_numeric(series, errors="coerce")
        if target_type in {"BIGINT", "INT", "INTEGER"}:
            return numeric.astype("Int64")
        return numeric

    @staticmethod
    def _convert_vectorized_string(series: pd.Series, _target_type: str) -> pd.Series:
        return series.astype(str).replace("nan", "")

    def _convert_column(self, series: pd.Series, target_type: str, column_name: str) -> pd.Series:
        """Convert a pandas Series to the target data type.

        Args:
            series: Input series to convert
            target_type: Target data type as string
            column_name: Name of the column for error reporting

        Returns:
            Converted series
        """
        target_type = target_type.upper()

        if target_type.startswith("VARCHAR") or target_type == "TEXT":
            return series.astype(str).replace("nan", "")

        elif target_type in ["DATE"]:
            return self._convert_to_date(series, column_name)

        elif target_type in ["DATETIME", "TIMESTAMP"]:
            return self._convert_to_datetime(series, column_name)

        elif target_type in ["BIGINT", "INT", "INTEGER"]:
            return self._convert_to_integer(series)

        elif target_type.startswith("DECIMAL") or target_type in ["FLOAT", "DOUBLE"]:
            return self._convert_to_decimal(series)

        elif target_type in ["BOOLEAN", "BOOL"]:
            return self._convert_to_boolean(series)

        elif target_type == "TINYINT":
            return self._convert_to_tinyint(series)

        else:
            logger.warning(f"Unknown target type {target_type}, returning as string")
            return series.astype(str)

    def _convert_to_date(self, series: pd.Series, column_name: str) -> pd.Series:
        """Convert series to date with TPC-DI specific handling."""
        date_format = self.date_formats.get(column_name, TPCDI_DATE_FORMAT)

        def safe_date_convert(value: Any) -> Any:
            if pd.isna(value) or value == "" or value == "NULL":
                return pd.NaT
            try:
                if isinstance(value, (datetime, date)):
                    return pd.to_datetime(value).date()
                return pd.to_datetime(str(value), format=date_format).date()
            except (ValueError, TypeError):
                try:
                    return pd.to_datetime(str(value)).date()
                except Exception:
                    logger.warning(f"Could not convert '{value}' to date in column {column_name}")
                    return pd.NaT

        return cast(pd.Series, series.apply(safe_date_convert))

    def _convert_to_datetime(self, series: pd.Series, column_name: str) -> pd.Series:
        """Convert series to datetime with TPC-DI specific handling."""
        datetime_format = self.date_formats.get(column_name, TPCDI_DATETIME_FORMAT)

        def safe_datetime_convert(value: Any) -> Any:
            if pd.isna(value) or value == "" or value == "NULL":
                return pd.NaT
            try:
                if isinstance(value, datetime):
                    return value
                return pd.to_datetime(str(value), format=datetime_format)
            except (ValueError, TypeError):
                try:
                    return pd.to_datetime(str(value))
                except Exception:
                    logger.warning(f"Could not convert '{value}' to datetime in column {column_name}")
                    return pd.NaT

        return cast(pd.Series, series.apply(safe_datetime_convert))

    def _convert_to_integer(self, series: pd.Series) -> pd.Series:
        """Convert series to integer with null handling."""

        def safe_int_convert(value: Any) -> Any:
            if pd.isna(value) or value == "" or value == "NULL":
                return pd.NA
            try:
                if isinstance(value, str) and value.strip() == "":
                    return pd.NA
                return int(float(str(value)))
            except (ValueError, TypeError):
                return pd.NA

        return cast(pd.Series, series.apply(safe_int_convert).astype("Int64"))

    def _convert_to_decimal(self, series: pd.Series) -> pd.Series:
        """Convert series to decimal/float with null handling."""

        def safe_decimal_convert(value: Any) -> Any:
            if pd.isna(value) or value == "" or value == "NULL":
                return pd.NA
            try:
                if isinstance(value, str) and value.strip() == "":
                    return pd.NA
                return float(str(value))
            except (ValueError, TypeError):
                return pd.NA

        return cast(pd.Series, series.apply(safe_decimal_convert))

    def _convert_to_boolean(self, series: pd.Series) -> pd.Series:
        """Convert series to boolean with TPC-DI specific handling."""

        def safe_bool_convert(value: Any) -> Any:
            if pd.isna(value) or value == "" or value == "NULL":
                return pd.NA

            str_val = str(value).strip().lower()
            if str_val in ["true", "1", "yes", "y", "t"]:
                return True
            elif str_val in ["false", "0", "no", "n", "f"]:
                return False
            else:
                return pd.NA

        return cast(pd.Series, series.apply(safe_bool_convert))

    def _convert_to_tinyint(self, series: pd.Series) -> pd.Series:
        """Convert series to tinyint (0-255) with validation."""
        int_series = self._convert_to_integer(series)

        def validate_tinyint(value: Any) -> Any:
            if pd.isna(value):
                return pd.NA
            if 0 <= value <= 255:
                return value
            else:
                logger.warning(f"Value {value} out of range for TINYINT (0-255)")
                return pd.NA

        return cast(pd.Series, int_series.apply(validate_tinyint))


class BusinessRuleTransformation(TransformationRule):
    """Applies TPC-DI specific business rules and calculations."""

    def __init__(self, rule_name: str, rule_config: dict[str, Any]) -> None:
        """Initialize business rule transformation.

        Args:
            rule_name: Name of the business rule to apply
            rule_config: Configuration parameters for the rule
        """
        self.rule_name = rule_name
        self.rule_config = rule_config
        self.business_rules = {
            "credit_rating_validation": self._validate_credit_rating,
            "net_worth_calculation": self._calculate_net_worth,
            "customer_tier_assignment": self._assign_customer_tier,
            "trade_commission_calculation": self._calculate_trade_commission,
            "trade_fee_calculation": self._calculate_trade_fee,
            "security_status_validation": self._validate_security_status,
            "account_status_validation": self._validate_account_status,
            "tax_calculation": self._calculate_tax,
            "marketing_nameplate_generation": self._generate_marketing_nameplate,
            "phone_number_standardization": self._standardize_phone_numbers,
            "email_validation": self._validate_email_addresses,
            "date_range_validation": self._validate_date_ranges,
        }

    def apply(self, data: pd.DataFrame) -> pd.DataFrame:
        """Apply business rule transformation.

        Args:
            data: Input dataframe

        Returns:
            Transformed dataframe with business rules applied
        """
        if data.empty:
            return data

        if self.rule_name not in self.business_rules:
            logger.warning(f"Unknown business rule: {self.rule_name}")
            return data

        try:
            return self.business_rules[self.rule_name](data)
        except Exception as e:
            logger.error(f"Error applying business rule {self.rule_name}: {e}")
            return data

    def _validate_credit_rating(self, data: pd.DataFrame) -> pd.DataFrame:
        """Validate and correct credit rating values (1-10 scale)."""
        result = data.copy()

        if "CreditRating" in result.columns:
            # Ensure credit rating is within valid range
            result["CreditRating"] = result["CreditRating"].apply(
                lambda x: max(MIN_CREDIT_RATING, min(MAX_CREDIT_RATING, x)) if pd.notna(x) else MIN_CREDIT_RATING
            )

            # Flag invalid original values
            invalid_mask = (data["CreditRating"] < MIN_CREDIT_RATING) | (data["CreditRating"] > MAX_CREDIT_RATING)
            if invalid_mask.any():
                result["CreditRating_corrected"] = invalid_mask
                logger.info(f"Corrected {invalid_mask.sum()} invalid credit rating values")

        return result

    def _calculate_net_worth(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate customer net worth based on assets and liabilities."""
        result = data.copy()

        # Net worth calculation logic (simplified for TPC-DI)
        if all(col in result.columns for col in ["Assets", "Liabilities"]):
            result["NetWorth"] = result["Assets"] - result["Liabilities"]
        elif "Income" in result.columns and "Age" in result.columns:
            # Estimate net worth based on income and age
            result["NetWorth"] = result["Income"] * (result["Age"] / 10) * 0.1

        # Ensure net worth is not negative (business rule)
        if "NetWorth" in result.columns:
            result["NetWorth"] = result["NetWorth"].apply(lambda x: max(0, x) if pd.notna(x) else 0)

        return result

    def _assign_customer_tier(self, data: pd.DataFrame) -> pd.DataFrame:
        """Assign customer tiers based on net worth and account value."""
        result = data.copy()

        if "NetWorth" in result.columns:

            def assign_tier(net_worth: Any) -> int:
                if pd.isna(net_worth):
                    return 3  # Default tier
                elif net_worth >= 1000000:
                    return 1  # Platinum
                elif net_worth >= 100000:
                    return 2  # Gold
                else:
                    return 3  # Standard

            result["Tier"] = result["NetWorth"].apply(assign_tier)

        return result

    def _calculate_trade_commission(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate trade commission based on trade value and customer tier."""
        result = data.copy()

        if all(col in result.columns for col in ["TradePrice", "Quantity"]):
            trade_value = result["TradePrice"] * result["Quantity"]

            # Commission rates by customer tier
            commission_rates = self.rule_config.get("commission_rates", {1: 0.005, 2: 0.0075, 3: 0.01})

            if "Tier" in result.columns:
                result["Commission"] = result.apply(
                    lambda row: trade_value.loc[row.name] * commission_rates.get(row["Tier"], 0.01),
                    axis=1,
                )
            else:
                # Default commission rate
                result["Commission"] = trade_value * 0.01

        return result

    def _calculate_trade_fee(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate trading fees based on trade type and volume."""
        result = data.copy()

        if "Type" in result.columns and "Quantity" in result.columns:
            # Fee structure based on trade type
            base_fees = self.rule_config.get("base_fees", {"Market": 5.0, "Limit": 7.5, "Stop": 10.0})

            def calculate_fee(row: Any) -> float:
                base_fee = base_fees.get(row["Type"], 5.0)
                quantity_fee = row["Quantity"] * 0.01 if pd.notna(row["Quantity"]) else 0
                return base_fee + quantity_fee

            result["Fee"] = result.apply(calculate_fee, axis=1)

        return result

    def _validate_security_status(self, data: pd.DataFrame) -> pd.DataFrame:
        """Validate security status values."""
        result = data.copy()

        if "Status" in result.columns:
            valid_statuses = {"Active", "Inactive", "Suspended", "Pending"}

            # Set invalid statuses to 'Active' (default)
            mask = ~result["Status"].isin(valid_statuses)
            if mask.any():
                result.loc[mask, "Status"] = "Active"
                result.loc[mask, "Status_corrected"] = True
                logger.info(f"Corrected {mask.sum()} invalid security status values")

        return result

    def _validate_account_status(self, data: pd.DataFrame) -> pd.DataFrame:
        """Validate account status values."""
        result = data.copy()

        if "Status" in result.columns:
            valid_statuses = {"Active", "Inactive", "Closed", "Suspended"}

            # Set invalid statuses to 'Active' (default)
            mask = ~result["Status"].isin(valid_statuses)
            if mask.any():
                result.loc[mask, "Status"] = "Active"
                result.loc[mask, "Status_corrected"] = True
                logger.info(f"Corrected {mask.sum()} invalid account status values")

        return result

    def _calculate_tax(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate tax based on trade profit and tax rates."""
        result = data.copy()

        required_cols = ["TradePrice", "Quantity", "LocalTaxRate", "NationalTaxRate"]
        if all(col in result.columns for col in required_cols):
            trade_value = result["TradePrice"] * result["Quantity"]

            # Simplified tax calculation (assumes profit = 10% of trade value)
            estimated_profit = trade_value * 0.1

            local_tax = estimated_profit * result["LocalTaxRate"].fillna(0)
            national_tax = estimated_profit * result["NationalTaxRate"].fillna(0)

            result["Tax"] = local_tax + national_tax

        return result

    def _generate_marketing_nameplate(self, data: pd.DataFrame) -> pd.DataFrame:
        """Generate marketing nameplate based on customer attributes."""
        result = data.copy()

        if all(col in result.columns for col in ["FirstName", "LastName", "Tier"]):

            def create_nameplate(row: Any) -> str:
                tier_names = {1: "Platinum", 2: "Gold", 3: "Standard"}
                tier_name = tier_names.get(row["Tier"], "Standard")
                return f"{tier_name} Customer: {row['FirstName']} {row['LastName']}"

            result["MarketingNameplate"] = result.apply(create_nameplate, axis=1)

        return result

    def _standardize_phone_numbers(self, data: pd.DataFrame) -> pd.DataFrame:
        """Standardize phone number formats."""
        result = data.copy()

        phone_columns = [col for col in result.columns if "Phone" in col]

        for col in phone_columns:
            if col in result.columns:
                result[col] = result[col].apply(self._format_phone_number)

        return result

    def _format_phone_number(self, phone: str) -> str:
        """Format phone number to standard format."""
        if pd.isna(phone) or phone == "":
            return ""

        # Remove all non-numeric characters
        digits = re.sub(r"\D", "", str(phone))

        # Format based on length
        if len(digits) == 10:
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        elif len(digits) == 11 and digits[0] == "1":
            return f"1-({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        else:
            return str(phone)  # Return original if format is unclear

    def _validate_email_addresses(self, data: pd.DataFrame) -> pd.DataFrame:
        """Validate email address formats."""
        result = data.copy()

        email_columns = [col for col in result.columns if "Email" in col]
        email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

        for col in email_columns:
            if col in result.columns:
                valid_mask = result[col].apply(
                    lambda x: bool(email_pattern.match(str(x))) if pd.notna(x) and x != "" else True
                )
                invalid_count = (~valid_mask).sum()
                if invalid_count > 0:
                    result.loc[~valid_mask, col] = ""  # Clear invalid emails
                    result.loc[~valid_mask, f"{col}_invalid"] = True
                    logger.info(f"Cleared {invalid_count} invalid email addresses in column {col}")

        return result

    def _validate_date_ranges(self, data: pd.DataFrame) -> pd.DataFrame:
        """Validate date ranges and relationships."""
        result = data.copy()

        # Validate EffectiveDate <= EndDate
        if all(col in result.columns for col in ["EffectiveDate", "EndDate"]):
            mask = (
                pd.notna(result["EffectiveDate"])
                & pd.notna(result["EndDate"])
                & (result["EffectiveDate"] > result["EndDate"])
            )

            if mask.any():
                # Normalize by setting EndDate to a far future date
                result.loc[mask, "EndDate"] = pd.to_datetime("2999-12-31").date()
                result.loc[mask, "EndDate_corrected"] = True
                logger.info(f"Corrected {mask.sum()} invalid date ranges")

        return result


class StreamingChunkProcessor:
    """Process streaming data chunks with memory management."""

    def __init__(self, memory_limit_mb: Optional[int] = None) -> None:
        """Initialize streaming processor.

        Args:
            memory_limit_mb: Maximum memory usage in MB
        """
        self.memory_limit_mb = memory_limit_mb or self._get_default_memory_limit()
        self.process = psutil.Process()
        self.peak_memory_mb = 0
        self.chunk_stats = deque(maxlen=100)  # Keep stats for last 100 chunks

    def _get_default_memory_limit(self) -> int:
        """Get default memory limit (80% of available memory)."""
        available_mb = psutil.virtual_memory().available / (1024 * 1024)
        return int(available_mb * 0.8)

    def get_current_memory_usage(self) -> float:
        """Get current memory usage in MB."""
        return self.process.memory_info().rss / (1024 * 1024)

    def check_memory_limits(self) -> tuple[bool, float]:
        """Check if memory usage is within limits.

        Returns:
            Tuple of (within_limits, current_usage_mb)
        """
        current_usage = self.get_current_memory_usage()
        self.peak_memory_mb = max(self.peak_memory_mb, current_usage)
        return current_usage <= self.memory_limit_mb, current_usage

    def force_gc(self) -> None:
        """Force garbage collection."""
        gc.collect()

    def process_chunk_streaming(
        self,
        chunk: pd.DataFrame,
        transformations: list[TransformationRule],
        chunk_id: int,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Process a single chunk with transformations and memory monitoring.

        Args:
            chunk: DataFrame chunk to process
            transformations: List of transformation rules to apply
            chunk_id: Unique identifier for this chunk

        Returns:
            Tuple of (transformed_chunk, processing_stats)
        """
        start_time = mono_time()
        start_memory = self.get_current_memory_usage()

        # Check memory before processing
        within_limits, current_memory = self.check_memory_limits()
        if not within_limits:
            self.force_gc()

        # Apply transformations sequentially
        transformed_chunk = chunk.copy()
        transformation_times = []

        for _i, rule in enumerate(transformations):
            rule_start = mono_time()
            try:
                transformed_chunk = rule.apply(transformed_chunk)
                transformation_times.append(elapsed_seconds(rule_start))
            except Exception as e:
                logger.error(f"Transformation {type(rule).__name__} failed on chunk {chunk_id}: {e}")
                # Continue with other transformations
                transformation_times.append(elapsed_seconds(rule_start))

        # Calculate processing stats
        end_time = mono_time()
        end_memory = self.get_current_memory_usage()

        stats = {
            "chunk_id": chunk_id,
            "input_rows": len(chunk),
            "output_rows": len(transformed_chunk),
            "processing_time_seconds": end_time - start_time,
            "memory_start_mb": start_memory,
            "memory_end_mb": end_memory,
            "memory_delta_mb": end_memory - start_memory,
            "transformation_times": transformation_times,
            "transformations_applied": len(transformations),
        }

        self.chunk_stats.append(stats)

        # Force cleanup if memory usage is high
        if end_memory > (self.memory_limit_mb * 0.8):
            self.force_gc()

        return transformed_chunk, stats

    def get_performance_stats(self) -> dict[str, Any]:
        """Get comprehensive performance statistics."""
        if not self.chunk_stats:
            return {}

        total_chunks = len(self.chunk_stats)
        total_time = sum(stat["processing_time_seconds"] for stat in self.chunk_stats)
        total_input_rows = sum(stat["input_rows"] for stat in self.chunk_stats)
        total_output_rows = sum(stat["output_rows"] for stat in self.chunk_stats)

        avg_time = total_time / total_chunks
        avg_memory_delta = sum(stat["memory_delta_mb"] for stat in self.chunk_stats) / total_chunks

        return {
            "total_chunks_processed": total_chunks,
            "total_processing_time_seconds": total_time,
            "total_input_rows": total_input_rows,
            "total_output_rows": total_output_rows,
            "average_chunk_time_seconds": avg_time,
            "average_memory_delta_mb": avg_memory_delta,
            "peak_memory_usage_mb": self.peak_memory_mb,
            "memory_limit_mb": self.memory_limit_mb,
            "rows_per_second": total_output_rows / total_time if total_time > 0 else 0,
        }


class StreamingSCDProcessor:
    """Streaming processor for SCD Type 2 operations."""

    def __init__(
        self,
        dimension_type: str,
        natural_keys: list[str],
        tracked_attributes: list[str],
    ) -> None:
        """Initialize streaming SCD processor.

        Args:
            dimension_type: Type of dimension (customer, security, etc.)
            natural_keys: Natural key columns for identifying records
            tracked_attributes: Attributes that trigger SCD Type 2 versioning
        """
        self.dimension_type = dimension_type
        self.natural_keys = natural_keys
        self.tracked_attributes = tracked_attributes
        self.existing_records = {}  # Cache for current records by natural key
        self.surrogate_key_counter = 1

    def process_chunk_scd2(self, chunk: pd.DataFrame, batch_id: int) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Process a chunk for SCD Type 2 changes.

        Args:
            chunk: DataFrame chunk containing new/changed records
            batch_id: Current batch identifier

        Returns:
            Tuple of (processed_chunk, scd_stats)
        """
        if chunk.empty:
            return chunk, {
                "new_records": 0,
                "changed_records": 0,
                "unchanged_records": 0,
            }

        result_records = []
        new_count = 0
        changed_count = 0
        unchanged_count = 0

        for _, new_record in chunk.iterrows():
            # Build natural key for lookup
            natural_key = tuple(new_record[key] for key in self.natural_keys)

            existing_record = self.existing_records.get(natural_key)

            if existing_record is None:
                # record - insert with new surrogate key
                new_record_dict = new_record.to_dict()
                new_record_dict[f"SK_{self.dimension_type.title()}ID"] = self.surrogate_key_counter
                new_record_dict["IsCurrent"] = True
                new_record_dict["EffectiveDate"] = datetime.now().date()
                new_record_dict["EndDate"] = datetime(9999, 12, 31).date()
                new_record_dict["BatchID"] = batch_id

                result_records.append(new_record_dict)
                self.existing_records[natural_key] = new_record_dict
                self.surrogate_key_counter += 1
                new_count += 1

            else:
                # Check for changes in tracked attributes
                has_changes = any(
                    str(new_record.get(attr, "")) != str(existing_record.get(attr, ""))
                    for attr in self.tracked_attributes
                    if attr in new_record.index
                )

                if has_changes:
                    # Close existing record
                    existing_record_copy = existing_record.copy()
                    existing_record_copy["IsCurrent"] = False
                    existing_record_copy["EndDate"] = datetime.now().date()
                    result_records.append(existing_record_copy)

                    # Create new version
                    new_record_dict = new_record.to_dict()
                    new_record_dict[f"SK_{self.dimension_type.title()}ID"] = self.surrogate_key_counter
                    new_record_dict["IsCurrent"] = True
                    new_record_dict["EffectiveDate"] = datetime.now().date()
                    new_record_dict["EndDate"] = datetime(9999, 12, 31).date()
                    new_record_dict["BatchID"] = batch_id

                    result_records.append(new_record_dict)
                    self.existing_records[natural_key] = new_record_dict
                    self.surrogate_key_counter += 1
                    changed_count += 1

                else:
                    # No changes - record already exists with same values
                    unchanged_count += 1

        result_df = pd.DataFrame(result_records) if result_records else pd.DataFrame()

        scd_stats = {
            "new_records": new_count,
            "changed_records": changed_count,
            "unchanged_records": unchanged_count,
            "total_output_records": len(result_df),
        }

        return result_df, scd_stats


class DimensionTransformation(TransformationRule):
    """Handles dimension table transformations including SCD operations."""

    def __init__(
        self,
        dimension_type: str,
        scd_type: int = 2,
        existing_data: Optional[pd.DataFrame] = None,
    ) -> None:
        """Initialize dimension transformation.

        Args:
            dimension_type: Type of dimension (customer, security, etc.)
            scd_type: Slowly Changing Dimension type (1, 2, or 3)
            existing_data: Existing dimension data for SCD processing
        """
        self.dimension_type = dimension_type
        self.scd_type = scd_type
        self.existing_data = existing_data

        # Define natural keys for each dimension type
        self.natural_keys = {
            "customer": ["CustomerID"],
            "account": ["AccountID"],
            "security": ["Symbol"],
            "company": ["CompanyID"],
            "broker": ["BrokerID"],
            "date": ["DateValue"],
            "time": ["TimeValue"],
        }

        # Define SCD Type 2 tracked attributes
        self.scd_attributes = {
            "customer": [
                "Status",
                "LastName",
                "FirstName",
                "AddressLine1",
                "AddressLine2",
                "PostalCode",
                "City",
                "StateProv",
                "Phone1",
                "Phone2",
                "Phone3",
                "Email1",
                "Email2",
                "CreditRating",
                "NetWorth",
                "Tier",
            ],
            "account": ["Status", "AccountDesc", "TaxStatus"],
            "security": ["Status", "Name", "SharesOutstanding", "Dividend"],
            "company": [
                "Status",
                "Name",
                "Industry",
                "SPrating",
                "CEO",
                "AddressLine1",
                "AddressLine2",
                "PostalCode",
                "City",
                "StateProv",
                "Description",
            ],
        }

    def apply(self, data: pd.DataFrame) -> pd.DataFrame:
        """Apply dimension transformation logic.

        Args:
            data: Input dataframe

        Returns:
            Transformed dimension data
        """
        if data.empty:
            return data

        # Apply specific transformation based on SCD type
        if self.scd_type == 1:
            return self._apply_scd_type1(data)
        elif self.scd_type == 2:
            return self._apply_scd_type2(data)
        elif self.scd_type == 3:
            return self._apply_scd_type3(data)
        else:
            logger.warning(f"Unsupported SCD type: {self.scd_type}")
            return data

    def _apply_scd_type1(self, data: pd.DataFrame) -> pd.DataFrame:
        """Apply SCD Type 1 transformation (overwrite)."""
        result = data.copy()

        # Generate surrogate keys if not present
        if f"SK_{self.dimension_type.title()}ID" not in result.columns:
            result[f"SK_{self.dimension_type.title()}ID"] = range(1, len(result) + 1)

        # Set current flag
        result["IsCurrent"] = True

        return result

    def _apply_scd_type2(self, data: pd.DataFrame) -> pd.DataFrame:
        """Apply SCD Type 2 transformation (versioning with effective dates)."""
        result = data.copy()

        # Ensure required SCD Type 2 columns exist
        scd_columns = ["IsCurrent", "EffectiveDate", "EndDate", "BatchID"]
        for col in scd_columns:
            if col not in result.columns:
                if col == "IsCurrent":
                    result[col] = True
                elif col == "EffectiveDate":
                    result[col] = datetime.now().date()
                elif col == "EndDate":
                    result[col] = pd.to_datetime("2999-12-31").date()
                elif col == "BatchID":
                    result[col] = DEFAULT_BATCH_ID

        # Generate surrogate keys
        if f"SK_{self.dimension_type.title()}ID" not in result.columns:
            result = self._generate_surrogate_keys(result)

        # If we have existing data, perform SCD Type 2 processing
        if self.existing_data is not None and not self.existing_data.empty:
            result = self._process_scd_type2_changes(result)

        return result

    def _apply_scd_type3(self, data: pd.DataFrame) -> pd.DataFrame:
        """Apply SCD Type 3 transformation (limited history with previous value columns)."""
        result = data.copy()

        # Generate surrogate keys if not present
        if f"SK_{self.dimension_type.title()}ID" not in result.columns:
            result[f"SK_{self.dimension_type.title()}ID"] = range(1, len(result) + 1)

        # For SCD Type 3, we'd add previous value columns for tracked attributes
        # This is a simplified implementation
        tracked_attrs = self.scd_attributes.get(self.dimension_type, [])
        for attr in tracked_attrs:
            if attr in result.columns:
                result[f"Previous{attr}"] = None  # Would be populated from existing data

        result["IsCurrent"] = True

        return result

    def _generate_surrogate_keys(self, data: pd.DataFrame) -> pd.DataFrame:
        """Generate surrogate keys for dimension records."""
        result = data.copy()

        surrogate_key_col = f"SK_{self.dimension_type.title()}ID"

        # Start surrogate keys from the max existing key + 1
        start_key = 1
        if self.existing_data is not None and not self.existing_data.empty:
            if surrogate_key_col in self.existing_data.columns:
                start_key = self.existing_data[surrogate_key_col].max() + 1

        result[surrogate_key_col] = range(start_key, start_key + len(result))

        return result

    def _process_scd_type2_changes(self, new_data: pd.DataFrame) -> pd.DataFrame:
        """Process SCD Type 2 changes by comparing with existing data."""
        natural_key = self.natural_keys.get(self.dimension_type, ["ID"])
        tracked_attrs = self.scd_attributes.get(self.dimension_type, [])

        if not all(col in new_data.columns for col in natural_key):
            logger.warning(f"Natural key columns {natural_key} not found in new data")
            return new_data

        result_records = []

        # Get current records from existing data
        current_existing = self.existing_data[self.existing_data["IsCurrent"]].copy()

        for _, new_record in new_data.iterrows():
            # Find matching existing record by natural key
            match_condition = True
            for key_col in natural_key:
                if key_col in current_existing.columns:
                    match_condition &= current_existing[key_col] == new_record[key_col]

            matching_records = current_existing[match_condition]

            if matching_records.empty:
                # record - insert as new
                new_record_dict = new_record.to_dict()
                new_record_dict["IsCurrent"] = True
                new_record_dict["EffectiveDate"] = datetime.now().date()
                new_record_dict["EndDate"] = pd.to_datetime("2999-12-31").date()
                result_records.append(new_record_dict)

            else:
                # Existing record - check for changes in tracked attributes
                existing_record = matching_records.iloc[0]

                # Compare tracked attributes
                has_changes = False
                for attr in tracked_attrs:
                    if attr in new_record.index and attr in existing_record.index:
                        if new_record[attr] != existing_record[attr]:
                            has_changes = True
                            break

                if has_changes:
                    # Close existing record
                    existing_record_dict = existing_record.to_dict()
                    existing_record_dict["IsCurrent"] = False
                    existing_record_dict["EndDate"] = datetime.now().date()
                    result_records.append(existing_record_dict)

                    # Create new version
                    new_record_dict = new_record.to_dict()
                    new_record_dict["IsCurrent"] = True
                    new_record_dict["EffectiveDate"] = datetime.now().date()
                    new_record_dict["EndDate"] = pd.to_datetime("2999-12-31").date()

                    # Generate new surrogate key
                    max_sk = max([r.get(f"SK_{self.dimension_type.title()}ID", 0) for r in result_records])
                    new_record_dict[f"SK_{self.dimension_type.title()}ID"] = max_sk + 1

                    result_records.append(new_record_dict)
                else:
                    # No changes - keep existing record
                    result_records.append(existing_record.to_dict())

        return pd.DataFrame(result_records) if result_records else new_data

    def create_dimension_with_metadata(self, data: pd.DataFrame, batch_id: int) -> pd.DataFrame:
        """Create dimension table with full TPC-DI metadata."""
        result = self.apply(data)

        # Add TPC-DI specific metadata
        if "BatchID" not in result.columns:
            result["BatchID"] = batch_id

        # Ensure proper column ordering for TPC-DI
        column_order = self._get_tpcdi_column_order()
        available_columns = [col for col in column_order if col in result.columns]
        other_columns = [col for col in result.columns if col not in column_order]

        result = result[available_columns + other_columns]

        return result

    def _get_tpcdi_column_order(self) -> list[str]:
        """Get standard TPC-DI column ordering for dimension tables."""
        base_order = [
            f"SK_{self.dimension_type.title()}ID",
            f"{self.dimension_type.title()}ID",
            "Status",
        ]

        # Add dimension-specific columns
        if self.dimension_type == "customer":
            base_order.extend(
                [
                    "TaxID",
                    "LastName",
                    "FirstName",
                    "MiddleInitial",
                    "Gender",
                    "Tier",
                    "DOB",
                    "AddressLine1",
                    "AddressLine2",
                    "PostalCode",
                    "City",
                    "StateProv",
                    "Country",
                ]
            )
        elif self.dimension_type == "security":
            base_order.extend(
                [
                    "Symbol",
                    "Issue",
                    "Name",
                    "ExchangeID",
                    "SK_CompanyID",
                    "SharesOutstanding",
                    "FirstTrade",
                    "FirstTradeOnExchange",
                    "Dividend",
                ]
            )

        # Add SCD Type 2 columns
        base_order.extend(["IsCurrent", "BatchID", "EffectiveDate", "EndDate"])

        return base_order


class FactTransformation(TransformationRule):
    """Handles fact table transformations and aggregations."""

    def __init__(
        self,
        fact_type: str,
        aggregation_rules: Optional[dict[str, str]] = None,
        dimension_lookups: Optional[dict[str, pd.DataFrame]] = None,
    ):
        """Initialize fact transformation.

        Args:
            fact_type: Type of fact table (trades, holdings, etc.)
            aggregation_rules: Rules for aggregating data
            dimension_lookups: Dimension tables for foreign key resolution
        """
        self.fact_type = fact_type
        self.aggregation_rules = aggregation_rules or {}
        self.dimension_lookups = dimension_lookups or {}

        # Define fact table specific transformations
        self.fact_processors = {
            "trade": self._process_trade_fact,
            "holdings": self._process_holdings_fact,
            "cashbalance": self._process_cashbalance_fact,
            "markethistory": self._process_markethistory_fact,
            "dailymarket": self._process_dailymarket_fact,
        }

    def apply(self, data: pd.DataFrame) -> pd.DataFrame:
        """Apply fact transformation logic.

        Args:
            data: Input dataframe

        Returns:
            Transformed fact data
        """
        if data.empty:
            return data

        # Apply general fact transformations
        result = self._apply_general_transformations(data)

        # Apply fact-specific transformations
        if self.fact_type in self.fact_processors:
            result = self.fact_processors[self.fact_type](result)

        return result

    def _apply_general_transformations(self, data: pd.DataFrame) -> pd.DataFrame:
        """Apply general transformations common to all fact tables."""
        result = data.copy()

        # Resolve foreign keys to surrogate keys
        result = self._resolve_foreign_keys(result)

        # Add batch tracking
        if "BatchID" not in result.columns:
            result["BatchID"] = DEFAULT_BATCH_ID

        # Apply aggregations if specified
        if self.aggregation_rules:
            result = self._apply_aggregations(result)

        return result

    def _resolve_foreign_keys(self, data: pd.DataFrame) -> pd.DataFrame:
        """Resolve natural keys to surrogate keys using dimension lookups."""
        result = data.copy()

        # Define foreign key mappings for TPC-DI fact tables
        fk_mappings = {
            "CustomerID": ("customer", "SK_CustomerID"),
            "AccountID": ("account", "SK_AccountID"),
            "SecurityID": ("security", "SK_SecurityID"),
            "CompanyID": ("company", "SK_CompanyID"),
            "BrokerID": ("broker", "SK_BrokerID"),
            "Symbol": ("security", "SK_SecurityID"),
            "TradeDate": ("date", "SK_CreateDateID"),
            "SettleDate": ("date", "SK_CloseDateID"),
            "TradeTime": ("time", "SK_CreateTimeID"),
            "SettleTime": ("time", "SK_CloseTimeID"),
        }

        for natural_key, (dim_type, surrogate_key) in fk_mappings.items():
            if natural_key in result.columns and dim_type in self.dimension_lookups:
                result = self._lookup_surrogate_key(result, natural_key, dim_type, surrogate_key)

        return result

    def _lookup_surrogate_key(
        self, data: pd.DataFrame, natural_key: str, dim_type: str, surrogate_key: str
    ) -> pd.DataFrame:
        """Lookup surrogate key from dimension table."""
        result = data.copy()
        dim_data = self.dimension_lookups[dim_type]

        # Get current dimension records only
        dim_lookup = dim_data[dim_data["IsCurrent"]] if "IsCurrent" in dim_data.columns else dim_data

        # Handle different lookup scenarios
        if natural_key == "Symbol" and dim_type == "security":
            # Special case for security symbol lookup
            merge_cols = ["Symbol"]
        elif natural_key in ["TradeDate", "SettleDate"] and dim_type == "date":
            # Date dimension lookup
            merge_cols = ["DateValue"]
            # Convert trade date to date format for lookup
            if natural_key in result.columns:
                result[f"{natural_key}_lookup"] = pd.to_datetime(result[natural_key]).dt.date
                natural_key = f"{natural_key}_lookup"
        elif natural_key in ["TradeTime", "SettleTime"] and dim_type == "time":
            # Time dimension lookup
            merge_cols = ["TimeValue"]
            # Convert trade time to time format for lookup
            if natural_key in result.columns:
                result[f"{natural_key}_lookup"] = pd.to_datetime(result[natural_key]).dt.time
                natural_key = f"{natural_key}_lookup"
        else:
            # Standard natural key lookup
            natural_id = f"{dim_type.title()}ID"
            merge_cols = [natural_id] if natural_id in dim_lookup.columns else [natural_key]

        # Perform the lookup
        if all(col in dim_lookup.columns for col in merge_cols):
            lookup_data = dim_lookup[merge_cols + [surrogate_key]].drop_duplicates()

            # Merge to get surrogate keys
            result = result.merge(
                lookup_data,
                left_on=natural_key,
                right_on=merge_cols[0],
                how="left",
                suffixes=("", "_dim"),
            )

            # Clean up merge artifacts
            if f"{merge_cols[0]}_dim" in result.columns:
                result = result.drop(columns=[f"{merge_cols[0]}_dim"])

        return result

    def _apply_aggregations(self, data: pd.DataFrame) -> pd.DataFrame:
        """Apply aggregation rules to fact data."""
        result = data.copy()

        for column, agg_rule in self.aggregation_rules.items():
            if column in result.columns:
                if agg_rule == "sum":
                    # Group by dimensions and sum measures
                    group_cols = [col for col in result.columns if col.startswith("SK_")]
                    if group_cols:
                        result = result.groupby(group_cols)[column].sum().reset_index()
                elif agg_rule == "avg":
                    group_cols = [col for col in result.columns if col.startswith("SK_")]
                    if group_cols:
                        result = result.groupby(group_cols)[column].mean().reset_index()

        return result

    def _process_trade_fact(self, data: pd.DataFrame) -> pd.DataFrame:
        """Process trade fact table specific transformations."""
        result = data.copy()

        # Calculate derived measures
        if all(col in result.columns for col in ["TradePrice", "Quantity"]):
            result["TradeValue"] = result["TradePrice"] * result["Quantity"]

        # Ensure trade status is valid
        if "Status" in result.columns:
            valid_statuses = {"Submitted", "Active", "Completed", "Canceled"}
            invalid_mask = ~result["Status"].isin(valid_statuses)
            if invalid_mask.any():
                result.loc[invalid_mask, "Status"] = "Submitted"
                result.loc[invalid_mask, "Status_corrected"] = True

        # Validate trade type
        if "Type" in result.columns:
            valid_types = {
                "Market Buy",
                "Market Sell",
                "Limit Buy",
                "Limit Sell",
                "Stop Loss",
            }
            invalid_mask = ~result["Type"].isin(valid_types)
            if invalid_mask.any():
                result.loc[invalid_mask, "Type"] = "Market Buy"
                result.loc[invalid_mask, "Type_corrected"] = True

        # Set cash flag for cash transactions
        if "CashFlag" not in result.columns:
            result["CashFlag"] = False  # Default to non-cash

        # Calculate total trade cost
        cost_columns = ["TradePrice", "Fee", "Commission", "Tax"]
        available_cost_cols = [col for col in cost_columns if col in result.columns]
        if len(available_cost_cols) > 1:
            result["TotalTradeCost"] = result[available_cost_cols].sum(axis=1)

        return result

    def _process_holdings_fact(self, data: pd.DataFrame) -> pd.DataFrame:
        """Process holdings fact table specific transformations."""
        result = data.copy()

        # Calculate current market value
        if all(col in result.columns for col in ["Quantity", "CurrentPrice"]):
            result["CurrentValue"] = result["Quantity"] * result["CurrentPrice"]

        # Calculate gain/loss if cost basis is available
        if all(col in result.columns for col in ["CurrentValue", "CostBasis"]):
            result["UnrealizedGainLoss"] = result["CurrentValue"] - result["CostBasis"]
            result["UnrealizedGainLossPercent"] = (result["UnrealizedGainLoss"] / result["CostBasis"] * 100).round(2)

        return result

    def _process_cashbalance_fact(self, data: pd.DataFrame) -> pd.DataFrame:
        """Process cash balance fact table specific transformations."""
        result = data.copy()

        # Ensure balance is not negative (business rule)
        if "Balance" in result.columns:
            negative_mask = result["Balance"] < 0
            if negative_mask.any():
                logger.warning(f"Found {negative_mask.sum()} negative cash balances")
                result.loc[negative_mask, "Balance_negative"] = True

        return result

    def _process_markethistory_fact(self, data: pd.DataFrame) -> pd.DataFrame:
        """Process market history fact table specific transformations."""
        result = data.copy()

        # Calculate daily price change
        if all(col in result.columns for col in ["ClosePrice", "OpenPrice"]):
            result["DailyChange"] = result["ClosePrice"] - result["OpenPrice"]
            result["DailyChangePercent"] = (result["DailyChange"] / result["OpenPrice"] * 100).round(4)

        # Calculate trading volume value
        if all(col in result.columns for col in ["Volume", "ClosePrice"]):
            result["VolumeValue"] = result["Volume"] * result["ClosePrice"]

        # Validate price data
        price_columns = ["OpenPrice", "HighPrice", "LowPrice", "ClosePrice"]
        for col in price_columns:
            if col in result.columns:
                # Ensure prices are positive
                negative_mask = result[col] <= 0
                if negative_mask.any():
                    logger.warning(f"Found {negative_mask.sum()} non-positive {col} values")
                    result.loc[negative_mask, f"{col}_invalid"] = True

        return result

    def _process_dailymarket_fact(self, data: pd.DataFrame) -> pd.DataFrame:
        """Process daily market fact table specific transformations."""
        result = data.copy()

        # Calculate 52-week high/low indicators
        if all(col in result.columns for col in ["ClosePrice", "FiftyTwoWeekHigh", "FiftyTwoWeekLow"]):
            result["AtFiftyTwoWeekHigh"] = result["ClosePrice"] >= result["FiftyTwoWeekHigh"]
            result["AtFiftyTwoWeekLow"] = result["ClosePrice"] <= result["FiftyTwoWeekLow"]

        # Calculate yield if dividend is available
        if all(col in result.columns for col in ["Dividend", "ClosePrice"]):
            result["Yield"] = (result["Dividend"] / result["ClosePrice"] * 100).round(4)

        return result

    def create_fact_with_metadata(self, data: pd.DataFrame, batch_id: int) -> pd.DataFrame:
        """Create fact table with full TPC-DI metadata and proper column ordering."""
        result = self.apply(data)

        # Add batch ID
        result["BatchID"] = batch_id

        # Ensure proper column ordering for TPC-DI
        column_order = self._get_tpcdi_fact_column_order()
        available_columns = [col for col in column_order if col in result.columns]
        other_columns = [col for col in result.columns if col not in column_order]

        result = result[available_columns + other_columns]

        return result

    def _get_tpcdi_fact_column_order(self) -> list[str]:
        """Get standard TPC-DI column ordering for fact tables."""
        if self.fact_type == "trade":
            return [
                "TradeID",
                "SK_BrokerID",
                "SK_CreateDateID",
                "SK_CreateTimeID",
                "SK_CloseDateID",
                "SK_CloseTimeID",
                "Status",
                "Type",
                "CashFlag",
                "SK_SecurityID",
                "SK_CompanyID",
                "Quantity",
                "BidPrice",
                "SK_CustomerID",
                "SK_AccountID",
                "ExecutedBy",
                "TradePrice",
                "Fee",
                "Commission",
                "Tax",
                "BatchID",
            ]
        else:
            # Generic fact table ordering
            sk_columns = [
                "SK_DateID",
                "SK_TimeID",
                "SK_CustomerID",
                "SK_AccountID",
                "SK_SecurityID",
                "SK_CompanyID",
                "SK_BrokerID",
            ]
            return sk_columns + ["BatchID"]


class TransformationConfig:
    """Simplified configuration for transformation processing."""

    def __init__(
        self,
        max_workers: Optional[int] = None,
        chunk_size: int = 5000,
        enable_parallel: bool = False,  # Parallel processing is opt-in
        worker_timeout: float = 300.0,
    ):
        """Initialize simplified transformation configuration.

        Args:
            max_workers: Maximum number of worker threads/processes
            chunk_size: Default number of records to process per chunk
            enable_parallel: Enable parallel processing
            worker_timeout: Timeout for worker operations in seconds
        """
        self.max_workers = max_workers or min(8, (multiprocessing.cpu_count() or 1) + 2)
        self.chunk_size = chunk_size
        self.enable_parallel = enable_parallel
        self.worker_timeout = worker_timeout

        # Validate configuration
        if self.max_workers < 1 or self.max_workers > 16:
            raise ValueError("max_workers must be between 1 and 16")
        if self.chunk_size < 100:
            raise ValueError("chunk_size must be at least 100")

    @classmethod
    def from_tpcdi_config(cls, tpcdi_config) -> "TransformationConfig":
        """Create TransformationConfig from TPCDIConfig."""
        etl_params = tpcdi_config.get_etl_config()
        return cls(
            max_workers=etl_params["max_workers"],
            chunk_size=etl_params["chunk_size"],
            enable_parallel=etl_params["enable_parallel_transform"],
            worker_timeout=etl_params["worker_timeout"],
        )


class ParallelTransformationContext:
    """Context for parallel transformation execution with monitoring."""

    def __init__(self, config: TransformationConfig) -> None:
        """Initialize parallel transformation context.

        Args:
            config: Enhanced parallel transformation configuration
        """
        self.config = config
        self.lock = threading.RLock()

        # Performance metrics
        self.transformation_metrics = {
            "dimension_processing_times": [],
            "fact_processing_times": [],
            "validation_times": [],
            "chunk_processing_times": [],
            "scd_processing_times": [],
            "parallel_efficiency": [],
            "memory_usage": [],
            "cpu_utilization": [],
        }

        # Worker tracking
        self.active_workers = set()
        self.completed_chunks = 0
        self.failed_chunks = 0
        self.total_records_processed = 0
        self.peak_memory_usage = 0

        # Adaptive chunking
        self.chunk_performance_history = []
        self.current_optimal_chunk_size = config.chunk_size

        # SCD tracking
        self.scd_operations = {
            "inserts": 0,
            "updates": 0,
            "scd2_versions": 0,
            "expired_records": 0,
        }

        # Quality metrics
        self.quality_issues = {
            "data_type_errors": 0,
            "constraint_violations": 0,
            "null_violations": 0,
            "business_rule_failures": 0,
        }

    def add_worker(self, worker_id: str) -> None:
        """Add active worker to tracking."""
        with self.lock:
            self.active_workers.add(worker_id)

    def remove_worker(self, worker_id: str) -> None:
        """Remove worker from tracking."""
        with self.lock:
            self.active_workers.discard(worker_id)

    def add_metric(self, metric_type: str, value: float) -> None:
        """Add performance metric in thread-safe manner."""
        with self.lock:
            if metric_type in self.transformation_metrics:
                self.transformation_metrics[metric_type].append(value)

    def get_processing_summary(self) -> dict[str, Any]:
        """Get comprehensive processing summary."""
        with self.lock:
            total_chunks = self.completed_chunks + self.failed_chunks

            return {
                "active_workers": len(self.active_workers),
                "completed_chunks": self.completed_chunks,
                "failed_chunks": self.failed_chunks,
                "total_records_processed": self.total_records_processed,
                "success_rate": self.completed_chunks / total_chunks if total_chunks > 0 else 0,
                "current_optimal_chunk_size": self.current_optimal_chunk_size,
                "peak_memory_usage_mb": self.peak_memory_usage,
                "scd_operations": self.scd_operations.copy(),
                "quality_issues": self.quality_issues.copy(),
            }


class TransformationEngine:
    """Main engine for orchestrating TPC-DI data transformations with parallel processing."""

    # Type hints for conditionally-set attributes
    parallel_context: Optional["ParallelTransformationContext"]

    def __init__(
        self,
        scale_factor: float = 1.0,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        max_workers: Optional[int] = None,
        enable_parallel: bool = False,  # Parallel processing is opt-in
        memory_limit_gb: Optional[float] = None,
        parallel_config: Optional[TransformationConfig] = None,
    ):
        """Initialize transformation engine.

        Args:
            scale_factor: TPC-DI scale factor for data volume
            chunk_size: Size of chunks for processing large datasets
            max_workers: Maximum number of worker processes/threads
            enable_parallel: Enable parallel processing for large datasets
            memory_limit_gb: Memory limit in GB (auto-detected if None)
            parallel_config: Parallel processing configuration
        """
        self.scale_factor = scale_factor
        self.chunk_size = chunk_size
        self.max_workers = max_workers or min(mp.cpu_count(), 8)
        self.enable_parallel = enable_parallel
        self.memory_limit_gb = memory_limit_gb or (psutil.virtual_memory().total / (1024**3) * 0.8)

        # Parallel processing
        self.parallel_config: TransformationConfig = parallel_config or TransformationConfig(
            max_workers=self.max_workers, chunk_size=chunk_size
        )
        self.parallel_enabled = parallel_config is not None

        if self.parallel_enabled:
            self.parallel_context = ParallelTransformationContext(self.parallel_config)
            # Worker pools are now created using context managers when needed
        else:
            self.parallel_context = None

        # Thread safety
        self._enhanced_lock = threading.RLock()

        self.transformation_rules: list[TransformationRule] = []
        self.batch_id: Optional[int] = None
        self.dimension_data: dict[str, pd.DataFrame] = {}
        self.quality_metrics: dict[str, Any] = {}

        # Performance tracking
        self.performance_stats: dict[str, Any] = {
            "chunks_processed": 0,
            "vectorized_operations": 0,
            "parallel_operations": 0,
            "memory_usage_peaks": [],
            "processing_times": {},
            "cache_hits": 0,
            "cache_misses": 0,
        }

        # Caching for lookup operations
        self._lookup_cache: dict[str, dict] = {}
        self._cache_max_size = 1000

        # Initialize logging
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Optimization settings based on scale factor
        self._configure_performance_settings()

        # TPC-DI specific configurations
        self.table_dependencies = {
            "DimDate": [],
            "DimTime": [],
            "DimCompany": [],
            "DimSecurity": ["DimCompany"],
            "DimCustomer": [],
            "DimAccount": ["DimCustomer"],
            "DimBroker": [],
            "FactTrade": [
                "DimDate",
                "DimTime",
                "DimSecurity",
                "DimCustomer",
                "DimAccount",
                "DimBroker",
            ],
            "FactHoldings": ["DimDate", "DimSecurity", "DimCustomer", "DimAccount"],
            "FactCashBalance": ["DimDate", "DimCustomer", "DimAccount"],
            "FactMarketHistory": ["DimDate", "DimSecurity"],
            "FactDailyMarket": ["DimDate", "DimSecurity"],
        }

    def _get_worker_pool_config(self) -> dict[str, Any]:
        """Get simple worker pool configuration."""
        return {
            "max_workers": self.parallel_config.max_workers,
            "use_threads_only": True,  # Simplified to use only ThreadPoolExecutor
        }

    def add_transformation(self, rule: TransformationRule) -> None:
        """Add a transformation rule to the engine.

        Args:
            rule: Transformation rule to add
        """
        if rule not in self.transformation_rules:
            self.transformation_rules.append(rule)
            self.logger.info(f"Added transformation rule: {type(rule).__name__}")

    def remove_transformation(self, rule: TransformationRule) -> None:
        """Remove a transformation rule from the engine.

        Args:
            rule: Transformation rule to remove
        """
        if rule in self.transformation_rules:
            self.transformation_rules.remove(rule)
            self.logger.info(f"Removed transformation rule: {type(rule).__name__}")

    def transform_batch(self, source_data: dict[str, pd.DataFrame], batch_id: int) -> dict[str, pd.DataFrame]:
        """Transform a complete batch of source data with performance optimizations.

        Args:
            source_data: Dictionary of source dataframes keyed by table name
            batch_id: Unique identifier for the batch

        Returns:
            Dictionary of transformed dataframes ready for loading
        """
        self.batch_id = batch_id
        start_time = mono_time()
        self.logger.info(f"Starting optimized batch transformation for batch {batch_id}")
        self.logger.info(
            f"Performance settings: chunk_size={self.chunk_size}, workers={self.max_workers}, parallel={self.enable_parallel}"
        )

        try:
            transformed_data = {}

            # Analyze dataset sizes for optimization decisions
            self._analyze_dataset_sizes(source_data)

            # Process tables in dependency order
            processing_order = self._get_processing_order()

            for table_name in processing_order:
                if table_name in source_data:
                    table_start = mono_time()
                    data_size = len(source_data[table_name])
                    self.logger.info(f"Transforming table: {table_name} ({data_size:,} rows)")

                    # Choose processing strategy based on data size
                    if data_size > PARALLEL_THRESHOLD and self.enable_parallel:
                        transformed_data[table_name] = self._transform_table_parallel(
                            source_data[table_name], table_name, batch_id
                        )
                        self.performance_stats["parallel_operations"] += 1
                    elif data_size > self.chunk_size:
                        transformed_data[table_name] = self._transform_table_chunked(
                            source_data[table_name], table_name, batch_id
                        )
                        self.performance_stats["chunks_processed"] += (data_size // self.chunk_size) + 1
                    else:
                        # Standard processing for smaller datasets
                        cleaned_data = self.apply_data_quality_rules(source_data[table_name], table_name)
                        transformed_data[table_name] = self._transform_single_table(cleaned_data, table_name, batch_id)

                    # Store dimension data for foreign key resolution
                    if table_name.startswith("Dim"):
                        dim_type = table_name.lower().replace("dim", "")
                        self.dimension_data[dim_type] = transformed_data[table_name]

                    table_time = elapsed_seconds(table_start)
                    self.performance_stats["processing_times"][table_name] = table_time
                    self.logger.info(f"  Completed {table_name} in {table_time:.2f}s")

                    # Memory management
                    self._manage_memory()

            # Generate audit metrics
            self.quality_metrics = self.generate_audit_metrics(source_data, transformed_data)

            total_time = elapsed_seconds(start_time)
            self.logger.info(f"Completed batch transformation for batch {batch_id} in {total_time:.2f}s")
            self._log_performance_summary()

            return transformed_data

        except Exception as e:
            self.logger.error(f"Error in batch transformation: {e}")
            raise

    def transform_incremental(
        self, source_data: dict[str, pd.DataFrame], target_data: dict[str, pd.DataFrame]
    ) -> dict[str, pd.DataFrame]:
        """Transform incremental data updates.

        Args:
            source_data: New/changed source data
            target_data: Existing target data for comparison

        Returns:
            Dictionary of incremental updates to apply
        """
        self.logger.info("Starting incremental transformation")

        try:
            incremental_updates = {}

            # Process dimensions first for SCD Type 2 handling
            for table_name, new_data in source_data.items():
                if table_name.startswith("Dim"):
                    existing_data = target_data.get(table_name, pd.DataFrame())

                    # Create dimension transformation with existing data
                    dim_type = table_name.lower().replace("dim", "")
                    dim_transformer = DimensionTransformation(
                        dimension_type=dim_type, scd_type=2, existing_data=existing_data
                    )

                    incremental_updates[table_name] = dim_transformer.apply(new_data)

                    # Configure dimension data cache
                    self.dimension_data[dim_type] = incremental_updates[table_name]

            # Process fact tables with updated dimension lookups
            for table_name, new_data in source_data.items():
                if table_name.startswith("Fact"):
                    fact_type = table_name.lower().replace("fact", "")
                    fact_transformer = FactTransformation(fact_type=fact_type, dimension_lookups=self.dimension_data)

                    incremental_updates[table_name] = fact_transformer.apply(new_data)

            self.logger.info("Completed incremental transformation")
            return incremental_updates

        except Exception as e:
            self.logger.error(f"Error in incremental transformation: {e}")
            raise

    def apply_data_quality_rules(self, data: pd.DataFrame, table_name: str) -> pd.DataFrame:
        """Apply data quality transformations.

        Args:
            data: Input dataframe
            table_name: Name of the target table

        Returns:
            Data with quality rules applied
        """
        if data.empty:
            return data

        result = data.copy()
        quality_issues = []

        try:
            # Apply table-specific data quality rules
            if table_name == "DimCustomer":
                result = self._apply_customer_quality_rules(result, quality_issues)
            elif table_name == "DimSecurity":
                result = self._apply_security_quality_rules(result, quality_issues)
            elif table_name == "FactTrade":
                result = self._apply_trade_quality_rules(result, quality_issues)

            # Apply general quality rules
            result = self._apply_general_quality_rules(result, table_name, quality_issues)

            # Store quality metrics
            if table_name not in self.quality_metrics:
                self.quality_metrics[table_name] = {}
            self.quality_metrics[table_name]["quality_issues"] = quality_issues
            self.quality_metrics[table_name]["records_processed"] = len(data)
            self.quality_metrics[table_name]["records_valid"] = len(result)

            return result

        except Exception as e:
            self.logger.error(f"Error applying data quality rules to {table_name}: {e}")
            return data

    def generate_audit_metrics(
        self,
        source_data: dict[str, pd.DataFrame],
        transformed_data: dict[str, pd.DataFrame],
    ) -> dict[str, Any]:
        """Generate audit metrics for transformation process.

        Args:
            source_data: Original source data
            transformed_data: Transformed data

        Returns:
            Dictionary of audit metrics and statistics
        """
        audit_metrics: dict[str, Any] = {
            "batch_id": self.batch_id,
            "transformation_timestamp": datetime.now().isoformat(),
            "tables_processed": [],
            "record_counts": {},
            "data_quality_summary": {},
            "transformation_summary": {},
        }

        try:
            for table_name in source_data:
                # Record counts
                source_count = len(source_data[table_name])
                target_count = len(transformed_data.get(table_name, pd.DataFrame()))

                audit_metrics["record_counts"][table_name] = {
                    "source_records": source_count,
                    "target_records": target_count,
                    "record_change": target_count - source_count,
                }

                audit_metrics["tables_processed"].append(table_name)

            # Data quality summary
            total_issues = 0
            for table_name, metrics in self.quality_metrics.items():
                if "quality_issues" in metrics:
                    issue_count = len(metrics["quality_issues"])
                    total_issues += issue_count
                    audit_metrics["data_quality_summary"][table_name] = {
                        "issues_found": issue_count,
                        "issues": metrics["quality_issues"],
                    }

            audit_metrics["data_quality_summary"]["total_issues"] = total_issues

            # Transformation summary
            audit_metrics["transformation_summary"] = {
                "rules_applied": len(self.transformation_rules),
                "scale_factor": self.scale_factor,
                "processing_order": self._get_processing_order(),
            }

            return audit_metrics

        except Exception as e:
            self.logger.error(f"Error generating audit metrics: {e}")
            return audit_metrics

    def _configure_performance_settings(self) -> None:
        """Configure performance settings based on scale factor and system resources."""
        # Adjust chunk size based on scale factor
        if self.scale_factor >= 10.0:
            self.chunk_size = min(50000, self.chunk_size * 5)
        elif self.scale_factor >= 5.0:
            self.chunk_size = min(25000, self.chunk_size * 2)

        # Adjust memory limit based on available system memory
        available_memory_gb = psutil.virtual_memory().available / (1024**3)
        if available_memory_gb < 4:
            self.chunk_size = min(5000, self.chunk_size)
            self.max_workers = min(2, self.max_workers)

        self.logger.info(
            f"Performance configuration: chunk_size={self.chunk_size}, workers={self.max_workers}, memory_limit={self.memory_limit_gb:.1f}GB"
        )

    def _analyze_dataset_sizes(self, source_data: dict[str, pd.DataFrame]) -> None:
        """Analyze dataset sizes to optimize processing strategy."""
        total_rows = sum(len(df) for df in source_data.values())
        total_memory_mb = sum(df.memory_usage(deep=True).sum() for df in source_data.values()) / 1024**2

        self.logger.info(f"Dataset analysis: {total_rows:,} total rows, {total_memory_mb:.1f}MB memory usage")

        # Adjust processing strategy based on data size
        if total_memory_mb > self.memory_limit_gb * 1024 * 0.5:  # Using more than 50% of memory limit
            self.chunk_size = max(1000, self.chunk_size // 2)
            self.logger.info(f"Large dataset detected, reducing chunk size to {self.chunk_size}")

    def _transform_table_parallel(self, data: pd.DataFrame, table_name: str, batch_id: int) -> pd.DataFrame:
        """Transform large table using parallel processing."""
        self.logger.info(f"  Using parallel processing for {table_name}")

        # Split data into chunks for parallel processing
        chunks = [data.iloc[i : i + self.chunk_size] for i in range(0, len(data), self.chunk_size)]

        # Use ThreadPoolExecutor for all operations (simplified approach)
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit transformation tasks
            futures = []
            for i, chunk in enumerate(chunks):
                future = executor.submit(self._transform_chunk_wrapper, chunk, table_name, batch_id, i)
                futures.append(future)

            # Collect results
            transformed_chunks = []
            for future in as_completed(futures):
                try:
                    result = future.result()
                    transformed_chunks.append(result)
                except Exception as e:
                    self.logger.error(f"Error in parallel chunk processing: {e}")
                    raise

        # Combine results
        if transformed_chunks:
            result = pd.concat(transformed_chunks, ignore_index=True)
            self.logger.info(f"  Parallel processing completed: {len(result):,} rows")
            return result
        else:
            return pd.DataFrame()

    def _transform_table_chunked(self, data: pd.DataFrame, table_name: str, batch_id: int) -> pd.DataFrame:
        """Transform large table using chunked processing to manage memory."""
        self.logger.info(f"  Using chunked processing for {table_name}")

        transformed_chunks = []
        total_chunks = (len(data) // self.chunk_size) + 1

        for i in range(0, len(data), self.chunk_size):
            chunk = data.iloc[i : i + self.chunk_size]
            chunk_num = (i // self.chunk_size) + 1

            if chunk_num % max(1, total_chunks // 10) == 0:  # Log every 10%
                progress = (chunk_num / total_chunks) * 100
                self.logger.info(f"    Processing chunk {chunk_num}/{total_chunks} ({progress:.1f}%)")

            # Transform chunk
            transformed_chunk = self._transform_chunk(chunk, table_name, batch_id)
            transformed_chunks.append(transformed_chunk)

            # Memory management
            if chunk_num % 10 == 0:  # Check memory every 10 chunks
                self._manage_memory()

        # Combine results
        if transformed_chunks:
            result = pd.concat(transformed_chunks, ignore_index=True)
            self.logger.info(f"  Chunked processing completed: {len(result):,} rows")
            return result
        else:
            return pd.DataFrame()

    def _transform_single_table(self, data: pd.DataFrame, table_name: str, batch_id: int) -> pd.DataFrame:
        """Transform table using standard processing."""
        # Transform based on table type
        if table_name.startswith("Dim"):
            return self._transform_dimension_table(data, table_name, batch_id)
        elif table_name.startswith("Fact"):
            return self._transform_fact_table(data, table_name, batch_id)
        else:
            return self._apply_general_transformations(data, table_name, batch_id)

    def _transform_chunk_wrapper(
        self, chunk: pd.DataFrame, table_name: str, batch_id: int, chunk_index: int
    ) -> pd.DataFrame:
        """Wrapper for chunk transformation that can be pickled for multiprocessing."""
        try:
            # Apply data quality rules first
            cleaned_chunk = self.apply_data_quality_rules(chunk, table_name)

            # Transform chunk
            return self._transform_chunk(cleaned_chunk, table_name, batch_id)
        except Exception as e:
            logger.error(f"Error transforming chunk {chunk_index} for {table_name}: {e}")
            raise

    def _transform_chunk(self, chunk: pd.DataFrame, table_name: str, batch_id: int) -> pd.DataFrame:
        """Transform a single chunk of data."""
        if table_name.startswith("Dim"):
            return self._transform_dimension_table(chunk, table_name, batch_id)
        elif table_name.startswith("Fact"):
            return self._transform_fact_table(chunk, table_name, batch_id)
        else:
            return self._apply_general_transformations(chunk, table_name, batch_id)

    def _manage_memory(self) -> None:
        """Monitor and manage memory usage."""
        memory_percent = psutil.virtual_memory().percent
        self.performance_stats["memory_usage_peaks"].append(memory_percent)

        if memory_percent > 85:  # High memory usage
            self.logger.warning(f"High memory usage detected: {memory_percent:.1f}%")
            # Force garbage collection
            gc.collect()
            # Clear lookup cache if needed
            if len(self._lookup_cache) > self._cache_max_size // 2:
                self._lookup_cache.clear()
                self.logger.info("Cleared lookup cache to free memory")

    def _log_performance_summary(self) -> None:
        """Log performance summary statistics."""
        stats = self.performance_stats
        self.logger.info("Performance Summary:")
        self.logger.info(f"  Chunks processed: {stats['chunks_processed']}")
        self.logger.info(f"  Vectorized operations: {stats['vectorized_operations']}")
        self.logger.info(f"  Parallel operations: {stats['parallel_operations']}")
        self.logger.info(f"  Cache hits/misses: {stats['cache_hits']}/{stats['cache_misses']}")

        if stats["memory_usage_peaks"]:
            avg_memory = sum(stats["memory_usage_peaks"]) / len(stats["memory_usage_peaks"])
            max_memory = max(stats["memory_usage_peaks"])
            self.logger.info(f"  Memory usage - avg: {avg_memory:.1f}%, peak: {max_memory:.1f}%")

        if stats["processing_times"]:
            self.logger.info("  Table processing times:")
            for table, time_taken in stats["processing_times"].items():
                self.logger.info(f"    {table}: {time_taken:.2f}s")

    def get_performance_config(self) -> dict[str, Any]:
        """Get current performance configuration."""
        return {
            "scale_factor": self.scale_factor,
            "chunk_size": self.chunk_size,
            "max_workers": self.max_workers,
            "enable_parallel": self.enable_parallel,
            "memory_limit_gb": self.memory_limit_gb,
            "vectorize_threshold": VECTORIZE_THRESHOLD,
            "parallel_threshold": PARALLEL_THRESHOLD,
            "memory_threshold": MEMORY_THRESHOLD,
            "performance_stats": self.performance_stats,
        }

    def optimize_for_scale_factor(self, scale_factor: float) -> None:
        """Optimize configuration for a specific scale factor."""
        self.scale_factor = scale_factor
        self._configure_performance_settings()

        # Clear caches and reset stats
        self._lookup_cache.clear()
        self.performance_stats: dict[str, Any] = {
            "chunks_processed": 0,
            "vectorized_operations": 0,
            "parallel_operations": 0,
            "memory_usage_peaks": [],
            "processing_times": {},
            "cache_hits": 0,
            "cache_misses": 0,
        }

        self.logger.info(f"Optimized configuration for scale factor {scale_factor}")

    def _get_processing_order(self) -> list[str]:
        """Get the correct processing order based on table dependencies."""
        # Topological sort of table dependencies
        order = []
        remaining = set(self.table_dependencies.keys())

        while remaining:
            # Find tables with no remaining dependencies
            ready = [table for table in remaining if all(dep in order for dep in self.table_dependencies[table])]

            if not ready:
                # Handle circular dependencies by processing remaining tables
                ready = list(remaining)

            # Sort ready tables (dimensions first, then facts)
            ready.sort(key=lambda x: (x.startswith("Fact"), x))

            order.extend(ready)
            remaining -= set(ready)

        return order

    def _transform_dimension_table(self, data: pd.DataFrame, table_name: str, batch_id: int) -> pd.DataFrame:
        """Transform a dimension table."""
        dim_type = table_name.lower().replace("dim", "")

        # Create dimension transformer
        transformer = DimensionTransformation(
            dimension_type=dim_type,
            scd_type=2,
            existing_data=self.dimension_data.get(dim_type),
        )

        return transformer.create_dimension_with_metadata(data, batch_id)

    def _transform_fact_table(self, data: pd.DataFrame, table_name: str, batch_id: int) -> pd.DataFrame:
        """Transform a fact table."""
        fact_type = table_name.lower().replace("fact", "")

        # Create fact transformer with dimension lookups
        transformer = FactTransformation(fact_type=fact_type, dimension_lookups=self.dimension_data)

        return transformer.create_fact_with_metadata(data, batch_id)

    def _apply_general_transformations(self, data: pd.DataFrame, table_name: str, batch_id: int) -> pd.DataFrame:
        """Apply general transformations to any table."""
        result = data.copy()

        # Add batch ID if not present
        if "BatchID" not in result.columns:
            result["BatchID"] = batch_id

        # Apply any registered transformation rules
        for rule in self.transformation_rules:
            result = rule.apply(result)

        return result

    def _apply_customer_quality_rules(self, data: pd.DataFrame, quality_issues: list[str]) -> pd.DataFrame:
        """Apply customer-specific data quality rules."""
        result = data.copy()

        # Check required fields
        required_fields = ["CustomerID", "LastName", "FirstName"]
        for field in required_fields:
            if field in result.columns:
                null_mask = result[field].isna() | (result[field] == "")
                if null_mask.any():
                    quality_issues.append(f"Missing {field} in {null_mask.sum()} records")
                    # Remove records with missing required fields
                    result = result[~null_mask]

        # Validate email format
        if "Email1" in result.columns:
            email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
            invalid_emails = ~result["Email1"].apply(
                lambda x: bool(email_pattern.match(str(x))) if pd.notna(x) and x != "" else True
            )
            if invalid_emails.any():
                quality_issues.append(f"Invalid email format in {invalid_emails.sum()} records")

        return result

    def _apply_security_quality_rules(self, data: pd.DataFrame, quality_issues: list[str]) -> pd.DataFrame:
        """Apply security-specific data quality rules."""
        result = data.copy()

        # Check required fields
        if "Symbol" in result.columns:
            null_symbols = result["Symbol"].isna() | (result["Symbol"] == "")
            if null_symbols.any():
                quality_issues.append(f"Missing Symbol in {null_symbols.sum()} records")
                result = result[~null_symbols]

        # Validate share count is positive
        if "SharesOutstanding" in result.columns:
            negative_shares = result["SharesOutstanding"] <= 0
            if negative_shares.any():
                quality_issues.append(f"Non-positive SharesOutstanding in {negative_shares.sum()} records")
                result.loc[negative_shares, "SharesOutstanding"] = 1  # Set to minimum valid value

        return result

    def _apply_trade_quality_rules(self, data: pd.DataFrame, quality_issues: list[str]) -> pd.DataFrame:
        """Apply trade-specific data quality rules."""
        result = data.copy()

        # Check for negative quantities
        if "Quantity" in result.columns:
            negative_qty = result["Quantity"] <= 0
            if negative_qty.any():
                quality_issues.append(f"Non-positive Quantity in {negative_qty.sum()} records")
                result = result[~negative_qty]  # Exclude invalid trades
        # Check for negative prices
        if "TradePrice" in result.columns:
            negative_price = result["TradePrice"] <= 0
            if negative_price.any():
                quality_issues.append(f"Non-positive TradePrice in {negative_price.sum()} records")
                result = result[~negative_price]  # Exclude invalid trades
        return result

    def _apply_general_quality_rules(
        self, data: pd.DataFrame, table_name: str, quality_issues: list[str]
    ) -> pd.DataFrame:
        """Apply general data quality rules to any table."""
        result = data.copy()

        # Check for completely empty rows
        empty_rows = result.isna().all(axis=1)
        if empty_rows.any():
            quality_issues.append(f"Removed {empty_rows.sum()} completely empty rows")
            result = result[~empty_rows]

        # Check for duplicate records (if natural key exists)
        if table_name == "DimCustomer" and "CustomerID" in result.columns:
            duplicates = result.duplicated(subset=["CustomerID"])
            if duplicates.any():
                quality_issues.append(f"Found {duplicates.sum()} duplicate CustomerID records")
                result = result[~duplicates]

        return result

    def transform_batch_streaming(
        self,
        source_data_chunks: dict[str, Iterator[pd.DataFrame]],
        batch_id: int,
        memory_limit_mb: Optional[int] = None,
        progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> Iterator[tuple[str, pd.DataFrame]]:
        """Transform a complete batch of source data in streaming mode.

        Args:
            source_data_chunks: Dictionary of iterators yielding dataframe chunks keyed by table name
            batch_id: Unique identifier for the batch
            memory_limit_mb: Maximum memory usage in MB
            progress_callback: Function to call with progress updates

        Yields:
            Tuples of (table_name, transformed_chunk) ready for loading
        """
        self.batch_id = batch_id
        self.logger.info(f"Starting streaming batch transformation for batch {batch_id}")

        # Initialize streaming processor
        chunk_processor = StreamingChunkProcessor(memory_limit_mb)

        try:
            # Process tables in dependency order
            processing_order = self._get_processing_order()

            # Process streaming data for each table
            for table_name in processing_order:
                if table_name not in source_data_chunks:
                    continue

                self.logger.info(f"Streaming transformation for table: {table_name}")
                chunk_iterator = source_data_chunks[table_name]
                chunk_number = 0

                for chunk in chunk_iterator:
                    chunk_number += 1

                    # Apply data quality rules first
                    cleaned_chunk = self.apply_data_quality_rules(chunk, table_name)

                    # Transform based on table type
                    if table_name.startswith("Dim"):
                        transformed_chunk = self._transform_dimension_chunk_streaming(
                            cleaned_chunk, table_name, batch_id
                        )
                    elif table_name.startswith("Fact"):
                        transformed_chunk = self._transform_fact_chunk_streaming(cleaned_chunk, table_name, batch_id)
                    else:
                        # Apply general transformations
                        transformed_chunk = self._apply_general_transformations(cleaned_chunk, table_name, batch_id)

                    # Store dimension data for foreign key resolution (for dimensions only)
                    if table_name.startswith("Dim"):
                        dim_type = table_name.lower().replace("dim", "")
                        # For streaming, we maintain a running cache (memory permitting)
                        if dim_type not in self.dimension_data:
                            self.dimension_data[dim_type] = transformed_chunk
                        else:
                            # Append to existing dimension data (may need optimization for very large dimensions)
                            self.dimension_data[dim_type] = pd.concat(
                                [self.dimension_data[dim_type], transformed_chunk],
                                ignore_index=True,
                            )

                    # Call progress callback if provided
                    if progress_callback:
                        progress_info = {
                            "table_name": table_name,
                            "chunk_number": chunk_number,
                            "chunk_size": len(transformed_chunk),
                            "memory_stats": chunk_processor.get_performance_stats(),
                        }
                        progress_callback(progress_info)

                    yield table_name, transformed_chunk

                    # Force cleanup after each chunk
                    chunk_processor.force_gc()

            # Generate final audit metrics
            self.quality_metrics = {"streaming_stats": chunk_processor.get_performance_stats()}

            self.logger.info(f"Completed streaming batch transformation for batch {batch_id}")

        except Exception as e:
            self.logger.error(f"Error in streaming batch transformation: {e}")
            raise

    def _transform_dimension_chunk_streaming(self, chunk: pd.DataFrame, table_name: str, batch_id: int) -> pd.DataFrame:
        """Transform a dimension table chunk in streaming mode."""
        if chunk.empty:
            return chunk

        dim_type = table_name.lower().replace("dim", "")

        # For streaming SCD processing, we need to check against existing dimension cache
        if dim_type in self.dimension_data and not self.dimension_data[dim_type].empty:
            # Use streaming SCD processor for Type 2 handling
            natural_keys = self._get_natural_keys_for_dimension(dim_type)
            tracked_attributes = self._get_tracked_attributes_for_dimension(dim_type)

            scd_processor = StreamingSCDProcessor(dim_type, natural_keys, tracked_attributes)
            transformed_chunk, scd_stats = scd_processor.process_chunk_scd2(chunk, batch_id)

            self.logger.debug(f"SCD processing for {table_name}: {scd_stats}")
        else:
            # Create standard dimension transformer for initial load
            transformer = DimensionTransformation(dimension_type=dim_type, scd_type=2, existing_data=None)
            transformed_chunk = transformer.create_dimension_with_metadata(chunk, batch_id)

        return transformed_chunk

    def _transform_fact_chunk_streaming(self, chunk: pd.DataFrame, table_name: str, batch_id: int) -> pd.DataFrame:
        """Transform a fact table chunk in streaming mode."""
        if chunk.empty:
            return chunk

        fact_type = table_name.lower().replace("fact", "")

        # Create fact transformer with available dimension lookups
        transformer = FactTransformation(fact_type=fact_type, dimension_lookups=self.dimension_data)

        return transformer.create_fact_with_metadata(chunk, batch_id)

    def _get_natural_keys_for_dimension(self, dim_type: str) -> list[str]:
        """Get natural key columns for a dimension type."""
        natural_keys_map = {
            "customer": ["CustomerID"],
            "account": ["AccountID"],
            "security": ["Symbol"],
            "company": ["CompanyID"],
            "broker": ["BrokerID"],
            "date": ["DateValue"],
            "time": ["TimeValue"],
        }
        return natural_keys_map.get(dim_type, ["ID"])

    def _get_tracked_attributes_for_dimension(self, dim_type: str) -> list[str]:
        """Get SCD Type 2 tracked attributes for a dimension type."""
        tracked_attributes_map = {
            "customer": [
                "Status",
                "LastName",
                "FirstName",
                "AddressLine1",
                "AddressLine2",
                "PostalCode",
                "City",
                "StateProv",
                "Phone1",
                "Phone2",
                "Phone3",
                "Email1",
                "Email2",
                "CreditRating",
                "NetWorth",
                "Tier",
            ],
            "account": ["Status", "AccountDesc", "TaxStatus"],
            "security": ["Status", "Name", "SharesOutstanding", "Dividend"],
            "company": [
                "Status",
                "Name",
                "Industry",
                "SPrating",
                "CEO",
                "AddressLine1",
                "AddressLine2",
                "PostalCode",
                "City",
                "StateProv",
                "Description",
            ],
        }
        return tracked_attributes_map.get(dim_type, [])

    def transform_batch_parallel(self, source_data: dict[str, pd.DataFrame], batch_id: int) -> dict[str, pd.DataFrame]:
        """Transform batch using parallel processing capabilities."""
        if not self.parallel_enabled:
            return self.transform_batch(source_data, batch_id)

        self.logger.info(f"Starting parallel batch transformation with {self.parallel_config.max_workers} workers")

        start_time = mono_time()

        # Separate tables by type for parallel processing strategy
        dimension_tables = {k: v for k, v in source_data.items() if k.startswith("Dim")}
        fact_tables = {k: v for k, v in source_data.items() if k.startswith("Fact")}
        other_tables = {k: v for k, v in source_data.items() if not (k.startswith(("Dim", "Fact")))}

        transformed_data = {}

        # Process dimensions first with parallel processing
        if dimension_tables and self.parallel_config.enable_parallel_dimensions:
            dimension_results = self._process_dimensions_parallel(dimension_tables, batch_id)
            transformed_data.update(dimension_results)

            # Configure dimension data cache for foreign key resolution
            for table_name, df in dimension_results.items():
                dim_type = table_name.lower().replace("dim", "")
                self.dimension_data[dim_type] = df

        # Process fact tables with parallel processing
        if fact_tables and self.parallel_config.enable_parallel_facts:
            fact_results = self._process_facts_parallel(fact_tables, batch_id)
            transformed_data.update(fact_results)

        # Process other tables sequentially
        for table_name, df in other_tables.items():
            transformed_data[table_name] = self._apply_general_transformations(df, table_name, batch_id)

        # Calculate processing efficiency
        total_time = elapsed_seconds(start_time)
        total_records = sum(len(df) for df in source_data.values())
        if total_records > 0:
            efficiency = total_records / total_time if total_time > 0 else 0
            self.parallel_context.add_metric("parallel_efficiency", efficiency)

        self.logger.info(f"Enhanced parallel batch transformation completed in {total_time:.2f}s")
        return transformed_data

    def _process_dimensions_parallel(
        self, dimension_tables: dict[str, pd.DataFrame], batch_id: int
    ) -> dict[str, pd.DataFrame]:
        """Process dimension tables using parallel processing."""
        if not dimension_tables:
            return {}

        self.logger.info(f"Processing {len(dimension_tables)} dimension tables with parallelism")

        # Group dimensions by dependency level
        dependency_levels = self._get_dimension_dependency_levels(list(dimension_tables.keys()))
        transformed_data = {}

        # Process each dependency level
        for _level, table_names in dependency_levels.items():
            if not table_names:
                continue

            level_tables = {name: dimension_tables[name] for name in table_names if name in dimension_tables}

            if len(level_tables) == 1:
                # Single table, process directly
                table_name = list(level_tables.keys())[0]
                df = list(level_tables.values())[0]
                transformed_data[table_name] = self._transform_dimension_table_enhanced(df, table_name, batch_id)
            else:
                # Multiple tables, process in parallel
                level_results = self._process_dimension_tables_parallel(level_tables, batch_id)
                transformed_data.update(level_results)

            # Configure dimension data cache for next level
            for table_name, df in transformed_data.items():
                if table_name.startswith("Dim"):
                    dim_type = table_name.lower().replace("dim", "")
                    self.dimension_data[dim_type] = df

        return transformed_data

    def _process_facts_parallel(self, fact_tables: dict[str, pd.DataFrame], batch_id: int) -> dict[str, pd.DataFrame]:
        """Process fact tables using parallel processing."""
        if not fact_tables:
            return {}

        self.logger.info(f"Processing {len(fact_tables)} fact tables with enhanced parallelism")

        # Fact tables can generally be processed independently
        return self._process_fact_tables_parallel(fact_tables, batch_id)

    def _process_dimension_tables_parallel(
        self, tables: dict[str, pd.DataFrame], batch_id: int
    ) -> dict[str, pd.DataFrame]:
        """Process multiple dimension tables in parallel."""
        if not tables or not self.enhanced_thread_pool:
            return self._process_tables_sequential(tables, batch_id, "dimension")

        results = {}
        futures = {}
        worker_id_counter = 0

        # Submit dimension transformation tasks
        for table_name, df in tables.items():
            worker_id = f"dim_worker_{worker_id_counter}"
            worker_id_counter += 1

            self.parallel_context.add_worker(worker_id)

            future = self.enhanced_thread_pool.submit(
                self._transform_dimension_table_enhanced_worker,
                table_name,
                df,
                batch_id,
                worker_id,
            )

            futures[future] = (table_name, worker_id)

        # Collect results
        for future in as_completed(futures, timeout=self.parallel_config.worker_timeout):
            table_name, worker_id = futures[future]
            self.parallel_context.remove_worker(worker_id)

            try:
                result = future.result()
                if result["success"]:
                    results[table_name] = result["data"]
                    self.parallel_context.add_metric("dimension_processing_times", result["processing_time"])
                    self.parallel_context.increment_completed_chunks(result.get("records_processed", 0))
                    self.logger.info(f"Completed dimension {table_name} in {result['processing_time']:.2f}s")
                else:
                    error_msg = f"Failed to transform dimension {table_name}: {result.get('error', 'Unknown error')}"
                    self.parallel_context.increment_failed_chunks()
                    self.logger.error(error_msg)
                    raise RuntimeError(error_msg)
            except Exception as e:
                self.parallel_context.increment_failed_chunks()
                error_msg = f"Exception transforming dimension {table_name}: {str(e)}"
                self.logger.error(error_msg)
                raise RuntimeError(error_msg)

        return results

    def _transform_dimension_table_enhanced_worker(
        self, table_name: str, df: pd.DataFrame, batch_id: int, worker_id: str
    ) -> dict[str, Any]:
        """Transform a dimension table in an enhanced worker."""
        start_time = mono_time()

        try:
            self.logger.debug(f"Worker {worker_id} processing dimension {table_name}")

            # Transform dimension with SCD processing
            transformed_data = self._transform_dimension_table_enhanced(df, table_name, batch_id)

            processing_time = elapsed_seconds(start_time)

            return {
                "success": True,
                "data": transformed_data,
                "processing_time": processing_time,
                "records_processed": len(transformed_data),
                "worker_id": worker_id,
            }

        except Exception as e:
            processing_time = elapsed_seconds(start_time)
            self.logger.error(f"Worker {worker_id} failed processing dimension {table_name}: {str(e)}")

            return {
                "success": False,
                "error": str(e),
                "processing_time": processing_time,
                "worker_id": worker_id,
            }

    def _transform_dimension_table_enhanced(self, data: pd.DataFrame, table_name: str, batch_id: int) -> pd.DataFrame:
        """Enhanced dimension table transformation with advanced SCD processing."""
        # Apply data quality rules first
        cleaned_data = self.apply_data_quality_rules(data, table_name)

        # Apply standard dimension transformation
        result = self._transform_dimension_table(cleaned_data, table_name, batch_id)

        return result

    def get_parallel_metrics(self) -> dict[str, Any]:
        """Get parallel processing performance metrics."""
        if not self.parallel_enabled:
            return {"error": "Parallel processing not enabled"}

        return self.parallel_context.get_performance_report()

    # Removed complex worker pool management - now using context managers

    def __enter__(self) -> "TransformationEngine":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit with cleanup."""
        # Worker pools are now managed by context managers - no manual cleanup needed
