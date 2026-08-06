"""Disk-budget estimator for UAT configs.

The checked-in TSV is an operator-maintained inventory from prior UAT
sweeps. Unknown cells stay visible in the estimate instead of being
treated as zero; preflight uses known peak demand as a headroom gate while
surfacing unknown coverage as an operator warning.

**Every number this module produces is a LOWER BOUND, never a
certification.** The inventory is partial in two independent ways, and
`assess_budget_coverage` / `format_budget_coverage` exist so neither can
be mistaken for zero demand:

1. Cells with no row at all are counted as `DiskBudget.unknown_cells` and
   contribute 0 GiB. As of 2026-08 the checked-in table covers four
   platforms (`clickhouse-local`, `datafusion`, `duckdb`, `lakesail`) out
   of the ~11 a `sql`-group sweep enumerates.
2. Rows whose `peak_database_gib` is a placeholder rather than a
   measurement, flagged by the optional `peak_database_gib_status` column
   (see `DiskBudgetRow.database_status`). As of 2026-08 EVERY checked-in
   row carries `peak_database_gib = 0.000000` with status `unmeasured`,
   so the loaded-database term of the estimate is identically zero and
   the whole budget is essentially the datagen term alone.

Consequence for callers: refusing a sweep because even this lower bound
does not fit is always sound. Passing it means only "no shortfall
detected against the measured subset" -- it does NOT mean the sweep fits.
Filling in (2) requires a real measured sweep; do not substitute a
guessed per-platform constant, which would convert a disclosed gap into
an undisclosed fabrication.
"""

from __future__ import annotations

import csv
import shutil
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


DATABASE_STATUS_MEASURED = "measured"
DATABASE_STATUS_UNMEASURED = "unmeasured"


@dataclass(frozen=True)
class DiskBudgetRow:
    """One observed disk envelope for a (platform, benchmark, scale) cell.

    `database_status` records whether `peak_database_gib` is a real
    observation or a placeholder, read from the optional
    `peak_database_gib_status` TSV column. It defaults to
    `DATABASE_STATUS_MEASURED` so a table without the column keeps its
    historical meaning, but the checked-in inventory sets every row to
    `DATABASE_STATUS_UNMEASURED` -- its `peak_database_gib` zeros are "we
    never measured this", NOT "these databases are free" (see the module
    docstring). Only a real measured sweep may flip a row to `measured`.
    """

    platform: str
    benchmark: str
    scale_factor: float
    peak_datagen_gib: float
    peak_database_gib: float
    transient_growth_gib: float
    database_status: str = DATABASE_STATUS_MEASURED

    @property
    def database_measured(self) -> bool:
        return self.database_status == DATABASE_STATUS_MEASURED


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
    without changing the estimator contract, with one exception: the
    optional `peak_database_gib_status` column is read into
    `DiskBudgetRow.database_status`. It is how the inventory declares that
    a `peak_database_gib` value is a placeholder rather than a
    measurement, and every row of the checked-in table currently declares
    `unmeasured` -- so the loaded-database term of every estimate this
    module produces is zero for want of data, not because the databases
    are small. `assess_budget_coverage` turns that into an operator-facing
    disclosure; nothing here silently treats it as a real zero.
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
                database_status=(row.get("peak_database_gib_status") or DATABASE_STATUS_MEASURED).strip().lower(),
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


def largest_scale_cells(config: UATConfig) -> tuple[Cell, ...]:
    """Return the enumerated cells at the config's largest configured scale rung.

    The same cell set `estimate_largest_scale_peak_disk` estimates, exposed
    so `assess_budget_coverage` reports coverage of exactly what the gate
    gated on rather than of a differently-selected population.
    """
    cells_by_scale: dict[float, list[Cell]] = {}
    for cell in enumerate_cells(config):
        cells_by_scale.setdefault(cell.scale, []).append(cell)
    if not cells_by_scale:
        return ()
    return tuple(cells_by_scale[max(cells_by_scale)])


@dataclass(frozen=True)
class DiskBudgetCoverage:
    """How much of a `DiskBudget` rests on measured data rather than absence.

    Two independent gaps, counted separately because they fail differently
    (see the module docstring):

    - `cells_with_rows` / `cells_total` and `measured_platforms` /
      `platforms_total`: cells the inventory has no row for at all. These
      contribute 0 GiB to the estimate.
    - `cells_with_measured_database` / `cells_total`: cells whose row
      exists but whose `peak_database_gib` is a declared placeholder. These
      contribute a real datagen figure and a fictitious 0 GiB database
      figure.

    `is_lower_bound` is true when either gap is non-empty, which is the
    signal callers must use to avoid reporting a passing gate as "fits".
    """

    cells_total: int
    cells_with_rows: int
    cells_with_measured_database: int
    platforms_total: int
    measured_platforms: tuple[str, ...]
    unmeasured_platforms: tuple[str, ...]

    @property
    def is_lower_bound(self) -> bool:
        """True when the estimate omits demand it could not measure."""
        return self.cells_with_rows < self.cells_total or self.cells_with_measured_database < self.cells_total


def assess_budget_coverage(cells: Iterable[Cell], *, table: BudgetTable) -> DiskBudgetCoverage:
    """Report which of *cells* the budget table actually measures.

    A platform counts as measured only when EVERY one of its cells has a
    row AND every one of those rows declares a measured
    `peak_database_gib`. Anything weaker would let a platform with one
    datagen row and no database measurement read as covered, which is the
    exact "modelled as 0" failure this exists to prevent.
    """
    cells_tuple = tuple(cells)
    platforms = sorted({cell.platform for cell in cells_tuple})
    cells_with_rows = 0
    cells_with_measured_database = 0
    unmeasured: set[str] = set()
    for cell in cells_tuple:
        row = table.get((cell.platform, cell.benchmark, cell.scale))
        if row is None:
            unmeasured.add(cell.platform)
            continue
        cells_with_rows += 1
        if row.database_measured:
            cells_with_measured_database += 1
        else:
            unmeasured.add(cell.platform)
    return DiskBudgetCoverage(
        cells_total=len(cells_tuple),
        cells_with_rows=cells_with_rows,
        cells_with_measured_database=cells_with_measured_database,
        platforms_total=len(platforms),
        measured_platforms=tuple(p for p in platforms if p not in unmeasured),
        unmeasured_platforms=tuple(p for p in platforms if p in unmeasured),
    )


_MAX_LISTED_PLATFORMS = 6


def format_budget_coverage(coverage: DiskBudgetCoverage) -> str:
    """One-line operator disclosure of what the budget estimate does not know.

    Deliberately never says "fits". A complete estimate is stated as
    complete; anything else is stated as a lower bound, naming the
    unmeasured platforms so the operator can tell "measured and fine" from
    "mostly unmeasured".
    """
    if coverage.cells_total == 0:
        return "Disk budget coverage: no cells enumerated for this config; nothing measured and nothing gated"
    if not coverage.is_lower_bound:
        return (
            "Disk budget coverage: COMPLETE -- measured rows cover all "
            f"{coverage.cells_total} largest-scale cell(s) across all "
            f"{coverage.platforms_total} platform(s)"
        )
    listed = coverage.unmeasured_platforms[:_MAX_LISTED_PLATFORMS]
    remainder = len(coverage.unmeasured_platforms) - len(listed)
    names = ", ".join(listed) + (f", +{remainder} more" if remainder > 0 else "")
    return (
        "Disk budget coverage: PARTIAL -- this estimate is a LOWER BOUND, not a certification that the "
        f"sweep fits. Measured rows cover {len(coverage.measured_platforms)} of {coverage.platforms_total} "
        f"platform(s); {coverage.cells_with_rows} of {coverage.cells_total} largest-scale cell(s) have any "
        f"row and {coverage.cells_with_measured_database} of {coverage.cells_total} have a measured "
        f"loaded-database footprint. Unmeasured platform(s): {names}"
    )


def format_budget_verdict(check: DiskHeadroomCheck, coverage: DiskBudgetCoverage) -> str:
    """Operator-facing verdict for a disk gate that did NOT refuse the sweep.

    Never renders as "fits" when coverage is partial: an operator must be
    able to tell "measured and fine" from "mostly unmeasured". Callers use
    `format_disk_headroom_failure` for the refusing direction, which stays
    sound regardless of coverage -- a lower bound that already does not fit
    cannot fit.
    """
    if coverage.is_lower_bound:
        return (
            f"Disk budget verdict: no shortfall detected against a lower-bound requirement of "
            f"{check.required_gib:.2f} GiB; real demand may be higher (see coverage above)"
        )
    return f"Disk budget verdict: measured requirement of {check.required_gib:.2f} GiB fits every required root"


def check_disk_headroom(
    budget: DiskBudget,
    roots: Iterable[DiskRootFreeSpace],
    *,
    min_free_gib: float,
) -> DiskHeadroomCheck:
    """Compare an estimated peak budget against required disk roots.

    The `max(...)` is load-bearing, not defensive: `preflight.free_space_min_gib`
    is the operator's configured absolute floor, and because the budget is a
    LOWER BOUND that is routinely far below it (the loaded-database term is
    currently identically zero -- see the module docstring), dropping the
    `max` would let a sweep start with a fraction of a GiB free against a
    5 GiB configured floor. `test_disk_headroom_gate_enforces_configured_floor`
    pins it.
    """
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
