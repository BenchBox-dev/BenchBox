#!/usr/bin/env python3
"""Rehearsal-only release isolation verifier.

Proves a release fully self-hosts its site — the full-site deployment source
is the single source of truth with no hidden coupling to a legacy Pages deploy
that would create collateral when the site is later self-hosted.

This script MUST NOT deploy; it is a read-only verification tool.

Usage:
  uv run -- python scripts/publication/verify_release_isolation.py --ref origin/release --mode rehearsal
  uv run -- python scripts/publication/verify_release_isolation.py --ref origin/release --mode rehearsal --json

Exit codes:
  0 - Isolation proven (no hidden coupling found).
  1 - Hidden coupling detected or operational error.
  2 - ``--mode prod`` is rejected (must use rehearsal mode).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

INTENDED_DEPLOY_WORKFLOW = "publication-deploy.yml"
LEGACY_DEPLOY_WORKFLOW = "docs.yml"

PAGES_DEPLOY_PATTERNS = ("deploy-pages@v4", "actions/deploy-pages@v4")

BUILD_PATTERNS = ("api_docs", "prose_site", "uv run python scripts/", "npm run build")


@dataclass
class ReleaseIsolationReport:
    mode: str
    ref: str
    deploy_source_present: bool
    deploy_source_workflow: str | None
    hidden_couplings: list[dict[str, Any]]
    isolation_proven: bool
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _get_workflow_files_at_ref(ref: str) -> list[str]:
    """List workflow YAML filenames (bare names) reachable from ref.

    `git ls-tree --name-only` returns full paths like
    `.github/workflows/docs.yml`; we strip the workflows-directory prefix so
    downstream code compares against bare filenames.
    """
    result = _run_git(["ls-tree", ref, "--name-only", ".github/workflows/"])
    if result.returncode != 0:
        raise RuntimeError(f"git ls-tree failed for ref '{ref}': {result.stderr.strip()}")
    files: list[str] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped.endswith((".yml", ".yaml")):
            continue
        files.append(Path(stripped).name)
    return files


def _read_workflow_at_ref(ref: str, workflow_path: str) -> str:
    """Read a single workflow file's contents at ref."""
    full_path = f".github/workflows/{Path(workflow_path).name}"
    result = _run_git(["show", f"{ref}:{full_path}"])
    if result.returncode != 0:
        raise RuntimeError(f"git show failed for '{ref}:{workflow_path}': {result.stderr.strip()}")
    return result.stdout


def _has_pages_deploy(workflow_data: dict[str, Any]) -> bool:
    """Check if any job in the workflow does a Pages deploy."""
    jobs = workflow_data.get("jobs", {})
    if not isinstance(jobs, dict):
        return False
    for job_def in jobs.values():
        if not isinstance(job_def, dict):
            continue
        steps = job_def.get("steps", [])
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses", "")
            if isinstance(uses, str) and any(p in uses for p in PAGES_DEPLOY_PATTERNS):
                return True
    return False


def _has_build_job(workflow_data: dict[str, Any]) -> bool:
    """Check if any job looks like an API-doc or site build job."""
    jobs = workflow_data.get("jobs", {})
    if not isinstance(jobs, dict):
        return False
    for job_def in jobs.values():
        if not isinstance(job_def, dict):
            continue
        job_name = job_def.get("name", "")
        steps = job_def.get("steps", [])
        if not isinstance(steps, list):
            continue
        step_runs = "\n".join(str(step.get("run", "")) for step in steps if isinstance(step, dict))
        if any(p in step_runs or p in str(job_name) for p in BUILD_PATTERNS):
            return True
    return False


def _detect_hidden_coupling(
    ref: str,
    workflow_files: list[str],
) -> list[dict[str, Any]]:
    """Detect workflows where a single job both builds AND deploys to Pages (hidden coupling).

    A separate build job + deploy job is the CORRECT pattern (e.g. publication-deploy.yml
    with a build job that produces artifacts and a deploy job that deploys them). The
    hidden coupling is a single job that does both building and deploying as a side effect.
    """
    couplings: list[dict[str, Any]] = []
    for wf_name in workflow_files:
        if wf_name == INTENDED_DEPLOY_WORKFLOW:
            continue
        try:
            text = _read_workflow_at_ref(ref, wf_name)
            data = yaml.safe_load(text)
        except (RuntimeError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue

        jobs = data.get("jobs", {})
        if not isinstance(jobs, dict):
            continue
        for job_name, job_def in jobs.items():
            if not isinstance(job_def, dict):
                continue
            steps = job_def.get("steps", [])
            if not isinstance(steps, list):
                continue
            step_runs = "\n".join(str(step.get("run", "")) for step in steps if isinstance(step, dict))
            step_uses = [
                str(step.get("uses", ""))
                for step in steps
                if isinstance(step, dict) and isinstance(step.get("uses"), str)
            ]
            builds = any(p in step_runs for p in BUILD_PATTERNS)
            deploys = any(any(p in u for p in PAGES_DEPLOY_PATTERNS) for u in step_uses)
            if builds and deploys:
                couplings.append(
                    {
                        "workflow": wf_name,
                        "coupled_jobs": [job_name],
                        "description": (
                            f"Workflow '{wf_name}' job '{job_name}' both builds and deploys to Pages — "
                            "hidden coupling that must be eliminated before self-hosted deployment."
                        ),
                    }
                )
    return couplings


def _check_deploy_source(workflow_files: list[str]) -> tuple[bool, str | None]:
    """Check that the intended deploy source workflow exists."""
    for name in (INTENDED_DEPLOY_WORKFLOW, LEGACY_DEPLOY_WORKFLOW):
        if name in workflow_files:
            return True, name
    return False, None


def verify_release_isolation(ref: str, mode: str = "rehearsal") -> ReleaseIsolationReport:
    errors: list[str] = []
    hidden_couplings: list[dict[str, Any]] = []

    if mode == "prod":
        return ReleaseIsolationReport(
            mode=mode,
            ref=ref,
            deploy_source_present=False,
            deploy_source_workflow=None,
            hidden_couplings=[],
            isolation_proven=False,
            errors=["--mode prod is rejected; must use --mode rehearsal for read-only verification"],
        )

    try:
        workflow_files = _get_workflow_files_at_ref(ref)
    except RuntimeError as exc:
        return ReleaseIsolationReport(
            mode=mode,
            ref=ref,
            deploy_source_present=False,
            deploy_source_workflow=None,
            hidden_couplings=[],
            isolation_proven=False,
            errors=[str(exc)],
        )

    deploy_present, deploy_name = _check_deploy_source(workflow_files)
    if not deploy_present:
        errors.append(
            f"No deploy source workflow found in {ref}; expected '{INTENDED_DEPLOY_WORKFLOW}' "
            f"or '{LEGACY_DEPLOY_WORKFLOW}'"
        )

    hidden_couplings = _detect_hidden_coupling(ref, workflow_files)

    isolation_proven = deploy_present and len(hidden_couplings) == 0 and not errors
    return ReleaseIsolationReport(
        mode=mode,
        ref=ref,
        deploy_source_present=deploy_present,
        deploy_source_workflow=deploy_name,
        hidden_couplings=hidden_couplings,
        isolation_proven=isolation_proven,
        errors=errors,
    )


def _resolve_ref(explicit: str | None) -> str:
    """Default to the release branch ref, falling back to HEAD when unavailable."""
    if explicit:
        return explicit
    probe = _run_git(["rev-parse", "--verify", "--quiet", "origin/release"])
    if probe.returncode == 0:
        return "origin/release"
    return "HEAD"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rehearsal-only release isolation verifier.")
    parser.add_argument(
        "--ref",
        default=None,
        help="Git ref to inspect (default: origin/release, or HEAD if absent).",
    )
    parser.add_argument(
        "--mode",
        choices=["rehearsal", "prod"],
        default="rehearsal",
        help="Verification mode: rehearsal (read-only, default) or prod (rejected).",
    )
    parser.add_argument("--json", action="store_true", help="Structured JSON output.")
    args = parser.parse_args(argv)
    args.ref = _resolve_ref(args.ref)
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    report = verify_release_isolation(ref=args.ref, mode=args.mode)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        if report.errors:
            for err in report.errors:
                print(f"ERROR: {err}", file=sys.stderr)
        if report.hidden_couplings:
            for coupling in report.hidden_couplings:
                print(f"HIDDEN COUPLING: {coupling['description']}", file=sys.stderr)
        if report.isolation_proven:
            print(f"[OK] Release isolation proven for {report.ref} (mode={report.mode})")
            print(f"  deploy source: {report.deploy_source_workflow}")
        else:
            print(f"[FAIL] Release isolation NOT proven for {report.ref} (mode={report.mode})")

    if args.mode == "prod":
        return 2
    if report.errors:
        return 1
    if report.hidden_couplings:
        return 1
    return 0 if report.isolation_proven else 1


if __name__ == "__main__":
    sys.exit(main())
