"""Fast-test coverage for tests/uat/cleanup.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.uat import cleanup

pytestmark = pytest.mark.fast


def test_source_reuse_graph_comes_from_registry_metadata():
    graph = cleanup.source_reuse_graph()

    assert graph["tpch"] == (
        "tpch",
        "read_primitives",
        "write_primitives",
        "transaction_primitives",
        "ai_primitives",
    )
    assert graph["tpcds"] == ("tpcds", "tpcds_obt")


def test_can_prune_blocks_when_consumer_pending():
    pending = [cleanup.CellKey("duckdb", "read_primitives", 0.01)]
    decision = cleanup.can_prune(
        "tpch",
        platform="duckdb",
        scale=0.01,
        pending_cells=pending,
        completed_cells=[],
    )
    assert decision.safe_to_prune is False
    assert "read_primitives" in decision.reason


def test_can_prune_allows_when_consumers_done():
    decision = cleanup.can_prune(
        "tpch",
        platform="duckdb",
        scale=0.01,
        pending_cells=[],
        completed_cells=[cleanup.CellKey("duckdb", "tpch", 0.01)],
    )
    assert decision.safe_to_prune is True


def test_can_prune_ignores_other_platform_consumers():
    pending = [cleanup.CellKey("sqlite", "read_primitives", 0.01)]
    decision = cleanup.can_prune(
        "tpch",
        platform="duckdb",
        scale=0.01,
        pending_cells=pending,
        completed_cells=[],
    )
    assert decision.safe_to_prune is True


def test_can_prune_unknown_source_only_blocks_on_self_consumers():
    pending = [cleanup.CellKey("duckdb", "ssb", 0.01)]
    decision = cleanup.can_prune(
        "ssb",
        platform="duckdb",
        scale=0.01,
        pending_cells=pending,
        completed_cells=[],
    )
    # ssb has no registry data-source consumers; only the same-name
    # consumer blocks pruning.
    assert decision.safe_to_prune is False


def test_prune_database_dir_dry_run_returns_size_without_delete(tmp_path: Path):
    target = tmp_path / "duckdb" / "tpch" / "0.01"
    target.mkdir(parents=True)
    (target / "loaded.db").write_bytes(b"x" * 4096)
    bytes_freed = cleanup.prune_database_dir(tmp_path, platform="duckdb", benchmark="tpch", scale=0.01, dry_run=True)
    assert bytes_freed == 4096
    assert target.exists()


def test_prune_database_dir_actually_deletes(tmp_path: Path):
    target = tmp_path / "duckdb" / "tpch" / "0.01"
    target.mkdir(parents=True)
    (target / "loaded.db").write_bytes(b"x" * 1024)
    bytes_freed = cleanup.prune_database_dir(tmp_path, platform="duckdb", benchmark="tpch", scale=0.01)
    assert bytes_freed == 1024
    assert not target.exists()


def test_prune_database_dir_missing_target_returns_zero(tmp_path: Path):
    bytes_freed = cleanup.prune_database_dir(tmp_path, platform="duckdb", benchmark="tpch", scale=0.01)
    assert bytes_freed == 0
