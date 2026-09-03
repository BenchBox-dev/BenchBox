"""Post-benchmark client-to-platform link overhead probe.

Measures empirical statement round-trip overhead on an active connection.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

from benchbox.utils.clock import elapsed_seconds, mono_time

logger = logging.getLogger(__name__)


def probe_statement_overhead(
    connection: Any,
    timeout_seconds: float = 5.0,
    sample_count: int = 5,
) -> dict[str, Any]:
    """Probe baseline statement round-trip overhead on the given connection.

    Discards 1 warmup query (`SELECT 1`), then executes `sample_count` measurement
    queries timing each in milliseconds. Bounded by `timeout_seconds` monotonic deadline.

    Never raises exceptions: non-standard connection objects (e.g. BigQuery client)
    or execution failures return partial unavailable status.
    """
    if connection is None:
        return {
            "collection_status": "partial",
            "source": "unavailable",
            "collection_error_class": "ValueError",
            "collection_error_message": "No active database connection provided for link probe",
        }

    try:
        cursor_factory = getattr(connection, "cursor", None)
        if not callable(cursor_factory):
            raise AttributeError(f"{type(connection).__name__} connection has no callable cursor() method")

        cursor = cursor_factory()
        try:
            start_mono = mono_time()
            deadline = start_mono + timeout_seconds

            # Discard 1 warmup query
            if mono_time() >= deadline:
                raise TimeoutError(f"Statement overhead probe timed out before warmup after {timeout_seconds}s")
            cursor.execute("SELECT 1")
            if hasattr(cursor, "fetchall") and callable(cursor.fetchall):
                cursor.fetchall()

            samples: list[float] = []
            for _ in range(sample_count):
                if mono_time() >= deadline:
                    raise TimeoutError(f"Statement overhead probe timed out after {timeout_seconds}s")
                query_start = mono_time()
                cursor.execute("SELECT 1")
                if hasattr(cursor, "fetchall") and callable(cursor.fetchall):
                    cursor.fetchall()
                duration_ms = elapsed_seconds(query_start) * 1000.0
                samples.append(duration_ms)

            if not samples:
                raise RuntimeError("No statement overhead samples collected")

            return {
                "collection_status": "available",
                "source": "observed",
                "statement_overhead_ms": {
                    "samples": len(samples),
                    "min": round(min(samples), 3),
                    "median": round(statistics.median(samples), 3),
                },
            }
        finally:
            if hasattr(cursor, "close") and callable(cursor.close):
                try:
                    cursor.close()
                except Exception:
                    pass
    except Exception as exc:
        raw_msg = str(exc)
        # Scrub network identifiers for security
        import re

        msg = re.sub(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b", "<IP_REDACTED>", raw_msg)
        msg = re.sub(r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b", "<MAC_REDACTED>", msg)
        msg = re.sub(r"\b(?:vpc-[0-9a-fA-F]+)\b", "<VPC_REDACTED>", msg)
        msg = re.sub(
            r"\b([a-zA-Z0-9-]+\.)+(?:com|net|org|io|cloud|aws|azure|gcp|internal|local)\b",
            "<HOST_REDACTED>",
            msg,
            flags=re.IGNORECASE,
        )
        msg = re.sub(r":\d{2,5}\b", ":<PORT_REDACTED>", msg)

        return {
            "collection_status": "partial",
            "source": "unavailable",
            "collection_error_class": type(exc).__name__,
            "collection_error_message": msg,
        }


__all__ = [
    "probe_statement_overhead",
]
