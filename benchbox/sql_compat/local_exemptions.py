"""@compat_local decorator - attribution mechanism for legitimate local rendering.

Marks a callable as containing platform-specific rendering that is NOT a
compatibility-policy decision and therefore exempt from the compat_lint
unregistered-dialect-branch rule.

Three categories of legitimate local rendering:
  type_mapping   - SQL type translation (INT → INT32, FLOAT → DOUBLE)
  storage_layout - Engine/storage specifics (MergeTree ORDER BY, columnar tuning)
  rendering      - Identifier quoting, case folding, output format differences

Usage:
    from benchbox.sql_compat.local_exemptions import compat_local

    @compat_local(
        kind="type_mapping",
        platform_specific=True,
        reason="Maps generic SQL types to ClickHouse / DuckDB / PostgreSQL equivalents.",
    )
    def _map_type_to_dialect(type_name: str, dialect: str) -> str:
        ...

Granularity rule (from ADR):
  Apply at the narrowest scope. If a function mixes type-mapping with
  compatibility-policy branches, split it first. A @compat_local-decorated
  function that contains branches of a different kind is a lint error.

The decorator is a no-op at runtime - it attaches metadata to the wrapped
function for tooling (linter, inventory) but does not alter behavior.
"""

from __future__ import annotations

from typing import Callable, Literal

CompatLocalKind = Literal["type_mapping", "storage_layout", "rendering"]

# Attribute name written onto decorated functions so tooling can inspect them
# without importing this module or re-parsing the AST.
_COMPAT_LOCAL_ATTR = "_compat_local"


def compat_local(
    kind: CompatLocalKind,
    platform_specific: bool,
    reason: str,
) -> Callable[[Callable], Callable]:
    """Mark a callable as containing legitimate local platform-specific rendering.

    This exempts the callable from the compat_lint "unregistered dialect branch"
    rule. It does NOT register a rule in the sql_compat registry.

    Args:
        kind: Category - type_mapping, storage_layout, or rendering.
        platform_specific: True if the branch is specific to one platform.
        reason: Why this is legitimate local rendering, not unregistered policy.
    """

    def decorator(fn: Callable) -> Callable:
        setattr(
            fn,
            _COMPAT_LOCAL_ATTR,
            {"kind": kind, "platform_specific": platform_specific, "reason": reason},
        )
        return fn

    return decorator
