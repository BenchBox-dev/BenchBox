"""Disk-budget estimator for UAT configs.

The checked-in TSV is an operator-maintained inventory from prior UAT
sweeps. Unknown cells stay visible in the estimate instead of being
treated as zero; preflight uses known peak demand as a headroom gate while
surfacing unknown coverage as an operator warning.
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


@dataclass(frozen=True)
class MemorySnapshot:
    """A host memory reading for the free-memory headroom gate (preflight.free_memory_min_gib).

    `free_gib` is None when free memory could not be measured on this host
    (psutil unavailable, or the read itself raised) -- callers MUST treat
    None as "unknown", never coerce it to 0.0 (would fail-closed and abort a
    host the gate simply cannot read) nor to a large number (would
    fail-open and silently skip the exact check this gate exists for). See
    `read_memory_snapshot` and `check_memory_headroom`.

    `swap_used_percent` is best-effort telemetry only (the 2026-08-04
    postmortem host also had 11.7 of 13.3 GB swap used alongside 72 MB free)
    -- it is logged alongside the gate result but never participates in the
    pass/fail decision, per the "gate on measured free memory with swap
    pressure logged alongside" guidance.
    """

    free_gib: float | None
    swap_used_percent: float | None


def read_memory_snapshot() -> MemorySnapshot:
    """Best-effort host free-memory + swap-pressure reading.

    Single measurement primitive for the free-memory gate, mirroring
    `free_space_gib`'s role for the disk gate. Uses
    `psutil.virtual_memory().available` -- `psutil` is a hard project
    dependency (see pyproject.toml; already used the same way for host
    telemetry in benchbox/platforms/base/result_capture.py) and reports
    memory actually available for new allocations (page cache/buffers
    already excluded on Linux) on macOS, Linux, and Windows alike, unlike a
    `/proc/meminfo`-only approach that would silently read as "unmeasurable"
    on macOS -- exactly the platform the 2026-08-04 incident happened on.

    `.available` is NOT interchangeable with the `free` figure an operator
    reads off `top`/Activity Monitor: on the 2026-08-05 dev host `.available`
    was 6.888 GiB while `.free` was 1.076 GiB. The gate's floor is expressed
    in `.available` terms -- see the CALIBRATION PROVENANCE note on
    `config.PreflightConfig.free_memory_min_gib` before comparing this
    reading against any number quoted in an incident report.

    Degrades safely to `MemorySnapshot(None, None)` on ANY failure (missing
    psutil, a sandboxed process denied access, ...) rather than raising or
    fabricating a value -- the gate must not silently pass as if there were
    headroom, nor hard-fail a host where the measurement itself is
    unavailable (e.g. a locked-down Linux CI container).
    """
    try:
        import psutil
    except ImportError:
        return MemorySnapshot(free_gib=None, swap_used_percent=None)
    try:
        free_gib = psutil.virtual_memory().available / (1024**3)
    except (OSError, RuntimeError, ValueError, AttributeError):
        free_gib = None
    try:
        swap_used_percent = psutil.swap_memory().percent
    except (OSError, RuntimeError, ValueError, AttributeError):
        swap_used_percent = None
    return MemorySnapshot(free_gib=free_gib, swap_used_percent=swap_used_percent)


@dataclass(frozen=True)
class MemoryHeadroomCheck:
    """Memory-gate result for one host memory snapshot."""

    free_gib: float | None
    required_gib: float
    swap_used_percent: float | None

    @property
    def shortfall(self) -> bool:
        """True iff free memory was measured and fell below the floor.

        An unmeasured reading (`free_gib is None`) is never a shortfall --
        the fail-safe "unknown != failing" branch (see
        `read_memory_snapshot`).
        """
        return self.free_gib is not None and self.free_gib < self.required_gib


def check_memory_headroom(snapshot: MemorySnapshot, *, min_free_gib: float) -> MemoryHeadroomCheck:
    """Compare a memory snapshot against the configured floor.

    Mirrors `check_disk_headroom`'s shape. Callers own the 0-disables
    convention (`min_free_gib <= 0` means the gate is off) the same way
    `execute.py`'s free-space check does -- this function does not special
    case it, but `shortfall` is `False` whenever `min_free_gib <= 0` since
    no measured `free_gib` can be less than a non-positive floor.
    """
    return MemoryHeadroomCheck(
        free_gib=snapshot.free_gib,
        required_gib=min_free_gib,
        swap_used_percent=snapshot.swap_used_percent,
    )


def format_memory_headroom_failure(check: MemoryHeadroomCheck) -> str:
    """Operator-facing abort reason for a memory-budget shortfall."""
    swap_note = f"; swap {check.swap_used_percent:.1f}% used" if check.swap_used_percent is not None else ""
    return (
        f"memory headroom gate failed: {check.free_gib:.2f} GiB free < {check.required_gib:.2f} GiB required{swap_note}"
    )


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
