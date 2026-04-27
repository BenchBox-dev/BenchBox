"""Tuning utilities for StarRocks."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        ForeignKeyConfiguration,
        PlatformOptimizationConfiguration,
        PrimaryKeyConfiguration,
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

    def apply_constraint_configuration(
        self,
        primary_key_config: PrimaryKeyConfiguration,
        foreign_key_config: ForeignKeyConfiguration,
        connection: Any,
    ) -> None:
        """Apply constraint configurations to StarRocks.

        StarRocks uses data model keys (DUPLICATE/AGGREGATE/UNIQUE/PRIMARY)
        defined at table creation time. This method logs the configuration
        since constraints are applied during CREATE TABLE.
        """
        if primary_key_config and primary_key_config.enabled:
            self.logger.info("Primary key constraints enabled (applied during table creation)")

        if foreign_key_config and foreign_key_config.enabled:
            self.logger.info("Foreign key constraints noted (StarRocks does not enforce foreign keys)")

    def supports_tuning_type(self, tuning_type) -> bool:
        """Check if StarRocks supports a specific tuning type."""
        try:
            from benchbox.core.tuning.interface import TuningType

            return tuning_type in {
                TuningType.PARTITIONING,
                TuningType.SORTING,
                TuningType.DISTRIBUTION,
            }
        except ImportError:
            return False

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
        if not unified_config:
            return

        self.apply_constraint_configuration(unified_config.primary_keys, unified_config.foreign_keys, connection)

        if unified_config.platform_optimizations:
            self.apply_platform_optimizations(unified_config.platform_optimizations, connection)

        for _table_name, table_tuning in unified_config.table_tunings.items():
            self.apply_table_tunings(table_tuning, connection)


__all__ = ["StarRocksTuningMixin"]
