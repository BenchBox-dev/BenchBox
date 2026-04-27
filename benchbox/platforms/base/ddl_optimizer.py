"""DdlOptimizer Protocol and BaseDdlOptimizer mixin for phase-aware DDL rewrites.

Pattern: rules registered under Phase.DDL_OPTIMIZE document *intent* for
governance/compat_lint; adapter methods implement the actual transformations.
BaseDdlOptimizer bridges the two by walking registered rules for the adapter's
platform key and dispatching each to the matching adapter method by transformer_id.

See benchbox/sql_compat/README.md for a worked example with SingleStore.
"""

from __future__ import annotations

import importlib
from typing import ClassVar, Protocol

_LOADED_PLATFORMS: set[str] = set()
# Not thread-safe by design: BenchBox runs benchmarks serially; the concurrent
# re-import scenario is harmless because REGISTRY.register() is idempotent.
# Process-lifetime cache: tests that mutate registry state should call
# _clear_load_cache() in a fixture to force re-import.


def _clear_load_cache() -> None:
    """Forget which platform rule modules have been loaded.

    Intended for test fixtures that mutate REGISTRY and need a fresh import
    cycle. Production code should not call this — the cache is correct for
    the process lifetime under normal use.
    """
    _LOADED_PLATFORMS.clear()


def _ensure_platform_rules_loaded(platform_key: str) -> None:
    """Import the DDL_OPTIMIZE rule file for *platform_key* (idempotent).

    Rule modules self-register against REGISTRY at import time.  Loading them
    here is cheap (the registry idempotency guard absorbs re-imports) and keeps
    adapters decoupled from rule module import order.

    If the rule file does not exist (ModuleNotFoundError for the file itself),
    the miss is cached so future calls skip the import attempt — the platform
    simply has no registered rules.

    If the file exists but fails to import (e.g. a broken transitive dependency),
    the exception propagates rather than being swallowed, so the failure is
    visible.  The platform is *not* added to _LOADED_PLATFORMS, so the next
    call will re-attempt the import (useful for test monkeypatching).
    """
    if platform_key in _LOADED_PLATFORMS:
        return
    module_name = f"benchbox.sql_compat.rules.ddl_optimize.{platform_key}_ddl_rewrites"
    try:
        importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            # A dependency of the rule module is missing — propagate, don't cache.
            raise
        # The rule file itself doesn't exist; intentional for platforms that
        # haven't migrated to BaseDdlOptimizer yet.  Cache the miss.
    _LOADED_PLATFORMS.add(platform_key)


class DdlOptimizer(Protocol):
    """Protocol for adapters that perform phase-aware DDL table-definition optimization."""

    def optimize_table_definition(self, stmt: str, table_name: str) -> str: ...


class BaseDdlOptimizer:
    """Mixin that dispatches Phase.DDL_OPTIMIZE rules to adapter transformer methods.

    Inheriting adapters must set ``_platform_key`` (as a ``ClassVar[str]``) and
    define a method for each ``transformer_id`` registered under
    ``(Phase.DDL_OPTIMIZE, _platform_key)``.  Rules are applied in registration
    order; each transformer receives the current stmt and returns the (possibly
    modified) stmt.

    Usage::

        class MyAdapter(BaseDdlOptimizer, PlatformAdapter):
            _platform_key: ClassVar[str] = "myplatform"

            def myplatform_strip_fk(self, stmt: str) -> str:
                return strip_foreign_keys(stmt)
    """

    _platform_key: ClassVar[str] = ""

    def optimize_table_definition(self, stmt: str, table_name: str) -> str:
        """Apply all DDL_OPTIMIZE rules for this platform in registration order.

        ``table_name`` satisfies the ``DdlOptimizer`` Protocol signature and is
        available for subclass overrides; the default dispatch loop passes only
        ``stmt`` to each transformer (transformers extract table context from the
        stmt when needed, avoiding a second parameter in every method signature).

        Uses ``REGISTRY.resolve_platform_rules`` to read rules registered at the
        platform-wide tier (benchmark=None, query_id=None). DDL governance does
        not have a benchmark or query context, so the synthetic-context tiers
        that ``resolve_all`` would walk are unnecessary.
        """
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
                # Rule exists only to satisfy compat_lint; the adapter performs the
                # rewrite via a different code path (e.g., string-replace inside its
                # own create_schema loop).
                continue
            transformer = getattr(self, payload.transformer_id)
            stmt = transformer(stmt)
        return stmt
