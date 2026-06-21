"""Thread-safety tests for the plan_first_n iteration counter.

Under concurrent stream execution (``--streams > 1``) multiple threads call
``capture_query_plan()`` for the same query_id and run a read-increment-write
against ``_plan_capture_iteration_counts``. Without a lock that sequence can
interleave and capture more than ``plan_first_n`` plans. These tests hammer the
counter from many threads and assert ``plan_first_n`` is honoured exactly.
"""

from __future__ import annotations

import threading

import pytest

from benchbox.platforms.duckdb import DuckDBAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _StubPlan:
    """Minimal QueryPlanDAG stand-in for capture_query_plan()."""

    plan_fingerprint = "stub-fingerprint"

    def estimate_serialized_size(self) -> int:
        return 16

    def apply_raw_output_policy(self, policy: str | None = None, max_bytes: int = 0) -> None:
        """No-op: capture_query_plan applies the raw-output retention policy in place."""


class _StubParser:
    def parse_explain_output(self, query_id: str, explain_output: str) -> _StubPlan:
        return _StubPlan()


def _make_stubbed_adapter(monkeypatch, **config) -> DuckDBAdapter:
    """DuckDBAdapter whose EXPLAIN + parser are stubbed (no real database)."""
    adapter = DuckDBAdapter(capture_plans=True, **config)
    monkeypatch.setattr(adapter, "get_query_plan", lambda connection, query: "EXPLAIN OUTPUT")
    monkeypatch.setattr(adapter, "get_query_plan_parser", lambda: _StubParser())
    return adapter


def test_plan_first_n_honoured_under_concurrent_capture(monkeypatch):
    """N threads capturing the same query_id must yield exactly plan_first_n plans."""
    first_n = 5
    thread_count = 64
    adapter = _make_stubbed_adapter(monkeypatch, plan_first_n=first_n)

    barrier = threading.Barrier(thread_count)

    def worker() -> None:
        barrier.wait()  # maximise contention on the read-increment-write
        adapter.capture_query_plan(connection=object(), query="SELECT 1", query_id="Q1")

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # The counter is a global per-query-id count, not per-thread: every call
    # increments it, so it equals the number of invocations.
    assert adapter._plan_capture_iteration_counts["Q1"] == thread_count
    # Exactly plan_first_n captures should have produced a plan.
    assert adapter.query_plans_captured == first_n


def test_plan_first_n_counts_are_per_query_id(monkeypatch):
    """Distinct query_ids keep independent first-N budgets under concurrency."""
    first_n = 3
    per_query_threads = 20
    query_ids = ["Q1", "Q2", "Q3"]
    adapter = _make_stubbed_adapter(monkeypatch, plan_first_n=first_n)

    barrier = threading.Barrier(len(query_ids) * per_query_threads)

    def worker(query_id: str) -> None:
        barrier.wait()
        adapter.capture_query_plan(connection=object(), query="SELECT 1", query_id=query_id)

    threads = [threading.Thread(target=worker, args=(qid,)) for qid in query_ids for _ in range(per_query_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    for qid in query_ids:
        assert adapter._plan_capture_iteration_counts[qid] == per_query_threads
    # first_n per query_id across three query_ids.
    assert adapter.query_plans_captured == first_n * len(query_ids)
