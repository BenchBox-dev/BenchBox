"""Timing policy enforcement with wall-clock allowlist."""

from __future__ import annotations

import argparse
import json
import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from timing_audit import collect_findings


def _load_allowlist(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("allowlist must contain an 'entries' list")
    return entries


def _is_allowed(path: str, text: str, symbol: str, entry: dict[str, Any]) -> bool:
    path_glob = entry.get("path_glob", "**")
    if not fnmatch(path, path_glob):
        return False

    allowed_symbol = entry.get("symbol")
    if allowed_symbol and allowed_symbol != symbol:
        return False

    line_regex = entry.get("line_regex")
    if line_regex and re.search(line_regex, text) is None:
        return False

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce timing policy with explicit wall-clock allowlist.")
    parser.add_argument(
        "--roots",
        nargs="+",
        default=[
            "benchbox",
            "scripts",
            "_project/scripts",
        ],
        help="Directories to scan (default: full benchbox tree)",
    )
    parser.add_argument(
        "--allowlist",
        default="_project/config/timing_wall_clock_allowlist.json",
        help="Allowlist JSON file path",
    )
    parser.add_argument("--strict", action="store_true", help="Fail on any non-allowlisted wall-clock violations")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    allowlist_path = repo_root / args.allowlist
    entries = _load_allowlist(allowlist_path)

    findings = collect_findings(repo_root, args.roots)
    candidate_violations = [
        f
        for f in findings
        if f.symbol in {"time.time", "datetime.now"}
        and f.classification in {"elapsed_or_timeout_wall_clock", "wall_clock_unknown"}
    ]

    violations = []
    allowed = 0
    for finding in candidate_violations:
        if any(_is_allowed(finding.path, finding.text, finding.symbol, entry) for entry in entries):
            allowed += 1
            continue
        violations.append(finding)

    print(f"Timing policy candidates: {len(candidate_violations)}")
    print(f"Allowlisted: {allowed}")
    print(f"Violations: {len(violations)}")
    for finding in violations[:200]:
        print(f"{finding.path}:{finding.line} [{finding.symbol}] {finding.text}")
    if len(violations) > 200:
        print(f"... truncated {len(violations) - 200} additional violations")

    if args.strict and violations:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
