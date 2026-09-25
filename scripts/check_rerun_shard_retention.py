#!/usr/bin/env python3
"""Enforce the generated-rerun-shard retention policy.

Rerun shards under ``tests/uat/configs/generated-rerun-shards/`` are frozen
operational scratch from a named sweep, not reusable templates. They
accumulate without expiry: every checked-in shard keeps corpus-guard coverage
(load + enumerate on every fast-lane run) forever, even years after its sweep.

Policy: a shard expires ``RETENTION_DAYS`` after the sweep date encoded in
its filename stem (``-<YYYYMMDD>``). An expired shard fails this check with
the exact archive command. Archival is ``git mv`` into
``_project/_archive/generated-rerun-shards-<YYYYMMDD>/`` (tracked evidence
outside corpus discovery) plus a README note naming the sweep.

Exit status: 0 all shards within retention; 1 expired shard(s) need archival;
2 usage error.

Usage:
    uv run -- python scripts/check_rerun_shard_retention.py            # check (CI mode)
    uv run -- python scripts/check_rerun_shard_retention.py --retention-days N
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARD_DIR = REPO_ROOT / "tests" / "uat" / "configs" / "generated-rerun-shards"
ARCHIVE_PARENT = REPO_ROOT / "_project" / "_archive"

RETENTION_DAYS = 180

_STEM_DATE_RE = re.compile(r"-(\d{8})$")


def shard_sweep_date(path: Path) -> date | None:
    """Parse the ``-<YYYYMMDD>`` sweep date from a shard filename stem."""
    match = _STEM_DATE_RE.search(path.stem)
    if not match:
        return None
    try:
        stamp = match.group(1)
        return date(int(stamp[0:4]), int(stamp[4:6]), int(stamp[6:8]))
    except ValueError:
        return None


def find_expired(today: date, retention_days: int) -> tuple[list[tuple[Path, date, int]], list[Path]]:
    """Return ``(expired, undated)`` for shards in the shard directory.

    ``expired`` holds ``(path, sweep_date, age_days)`` for shards at or past
    retention, sorted. ``undated`` holds shards whose filename carries no
    parseable ``-<YYYYMMDD>`` sweep date; those fail the check too, since an
    undated shard can never expire on its own.
    """
    expired: list[tuple[Path, date, int]] = []
    undated: list[Path] = []
    if not SHARD_DIR.is_dir():
        return expired, undated
    for path in sorted(SHARD_DIR.glob("*.yaml")) + sorted(SHARD_DIR.glob("*.yml")):
        sweep = shard_sweep_date(path)
        if sweep is None:
            undated.append(path)
            continue
        age = (today - sweep).days
        if age >= retention_days:
            expired.append((path, sweep, age))
    return expired, undated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--retention-days",
        type=int,
        default=RETENTION_DAYS,
        help=f"Days after the sweep date before a shard expires (default {RETENTION_DAYS}).",
    )
    args = parser.parse_args(argv)

    expired, undated = find_expired(date.today(), args.retention_days)
    if not expired and not undated:
        print("rerun shards: OK - no expired generated shards.")
        return 0
    if undated:
        print(f"rerun shards: {len(undated)} shard(s) carry no parseable -<YYYYMMDD> sweep date:")
        for path in undated:
            print(f"  {path.name}: rename to stem-<YYYYMMDD>.yaml or archive it.")
    if expired:
        print(f"rerun shards: {len(expired)} expired shard(s) (retention {args.retention_days}d):")
        for path, sweep, age in expired:
            target = ARCHIVE_PARENT / f"generated-rerun-shards-{sweep.strftime('%Y%m%d')}"
            try:
                rel = str(path.relative_to(REPO_ROOT))
            except ValueError:
                rel = str(path)
            print(f"  {path.name}: sweep {sweep.isoformat()} ({age}d old)")
            print(
                f"    archive: mkdir -p {target.relative_to(REPO_ROOT)} && git mv {rel} {target.relative_to(REPO_ROOT)}/"
            )
    print("\nArchived shards stay tracked evidence under _project/_archive/ (outside corpus discovery).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
