#!/usr/bin/env python3
"""Nightly sweep for open develop PRs that look stranded auto-merge-off.

Prior art: `harden-auto-merge-on-open-stranding` diagnosed exactly this
failure class -- three PRs had their auto-merge-on-open.yml `enable` job
complete with `conclusion: success`, yet the PR's own `auto_merge` field
later read back `null`, and the fixes sat un-merged until someone noticed
by hand. This script does NOT modify `auto-merge-on-open.yml` or how it
enables auto-merge; it is a read-only external observer that classifies
every OPEN, non-draft develop PR and alerts when one looks stranded:

    (a) required-lane green -- the LATEST `ci-required-result` check run
        on the PR's head SHA completed with conclusion `success`.
    (b) auto-merge is OFF    -- the PR's own `auto_merge` field is falsy
        (null or an explicit off), regardless of what the enable job's
        own run concluded (see "Known timing behavior" below -- a green
        enable-job run is NOT proof the field ended up populated).
    (c) not soundness-gated  -- `any_soundness_path` over the PR's changed
        files is False. Soundness-gated PRs correctly never auto-merge
        (see `auto_merge_soundness_paths.py` /
        `.github/workflows/auto-merge-on-open.yml`); that withheld state
        is by design and is covered by the separate daily
        soundness-drain digest, not this sweep.
    (d) past the grace period -- more than `GRACE_PERIOD_HOURS` (default
        2h) since the head commit was pushed, so the enable workflow's
        `synchronize`-triggered re-run has had every chance to fire
        before this sweep calls a PR stranded.

The only mutation this script ever performs (and only under `--apply`) is
creating/updating ONE marker-tagged tracking issue (title "Green-but-unmerged
PR sweep") with the current digest -- created/refreshed while the stranded
set is non-empty (or develop post-merge is red, see `--check-post-merge`
below), and patched to the empty state exactly once when it drains, then
left alone. It never enables auto-merge, never merges, never labels, and
never comments on a PR -- enabling auto-merge outside the sanctioned
predicate path in `auto-merge-on-open.yml` would bypass the soundness gate.

`--check-post-merge` additionally checks the most recent "Develop post-merge"
workflow run; if its conclusion is `failure`, a prominent section is added to
the top of the sweep issue calling out the fix-forward SLA (same day -- see
docs/operations/pr-triage.md). This does not touch develop-post-merge.yml.

Known timing behavior (observed live 2026-07-23 against PRs #1282-#1286,
all opened and auto-merge-enabled the same day): the `auto-merge-on-open.yml`
`enable` job (`gh pr merge --auto --squash`) completed `conclusion: success`
on every one of those PRs' head SHAs, per the Actions API. However, reading
those same PRs back through the GitHub MCP server's `pull_request_read` tool
omitted the `auto_merge` field entirely rather than surfacing it as populated
or explicit `null` -- i.e. a caller relying on that read path cannot tell
"enabled but not yet visible" from "never enabled" from "the read path just
doesn't carry this field". The raw REST `GET /pulls` endpoint (what this
script calls directly) does carry `auto_merge` on every PR, so this script
never infers state from a workflow run's conclusion -- it always re-fetches
each PR's own current `auto_merge` object.

Auth: GITHUB_TOKEN or GH_TOKEN from the environment (used directly over the
REST API). If neither is set but the `gh` CLI is on PATH, its token
(`gh auth token`) is used instead -- this lets the script run locally
against an interactively-authenticated `gh` without exporting a token by
hand. No long-lived PAT is required or read from anywhere else.

Usage:
    uv run -- python _project/scripts/green_unmerged_sweep.py
    uv run -- python _project/scripts/green_unmerged_sweep.py --json
    uv run -- python _project/scripts/green_unmerged_sweep.py --apply --check-post-merge
    uv run -- python _project/scripts/green_unmerged_sweep.py --self-test
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

FIXTURE_PATH = SCRIPT_DIR / "fixtures" / "green_unmerged_fixture.json"

DEFAULT_REPO = "joeharris76/BenchBox"
REQUIRED_CHECK_NAME = "ci-required-result"
GRACE_PERIOD_HOURS = 2.0
API_ROOT = "https://api.github.com"
DEVELOP_POST_MERGE_WORKFLOW = "develop-post-merge.yml"

PINNED_ISSUE_TITLE = "Green-but-unmerged PR sweep"
# Body marker: proves the digest issue was written by this script, so
# find_pinned_issue never adopts (and later clobbers) a human issue that
# happens to reuse the title.
DIGEST_BODY_MARKER = "<!-- green-unmerged-sweep -->"
POST_MERGE_SLA = "fix-forward SLA: same day"


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
    head_age_hours: float
    stranded: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_iso(value: str) -> dt.datetime:
    # GitHub timestamps are RFC3339 with a trailing "Z".
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def required_lane_check_run(check_runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the latest ``ci-required-result`` check run, if present.

    A re-run can leave multiple same-named runs on one SHA; pick the most
    recently started so a stale conclusion never wins.
    """
    matches = [run for run in check_runs if run.get("name") == REQUIRED_CHECK_NAME]
    if not matches:
        return None
    return max(matches, key=lambda run: run.get("started_at") or "")


def is_required_lane_green(check_runs: list[dict[str, Any]]) -> bool:
    run = required_lane_check_run(check_runs)
    if run is None:
        return False
    return run.get("status") == "completed" and run.get("conclusion") == "success"


def is_soundness_gated(changed_files: list[str]) -> bool:
    return any_soundness_path(changed_files)


def head_age_hours(pr: dict[str, Any], now: dt.datetime) -> float:
    """Hours since the PR's head commit was pushed.

    Anchored on ``head_pushed_at`` when present (the commit's own
    author/committer timestamp, fetched alongside the head SHA -- see
    `fetch_head_pushed_at`). committer.date is a push-time APPROXIMATION:
    rebases/cherry-picks reset it to ~push time, but an old commit held
    locally then pushed, or a reopened PR, can look past-grace early. The
    consequence is bounded to a premature advisory line (no PR mutation)
    that self-corrects on the next nightly run. Falls back to
    ``updated_at``. An unknown
    anchor returns 0.0 (fail-closed: an unaged PR never qualifies as
    stranded until its push time is actually known).
    """
    anchor = pr.get("head_pushed_at") or pr.get("updated_at")
    if not anchor:
        return 0.0
    return (now - _parse_iso(anchor)).total_seconds() / 3600.0


def is_stranded(
    *,
    draft: bool,
    required_green: bool,
    auto_merge_enabled: bool,
    soundness_gated: bool,
    age_hours: float,
    grace_hours: float,
) -> bool:
    """True when a PR looks like a stranded (never-enabled-or-dropped) auto-merge."""
    return (
        (not draft)
        and required_green
        and (not auto_merge_enabled)
        and (not soundness_gated)
        and age_hours > grace_hours
    )


def classify_pr(
    pr: dict[str, Any],
    now: dt.datetime,
    *,
    grace_hours: float = GRACE_PERIOD_HOURS,
) -> ClassifiedPR:
    """Classify one normalized PR record. Pure -- no I/O."""
    check_runs = pr.get("check_runs") or []
    changed_files = pr.get("changed_files") or []

    required_green = is_required_lane_green(check_runs)
    soundness_gated = is_soundness_gated(changed_files)
    auto_merge_enabled = bool(pr.get("auto_merge"))
    draft = bool(pr.get("draft"))
    age_h = head_age_hours(pr, now)
    stranded = is_stranded(
        draft=draft,
        required_green=required_green,
        auto_merge_enabled=auto_merge_enabled,
        soundness_gated=soundness_gated,
        age_hours=age_h,
        grace_hours=grace_hours,
    )

    return ClassifiedPR(
        number=pr["number"],
        title=pr.get("title", ""),
        html_url=pr.get("html_url", ""),
        draft=draft,
        required_green=required_green,
        soundness_gated=soundness_gated,
        auto_merge_enabled=auto_merge_enabled,
        head_age_hours=age_h,
        stranded=stranded,
    )


def classify_all(
    prs: list[dict[str, Any]],
    now: dt.datetime,
    *,
    grace_hours: float = GRACE_PERIOD_HOURS,
) -> list[ClassifiedPR]:
    return [classify_pr(pr, now, grace_hours=grace_hours) for pr in prs]


def stranded_prs(classified: list[ClassifiedPR]) -> list[ClassifiedPR]:
    """Stranded PRs, oldest-head-push first (longest stranded, most urgent)."""
    hits = [c for c in classified if c.stranded]
    return sorted(hits, key=lambda c: c.head_age_hours, reverse=True)


def is_post_merge_red(run: dict[str, Any] | None) -> bool:
    """True when the most recent Develop post-merge run completed red.

    Anything other than a completed `failure` (queued/in-progress,
    cancelled, success, or no run found at all) is treated as not-red --
    this flag exists to raise a same-day SLA on a genuine failure, not to
    editorialize about cancellations or in-flight runs.
    """
    if not run:
        return False
    return run.get("status") == "completed" and run.get("conclusion") == "failure"


def _fmt_hours(hours: float) -> str:
    days, rem = divmod(hours, 24.0)
    if days >= 1:
        return f"{days:.0f}d{rem:.0f}h"
    return f"{hours:.1f}h"


def build_digest(
    classified: list[ClassifiedPR],
    *,
    now: dt.datetime,
    repo: str,
    post_merge_red: bool = False,
    post_merge_run: dict[str, Any] | None = None,
) -> str:
    """Human-readable digest body.

    Empty-queue body (no stranded PRs, develop post-merge not red) is used
    by local/manual runs and by the one-time "mark existing digest empty"
    patch; --apply never CREATES an issue for that state.
    """
    hits = stranded_prs(classified)
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        DIGEST_BODY_MARKER,
        f"Green-but-unmerged PR sweep -- nightly digest (last updated {stamp})",
        "",
    ]

    if post_merge_red:
        run_url = (post_merge_run or {}).get("html_url", "")
        lines.append(f"## develop post-merge is RED -- {POST_MERGE_SLA}")
        lines.append("")
        lines.append(
            'The most recent "Develop post-merge" workflow run on develop\'s tip '
            f"completed with conclusion `failure` -- {run_url}".rstrip()
        )
        lines.append('See docs/operations/pr-triage.md "Develop post-merge SLA" for the fix-forward expectation.')
        lines.append("")

    if not hits:
        lines.append("No stranded PRs: every open, green, non-soundness develop PR has auto-merge on.")
        return "\n".join(lines)

    lines.append(
        f"{len(hits)} PR(s) green on required checks, non-draft, non-soundness-gated, "
        f"auto-merge OFF, head pushed > {GRACE_PERIOD_HOURS:.0f}h ago:"
    )
    lines.append("")
    for c in hits:
        lines.append(f"- #{c.number} {c.title} -- head pushed {_fmt_hours(c.head_age_hours)} ago -- {c.html_url}")
    lines.append("")
    lines.append(
        "This sweep never enables auto-merge itself -- re-run `gh pr merge --auto --squash` "
        "by hand (or re-push to retrigger auto-merge-on-open.yml's `synchronize` path) after "
        "confirming the PR is genuinely ready. See docs/operations/pr-triage.md."
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
    mutations otherwise. Mirrors soundness_drain_report.py's retry/urllib
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
                "User-Agent": "benchbox-green-unmerged-sweep",
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

    def get_all(
        self,
        path: str,
        params: dict[str, str] | None = None,
        max_items: int | None = None,
    ) -> list[dict[str, Any]]:
        """GET a list endpoint, following `page` params up to a sane cap.

        `max_items` stops fetching once that many items are collected --
        without it, a small per_page (e.g. 1) would page all the way to the
        cap just to return the first item.
        """
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
            if isinstance(result, dict) and "workflow_runs" in result:
                result = result["workflow_runs"]
            if not result:
                break
            out.extend(result)
            if max_items is not None and len(out) >= max_items:
                return out[:max_items]
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
        commit = client.get_one(f"repos/{owner}/{repo}/commits/{head_sha}") or {}
        commit_info = commit.get("commit") or {}
        head_pushed_at = (commit_info.get("committer") or {}).get("date") or (commit_info.get("author") or {}).get(
            "date"
        )
        normalized.append(
            {
                "number": number,
                "title": raw.get("title", ""),
                "html_url": raw.get("html_url", ""),
                "draft": bool(raw.get("draft")),
                "updated_at": raw.get("updated_at"),
                "head_pushed_at": head_pushed_at,
                # auto_merge is the PR's OWN current field -- re-fetched here,
                # never inferred from a workflow run's conclusion. See "Known
                # timing behavior" in the module docstring.
                "auto_merge": raw.get("auto_merge"),
                "changed_files": [f.get("filename", "") for f in files],
                "check_runs": [
                    {
                        "name": run.get("name"),
                        "status": run.get("status"),
                        "conclusion": run.get("conclusion"),
                        "started_at": run.get("started_at"),
                    }
                    for run in check_runs
                ],
            }
        )
    return normalized


def fetch_latest_develop_post_merge_run(client: GitHubClient, owner: str, repo: str) -> dict[str, Any] | None:
    """Latest "Develop post-merge" workflow run on develop, or None."""
    runs = client.get_all(
        f"repos/{owner}/{repo}/actions/workflows/{DEVELOP_POST_MERGE_WORKFLOW}/runs",
        {"branch": "develop", "per_page": "1"},
        max_items=1,
    )
    return runs[0] if runs else None


# ---------------------------------------------------------------------------
# Mutations (only reached under --apply): pinned-issue upsert only. No
# label, no auto-merge call, no PR comments.
# ---------------------------------------------------------------------------
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
    """Create/update the single digest issue (non-empty path)."""
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
    grace_hours = fixture.get("grace_hours", GRACE_PERIOD_HOURS)
    classified = classify_all(fixture["prs"], now, grace_hours=grace_hours)
    by_number = {c.number: c for c in classified}

    failures: list[str] = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    expected_stranded = set(fixture["expected_stranded"])
    actual_stranded = {c.number for c in stranded_prs(classified)}
    expect(
        actual_stranded == expected_stranded,
        f"stranded set mismatch: expected {sorted(expected_stranded)}, got {sorted(actual_stranded)}",
    )

    for number, reason in fixture.get("expected_excluded_reasons", {}).items():
        c = by_number.get(int(number))
        expect(c is not None, f"missing fixture PR #{number}")
        if c is None:
            continue
        expect(not c.stranded, f"PR #{number} unexpectedly stranded (expected excluded: {reason})")
        if reason == "not_green":
            expect(not c.required_green, f"PR #{number} expected required_green=False")
        elif reason == "auto_merge_on":
            expect(c.auto_merge_enabled, f"PR #{number} expected auto_merge_enabled=True")
        elif reason == "draft":
            expect(c.draft, f"PR #{number} expected draft=True")
        elif reason == "soundness_gated":
            expect(c.soundness_gated, f"PR #{number} expected soundness_gated=True")
        elif reason == "within_grace":
            expect(c.head_age_hours <= grace_hours, f"PR #{number} expected head_age_hours <= {grace_hours}")

    # build_digest must always carry the marker, whatever the queue state.
    expect(
        DIGEST_BODY_MARKER in build_digest(classified, now=now, repo=fixture.get("repo", DEFAULT_REPO)),
        "build_digest output missing DIGEST_BODY_MARKER",
    )

    post_merge_run = fixture.get("post_merge_run")
    if "expected_post_merge_red" in fixture:
        actual_red = is_post_merge_red(post_merge_run)
        expect(
            actual_red == fixture["expected_post_merge_red"],
            f"is_post_merge_red mismatch: expected {fixture['expected_post_merge_red']}, got {actual_red}",
        )
        if actual_red:
            digest_with_sla = build_digest(
                classified,
                now=now,
                repo=fixture.get("repo", DEFAULT_REPO),
                post_merge_red=True,
                post_merge_run=post_merge_run,
            )
            expect(POST_MERGE_SLA in digest_with_sla, "post-merge-red digest missing the fix-forward SLA line")

    if failures:
        print("SELF-TEST FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(f"SELF-TEST PASSED ({len(classified)} fixture PRs, {len(actual_stranded)} stranded).")
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
        help="Mutate: upsert the pinned digest issue (no label, no auto-merge call, no PR comments).",
    )
    parser.add_argument(
        "--grace-hours",
        type=float,
        default=GRACE_PERIOD_HOURS,
        help=f"Grace period in hours since head push (default: {GRACE_PERIOD_HOURS}).",
    )
    parser.add_argument(
        "--check-post-merge",
        action="store_true",
        help="Also check the latest 'Develop post-merge' run and flag the issue if it's red.",
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
    classified = classify_all(prs, now, grace_hours=args.grace_hours)
    hits = stranded_prs(classified)

    post_merge_run: dict[str, Any] | None = None
    post_merge_red = False
    if args.check_post_merge:
        post_merge_run = fetch_latest_develop_post_merge_run(client, owner, repo)
        post_merge_red = is_post_merge_red(post_merge_run)

    if args.json:
        print(
            json.dumps(
                {
                    "generated_at": now.isoformat(),
                    "repo": args.repo,
                    "evaluated_count": len(classified),
                    "stranded": [c.to_dict() for c in hits],
                    "post_merge_checked": args.check_post_merge,
                    "post_merge_red": post_merge_red,
                },
                indent=2,
            )
        )
    else:
        print(
            build_digest(
                classified, now=now, repo=args.repo, post_merge_red=post_merge_red, post_merge_run=post_merge_run
            )
        )

    if args.apply:
        should_have_issue = bool(hits) or post_merge_red
        if should_have_issue:
            body = build_digest(
                classified, now=now, repo=args.repo, post_merge_red=post_merge_red, post_merge_run=post_merge_run
            )
            outcome = upsert_pinned_issue(client, owner, repo, body)
            print(f"digest issue: {outcome}", file=sys.stderr)
        else:
            # Silent-when-clear means no new issue and no repeated updates --
            # but an existing digest must not keep showing yesterday's
            # stranded PRs forever. Patch it to the clear state exactly once.
            existing = find_pinned_issue(client, owner, repo)
            existing_body = (existing or {}).get("body") or ""
            # Stale content = either yesterday's stranded list OR a RED
            # post-merge banner from a recovered incident: a red+zero-stranded
            # day writes a body that ALREADY contains the clear-state line, so
            # guarding on that line alone would leave the RED banner up forever.
            stale = "No stranded PRs" not in existing_body or "develop post-merge is RED" in existing_body
            if existing is not None and stale:
                client.patch(
                    f"repos/{owner}/{repo}/issues/{existing['number']}",
                    {"body": build_digest(classified, now=now, repo=args.repo)},
                )
                print(f"digest issue: #{existing['number']} marked clear (one-time)", file=sys.stderr)
            else:
                print("digest issue: nothing stranded, no update (silent by design)", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
