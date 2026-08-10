#!/usr/bin/env python3
"""Nightly auto-ratchet signal for the fast-lane test-count ceiling.

Companion to `_project/scripts/timing_policy_check.py`'s fast-lane check and
`_project/config/fast_lane_ceiling_log.md`'s +500 quantum / >=250 headroom
bump convention (see `fast-lane-decouple-ceiling-contention-2` and
docs/operations/fast-lane-budget.md for the full history/rationale). This
script does NOT bump the ceiling, open a PR, or push a branch -- GITHUB_TOKEN-
authored PRs get no required checks (see green_unmerged_sweep.py's own note
on that constraint), so a ceiling bump stays a deliberate human/agent-
authored PR. The only mutation this script ever performs (and only under
`--apply`) is creating/updating ONE marker-tagged tracking issue (title
"Fast-lane ceiling needs a quantum bump"), mirroring
`_project/scripts/green_unmerged_sweep.py`'s pinned-issue upsert pattern --
read that script first if extending this one.

What it checks: collects the fast lane (`pytest -m fast --collect-only`,
same mechanism `timing_policy_check.py` uses) and compares it against the
current `max_fast_tests` ceiling in `_project/config/fast_test_lane_policy.json`.
An optional named `reservation` in that policy raises the nightly action
threshold above `WARN_THRESHOLD` (100), so consuming reserved headroom files
the same actionable issue before the absolute ceiling is close. The hard
ceiling and PR-time warning remain unchanged. When headroom recovers (a bump
landed, the lane contracted, or a completed reservation is explicitly
cleared), the issue is patched to the clear state exactly once, then left
alone -- never repeatedly updated for a state that hasn't changed (same
"silent when clear" contract as green_unmerged_sweep.py).

Auth: GITHUB_TOKEN or GH_TOKEN from the environment (used directly over the
REST API). If neither is set but the `gh` CLI is on PATH, its token
(`gh auth token`) is used instead. No long-lived PAT is required or read
from anywhere else.

Usage:
    uv run -- python _project/scripts/fast_lane_ratchet_check.py
    uv run -- python _project/scripts/fast_lane_ratchet_check.py --json
    uv run -- python _project/scripts/fast_lane_ratchet_check.py --apply
    uv run -- python _project/scripts/fast_lane_ratchet_check.py --self-test
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
FIXTURE_PATH = SCRIPT_DIR / "fixtures" / "fast_lane_ratchet_fixture.json"
POLICY_PATH = REPO_ROOT / "_project" / "config" / "fast_test_lane_policy.json"
CEILING_LOG_PATH = "_project/config/fast_lane_ceiling_log.md"

DEFAULT_REPO = "joeharris76/BenchBox"
API_ROOT = "https://api.github.com"

# Same threshold timing_policy_check.py's FAST_LANE_WARNING uses -- this
# script is the nightly, always-runs echo of that PR-time warning, not an
# independent policy.
WARN_THRESHOLD = 100
BUMP_QUANTUM = 500
MIN_HEADROOM_AFTER_BUMP = 250

PINNED_ISSUE_TITLE = "Fast-lane ceiling needs a quantum bump"
# Body marker: proves the digest issue was written by this script, so
# find_pinned_issue never adopts (and later clobbers) a human issue that
# happens to reuse the title.
DIGEST_BODY_MARKER = "<!-- fast-lane-ratchet-check -->"

_COLLECT_COUNT_PATTERN = re.compile(r"(\d+)/(\d+) tests collected(?: \((\d+) deselected\))?")


# ---------------------------------------------------------------------------
# Pure logic (unit-/self-tested; no git/network)
# ---------------------------------------------------------------------------
def parse_collect_count(output: str) -> int | None:
    match = _COLLECT_COUNT_PATTERN.search(output)
    if match:
        return int(match.group(1))
    if "no tests collected" in output.lower():
        return 0
    return None


def load_ceiling(policy_path: Path = POLICY_PATH) -> int:
    data = json.loads(policy_path.read_text(encoding="utf-8"))
    return int(data["max_fast_tests"])


def load_reservation(policy_path: Path = POLICY_PATH) -> tuple[str, int] | None:
    """Return an active ``(program, headroom_floor)`` reservation, if any."""
    data = json.loads(policy_path.read_text(encoding="utf-8"))
    reservation = data.get("reservation")
    if reservation is None:
        return None
    if not isinstance(reservation, dict):
        raise ValueError("fast-lane reservation must be an object or null")
    program = reservation.get("program")
    headroom_floor = reservation.get("headroom_floor")
    if not isinstance(program, str) or not program.strip():
        raise ValueError("fast-lane reservation program must be a non-empty string")
    if not isinstance(headroom_floor, int) or isinstance(headroom_floor, bool) or headroom_floor < WARN_THRESHOLD:
        raise ValueError(f"fast-lane reservation headroom_floor must be an integer >= {WARN_THRESHOLD}")
    return program.strip(), headroom_floor


def headroom_status(collected: int, ceiling: int, warn_threshold: int = WARN_THRESHOLD) -> tuple[int, bool]:
    """Return (headroom, needs_ratchet). headroom can be negative (over ceiling)."""
    headroom = ceiling - collected
    return headroom, headroom < warn_threshold


def suggested_next_ceiling(
    collected: int,
    ceiling: int,
    *,
    quantum: int = BUMP_QUANTUM,
    min_headroom: int = MIN_HEADROOM_AFTER_BUMP,
) -> int:
    """The next ceiling per the +500 quantum / >=250 headroom convention.

    Bumps by one quantum at a time from the CURRENT ceiling (never from the
    collected count directly -- a bump is always a multiple of the quantum
    above the last ceiling) until the resulting headroom clears the floor.
    """
    candidate = ceiling
    while candidate - collected < min_headroom:
        candidate += quantum
    return candidate


def _fmt_stamp(now: dt.datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M UTC")


def build_digest(
    *,
    collected: int,
    ceiling: int,
    headroom: int,
    repo: str,
    now: dt.datetime,
    reservation: tuple[str, int] | None = None,
) -> str:
    """Digest for the non-empty (needs-ratchet) state."""
    target_headroom = max(MIN_HEADROOM_AFTER_BUMP, reservation[1] if reservation else 0)
    next_ceiling = suggested_next_ceiling(collected, ceiling, min_headroom=target_headroom)
    bump = next_ceiling - ceiling
    new_headroom = next_ceiling - collected
    stamp = _fmt_stamp(now)
    lines = [
        DIGEST_BODY_MARKER,
        f"Fast-lane ceiling ratchet signal -- nightly check (last updated {stamp})",
        "",
        f"Fast lane collected **{collected}** tests against a ceiling of **{ceiling}** "
        f"(headroom {headroom}, below the "
        f"{reservation[1] if reservation else WARN_THRESHOLD} action threshold).",
        "",
        "## The exact edit",
        "",
        "1. In `_project/config/fast_test_lane_policy.json`, set:",
        "   ```json",
        f'   "max_fast_tests": {next_ceiling}',
        "   ```",
        f"   (+{bump} from the current ceiling, a {bump // BUMP_QUANTUM if bump % BUMP_QUANTUM == 0 else '~'} "
        f"quantum step, restoring {new_headroom} headroom -- >= {MIN_HEADROOM_AFTER_BUMP} per the convention.)",
        f"2. Append a dated entry to `{CEILING_LOG_PATH}` explaining the bump (quantum, resulting "
        "headroom, and what work drove the collected-count growth if known).",
        "3. Land this as a normal PR -- this signal never opens or pushes a PR itself "
        "(GITHUB_TOKEN-authored PRs get no required checks; see green_unmerged_sweep.py's own note "
        "on that constraint).",
        "",
        "Ceiling bumps remain deliberate human/agent PRs; this issue only surfaces the need. See "
        "docs/operations/fast-lane-budget.md.",
        f"(repo: {repo})",
    ]
    if reservation:
        lines[5:5] = [
            f"Active reservation: **{reservation[0]}** retains at least **{reservation[1]}** tests of headroom.",
            "Current growth has consumed that floor; either restore it with the quantum bump or explicitly clear",
            "the reservation after the named program lands.",
            "",
        ]
    return "\n".join(lines)


def build_clear_digest(*, collected: int, ceiling: int, headroom: int, repo: str, now: dt.datetime) -> str:
    """Digest for the empty (clear) state -- used only to patch a stale issue once."""
    stamp = _fmt_stamp(now)
    lines = [
        DIGEST_BODY_MARKER,
        f"Fast-lane ceiling ratchet signal -- nightly check (last updated {stamp})",
        "",
        f"No ratchet needed: fast lane collected {collected} tests against a ceiling of {ceiling} "
        f"(headroom {headroom}, at or above the {WARN_THRESHOLD} warning threshold).",
        f"(repo: {repo})",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# I/O: pytest collect (subprocess)
# ---------------------------------------------------------------------------
def collect_fast_count(repo_root: Path) -> int:
    env = dict(os.environ)
    env["BENCHBOX_SKIP_TEST_LOCK"] = "1"
    cmd = [sys.executable, "-m", "pytest", "-n", "0", "-m", "fast", "--collect-only", "-q"]
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
    count = parse_collect_count(output)
    if count is None:
        raise RuntimeError("could not parse fast lane collect count:\n" + output)
    return count


# ---------------------------------------------------------------------------
# I/O: GitHub REST (token-source chain: GITHUB_TOKEN/GH_TOKEN env, else the
# `gh` CLI's own token if on PATH). Mirrors green_unmerged_sweep.py.
# ---------------------------------------------------------------------------
def resolve_token() -> str | None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    if shutil.which("gh"):
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except OSError:
            return None
        if result.returncode == 0:
            candidate = result.stdout.strip()
            if candidate:
                return candidate
    return None


class GitHubClient:
    """Thin REST client. GET pagination via Link-style `page` params;
    single-page mutations otherwise. Mirrors green_unmerged_sweep.py's
    retry/urllib conventions.
    """

    def __init__(self, token: str) -> None:
        self.token = token

    def _request(self, method: str, url: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "benchbox-fast-lane-ratchet-check",
                **({"Content-Type": "application/json"} if data is not None else {}),
            },
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    payload = resp.read()
                    return json.loads(payload) if payload else None
            except urllib.error.HTTPError as err:
                if err.code == 404:
                    return None
                if attempt == 2:
                    raise
            except urllib.error.URLError:
                if attempt == 2:
                    raise
        return None

    def get_all(self, path: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        query = dict(params or {})
        query.setdefault("per_page", "100")
        out: list[dict[str, Any]] = []
        page = 1
        while page <= 10:
            query["page"] = str(page)
            url = f"{API_ROOT}/{path}?{urllib.parse.urlencode(query)}"
            result = self._request("GET", url) or []
            if not result:
                break
            out.extend(result)
            if len(result) < int(query["per_page"]):
                break
            page += 1
        return out

    def post(self, path: str, body: dict[str, Any]) -> Any:
        return self._request("POST", f"{API_ROOT}/{path}", body)

    def patch(self, path: str, body: dict[str, Any]) -> Any:
        return self._request("PATCH", f"{API_ROOT}/{path}", body)


def find_pinned_issue(client: GitHubClient, owner: str, repo: str) -> dict[str, Any] | None:
    """Locate the digest issue: exact title AND the body marker (see
    green_unmerged_sweep.py's identical adoption-safety rationale)."""
    issues = client.get_all(f"repos/{owner}/{repo}/issues", {"state": "all"})
    for item in issues:
        if "pull_request" in item:
            continue
        if item.get("title") == PINNED_ISSUE_TITLE and DIGEST_BODY_MARKER in (item.get("body") or ""):
            return item
    return None


def upsert_pinned_issue(client: GitHubClient, owner: str, repo: str, body: str) -> str:
    existing = find_pinned_issue(client, owner, repo)
    if existing is None:
        created = client.post(f"repos/{owner}/{repo}/issues", {"title": PINNED_ISSUE_TITLE, "body": body})
        return f"created issue #{created['number']}"
    payload: dict[str, Any] = {"body": body}
    if existing.get("state") == "closed":
        payload["state"] = "open"
    client.patch(f"repos/{owner}/{repo}/issues/{existing['number']}", payload)
    return f"updated issue #{existing['number']}"


# ---------------------------------------------------------------------------
# Self-test (fixture-driven, no network/subprocess)
# ---------------------------------------------------------------------------
def run_self_test() -> int:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    now = dt.datetime.fromisoformat(fixture["as_of"].replace("Z", "+00:00"))
    repo = fixture.get("repo", DEFAULT_REPO)
    warn_threshold = fixture.get("warn_threshold", WARN_THRESHOLD)

    failures: list[str] = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    for scenario in fixture["scenarios"]:
        name = scenario["name"]
        collected = scenario["collected"]
        ceiling = scenario["ceiling"]
        expected_needs_ratchet = scenario["expect_needs_ratchet"]

        headroom, needs_ratchet = headroom_status(collected, ceiling, warn_threshold)
        expect(
            needs_ratchet == expected_needs_ratchet,
            f"{name}: needs_ratchet mismatch (collected={collected} ceiling={ceiling} "
            f"headroom={headroom}): expected {expected_needs_ratchet}, got {needs_ratchet}",
        )

        if needs_ratchet:
            next_ceiling = suggested_next_ceiling(collected, ceiling)
            expect(
                next_ceiling - collected >= MIN_HEADROOM_AFTER_BUMP,
                f"{name}: suggested_next_ceiling {next_ceiling} does not restore "
                f"{MIN_HEADROOM_AFTER_BUMP} headroom over collected {collected}",
            )
            expect(
                (next_ceiling - ceiling) % BUMP_QUANTUM == 0,
                f"{name}: suggested_next_ceiling {next_ceiling} is not a {BUMP_QUANTUM}-quantum "
                f"step above ceiling {ceiling}",
            )
            digest = build_digest(collected=collected, ceiling=ceiling, headroom=headroom, repo=repo, now=now)
            expect(DIGEST_BODY_MARKER in digest, f"{name}: build_digest output missing DIGEST_BODY_MARKER")
            expect(str(next_ceiling) in digest, f"{name}: build_digest does not name the suggested next ceiling")
        else:
            clear_digest = build_clear_digest(
                collected=collected, ceiling=ceiling, headroom=headroom, repo=repo, now=now
            )
            expect(DIGEST_BODY_MARKER in clear_digest, f"{name}: build_clear_digest output missing DIGEST_BODY_MARKER")
            expect("No ratchet needed" in clear_digest, f"{name}: build_clear_digest missing the clear-state line")

    if failures:
        print("SELF-TEST FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(f"SELF-TEST PASSED ({len(fixture['scenarios'])} fixture scenarios).")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO),
        help=f"owner/name (default: $GITHUB_REPOSITORY or {DEFAULT_REPO})",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of the digest text.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Mutate: upsert the pinned ratchet-signal issue (no PR, no push, no label).",
    )
    parser.add_argument("--self-test", action="store_true", help="Run the bundled fixture-based logic test.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])

    if args.self_test:
        return run_self_test()

    try:
        owner, repo = args.repo.split("/", 1)
    except ValueError:
        print(f"::error::--repo must be owner/name, got {args.repo!r}", file=sys.stderr)
        return 2

    ceiling = load_ceiling()
    reservation = load_reservation()
    collected = collect_fast_count(REPO_ROOT)
    action_threshold = max(WARN_THRESHOLD, reservation[1] if reservation else WARN_THRESHOLD)
    headroom, needs_ratchet = headroom_status(collected, ceiling, action_threshold)
    now = dt.datetime.now(dt.timezone.utc)

    if args.json:
        print(
            json.dumps(
                {
                    "generated_at": now.isoformat(),
                    "repo": args.repo,
                    "collected": collected,
                    "ceiling": ceiling,
                    "headroom": headroom,
                    "action_threshold": action_threshold,
                    "reservation": (
                        {"program": reservation[0], "headroom_floor": reservation[1]} if reservation else None
                    ),
                    "needs_ratchet": needs_ratchet,
                },
                indent=2,
            )
        )
    elif needs_ratchet:
        print(
            build_digest(
                collected=collected,
                ceiling=ceiling,
                headroom=headroom,
                repo=args.repo,
                now=now,
                reservation=reservation,
            )
        )
    else:
        print(f"Fast lane headroom OK: {headroom} (collected {collected} / ceiling {ceiling}).")

    if args.apply:
        token = resolve_token()
        if not token:
            print(
                "::error::No GITHUB_TOKEN/GH_TOKEN in the environment and no authenticated `gh` on PATH.",
                file=sys.stderr,
            )
            return 2
        client = GitHubClient(token)
        if needs_ratchet:
            body = build_digest(
                collected=collected,
                ceiling=ceiling,
                headroom=headroom,
                repo=args.repo,
                now=now,
                reservation=reservation,
            )
            outcome = upsert_pinned_issue(client, owner, repo, body)
            print(f"ratchet issue: {outcome}", file=sys.stderr)
        else:
            existing = find_pinned_issue(client, owner, repo)
            existing_body = (existing or {}).get("body") or ""
            stale = "No ratchet needed" not in existing_body
            if existing is not None and stale:
                client.patch(
                    f"repos/{owner}/{repo}/issues/{existing['number']}",
                    {
                        "body": build_clear_digest(
                            collected=collected, ceiling=ceiling, headroom=headroom, repo=args.repo, now=now
                        )
                    },
                )
                print(f"ratchet issue: #{existing['number']} marked clear (one-time)", file=sys.stderr)
            else:
                print("ratchet issue: headroom OK, no update (silent by design)", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
