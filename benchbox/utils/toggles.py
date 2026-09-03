"""Layer-neutral toggle normalization shared by CLI, core, and platforms.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

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
        # Unrecognized tokens fail closed: running billable probe statements
        # on ambiguous input is worse than skipping them.
        logger.warning("Unrecognized toggle value %r; treating as not requested", value)
        return False
    return bool(value)


__all__ = [
    "is_probe_requested",
]
