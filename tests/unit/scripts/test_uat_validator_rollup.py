"""Tests for scripts/uat_validator_rollup.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchbox.validation.bundle import discover_bundles
from scripts.uat_validator_rollup import (
    CLI_REFUSED_COMPLIANCE_CLASSES,
    TSV_HEADER,
    build_rows,
    format_footer,
    main,
    render_tsv,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "uat_rollup"


def _bundle(
    *,
    platform: str,
    benchmark: str = "tpch",
    scale: float = 0.01,
    compliance_class: str = "official",
    queries: list[dict] | None = None,
    cost_status: str = "not_applicable_local",
    extra_cost: dict | None = None,
) -> dict:
    if queries is None:
        queries = [
            {"id": "Q1", "ms": 100, "status": "pass"},
            {"id": "Q2", "ms": 200, "status": "pass"},
        ]
    out: dict = {
        "version": "2.1",
        "run": {"id": "abc", "timestamp": "2026-05-03T00:00:00", "total_duration_ms": 1000},
        "benchmark": {
            "id": benchmark,
            "scale_factor": scale,
            "compliance_class": compliance_class,
        },
        "platform": {"name": platform, "version": "0.0.0"},
        "summary": {"validation": "passed", "queries": {"total": len(queries), "passed": len(queries), "failed": 0}},
        "queries": queries,
        "normalized_cost": {
            "normalized_cost_usd": "0",
            "cost_model_version": "2026.05.0",
            "cost_model_source": "benchbox.core.cost.pricing",
            "cost_scope": "compute_only",
            "cost_status": cost_status,
            "billing_unit": "not_applicable",
            "pricing_region": "not_applicable",
        },
    }
    if extra_cost is not None:
        out["cost"] = extra_cost
    return out


def test_fixture_dir_one_third_clean_rate():
    """Smoke test against the checked-in fixture set: 1 clean, 2 error."""
    bundles = discover_bundles(FIXTURE_DIR)
    rows = build_rows(bundles)
    by_status = {r.validator_status: 0 for r in rows}
    for r in rows:
        by_status[r.validator_status] += 1

    assert len(rows) == 3
    assert by_status.get("clean") == 1
    assert by_status.get("error") == 2

    footer = format_footer(rows)
    overall = footer[0]
    assert "total=3" in overall
    assert "submittable=3" in overall
    assert "clean=1" in overall
    assert "validator_clean_rate=33.3%" in overall


def test_categorisation_matches_validator(tmp_path: Path):
    """Each per-bundle status should follow validate_submission's verdict."""
    clean = _bundle(platform="DuckDB")
    cost_err = _bundle(platform="DataFusion", cost_status="unavailable", extra_cost={"total_usd": "1.50"})
    zero_timing = _bundle(
        platform="Polars",
        queries=[{"id": "Q1", "ms": 0, "status": "pass"}, {"id": "Q2", "ms": 0, "status": "pass"}],
    )
    refused = _bundle(platform="DuckDB", benchmark="tpcds", compliance_class="unofficial_subscale")

    for name, payload in [
        ("clean", clean),
        ("cost_err", cost_err),
        ("zero", zero_timing),
        ("refused", refused),
    ]:
        (tmp_path / f"{name}.json").write_text(json.dumps(payload))

    rows = build_rows(sorted(tmp_path.glob("*.json")))
    statuses = {Path(r.result_path).stem: r.validator_status for r in rows}

    assert statuses["clean"] == "clean"
    assert statuses["cost_err"] == "error"
    assert statuses["zero"] == "error"
    assert statuses["refused"] == "refused-by-cli"


def test_refused_compliance_classes_are_complete():
    """Guard against a future compliance_class addition silently slipping through."""
    assert {"unofficial_subscale", "unofficial_nonstandard"} == CLI_REFUSED_COMPLIANCE_CLASSES


def test_refused_bundles_excluded_from_clean_rate_denominator(tmp_path: Path):
    clean = _bundle(platform="DuckDB")
    refused = _bundle(platform="DuckDB", benchmark="tpcds", compliance_class="unofficial_subscale")
    (tmp_path / "clean.json").write_text(json.dumps(clean))
    (tmp_path / "refused.json").write_text(json.dumps(refused))

    rows = build_rows(sorted(tmp_path.glob("*.json")))
    overall = format_footer(rows)[0]

    assert "total=2" in overall
    assert "submittable=1" in overall
    assert "validator_clean_rate=100.0%" in overall


def test_render_tsv_includes_header_and_rows(tmp_path: Path):
    (tmp_path / "b.json").write_text(json.dumps(_bundle(platform="DuckDB")))
    rows = build_rows(sorted(tmp_path.glob("*.json")))
    output = render_tsv(rows)

    assert output.startswith(TSV_HEADER + "\n")
    assert "DuckDB\ttpch\t0.01" in output
    assert output.rstrip().splitlines()[-1].startswith("# benchmark=tpch")


def test_main_writes_to_output_file(tmp_path: Path, capsys):
    (tmp_path / "b.json").write_text(json.dumps(_bundle(platform="DuckDB")))
    out_path = tmp_path / "rollup.tsv"

    rc = main([str(tmp_path), "--output", str(out_path)])
    assert rc == 0
    assert capsys.readouterr().out == ""
    written = out_path.read_text()
    assert written.startswith(TSV_HEADER + "\n")
    assert "validator_clean_rate=" in written


def test_main_stdout(tmp_path: Path, capsys):
    (tmp_path / "b.json").write_text(json.dumps(_bundle(platform="DuckDB")))

    rc = main([str(tmp_path), "--output", "-"])
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out.startswith(TSV_HEADER + "\n")


def test_newer_filter_skips_old_bundles(tmp_path: Path):
    import os

    sentinel = tmp_path / ".sweep_start"
    sentinel.write_text("")
    sentinel_mtime = sentinel.stat().st_mtime

    old = tmp_path / "old.json"
    old.write_text(json.dumps(_bundle(platform="DuckDB")))
    os.utime(old, (sentinel_mtime - 60, sentinel_mtime - 60))

    new = tmp_path / "new.json"
    new.write_text(json.dumps(_bundle(platform="DataFusion")))
    os.utime(new, (sentinel_mtime + 60, sentinel_mtime + 60))

    rc = main([str(tmp_path), "--output", "-", "--newer", str(sentinel)])
    assert rc == 0


def test_missing_path_returns_nonzero(tmp_path: Path):
    rc = main([str(tmp_path / "does-not-exist")])
    assert rc != 0
