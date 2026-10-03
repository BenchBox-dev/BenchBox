from __future__ import annotations

from typing import Any


class NoConstraintEnforcementMixin:
    def apply_constraint_configuration(
        self,
        primary_key_config: Any,
        foreign_key_config: Any,
        connection: Any,
    ) -> None:
        name = getattr(self, "platform_name", type(self).__name__)
        if primary_key_config and getattr(primary_key_config, "enabled", False):
            self.log_verbose(f"{name} does not enforce PRIMARY KEY constraints - configuration noted but not applied")
        if foreign_key_config and getattr(foreign_key_config, "enabled", False):
            self.log_verbose(f"{name} does not enforce FOREIGN KEY constraints - configuration noted but not applied")

    def apply_platform_optimizations(self, platform_config: Any, connection: Any) -> None:
        if not platform_config:
            self.log_verbose("No platform optimizations configured")
            return
        name = getattr(self, "platform_name", type(self).__name__)
        self.log_verbose(f"{name} optimizations are applied at session initialization")
