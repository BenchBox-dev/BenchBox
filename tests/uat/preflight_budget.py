"""Disk-budget estimator for UAT configs.

The checked-in TSV is an operator-maintained inventory from prior UAT
sweeps. Unknown cells stay visible in the estimate instead of being
treated as zero; preflight uses known peak demand as a headroom gate while
surfacing unknown coverage as an operator warning.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from tests.uat.config import UATConfig
from tests.uat.phases.enumerate import Cell, enumerate_cells

DEFAULT_TABLE_PATH = Path(__file__).resolve().parent / "data" / "disk_budget_table.tsv"


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


def format_disk_headroom_failure(check: DiskHeadroomCheck) -> str:
    """Operator-facing abort reason for disk-budget shortfalls."""
    details = "; ".join(
        f"{shortfall.label} {shortfall.path}: "
        f"{shortfall.free_gib:.1f} GiB free < {shortfall.required_gib:.1f} GiB required"
        for shortfall in check.shortfalls
    )
    return f"disk headroom gate failed: {details}"
