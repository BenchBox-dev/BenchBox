"""Tuned-template coverage inventory helpers.

The runtime `--tuning tuned` resolver first looks for
`examples/tunings/{platform}/{benchmark}_tuned.yaml`; if no template exists,
it falls back to an enabled but generic constraints-only configuration. These
helpers make that contract auditable for UAT without making fallback an error.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

TUNED_TEMPLATE = "tuned_template"
BASIC_CONSTRAINTS = "basic_constraints"
UNTUNED = "untuned"
VALID_STATUSES = frozenset({TUNED_TEMPLATE, BASIC_CONSTRAINTS, UNTUNED})

DECISION_AUTHOR = "author"
DECISION_WAIVED = "waived"
DECISION_DONE = "done"
VALID_DECISIONS = frozenset({DECISION_AUTHOR, DECISION_WAIVED, DECISION_DONE})

STATUS_RANK = {
    UNTUNED: 0,
    BASIC_CONSTRAINTS: 1,
    TUNED_TEMPLATE: 2,
}

REPO_ROOT = Path(__file__).resolve().parents[3]
TUNING_TEMPLATE_ROOT = REPO_ROOT / "examples" / "tunings"
MATRIX_COLUMNS = ("platform", "benchmark", "status", "decision", "reason", "template_path")

# The 2026-05-05 handoff called these out as high-priority tuned-template gaps.
HIGH_PRIORITY_AUTHOR_BACKLOG = frozenset(
    {
        ("duckdb", "flightdata"),
        ("duckdb", "nyctaxi"),
    }
)


@dataclass(frozen=True)
class TuningCoverageRow:
    platform: str
    benchmark: str
    status: str
    decision: str
    reason: str
    template_path: str = "-"

    @property
    def key(self) -> tuple[str, str]:
        return (self.platform, self.benchmark)

    def to_dict(self) -> dict[str, str]:
        return {
            "platform": self.platform,
            "benchmark": self.benchmark,
            "status": self.status,
            "decision": self.decision,
            "reason": self.reason,
            "template_path": self.template_path,
        }


@dataclass(frozen=True)
class RuntimeTuningObservation:
    platform: str
    benchmark: str
    status: str
    log_path: Path

    @property
    def key(self) -> tuple[str, str]:
        return (self.platform, self.benchmark)


def template_path_for(platform: str, benchmark: str, *, root: Path = REPO_ROOT) -> Path:
    """Return the standard tuned-template path used by `--tuning tuned`."""
    return root / "examples" / "tunings" / platform.lower() / f"{benchmark.lower()}_tuned.yaml"


def classify_template(platform: str, benchmark: str, *, root: Path = REPO_ROOT) -> tuple[str, str]:
    """Classify one platform/benchmark pair from checked-in tuning templates."""
    template_path = template_path_for(platform, benchmark, root=root)
    if template_path.exists():
        return TUNED_TEMPLATE, _relpath(template_path, root)
    return BASIC_CONSTRAINTS, "-"


def build_tuning_coverage_rows(
    platforms: Iterable[str],
    benchmarks: Iterable[str],
    *,
    root: Path = REPO_ROOT,
) -> list[TuningCoverageRow]:
    """Build a deterministic coverage matrix for the supplied cells."""
    rows: list[TuningCoverageRow] = []
    for platform in platforms:
        for benchmark in benchmarks:
            status, template_path = classify_template(platform, benchmark, root=root)
            decision, reason = default_decision(platform, benchmark, status)
            rows.append(
                TuningCoverageRow(
                    platform=platform,
                    benchmark=benchmark,
                    status=status,
                    decision=decision,
                    reason=reason,
                    template_path=template_path,
                )
            )
    return rows


def default_decision(platform: str, benchmark: str, status: str) -> tuple[str, str]:
    if status == TUNED_TEMPLATE:
        return DECISION_DONE, "benchmark-specific tuned template exists"
    if (platform, benchmark) in HIGH_PRIORITY_AUTHOR_BACKLOG:
        return DECISION_AUTHOR, "high-priority backlog from 2026-05-05 fallback evidence"
    if status == BASIC_CONSTRAINTS:
        return DECISION_WAIVED, "basic constraints are acceptable until measured benefit justifies a template"
    return DECISION_WAIVED, "tuned mode has no applicable tuning input for this cell"


def write_tuning_coverage_tsv(rows: Iterable[TuningCoverageRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=MATRIX_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())


def read_tuning_coverage_tsv(path: Path) -> list[TuningCoverageRow]:
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        missing = set(MATRIX_COLUMNS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"tuning coverage TSV missing columns: {sorted(missing)}")
        rows = []
        for row in reader:
            status = row["status"]
            decision = row["decision"]
            if status not in VALID_STATUSES:
                raise ValueError(f"invalid tuning status {status!r} for {row['platform']}/{row['benchmark']}")
            if decision not in VALID_DECISIONS:
                raise ValueError(f"invalid tuning decision {decision!r} for {row['platform']}/{row['benchmark']}")
            rows.append(
                TuningCoverageRow(
                    platform=row["platform"],
                    benchmark=row["benchmark"],
                    status=status,
                    decision=decision,
                    reason=row["reason"],
                    template_path=row.get("template_path", "-"),
                )
            )
    return rows


def static_matrix_drift(
    recorded_rows: Iterable[TuningCoverageRow],
    current_rows: Iterable[TuningCoverageRow],
) -> list[str]:
    """Return checked-in matrix drift that would hide coverage regressions.

    Flags three kinds of drift between the checked-in TSV and the
    currently-derived inventory: (1) recorded keys missing from current,
    (2) status downgrades vs. the recorded baseline, and (3) newly-derived
    keys that have not yet been added to the matrix.
    """
    recorded_by_key = {row.key: row for row in recorded_rows}
    current_by_key = {row.key: row for row in current_rows}
    drift: list[str] = []
    for recorded in recorded_by_key.values():
        current = current_by_key.get(recorded.key)
        if current is None:
            drift.append(f"missing current row for {recorded.platform}/{recorded.benchmark}")
            continue
        if STATUS_RANK[current.status] < STATUS_RANK[recorded.status]:
            drift.append(f"{recorded.platform}/{recorded.benchmark}: {recorded.status} -> {current.status}")
    for current in current_by_key.values():
        if current.key not in recorded_by_key:
            drift.append(f"new current row missing from matrix for {current.platform}/{current.benchmark}")
    return drift


def parse_runtime_tuning_logs(
    logs_dir: Path,
    *,
    platforms: Iterable[str],
    benchmarks: Iterable[str],
) -> list[RuntimeTuningObservation]:
    """Parse per-cell UAT logs for their observed tuning resolution status."""
    if not logs_dir.exists():
        raise FileNotFoundError(f"logs directory does not exist: {logs_dir}")
    known_platforms = set(platforms)
    known_benchmarks = set(benchmarks)
    observations: list[RuntimeTuningObservation] = []
    for log_path in sorted(logs_dir.rglob("*.log")):
        parsed = parse_uat_cell_log_stem(
            log_path.stem,
            platforms=known_platforms,
            benchmarks=known_benchmarks,
        )
        if parsed is None:
            continue
        text = log_path.read_text(encoding="utf-8", errors="replace")
        status = status_from_log_text(text)
        if status is None:
            continue
        platform, benchmark = parsed
        observations.append(RuntimeTuningObservation(platform, benchmark, status, log_path))
    return observations


def parse_uat_cell_log_stem(
    stem: str,
    *,
    platforms: Iterable[str],
    benchmarks: Iterable[str],
) -> tuple[str, str] | None:
    """Parse `<platform>_<benchmark>_<scale>_<yyyymmdd>_<hhmmss>` UAT log stems."""
    parts = stem.split("_")
    if len(parts) < 5:
        return None
    platform = parts[0]
    benchmark = "_".join(parts[1:-3])
    if platform not in set(platforms) or benchmark not in set(benchmarks):
        return None
    return platform, benchmark


def status_from_log_text(text: str) -> str | None:
    if "Tuning: auto-discovered template" in text:
        return TUNED_TEMPLATE
    if "Tuning: using basic constraints" in text:
        return BASIC_CONSTRAINTS
    if "Tuning disabled:" in text:
        return UNTUNED
    return None


def runtime_mismatches(
    matrix_rows: Iterable[TuningCoverageRow],
    observations: Iterable[RuntimeTuningObservation],
) -> list[str]:
    """Return observed UAT log statuses that disagree with the static matrix."""
    matrix_by_key: Mapping[tuple[str, str], TuningCoverageRow] = {row.key: row for row in matrix_rows}
    mismatches: list[str] = []
    for observation in observations:
        row = matrix_by_key.get(observation.key)
        if row is None:
            mismatches.append(
                f"{observation.log_path}: observed {observation.platform}/{observation.benchmark} not in matrix"
            )
            continue
        if row.status != observation.status:
            mismatches.append(
                f"{observation.log_path}: observed {observation.status}, matrix has {row.status} "
                f"for {observation.platform}/{observation.benchmark}"
            )
    return mismatches


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
