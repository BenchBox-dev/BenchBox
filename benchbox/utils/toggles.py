"""Layer-neutral toggle normalization shared by CLI, core, and platforms.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

from __future__ import annotations

from typing import Any

_FALSE_TOKENS = frozenset({"0", "false", "no", "off"})
_TRUE_TOKENS = frozenset({"1", "true", "yes", "on"})


def is_probe_requested(value: Any) -> bool:
    """Normalize an opt-out toggle such as ``link_probe`` to a boolean.

    ``None`` (unset) means requested: the feature is default-on and callers
    opt out explicitly via ``False`` / ``"false"`` / ``"0"`` / ``0``.
    """
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _FALSE_TOKENS:
            return False
        if normalized in _TRUE_TOKENS:
            return True
        return bool(normalized)
    return bool(value)


__all__ = [
    "is_probe_requested",
]
