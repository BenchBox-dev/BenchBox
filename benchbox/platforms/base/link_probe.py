"""Post-benchmark client-to-platform link overhead probe.

Measures empirical statement round-trip overhead on an active connection.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

from __future__ import annotations

import logging
import statistics
import threading
from typing import Any

from benchbox.utils.clock import elapsed_seconds, mono_time

logger = logging.getLogger(__name__)


def _allowlisted_error(exc: BaseException) -> dict[str, Any]:
    """Build the published failure block for a probe error.

    Only the exception class name is published. Raw exception text can
    carry hostnames, IPs, credentials, or connection strings, so it is
    kept to the local debug log and never enters the result bundle.
    """
    logger.debug("Statement overhead probe failed: %r", exc)
    return {
        "collection_status": "partial",
        "source": "unavailable",
        "collection_error_class": type(exc).__name__,
        "collection_error_message": f"{type(exc).__name__}: statement overhead probe failed",
    }


def _run_samples(execute_one: Any, sample_count: int) -> list[float]:
    """Run 1 warmup plus ``sample_count`` timed statements."""
    execute_one()
    samples: list[float] = []
    for _ in range(sample_count):
        query_start = mono_time()
        execute_one()
        samples.append(elapsed_seconds(query_start) * 1000.0)
    return samples


def _sample_via_cursor(connection: Any, sample_count: int) -> list[float]:
    """Sample round trips through a DB-API cursor."""
    cursor = connection.cursor()
    try:

        def execute_one() -> None:
            cursor.execute("SELECT 1")
            fetchall = getattr(cursor, "fetchall", None)
            if callable(fetchall):
                fetchall()

        return _run_samples(execute_one, sample_count)
    finally:
        close = getattr(cursor, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _sample_via_query_api(connection: Any, timeout_seconds: float, sample_count: int) -> list[float]:
    """Sample round trips through a ``query()`` job API (e.g. BigQuery client).

    The job handle's ``result(timeout=...)`` enforces a per-statement bound,
    which DB-API cursors cannot provide portably.
    """
    per_statement_timeout = max(0.5, timeout_seconds / (sample_count + 1))

    def execute_one() -> None:
        job = connection.query("SELECT 1")
        result = getattr(job, "result", None)
        if callable(result):
            result(timeout=per_statement_timeout)
        elif hasattr(job, "__iter__"):
            list(job)

    return _run_samples(execute_one, sample_count)


def probe_statement_overhead(
    connection: Any,
    timeout_seconds: float = 5.0,
    sample_count: int = 5,
) -> dict[str, Any]:
    """Probe baseline statement round-trip overhead on the given connection.

    Discards 1 warmup query (`SELECT 1`), then executes `sample_count` measurement
    queries timing each in milliseconds.

    The whole probe is bounded by `timeout_seconds`: sampling runs on a daemon
    thread and the caller stops waiting after the deadline, so a hung
    `execute()` cannot hang a benchmark run that already succeeded.

    On timeout the worker may still hold the connection when this returns:
    callers must treat the connection as tainted (no further use except
    close) when `collection_error_class` is `"TimeoutError"`.

    Never raises exceptions: missing connections, non-standard clients, and
    execution failures return a partial/unavailable status with an allowlisted
    diagnostic (no raw error text enters the bundle).
    """
    if connection is None:
        return {
            "collection_status": "partial",
            "source": "unavailable",
            "collection_error_class": "ValueError",
            "collection_error_message": "ValueError: statement overhead probe failed",
        }

    cursor_factory = getattr(connection, "cursor", None)
    query_api = getattr(connection, "query", None)
    if not callable(cursor_factory) and not callable(query_api):
        return _allowlisted_error(
            AttributeError(f"{type(connection).__name__} connection has no callable cursor() or query() method")
        )

    outcome: dict[str, Any] = {}

    def _sample() -> None:
        try:
            # A connection left inside a failed transaction would fail every
            # probe statement with the backend's own error, masking the real
            # state in the published diagnostic. Reset defensively inside the
            # worker so the rollback itself is covered by the deadline; the
            # benchmark workload that used this connection has completed.
            rollback = getattr(connection, "rollback", None)
            if callable(rollback):
                try:
                    rollback()
                except Exception as exc:
                    logger.debug("Link probe pre-rollback skipped: %r", exc)
            if callable(cursor_factory):
                samples = _sample_via_cursor(connection, sample_count)
            else:
                samples = _sample_via_query_api(connection, timeout_seconds, sample_count)
            if not samples:
                raise RuntimeError("No statement overhead samples collected")
            outcome["result"] = {
                "collection_status": "available",
                "source": "observed",
                "statement_overhead_ms": {
                    "samples": len(samples),
                    "min": round(min(samples), 3),
                    "median": round(statistics.median(samples), 3),
                },
            }
        except Exception as exc:  # noqa: BLE001 - probe must never raise
            outcome["result"] = _allowlisted_error(exc)

    worker = threading.Thread(target=_sample, name="benchbox-link-probe", daemon=True)
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        return _allowlisted_error(TimeoutError(f"Statement overhead probe timed out after {timeout_seconds}s"))
    result = outcome.get("result")
    if not isinstance(result, dict):
        return _allowlisted_error(RuntimeError("Statement overhead probe produced no result"))
    return result


__all__ = [
    "probe_statement_overhead",
]
