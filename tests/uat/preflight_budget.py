"""Disk-budget estimator for UAT configs.

The checked-in TSV is an operator-maintained inventory from prior UAT
sweeps. Unknown cells stay visible in the estimate instead of being
treated as zero; preflight uses known peak demand as a headroom gate while
surfacing unknown coverage as an operator warning.
"""

from __future__ import annotations

import csv
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from tests.uat.config import UATConfig
from tests.uat.phases.enumerate import Cell, enumerate_cells

DEFAULT_TABLE_PATH = Path(__file__).resolve().parent / "data" / "disk_budget_table.tsv"


def free_space_gib(path: str | Path) -> float:
    """Return free space at `path` in GiB.

    Single measurement primitive for all three UAT disk-policy sites: the
    preflight gate (`phases/preflight.py`), execute's platform-boundary check
    (`phases/execute.py`), and the orchestrator's per-cell disk-floor watch
    (`orchestrator.py`) -- see uat-execute-path-unification w6. The policy
    (what threshold, when to check, what to do on shortfall) stays distinct
    per site; only the measurement is shared.
    """
    p = Path(path).expanduser()
    if not p.exists():
        # Walk up to first existing ancestor so a missing log dir doesn't
        # falsely trigger the abort.
        p = next((ancestor for ancestor in p.parents if ancestor.exists()), Path("/"))
    usage = shutil.disk_usage(p)
    return usage.free / (1024**3)


@dataclass(frozen=True)
class DiskBudgetRow:
    """One observed disk envelope for a (platform, benchmark, scale) cell."""

    platform: str
    benchmark: str
    scale_factor: float
    peak_datagen_gib: float
    peak_database_gib: float
    transient_growth_gib: float


@dataclass(frozen=True)
class UnknownDiskCell:
    """A config cell absent from the advisory inventory."""

    platform: str
    benchmark: str
    scale: float

    @property
    def key(self) -> str:
        return cell_key(self.platform, self.benchmark, self.scale)


@dataclass(frozen=True)
class DiskBudget:
    """Estimated disk demand for a config."""

    cells: int
    est_peak_gib: float
    est_steady_gib: float
    unknown_cells: tuple[UnknownDiskCell, ...]


@dataclass(frozen=True)
class DiskRootFreeSpace:
    """Free-space observation for a required UAT disk root."""

    label: str
    path: Path
    free_gib: float


@dataclass(frozen=True)
class DiskHeadroomShortfall:
    """A required root that cannot fit the estimated disk budget."""

    label: str
    path: Path
    free_gib: float
    required_gib: float


@dataclass(frozen=True)
class DiskHeadroomCheck:
    """Disk-budget gate result for a set of required roots."""

    required_gib: float
    shortfalls: tuple[DiskHeadroomShortfall, ...]


BudgetTable = dict[tuple[str, str, float], DiskBudgetRow]


def cell_key(platform: str, benchmark: str, scale: float) -> str:
    """Stable manifest/table key for a UAT matrix cell."""
    return f"{platform}|{benchmark}|{scale:g}"


def load_budget_table(path: Path | None = None) -> BudgetTable:
    """Load the advisory disk-budget TSV.

    Extra columns are ignored so future inventories can carry provenance
    without changing the estimator contract.
    """
    table_path = path or DEFAULT_TABLE_PATH
    rows: BudgetTable = {}
    if not table_path.exists():
        return rows
    with table_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        required = {
            "platform",
            "benchmark",
            "scale_factor",
            "peak_datagen_gib",
            "peak_database_gib",
            "transient_growth_gib",
        }
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"disk budget table {table_path} missing columns: {sorted(missing)}")
        for row in reader:
            budget_row = DiskBudgetRow(
                platform=row["platform"],
                benchmark=row["benchmark"],
                scale_factor=float(row["scale_factor"]),
                peak_datagen_gib=float(row["peak_datagen_gib"]),
                peak_database_gib=float(row["peak_database_gib"]),
                transient_growth_gib=float(row["transient_growth_gib"]),
            )
            rows[(budget_row.platform, budget_row.benchmark, budget_row.scale_factor)] = budget_row
    return rows


def estimate_peak_disk(config: UATConfig, *, table_path: Path | None = None) -> DiskBudget:
    """Return an advisory disk estimate for all cells enumerated by *config*.

    Datagen is counted once per (benchmark, scale) because UAT reuses
    source data across platforms where possible. Database and transient
    growth are counted per cell. Unknown cells are reported separately;
    callers must not treat them as a hard gate.
    """
    return estimate_cells(enumerate_cells(config), table=load_budget_table(table_path))


def estimate_peak_disk_by_scale(config: UATConfig, *, table_path: Path | None = None) -> dict[float, DiskBudget]:
    """Return advisory disk estimates grouped by scale rung."""
    table = load_budget_table(table_path)
    cells_by_scale: dict[float, list[Cell]] = {}
    for cell in enumerate_cells(config):
        cells_by_scale.setdefault(cell.scale, []).append(cell)
    return {scale: estimate_cells(cells, table=table) for scale, cells in cells_by_scale.items()}


def estimate_largest_scale_peak_disk(config: UATConfig, *, table_path: Path | None = None) -> DiskBudget:
    """Return the disk estimate for the largest configured scale rung."""
    by_scale = estimate_peak_disk_by_scale(config, table_path=table_path)
    if not by_scale:
        return DiskBudget(cells=0, est_peak_gib=0.0, est_steady_gib=0.0, unknown_cells=())
    return by_scale[max(by_scale)]


def estimate_cells(cells: Iterable[Cell], *, table: BudgetTable) -> DiskBudget:
    """Estimate a concrete cell iterable; public for focused tests."""
    cells_tuple = tuple(cells)
    datagen_by_source: dict[tuple[str, float], float] = {}
    database_gib = 0.0
    transient_gib = 0.0
    unknown: list[UnknownDiskCell] = []

    for cell in cells_tuple:
        row = table.get((cell.platform, cell.benchmark, cell.scale))
        if row is None:
            unknown.append(UnknownDiskCell(cell.platform, cell.benchmark, cell.scale))
            continue
        datagen_key = (cell.benchmark, cell.scale)
        datagen_by_source[datagen_key] = max(datagen_by_source.get(datagen_key, 0.0), row.peak_datagen_gib)
        database_gib += row.peak_database_gib
        transient_gib += row.transient_growth_gib

    steady_gib = sum(datagen_by_source.values()) + database_gib
    return DiskBudget(
        cells=len(cells_tuple),
        est_peak_gib=steady_gib + transient_gib,
        est_steady_gib=steady_gib,
        unknown_cells=tuple(unknown),
    )


def check_disk_headroom(
    budget: DiskBudget,
    roots: Iterable[DiskRootFreeSpace],
    *,
    min_free_gib: float,
) -> DiskHeadroomCheck:
    """Compare an estimated peak budget against required disk roots."""
    required_gib = max(min_free_gib, budget.est_peak_gib)
    shortfalls = tuple(
        DiskHeadroomShortfall(root.label, root.path, root.free_gib, required_gib)
        for root in roots
        if root.free_gib < required_gib
    )
    return DiskHeadroomCheck(required_gib=required_gib, shortfalls=shortfalls)


def format_disk_budget(budget: DiskBudget) -> str:
    """One-line operator summary used by preflight CLI/sweep output."""
    return (
        "Disk budget estimate: "
        f"{budget.est_peak_gib:.2f} GiB peak "
        f"({budget.est_steady_gib:.2f} GiB steady; "
        f"cells={budget.cells}; unknown={len(budget.unknown_cells)})"
    )


def _largest_scale_cells(config: UATConfig) -> tuple[Cell, ...]:
    """Return the enumerated cells at the config's largest configured scale rung.

    Mirrors the selection `estimate_largest_scale_peak_disk` makes (peak
    concurrent database footprint is largest at the largest rung), factored
    out so `estimate_platform_chunking_budget` can group the same cell set
    by platform instead of summing it flat.
    """
    cells_by_scale: dict[float, list[Cell]] = {}
    for cell in enumerate_cells(config):
        cells_by_scale.setdefault(cell.scale, []).append(cell)
    if not cells_by_scale:
        return ()
    return tuple(cells_by_scale[max(cells_by_scale)])


@dataclass(frozen=True)
class PlatformChunkingBudget:
    """Per-platform disk math for `execute.platform_chunking` decisions.

    `concurrent_required_gib` is what today's non-chunked execute needs if
    every platform's loaded databases coexisted at once (11 platforms at
    ~15 GiB each was the 2026-08-04 release-gate stage-1 incident this
    estimator exists to catch before it happens again) -- numerically
    identical to `estimate_largest_scale_peak_disk(config).est_peak_gib`
    (same cells, same table, same dedup rule; see
    `estimate_platform_chunking_budget`).

    `per_platform_peak_gib` is the worst single platform's OWN loaded
    -database + transient-growth footprint -- deliberately excluding
    datagen, which `cleanup.preserve_datagen: true` keeps resident for the
    whole sweep regardless of chunking, so it is neither freed nor
    re-charged per platform. This is exactly what
    `cleanup.prune_platform_chunk` frees at a chunk boundary.

    `chunked_required_gib` is `per_platform_peak_gib` plus that
    always-resident datagen total -- the bound `execute.platform_chunking`
    enforces once a platform's databases are pruned before the next
    platform starts.

    All three are derived from the SAME table-driven estimator as
    `estimate_largest_scale_peak_disk` -- grouped by platform for the
    per-platform split, never re-summed per platform for datagen (datagen is
    shared/deduped globally, exactly like the flat estimate; summing a
    shared file's size once per platform that reuses it would silently
    inflate `concurrent_required_gib`) -- at the config's largest
    CONFIGURED `scales.rungs` entry, never a hardcoded flat per-platform
    constant. `basis` records that provenance for the lifecycle log.
    """

    platform_count: int
    per_platform_peak_gib: float
    concurrent_required_gib: float
    chunked_required_gib: float
    basis: str
    unknown_cells: tuple[UnknownDiskCell, ...]


def estimate_platform_chunking_budget(
    config: UATConfig,
    *,
    table_path: Path | None = None,
) -> PlatformChunkingBudget:
    """Estimate concurrent (all-platforms) vs chunked (one-platform) disk demand.

    Reuses `estimate_cells` for the authoritative concurrent total -- the
    same table-driven estimator, over the same largest-scale cell set, that
    `estimate_largest_scale_peak_disk` uses -- rather than adding a second,
    divergent estimator (see uat-disk-budget-and-platform-chunking prior
    art: extend, don't duplicate). A second, additive-only pass over the
    same cells splits the per-platform loaded-database/transient share out
    from the globally-deduped datagen share, which `DiskBudget` does not
    expose on its own; see `PlatformChunkingBudget` for why datagen must
    stay deduped rather than summed per platform.
    """
    table = load_budget_table(table_path)
    largest_cells = _largest_scale_cells(config)
    flat_budget = estimate_cells(largest_cells, table=table)

    database_transient_by_platform: dict[str, float] = defaultdict(float)
    for cell in largest_cells:
        row = table.get((cell.platform, cell.benchmark, cell.scale))
        if row is None:
            continue
        database_transient_by_platform[cell.platform] += row.peak_database_gib + row.transient_growth_gib

    platform_count = len(database_transient_by_platform)
    per_platform_peak_gib = max(database_transient_by_platform.values(), default=0.0)
    concurrent_required_gib = flat_budget.est_peak_gib
    datagen_gib = concurrent_required_gib - sum(database_transient_by_platform.values())
    chunked_required_gib = datagen_gib + per_platform_peak_gib
    scale = max((cell.scale for cell in largest_cells), default=None)
    if scale is None:
        basis = "no cells enumerated for the configured matrix; basis unavailable"
    else:
        basis = (
            f"disk_budget_table rows at scale={scale:g} "
            f"(largest of scales.rungs={config.scales.rungs}) across {platform_count} platform(s); "
            f"datagen (shared, resident regardless of chunking)={datagen_gib:.2f} GiB, "
            f"worst platform database+transient={per_platform_peak_gib:.2f} GiB, "
            f"sum-of-all-platforms database+transient={concurrent_required_gib - datagen_gib:.2f} GiB"
        )
    return PlatformChunkingBudget(
        platform_count=platform_count,
        per_platform_peak_gib=per_platform_peak_gib,
        concurrent_required_gib=concurrent_required_gib,
        chunked_required_gib=chunked_required_gib,
        basis=basis,
        unknown_cells=flat_budget.unknown_cells,
    )


def check_platform_chunking_headroom(
    budget: PlatformChunkingBudget,
    roots: Iterable[DiskRootFreeSpace],
    *,
    min_free_gib: float,
    chunking_enabled: bool,
) -> DiskHeadroomCheck:
    """Compare the platform-chunking budget against required disk roots.

    Gates against `concurrent_required_gib` when `chunking_enabled` is
    False (today's real risk: every platform's database can coexist) and
    against the much smaller `chunked_required_gib` when True (one
    platform's databases at a time, pruned between chunks).
    """
    required_gib = max(
        min_free_gib,
        budget.chunked_required_gib if chunking_enabled else budget.concurrent_required_gib,
    )
    shortfalls = tuple(
        DiskHeadroomShortfall(root.label, root.path, root.free_gib, required_gib)
        for root in roots
        if root.free_gib < required_gib
    )
    return DiskHeadroomCheck(required_gib=required_gib, shortfalls=shortfalls)


def recommend_platform_chunking(
    budget: PlatformChunkingBudget,
    roots: Iterable[DiskRootFreeSpace],
    *,
    min_free_gib: float,
) -> str:
    """Return an operator-facing platform-chunking recommendation.

    Three outcomes: chunking unnecessary (every platform's database fits
    concurrently), chunking recommended (fits only with between-platform
    pruning), or a hard failure with the computed shortfall against the
    chunked requirement -- callers should fail preflight rather than let an
    under-provisioned sweep pass and exhaust disk mid-sweep (see
    uat-disk-budget-and-platform-chunking anti-pattern).
    """
    roots = tuple(roots)
    unchunked = check_platform_chunking_headroom(budget, roots, min_free_gib=min_free_gib, chunking_enabled=False)
    if not unchunked.shortfalls:
        return (
            "platform_chunking not required: concurrent disk budget "
            f"({unchunked.required_gib:.2f} GiB, basis: {budget.basis}) fits available headroom"
        )
    chunked = check_platform_chunking_headroom(budget, roots, min_free_gib=min_free_gib, chunking_enabled=True)
    if not chunked.shortfalls:
        return (
            "platform_chunking recommended: concurrent disk budget "
            f"({unchunked.required_gib:.2f} GiB) exceeds headroom, but the chunked "
            f"per-platform footprint ({chunked.required_gib:.2f} GiB, basis: {budget.basis}) fits -- "
            "set execute.platform_chunking: true"
        )
    return (
        "insufficient disk even with execute.platform_chunking: "
        f"{format_disk_headroom_failure(chunked)} (basis: {budget.basis})"
    )


def format_disk_headroom_failure(check: DiskHeadroomCheck) -> str:
    """Operator-facing abort reason for disk-budget shortfalls."""
    details = "; ".join(
        f"{shortfall.label} {shortfall.path}: "
        f"{shortfall.free_gib:.1f} GiB free < {shortfall.required_gib:.1f} GiB required"
        for shortfall in check.shortfalls
    )
    return f"disk headroom gate failed: {details}"
