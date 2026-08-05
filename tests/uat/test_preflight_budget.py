"""Fast tests for the UAT disk-budget estimator."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.uat.config import validate_config
from tests.uat.preflight_budget import (
    DiskBudget,
    DiskRootFreeSpace,
    check_disk_headroom,
    check_platform_chunking_headroom,
    estimate_largest_scale_peak_disk,
    estimate_peak_disk,
    estimate_platform_chunking_budget,
    format_disk_budget,
    format_disk_headroom_failure,
    recommend_platform_chunking,
)

pytestmark = pytest.mark.fast


def test_estimate_peak_disk_counts_datagen_once_and_reports_unknown(tmp_path: Path):
    table = tmp_path / "disk_budget.tsv"
    table.write_text(
        "platform\tbenchmark\tscale_factor\tpeak_datagen_gib\tpeak_database_gib\ttransient_growth_gib\n"
        "duckdb\ttpch\t0.01\t1.0\t2.0\t0.5\n"
        "sqlite\ttpch\t0.01\t1.5\t3.0\t0.25\n",
        encoding="utf-8",
    )
    cfg = validate_config(
        {
            "name": "budget-smoke",
            "platforms": {"include": ["duckdb", "sqlite", "datafusion"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )

    budget = estimate_peak_disk(cfg, table_path=table)

    assert budget.cells == 3
    assert budget.est_steady_gib == pytest.approx(1.5 + 2.0 + 3.0)
    assert budget.est_peak_gib == pytest.approx(1.5 + 2.0 + 3.0 + 0.5 + 0.25)
    assert [cell.key for cell in budget.unknown_cells] == ["datafusion|tpch|0.01"]


def test_format_disk_budget_includes_operator_fields(tmp_path: Path):
    table = tmp_path / "disk_budget.tsv"
    table.write_text(
        "platform\tbenchmark\tscale_factor\tpeak_datagen_gib\tpeak_database_gib\ttransient_growth_gib\n"
        "duckdb\ttpch\t0.01\t1.0\t2.0\t0.5\n",
        encoding="utf-8",
    )
    cfg = validate_config(
        {
            "name": "budget-smoke",
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
        }
    )

    line = format_disk_budget(estimate_peak_disk(cfg, table_path=table))

    assert line.startswith("Disk budget estimate: ")
    assert "GiB peak" in line
    assert "cells=1" in line
    assert "unknown=0" in line


def test_estimate_largest_scale_peak_disk_uses_largest_configured_scale(tmp_path: Path):
    table = tmp_path / "disk_budget.tsv"
    table.write_text(
        "platform\tbenchmark\tscale_factor\tpeak_datagen_gib\tpeak_database_gib\ttransient_growth_gib\n"
        "duckdb\ttpch\t0.01\t1.0\t2.0\t0.5\n"
        "duckdb\ttpch\t1\t10.0\t20.0\t5.0\n"
        "sqlite\ttpch\t1\t12.0\t30.0\t7.0\n",
        encoding="utf-8",
    )
    cfg = validate_config(
        {
            "name": "budget-smoke",
            "platforms": {"include": ["duckdb", "sqlite"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01, 1]},
        }
    )

    budget = estimate_largest_scale_peak_disk(cfg, table_path=table)

    assert budget.cells == 2
    assert budget.est_steady_gib == pytest.approx(12.0 + 20.0 + 30.0)
    assert budget.est_peak_gib == pytest.approx(12.0 + 20.0 + 30.0 + 5.0 + 7.0)
    assert budget.unknown_cells == ()


def test_disk_headroom_gate_reports_short_root(tmp_path: Path):
    budget = DiskBudget(cells=1, est_peak_gib=10.0, est_steady_gib=8.0, unknown_cells=())
    # Render the expectation from the same Path the formatter receives: str(Path) uses
    # the platform separator, so a hardcoded "/tmp" fails on Windows ("\tmp") while
    # asserting nothing extra. Mirrors the idiom already used in test_preflight.py.
    tmp_root = Path("/tmp")
    roots = (
        DiskRootFreeSpace("tmp", tmp_root, 4.0),
        DiskRootFreeSpace("output", tmp_path, 20.0),
    )

    check = check_disk_headroom(budget, roots, min_free_gib=5.0)

    assert check.required_gib == pytest.approx(10.0)
    assert len(check.shortfalls) == 1
    assert check.shortfalls[0].label == "tmp"
    assert f"tmp {tmp_root}: 4.0 GiB free < 10.0 GiB required" in format_disk_headroom_failure(check)


# ---------------------------------------------------------------------------
# execute.platform_chunking: per-platform database term
# (uat-disk-budget-and-platform-chunking).
# ---------------------------------------------------------------------------


def _three_platform_table(tmp_path: Path) -> Path:
    """A table with a distinct largest-scale (1.0) database footprint per
    platform, plus a smaller scale rung, so tests can prove the estimator
    picks the LARGEST configured rung, groups by platform (not a flat sum),
    and never falls back to a hardcoded constant."""
    table = tmp_path / "disk_budget.tsv"
    table.write_text(
        "platform\tbenchmark\tscale_factor\tpeak_datagen_gib\tpeak_database_gib\ttransient_growth_gib\n"
        "duckdb\ttpch\t0.01\t0.1\t0.2\t0.05\n"
        "duckdb\ttpch\t1\t2.0\t20.0\t1.0\n"
        "sqlite\ttpch\t1\t2.0\t30.0\t1.0\n"
        "datafusion\ttpch\t1\t2.0\t15.0\t1.0\n",
        encoding="utf-8",
    )
    return table


def _three_platform_config():
    return validate_config(
        {
            "name": "chunk-budget-smoke",
            "platforms": {"include": ["duckdb", "sqlite", "datafusion"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01, 1]},
        }
    )


def test_estimate_platform_chunking_budget_accounts_for_platform_count(tmp_path: Path):
    table = _three_platform_table(tmp_path)
    cfg = _three_platform_config()

    budget = estimate_platform_chunking_budget(cfg, table_path=table)

    # Grouped by platform at the largest configured rung (1.0) -- not the
    # smaller 0.01 rung, and not a flat sum over every cell regardless of
    # platform.
    assert budget.platform_count == 3
    # datagen is shared/deduped once per (benchmark, scale) -- all three
    # platforms' tpch@1.0 rows share the SAME 2.0 GiB, matching the flat
    # estimator's dedup rule (`estimate_cells`), not summed once per
    # platform (that would silently inflate concurrent_required_gib by
    # double/triple-counting a file that is only ever generated once).
    datagen_gib = 2.0
    # per_platform_peak_gib is the worst platform's OWN database + transient
    # only -- datagen is excluded because cleanup.preserve_datagen keeps it
    # resident regardless of chunking, so pruning a platform's chunk never
    # frees it (matches what cleanup.prune_platform_chunk actually frees).
    assert budget.per_platform_peak_gib == pytest.approx(30.0 + 1.0)  # sqlite: worst platform
    assert budget.concurrent_required_gib == pytest.approx(datagen_gib + (20.0 + 1.0) + (30.0 + 1.0) + (15.0 + 1.0))
    assert budget.chunked_required_gib == pytest.approx(datagen_gib + budget.per_platform_peak_gib)
    # Basis records the derivation (config scale rung + row provenance), not
    # a bare number -- an operator reading the lifecycle log must be able to
    # tell this wasn't a hardcoded constant.
    assert "scale=1" in budget.basis
    assert "3 platform" in budget.basis


def test_estimate_platform_chunking_budget_concurrent_matches_flat_estimator(tmp_path: Path):
    """concurrent_required_gib must never diverge from the existing flat gate.

    Regression guard for the datagen-dedup bug caught in review: grouping
    per platform must not re-sum a shared datagen file once per platform
    that reuses it. `estimate_largest_scale_peak_disk` is the existing,
    already-trusted flat estimate `phases/preflight.py` gates on today --
    `concurrent_required_gib` must equal it exactly, not merely be close.
    """
    table = _three_platform_table(tmp_path)
    cfg = _three_platform_config()

    budget = estimate_platform_chunking_budget(cfg, table_path=table)
    flat = estimate_largest_scale_peak_disk(cfg, table_path=table)

    assert budget.concurrent_required_gib == pytest.approx(flat.est_peak_gib)


def test_check_platform_chunking_headroom_fails_unchunked_passes_chunked(tmp_path: Path):
    table = _three_platform_table(tmp_path)
    cfg = _three_platform_config()
    budget = estimate_platform_chunking_budget(cfg, table_path=table)

    # Enough room for the single worst platform's chunk (plus the
    # always-resident datagen) but not for all three platforms coexisting
    # (unchunked) -- the exact 2026-08-04 release-gate stage-1 shape (11
    # platforms x ~15 GiB > free, but any single platform would have fit).
    free_gib = budget.chunked_required_gib + 5.0
    assert free_gib < budget.concurrent_required_gib
    roots = (DiskRootFreeSpace("output", tmp_path, free_gib),)

    unchunked = check_platform_chunking_headroom(budget, roots, min_free_gib=5.0, chunking_enabled=False)
    chunked = check_platform_chunking_headroom(budget, roots, min_free_gib=5.0, chunking_enabled=True)

    assert len(unchunked.shortfalls) == 1
    assert unchunked.shortfalls[0].required_gib == pytest.approx(budget.concurrent_required_gib)
    assert chunked.shortfalls == ()
    assert chunked.required_gib == pytest.approx(budget.chunked_required_gib)


def test_recommend_platform_chunking_not_required_when_concurrent_fits(tmp_path: Path):
    table = _three_platform_table(tmp_path)
    cfg = _three_platform_config()
    budget = estimate_platform_chunking_budget(cfg, table_path=table)
    roots = (DiskRootFreeSpace("output", tmp_path, budget.concurrent_required_gib + 10.0),)

    message = recommend_platform_chunking(budget, roots, min_free_gib=5.0)

    assert message.startswith("platform_chunking not required")


def test_recommend_platform_chunking_recommended_when_only_chunked_fits(tmp_path: Path):
    table = _three_platform_table(tmp_path)
    cfg = _three_platform_config()
    budget = estimate_platform_chunking_budget(cfg, table_path=table)
    roots = (DiskRootFreeSpace("output", tmp_path, budget.chunked_required_gib + 5.0),)

    message = recommend_platform_chunking(budget, roots, min_free_gib=5.0)

    assert message.startswith("platform_chunking recommended")
    assert "execute.platform_chunking: true" in message


def test_recommend_platform_chunking_fails_with_computed_shortfall_even_chunked(tmp_path: Path):
    table = _three_platform_table(tmp_path)
    cfg = _three_platform_config()
    budget = estimate_platform_chunking_budget(cfg, table_path=table)
    # Not even the single worst platform's chunk fits.
    free_gib = budget.chunked_required_gib - 5.0
    roots = (DiskRootFreeSpace("output", tmp_path, free_gib),)

    message = recommend_platform_chunking(budget, roots, min_free_gib=5.0)

    assert message.startswith("insufficient disk even with execute.platform_chunking")
    # The computed shortfall (not a vague "not enough disk") is present:
    # required GiB, free GiB, and the root label all appear.
    assert f"{budget.chunked_required_gib:.1f} GiB required" in message
    assert f"{free_gib:.1f} GiB free" in message
    assert "output" in message
