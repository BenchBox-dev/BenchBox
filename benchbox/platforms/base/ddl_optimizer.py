from __future__ import annotations

import importlib
from typing import ClassVar, Protocol

_LOADED_PLATFORMS: set[str] = set()


def _clear_load_cache() -> None:
    _LOADED_PLATFORMS.clear()


def _ensure_platform_rules_loaded(platform_key: str) -> None:
    if platform_key in _LOADED_PLATFORMS:
        return
    module_name = f"benchbox.sql_compat.rules.ddl_optimize.{platform_key}_ddl_rewrites"
    try:
        importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
    _LOADED_PLATFORMS.add(platform_key)


class DdlOptimizer(Protocol):
    def optimize_table_definition(self, stmt: str, table_name: str) -> str: ...


class BaseDdlOptimizer:
    _platform_key: ClassVar[str] = ""

    def optimize_table_definition(self, stmt: str, table_name: str) -> str:
        from benchbox.sql_compat.context import Phase
        from benchbox.sql_compat.decision import RewriteDDLPayload
        from benchbox.sql_compat.registry import REGISTRY

        if not self._platform_key:
            raise TypeError(
                f"{type(self).__name__} must declare a non-empty '_platform_key' ClassVar[str] to use BaseDdlOptimizer."
            )
        _ensure_platform_rules_loaded(self._platform_key)
        for decision in REGISTRY.resolve_platform_rules(Phase.DDL_OPTIMIZE, self._platform_key):
            payload = decision.payload
            if not isinstance(payload, RewriteDDLPayload):
                continue
            if payload.governance_only:
                continue
            transformer = getattr(self, payload.transformer_id)
            stmt = transformer(stmt)
        return stmt
