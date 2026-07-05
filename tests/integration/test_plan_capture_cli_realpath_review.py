"""Real CLI round-trip for the plan-consumption surface (query-plan-capture review).

Covers the gap the mocked coverage tests (``test_show_plan_coverage.py``,
``test_compare_plans_coverage.py``) and the direct-``QueryPlanDAG.from_dict``
integration test (``test_plan_capture_e2e.py``) both leave open: neither drives
a real exported bundle through the real ``load_result_file`` -> CLI command path.

This test runs a real DuckDB workload with ``capture_plans=True``, exports it
through the production ``ResultExporter`` (``<run>.json`` + ``<run>.plans.json``),
and invokes the real ``show-plan``, ``compare-plans``, and ``compare
--include-plans`` Click commands against the on-disk bundle with no mocking of
``load_result_file``. Before the fix, all three commands crash with
``AttributeError: 'BenchmarkResults' object has no attribute 'phases'``
(swallowed by a bare ``except Exception`` into exit code 1).
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
    pytest.mark.duckdb,
]

_QUERIES = [
    ("q1", "SELECT i FROM range(5) t(i) WHERE i > 2"),
    ("q2", "SELECT count(*) AS c FROM range(5) t(i)"),
]
# Query IDs use the documented "q1"/"q2" style deliberately: the compact export
# format normalizes IDs (query_normalizer.normalize_query_id strips a leading
# "Q"/"q", so "q1" round-trips through a bundle as "1"), which exercises the
# --query-id normalization fix in show_plan.py/compare_plans.py below.


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


def _export_bundle(output_dir, execution_id: str):
    """Run the trivial workload with capture, export a real result bundle, return its main JSON path."""
    from benchbox.core.results.exporter import ResultExporter
    from tests.fixtures.result_dict_fixtures import make_benchmark_results

    captured = _run_queries(capture_plans=True)
    query_results = []
    for order, (query_id, _sql) in enumerate(_QUERIES, start=1):
        row = captured[query_id]
        assert row["status"] == "SUCCESS", f"{query_id} did not succeed: {row}"
        query_results.append(
            {
                "query_id": query_id,
                "status": "SUCCESS",
                "execution_order": order,
                "execution_time_ms": (row.get("execution_time_seconds") or 0.0) * 1000.0,
                "rows_returned": row.get("rows_returned", 0),
                "query_plan": row.get("query_plan"),
                "plan_fingerprint": row.get("plan_fingerprint"),
            }
        )

    results = make_benchmark_results(
        benchmark_id="plan-cli-realpath",
        benchmark_name="plan-cli-realpath",
        platform="duckdb",
        scale_factor=0.01,
        execution_id=execution_id,
        duration_seconds=0.0,
        total_queries=len(_QUERIES),
        successful_queries=len(_QUERIES),
        query_plans_captured=len(_QUERIES),
        query_results=query_results,
    )

    exporter = ResultExporter(output_dir=output_dir)
    exported = exporter.export_result(results, ["json"])
    return exported["json"]


class TestPlanCaptureCLIRealpath:
    """Drive show-plan / compare-plans / compare --include-plans through real bundles."""

    def test_show_plan_renders_from_real_bundle(self, tmp_path):
        """`benchbox show-plan --run <real bundle>` must exit 0 and render a plan."""
        from benchbox.cli.commands.show_plan import show_plan

        main_json = _export_bundle(tmp_path / "run1", "run1")
        result = CliRunner().invoke(show_plan, ["--run", str(main_json), "--query-id", "q1"])

        assert result.exit_code == 0, result.output
        assert "no attribute" not in result.output.lower()
        assert "Query Plan" in result.output

    def test_show_plan_json_format_from_real_bundle(self, tmp_path):
        """`--format json` must emit the real rehydrated plan, not an error."""
        from benchbox.cli.commands.show_plan import show_plan

        main_json = _export_bundle(tmp_path / "run1", "run1")
        result = CliRunner().invoke(show_plan, ["--run", str(main_json), "--query-id", "q2", "--format", "json"])

        assert result.exit_code == 0, result.output
        # The emitted plan is the QueryPlanDAG captured at execution time, whose own
        # query_id field retains the original "q2" (not the reconstructed result
        # dict's separately-normalized "query_id" of "2").
        assert '"query_id": "q2"' in result.output

    @pytest.mark.parametrize("requested_id", ["q1", "Q1", "1"])
    def test_show_plan_query_id_normalization(self, tmp_path, requested_id):
        """--query-id accepts any documented format (q1/Q1/1) against a normalized real bundle."""
        from benchbox.cli.commands.show_plan import show_plan

        main_json = _export_bundle(tmp_path / "run1", "run1")
        result = CliRunner().invoke(show_plan, ["--run", str(main_json), "--query-id", requested_id])

        assert result.exit_code == 0, result.output
        assert "not found" not in result.output.lower()

    def test_compare_plans_summary_from_real_bundles(self, tmp_path):
        """The deprecated `compare-plans --summary` path must work against real bundles."""
        from benchbox.cli.commands.compare_plans import compare_plans

        run1 = _export_bundle(tmp_path / "run1", "run1")
        run2 = _export_bundle(tmp_path / "run2", "run2")

        result = CliRunner().invoke(
            compare_plans,
            ["--run1", str(run1), "--run2", str(run2), "--summary"],
        )

        assert result.exit_code == 0, result.output
        assert "no attribute" not in result.output.lower()

    def test_compare_plans_explicit_query_id_normalization(self, tmp_path):
        """`compare-plans --query-id q1` must match a bundle whose reloaded ID normalized to "1"."""
        from benchbox.cli.commands.compare_plans import compare_plans

        run1 = _export_bundle(tmp_path / "run1", "run1")
        run2 = _export_bundle(tmp_path / "run2", "run2")

        result = CliRunner().invoke(
            compare_plans,
            ["--run1", str(run1), "--run2", str(run2), "--query-id", "q1"],
        )

        assert result.exit_code == 0, result.output
        assert "missing plan" not in result.output.lower()

    def test_compare_include_plans_from_real_bundles(self, tmp_path):
        """`benchbox compare <run1> <run2> --include-plans` - the recommended path - must exit 0."""
        from benchbox.cli.commands.compare import compare

        run1 = _export_bundle(tmp_path / "run1", "run1")
        run2 = _export_bundle(tmp_path / "run2", "run2")

        result = CliRunner().invoke(
            compare,
            [str(run1), str(run2), "--include-plans", "--non-interactive"],
        )

        assert result.exit_code == 0, result.output
        assert "no attribute" not in result.output.lower()

    def test_loaded_query_results_carry_rehydrated_plans(self, tmp_path):
        """load_result_file must reattach query_plan/plan_fingerprint from the .plans.json companion."""
        from benchbox.core.results.loader import iter_query_results, load_result_file
        from benchbox.core.results.query_plan_models import QueryPlanDAG

        main_json = _export_bundle(tmp_path / "run1", "run1")
        loaded, _raw = load_result_file(main_json)

        query_results = iter_query_results(loaded)
        assert len(query_results) == len(_QUERIES)
        for qr in query_results:
            plan = qr.get("query_plan")
            assert isinstance(plan, QueryPlanDAG), f"{qr.get('query_id')}: query_plan not rehydrated: {plan!r}"
            assert qr.get("plan_fingerprint"), f"{qr.get('query_id')}: plan_fingerprint missing after reload"
