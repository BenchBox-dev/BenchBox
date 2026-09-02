#!/usr/bin/env python3
"""Operational receipts and capacity/retention auditor (A11 w2).

Audits operational exercise receipts, storage capacity, retention policies, and
drill freshness. It never fabricates a receipt, a capacity measurement, or a
retention policy. Every input must be supplied as a real file (or, for capacity,
a real directory to measure). A missing required input fails closed (exit 1 for
a policy violation, exit 2 for a config/parse error).

1. Capacity Limits (GitHub Pages rejects AT the limit, so comparisons are >=):
   - Total Pages publication tree size < 1 GiB (1,073,741,824 B); warn at 800 MiB.
   - Maximum individual file size < 100 MiB (104,857,600 B).
2. Retention Rules (from the retention-policy.json ``source`` field, which must
   cite the governing workflow ``retention-days`` or contract clause):
   - Transient build/test artifacts: <= 7 days retention.
   - Attested receipts & audit logs: >= 30 days retention.
   - Rollback checkpoints & disaster recovery states: >= 90 days retention.
3. Operational Drills (each receipt required on disk; a missing receipt is a
   MISSING violation, never a synthesized pass):
   - Automated rollback drill receipt freshness (<= max-age-days, default 30).
   - Emergency takedown drill receipt freshness (<= max-age-days).
   - Incident response drill receipt freshness (<= max-age-days).

Exit codes:
  0 - All operational receipts, capacity bounds, and retention policies verified.
  1 - Verification failure (capacity limit exceeded, expired/missing drill,
      retention policy violation).
  2 - Configuration, file reading, or argument error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

MAX_TOTAL_PAGES_BYTES = 1024 * 1024 * 1024  # 1 GiB
WARNING_TOTAL_PAGES_BYTES = 800 * 1024 * 1024  # 800 MiB
MAX_INDIVIDUAL_FILE_BYTES = 100 * 1024 * 1024  # 100 MiB

MAX_TRANSIENT_RETENTION_DAYS = 7
MIN_RECEIPT_RETENTION_DAYS = 30
MIN_ROLLBACK_CHECKPOINT_RETENTION_DAYS = 90

DEFAULT_MAX_AGE_DAYS = 30.0
FUTURE_SKEW_SECONDS = 300.0

ROLLBACK_DRILL_FILE = "rollback-drill.json"
TAKEDOWN_DRILL_FILE = "takedown-drill.json"
INCIDENT_DRILL_FILE = "incident-drill.json"
CAPACITY_FILE = "capacity-audit.json"
RETENTION_FILE = "retention-policy.json"


class ReceiptsConfigError(ValueError):
    """Raised for a configuration or parse error in operational inputs."""


@dataclass
class CapacityAudit:
    """Audit of publication artifact storage capacity."""

    total_size_bytes: int
    max_total_bytes: int = MAX_TOTAL_PAGES_BYTES
    warning_total_bytes: int = WARNING_TOTAL_PAGES_BYTES
    largest_file_bytes: int = 0
    largest_file_path: str = ""
    max_file_bytes: int = MAX_INDIVIDUAL_FILE_BYTES
    measured: bool = False
    passed: bool = True
    warnings: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RetentionAudit:
    """Audit of artifact retention configuration."""

    transient_retention_days: int | None = None
    receipt_retention_days: int | None = None
    rollback_checkpoint_retention_days: int | None = None
    source: str = ""
    passed: bool = True
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DrillReceiptStatus:
    """Verification status of an operational exercise drill receipt."""

    drill_type: str
    status: str  # VERIFIED, EXPIRED, MISSING, INVALID, FAILED
    receipt_id: str | None = None
    executed_at: str | None = None
    age_days: float | None = None
    max_age_days: float = DEFAULT_MAX_AGE_DAYS
    passed: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OperationalReceiptsReport:
    """Structured report on operational exercises, capacity, and retention."""

    valid: bool = True
    capacity: CapacityAudit = field(default_factory=lambda: CapacityAudit(total_size_bytes=0))
    retention: RetentionAudit = field(default_factory=RetentionAudit)
    drills: dict[str, DrillReceiptStatus] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "capacity": self.capacity.to_dict(),
            "retention": self.retention.to_dict(),
            "drills": {k: v.to_dict() for k, v in self.drills.items()},
            "violations": self.violations,
            "warnings": self.warnings,
            "timestamp": self.timestamp,
        }


def parse_iso_timestamp(ts_str: str) -> datetime | None:
    """Parse an ISO-8601 UTC timestamp string."""
    if not ts_str:
        return None
    cleaned = ts_str.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ReceiptsConfigError(f"cannot read {path}: {e}") from e
    if not isinstance(data, dict):
        raise ReceiptsConfigError(f"expected JSON object in {path}, got {type(data).__name__}")
    return data


def audit_capacity(
    total_bytes: int,
    largest_file_bytes: int = 0,
    largest_file_path: str = "",
    measured: bool = False,
) -> CapacityAudit:
    """Evaluate storage capacity against Pages limits (rejection is AT the limit)."""
    warnings: list[str] = []
    violations: list[str] = []
    passed = True

    if total_bytes >= MAX_TOTAL_PAGES_BYTES:
        passed = False
        violations.append(
            f"Pages total size ({total_bytes:,} bytes) meets or exceeds limit of {MAX_TOTAL_PAGES_BYTES:,} bytes (1.0 GiB)"
        )
    elif total_bytes >= WARNING_TOTAL_PAGES_BYTES:
        warnings.append(
            f"Pages total size ({total_bytes:,} bytes) exceeds warning threshold of {WARNING_TOTAL_PAGES_BYTES:,} bytes (800 MiB)"
        )

    if largest_file_bytes >= MAX_INDIVIDUAL_FILE_BYTES:
        passed = False
        violations.append(
            f"Individual file '{largest_file_path}' ({largest_file_bytes:,} bytes) meets or exceeds limit of "
            f"{MAX_INDIVIDUAL_FILE_BYTES:,} bytes (100 MiB)"
        )

    return CapacityAudit(
        total_size_bytes=total_bytes,
        largest_file_bytes=largest_file_bytes,
        largest_file_path=largest_file_path,
        measured=measured,
        passed=passed,
        warnings=warnings,
        violations=violations,
    )


def audit_retention(
    transient_days: int | None,
    receipt_days: int | None,
    rollback_days: int | None,
    source: str = "",
) -> RetentionAudit:
    """Evaluate artifact retention policies against minimum requirements.

    A missing value (``None``) is itself a violation - the policy must state it.
    """
    violations: list[str] = []
    passed = True

    if not source:
        passed = False
        violations.append("Retention policy does not cite a source (workflow retention-days or contract clause)")

    if transient_days is None:
        passed = False
        violations.append("Retention policy does not declare transient_retention_days")
    elif transient_days > MAX_TRANSIENT_RETENTION_DAYS:
        passed = False
        violations.append(
            f"Transient artifact retention ({transient_days} days) exceeds maximum budget of {MAX_TRANSIENT_RETENTION_DAYS} days"
        )

    if receipt_days is None:
        passed = False
        violations.append("Retention policy does not declare receipt_retention_days")
    elif receipt_days < MIN_RECEIPT_RETENTION_DAYS:
        passed = False
        violations.append(
            f"Receipt retention ({receipt_days} days) is below mandatory minimum of {MIN_RECEIPT_RETENTION_DAYS} days"
        )

    if rollback_days is None:
        passed = False
        violations.append("Retention policy does not declare rollback_checkpoint_retention_days")
    elif rollback_days < MIN_ROLLBACK_CHECKPOINT_RETENTION_DAYS:
        passed = False
        violations.append(
            f"Rollback checkpoint retention ({rollback_days} days) is below mandatory minimum of "
            f"{MIN_ROLLBACK_CHECKPOINT_RETENTION_DAYS} days"
        )

    return RetentionAudit(
        transient_retention_days=transient_days,
        receipt_retention_days=receipt_days,
        rollback_checkpoint_retention_days=rollback_days,
        source=source,
        passed=passed,
        violations=violations,
    )


def audit_drill_receipt(
    drill_type: str,
    receipt_data: dict[str, Any] | None,
    max_age_days: float = DEFAULT_MAX_AGE_DAYS,
    now_dt: datetime | None = None,
) -> DrillReceiptStatus:
    """Evaluate an operational drill receipt for freshness and status."""
    now = now_dt or datetime.now(timezone.utc)

    if not receipt_data:
        return DrillReceiptStatus(
            drill_type=drill_type,
            status="MISSING",
            max_age_days=max_age_days,
            passed=False,
            error=f"Operational receipt for drill '{drill_type}' is missing",
        )

    receipt_id = receipt_data.get("receipt_id") or receipt_data.get("id")
    executed_at = receipt_data.get("executed_at") or receipt_data.get("timestamp") or receipt_data.get("created_at")
    status = receipt_data.get("status")

    if status is None:
        return DrillReceiptStatus(
            drill_type=drill_type,
            status="INVALID",
            receipt_id=receipt_id,
            max_age_days=max_age_days,
            passed=False,
            error="Drill receipt does not declare an execution status",
        )

    if not executed_at:
        return DrillReceiptStatus(
            drill_type=drill_type,
            status="INVALID",
            receipt_id=receipt_id,
            max_age_days=max_age_days,
            passed=False,
            error="Drill receipt missing execution timestamp",
        )

    exec_dt = parse_iso_timestamp(str(executed_at))
    if not exec_dt:
        return DrillReceiptStatus(
            drill_type=drill_type,
            status="INVALID",
            receipt_id=receipt_id,
            executed_at=str(executed_at),
            max_age_days=max_age_days,
            passed=False,
            error="Drill receipt contains unparseable timestamp",
        )

    age_seconds = (now - exec_dt).total_seconds()
    if age_seconds < -FUTURE_SKEW_SECONDS:
        return DrillReceiptStatus(
            drill_type=drill_type,
            status="INVALID",
            receipt_id=receipt_id,
            executed_at=str(executed_at),
            age_days=round(age_seconds / 86400.0, 2),
            max_age_days=max_age_days,
            passed=False,
            error="Drill receipt execution timestamp is in the future",
        )

    age_days = round(age_seconds / 86400.0, 2)

    if str(status).upper() not in ("SUCCESS", "PASSED", "VERIFIED"):
        return DrillReceiptStatus(
            drill_type=drill_type,
            status="FAILED",
            receipt_id=receipt_id,
            executed_at=str(executed_at),
            age_days=age_days,
            max_age_days=max_age_days,
            passed=False,
            error=f"Drill execution status is '{status}', expected SUCCESS",
        )

    if age_days > max_age_days:
        return DrillReceiptStatus(
            drill_type=drill_type,
            status="EXPIRED",
            receipt_id=receipt_id,
            executed_at=str(executed_at),
            age_days=age_days,
            max_age_days=max_age_days,
            passed=False,
            error=f"Drill receipt is expired: age {age_days} days exceeds maximum threshold of {max_age_days} days",
        )

    return DrillReceiptStatus(
        drill_type=drill_type,
        status="VERIFIED",
        receipt_id=receipt_id,
        executed_at=str(executed_at),
        age_days=age_days,
        max_age_days=max_age_days,
        passed=True,
    )


def measure_local_directory_capacity(path: Path) -> tuple[int, int, str]:
    """Measure total size, largest file size, and largest file path of a directory."""
    if not path.exists():
        raise ReceiptsConfigError(f"capacity measurement path does not exist: {path}")

    if path.is_file():
        sz = path.stat().st_size
        return sz, sz, str(path)

    total_size = 0
    max_size = 0
    max_file = ""

    for root, _, files in os.walk(path):
        for f in files:
            p = Path(root) / f
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            total_size += sz
            if sz > max_size:
                max_size = sz
                max_file = str(p.relative_to(path))

    return total_size, max_size, max_file


def audit_operational_receipts(
    receipts_dir: Path | None = None,
    pages_dir: Path | None = None,
    max_age_days: float = DEFAULT_MAX_AGE_DAYS,
    now_dt: datetime | None = None,
) -> OperationalReceiptsReport:
    """Audit all operational exercise receipts, capacity, and retention rules.

    ``receipts_dir`` is required and must contain the three drill receipts, a
    retention policy, and either a capacity audit file or (via ``pages_dir``) a
    real directory to measure.
    """
    now = now_dt or datetime.now(timezone.utc)

    if receipts_dir is None:
        raise ReceiptsConfigError(
            "receipts_dir is required; this auditor does not synthesize drill receipts, "
            "capacity numbers, or retention policy"
        )
    if not receipts_dir.is_dir():
        raise ReceiptsConfigError(f"receipts directory not found: {receipts_dir}")

    all_violations: list[str] = []
    all_warnings: list[str] = []

    def _load_optional(name: str) -> dict[str, Any] | None:
        p = receipts_dir / name
        return _load_json_object(p) if p.is_file() else None

    rollback_data = _load_optional(ROLLBACK_DRILL_FILE)
    takedown_data = _load_optional(TAKEDOWN_DRILL_FILE)
    incident_data = _load_optional(INCIDENT_DRILL_FILE)

    # Capacity: measure a real directory or read a real audit file. Never invent.
    cap_data = _load_optional(CAPACITY_FILE)
    if pages_dir is not None:
        total_bytes, largest_file_bytes, largest_file_path = measure_local_directory_capacity(pages_dir)
        capacity_audit = audit_capacity(total_bytes, largest_file_bytes, largest_file_path, measured=True)
    elif cap_data is not None:
        try:
            total_bytes = int(cap_data["total_size_bytes"])
            largest_file_bytes = int(cap_data.get("largest_file_bytes", 0))
        except (KeyError, TypeError, ValueError) as e:
            raise ReceiptsConfigError(f"{CAPACITY_FILE} is missing/invalid total_size_bytes: {e}") from e
        capacity_audit = audit_capacity(
            total_bytes,
            largest_file_bytes,
            str(cap_data.get("largest_file_path", "")),
            measured=bool(cap_data.get("measured", False)),
        )
    else:
        capacity_audit = CapacityAudit(total_size_bytes=0, passed=False)
        capacity_audit.violations.append(
            f"No capacity evidence: supply --pages-dir or {CAPACITY_FILE} in the receipts directory"
        )

    if not capacity_audit.passed:
        all_violations.extend(capacity_audit.violations)
    all_warnings.extend(capacity_audit.warnings)

    # Retention: real policy file only.
    ret_data = _load_optional(RETENTION_FILE)
    if ret_data is None:
        retention_audit = RetentionAudit(passed=False)
        retention_audit.violations.append(
            f"No retention policy: supply {RETENTION_FILE} declaring transient/receipt/rollback retention and its source"
        )
    else:
        retention_audit = audit_retention(
            transient_days=ret_data.get("transient_retention_days"),
            receipt_days=ret_data.get("receipt_retention_days"),
            rollback_days=ret_data.get("rollback_checkpoint_retention_days"),
            source=str(ret_data.get("source", "")),
        )
    if not retention_audit.passed:
        all_violations.extend(retention_audit.violations)

    drills: dict[str, DrillReceiptStatus] = {}
    for key, data in (
        ("rollback", rollback_data),
        ("takedown", takedown_data),
        ("incident_response", incident_data),
    ):
        status = audit_drill_receipt(key, data, max_age_days=max_age_days, now_dt=now)
        drills[key] = status
        if not status.passed and status.error:
            all_violations.append(status.error)

    valid = len(all_violations) == 0

    return OperationalReceiptsReport(
        valid=valid,
        capacity=capacity_audit,
        retention=retention_audit,
        drills=drills,
        violations=all_violations,
        warnings=all_warnings,
        timestamp=now.isoformat(),
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Operational receipts, capacity bounds, and retention auditor (A11 w2)."
    )
    parser.add_argument(
        "--receipts-dir",
        type=Path,
        default=None,
        help="Directory containing operational drill receipts, retention policy, and capacity audit. REQUIRED.",
    )
    parser.add_argument(
        "--pages-dir",
        type=Path,
        default=None,
        help="Real Pages publication tree to measure for capacity (alternative to capacity-audit.json).",
    )
    parser.add_argument(
        "--max-age-days",
        type=float,
        default=DEFAULT_MAX_AGE_DAYS,
        help=f"Maximum allowed age for drill receipts in days (default: {DEFAULT_MAX_AGE_DAYS}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured audit report as JSON to stdout.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    if args.receipts_dir is None:
        sys.stderr.write(
            "Error: --receipts-dir is required. This auditor does not fabricate drill "
            "receipts, capacity numbers, or retention policy.\n"
        )
        return 2
    if not args.receipts_dir.is_dir():
        sys.stderr.write(f"Receipts directory not found: {args.receipts_dir}\n")
        return 2

    try:
        report = audit_operational_receipts(
            receipts_dir=args.receipts_dir,
            pages_dir=args.pages_dir,
            max_age_days=args.max_age_days,
        )
    except ReceiptsConfigError as e:
        sys.stderr.write(f"Error: {e}\n")
        return 2

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        status_str = "PASS - OPERATIONAL COMPLIANCE" if report.valid else "FAIL - VIOLATIONS DETECTED"
        print(f"Operational Receipts and Capacity Audit: {status_str}")
        print(
            f"  Pages Total Size    : {report.capacity.total_size_bytes:,} / {report.capacity.max_total_bytes:,} bytes"
            f" ({'measured' if report.capacity.measured else 'declared'})"
        )
        print(
            f"  Largest File Size   : {report.capacity.largest_file_bytes:,} / {report.capacity.max_file_bytes:,} bytes"
            f" ({report.capacity.largest_file_path})"
        )
        print(
            f"  Retention Windows   : Transient={report.retention.transient_retention_days}d, "
            f"Receipts={report.retention.receipt_retention_days}d, "
            f"Rollback={report.retention.rollback_checkpoint_retention_days}d "
            f"(source: {report.retention.source or 'NONE'})"
        )

        print("\nOperational Drill Statuses:")
        for name, drill in report.drills.items():
            age_info = f"({drill.age_days:.1f}d old)" if drill.age_days is not None else ""
            print(f"  - {name:<18}: {drill.status} {age_info}")

        if report.warnings:
            print("\nWarnings:")
            for w in report.warnings:
                print(f"  - [WARNING] {w}")

        if report.violations:
            print("\nViolations:")
            for v in report.violations:
                print(f"  - [VIOLATION] {v}")

    return 0 if report.valid else 1


if __name__ == "__main__":
    sys.exit(main())
