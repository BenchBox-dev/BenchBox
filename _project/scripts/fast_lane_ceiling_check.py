from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TypedDict, cast


class FastLanePolicy(TypedDict, total=False):
    enabled: bool
    forbidden_marker_expressions: list[str]
    forbidden_path_substrings: list[str]


def _load_fast_lane_policy(path: Path) -> FastLanePolicy:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("fast lane policy must be a JSON object")
    return cast(FastLanePolicy, data)


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


class FastLaneCollectError(RuntimeError):
    def __init__(self, message: str, *, violations: list[str] | None = None) -> None:
        super().__init__(message)
        self.violations = list(violations or [])


def _collect_environment_error(
    markexpr: str, returncode: int, output: str, *, violations: list[str] | None = None
) -> FastLaneCollectError:
    tail = "\n".join(line for line in output.strip().splitlines()[-5:])
    return FastLaneCollectError(
        f"could not run pytest --collect-only for '-m {markexpr}' "
        f"(exit {returncode}) using interpreter {sys.executable}. "
        "This usually means pytest or benchbox is not importable in that "
        "environment - run the check from the project environment, e.g. "
        "`uv run -- python _project/scripts/fast_lane_ceiling_check.py --strict`. "
        f"Last output lines:\n{tail}",
        violations=violations,
    )


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
    forbidden_marker_expressions = policy.get("forbidden_marker_expressions", [])
    forbidden_path_substrings = policy.get("forbidden_path_substrings", [])

    if forbidden_path_substrings:
        rc, fast_output = _run_pytest_collect(repo_root, "fast")
        print(f"Fast lane collect exit code: {rc}")
        if rc not in (0, 5):
            raise _collect_environment_error("fast", rc, fast_output)
        if _parse_collect_count(fast_output) is None:
            raise _collect_environment_error("fast", rc, fast_output)
        offending_lines = [
            line
            for line in fast_output.splitlines()
            if "::" in line and any(substring in line for substring in forbidden_path_substrings)
        ]
        if offending_lines:
            violations.append("fast lane includes Java/Spark-adjacent test paths: " + ", ".join(offending_lines[:10]))

    for expr in forbidden_marker_expressions:
        rc, output = _run_pytest_collect(repo_root, f"fast and {expr}")
        print(f"Fast lane intersection '{expr}' exit code: {rc}")
        if rc not in (0, 5):
            raise _collect_environment_error(f"fast and {expr}", rc, output, violations=violations)
        count = _parse_collect_count(output)
        if count is None:
            raise _collect_environment_error(f"fast and {expr}", rc, output, violations=violations)
        print(f"Fast lane intersection '{expr}' count: {count}")
        if count != 0:
            violations.append(f"fast lane unexpectedly includes {count} test(s) matching 'fast and {expr}'")

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce the fast-lane forbidden-marker and forbidden-path guards.")
    parser.add_argument(
        "--fast-lane-policy",
        default="_project/config/fast_test_lane_policy.json",
        help="Fast-lane guardrail JSON file path",
    )
    parser.add_argument("--strict", action="store_true", help="Fail on any fast-lane policy violation")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]

    fast_lane_policy = _load_fast_lane_policy(repo_root / args.fast_lane_policy)
    fast_lane_violations: list[str]
    fast_lane_environment_error = False
    try:
        fast_lane_violations = _check_fast_lane_policy(repo_root, fast_lane_policy)
    except FastLaneCollectError as exc:
        fast_lane_violations = exc.violations
        print(f"Fast lane policy violations: {len(fast_lane_violations)}")
        for violation in fast_lane_violations:
            print(f"FAST_LANE_VIOLATION: {violation}")
        print(f"FAST_LANE_ENVIRONMENT_ERROR: {exc}", file=sys.stderr)
        fast_lane_environment_error = True
    else:
        print(f"Fast lane policy violations: {len(fast_lane_violations)}")
        for violation in fast_lane_violations:
            print(f"FAST_LANE_VIOLATION: {violation}")

    if args.strict and (fast_lane_violations or fast_lane_environment_error):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
