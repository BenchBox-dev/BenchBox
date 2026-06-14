"""Guardrails for the external-root datagen-leak invariant.

Regression coverage for the 2026-06-01 incident: a run configured for an
external output root (``BENCHBOX_OUTPUT_DIR``) leaked ~4.2 GB of datagen
artifacts into the worktree-local ``benchmark_runs/datagen/``. The
output-root propagation fix (PR #780) closed that; these tests fail loudly
if the invariant is ever broken again.

The lightweight "generation path" is the pure-Python CoffeeShop generator at
a tiny scale factor — it honors ``get_benchmark_runs_datagen_path`` (and thus
``BENCHBOX_OUTPUT_DIR``) and runs in well under a second.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchbox.core.coffeeshop.generator import CoffeeShopDataGenerator
from tests.uat.artifact_hygiene import (
    LocalArtifactGrowthError,
    assert_no_local_growth,
    audit_local_datagen,
    configured_external_root,
    dir_size_bytes,
    local_runs_root,
    snapshot_local_runs,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _isolated_roots(tmp_path: Path) -> tuple[Path, Path]:
    """Return (worktree_cwd, external_root) as siblings so neither nests in the other."""
    worktree = tmp_path / "worktree"
    external = tmp_path / "external_runs"
    worktree.mkdir()
    external.mkdir()
    return worktree, external


def test_external_root_run_does_not_grow_local_benchmark_runs(monkeypatch, tmp_path):
    """A lightweight generation run with an external root must not touch cwd/benchmark_runs."""
    worktree, external = _isolated_roots(tmp_path)
    monkeypatch.chdir(worktree)
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(external))

    # Sanity: the guardrail considers this an external-root run.
    resolved = configured_external_root(cwd=worktree)
    assert resolved == external.resolve()

    before = snapshot_local_runs(worktree)
    assert before.total_bytes == 0

    generator = CoffeeShopDataGenerator(scale_factor=0.0001, compress_data=False)
    tables = generator.generate_data()

    # Datagen landed under the external root, not the worktree.
    order_lines_parent = Path(tables["order_lines"]).parent
    assert order_lines_parent.is_relative_to(external)
    assert dir_size_bytes(external) > 0

    # The invariant: cwd/benchmark_runs did not grow. Raises loudly otherwise.
    assert_no_local_growth(before, external, cwd=worktree)
    assert not local_runs_root(worktree).exists()


def test_assert_no_local_growth_flags_a_simulated_leak(monkeypatch, tmp_path):
    """If datagen leaks into cwd/benchmark_runs, the guardrail fails and names both paths."""
    worktree, external = _isolated_roots(tmp_path)
    monkeypatch.chdir(worktree)
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(external))

    before = snapshot_local_runs(worktree)

    # Simulate the incident shape: artifacts accumulating under the local tree.
    leaked = local_runs_root(worktree) / "datagen" / "coffeeshop_sf00001" / "order_lines.csv"
    leaked.parent.mkdir(parents=True)
    leaked.write_bytes(b"x" * 4096)

    with pytest.raises(LocalArtifactGrowthError) as excinfo:
        assert_no_local_growth(before, external, cwd=worktree)

    message = str(excinfo.value)
    assert str(local_runs_root(worktree)) in message
    assert str(external) in message
    assert "PR #780" in message
    # Report-only: the leaked artifact is left in place for inspection.
    assert leaked.exists()


def test_configured_external_root_skips_default_local_runs(monkeypatch, tmp_path):
    """No env/flag, or an output root inside the worktree, is treated as a local run."""
    worktree, _external = _isolated_roots(tmp_path)
    monkeypatch.chdir(worktree)
    monkeypatch.delenv("BENCHBOX_OUTPUT_DIR", raising=False)

    # No configuration at all.
    assert configured_external_root(cwd=worktree) is None

    # Empty env var does not count as configured.
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", "")
    assert configured_external_root(cwd=worktree) is None

    # A root *inside* the worktree is a local run, not external.
    inside = worktree / "benchmark_runs"
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(inside))
    assert configured_external_root(cwd=worktree) is None


def test_audit_local_datagen_is_noop_without_external_root(monkeypatch, tmp_path):
    """The preflight gate must never block ordinary default local runs."""
    worktree, _external = _isolated_roots(tmp_path)
    monkeypatch.delenv("BENCHBOX_OUTPUT_DIR", raising=False)

    # Even with pre-existing local datagen, no external root => no-op.
    leaked = local_runs_root(worktree) / "datagen" / "tpch_sf1" / "lineitem.tbl"
    leaked.parent.mkdir(parents=True)
    leaked.write_bytes(b"x" * 1024)

    assert audit_local_datagen(cwd=worktree) is None


def test_audit_local_datagen_reports_existing_local_artifacts(monkeypatch, tmp_path):
    """With an external root configured, pre-existing local datagen is reported."""
    worktree, external = _isolated_roots(tmp_path)
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(external))

    leaked = local_runs_root(worktree) / "datagen" / "tpch_sf1" / "lineitem.tbl"
    leaked.parent.mkdir(parents=True)
    leaked.write_bytes(b"x" * 8192)

    message = audit_local_datagen(cwd=worktree, output=str(external))
    assert message is not None
    assert str(local_runs_root(worktree) / "datagen") in message
    assert str(external) in message
    # Threshold above the leak size suppresses the report.
    assert audit_local_datagen(cwd=worktree, output=str(external), threshold_bytes=8192) is None
