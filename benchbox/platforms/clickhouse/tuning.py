"""Tuning utilities for ClickHouse."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from benchbox.core.exceptions import ConfigurationError
from benchbox.platforms.base.tuning import make_informational_constraint_applier, supports_named_tuning_type

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        UnifiedTuningConfiguration,
    )


class ClickHouseTuningMixin:
    """Implement tuning primitives for ClickHouse."""

    def get_effective_tuning_configuration(
        self,
    ) -> UnifiedTuningConfiguration | None:
        """Override to create ClickHouse-specific tuning configuration.

        ClickHouse requires primary keys even in no-tuning mode, so we create
        a configuration that reflects ClickHouse's requirements.
        """
        from benchbox.core.tuning.interface import UnifiedTuningConfiguration

        # Get base configuration if it exists
        base_config = super().get_effective_tuning_configuration()
        if base_config:
            # Ensure primary keys are always enabled for ClickHouse
            base_config.primary_keys.enabled = True
            return base_config

        # Create ClickHouse-specific configuration
        config = UnifiedTuningConfiguration()
        config.primary_keys.enabled = True  # Always required for ClickHouse
        config.foreign_keys.enabled = False  # Default for no-tuning mode

        return config

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply ClickHouse-specific optimizations based on benchmark type.

        Respects tuning configuration - if tuning is enabled, only applies basic settings.
        If tuning is disabled, applies OLAP optimizations with local ClickHouse validation.
        """

        # Basic settings that are always safe to apply
        settings = {
            "max_memory_usage": self._parse_memory_setting(self.max_memory_usage),
            "max_execution_time": self.max_execution_time,
            "max_threads": self.max_threads,
            "use_uncompressed_cache": 0,  # DISABLED - causes 20-30x memory bloat for OLAP workloads
            "enable_optimize_predicate_expression": 1,
            # Enable correlated subqueries for TPC-H queries 2, 4, 17, 20, 21, 22
            # Experimental in ClickHouse v25.5.x (chdb 3.6.0), enabled by default in v25.8+
            "allow_experimental_correlated_subqueries": 1,
        }

        # Apply cache control settings for accurate benchmarking
        if self.disable_result_cache:
            settings.update(
                {
                    "use_query_cache": 0,
                    "enable_writes_to_query_cache": 0,
                    "enable_reads_from_query_cache": 0,
                }
            )

        # Only apply OLAP optimizations if tuning is disabled
        if not self.tuning_enabled and benchmark_type.lower() in [
            "olap",
            "analytics",
            "tpch",
            "tpcds",
        ]:
            # OLAP optimizations with local ClickHouse validation
            olap_settings = {
                "max_bytes_in_join": int(
                    self._parse_memory_setting(self.max_memory_usage) * 0.5
                ),  # 50% of memory for JOINs - Q5 multi-table join at SF1 needs 2.72 GiB
                "join_use_nulls": 1,
                "optimize_aggregation_in_order": 1,
                "group_by_two_level_threshold": 100000,
                # Disk spilling for graceful degradation - aggressive thresholds
                "max_bytes_before_external_group_by": int(
                    self._parse_memory_setting(self.max_memory_usage) * 0.5
                ),  # Spill at 50% (reduced from 75%)
                "max_bytes_before_external_sort": int(
                    self._parse_memory_setting(self.max_memory_usage) * 0.5
                ),  # Spill at 50% (reduced from 75%)
                # Memory-efficient JOIN algorithm that spills to disk
                "join_algorithm": "grace_hash",
                "grace_hash_join_initial_buckets": 8,
            }

            settings.update(olap_settings)

        # Apply settings with local ClickHouse validation
        critical_failures = []
        for setting, value in settings.items():
            success = self._apply_setting_with_validation(connection, setting, value)
            # Track if critical cache control settings failed
            if not success and setting in [
                "use_query_cache",
                "enable_writes_to_query_cache",
                "enable_reads_from_query_cache",
            ]:
                critical_failures.append(setting)

        # Validate cache control settings were successfully applied
        if self.disable_result_cache or critical_failures:
            self.logger.debug("Validating cache control settings...")
            validation_result = self.validate_session_cache_control(connection)

            if not validation_result["validated"]:
                self.logger.warning(f"Cache control validation failed: {validation_result.get('errors', [])}")
            else:
                self.logger.info(
                    f"Cache control validated successfully: cache_disabled={validation_result['cache_disabled']}"
                )

    def validate_session_cache_control(self, connection: Any) -> dict[str, Any]:
        """Validate that session-level cache control settings were successfully applied.

        Args:
            connection: Active ClickHouse database connection

        Returns:
            dict with:
                - validated: bool - Whether validation passed
                - cache_disabled: bool - Whether cache is actually disabled
                - settings: dict - Actual session settings
                - warnings: list[str] - Any validation warnings
                - errors: list[str] - Any validation errors

        Raises:
            ConfigurationError: If cache control validation fails and strict_validation=True
        """
        result = {
            "validated": False,
            "cache_disabled": False,
            "settings": {},
            "warnings": [],
            "errors": [],
        }

        try:
            # Query current session settings for cache control
            query = """
                SELECT name, value
                FROM system.settings
                WHERE name IN ('use_query_cache', 'enable_writes_to_query_cache', 'enable_reads_from_query_cache')
                ORDER BY name
            """
            rows = connection.execute(query)

            # Parse results into settings dict
            for row in rows:
                setting_name = row[0]
                setting_value = str(row[1])
                result["settings"][setting_name] = setting_value

            # Determine expected values based on configuration
            expected_cache_value = "0" if self.disable_result_cache else "1"

            # Validate all three cache settings
            cache_settings = ["use_query_cache", "enable_writes_to_query_cache", "enable_reads_from_query_cache"]
            all_validated = True

            for setting_name in cache_settings:
                actual_value = result["settings"].get(setting_name, "unknown")

                if actual_value != expected_cache_value:
                    all_validated = False
                    error_msg = (
                        f"Cache control validation failed for {setting_name}: "
                        f"expected {expected_cache_value}, got {actual_value}"
                    )
                    result["errors"].append(error_msg)
                    self.logger.error(error_msg)

            if all_validated:
                result["validated"] = True
                result["cache_disabled"] = expected_cache_value == "0"
                self.logger.debug(
                    f"Cache control validated: all cache settings={expected_cache_value} (expected {expected_cache_value})"
                )
            else:
                # Raise error if strict validation mode enabled
                if self.strict_validation:
                    raise ConfigurationError(
                        "ClickHouse session cache control validation failed - "
                        "benchmark results may be incorrect due to cached query results",
                        details=result,
                    )

        except Exception as e:
            # If this is our ConfigurationError, re-raise it
            if isinstance(e, ConfigurationError):
                raise

            # Otherwise log validation error
            error_msg = f"Validation query failed: {e}"
            result["errors"].append(error_msg)
            self.logger.error(f"Cache control validation error: {e}")

            # Raise if strict mode and query failed
            if self.strict_validation:
                raise ConfigurationError(
                    "Failed to validate ClickHouse cache control settings",
                    details={"original_error": str(e), "validation_result": result},
                ) from e

        return result

    def _parse_memory_setting(self, memory_str: str) -> int:
        """Parse memory setting string to bytes."""
        if isinstance(memory_str, int):
            return memory_str

        memory_str = memory_str
        if memory_str.endswith("GB"):
            return int(float(memory_str[:-2]) * 1024 * 1024 * 1024)
        elif memory_str.endswith("MB"):
            return int(float(memory_str[:-2]) * 1024 * 1024)
        elif memory_str.endswith("KB"):
            return int(float(memory_str[:-2]) * 1024)
        else:
            return int(memory_str)

    def _apply_setting_with_validation(self, connection: Any, setting: str, value: Any) -> bool:
        """Apply ClickHouse setting with local mode validation.

        Args:
            connection: ClickHouse connection
            setting: Setting name
            value: Setting value

        Returns:
            bool: True if setting was applied successfully, False otherwise
        """
        # Known problematic settings in local ClickHouse
        local_incompatible_settings = {
            "join_algorithm",
            "enable_multiple_joins_emulation",
        }

        # Skip known incompatible settings in local mode
        if self.deployment_mode == "local" and setting in local_incompatible_settings:
            self.logger.debug(f"Skipping {setting} in local mode (known incompatible)")
            return False

        try:
            setting_value = self._format_setting_value(value)
            connection.execute(f"SET {setting} = {setting_value}")
            self.logger.debug(f"Set {setting} = {value}")
            return True
        except Exception as e:
            # Suppress warnings for known problematic settings in local mode
            if self.deployment_mode == "local" and setting in local_incompatible_settings:
                self.logger.debug(f"Setting {setting} not available in local mode: {e}")
            else:
                self.logger.warning(f"Failed to set {setting}: {e}")
            return False

    def _format_setting_value(self, value: Any) -> Any:
        """Format ClickHouse SET values, quoting string literals."""
        if not isinstance(value, str):
            return value
        if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
            return value
        return "'" + value.replace("'", "''") + "'"

    _supported_tuning_type_names = ("PARTITIONING", "SORTING", "CLUSTERING", "DISTRIBUTION")

    def supports_tuning_type(self, tuning_type) -> bool:
        """Check if ClickHouse supports a specific tuning type."""
        return supports_named_tuning_type(tuning_type, self._supported_tuning_type_names)

    def apply_table_tunings(self, table_tuning, connection: Any) -> None:
        """Apply ClickHouse-specific table tunings.

        ClickHouse tuning approach:
        - PARTITIONING: Handled via PARTITION BY in CREATE TABLE
        - SORTING: Handled via ORDER BY in CREATE TABLE
        - CLUSTERING: Achieved through ORDER BY and OPTIMIZE operations
        - DISTRIBUTION: Handled via distributed engine settings

        Args:
            table_tuning: TableTuning configuration object
            connection: ClickHouse connection

        Raises:
            ValueError: If the tuning configuration is invalid for ClickHouse
        """
        if not table_tuning or not table_tuning.has_any_tuning():
            return

        table_name = table_tuning.table_name
        self.logger.info(f"Applying ClickHouse tunings for table: {table_name}")

        try:
            # Import here to avoid circular imports
            from benchbox.core.tuning.interface import TuningType

            # ClickHouse doesn't support ALTER TABLE for changing partitioning or ordering
            # after table creation, but we can optimize existing tables

            # Apply sorting optimization by running OPTIMIZE TABLE
            sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
            if sort_columns:
                sorted_cols = sorted(sort_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]
                self.logger.info(f"Optimizing table {table_name} for sorting on columns: {', '.join(column_names)}")
                self.optimize_table(connection, table_name)

            # Apply clustering optimization via OPTIMIZE TABLE FINAL
            cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
            if cluster_columns:
                sorted_cols = sorted(cluster_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]
                self.logger.info(
                    f"Applying clustering optimization to table {table_name} on columns: {', '.join(column_names)}"
                )
                connection.execute(f"OPTIMIZE TABLE {table_name} FINAL")

            # Log partitioning strategy (must be defined at CREATE TABLE time)
            partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
            if partition_columns:
                sorted_cols = sorted(partition_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]
                self.logger.info(
                    f"Partitioning strategy for table {table_name}: {', '.join(column_names)} (defined at CREATE TABLE time)"
                )

            # Log distribution strategy (handled by engine settings)
            distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
            if distribution_columns:
                sorted_cols = sorted(distribution_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]
                self.logger.info(
                    f"Distribution strategy for table {table_name}: {', '.join(column_names)} (handled by ClickHouse engine settings)"
                )

        except ImportError:
            self.logger.warning("Tuning interface not available - skipping tuning application")
        except Exception as e:
            raise ValueError(f"Failed to apply tunings to ClickHouse table {table_name}: {e}") from e

    def generate_tuning_clause(self, table_tuning) -> str:
        """Generate ClickHouse-specific tuning clauses for CREATE TABLE statements.

        ClickHouse tuning is applied through:
        - PARTITION BY clause for partitioning
        - ORDER BY clause for sorting and clustering (combined)
        - PRIMARY KEY clause (optional, derived from ORDER BY)

        Args:
            table_tuning: TableTuning configuration object

        Returns:
            SQL clause string to be appended to CREATE TABLE statement
        """
        if not table_tuning or not table_tuning.has_any_tuning():
            return ""

        clauses = []

        try:
            # Import here to avoid circular imports
            from benchbox.core.tuning.interface import TuningType

            # Generate PARTITION BY clause
            partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
            if partition_columns:
                # Sort by order and create partition expression
                sorted_columns = sorted(partition_columns, key=lambda c: c.order)
                partition_expr = ", ".join(col.name for col in sorted_columns)
                clauses.append(f"PARTITION BY ({partition_expr})")

            # Generate ORDER BY clause (combines sorting and clustering)
            order_columns = []

            # Include clustering columns first (they should come before sorting columns in ORDER BY)
            cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
            if cluster_columns:
                order_columns.extend(sorted(cluster_columns, key=lambda c: c.order))

            # Include sorting columns (higher priority in ordering)
            sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
            if sort_columns:
                order_columns.extend(sorted(sort_columns, key=lambda c: c.order))

            if order_columns:
                # Remove duplicates while preserving order
                seen = set()
                unique_columns = []
                for col in order_columns:
                    if col.name not in seen:
                        unique_columns.append(col)
                        seen.add(col.name)

                order_expr = ", ".join(col.name for col in unique_columns)
                clauses.append(f"ORDER BY ({order_expr})")

            # Distribution handled by engine type and cluster configuration
            # Log distribution columns but don't add to CREATE TABLE clause
            distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
            if distribution_columns:
                # Distribution in ClickHouse is handled at the engine level
                pass

            return " " + " ".join(clauses) if clauses else ""

        except ImportError:
            # If tuning interface not available, return empty string
            return ""
        except Exception as e:
            if hasattr(table_tuning, "table_name"):
                self.logger.warning(f"Failed to generate tuning clauses for table {table_tuning.table_name}: {e}")
            else:
                self.logger.warning(f"Failed to generate tuning clauses: {e}")
            return ""

    def apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None:
        """Apply unified tuning configuration to ClickHouse.

        Args:
            unified_config: Unified tuning configuration to apply
            connection: ClickHouse connection
        """
        from benchbox.platforms.base.tuning_config import apply_standard_unified_tuning

        apply_standard_unified_tuning(self, unified_config, connection)

    def apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None:
        """Apply ClickHouse-specific platform optimizations.

        Args:
            platform_config: Platform optimization configuration
            connection: ClickHouse connection
        """
        if not platform_config or not platform_config.clickhouse_optimizations:
            return

        try:
            # Apply ClickHouse-specific optimizations
            optimizations = platform_config.clickhouse_optimizations

            # Apply memory settings
            if hasattr(optimizations, "max_memory_usage") and optimizations.max_memory_usage:
                memory_bytes = self._parse_memory_setting(optimizations.max_memory_usage)
                connection.execute(f"SET max_memory_usage = {memory_bytes}")
                self.logger.info(f"Set max_memory_usage = {memory_bytes}")

            # Apply thread settings
            if hasattr(optimizations, "max_threads") and optimizations.max_threads:
                connection.execute(f"SET max_threads = {optimizations.max_threads}")
                self.logger.info(f"Set max_threads = {optimizations.max_threads}")

            # Apply join algorithm
            if hasattr(optimizations, "join_algorithm") and optimizations.join_algorithm:
                if self._apply_setting_with_validation(
                    connection, "join_algorithm", f"'{optimizations.join_algorithm}'"
                ):
                    self.logger.info(f"Set join_algorithm = {optimizations.join_algorithm}")

            # Apply additional settings if available
            if hasattr(optimizations, "additional_settings") and optimizations.additional_settings:
                for setting, value in optimizations.additional_settings.items():
                    if self._apply_setting_with_validation(connection, setting, value):
                        self.logger.info(f"Set {setting} = {value}")

        except Exception as e:
            self.logger.error(f"Failed to apply ClickHouse platform optimizations: {e}")

    apply_constraint_configuration = make_informational_constraint_applier(
        "Primary key constraints enabled for ClickHouse (applied during table creation)",
        "Foreign key constraints enabled for ClickHouse (applied during table creation)",
    )


__all__ = ["ClickHouseTuningMixin"]
