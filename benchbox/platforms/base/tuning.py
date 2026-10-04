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
    platform_name: str
    _supported_tuning_type_names: Iterable[str] | None = None
    physical_identifier_case: str = "preserve"

    def resolve_physical_table(self, logical_name: str, connection: Any = None) -> str:
        return _PHYSICAL_IDENTIFIER_FOLDERS[self.physical_identifier_case](logical_name)

    def resolve_physical_column(self, table_name: str, logical_column: str, connection: Any = None) -> str:
        return _PHYSICAL_IDENTIFIER_FOLDERS[self.physical_identifier_case](logical_column)

    def apply_table_tunings(self, table_tuning: TableTuning, connection: Any) -> None:
        return None

    def supports_tuning_type(self, tuning_type: TuningTypeT) -> bool:
        if self._supported_tuning_type_names is not None:
            return supports_named_tuning_type(tuning_type, self._supported_tuning_type_names)
        if TuningType is None:
            return False

        platform_key = getattr(self, "canonical_platform_type", self.platform_name)
        return tuning_type.is_compatible_with_platform(platform_key)

    def generate_tuning_clause(self, table_tuning: TableTuning) -> str:
        return ""
