#!/usr/bin/env python3
"""Daily observability signal for parked soundness-path PRs.

Soundness-path PRs correctly never auto-merge (see
``_project/scripts/auto_merge_soundness_paths.py`` and
``.github/workflows/auto-merge-on-open.yml``: the owner must review and
merge those PRs by hand). That withholding gate is intentional and this
script does NOT touch it -- no auto-merge, no auto-approve, nothing that
changes whether or how a PR can merge. What the gate does not do on its own
is tell anyone a PR has been sitting there: #1116 and #1142 both sat parked
for days with accumulating conflicts before anyone noticed. This script is
the missing "someone should look at this" signal:

- It classifies every OPEN PR targeting ``develop`` as qualifying for the
  drain queue when ALL of the following hold:
    (a) required-lane green  -- EVERY develop-ruleset required status
        context in ``REQUIRED_CHECK_NAMES`` has its LATEST check run on the
        PR's head SHA completed with conclusion ``success``. Today that is
        both ``ci-required-result`` and ``Results Explorer browser gate``
        (docs/operations/repo-admin-settings.md; live ruleset
        develop-squash-only). Partial green -- one context success, another
        red or never reported -- is NOT required-green; a missing run is
        fail-closed not-green.
    (b) awaiting the owner   -- auto-merge is OFF *and* (the PR touches a
        soundness-critical path per ``SOUNDNESS_PREFIXES``, OR the owner is
        a requested reviewer).
    (c) parked > 24h          -- more than 24 hours of park time (anchored
        on the LAST required context to finish, NOT ``updated_at``: the label
        writes below and ordinary human comments bump ``updated_at``, and a
        gate based on it would flap a genuinely parked PR out of the queue).
- The only mutations it ever performs (and only under ``--apply``) are:
    1. adding/removing the ``awaiting-owner`` label to match the current
       qualifying set, and
    2. creating/updating ONE tracking issue (title "Soundness-PR drain
       queue") with the current digest -- created/refreshed only while the
       queue is non-empty; when the queue drains, an existing digest is
       patched to the empty state exactly once, then left alone (silent).
  It never merges, approves, or otherwise changes a PR's mergeability.

Auth: GITHUB_TOKEN or GH_TOKEN from the environment (used directly over the
REST API). If neither is set but the ``gh`` CLI is on PATH, its token
(``gh auth token``) is used instead -- this lets the script run locally
against an interactively-authenticated ``gh`` without exporting a token by
hand. No long-lived PAT is required or read from anywhere else.

Usage:
    uv run -- python _project/scripts/soundness_drain_report.py
    uv run -- python _project/scripts/soundness_drain_report.py --json
    uv run -- python _project/scripts/soundness_drain_report.py --apply
    uv run -- python _project/scripts/soundness_drain_report.py --self-test
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from auto_merge_soundness_paths import any_soundness_path  # noqa: E402
from required_lane import (  # noqa: E402
    REQUIRED_CHECK_NAMES,
    _parse_iso,
    is_check_run_success,
    is_required_lane_green,
    latest_check_run,
)

FIXTURE_PATH = SCRIPT_DIR / "fixtures" / "soundness_drain_fixture.json"

# The sole code owner today (mirrors .github/CODEOWNERS). Used to detect
# "review requested from the owner" for non-soundness-path PRs that still
# need the owner's eyes (e.g. a manual review request on a normal PR).
OWNER_LOGIN = "joeharris76"

DEFAULT_REPO = "joeharris76/BenchBox"
DRAIN_LABEL = "awaiting-owner"
DRAIN_LABEL_COLOR = "b60205"
DRAIN_LABEL_DESCRIPTION = "Green, gated on owner review, parked >24h (see docs/operations/soundness-drain.md)"
PINNED_ISSUE_TITLE = "Soundness-PR drain queue"
# Body marker: proves the digest issue was written by this script, so
# find_pinned_issue never adopts (and later clobbers) a human issue that
# happens to reuse the title.
DIGEST_BODY_MARKER = "<!-- soundness-drain-digest -->"
IDLE_THRESHOLD_HOURS = 24.0
API_ROOT = "https://api.github.com"


# ---------------------------------------------------------------------------
# Pure classification logic (unit-/self-tested; no git/network)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ClassifiedPR:
    number: int
    title: str
    html_url: str
    draft: bool
    required_green: bool
    soundness_gated: bool
    auto_merge_enabled: bool
    review_requested_owner: bool
    awaiting_owner: bool
    idle_hours: float
    park_time_hours: float | None
    qualifies: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def required_lane_green_at(check_runs: list[dict[str, Any]]) -> str | None:
    """Timestamp at which the required lane went green: the LAST context to finish.

    A PR is only green once *every* required context has completed, so the
    park-time anchor is the maximum ``completed_at`` across them -- not
    ``ci-required-result``'s alone, which would overstate park time whenever
    the browser gate finishes later and trip the >24h gate early. Returns
    None when any required context lacks a completion timestamp, leaving the
    caller to fall back rather than anchor on a half-finished lane.
    Uses datetime parsing so fractional seconds and offsets sort correctly.
    """
    stamps: list[dt.datetime] = []
    raw: list[str] = []
    for name in REQUIRED_CHECK_NAMES:
        stamp = (latest_check_run(check_runs, name) or {}).get("completed_at")
        if not stamp:
            return None
        raw.append(str(stamp))
        try:
            stamps.append(_parse_iso(str(stamp)))
        except (ValueError, TypeError):
            return None
    # Return the raw string of the latest timestamp (caller parses it).
    latest = max(zip(stamps, raw), key=lambda x: x[0])[1]
    return latest


def is_soundness_gated(changed_files: list[str]) -> bool:
    return any_soundness_path(changed_files)


def is_awaiting_owner(
    *,
    auto_merge_enabled: bool,
    soundness_gated: bool,
    review_requested_owner: bool,
) -> bool:
    """True when the PR is parked on the owner: auto-merge off AND gated."""
    return (not auto_merge_enabled) and (soundness_gated or review_requested_owner)


def idle_hours(updated_at: str, now: dt.datetime) -> float:
    return (now - _parse_iso(updated_at)).total_seconds() / 3600.0


def park_time_hours(pr: dict[str, Any], now: dt.datetime, *, required_green: bool) -> float | None:
    """Hours since the PR became ready-and-green.

    Anchored on the ``completed_at`` of the LAST required context to finish
    -- the point the PR became green (the soundness-path/auto-merge-off state
    is static from the diff and typically already true by then, so "went
    green" is the later, load-bearing event in practice). Falls back to
    ``updated_at`` if any required context lacks a completion timestamp.
    Returns None when the required lane is not green (park time is undefined
    until it is).
    """
    if not required_green:
        return None
    anchor = required_lane_green_at(pr.get("check_runs") or []) or pr.get("updated_at")
    if not anchor:
        return None
    return (now - _parse_iso(anchor)).total_seconds() / 3600.0


def classify_pr(
    pr: dict[str, Any],
    now: dt.datetime,
    *,
    owner_login: str = OWNER_LOGIN,
    idle_threshold_hours: float = IDLE_THRESHOLD_HOURS,
) -> ClassifiedPR:
    """Classify one normalized PR record. Pure -- no I/O."""
    check_runs = pr.get("check_runs") or []
    changed_files = pr.get("changed_files") or []
    requested_reviewers = pr.get("requested_reviewers") or []

    required_green = is_required_lane_green(check_runs)
    soundness_gated = is_soundness_gated(changed_files)
    auto_merge_enabled = bool(pr.get("auto_merge"))
    review_requested_owner = owner_login in requested_reviewers
    awaiting_owner = is_awaiting_owner(
        auto_merge_enabled=auto_merge_enabled,
        soundness_gated=soundness_gated,
        review_requested_owner=review_requested_owner,
    )
    idle_h = idle_hours(pr["updated_at"], now)
    draft = bool(pr.get("draft"))
    park_h = park_time_hours(pr, now, required_green=required_green)
    # Gate on park time (anchored to the required lane going green), NOT
    # idle_hours: `updated_at` is bumped by this script's own label writes and
    # by any human comment, so an updated_at-based gate flaps a genuinely
    # parked PR out of the queue every time the signal fires.
    qualifies = (not draft) and required_green and awaiting_owner and (park_h or 0.0) > idle_threshold_hours

    return ClassifiedPR(
        number=pr["number"],
        title=pr.get("title", ""),
        html_url=pr.get("html_url", ""),
        draft=draft,
        required_green=required_green,
        soundness_gated=soundness_gated,
        auto_merge_enabled=auto_merge_enabled,
        review_requested_owner=review_requested_owner,
        awaiting_owner=awaiting_owner,
        idle_hours=idle_h,
        park_time_hours=park_h,
        qualifies=qualifies,
    )


def classify_all(
    prs: list[dict[str, Any]],
    now: dt.datetime,
    *,
    owner_login: str = OWNER_LOGIN,
    idle_threshold_hours: float = IDLE_THRESHOLD_HOURS,
) -> list[ClassifiedPR]:
    return [classify_pr(pr, now, owner_login=owner_login, idle_threshold_hours=idle_threshold_hours) for pr in prs]


def qualifying(classified: list[ClassifiedPR]) -> list[ClassifiedPR]:
    """Qualifying PRs, longest-parked first (most in need of attention)."""
    ready = [c for c in classified if c.qualifies]
    return sorted(ready, key=lambda c: c.park_time_hours or 0.0, reverse=True)


def _fmt_hours(hours: float) -> str:
    days, rem = divmod(hours, 24.0)
    if days >= 1:
        return f"{days:.0f}d{rem:.0f}h"
    return f"{hours:.1f}h"


def build_digest(classified: list[ClassifiedPR], *, now: dt.datetime, repo: str) -> str:
    """Human-readable digest body.

    Empty-queue body is used by local/manual runs and by the one-time
    "mark existing digest empty" patch; --apply never CREATES an issue for
    an empty queue.
    """
    ready = qualifying(classified)
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        DIGEST_BODY_MARKER,
        f"Soundness-PR drain queue -- daily digest (last updated {stamp})",
        "",
    ]
    if not ready:
        lines.append("Queue is empty: no PRs currently parked awaiting owner review.")
        return "\n".join(lines)

    lines.append(f"{len(ready)} PR(s) green on required checks, awaiting owner review, parked > 24h since green:")
    lines.append("")
    for c in ready:
        reason = "soundness-gated" if c.soundness_gated else "review-requested"
        park = _fmt_hours(c.park_time_hours) if c.park_time_hours is not None else "?"
        idle = _fmt_hours(c.idle_hours)
        lines.append(f"- #{c.number} {c.title} -- {reason}, idle {idle}, parked {park} -- {c.html_url}")
    lines.append("")
    lines.append(
        f"The `{DRAIN_LABEL}` label above reflects this list exactly (added/removed to match). "
        "The soundness auto-merge gate itself is untouched by this report -- see "
        "docs/operations/soundness-drain.md."
    )
    lines.append(f"(repo: {repo})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# I/O: GitHub REST (token-source chain: GITHUB_TOKEN/GH_TOKEN env, else the
# `gh` CLI's own token if it is on PATH -- never a separately-stored PAT).
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
    """Thin REST client. GET pagination via Link headers; single-page
    mutations otherwise. Mirrors detect_orphaned_commits.py's retry/urllib
    conventions.
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
                "User-Agent": "benchbox-soundness-drain-report",
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
        """GET a list endpoint, following `page` params up to a sane cap."""
        query = dict(params or {})
        query.setdefault("per_page", "100")
        out: list[dict[str, Any]] = []
        page = 1
        while page <= 10:  # 1000 items is far beyond this repo's open-PR volume
            query["page"] = str(page)
            url = f"{API_ROOT}/{path}?{urllib.parse.urlencode(query)}"
            result = self._request("GET", url) or []
            if isinstance(result, dict) and "check_runs" in result:
                result = result["check_runs"]
            if not result:
                break
            out.extend(result)
            if len(result) < int(query["per_page"]):
                break
            page += 1
        return out

    def get_one(self, path: str) -> Any:
        return self._request("GET", f"{API_ROOT}/{path}")

    def post(self, path: str, body: dict[str, Any]) -> Any:
        return self._request("POST", f"{API_ROOT}/{path}", body)

    def patch(self, path: str, body: dict[str, Any]) -> Any:
        return self._request("PATCH", f"{API_ROOT}/{path}", body)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", f"{API_ROOT}/{path}")


def fetch_open_prs(client: GitHubClient, owner: str, repo: str) -> list[dict[str, Any]]:
    """Fetch + normalize every OPEN PR targeting develop into the internal
    shape consumed by classify_pr (same shape as the self-test fixture).
    """
    raw_prs = client.get_all(f"repos/{owner}/{repo}/pulls", {"state": "open", "base": "develop"})
    normalized: list[dict[str, Any]] = []
    for raw in raw_prs:
        number = raw["number"]
        head_sha = raw["head"]["sha"]
        files = client.get_all(f"repos/{owner}/{repo}/pulls/{number}/files")
        check_runs = client.get_all(f"repos/{owner}/{repo}/commits/{head_sha}/check-runs")
        normalized.append(
            {
                "number": number,
                "title": raw.get("title", ""),
                "html_url": raw.get("html_url", ""),
                "draft": bool(raw.get("draft")),
                "created_at": raw.get("created_at"),
                "updated_at": raw.get("updated_at"),
                "auto_merge": raw.get("auto_merge"),
                "requested_reviewers": [r.get("login") for r in (raw.get("requested_reviewers") or [])],
                # GitHub reports a rename as the *new* `filename` plus a
                # `previous_filename`. The live auto-merge gate deliberately uses
                # `git diff --name-only --no-renames` (both sides of a rename) and
                # tests/unit/test_auto_merge_soundness_paths.py pins that, so a PR
                # that moves a protected soundness file OUT to an unprotected path
                # still disables auto-merge. Keep both names here or this report
                # would miss exactly those parked soundness-gated PRs.
                "changed_files": [
                    name for f in files for name in (f.get("filename", ""), f.get("previous_filename", "")) if name
                ],
                "check_runs": [
                    {
                        "name": run.get("name"),
                        "status": run.get("status"),
                        "conclusion": run.get("conclusion"),
                        "completed_at": run.get("completed_at"),
                    }
                    for run in check_runs
                ],
            }
        )
    return normalized


# ---------------------------------------------------------------------------
# Mutations (only reached under --apply): label sync + pinned issue upsert.
# ---------------------------------------------------------------------------
def ensure_label_exists(client: GitHubClient, owner: str, repo: str) -> None:
    existing = client.get_one(f"repos/{owner}/{repo}/labels/{DRAIN_LABEL}")
    if existing is not None:
        return
    client.post(
        f"repos/{owner}/{repo}/labels",
        {"name": DRAIN_LABEL, "color": DRAIN_LABEL_COLOR, "description": DRAIN_LABEL_DESCRIPTION},
    )


def sync_labels(client: GitHubClient, owner: str, repo: str, ready: list[ClassifiedPR]) -> tuple[list[int], list[int]]:
    """Add DRAIN_LABEL to qualifying PRs, remove it from evaluated PRs that
    no longer qualify but currently carry it. Returns (added, removed).
    """
    ensure_label_exists(client, owner, repo)
    qualifying_numbers = {c.number for c in ready}

    labeled_prs = client.get_all(
        f"repos/{owner}/{repo}/issues",
        {"labels": DRAIN_LABEL, "state": "open"},
    )
    labeled_numbers = {item["number"] for item in labeled_prs if "pull_request" in item}

    added: list[int] = []
    for number in sorted(qualifying_numbers - labeled_numbers):
        client.post(f"repos/{owner}/{repo}/issues/{number}/labels", {"labels": [DRAIN_LABEL]})
        added.append(number)

    removed: list[int] = []
    for number in sorted(labeled_numbers - qualifying_numbers):
        client.delete(f"repos/{owner}/{repo}/issues/{number}/labels/{DRAIN_LABEL}")
        removed.append(number)

    return added, removed


def find_pinned_issue(client: GitHubClient, owner: str, repo: str) -> dict[str, Any] | None:
    """Locate the digest issue: exact title AND the body marker.

    The marker requirement means a manually-created issue that happens to
    reuse the title is never clobbered; the script only adopts issues it
    wrote. Title matches without the marker are skipped.
    """
    issues = client.get_all(f"repos/{owner}/{repo}/issues", {"state": "all"})
    for item in issues:
        if "pull_request" in item:
            continue
        if item.get("title") == PINNED_ISSUE_TITLE and DIGEST_BODY_MARKER in (item.get("body") or ""):
            return item
    return None


def upsert_pinned_issue(client: GitHubClient, owner: str, repo: str, body: str) -> str:
    """Create/update the single digest issue (non-empty queue path)."""
    existing = find_pinned_issue(client, owner, repo)
    if existing is None:
        created = client.post(
            f"repos/{owner}/{repo}/issues",
            {"title": PINNED_ISSUE_TITLE, "body": body},
        )
        return f"created issue #{created['number']}"
    payload: dict[str, Any] = {"body": body}
    if existing.get("state") == "closed":
        payload["state"] = "open"
    client.patch(f"repos/{owner}/{repo}/issues/{existing['number']}", payload)
    return f"updated issue #{existing['number']}"


# ---------------------------------------------------------------------------
# Self-test (fixture-driven, no network)
# ---------------------------------------------------------------------------
def run_self_test() -> int:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    now = _parse_iso(fixture["as_of"])
    owner_login = fixture.get("owner_login", OWNER_LOGIN)
    classified = classify_all(fixture["prs"], now, owner_login=owner_login)
    by_number = {c.number: c for c in classified}

    failures: list[str] = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    expected_qualifying = set(fixture["expected_qualifying"])
    actual_qualifying = {c.number for c in qualifying(classified)}
    expect(
        actual_qualifying == expected_qualifying,
        f"qualifying set mismatch: expected {sorted(expected_qualifying)}, got {sorted(actual_qualifying)}",
    )

    for number in expected_qualifying:
        expect(number in by_number, f"expected PR #{number} in fixture")

    for number, reason in fixture.get("expected_excluded_reasons", {}).items():
        c = by_number.get(int(number))
        expect(c is not None, f"missing fixture PR #{number}")
        if c is None:
            continue
        expect(not c.qualifies, f"PR #{number} unexpectedly qualifies (expected excluded: {reason})")
        if reason == "not_green":
            expect(not c.required_green, f"PR #{number} expected required_green=False")
        elif reason == "auto_merge_on":
            expect(c.auto_merge_enabled, f"PR #{number} expected auto_merge_enabled=True")
        elif reason == "too_young":
            expect(
                (c.park_time_hours or 0.0) <= IDLE_THRESHOLD_HOURS,
                f"PR #{number} expected park_time_hours <= 24",
            )
        elif reason == "draft":
            expect(c.draft, f"PR #{number} expected draft=True")

    # park_time_hours is only defined once the required lane is green.
    for c in classified:
        if c.required_green:
            expect(c.park_time_hours is not None, f"PR #{c.number}: required_green but park_time_hours is None")
        else:
            expect(c.park_time_hours is None, f"PR #{c.number}: not required_green but park_time_hours is set")

    if failures:
        print("SELF-TEST FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(f"SELF-TEST PASSED ({len(classified)} fixture PRs, {len(actual_qualifying)} qualifying).")
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
        help="Mutate: sync the awaiting-owner label and (if non-empty) upsert the pinned digest issue.",
    )
    parser.add_argument(
        "--idle-hours",
        type=float,
        default=IDLE_THRESHOLD_HOURS,
        help=f"Idle threshold in hours (default: {IDLE_THRESHOLD_HOURS}).",
    )
    parser.add_argument("--self-test", action="store_true", help="Run the bundled fixture-based classifier test.")
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

    token = resolve_token()
    if not token:
        print(
            "::error::No GITHUB_TOKEN/GH_TOKEN in the environment and no authenticated `gh` on PATH.",
            file=sys.stderr,
        )
        return 2

    client = GitHubClient(token)
    prs = fetch_open_prs(client, owner, repo)
    now = dt.datetime.now(dt.timezone.utc)
    classified = classify_all(prs, now, idle_threshold_hours=args.idle_hours)
    ready = qualifying(classified)

    if args.json:
        print(
            json.dumps(
                {
                    "generated_at": now.isoformat(),
                    "repo": args.repo,
                    "evaluated_count": len(classified),
                    "qualifying": [c.to_dict() for c in ready],
                },
                indent=2,
            )
        )
    else:
        print(build_digest(classified, now=now, repo=args.repo))

    if args.apply:
        added, removed = sync_labels(client, owner, repo, ready)
        if added:
            print(f"label: added {DRAIN_LABEL} to {added}", file=sys.stderr)
        if removed:
            print(f"label: removed {DRAIN_LABEL} from {removed}", file=sys.stderr)
        if ready:
            outcome = upsert_pinned_issue(client, owner, repo, build_digest(classified, now=now, repo=args.repo))
            print(f"digest issue: {outcome}", file=sys.stderr)
        else:
            # Silent-when-empty means no new issue and no repeated updates --
            # but an existing digest must not keep showing yesterday's parked
            # PRs forever. Patch it to the empty state exactly once.
            existing = find_pinned_issue(client, owner, repo)
            if existing is not None and "Queue is empty" not in (existing.get("body") or ""):
                client.patch(
                    f"repos/{owner}/{repo}/issues/{existing['number']}",
                    {"body": build_digest(classified, now=now, repo=args.repo)},
                )
                print(f"digest issue: #{existing['number']} marked empty (one-time)", file=sys.stderr)
            else:
                print("digest issue: queue empty, no update (silent by design)", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
