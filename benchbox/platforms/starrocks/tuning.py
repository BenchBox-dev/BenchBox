from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from benchbox.platforms.base.tuning import make_informational_constraint_applier, supports_named_tuning_type

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        UnifiedTuningConfiguration,
    )

_VALID_SETTING_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class StarRocksTuningMixin:
    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        cursor = connection.cursor()
        try:
            try:
                cursor.execute(f"SET query_timeout = {int(self.max_execution_time)}")
            except Exception as e:
                self.logger.debug(f"Could not set query_timeout: {e}")

            if self.disable_result_cache:
                try:
                    cursor.execute("SET enable_query_cache = false")
                except Exception as e:
                    self.logger.debug(f"Could not disable query cache: {e}")

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
        if not platform_config:
            return

        cursor = connection.cursor()

        try:
            if hasattr(platform_config, "additional_settings") and platform_config.additional_settings:
                for setting, value in platform_config.additional_settings.items():
                    if not _VALID_SETTING_PATTERN.match(setting):
                        self.logger.warning(f"Skipping invalid setting name: {setting!r}")
                        continue
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
        return supports_named_tuning_type(tuning_type, self._supported_tuning_type_names)

    def apply_table_tunings(self, table_tuning, connection: Any) -> None:
        if not table_tuning or not table_tuning.has_any_tuning():
            return

        table_name = table_tuning.table_name
        self.logger.info(f"Applying StarRocks tunings for table: {table_name}")

        try:
            from benchbox.core.tuning.interface import TuningType

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
        from benchbox.platforms.base.tuning_config import apply_standard_unified_tuning

        apply_standard_unified_tuning(self, unified_config, connection)


__all__ = ["StarRocksTuningMixin"]
