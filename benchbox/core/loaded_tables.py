"""Checks that a benchmark loaded the tables its queries read."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import NonCallableMock

logger = logging.getLogger(__name__)


def is_data_loading_skipped(benchmark: Any) -> bool:
    """Return True when the benchmark declares schema-only mode.

    The ``SKIP_DATA_LOADING`` flag is read from the benchmark *class* first.
    Mock benchmark doubles auto-create any attribute read on the instance as
    a truthy ``Mock`` object, so reading the instance first would let a mock
    benchmark silently disable the loaded-table checks. The instance is
    therefore consulted only as a fallback, and only when the benchmark is a
    real object (not a ``unittest.mock`` double) -- e.g. benchmarks that set
    the flag per-instance in ``__init__``. Every load path (``DataLoader``,
    the Spark loader, the adapter setup phases, and ``require_loaded_tables``)
    must read the flag through this one helper.
    """
    if getattr(type(benchmark), "SKIP_DATA_LOADING", False):
        return True
    if isinstance(benchmark, NonCallableMock):
        return False
    return bool(getattr(benchmark, "SKIP_DATA_LOADING", False))


def _holds_rows(rows: Any) -> bool:
    """Return True when a table stat reports a positive loaded row count."""
    return isinstance(rows, (int, float)) and not isinstance(rows, bool) and rows > 0


def require_loaded_tables(benchmark: Any, table_stats: dict[str, Any] | None) -> None:
    """Fail the run when a table the benchmark's queries need was not loaded.

    A benchmark lists those tables in ``REQUIRED_LOADED_TABLES``. Without this
    check a run that loaded the wrong dataset still measures: the schema DDL
    creates the required table empty, its queries succeed with no rows, and the
    result looks valid.

    Benchmarks without a pinned table list are still refused a vacuous load:
    when the benchmark expects data (anything but ``SKIP_DATA_LOADING``), zero
    loaded tables or zero loaded rows fail the run instead of validating
    vacuously.
    """
    if is_data_loading_skipped(benchmark):
        return
    required = getattr(benchmark, "REQUIRED_LOADED_TABLES", ())
    if not isinstance(required, (tuple, list, set, frozenset)):
        # A non-collection pin (notably None) names no tables, so it is
        # checked like the empty case below instead of returning early and
        # letting a zero-row load pass vacuously.
        required = ()
    loaded = {str(name).lower(): rows for name, rows in (table_stats or {}).items()}
    problems = []
    if not required:
        if not any(_holds_rows(rows) for rows in loaded.values()):
            problems.append("no rows were loaded for any table")
        else:
            # Without a pinned table list there is no per-table contract to
            # enforce, so a partial load (at least one table holding rows)
            # passes; the zero-row tables are logged for visibility instead
            # of failing the run.
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
