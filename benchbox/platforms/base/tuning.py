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


_PHYSICAL_IDENTIFIER_FOLDERS: dict[str, Callable[[str], str]] = {
    "lower": str.lower,
    "upper": str.upper,
    "preserve": str,
}


class TuningHooksMixin:
    """Mixin providing the per-table tuning DDL/clause hooks.

    Expects the host class to expose `platform_name`. Default implementations
    are no-ops so adapters without tuning support inherit safe behavior.
    """

    platform_name: str
    _supported_tuning_type_names: Iterable[str] | None = None
    physical_identifier_case: str = "preserve"
    post_load_connection_recording: bool = True

    @staticmethod
    def table_tuning_for(effective_config: Any, table_name: str) -> Any:
        table_tunings = getattr(effective_config, "table_tunings", None) or {}
        for name, table_tuning in table_tunings.items():
            if name.lower() == table_name.lower():
                return table_tuning
        return None

    def apply_post_load_tunings(self, table_name: str, effective_config: Any, connection: Any) -> bool:
        return False

    def note_post_load_maintenance_failure(self) -> None:
        """Mark the maintenance phase FAILED for a statement a hook caught and logged."""
        self._post_load_maintenance_errors = getattr(self, "_post_load_maintenance_errors", 0) + 1

    def run_post_load_tunings(self, table_name: str, effective_config: Any, connection: Any) -> None:
        if effective_config is None or getattr(self, "dry_run_mode", False):
            return
        from benchbox.core.tuning.applied_ledger import PHASE_POST_LOAD, recording_connection
        from benchbox.utils.clock import elapsed_seconds, mono_time

        ledger = getattr(self, "_applied_tuning_ledger", None)
        record = ledger is not None and self.post_load_connection_recording
        target = recording_connection(connection, ledger, PHASE_POST_LOAD) if record else connection
        performed = False
        start = mono_time()
        try:
            performed = bool(self.apply_post_load_tunings(table_name, effective_config, target))
        except Exception as exc:
            performed = True
            self.note_post_load_maintenance_failure()
            self.logger.warning(f"Post-load tuning failed for {table_name}: {exc}")
        finally:
            if performed:
                elapsed = elapsed_seconds(start)
                self._post_load_maintenance_seconds = getattr(self, "_post_load_maintenance_seconds", 0.0) + elapsed
                tables = getattr(self, "_post_load_maintenance_tables", None)
                if tables is None:
                    tables = []
                    self._post_load_maintenance_tables = tables
                tables.append(table_name)
                by_table = getattr(self, "_post_load_maintenance_by_table", None)
                if by_table is None:
                    by_table = {}
                    self._post_load_maintenance_by_table = by_table
                by_table[table_name.lower()] = by_table.get(table_name.lower(), 0.0) + elapsed

    def exclude_post_load_maintenance(self, loading_time: float, per_table_timings: Any) -> tuple[float, Any]:
        by_table = getattr(self, "_post_load_maintenance_by_table", None) or {}
        if isinstance(per_table_timings, dict):
            for key, entry in per_table_timings.items():
                spent = by_table.get(str(key).lower(), 0.0)
                if spent and isinstance(entry, dict) and "total_ms" in entry:
                    entry["total_ms"] = max(0.0, entry["total_ms"] - spent * 1000)
        return max(loading_time - getattr(self, "_post_load_maintenance_seconds", 0.0), 0.0), per_table_timings

    def build_post_load_maintenance_phase(self) -> Any:
        from benchbox.core.results.models import PostLoadMaintenancePhase

        tables = set(getattr(self, "_post_load_maintenance_tables", None) or [])
        if not tables:
            return None
        return PostLoadMaintenancePhase(
            duration_ms=int(getattr(self, "_post_load_maintenance_seconds", 0.0) * 1000),
            status="FAILED" if getattr(self, "_post_load_maintenance_errors", 0) else "SUCCESS",
            tables_processed=len(tables),
        )

    def get_post_load_maintenance_metadata(self) -> dict[str, Any]:
        return {
            "total_apply_seconds": getattr(self, "_post_load_maintenance_seconds", 0.0),
            "applied_tables": sorted(set(getattr(self, "_post_load_maintenance_tables", []))),
        }

    def resolve_physical_table(self, logical_name: str, connection: Any = None) -> str:
        return _PHYSICAL_IDENTIFIER_FOLDERS[self.physical_identifier_case](logical_name)

    def resolve_physical_column(self, table_name: str, logical_column: str, connection: Any = None) -> str:
        return _PHYSICAL_IDENTIFIER_FOLDERS[self.physical_identifier_case](logical_column)

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

        # is_compatible_with_platform expects the canonical, machine-readable
        # platform type key (e.g. "clickhouse-local"), not `platform_name`,
        # which is a human-facing display string (e.g. "ClickHouse Local").
        # Fall back to `platform_name` via getattr for hosts that predate
        # `canonical_platform_type` (added on PlatformAdapter in #1174).
        platform_key = getattr(self, "canonical_platform_type", self.platform_name)
        return tuning_type.is_compatible_with_platform(platform_key)

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
