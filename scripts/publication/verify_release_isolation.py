#!/usr/bin/env python3
"""Rehearsal-only release isolation verifier.

Proves a release fully self-hosts its site from a *single* GitHub Pages
deployment source, with no second deploy source and no hidden coupling of a
build step to a Pages deploy. This is the evidence tool for the A10 "single
deployment source" gate (G3 release-deploy removal): while the legacy
release-driven Pages deploy (``docs.yml``) still contains a ``deploy`` job,
isolation is NOT proven and this script fails.

This script MUST NOT deploy; it is a read-only verification tool.

What it checks, at the requested git ref:
  1. Count every workflow that contains a Pages deploy step (official
     ``actions/deploy-pages`` at any version/pin, known third-party deployers,
     or a raw ``gh-pages`` push). Isolation requires exactly one, and it must
     be the intended ``publication-deploy.yml``.
  2. The legacy ``docs.yml`` workflow must contain no Pages deploy step.
  3. No single job anywhere both builds the site AND deploys it (hidden
     coupling). A separate build job feeding a separate deploy job is fine.
  4. Any job that delegates to a reusable workflow (``jobs.<id>.uses``) is
     reported as un-analyzable rather than assumed clean.

Usage:
  uv run -- python scripts/publication/verify_release_isolation.py --ref origin/release --mode rehearsal
  uv run -- python scripts/publication/verify_release_isolation.py --ref origin/release --mode rehearsal --json

Exit codes:
  0 - Isolation proven (single deploy source, no hidden coupling).
  1 - Isolation not proven or operational error.
  2 - ``--mode prod`` is rejected (must use rehearsal mode).
"""

from __future__ import annotations

import argparse
import json
import re
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

# Known GitHub Pages deployer actions, matched on the version-independent
# ``owner/repo`` prefix so ``@v4``, ``@v5``, ``@main`` and 40-hex SHA pins are
# all caught. ``actions/deploy-pages`` is matched by suffix as well to cover a
# vendored fork path.
KNOWN_PAGES_DEPLOYERS = (
    "actions/deploy-pages",
    "peaceiris/actions-gh-pages",
    "JamesIves/github-pages-deploy-action",
    "crazy-max/ghaction-github-pages",
    "cloudflare/pages-action",
    "cloudflare/wrangler-action",
)

# ``run:`` script fragments that indicate a raw push to a Pages branch.
RAW_PAGES_PUSH_RE = re.compile(
    r"(git\s+push[^\n]*\bgh-pages\b)"
    r"|(\bnpx\s+gh-pages\b)"
    r"|(\bgh-pages\b[^\n]*--dist)"
    r"|(peaceiris/actions-gh-pages)",
    re.IGNORECASE,
)

BUILD_PATTERNS = (
    "api_docs",
    "prose_site",
    "assemble_public_site",
    "uv run python scripts/",
    "uv run -- python scripts/",
    "npm run build",
    "sphinx-build",
)


@dataclass
class ReleaseIsolationReport:
    mode: str
    ref: str
    deploy_sources: list[dict[str, Any]]
    deploy_source_count: int
    intended_deploy_workflow_present: bool
    legacy_deploy_workflow_deploys: bool
    hidden_couplings: list[dict[str, Any]]
    unanalyzable_jobs: list[dict[str, Any]]
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
    """List workflow YAML filenames (bare names) reachable from ref."""
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


def _uses_is_pages_deployer(uses: str) -> bool:
    action = uses.split("@", 1)[0].strip().lower()
    if not action:
        return False
    for known in KNOWN_PAGES_DEPLOYERS:
        if action == known or action.startswith(f"{known}/"):
            return True
    # Bare / vendored deploy-pages (``./.github/actions/deploy-pages``, forks).
    return action.endswith("/deploy-pages") or action == "deploy-pages"


def _job_pages_deployers(job_def: dict[str, Any]) -> list[str]:
    """Return the deploy markers found inside a single job's steps."""
    deployers: list[str] = []
    steps = job_def.get("steps", [])
    if not isinstance(steps, list):
        return deployers
    for step in steps:
        if not isinstance(step, dict):
            continue
        uses = step.get("uses", "")
        if isinstance(uses, str) and _uses_is_pages_deployer(uses):
            deployers.append(uses.strip())
        run = step.get("run", "")
        if isinstance(run, str) and RAW_PAGES_PUSH_RE.search(run):
            deployers.append("raw-run:gh-pages-push")
    return deployers


def _job_builds(job_def: dict[str, Any]) -> bool:
    steps = job_def.get("steps", [])
    if not isinstance(steps, list):
        return False
    step_runs = "\n".join(str(step.get("run", "")) for step in steps if isinstance(step, dict))
    job_name = str(job_def.get("name", ""))
    return any(p in step_runs or p in job_name for p in BUILD_PATTERNS)


@dataclass
class _WorkflowScan:
    deploy_jobs: dict[str, list[str]]
    coupled_jobs: list[str]
    unanalyzable_jobs: list[str]


def _scan_workflow(data: dict[str, Any]) -> _WorkflowScan:
    deploy_jobs: dict[str, list[str]] = {}
    coupled_jobs: list[str] = []
    unanalyzable_jobs: list[str] = []

    jobs = data.get("jobs", {})
    if not isinstance(jobs, dict):
        return _WorkflowScan(deploy_jobs, coupled_jobs, unanalyzable_jobs)

    for job_name, job_def in jobs.items():
        if not isinstance(job_def, dict):
            continue
        # A job that calls a reusable workflow has no inspectable steps.
        if isinstance(job_def.get("uses"), str) and job_def["uses"].strip():
            unanalyzable_jobs.append(str(job_name))
            continue
        deployers = _job_pages_deployers(job_def)
        if deployers:
            deploy_jobs[str(job_name)] = deployers
            if _job_builds(job_def):
                coupled_jobs.append(str(job_name))
    return _WorkflowScan(deploy_jobs, coupled_jobs, unanalyzable_jobs)


def _analyze(
    ref: str, workflow_files: list[str]
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
]:
    """Return (deploy_sources, hidden_couplings, unanalyzable_jobs, errors)."""
    deploy_sources: list[dict[str, Any]] = []
    hidden_couplings: list[dict[str, Any]] = []
    unanalyzable: list[dict[str, Any]] = []
    errors: list[str] = []

    for wf_name in sorted(workflow_files):
        try:
            data = yaml.safe_load(_read_workflow_at_ref(ref, wf_name))
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        except yaml.YAMLError as exc:
            errors.append(f"workflow '{wf_name}' has malformed YAML: {exc}")
            continue
        if not isinstance(data, dict):
            errors.append(f"workflow '{wf_name}' must have a mapping root")
            continue

        if not isinstance(data.get("jobs"), dict):
            errors.append(f"workflow '{wf_name}' has invalid jobs mapping")
            continue

        scan = _scan_workflow(data)
        if scan.deploy_jobs:
            deploy_sources.append(
                {
                    "workflow": wf_name,
                    "jobs": sorted(scan.deploy_jobs),
                    "deployers": sorted({d for ds in scan.deploy_jobs.values() for d in ds}),
                }
            )
        for job_name in scan.coupled_jobs:
            hidden_couplings.append(
                {
                    "workflow": wf_name,
                    "coupled_jobs": [job_name],
                    "description": (
                        f"Workflow '{wf_name}' job '{job_name}' both builds the site and "
                        "deploys it to Pages — hidden coupling that must be eliminated "
                        "before the release self-hosts its deployment."
                    ),
                }
            )
        for job_name in scan.unanalyzable_jobs:
            unanalyzable.append(
                {
                    "workflow": wf_name,
                    "job": job_name,
                    "description": (
                        f"Workflow '{wf_name}' job '{job_name}' delegates to a reusable "
                        "workflow; its steps cannot be inspected for a hidden Pages deploy."
                    ),
                }
            )
    return deploy_sources, hidden_couplings, unanalyzable, errors


def verify_release_isolation(ref: str, mode: str = "rehearsal") -> ReleaseIsolationReport:
    if mode == "prod":
        return ReleaseIsolationReport(
            mode=mode,
            ref=ref,
            deploy_sources=[],
            deploy_source_count=0,
            intended_deploy_workflow_present=False,
            legacy_deploy_workflow_deploys=False,
            hidden_couplings=[],
            unanalyzable_jobs=[],
            isolation_proven=False,
            errors=["--mode prod is rejected; must use --mode rehearsal for read-only verification"],
        )

    try:
        workflow_files = _get_workflow_files_at_ref(ref)
    except RuntimeError as exc:
        return ReleaseIsolationReport(
            mode=mode,
            ref=ref,
            deploy_sources=[],
            deploy_source_count=0,
            intended_deploy_workflow_present=False,
            legacy_deploy_workflow_deploys=False,
            hidden_couplings=[],
            unanalyzable_jobs=[],
            isolation_proven=False,
            errors=[str(exc)],
        )

    deploy_sources, hidden_couplings, unanalyzable, errors = _analyze(ref, workflow_files)

    source_names = {s["workflow"] for s in deploy_sources}
    deploy_source_count = len(deploy_sources)
    intended_present = INTENDED_DEPLOY_WORKFLOW in source_names
    legacy_deploys = LEGACY_DEPLOY_WORKFLOW in source_names

    if deploy_source_count == 0:
        errors.append(f"No Pages deploy source found in {ref}; expected exactly one ('{INTENDED_DEPLOY_WORKFLOW}').")
    if deploy_source_count > 1:
        errors.append(
            f"{deploy_source_count} Pages deploy sources found in {ref} "
            f"({sorted(source_names)}); isolation requires exactly one."
        )
    if legacy_deploys:
        errors.append(
            f"Legacy workflow '{LEGACY_DEPLOY_WORKFLOW}' still contains a Pages deploy step "
            "(the G3 release-deploy surface); isolation is not proven until it is removed."
        )
    if deploy_source_count >= 1 and not intended_present:
        errors.append(
            f"Intended deploy workflow '{INTENDED_DEPLOY_WORKFLOW}' does not contain a "
            f"Pages deploy step; deploy sources present: {sorted(source_names)}."
        )

    isolation_proven = (
        deploy_source_count == 1
        and intended_present
        and not legacy_deploys
        and not hidden_couplings
        and not unanalyzable
        and not errors
    )

    return ReleaseIsolationReport(
        mode=mode,
        ref=ref,
        deploy_sources=deploy_sources,
        deploy_source_count=deploy_source_count,
        intended_deploy_workflow_present=intended_present,
        legacy_deploy_workflow_deploys=legacy_deploys,
        hidden_couplings=hidden_couplings,
        unanalyzable_jobs=unanalyzable,
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
        for err in report.errors:
            print(f"ERROR: {err}", file=sys.stderr)
        for coupling in report.hidden_couplings:
            print(f"HIDDEN COUPLING: {coupling['description']}", file=sys.stderr)
        for job in report.unanalyzable_jobs:
            print(f"UNANALYZABLE: {job['description']}", file=sys.stderr)
        if report.isolation_proven:
            print(f"[OK] Release isolation proven for {report.ref} (mode={report.mode})")
            print(f"  single deploy source: {report.deploy_sources[0]['workflow']}")
        else:
            print(f"[FAIL] Release isolation NOT proven for {report.ref} (mode={report.mode})")
            print(f"  deploy sources ({report.deploy_source_count}): {[s['workflow'] for s in report.deploy_sources]}")

    if args.mode == "prod":
        return 2
    return 0 if report.isolation_proven else 1


if __name__ == "__main__":
    sys.exit(main())
