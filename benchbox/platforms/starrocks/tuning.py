"""Tuning utilities for StarRocks."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from benchbox.platforms.base.tuning import make_informational_constraint_applier, supports_named_tuning_type

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        UnifiedTuningConfiguration,
    )

# Whitelist pattern for StarRocks SET variable names
_VALID_SETTING_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class StarRocksTuningMixin:
    """Implement tuning primitives for StarRocks."""

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply StarRocks-specific optimizations based on benchmark type."""
        cursor = connection.cursor()
        try:
            # Set query timeout
            try:
                cursor.execute(f"SET query_timeout = {int(self.max_execution_time)}")
            except Exception as e:
                self.logger.debug(f"Could not set query_timeout: {e}")

            # Disable SQL cache for accurate benchmarking
            if self.disable_result_cache:
                try:
                    cursor.execute("SET enable_query_cache = false")
                except Exception as e:
                    self.logger.debug(f"Could not disable query cache: {e}")

            # OLAP optimizations for analytical workloads
            if benchmark_type.lower() in ["olap", "analytics", "tpch", "tpcds"]:
                olap_settings = {
                    "new_planner_optimize_timeout": 30000,
                    "enable_profile": "false",
                }
                for setting, value in olap_settings.items():
                    try:
                        cursor.execute(f"SET {setting} = {value}")
                        self.logger.debug(f"Set {setting} = {value}")
                    except Exception as e:
                        self.logger.debug(f"Could not set {setting}: {e}")
        finally:
            cursor.close()
        self.logger.info(f"Configured StarRocks for benchmark type: {benchmark_type}")

    def apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None:
        """Apply StarRocks-specific platform optimizations."""
        if not platform_config:
            return

        cursor = connection.cursor()

        try:
            # Apply any generic session-level settings from config
            if hasattr(platform_config, "additional_settings") and platform_config.additional_settings:
                for setting, value in platform_config.additional_settings.items():
                    # Validate setting name to prevent SQL injection
                    if not _VALID_SETTING_PATTERN.match(setting):
                        self.logger.warning(f"Skipping invalid setting name: {setting!r}")
                        continue
                    # Validate value: allow int, float, bool, or simple string tokens
                    str_value = str(value)
                    if not re.match(r"^[a-zA-Z0-9_.+-]+$", str_value):
                        self.logger.warning(f"Skipping setting {setting} with unsafe value: {str_value!r}")
                        continue
                    try:
                        cursor.execute(f"SET {setting} = {str_value}")
                        self.logger.info(f"Set {setting} = {str_value}")
                    except Exception as e:
                        self.logger.warning(f"Failed to set {setting}: {e}")
        except Exception as e:
            self.logger.error(f"Failed to apply StarRocks platform optimizations: {e}")
        finally:
            cursor.close()

    apply_constraint_configuration = make_informational_constraint_applier(
        "Primary key constraints enabled (applied during table creation)",
        "Foreign key constraints noted (StarRocks does not enforce foreign keys)",
    )

    _supported_tuning_type_names = ("PARTITIONING", "SORTING", "DISTRIBUTION")

    def supports_tuning_type(self, tuning_type) -> bool:
        """Check if StarRocks supports a specific tuning type."""
        return supports_named_tuning_type(tuning_type, self._supported_tuning_type_names)

    def apply_table_tunings(self, table_tuning, connection: Any) -> None:
        """Apply StarRocks-specific table tunings.

        StarRocks tuning is primarily done at table creation time:
        - PARTITIONING: Via PARTITION BY clause
        - SORTING: Via ORDER BY in data model keys
        - DISTRIBUTION: Via DISTRIBUTED BY HASH clause
        """
        if not table_tuning or not table_tuning.has_any_tuning():
            return

        table_name = table_tuning.table_name
        self.logger.info(f"Applying StarRocks tunings for table: {table_name}")

        try:
            from benchbox.core.tuning.interface import TuningType

            # Log tuning strategies (most must be defined at CREATE TABLE time)
            partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
            if partition_columns:
                sorted_cols = sorted(partition_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]
                self.logger.info(f"Partitioning for {table_name}: {', '.join(column_names)} (defined at CREATE TABLE)")

            sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
            if sort_columns:
                sorted_cols = sorted(sort_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]
                self.logger.info(f"Sort key for {table_name}: {', '.join(column_names)} (defined at CREATE TABLE)")

            distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
            if distribution_columns:
                sorted_cols = sorted(distribution_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]
                self.logger.info(f"Distribution for {table_name}: {', '.join(column_names)} (defined at CREATE TABLE)")

        except ImportError:
            self.logger.warning("Tuning interface not available - skipping tuning application")
        except Exception as e:
            raise ValueError(f"Failed to apply tunings to StarRocks table {table_name}: {e}") from e

    def apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None:
        """Apply unified tuning configuration to StarRocks."""
        from benchbox.platforms.base.tuning_config import apply_standard_unified_tuning

        apply_standard_unified_tuning(self, unified_config, connection)


__all__ = ["StarRocksTuningMixin"]
