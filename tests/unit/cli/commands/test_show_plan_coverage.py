"""Coverage tests for cli/commands/show_plan.py."""

from __future__ import annotations

import importlib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from benchbox.core.results.canonical_json import canonical_json_text
from benchbox.core.results.query_plan_models import LogicalOperator, LogicalOperatorType, QueryPlanDAG
from benchbox.core.results.schema import build_plans_payload, build_result_payload
from tests.fixtures.result_dict_fixtures import make_benchmark_results

mod = importlib.import_module("benchbox.cli.commands.show_plan")

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _make_results(query_id: str = "q1", has_plan: bool = True):
    """Build a real BenchmarkResults instance (not a fabricated `.phases` fake)."""
    plan = SimpleNamespace(to_dict=lambda: {"node": "scan"}) if has_plan else None
    query_result: dict = {"query_id": query_id}
    if plan is not None:
        query_result["query_plan"] = plan
    return make_benchmark_results(query_results=[query_result])


def _write_real_bundle(tmp_path: Path, query_id: str = "1") -> Path:
    """Write a REAL on-disk v2 bundle (main file + .plans.json companion) with a
    genuine QueryPlanDAG, so a test can drive show-plan through the actual
    ``load_result_file`` -> reconstruct -> companion-rehydrate path with NO
    monkeypatching (qpc-11 w1: one real-loader test per CLI).
    """
    root = LogicalOperator(operator_type=LogicalOperatorType.SCAN, operator_id="scan_1", table_name="lineitem")
    plan = QueryPlanDAG(query_id=query_id, platform="duckdb", logical_root=root)
    results = make_benchmark_results(
        benchmark_id="tpch",
        benchmark_name="tpch",
        platform="duckdb",
        scale_factor=1.0,
        execution_id="show-plan-real",
        timestamp=datetime(2025, 1, 1, 12, 0, 0),
        duration_seconds=1.0,
        total_queries=1,
        successful_queries=1,
        query_plans_captured=1,
        query_results=[
            {
                "query_id": query_id,
                "status": "SUCCESS",
                "execution_time_ms": 100.0,
                "rows_returned": 4,
                "query_plan": plan,
                "plan_fingerprint": plan.plan_fingerprint,
            }
        ],
    )
    main_path = tmp_path / "r.json"
    main_path.write_text(canonical_json_text(build_result_payload(results)), encoding="utf-8")
    plans_payload = build_plans_payload(results)
    assert plans_payload is not None
    (tmp_path / "r.plans.json").write_text(canonical_json_text(plans_payload), encoding="utf-8")
    return main_path


def _make_load(results):
    """Return a load_result_file stub yielding (results, {})."""
    return lambda _p: (results, {})


def _write(path: Path, payload: str = "{}") -> None:
    path.write_text(payload, encoding="utf-8")


def test_show_plan_tree_summary_and_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "r.json"
    _write(p)
    monkeypatch.setattr(mod, "load_result_file", _make_load(_make_results()))
    monkeypatch.setattr(mod, "render_plan", lambda *_a, **_k: "TREE")
    monkeypatch.setattr(mod, "render_summary", lambda *_a, **_k: "SUMMARY")

    r1 = CliRunner().invoke(mod.show_plan, ["--run", str(p), "--query-id", "q1", "--format", "tree"])
    assert r1.exit_code == 0
    r2 = CliRunner().invoke(mod.show_plan, ["--run", str(p), "--query-id", "q1", "--format", "summary"])
    assert r2.exit_code == 0
    r3 = CliRunner().invoke(mod.show_plan, ["--run", str(p), "--query-id", "q1", "--format", "json"])
    assert r3.exit_code == 0
    assert '"node": "scan"' in r3.output


def test_show_plan_uses_load_result_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """show-plan must use load_result_file (which also loads the companion .plans.json)."""
    p = tmp_path / "r.json"
    _write(p)
    calls = []

    def _spy(path):
        calls.append(path)
        return (_make_results(), {})

    monkeypatch.setattr(mod, "load_result_file", _spy)
    monkeypatch.setattr(mod, "render_plan", lambda *_a, **_k: "TREE")
    CliRunner().invoke(mod.show_plan, ["--run", str(p), "--query-id", "q1"])
    assert len(calls) == 1


def test_show_plan_missing_query_and_plan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    p = tmp_path / "r.json"
    _write(p)

    monkeypatch.setattr(mod, "load_result_file", _make_load(_make_results(query_id="q2", has_plan=True)))
    miss_q = CliRunner().invoke(mod.show_plan, ["--run", str(p), "--query-id", "q1"])
    assert miss_q.exit_code == 1

    monkeypatch.setattr(mod, "load_result_file", _make_load(_make_results(query_id="q1", has_plan=False)))
    miss_p = CliRunner().invoke(mod.show_plan, ["--run", str(p), "--query-id", "q1"])
    assert miss_p.exit_code == 1


def test_show_plan_real_loader_renders_plan_from_bundle(tmp_path: Path) -> None:
    """End-to-end through the REAL loader: no load_result_file monkeypatch.

    Proves the CLI works against an actual on-disk bundle -- the companion
    .plans.json is discovered, the plan is rehydrated into a real QueryPlanDAG,
    and JSON output carries its structure. A fabricated fake that merely
    defined the attributes the CLI reads would pass its other tests while this
    real path stayed broken (the exact F8.1 masking this item targets).
    """
    main_path = _write_real_bundle(tmp_path, query_id="1")

    result = CliRunner().invoke(mod.show_plan, ["--run", str(main_path), "--query-id", "1", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert '"logical_root"' in result.output
    assert '"lineitem"' in result.output


def test_show_plan_load_error_and_verbose_exception(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # File that causes load_result_file to fail (bad JSON → ResultLoadError → caught as Exception)
    bad = tmp_path / "bad.json"
    _write(bad, "{bad")
    out = CliRunner().invoke(mod.show_plan, ["--run", str(bad), "--query-id", "q1"])
    assert out.exit_code == 1

    p = tmp_path / "ok.json"
    _write(p)
    monkeypatch.setattr(mod, "load_result_file", _make_load(_make_results(query_id="q1", has_plan=True)))
    monkeypatch.setattr(mod, "render_plan", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    res = CliRunner().invoke(mod.show_plan, ["--run", str(p), "--query-id", "q1"], obj={"verbose": True})
    assert res.exit_code == 1
    assert isinstance(res.exception, RuntimeError)
