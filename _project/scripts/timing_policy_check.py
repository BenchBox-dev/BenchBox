"""Timing policy enforcement with wall-clock allowlist."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, TypedDict, cast

from timing_audit import collect_findings


class AllowlistEntry(TypedDict, total=False):
    path_glob: str
    symbol: str
    line_regex: str
    reason: str


# Keys prefixed with "_" in the fast-lane policy JSON are human-facing annotations
# (e.g. "_ceiling_note") and are intentionally not modeled here.
class FastLanePolicy(TypedDict, total=False):
    enabled: bool
    max_fast_tests: int
    forbidden_marker_expressions: list[str]
    forbidden_path_substrings: list[str]


def _load_allowlist(path: Path) -> list[AllowlistEntry]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("allowlist must contain an 'entries' list")
    return cast(list[AllowlistEntry], entries)


def _load_fast_lane_policy(path: Path) -> FastLanePolicy:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("fast lane policy must be a JSON object")
    return cast(FastLanePolicy, data)


def _is_allowed(path: str, text: str, symbol: str, entry: AllowlistEntry) -> bool:
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


_COLLECT_COUNT_PATTERN = re.compile(r"(\d+)/(\d+) tests collected(?: \((\d+) deselected\))?")


def _run_pytest_collect(repo_root: Path, markexpr: str) -> tuple[int, str]:
    env = dict(os.environ)
    env["BENCHBOX_SKIP_TEST_LOCK"] = "1"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-n",
        "0",
        "-m",
        markexpr,
        "--collect-only",
        "-q",
    ]
    result = subprocess.run(
        cmd,
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return result.returncode, output


def _parse_collect_count(output: str) -> int | None:
    match = _COLLECT_COUNT_PATTERN.search(output)
    if match:
        return int(match.group(1))
    if "no tests collected" in output.lower():
        return 0
    return None


def _check_fast_lane_policy(repo_root: Path, policy: FastLanePolicy) -> list[str]:
    if not policy or not policy.get("enabled", True):
        return []

    violations: list[str] = []
    max_fast_tests = int(policy.get("max_fast_tests", 500))
    forbidden_marker_expressions = policy.get("forbidden_marker_expressions", [])
    forbidden_path_substrings = policy.get("forbidden_path_substrings", [])

    rc, fast_output = _run_pytest_collect(repo_root, "fast")
    fast_count = _parse_collect_count(fast_output)
    print(f"Fast lane collect exit code: {rc}")
    if fast_count is None:
        violations.append("could not parse fast lane collect count")
    else:
        print(f"Fast lane tests collected: {fast_count}")
        if fast_count > max_fast_tests:
            violations.append(f"fast lane count {fast_count} exceeds limit {max_fast_tests}")
        if forbidden_path_substrings:
            offending_lines = [
                line
                for line in fast_output.splitlines()
                if "::" in line and any(substring in line for substring in forbidden_path_substrings)
            ]
            if offending_lines:
                violations.append(
                    "fast lane includes Java/Spark-adjacent test paths: " + ", ".join(offending_lines[:10])
                )

    for expr in forbidden_marker_expressions:
        rc, output = _run_pytest_collect(repo_root, f"fast and {expr}")
        count = _parse_collect_count(output)
        print(f"Fast lane intersection '{expr}' exit code: {rc}")
        if count is None:
            violations.append(f"could not parse collect count for 'fast and {expr}'")
            continue
        print(f"Fast lane intersection '{expr}' count: {count}")
        if count != 0:
            violations.append(f"fast lane unexpectedly includes {count} test(s) matching 'fast and {expr}'")

    return violations


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
    parser.add_argument(
        "--fast-lane-policy",
        default="_project/config/fast_test_lane_policy.json",
        help="Fast-lane guardrail JSON file path",
    )
    parser.add_argument("--strict", action="store_true", help="Fail on any non-allowlisted wall-clock violations")
    lane_group = parser.add_mutually_exclusive_group()
    lane_group.add_argument(
        "--skip-fast-lane",
        action="store_true",
        help="Skip the pytest-collection fast-lane policy checks (runs only the allowlist scan).",
    )
    lane_group.add_argument(
        "--only-fast-lane",
        action="store_true",
        help="Run only the pytest-collection fast-lane policy checks (skips the allowlist scan).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]

    violations: list[Any] = []
    fast_lane_violations: list[str] = []

    if not args.only_fast_lane:
        allowlist_path = repo_root / args.allowlist
        entries = _load_allowlist(allowlist_path)

        findings = collect_findings(repo_root, args.roots)
        candidate_violations = [
            f
            for f in findings
            if f.symbol in {"time.time", "datetime.now"}
            and f.classification == "elapsed_or_timeout_wall_clock"
        ]

        unknown_wall_clock = [
            f
            for f in findings
            if f.symbol in {"time.time", "datetime.now"}
            and f.classification == "wall_clock_unknown"
        ]

        allowed = 0
        for finding in candidate_violations:
            if any(_is_allowed(finding.path, finding.text, finding.symbol, entry) for entry in entries):
                allowed += 1
                continue
            violations.append(finding)

        print(f"Timing policy candidates: {len(candidate_violations)}")
        print(f"Allowlisted: {allowed}")
        print(f"Violations: {len(violations)}")
        print(f"Unknown (informational): {len(unknown_wall_clock)}")
        for finding in violations[:200]:
            print(f"{finding.path}:{finding.line} [{finding.symbol}] {finding.text}")
        if len(violations) > 200:
            print(f"... truncated {len(violations) - 200} additional violations")

    if not args.skip_fast_lane:
        fast_lane_policy_path = repo_root / args.fast_lane_policy
        fast_lane_policy = _load_fast_lane_policy(fast_lane_policy_path)
        fast_lane_violations = _check_fast_lane_policy(repo_root, fast_lane_policy)
        print(f"Fast lane policy violations: {len(fast_lane_violations)}")
        for violation in fast_lane_violations:
            print(f"FAST_LANE_VIOLATION: {violation}")

    if args.strict and (violations or fast_lane_violations):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
