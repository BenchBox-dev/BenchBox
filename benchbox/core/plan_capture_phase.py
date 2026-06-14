"""Isolated, post-measurement query-plan capture phase.

Plan capture is intended to be a *separate* phase of a benchmark run, decoupled
from the timed power/throughput measurement. The legacy path captures plans
inline inside each adapter's ``execute_query()`` (guarded by ``capture_plans``),
which interleaves EXPLAIN with the timed query and — for ANALYZE-based adapters
(DuckDB, MotherDuck, PostgreSQL) — contends on the same connection.

This module provides the additive building block for the phased model:
``run_plan_capture_phase()`` captures plans *after* measurement is complete,
using a fresh connection and structural-only EXPLAIN (no ANALYZE re-execution).
It is intentionally additive — the inline path stays in place so platforms that
surface plans as an execution side effect (BigQuery job stats, Spark event logs)
keep working. See ``_project/TODO/main/planning/
query-plan-capture-isolation-phase-design.yaml`` for the full design note.

Key isolation properties:

- **Post-measurement**: the caller runs this after all power/throughput
  iterations, so EXPLAIN never delays a timed query.
- **Separate connection** (default): a fresh connection is opened via
  ``adapter.create_connection()`` so the phase cannot contaminate measurement
  transaction state. Callers may pass an existing ``connection`` to opt out.
- **Structural-only**: ``analyze_plans`` is forced to ``False`` for the phase,
  so DML/CTAS queries are never re-executed and SELECT queries pay only the
  planning cost rather than ~1x execution time. The structural fingerprint is
  unaffected (it excludes timing/cardinality by design).
- **Filter-independent**: the measurement-phase sampling filters
  (``plan_first_n``, ``plan_sampling_rate``) are bypassed so each requested
  query is captured exactly once; the explicit query list is the selection.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlanCapturePhaseResult:
    """Outcome of an isolated plan-capture phase.

    Attributes:
        plans: query_id -> parsed ``QueryPlanDAG`` for queries captured.
        fingerprints: query_id -> structural ``plan_fingerprint``.
        per_query_capture_ms: query_id -> wall-clock ms spent on that capture.
        total_capture_ms: wall-clock ms for the whole phase (incl. connection).
        captured: number of queries with a parsed plan.
        failed: number of queries whose capture failed (no plan parsed).
    """

    plans: dict[str, Any] = field(default_factory=dict)
    fingerprints: dict[str, str] = field(default_factory=dict)
    per_query_capture_ms: dict[str, float] = field(default_factory=dict)
    total_capture_ms: float = 0.0
    captured: int = 0
    failed: int = 0


def _normalize_queries(queries: Mapping[str, str] | Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Coerce the queries argument into an ordered list of ``(query_id, sql)``."""
    if isinstance(queries, Mapping):
        return list(queries.items())
    return [(str(qid), sql) for qid, sql in queries]


def run_plan_capture_phase(
    adapter: Any,
    queries: Mapping[str, str] | Iterable[tuple[str, str]],
    *,
    connection: Any | None = None,
    connection_config: Mapping[str, Any] | None = None,
    analyze_plans: bool = False,
    close_connection: bool | None = None,
) -> PlanCapturePhaseResult:
    """Capture query plans in an isolated phase, decoupled from measurement.

    Intended to run *after* all power/throughput iterations complete. For each
    ``(query_id, sql)`` it calls ``adapter.capture_query_plan()`` and collects
    the parsed plan, fingerprint, and per-query capture time.

    Args:
        adapter: A platform adapter exposing ``capture_query_plan()`` and (when
            opening its own connection) ``create_connection()``.
        queries: Mapping of ``query_id -> sql`` or an iterable of
            ``(query_id, sql)`` pairs. Order is preserved.
        connection: An existing connection to capture against. When ``None``
            (default), a fresh connection is opened via
            ``adapter.create_connection(**connection_config)`` — the isolation
            default that avoids contaminating measurement state.
        connection_config: kwargs forwarded to ``create_connection()`` when a
            fresh connection is opened. Ignored if ``connection`` is provided.
        analyze_plans: Whether the phase should run ANALYZE-based EXPLAIN.
            Defaults to ``False`` (structural plan only, no re-execution cost);
            ANALYZE belongs to the measurement phase, not the capture phase.
        close_connection: Whether to close the connection when done. Defaults to
            ``True`` when this function opened the connection and ``False`` when
            the caller supplied one.

    Returns:
        A :class:`PlanCapturePhaseResult` with plans, fingerprints, and timing.
    """
    items = _normalize_queries(queries)
    result = PlanCapturePhaseResult()

    owns_connection = connection is None
    if close_connection is None:
        close_connection = owns_connection

    # Save the measurement-phase configuration so the phase can run structural,
    # filter-free capture without leaking that override back into the adapter.
    saved = {
        "analyze_plans": getattr(adapter, "analyze_plans", True),
        "capture_plans": getattr(adapter, "capture_plans", False),
        "plan_first_n": getattr(adapter, "plan_first_n", None),
        "plan_sampling_rate": getattr(adapter, "plan_sampling_rate", None),
    }

    phase_start = time.perf_counter()
    try:
        if owns_connection:
            connection = adapter.create_connection(**(dict(connection_config) if connection_config else {}))

        adapter.analyze_plans = analyze_plans
        adapter.capture_plans = True
        # The explicit query list is the selection for this phase; bypass the
        # measurement-phase sampling filters so each query is captured once.
        adapter.plan_first_n = None
        adapter.plan_sampling_rate = None

        for query_id, sql in items:
            plan, capture_ms = adapter.capture_query_plan(connection, sql, query_id)
            result.per_query_capture_ms[query_id] = capture_ms
            if plan is not None:
                result.plans[query_id] = plan
                result.fingerprints[query_id] = plan.plan_fingerprint
                result.captured += 1
            else:
                result.failed += 1
    finally:
        adapter.analyze_plans = saved["analyze_plans"]
        adapter.capture_plans = saved["capture_plans"]
        adapter.plan_first_n = saved["plan_first_n"]
        adapter.plan_sampling_rate = saved["plan_sampling_rate"]
        if close_connection and connection is not None:
            with contextlib.suppress(Exception):
                connection.close()

    result.total_capture_ms = (time.perf_counter() - phase_start) * 1000
    return result
