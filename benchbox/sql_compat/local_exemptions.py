from __future__ import annotations

from typing import Callable, Literal

CompatLocalKind = Literal["type_mapping", "storage_layout", "rendering"]

_COMPAT_LOCAL_ATTR = "_compat_local"


def compat_local(
    kind: CompatLocalKind,
    platform_specific: bool,
    reason: str,
) -> Callable[[Callable], Callable]:

    def decorator(fn: Callable) -> Callable:
        setattr(
            fn,
            _COMPAT_LOCAL_ATTR,
            {"kind": kind, "platform_specific": platform_specific, "reason": reason},
        )
        return fn

    return decorator
