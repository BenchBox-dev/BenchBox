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
# (e.g. "_ceiling_log", a pointer string to _project/config/fast_lane_ceiling_log.md)
# and are intentionally not modeled here.
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

# Headroom (max_fast_tests - collected) below this triggers a FAST_LANE_WARNING
# (advisory only -- does not affect exit code) pointing at the +500 quantum
# bump convention in fast_lane_ceiling_log.md. See
# fast-lane-decouple-ceiling-contention-2 / docs/operations/fast-lane-budget.md.
FAST_LANE_HEADROOM_WARNING_THRESHOLD = 100

# Delta-guard thresholds for --delta-check (PR lane, additive to the absolute
# ceiling enforced by _check_fast_lane_policy -- never a substitute for it).
FAST_LANE_DELTA_FAIL_THRESHOLD = 150
FAST_LANE_DELTA_WARN_THRESHOLD = 75

CEILING_LOG_PATH = "_project/config/fast_lane_ceiling_log.md"


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
    """The collect subprocess could not run, so the policy was never checked.

    Distinct from a policy violation: nothing is known to be wrong with the
    fast lane, we simply failed to measure it. Conflating the two reports a
    green tree as several FAST_LANE_VIOLATIONs.
    """

    def __init__(self, message: str, *, violations: list[str] | None = None) -> None:
        super().__init__(message)
        self.violations = list(violations or [])


def _collect_environment_error(
    markexpr: str, returncode: int, output: str, *, violations: list[str] | None = None
) -> FastLaneCollectError:
    """Build an actionable error for a collect run that produced no count."""
    tail = "\n".join(line for line in output.strip().splitlines()[-5:])
    return FastLaneCollectError(
        f"could not run pytest --collect-only for '-m {markexpr}' "
        f"(exit {returncode}) using interpreter {sys.executable}. "
        "This usually means pytest or benchbox is not importable in that "
        "environment - run the check from the project environment, e.g. "
        "`uv run -- python _project/scripts/timing_policy_check.py --strict`. "
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


def _has_justified_ceiling_bump(repo_root: Path) -> bool:
    """Return whether this PR records a convention-compliant fast-lane bump."""
    policy_path = repo_root / "_project" / "config" / "fast_test_lane_policy.json"
    try:
        current_limit = int(_load_fast_lane_policy(policy_path).get("max_fast_tests", 500))
        base_policy = subprocess.run(
            ["git", "show", f"origin/develop:{policy_path.relative_to(repo_root)}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if base_policy.returncode != 0:
            return False
        base_limit = int(json.loads(base_policy.stdout).get("max_fast_tests", 500))
        if current_limit <= base_limit or (current_limit - base_limit) % 500 != 0:
            return False
        log_diff = subprocess.run(
            ["git", "diff", "origin/develop...HEAD", "--", CEILING_LOG_PATH],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return False

    return any(
        line.startswith("+")
        and not line.startswith("+++")
        and re.search(r"\+\s*-\s*\d{4}-\d{2}-\d{2}:.*\bBump(?:ed)?\b", line, re.IGNORECASE)
        for line in log_diff.stdout.splitlines()
    )


def _check_fast_lane_policy(repo_root: Path, policy: FastLanePolicy) -> list[str]:
    if not policy or not policy.get("enabled", True):
        return []

    violations: list[str] = []
    max_fast_tests = int(policy.get("max_fast_tests", 500))
    forbidden_marker_expressions = policy.get("forbidden_marker_expressions", [])
    forbidden_path_substrings = policy.get("forbidden_path_substrings", [])

    rc, fast_output = _run_pytest_collect(repo_root, "fast")
    print(f"Fast lane collect exit code: {rc}")
    if rc not in (0, 5):
        raise _collect_environment_error("fast", rc, fast_output)
    fast_count = _parse_collect_count(fast_output)
    if fast_count is None:
        raise _collect_environment_error("fast", rc, fast_output)
    print(f"Fast lane tests collected: {fast_count}")
    if fast_count > max_fast_tests:
        violations.append(f"fast lane count {fast_count} exceeds limit {max_fast_tests}")
    else:
        headroom = max_fast_tests - fast_count
        if headroom < FAST_LANE_HEADROOM_WARNING_THRESHOLD:
            print(
                f"FAST_LANE_WARNING: headroom {headroom} below "
                f"{FAST_LANE_HEADROOM_WARNING_THRESHOLD} - bump per {CEILING_LOG_PATH} "
                "conventions (+500 quantum)"
            )
    if forbidden_path_substrings:
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


def _emit_fast_count(repo_root: Path) -> int:
    """Collect the fast lane and print ONLY the machine-readable count.

    Used by develop-post-merge.yml to persist a baseline count for the PR
    lane's --delta-check (see below) to diff against. Deliberately minimal
    output (bare integer, nothing else on stdout) so a workflow step can
    redirect stdout straight into a cache-backed file. On a collection failure
    or parse failure, prints a message to stderr and returns nonzero -- the *workflow* step
    that calls this is responsible for never failing the post-merge job
    itself (guarded with `|| true`/a fallback there), not this function.
    """
    rc, output = _run_pytest_collect(repo_root, "fast")
    if rc not in (0, 5):
        print(f"FAST_LANE_ENVIRONMENT_ERROR: {_collect_environment_error('fast', rc, output)}", file=sys.stderr)
        return 1
    count = _parse_collect_count(output)
    if rc != 0 or count is None:
        print(f"FAST_LANE_ENVIRONMENT_ERROR: {_collect_environment_error('fast', rc, output)}", file=sys.stderr)
        return 1
    print(count)
    return 0


def _delta_check(repo_root: Path, develop_count_file: Path) -> int:
    """Compare this run's fast-lane collect count against a develop baseline.

    FAIL-OPEN BY DESIGN when no baseline is available (missing/unreadable
    file): the absolute ceiling check (_check_fast_lane_policy, run as its
    own separate --strict step) remains the enforced backstop in that case.
    This delta guard is additive on top of it, never a replacement.
    """
    if not develop_count_file.exists():
        print("DELTA_CHECK_SKIPPED (no develop baseline available - absolute ceiling still enforced)")
        return 0

    try:
        develop_count = int(develop_count_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        print("DELTA_CHECK_SKIPPED (no develop baseline available - absolute ceiling still enforced)")
        return 0

    rc, output = _run_pytest_collect(repo_root, "fast")
    if rc not in (0, 5):
        print(
            f"DELTA_CHECK_ENVIRONMENT_ERROR: {_collect_environment_error('fast', rc, output)}",
            file=sys.stderr,
        )
        return 1
    pr_count = _parse_collect_count(output)
    if pr_count is None:
        print(
            f"DELTA_CHECK_ENVIRONMENT_ERROR: {_collect_environment_error('fast', rc, output)}",
            file=sys.stderr,
        )
        return 1

    delta = pr_count - develop_count
    print(f"Fast lane delta vs develop: pr={pr_count} develop={develop_count} delta={delta:+d}")

    if delta > FAST_LANE_DELTA_FAIL_THRESHOLD:
        if _has_justified_ceiling_bump(repo_root):
            print(
                "FAST_LANE_DELTA_BUMP_AUTHORIZED: this PR records a +500 ceiling bump "
                f"with a dated justification in {CEILING_LOG_PATH}"
            )
            return 0
        print(
            f"FAST_LANE_DELTA_VIOLATION: this PR adds {delta} fast tests over develop's baseline "
            f"of {develop_count} (limit +{FAST_LANE_DELTA_FAIL_THRESHOLD} per PR). Mark new/converted "
            "tests medium instead of fast (pytestmark = [pytest.mark.unit, pytest.mark.medium]), split "
            "the change across PRs. A ceiling bump does not waive this per-PR delta guard."
        )
        return 1

    if delta > FAST_LANE_DELTA_WARN_THRESHOLD:
        print(
            f"FAST_LANE_DELTA_WARNING: this PR adds {delta} fast tests over develop's baseline of "
            f"{develop_count} (soft warning threshold +{FAST_LANE_DELTA_WARN_THRESHOLD}, hard limit "
            f"+{FAST_LANE_DELTA_FAIL_THRESHOLD}). Consider marking new tests medium if they don't need "
            "sub-second fast-lane execution."
        )
        return 0

    return 0


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
    parser.add_argument(
        "--emit-fast-count",
        action="store_true",
        help=(
            "Collect the fast lane and print ONLY the machine-readable count (stdout), then exit. "
            "Ignores every other mode; used to persist a develop baseline count for --delta-check."
        ),
    )
    parser.add_argument(
        "--delta-check",
        action="store_true",
        help=(
            "Compare this run's fast-lane collect count against a develop baseline count file "
            "(--develop-count-file). Additive to the absolute ceiling check, never a replacement."
        ),
    )
    parser.add_argument(
        "--develop-count-file",
        help="Path (repo-root-relative or absolute) to the develop baseline count file, used with --delta-check.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]

    if args.emit_fast_count:
        return _emit_fast_count(repo_root)

    if args.delta_check:
        if not args.develop_count_file:
            print("--delta-check requires --develop-count-file", file=sys.stderr)
            return 2
        develop_count_file = Path(args.develop_count_file)
        if not develop_count_file.is_absolute():
            develop_count_file = repo_root / develop_count_file
        return _delta_check(repo_root, develop_count_file)

    violations: list[Any] = []
    fast_lane_violations: list[str] = []
    fast_lane_environment_error = False

    if not args.only_fast_lane:
        allowlist_path = repo_root / args.allowlist
        entries = _load_allowlist(allowlist_path)

        findings = collect_findings(repo_root, args.roots)
        candidate_violations = [
            f
            for f in findings
            if f.symbol in {"time.time", "datetime.now"} and f.classification == "elapsed_or_timeout_wall_clock"
        ]

        unknown_wall_clock = [
            f
            for f in findings
            if f.symbol in {"time.time", "datetime.now"} and f.classification == "wall_clock_unknown"
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
        try:
            fast_lane_violations = _check_fast_lane_policy(repo_root, fast_lane_policy)
        except FastLaneCollectError as exc:
            # Not a policy violation: the lane was never measured. Reported
            # separately so a broken environment cannot masquerade as a set of
            # fast-lane breaches.
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

    if args.strict and (violations or fast_lane_violations or fast_lane_environment_error):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
