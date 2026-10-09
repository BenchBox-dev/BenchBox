from __future__ import annotations

CANARY_CHECKS = ("name", "status", "muse", "retry")


def canary_check_count() -> int:
    return len(CANARY_CHECKS)
