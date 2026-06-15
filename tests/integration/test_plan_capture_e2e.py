"""End-to-end test for the query plan capture pipeline.

Covers the full path without mocks or external credentials:
  DuckDB in-memory run with capture_plans=True
  → plan_fingerprint in result dict (64-char SHA-256 hex)
  → fingerprint stability across two identical runs
  → render_plan() returns non-empty tree
  → compare_query_plans() reports fingerprints_match for unchanged plans
"""

import re

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
    pytest.mark.duckdb,
]

_FP_RE = re.compile(r"^[a-f0-9]{64}$")
_QUERIES = [
    ("q1", "SELECT 1"),
    ("q2", "SELECT 1 + 1"),
]


def _run_queries(capture_plans: bool) -> dict[str, dict]:
    """Run _QUERIES through a fresh DuckDB in-memory adapter; return results keyed by query_id."""
    from benchbox.platforms.duckdb import DuckDBAdapter

    adapter = DuckDBAdapter(capture_plans=capture_plans)
    conn = adapter.create_connection()
    results: dict[str, dict] = {}
    try:
        for query_id, query in _QUERIES:
            results[query_id] = adapter.execute_query(
                connection=conn,
                query=query,
                query_id=query_id,
                validate_row_count=False,
            )
    finally:
        adapter.close_connection(conn)
    return results


class TestPlanCaptureE2E:
    def test_fingerprints_present_and_well_formed(self):
        """Each result has a 64-char hex fingerprint."""
        results = _run_queries(capture_plans=True)
        for query_id, _ in _QUERIES:
            result = results[query_id]
            assert result["status"] == "SUCCESS", f"{query_id} did not succeed: {result}"
            fp = result.get("plan_fingerprint")
            assert fp is not None, f"plan_fingerprint missing for {query_id}"
            assert _FP_RE.match(fp), f"plan_fingerprint for {query_id} is not a 64-char hex: {fp!r}"

    def test_fingerprints_stable_across_runs(self):
        """Running the same queries twice produces identical fingerprints."""
        run1 = _run_queries(capture_plans=True)
        run2 = _run_queries(capture_plans=True)
        for query_id, _ in _QUERIES:
            fp1 = run1[query_id].get("plan_fingerprint")
            fp2 = run2[query_id].get("plan_fingerprint")
            assert fp1 is not None and fp2 is not None
            assert fp1 == fp2, f"Fingerprint for {query_id} changed between runs: {fp1!r} != {fp2!r}"

    def test_no_fingerprint_without_capture(self):
        """capture_plans=False must not produce a fingerprint."""
        results = _run_queries(capture_plans=False)
        for query_id, _ in _QUERIES:
            result = results[query_id]
            assert result.get("plan_fingerprint") is None, (
                f"Unexpected fingerprint on {query_id} when capture_plans=False"
            )

    def test_render_plan_returns_non_empty_string(self):
        """render_plan() should return a non-empty ASCII tree string."""
        from benchbox.core.query_plans.visualization import render_plan

        results = _run_queries(capture_plans=True)
        for query_id, _ in _QUERIES:
            plan = results[query_id].get("query_plan")
            assert plan is not None, f"query_plan missing for {query_id}"
            rendered = render_plan(plan)
            assert isinstance(rendered, str) and rendered.strip(), f"render_plan() returned empty output for {query_id}"

    def test_compare_plans_fingerprints_match(self):
        """compare_query_plans() must report fingerprints_match=True for identical runs."""
        from benchbox.core.query_plans.comparison import compare_query_plans

        run1 = _run_queries(capture_plans=True)
        run2 = _run_queries(capture_plans=True)
        for query_id, _ in _QUERIES:
            plan1 = run1[query_id].get("query_plan")
            plan2 = run2[query_id].get("query_plan")
            assert plan1 is not None and plan2 is not None
            comparison = compare_query_plans(plan1, plan2)
            assert comparison.fingerprints_match, (
                f"compare_query_plans() reported fingerprints differ for {query_id} "
                f"across identical runs; fingerprints: "
                f"{run1[query_id]['plan_fingerprint']!r} vs "
                f"{run2[query_id]['plan_fingerprint']!r}"
            )
