from __future__ import annotations

CANARY_FLAGS = ("install", "version", "verdict", "retry")


def canary_flag_count() -> int:
    return len(CANARY_FLAGS)
