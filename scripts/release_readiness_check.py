#!/usr/bin/env python3
"""Release canary freshness gate.

Used by the release-PR validation workflow. It fails closed unless the latest
completed release canary workflow run is green, fresh, and, by default, has a
summary artifact whose checked commit is an ancestor of the release PR head.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

BOOTSTRAP_REQUIRED_EXIT_CODE = 20


@dataclass(frozen=True)
class ReadinessResult:
    ok: bool
    message: str
    summary: list[str]
    bootstrap_required: bool = False


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


def _api_bytes(url: str, token: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _release_canary_commit_sha(run: dict[str, Any], token: str, *, expected_checked_ref: str = "develop") -> str:
    """Return the commit SHA that release-canary.yml actually checked out and tested."""
    artifacts_url = run.get("artifacts_url")
    if not artifacts_url:
        if expected_checked_ref:
            raise RuntimeError(f"release canary run {run.get('id', '(unknown)')} has no artifacts URL")
        return str(run.get("head_sha", "")).strip()

    artifacts = _api_json(artifacts_url, token).get("artifacts", [])
    summary_artifacts = [
        artifact
        for artifact in artifacts
        if artifact.get("name") == "release-canary-summary" and not artifact.get("expired")
    ]
    if not summary_artifacts:
        raise RuntimeError(f"release canary run {run.get('id', '(unknown)')} has no release-canary-summary artifact")

    latest_summary = max(summary_artifacts, key=lambda artifact: artifact.get("created_at", ""))
    archive_url = latest_summary.get("archive_download_url")
    if not archive_url:
        raise RuntimeError(f"release canary run {run.get('id', '(unknown)')} summary artifact has no download URL")

    archive_bytes = _api_bytes(archive_url, token)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        summary_names = [name for name in archive.namelist() if name.endswith("release-canary-summary.json")]
        if not summary_names:
            raise RuntimeError(f"release canary run {run.get('id', '(unknown)')} summary artifact has no summary JSON")
        with archive.open(summary_names[0]) as handle:
            payload = json.loads(handle.read().decode("utf-8"))

    checked_ref = str(payload.get("checked_ref", "")).strip()
    if expected_checked_ref and checked_ref != expected_checked_ref:
        raise RuntimeError(
            f"release canary run {run.get('id', '(unknown)')} tested {checked_ref!r}, expected {expected_checked_ref!r}"
        )
    commit_sha = str(payload.get("commit_sha", "")).strip()
    if not commit_sha:
        raise RuntimeError(f"release canary run {run.get('id', '(unknown)')} summary did not record commit_sha")
    return commit_sha


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
    canary_commit_sha: Callable[[dict[str, Any]], str] | None = None,
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
    checked_sha = run_sha
    completed_at = _parse_github_time(latest["updated_at"])
    age_hours = (now - completed_at).total_seconds() / 3600
    age_display = f"{age_hours:.1f}h"

    summary = [
        f"- canary: {name}",
        f"- conclusion: {conclusion}",
        f"- completed_at: {completed_at.isoformat()}",
        f"- age: {age_display}",
        f"- workflow_sha: {run_sha}",
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
    if require_ancestor and canary_commit_sha is not None:
        checked_sha = canary_commit_sha(latest)
    if checked_sha != run_sha:
        summary.append(f"- checked_sha: {checked_sha}")
    if require_ancestor and not is_ancestor(checked_sha, head_sha):
        return ReadinessResult(
            False,
            f"Latest release canary SHA {checked_sha} is not an ancestor of release head {head_sha}.",
            summary,
        )
    return ReadinessResult(True, "Release canary is green, fresh, and applicable.", summary)


def _workflow_runs_url(repo: str, workflow: str, branch: str) -> str:
    branch = branch.strip()
    if not branch:
        raise ValueError("release canary workflow run lookup requires a trusted branch filter")
    workflow_quoted = urllib.parse.quote(workflow, safe="")
    query_args = {"branch": branch, "status": "completed", "per_page": "20"}
    query = urllib.parse.urlencode(query_args)
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
    parser.add_argument(
        "--branch",
        default=os.environ.get("RELEASE_CANARY_BRANCH", "develop"),
        help="Trusted branch/ref that owns the release-canary workflow runs (the default branch, develop as of the 2026-07-08 switch).",
    )
    parser.add_argument(
        "--max-age-hours", type=float, default=float(os.environ.get("RELEASE_CANARY_MAX_AGE_HOURS", "48"))
    )
    parser.add_argument("--head-sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "joeharris76/BenchBox"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--checked-ref", default=os.environ.get("RELEASE_CANARY_CHECKED_REF", "develop"))
    parser.add_argument("--no-ancestor-check", action="store_true")
    parser.add_argument(
        "--bootstrap-on-missing-workflow",
        action="store_true",
        help=f"Return exit {BOOTSTRAP_REQUIRED_EXIT_CODE} when the canary workflow is not yet available on the default branch.",
    )
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
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and args.bootstrap_on_missing_workflow:
            result = ReadinessResult(
                False,
                (
                    f"Release canary workflow {args.workflow!r} is not available from the repository "
                    "default branch yet; inline bootstrap evidence is required."
                ),
                [
                    "- canary: bootstrap-required",
                    f"- workflow: {args.workflow}",
                    f"- branch_filter: {args.branch or '(none)'}",
                ],
                bootstrap_required=True,
            )
        else:
            result = ReadinessResult(
                False,
                f"Release canary readiness check failed while querying GitHub: HTTP {exc.code} {exc.reason}",
                ["- canary: api-or-ancestor-check-error"],
            )
    except Exception as exc:
        result = ReadinessResult(
            False,
            f"Release canary readiness check failed while querying GitHub: {exc}",
            ["- canary: api-or-ancestor-check-error"],
        )
    else:
        try:
            result = evaluate_canary_runs(
                data.get("workflow_runs", []),
                now=datetime.now(UTC),
                max_age_hours=args.max_age_hours,
                head_sha=args.head_sha,
                require_ancestor=not args.no_ancestor_check,
                canary_commit_sha=lambda run: _release_canary_commit_sha(
                    run,
                    args.token,
                    expected_checked_ref=args.checked_ref,
                ),
            )
        except Exception as exc:
            result = ReadinessResult(
                False,
                f"Release canary readiness check failed while validating evidence: {exc}",
                ["- canary: api-or-ancestor-check-error"],
            )
    _write_summary(result, summary_path=os.environ.get("GITHUB_STEP_SUMMARY"))
    if not result.ok:
        print(f"ERROR: {result.message}", file=sys.stderr)
        return BOOTSTRAP_REQUIRED_EXIT_CODE if result.bootstrap_required else 1
    print(result.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
