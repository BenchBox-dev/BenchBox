"""No-op constraint and optimization hooks for in-memory / DataFrame platforms.

DataFusion, Polars, and cuDF share identical semantics for constraint
enforcement and platform optimization: neither PRIMARY KEY nor FOREIGN KEY
constraints are enforced, and query-level optimizations happen internally at
session/initialization time rather than through BenchBox's optimization hooks.

This mixin centralises those no-op implementations so they stay in sync.
"""

from __future__ import annotations

from typing import Any


class NoConstraintEnforcementMixin:
    """No-op apply_constraint_configuration and apply_platform_optimizations.

    Intended for in-memory and DataFrame platforms (DataFusion, Polars, cuDF)
    that do not enforce SQL constraints and whose performance knobs are set at
    session creation rather than via the standard optimization hook.

    The mixin reads ``self.platform_name`` (expected on the host adapter) for
    log messages.  Falls back to the class name if the attribute is absent.
    """

    def apply_constraint_configuration(
        self,
        primary_key_config: Any,
        foreign_key_config: Any,
        connection: Any,
    ) -> None:
        name = getattr(self, "platform_name", type(self).__name__)
        if primary_key_config and getattr(primary_key_config, "enabled", False):
            self.log_verbose(  # type: ignore[attr-defined]
                f"{name} does not enforce PRIMARY KEY constraints - configuration noted but not applied"
            )
        if foreign_key_config and getattr(foreign_key_config, "enabled", False):
            self.log_verbose(  # type: ignore[attr-defined]
                f"{name} does not enforce FOREIGN KEY constraints - configuration noted but not applied"
            )

    def apply_platform_optimizations(self, platform_config: Any, connection: Any) -> None:
        if not platform_config:
            self.log_verbose("No platform optimizations configured")  # type: ignore[attr-defined]
            return
        name = getattr(self, "platform_name", type(self).__name__)
        self.log_verbose(  # type: ignore[attr-defined]
            f"{name} optimizations are applied at session initialization"
        )
