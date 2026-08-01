"""Reject a uv.lock schema-revision downgrade.

An older local uv (< 0.8) silently rewrites the committed ``revision = 3``
lockfile back to revision 2 as a side effect of any ``uv add``/``uv lock``
run, and the downgrade rides along with the intended change. This guard
fails when the revision DECREASES relative to the committed baseline;
unchanged and increased revisions pass so legitimate lock updates need no
ceremony.

Modes:
  --old N --new N   pure comparison (test interface, no git or files needed)
  default           compare ``git show HEAD:uv.lock`` against ./uv.lock

Exit status: 0 ok, 1 downgrade (or malformed lock), 2 usage error.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_REVISION_RE = re.compile(r"^revision\s*=\s*(\d+)\s*$", re.MULTILINE)


def parse_revision(lock_text: str, origin: str) -> int:
    match = _REVISION_RE.search(lock_text)
    if not match:
        raise ValueError(f"no 'revision = N' line found in {origin}")
    return int(match.group(1))


def check(old: int, new: int) -> int:
    if new < old:
        print(
            f"uv.lock revision DOWNGRADE rejected: {old} -> {new}.\n"
            f"An older local uv rewrites the lock schema as a side effect; "
            f"upgrade uv (see docs/development/development.md) and regenerate "
            f"the lock, or discard the uv.lock hunk from this change.",
            file=sys.stderr,
        )
        return 1
    return 0


def _committed_lock_text(repo_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "show", "HEAD:uv.lock"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=int, default=None, help="baseline revision (test interface)")
    parser.add_argument("--new", type=int, default=None, help="candidate revision (test interface)")
    args = parser.parse_args(argv)

    if (args.old is None) != (args.new is None):
        parser.error("--old and --new must be given together")
    if args.old is not None and args.new is not None:
        return check(args.old, args.new)

    repo_root = Path(__file__).resolve().parents[2]
    working_lock = repo_root / "uv.lock"
    if not working_lock.exists():
        print("uv.lock not found in working tree; nothing to check")
        return 0
    committed = _committed_lock_text(repo_root)
    if committed is None:
        # No committed baseline (fresh repo / uv.lock not yet tracked).
        print("no committed uv.lock baseline (HEAD); nothing to compare")
        return 0
    try:
        old = parse_revision(committed, "HEAD:uv.lock")
        new = parse_revision(working_lock.read_text(encoding="utf-8"), "uv.lock")
    except ValueError as exc:
        print(f"uv.lock revision guard: {exc}", file=sys.stderr)
        return 1
    return check(old, new)


if __name__ == "__main__":
    sys.exit(main())
