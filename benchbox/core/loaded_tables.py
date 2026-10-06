from __future__ import annotations

import logging
from typing import Any
from unittest.mock import NonCallableMock

logger = logging.getLogger(__name__)


def is_data_loading_skipped(benchmark: Any) -> bool:
    if getattr(type(benchmark), "SKIP_DATA_LOADING", False):
        return True
    if isinstance(benchmark, NonCallableMock):
        return False
    return bool(getattr(benchmark, "SKIP_DATA_LOADING", False))


def _holds_rows(rows: Any) -> bool:
    return isinstance(rows, (int, float)) and not isinstance(rows, bool) and rows > 0


def require_loaded_tables(benchmark: Any, table_stats: dict[str, Any] | None) -> None:
    if is_data_loading_skipped(benchmark):
        return
    required = getattr(benchmark, "REQUIRED_LOADED_TABLES", ())
    if not isinstance(required, (tuple, list, set, frozenset)):
        required = ()
    loaded = {str(name).lower(): rows for name, rows in (table_stats or {}).items()}
    problems = []
    if not required:
        if not any(_holds_rows(rows) for rows in loaded.values()):
            problems.append("no rows were loaded for any table")
        else:
            zero_row = sorted(name for name, rows in loaded.items() if not _holds_rows(rows))
            if zero_row:
                logger.warning(
                    "Partial load: at least one table holds rows, but these tables loaded no rows: %s",
                    ", ".join(zero_row),
                )
    else:
        for table in required:
            rows = loaded.get(table.lower())
            if rows is None:
                problems.append(f"{table} was not loaded")
            elif not isinstance(rows, (int, float)) or rows <= 0:
                problems.append(f"{table} has {rows} rows")
    if problems:
        raise RuntimeError(
            "Required benchmark tables are missing or empty after load: "
            + "; ".join(problems)
            + f". Loaded tables: {sorted(loaded)}"
        )
