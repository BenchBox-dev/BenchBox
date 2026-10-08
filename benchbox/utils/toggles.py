# Copyright 2026 Joe Harris / BenchBox Project
# Licensed under the MIT License.

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_FALSE_TOKENS = frozenset({"0", "false", "no", "off"})
_TRUE_TOKENS = frozenset({"1", "true", "yes", "on"})


def is_probe_requested(value: Any) -> bool:
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

        logger.warning("Unrecognized toggle value %r; treating as not requested", value)
        return False
    return bool(value)


__all__ = [
    "is_probe_requested",
]
