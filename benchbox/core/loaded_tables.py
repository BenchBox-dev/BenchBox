"""Checks that a benchmark loaded the tables its queries read."""

from __future__ import annotations

from typing import Any


def require_loaded_tables(benchmark: Any, table_stats: dict[str, Any] | None) -> None:
    """Fail the run when a table the benchmark's queries need was not loaded.

    A benchmark lists those tables in ``REQUIRED_LOADED_TABLES``. Without this
    check a run that loaded the wrong dataset still measures: the schema DDL
    creates the required table empty, its queries succeed with no rows, and the
    result looks valid.
    """
    required = getattr(benchmark, "REQUIRED_LOADED_TABLES", ())
    if not isinstance(required, (tuple, list, set, frozenset)) or not required:
        return
    loaded = {str(name).lower(): rows for name, rows in (table_stats or {}).items()}
    problems = []
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
