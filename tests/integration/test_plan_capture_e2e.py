"""End-to-end test for the query plan capture pipeline.

Covers the full path without mocks or external credentials:
  DuckDB in-memory run with capture_plans=True
  → plan_fingerprint in result dict (64-char SHA-256 hex)
  → fingerprint stability across two identical runs
  → render_plan() returns non-empty tree
  → compare_query_plans() reports fingerprints_match for unchanged plans

``TestPlanCaptureBundlePipeline`` additionally drives the serialization
round-trip the adapter-level tests above do not: the captured plans are written
to a result bundle (``<run>.json`` + ``<run>.plans.json``) via the real
``ResultExporter``, rebuilt from the on-disk companion with the same
``QueryPlanDAG.from_dict`` deserializer, and fed through the same functions the
``show-plan`` (``render_plan``) and ``compare-plans`` (``compare_query_plans``)
commands delegate to. A regression in any intermediate step (result dict → JSON
bundle → rebuilt plan → render/compare) would be caught here — the gap the
adapter-level unit tests leave open.
"""

import re

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
    pytest.mark.duckdb,
]

_FP_RE = re.compile(r"^[a-f0-9]{64}$")
# Two STRUCTURALLY DISTINCT plans (filter+projection vs aggregate) over the
# zero-dependency ``range()`` table function, so the fingerprints genuinely
# differ — making the stability / comparison / per-query assertions discriminate
# between queries rather than passing on two identical trivial plans.
_QUERIES = [
    ("q1", "SELECT i FROM range(5) t(i) WHERE i > 2"),
    ("q2", "SELECT count(*) AS c FROM range(5) t(i)"),
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


def _export_bundle(output_dir, execution_id: str):
    """Run the trivial workload with capture, export a result bundle, return its main JSON path.

    Mirrors a real ``benchbox run --capture-plans`` without a subprocess: the
    DuckDB-captured plans flow into a ``BenchmarkResults`` and out through the
    production ``ResultExporter`` (``<run>.json`` + companion ``<run>.plans.json``).
    """
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
        benchmark_id="plan-e2e",
        benchmark_name="plan-e2e",
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


def _load_bundle_plans(main_json) -> dict[str, tuple[str, object]]:
    """Read a bundle's companion ``.plans.json`` and rehydrate each plan.

    Returns ``query_id -> (serialized_fingerprint, QueryPlanDAG)``. This is the
    serialization round-trip the ``show-plan`` / ``compare-plans`` commands rely on:
    the plan lives in the ``.plans.json`` companion and is rebuilt with the same
    ``QueryPlanDAG.from_dict`` the loader uses (``verify_fingerprint=True`` by
    default — it recomputes the fingerprint from the rebuilt tree and only marks the
    plan VERIFIED when that recompute matches the stored value), then handed to the
    same comparison / visualization functions the CLI delegates to.
    """
    import json

    from benchbox.core.results.query_plan_models import QueryPlanDAG

    plans_path = main_json.with_suffix(".plans.json")
    assert plans_path.exists(), "plans companion file was not written"
    doc = json.loads(plans_path.read_text(encoding="utf-8"))

    out: dict[str, tuple[str, object]] = {}
    for query_id, entry in doc["queries"].items():
        fingerprint = entry.get("fingerprint")
        out[query_id] = (fingerprint, QueryPlanDAG.from_dict(entry["plan"]))
    return out


class TestPlanCaptureBundlePipeline:
    """Full pipeline: run -> result bundle -> show-plan / compare-plans round-trip.

    These cover the serialization steps the adapter-level tests skip — captured
    plans written by the real ``ResultExporter`` and rebuilt from the on-disk
    bundle — then exercise the same underlying functions ``show-plan`` (render) and
    ``compare-plans`` (compare) delegate to. (The thin CLI wrappers themselves load
    the bundle through ``load_result_file``, which is tested separately at the unit
    level; here the focus is the bundle <-> plan-object serialization contract.)
    """

    def test_bundle_plans_companion_has_well_formed_fingerprints(self, tmp_path):
        """The exported bundle persists a 64-char hex fingerprint for every query."""
        import json

        main_json = _export_bundle(tmp_path / "run1", "run1")
        plans_path = main_json.with_suffix(".plans.json")
        assert plans_path.exists(), "plans companion file was not written"

        plans_doc = json.loads(plans_path.read_text(encoding="utf-8"))
        serialized = plans_doc["queries"]
        assert len(serialized) == len(_QUERIES)
        for query_id, entry in serialized.items():
            fp = entry.get("fingerprint") or entry.get("plan", {}).get("plan_fingerprint")
            assert fp is not None, f"no fingerprint serialized for {query_id}: {entry}"
            assert _FP_RE.match(fp), f"fingerprint for {query_id} is not 64-char hex: {fp!r}"

    def test_serialized_plan_rehydrates_with_verified_structure(self, tmp_path):
        """A plan rebuilt from the bundle recomputes a fingerprint matching disk.

        ``from_dict`` recomputes the fingerprint from the *rebuilt tree* and marks the
        plan VERIFIED only when it matches the stored value, so VERIFIED proves the
        operator tree survived serialization structurally — not merely that a copied
        scalar round-tripped.
        """
        from benchbox.core.results.query_plan_models import FingerprintIntegrity

        main_json = _export_bundle(tmp_path / "run1", "run1")
        rehydrated = _load_bundle_plans(main_json)
        assert len(rehydrated) == len(_QUERIES)
        for query_id, (stored_fp, plan) in rehydrated.items():
            assert stored_fp is not None and _FP_RE.match(stored_fp)
            assert plan.fingerprint_integrity == FingerprintIntegrity.VERIFIED, (
                f"{query_id}: rebuilt tree did not reproduce the stored fingerprint "
                f"(integrity={plan.fingerprint_integrity!r}) — serialization lost structure"
            )

    def test_distinct_queries_have_distinct_fingerprints(self, tmp_path):
        """The two workload queries serialize different fingerprints.

        Guards the discrimination the comparison/stability tests depend on: if both
        plans hashed equal, those tests could not distinguish a swapped or duplicated
        plan from a correct one.
        """
        rehydrated = _load_bundle_plans(_export_bundle(tmp_path / "run1", "run1"))
        fingerprints = {fp for fp, _plan in rehydrated.values()}
        assert len(fingerprints) == len(_QUERIES), f"queries collapsed to one fingerprint: {fingerprints}"

    def test_fingerprints_stable_across_bundles(self, tmp_path):
        """Two independent runs serialize identical fingerprints per query."""
        plans1 = _load_bundle_plans(_export_bundle(tmp_path / "run1", "run1"))
        plans2 = _load_bundle_plans(_export_bundle(tmp_path / "run2", "run2"))
        assert plans1 and plans1.keys() == plans2.keys()
        for query_id in plans1:
            assert plans1[query_id][0] == plans2[query_id][0], f"fingerprint for {query_id} changed across bundles"

    def test_show_plan_renders_from_bundle(self, tmp_path):
        """show-plan path: rebuild the plan from the bundle, render a non-empty tree."""
        from benchbox.core.query_plans.visualization import render_plan

        rehydrated = _load_bundle_plans(_export_bundle(tmp_path / "run1", "run1"))
        assert len(rehydrated) == len(_QUERIES), "not every query round-tripped a plan"
        for query_id, (_fp, plan) in rehydrated.items():
            rendered = render_plan(plan)
            assert isinstance(rendered, str) and rendered.strip(), f"empty render for {query_id}"

    def test_compare_plans_unchanged_across_bundles(self, tmp_path):
        """compare-plans path: two identical bundles report every plan unchanged."""
        from benchbox.core.query_plans.comparison import compare_query_plans

        plans1 = _load_bundle_plans(_export_bundle(tmp_path / "run1", "run1"))
        plans2 = _load_bundle_plans(_export_bundle(tmp_path / "run2", "run2"))

        shared = set(plans1) & set(plans2)
        assert shared, "no common queries with plans across the two bundles"
        for query_id in shared:
            comparison = compare_query_plans(plans1[query_id][1], plans2[query_id][1])
            assert comparison.fingerprints_match, f"{query_id} reported changed across identical bundles"
            assert comparison.plans_identical, f"{query_id} not identical across identical bundles"
