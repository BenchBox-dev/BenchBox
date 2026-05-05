"""Reuse-aware cleanup of `~/Developer/benchmark_runs/databases/`.

Implements the cleanup discipline the 2026-05-02 sweep operator
performed manually: preserve `datagen/` while later platforms can
reuse it, prune `databases/` only at safe reuse boundaries.

Source/scale boundary rule (from
_project/handoffs/results-explorer-uat-retrospective-20260502.md):
TPC-H loaded databases are reused by `read_primitives`,
`write_primitives`, `transaction_primitives`, and `ai_primitives`,
so a TPC-H load is only safe to prune after all consumers for that
scale have completed.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

# Benchmark → benchmarks that consume its loaded databases. Used to
# decide whether a per-platform mid-sweep prune is safe.
SOURCE_REUSE_GRAPH: dict[str, tuple[str, ...]] = {
    "tpch": (
        "tpch",
        "read_primitives",
        "write_primitives",
        "transaction_primitives",
        "ai_primitives",
    ),
    "tpcds": ("tpcds", "tpcds_obt"),
}


@dataclass(frozen=True)
class CellKey:
    platform: str
    benchmark: str
    scale: float


@dataclass(frozen=True)
class CleanupDecision:
    """Decision for a single (platform, source_benchmark, scale) prune candidate."""

    safe_to_prune: bool
    reason: str


def remaining_consumers(
    source_benchmark: str,
    completed_cells: list[CellKey],
    pending_cells: list[CellKey],
    *,
    platform: str,
    scale: float,
) -> list[CellKey]:
    """Return pending cells (same platform, same scale) that consume `source_benchmark`."""
    consumers = SOURCE_REUSE_GRAPH.get(source_benchmark, (source_benchmark,))
    out = []
    for cell in pending_cells:
        if cell.platform != platform:
            continue
        if cell.scale != scale:
            continue
        if cell.benchmark in consumers:
            out.append(cell)
    return out


def can_prune(
    source_benchmark: str,
    *,
    platform: str,
    scale: float,
    pending_cells: list[CellKey],
    completed_cells: list[CellKey],
) -> CleanupDecision:
    """Return a CleanupDecision for whether the loaded DB for (platform, source_benchmark, scale) can be pruned."""
    remaining = remaining_consumers(
        source_benchmark,
        completed_cells,
        pending_cells,
        platform=platform,
        scale=scale,
    )
    if remaining:
        names = ", ".join(f"{c.platform}/{c.benchmark}@{c.scale}" for c in remaining)
        return CleanupDecision(
            safe_to_prune=False,
            reason=f"{len(remaining)} pending consumer(s): {names}",
        )
    return CleanupDecision(
        safe_to_prune=True,
        reason=f"no pending consumers of {source_benchmark}@{scale}",
    )


def prune_database_dir(
    databases_root: Path,
    *,
    platform: str,
    benchmark: str,
    scale: float,
    dry_run: bool = False,
) -> int:
    """Remove loaded-database artefacts under databases_root for (platform, benchmark, scale).

    Returns the bytes-freed estimate (du-style sum). dry_run=True only
    measures and does not delete.
    """
    target = databases_root / platform / benchmark / str(scale)
    if not target.exists():
        return 0
    bytes_total = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
    if not dry_run:
        shutil.rmtree(target, ignore_errors=True)
    return bytes_total
