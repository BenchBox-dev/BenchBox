#!/usr/bin/env python3
"""Release canary freshness gate.

Used by the release-PR validation workflow. It fails closed unless the latest
completed release canary workflow run on the configured branch is green, fresh,
and, by default, an ancestor of the release PR head.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ReadinessResult:
    ok: bool
    message: str
    summary: list[str]


def _parse_github_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _api_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _is_ancestor_with_git(ancestor_sha: str, head_sha: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor_sha, head_sha],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise RuntimeError(result.stderr.strip() or f"git merge-base failed with exit {result.returncode}")


def _override_active(env: dict[str, str], head_sha: str) -> tuple[bool, str]:
    override_sha = env.get("RELEASE_READINESS_OVERRIDE_SHA", "").strip()
    reason = env.get("RELEASE_READINESS_OVERRIDE_REASON", "").strip()
    if override_sha and reason and override_sha == head_sha:
        return True, reason
    return False, ""


def evaluate_canary_runs(
    runs: list[dict[str, Any]],
    *,
    now: datetime,
    max_age_hours: float,
    head_sha: str,
    require_ancestor: bool = True,
    is_ancestor: Callable[[str, str], bool] = _is_ancestor_with_git,
) -> ReadinessResult:
    """Return the release-readiness verdict for a workflow-runs payload."""
    completed = [run for run in runs if run.get("status") == "completed"]
    if not completed:
        return ReadinessResult(False, "No completed release canary runs found.", ["- canary: missing"])

    latest = max(completed, key=lambda run: _parse_github_time(run["updated_at"]))
    name = latest.get("display_title") or latest.get("name") or "release canary"
    conclusion = latest.get("conclusion")
    url = latest.get("html_url", "(no run URL)")
    run_sha = latest.get("head_sha", "")
    completed_at = _parse_github_time(latest["updated_at"])
    age_hours = (now - completed_at).total_seconds() / 3600
    age_display = f"{age_hours:.1f}h"

    summary = [
        f"- canary: {name}",
        f"- conclusion: {conclusion}",
        f"- completed_at: {completed_at.isoformat()}",
        f"- age: {age_display}",
        f"- sha: {run_sha}",
        f"- url: {url}",
    ]

    if conclusion != "success":
        return ReadinessResult(False, f"Latest release canary is {conclusion}; release is blocked.", summary)
    if age_hours > max_age_hours:
        return ReadinessResult(
            False,
            f"Latest release canary is stale ({age_display}; max {max_age_hours:g}h).",
            summary,
        )
    if require_ancestor and not is_ancestor(run_sha, head_sha):
        return ReadinessResult(
            False,
            f"Latest release canary SHA {run_sha} is not an ancestor of release head {head_sha}.",
            summary,
        )
    return ReadinessResult(True, "Release canary is green, fresh, and applicable.", summary)


def _workflow_runs_url(repo: str, workflow: str, branch: str) -> str:
    workflow_quoted = urllib.parse.quote(workflow, safe="")
    query = urllib.parse.urlencode({"branch": branch, "status": "completed", "per_page": "20"})
    return f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_quoted}/runs?{query}"


def _write_summary(result: ReadinessResult, *, summary_path: str | None, override_reason: str = "") -> None:
    lines = ["## Release Readiness", "", result.message, "", *result.summary]
    if override_reason:
        lines.extend(["", f"Emergency override: {override_reason}"])
    text = "\n".join(lines) + "\n"
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(text)
    else:
        print(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", default=os.environ.get("RELEASE_CANARY_WORKFLOW", "release-canary.yml"))
    parser.add_argument("--branch", default=os.environ.get("RELEASE_CANARY_BRANCH", "develop"))
    parser.add_argument(
        "--max-age-hours", type=float, default=float(os.environ.get("RELEASE_CANARY_MAX_AGE_HOURS", "48"))
    )
    parser.add_argument("--head-sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "joeharris76/BenchBox"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--no-ancestor-check", action="store_true")
    args = parser.parse_args(argv)

    if not args.head_sha:
        print("ERROR: release readiness requires GITHUB_SHA or --head-sha.", file=sys.stderr)
        return 1

    override, reason = _override_active(os.environ, args.head_sha)
    if override:
        result = ReadinessResult(
            True,
            "Release readiness override is active for this exact release head SHA.",
            [f"- sha: {args.head_sha}", "- canary: bypassed by explicit admin override"],
        )
        _write_summary(result, summary_path=os.environ.get("GITHUB_STEP_SUMMARY"), override_reason=reason)
        return 0

    if not args.token:
        print("ERROR: release readiness requires GITHUB_TOKEN or --token.", file=sys.stderr)
        return 1

    try:
        data = _api_json(_workflow_runs_url(args.repo, args.workflow, args.branch), args.token)
        result = evaluate_canary_runs(
            data.get("workflow_runs", []),
            now=datetime.now(UTC),
            max_age_hours=args.max_age_hours,
            head_sha=args.head_sha,
            require_ancestor=not args.no_ancestor_check,
        )
    except Exception as exc:
        result = ReadinessResult(
            False,
            f"Release canary readiness check failed while querying or validating evidence: {exc}",
            ["- canary: api-or-ancestor-check-error"],
        )
    _write_summary(result, summary_path=os.environ.get("GITHUB_STEP_SUMMARY"))
    if not result.ok:
        print(f"ERROR: {result.message}", file=sys.stderr)
        return 1
    print(result.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
