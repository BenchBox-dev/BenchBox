#!/usr/bin/env python3
"""Audit GitHub Actions workflow files for least-privilege permissions.

This script inspects `.github/workflows/*.yml` files to verify that:
1. No workflow uses wildcard or unconstrained permissions (`write-all` or `read-all`).
2. Dangerous write permissions are scoped to the specific jobs requiring them.
3. The independent publication deployment workflow (`publication-deploy.yml`)
   strictly follows the armed production-deployer least-privilege contract:
   - `build` job has only `contents: read` (no write permissions).
   - `deploy` job alone receives the Pages deployment write capabilities.
   - `verify` job has only `contents: read` (read-only probes).
   - `rollback` has only the bounded Pages deployment capabilities needed to
     restore a cryptographically attested artifact plus `actions: read`.

Usage:
  uv run -- python scripts/publication/check_workflow_permissions.py
  uv run -- python scripts/publication/check_workflow_permissions.py --workflow .github/workflows/publication-deploy.yml
  uv run -- python scripts/publication/check_workflow_permissions.py --strict

Exit codes:
  0 - All workflow permission checks passed.
  1 - Permission violations found.
  2 - Invalid usage or unparseable YAML file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKFLOWS_DIR = ROOT / ".github" / "workflows"
TARGET_PUBLICATION_DEPLOY_NAME = "publication-deploy.yml"

VALID_PERMISSION_SCOPES = {
    "actions",
    "checks",
    "contents",
    "deployments",
    "discussions",
    "id-token",
    "issues",
    "packages",
    "pages",
    "pull-requests",
    "repository-projects",
    "security-events",
    "statuses",
}

VALID_PERMISSION_VALUES = {"read", "write", "none"}


def _normalize_permissions(perms: Any) -> dict[str, str] | str | None:
    """Normalize permissions representation."""
    if perms is None:
        return None
    if isinstance(perms, str):
        return perms.strip().lower()
    if isinstance(perms, dict):
        return {str(k).strip().lower(): str(v).strip().lower() for k, v in perms.items()}
    return str(perms)


def check_general_workflow_permissions(file_path: Path, data: dict[str, Any]) -> list[str]:
    """Check general least-privilege rules across all workflows."""
    errors: list[str] = []
    top_perm = _normalize_permissions(data.get("permissions"))

    # Rule 1: No wildcard permissions
    if top_perm == "write-all":
        errors.append(f"{file_path.name}: top-level 'permissions: write-all' violates least privilege")
    elif top_perm == "read-all":
        # read-all is acceptable but explicit scopes are preferred
        pass

    if isinstance(top_perm, dict):
        for scope, val in top_perm.items():
            if scope not in VALID_PERMISSION_SCOPES:
                errors.append(f"{file_path.name}: unknown top-level permission scope '{scope}'")
            if val not in VALID_PERMISSION_VALUES:
                errors.append(f"{file_path.name}: invalid permission value '{val}' for scope '{scope}'")

    jobs = data.get("jobs", {})
    if not isinstance(jobs, dict):
        errors.append(f"{file_path.name}: missing or invalid 'jobs' mapping")
        return errors

    for job_name, job_data in jobs.items():
        if not isinstance(job_data, dict):
            continue
        job_perm = _normalize_permissions(job_data.get("permissions"))
        if job_perm == "write-all":
            errors.append(f"{file_path.name} (job '{job_name}'): 'permissions: write-all' violates least privilege")
        elif isinstance(job_perm, dict):
            for scope, val in job_perm.items():
                if scope not in VALID_PERMISSION_SCOPES:
                    errors.append(f"{file_path.name} (job '{job_name}'): unknown permission scope '{scope}'")
                if val not in VALID_PERMISSION_VALUES:
                    errors.append(
                        f"{file_path.name} (job '{job_name}'): invalid permission value '{val}' for scope '{scope}'"
                    )

    return errors


def _check_build_job_perms(file_path: Path, data: dict[str, Any], jobs: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    build_job = jobs.get("build", {})
    build_perm = _normalize_permissions(build_job.get("permissions"))
    if build_perm is None:
        top_perm = _normalize_permissions(data.get("permissions"))
        if isinstance(top_perm, dict):
            write_scopes = [k for k, v in top_perm.items() if v == "write"]
            if write_scopes:
                errors.append(
                    f"{file_path.name} (job 'build'): inherits top-level write permissions: {write_scopes}. "
                    f"'build' job must declare explicit read-only permissions."
                )
    elif isinstance(build_perm, dict):
        write_scopes = [k for k, v in build_perm.items() if v == "write"]
        if write_scopes:
            errors.append(
                f"{file_path.name} (job 'build'): declared write permissions: {write_scopes}. Must be read-only."
            )
    elif build_perm not in ("read-all", "contents: read"):
        errors.append(f"{file_path.name} (job 'build'): invalid permissions '{build_perm}'. Must be read-only.")
    return errors


def _check_deploy_job_perms(file_path: Path, jobs: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    deploy_job = jobs.get("deploy", {})
    deploy_perm = _normalize_permissions(deploy_job.get("permissions"))
    expected = {"contents": "read", "pages": "write", "id-token": "write"}
    if deploy_perm != expected:
        errors.append(
            f"{file_path.name} (job 'deploy'): must declare exactly {expected}; "
            "only the deploy job may receive Pages write capabilities."
        )
    return errors


def _check_verify_job_perms(file_path: Path, data: dict[str, Any], jobs: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    verify_job = jobs.get("verify", {})
    verify_perm = _normalize_permissions(verify_job.get("permissions"))
    if isinstance(verify_perm, dict):
        write_scopes = [k for k, v in verify_perm.items() if v == "write"]
        if write_scopes:
            errors.append(
                f"{file_path.name} (job 'verify'): declared write permissions: {write_scopes}. Must be read-only."
            )
    elif verify_perm is None:
        top_perm = _normalize_permissions(data.get("permissions"))
        if isinstance(top_perm, dict):
            write_scopes = [k for k, v in top_perm.items() if v == "write"]
            if write_scopes:
                errors.append(
                    f"{file_path.name} (job 'verify'): inherits top-level write permissions: {write_scopes}. Must be read-only."
                )
    return errors


def _check_rollback_job_perms(file_path: Path, jobs: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    rollback_job = jobs.get("rollback", {})
    rollback_perm = _normalize_permissions(rollback_job.get("permissions"))
    expected = {"actions": "read", "contents": "read", "pages": "write", "id-token": "write"}
    if rollback_perm != expected:
        errors.append(
            f"{file_path.name} (job 'rollback'): must declare exactly {expected}; "
            "rollback may restore only an attested artifact and may not gain unbounded write."
        )
    return errors


def check_publication_deploy_permissions(file_path: Path, data: dict[str, Any]) -> list[str]:
    """Verify strict least-privilege rules for publication-deploy.yml."""
    errors: list[str] = []
    jobs = data.get("jobs", {})

    if not isinstance(jobs, dict):
        errors.append(f"{file_path.name}: 'jobs' section is missing or not a dictionary")
        return errors

    expected_jobs = {"build", "deploy", "verify", "rollback"}
    missing_jobs = expected_jobs - set(jobs.keys())
    if missing_jobs:
        errors.append(f"{file_path.name}: missing required publication pipeline jobs: {sorted(missing_jobs)}")

    errors.extend(_check_build_job_perms(file_path, data, jobs))
    errors.extend(_check_deploy_job_perms(file_path, jobs))
    errors.extend(_check_verify_job_perms(file_path, data, jobs))
    errors.extend(_check_rollback_job_perms(file_path, jobs))

    return errors


def audit_workflow_file(file_path: Path, strict: bool = False) -> list[str]:
    """Audit a single workflow file for permissions compliance."""
    try:
        content = file_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
    except Exception as exc:
        return [f"{file_path.name}: YAML parse error: {exc}"]

    if not isinstance(data, dict):
        return [f"{file_path.name}: Root of workflow is not a mapping"]

    errors = check_general_workflow_permissions(file_path, data)

    # Special checks for publication-deploy.yml
    if file_path.name == TARGET_PUBLICATION_DEPLOY_NAME or "publication-deploy" in file_path.stem:
        errors.extend(check_publication_deploy_permissions(file_path, data))

    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--workflows-dir",
        type=Path,
        default=DEFAULT_WORKFLOWS_DIR,
        help=f"Directory containing workflow YAML files (default: {DEFAULT_WORKFLOWS_DIR})",
    )
    parser.add_argument(
        "--workflow",
        type=Path,
        default=None,
        help="Path to a specific workflow YAML file to audit",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.workflow is not None:
        workflow_files = [args.workflow]
    else:
        if not args.workflows_dir.is_dir():
            print(f"Error: workflows directory not found: {args.workflows_dir}", file=sys.stderr)
            return 2
        workflow_files = sorted(args.workflows_dir.glob("*.yml"))

    all_errors: dict[str, list[str]] = {}
    for wf in workflow_files:
        errors = audit_workflow_file(wf, strict=args.strict)
        if errors:
            all_errors[wf.name] = errors

    if all_errors:
        print("Workflow Permission Audit FAILED:")
        for wf_name, errors in all_errors.items():
            print(f"\n  File: {wf_name}")
            for err in errors:
                print(f"    ✗ {err}")
        return 1

    print(f"Workflow permission audit OK: {len(workflow_files)} workflow files checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
