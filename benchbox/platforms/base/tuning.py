"""Per-table tuning DDL/clause hooks for PlatformAdapter.

Extracted from `benchbox.platforms.base.adapter` per the refactor map
(`docs/development/adapter-refactor-map.md` Slice 2c). Houses the
per-table tuning hooks that adapters override to emit CREATE TABLE
clauses or apply post-creation tunings.

The two abstract `apply_platform_optimizations` /
`apply_constraint_configuration` hooks remain on `PlatformAdapter`
itself - they have 26+ subclass overrides each and the contract
surface is intentionally visible on the base class.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        ForeignKeyConfiguration,
        PrimaryKeyConfiguration,
        TableTuning,
        TuningType as TuningTypeT,
    )

try:
    from benchbox.core.tuning.interface import TuningType
except ImportError:
    TuningType = None


def supports_named_tuning_type(tuning_type: Any, supported_names: Iterable[str]) -> bool:
    """Return whether *tuning_type* matches one of the named TuningType members."""
    try:
        from benchbox.core.tuning.interface import TuningType as CurrentTuningType
    except ImportError:
        return False
    for name in supported_names:
        candidate = getattr(CurrentTuningType, name, None)
        if candidate is not None and tuning_type == candidate:
            return True
    return False


def make_informational_constraint_applier(
    primary_message: str,
    foreign_message: str,
) -> Callable[[Any, Any, Any, Any], None]:
    """Create a constraint hook that logs enabled informational constraints."""

    def apply_constraint_configuration(
        self,
        primary_key_config: PrimaryKeyConfiguration,
        foreign_key_config: ForeignKeyConfiguration,
        connection: Any,
    ) -> None:
        if primary_key_config and primary_key_config.enabled:
            self.logger.info(primary_message)
        if foreign_key_config and foreign_key_config.enabled:
            self.logger.info(foreign_message)

    apply_constraint_configuration.__name__ = "apply_constraint_configuration"
    apply_constraint_configuration.__qualname__ = "apply_constraint_configuration"
    return apply_constraint_configuration


class TuningHooksMixin:
    """Mixin providing the per-table tuning DDL/clause hooks.

    Expects the host class to expose `platform_name`. Default implementations
    are no-ops so adapters without tuning support inherit safe behavior.
    """

    platform_name: str
    _supported_tuning_type_names: Iterable[str] | None = None

    def apply_table_tunings(self, table_tuning: TableTuning, connection: Any) -> None:
        """Apply tuning configurations to a database table.

        This method should be implemented by platform adapters to apply
        platform-specific tuning optimizations such as partitioning,
        clustering, distribution, and sorting.

        Args:
            table_tuning: The tuning configuration to apply
            connection: Database connection

        Raises:
            NotImplementedError: If tuning is not supported by the platform
            ValueError: If the tuning configuration is invalid for this platform
        """
        return None

    def supports_tuning_type(self, tuning_type: TuningTypeT) -> bool:
        """Check if this platform adapter supports a specific tuning type.

        Args:
            tuning_type: The type of tuning to check support for

        Returns:
            True if the tuning type is supported by this platform
        """
        if self._supported_tuning_type_names is not None:
            return supports_named_tuning_type(tuning_type, self._supported_tuning_type_names)
        if TuningType is None:
            return False

        return tuning_type.is_compatible_with_platform(self.platform_name)

    def generate_tuning_clause(self, table_tuning: TableTuning) -> str:
        """Generate platform-specific tuning clauses for CREATE TABLE statements.

        This method should generate the appropriate SQL clauses to be included
        in CREATE TABLE statements to apply the specified tuning configurations.

        Args:
            table_tuning: The tuning configuration for the table

        Returns:
            SQL clause string to be appended to CREATE TABLE statement
            (empty string if no tuning clauses are needed)

        Raises:
            ValueError: If the tuning configuration is invalid for this platform
        """
        return ""
