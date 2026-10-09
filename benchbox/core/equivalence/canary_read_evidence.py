from __future__ import annotations

CANARY_ROWS = ("alpha", "beta", "gamma")


def canary_row_count() -> int:
    return len(CANARY_ROWS)
