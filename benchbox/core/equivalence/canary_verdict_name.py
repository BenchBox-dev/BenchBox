from __future__ import annotations

CANARY_NAMES = ("oracle", "verdict")


def canary_name_count() -> int:
    return len(CANARY_NAMES)
