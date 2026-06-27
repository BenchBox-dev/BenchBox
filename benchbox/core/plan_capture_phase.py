"""Isolated, post-measurement query-plan capture phase.

Canonical capture contract (single source of truth)
---------------------------------------------------
Query plan capture is a FULLY SEPARATE and FULLY ISOLATED concern from the timed
measurement run. The target architecture (see
``_project/TODO/main/planning/query-plan-capture-canonical-isolation.yaml``, which
supersedes the additive ``query-plan-capture-isolation-phase-design``) is:

- **One capture path.** A single post-measurement isolated phase runs after all
  timed queries of every test type (power, throughput, maintenance, combined)
  complete. Capture is never interleaved with measurement and never runs inside a
  concurrent throughput stream.
- **One knob: ``analyze_plans``.** ``True`` re-runs each query once *after*
  measurement with EXPLAIN ANALYZE for full execution detail (writes stay on a
  non-ANALYZE EXPLAIN via the ``is_dml_query`` guard, so DML/CTAS is never
  re-executed); ``False`` captures the static (structural) EXPLAIN with no
  re-execution. There are no other capture knobs.
- **Capture once per query.** Each distinct executed query is captured exactly
  once — a plan is a property of ``(query, schema, engine)``, not of an execution
  — so the inline-era per-iteration / per-stream sampling machinery
  (``plan_first_n`` / ``plan_sampling_rate``) is not needed by this path.
- **Default eligibility ON for EXPLAIN-based engines.** Only engines whose plan is
  obtainable solely as a side effect of the measured job (BigQuery-class) are a
  genuine exception and keep a special path.
- **Connection reuse.** The measurement connection is reused so embedded
  ``:memory:`` engines still see the loaded data; isolation comes from running
  *post-measurement*, not from a second connection.

``run_plan_capture_phase()`` is the implementation of this phase.

Migration status (this is an umbrella in progress — see the canonical TODO):
the phase is the capture path for the EXPLAIN-based ``plan_capture_phase_eligible``
adapters in the power/standard path, and now honours ``analyze_plans`` (previously
it hard-coded structural-only, silently dropping ANALYZE timing for
``--capture-plans``). Remaining work tracked on the canonical TODO: default
eligibility ON for all EXPLAIN engines, running the phase for every test type,
removing the inline ``execute_query()`` capture path and the sampling machinery,
and collapsing the knob surface to ``analyze_plans``.

Key isolation properties of ``run_plan_capture_phase``:

- **Post-measurement**: the caller runs this after all power/throughput
  iterations, so EXPLAIN never delays a timed query.
- **Connection**: a fresh connection is opened via ``adapter.create_connection()``
  by default (so the phase cannot contaminate measurement transaction state);
  the integrated run path passes the measurement connection instead so embedded
  in-memory engines still see the loaded data.
- **Honours ``analyze_plans``**: the caller selects ANALYZE (full execution
  detail) vs. structural-only. With ANALYZE, adapters must downgrade DML to a
  non-ANALYZE EXPLAIN in ``get_query_plan()`` (DuckDB/MotherDuck/PostgreSQL do via
  ``is_dml_query``) so writes are never re-executed. The structural fingerprint is
  unaffected either way (it excludes timing/cardinality by design).
- **Capture once per query**: the explicit query list is the selection; each
  requested query is captured exactly once. (The inline-era per-iteration /
  per-stream sampling machinery — ``plan_first_n`` / ``plan_sampling_rate`` — has
  been retired; only the ``plan_query_filter`` query-selection set remains.)
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
    pairs: Iterable[tuple[str, str]] = queries.items() if isinstance(queries, Mapping) else queries
    return [(str(query_id), str(sql)) for query_id, sql in pairs]


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
            default that avoids contaminating measurement state. The integrated
            run orchestrator passes the measurement connection here instead, so
            embedded in-memory engines still see the loaded data.
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

    # Save the measurement-phase configuration so the phase can force capture on
    # without leaking that override back into the adapter.
    saved = {
        "analyze_plans": getattr(adapter, "analyze_plans", True),
        "capture_plans": getattr(adapter, "capture_plans", False),
    }

    phase_start = time.perf_counter()
    try:
        if owns_connection:
            connection = adapter.create_connection(**(dict(connection_config) if connection_config else {}))

        adapter.analyze_plans = analyze_plans
        adapter.capture_plans = True

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
        if close_connection and connection is not None:
            with contextlib.suppress(Exception):
                connection.close()

    result.total_capture_ms = (time.perf_counter() - phase_start) * 1000
    return result
