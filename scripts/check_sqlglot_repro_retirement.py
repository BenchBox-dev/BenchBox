#!/usr/bin/env python3
"""Run SQLGlot upstream repros when the locked sqlglot version changes.

Workaround retirement needs a trigger: a repro that flips from FAIL to PASS
on a new sqlglot version means the upstream defect may be fixed and the
BenchBox workaround it pins may be removable. Without a trigger, upgrades
land silently and workarounds live forever.

Behavior:

* Resolve the locked sqlglot version from ``uv.lock`` at HEAD and at the
  merge-base with ``origin/develop`` (or a ``--base-ref`` override).
* When the versions match, exit 0: no upgrade, nothing to re-run.
* When they differ, run ``repro_all.py`` on the NEW lockfile version and
  report per-repro PASS/FAIL. A repro that now PASSes is a retirement
  candidate: print the linked workaround from the README tier table and fail
  with guidance to audit and retire it. A repro that still FAILs is
  informational only.
* ``--check`` is the CI gate mode (same behavior; explicit for symmetry with
  sibling lint scripts). Default mode also runs the comparison.

Exit status: 0 no upgrade or no retirement candidates; 1 upgrade contains a
newly-passing repro that needs a retirement audit; 2 usage error.

Usage:
    uv run -- python scripts/check_sqlglot_repro_retirement.py [--base-ref REF] [--check]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPRO_SCRIPT = REPO_ROOT / "_project" / "sqlglot-upstream" / "repros" / "repro_all.py"
TIER_TABLE_REF = "_project/sqlglot-upstream/README.md (tier table)"

_LOCK_VERSION_RE = re.compile(r'name = "sqlglot"\nversion = "([^"]+)"')


def locked_sqlglot_version(ref: str | None = None) -> str | None:
    """Return the locked sqlglot version at ``ref`` (None = working tree)."""
    if ref is None:
        text = (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
    else:
        proc = subprocess.run(
            ["git", "show", f"{ref}:uv.lock"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise ValueError(f"cannot read uv.lock at ref {ref!r}: {proc.stderr.strip()}")
        text = proc.stdout
    match = _LOCK_VERSION_RE.search(text)
    return match.group(1) if match else None


def merge_base(ref: str = "origin/develop") -> str:
    proc = subprocess.run(
        ["git", "merge-base", "HEAD", ref],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ValueError(f"cannot resolve merge-base with {ref!r}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def run_repros() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(REPRO_SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def newly_passing(output: str) -> list[str] | None:
    """Extract repro labels that PASS in the summary section.

    Returns None when no summary section exists (harness crashed before
    reporting), so callers cannot mistake a crash for an all-FAIL run.
    """
    passing: list[str] = []
    in_summary = False
    for line in output.splitlines():
        if line.startswith("=== Summary"):
            in_summary = True
            continue
        if in_summary:
            match = re.match(r"\s*\[(PASS|FAIL)\]\s+(.+)", line)
            if match and match.group(1) == "PASS":
                passing.append(match.group(2).strip())
    return passing if in_summary else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-ref",
        default=None,
        help="Base ref for upgrade detection (default: merge-base with origin/develop).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="CI gate mode (same behavior; fails on retirement candidates).",
    )
    args = parser.parse_args(argv)

    try:
        base = args.base_ref or merge_base()
        old = locked_sqlglot_version(base)
        new = locked_sqlglot_version(None)
    except ValueError as err:
        print(f"sqlglot repro retirement: {err}", file=sys.stderr)
        return 2
    if old is None or new is None:
        print("sqlglot repro retirement: locked version not found in uv.lock.", file=sys.stderr)
        return 2
    if old == new:
        print(f"sqlglot repro retirement: OK - no upgrade (locked {new}).")
        return 0

    print(f"sqlglot repro retirement: upgrade {old} -> {new}; running repros...")
    status, output = run_repros()
    print(output)
    if status != 0 and "=== Summary" not in output:
        print(
            "sqlglot repro retirement: repro harness crashed before reporting "
            f"(exit {status}); cannot assess retirement - inspect the output above.",
            file=sys.stderr,
        )
        return 1
    passing = newly_passing(output)
    if passing is None:
        print(
            "sqlglot repro retirement: no summary section in repro output; cannot assess retirement.",
            file=sys.stderr,
        )
        return 1
    if not passing:
        print("sqlglot repro retirement: OK - all repros still FAIL; no retirement candidates.")
        return 0
    print("sqlglot repro retirement: RETIREMENT CANDIDATES (repro now passes):")
    for label in passing:
        print(f"  PASS {label}")
    print(
        f"\nAudit each candidate against {TIER_TABLE_REF}: verify the linked "
        "BenchBox workaround is truly unneeded on the new version, retire it, "
        "and update the tier table. A PASS here is a candidate, not proof — "
        "see repro_all.py header on proxy-dialect caveats."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
