"""Tuning configuration helpers for PlatformAdapter.

Extracted from `benchbox.platforms.base.adapter` per the refactor map
(`docs/development/adapter-refactor-map.md` Slice 2). Covers unified-tuning
application, effective-config resolution, and tuning-metadata persistence.

The abstract `configure_for_benchmark` hook stays on PlatformAdapter
itself (32 subclass overrides - moving its name risks breaking the
contract surface).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration


def apply_standard_unified_tuning(adapter: Any, unified_config: UnifiedTuningConfiguration, connection: Any) -> None:
    """Apply the standard constraint, platform, then table-tuning hook sequence."""
    if not unified_config:
        return

    adapter.apply_constraint_configuration(unified_config.primary_keys, unified_config.foreign_keys, connection)
    if unified_config.platform_optimizations:
        adapter.apply_platform_optimizations(unified_config.platform_optimizations, connection)
    for _table_name, table_tuning in unified_config.table_tunings.items():
        adapter.apply_table_tunings(table_tuning, connection)


class TuningConfigMixin:
    """Mixin providing unified-tuning configuration handling for `PlatformAdapter`.

    Expects host class to expose `platform_name`, `logger`, `tuning_enabled`,
    `create_connection`, `close_connection`, plus `log_verbose` /
    `log_very_verbose` from `VerbosityMixin`.
    """

    platform_name: str
    logger: logging.Logger
    tuning_enabled: bool

    def apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None:
        """Apply unified tuning configuration to the database.

        This method should implement platform-specific logic for applying
        the full unified tuning configuration, including:
        - Schema constraints (primary keys, foreign keys, unique, check)
        - Platform-specific optimizations (Z-ordering, auto-optimize, etc.)
        - Table-level tunings (partitioning, clustering, distribution, sorting)

        Args:
            unified_config: Unified tuning configuration to apply
            connection: Database connection

        Raises:
            NotImplementedError: If unified tuning is not supported by the platform
            ValueError: If the configuration is invalid for this platform
        """
        if unified_config:
            self.log_verbose(f"Unified tuning not implemented for {self.platform_name} - using base class no-op")
        else:
            self.log_very_verbose("No unified tuning configuration provided")
        return None

    def get_effective_tuning_configuration(self) -> UnifiedTuningConfiguration | None:
        """Get the effective tuning configuration.

        Returns:
            The unified tuning configuration, or None if no tuning is configured
        """
        return getattr(self, "unified_tuning_configuration", None)

    def validate_tuning_configuration_for_platform(self) -> list[str]:
        """Validate the current tuning configuration against this platform's capabilities.

        Returns:
            List of validation error messages (empty if no errors)
        """
        effective_config = self.get_effective_tuning_configuration()
        if not effective_config:
            return []

        return effective_config.validate_for_platform(self.platform_name)

    def validate_tuning_configuration(self, unified_config: UnifiedTuningConfiguration) -> list[str]:
        """Validate a unified tuning configuration against platform capabilities.

        Args:
            unified_config: The unified tuning configuration to validate

        Returns:
            List of validation error messages (empty if all valid)
        """
        if not unified_config:
            return []

        return unified_config.validate_for_platform(self.platform_name)

    def _validate_database_tunings(self, **connection_config):
        """Validate that database tunings match expected configuration.

        Args:
            **connection_config: Connection configuration

        Returns:
            ValidationResult with tuning comparison results
        """
        try:
            from benchbox.core.tuning.metadata import (
                MetadataValidationResult,
                TuningMetadataManager,
            )

            self._validating_database = True
            temp_connection = None
            if hasattr(self, "_create_direct_connection"):
                temp_connection = self._create_direct_connection(**connection_config)
            else:
                temp_connection = self.create_connection(**connection_config)

            try:
                metadata_manager = TuningMetadataManager(self, connection_config.get("database"))

                effective_config = self.get_effective_tuning_configuration()
                if effective_config:
                    return metadata_manager.validate_unified_tunings(effective_config)
                else:
                    existing_tunings = metadata_manager.load_unified_tunings()
                    result = MetadataValidationResult()
                    if existing_tunings:
                        result.add_warning("Database contains tuning metadata but no tunings expected")
                    return result

            finally:
                self.close_connection(temp_connection)
                self._validating_database = False

        except Exception as e:
            from benchbox.core.tuning.metadata import MetadataValidationResult

            self._validating_database = False
            result = MetadataValidationResult()
            result.add_error(f"Failed to validate database tunings: {e}")
            return result

    def save_tuning_metadata(self, connection: Any) -> bool:
        """Save tuning metadata to database for future validation.

        Args:
            connection: Database connection

        Returns:
            True if metadata was saved successfully, False otherwise
        """
        effective_config = self.get_effective_tuning_configuration()
        if not self.tuning_enabled or not effective_config:
            return True

        try:
            from benchbox.core.tuning.metadata import TuningMetadataManager

            metadata_manager = TuningMetadataManager(self)
            return metadata_manager.save_unified_tunings(effective_config)

        except Exception as e:
            self.logger.error(f"Failed to save tuning metadata: {e}")
            return False
