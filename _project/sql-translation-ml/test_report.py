import json

import curves
from evaluate import report
from experiment import write_json


def test_supplemental_repairs_do_not_change_primary_comparisons(tmp_path, monkeypatch):
    monkeypatch.setattr(curves, "plot", lambda run: None)
    for system in ("sqlglot", "benchbox", "full", "edit"):
        success = system in ("full", "edit")
        rows = [
            {"case_id": f"{dialect}/{suite}", "source": dialect, "suite": suite, "eligible": True, "success": success}
            for dialect in ("duckdb", "sqlite")
            for suite in ("test", "supplemental")
        ]
        (tmp_path / f"evaluation-{system}.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
        )
        metric = {
            "k": int(success),
            "n": 1,
            "decision_lower": 0.0,
            "sufficient_families": False,
            "long_input_count": 0,
            "all_fixtures_empty_count": 0,
            "median_seconds": 0.1,
            "p95_seconds": 0.1,
            "existing_workload": {"k": int(success), "n": 1},
            "breakdowns": {},
        }
        write_json(
            tmp_path / f"evaluation-{system}.json",
            {
                "directions": {dialect: dict(metric) for dialect in ("duckdb", "sqlite")},
                "cold_seconds": 0.1,
                "peak_sampled_rss": 100,
                "model_identity": None,
            },
        )
    report(tmp_path)
    manifest = json.loads((tmp_path / "run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["comparisons"]["full/sqlglot/duckdb"] == {"repaired": 1, "broken": 0}
    assert "does not support" in (tmp_path / "verdict.md").read_text(encoding="utf-8")
