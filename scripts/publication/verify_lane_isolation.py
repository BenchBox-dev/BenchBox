#!/usr/bin/env python3
"""Verify publication lane isolation across site, explorer, and corpus lanes."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_IGNORES = (
    ".git",
    ".git/*",
    "**/.git/**",
    ".venv",
    ".venv/*",
    "**/.venv/**",
    "__pycache__",
    "**/__pycache__/**",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".pytest_cache",
    "**/.pytest_cache/**",
    ".ruff_cache",
    "**/.ruff_cache/**",
    ".mypy_cache",
    "**/.mypy_cache/**",
    "docs/_build",
    "docs/_build/**",
    "**/node_modules/**",
    "results-explorer/dist/**",
    "lane_artifacts/**",
    "site/**",
    ".DS_Store",
    "**/.DS_Store",
    "*.log",
    "tmp/**",
)

SHARED_BUILD_INPUTS: tuple[str, ...] = (
    "benchbox/",
    "pyproject.toml",
    "uv.lock",
)

LANE_PREFIXES: dict[str, tuple[str, ...]] = {
    "site": (
        "docs/",
        "landing/",
        "_blog/",
        "scripts/assemble_public_site.py",
        "scripts/publication/verify_lane_isolation.py",
        ".github/workflows/publication-lane-docs.yml",
    ),
    "explorer": (
        "results-explorer/",
        "_project/scripts/explorer_pipeline/",
        "_project/scripts/explorer_publish.py",
        "_project/scripts/results_explorer_snapshot_invariants.py",
        ".github/workflows/results-explorer-browser.yml",
    ),
    "corpus": (
        "results-data/",
        "scripts/validate_submission.py",
        "scripts/publication/validator_parity.py",
        ".github/workflows/validate-submission.yml",
        ".github/workflows/sync-results-data-to-published.yml",
        ".github/workflows/corpus-drift-check.yml",
    ),
}

LANE_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "site": ("prose_site", "api_docs"),
    "explorer": ("explorer_app", "results.duckdb"),
    "corpus": ("corpus_archive", "accepted_bundles"),
}

LANE_WORKFLOWS: dict[str, str] = {
    "site": ".github/workflows/publication-lane-docs.yml",
}


@dataclass
class LaneIsolationReport:
    lane: str
    digest: str
    file_count: int
    artifacts: list[str]
    success: bool
    errors: list[str] = field(default_factory=list)
    mutation_isolation_verified: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_ignored(rel_path: str, custom_ignores: Sequence[str] = DEFAULT_IGNORES) -> bool:
    normalized = rel_path.replace("\\", "/")
    parts = normalized.split("/")
    for ignore in custom_ignores:
        if fnmatch.fnmatch(normalized, ignore):
            return True
        if any(fnmatch.fnmatch(part, ignore) for part in parts):
            return True
    return False


def _is_shared_input(rel_path: str) -> bool:
    normalized = rel_path.strip().replace("\\", "/")
    if not normalized:
        return False
    for prefix in SHARED_BUILD_INPUTS:
        if prefix.endswith("/"):
            if normalized.startswith(prefix) or normalized == prefix[:-1]:
                return True
        else:
            if normalized == prefix or fnmatch.fnmatch(normalized, prefix):
                return True
    return False


def classify_path(rel_path: str) -> set[str]:
    """Return owning lanes for *rel_path*.

    Shared build inputs (``benchbox/``, ``pyproject.toml``, ``uv.lock``) are
    intentionally **not** classified to any lane — they are folded into every
    lane digest via ``SHARED_BUILD_INPUTS`` / ``scan_lane_files`` and are
    exempted from contamination checks via ``_is_shared_input``. Callers that
    gate on lane ownership must check ``_is_shared_input`` first; an empty
    return does not mean "unowned" when the path is a shared input. See
    ``verify_lane_isolation`` changed-paths handling for the canonical
    ``_is_shared_input → classify_path`` order.
    """
    normalized = rel_path.strip().replace("\\", "/")
    if not normalized:
        return set()
    matched = set()
    for lane, prefixes in LANE_PREFIXES.items():
        for prefix in prefixes:
            if prefix.endswith("/"):
                if normalized.startswith(prefix) or normalized == prefix[:-1]:
                    matched.add(lane)
                    break
            else:
                if normalized == prefix or fnmatch.fnmatch(normalized, prefix):
                    matched.add(lane)
                    break
    return matched


def scan_lane_files(  # noqa: C901
    lane: str,
    repo_root: Path,
    extra_files: dict[str, bytes] | None = None,
) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    prefixes = LANE_PREFIXES.get(lane, ())
    unreadable: list[str] = []

    for prefix in prefixes:
        target = repo_root / prefix
        if prefix.endswith("/"):
            if target.is_dir():
                for root, _, filenames in os.walk(target):
                    for fname in filenames:
                        file_path = Path(root) / fname
                        rel = file_path.relative_to(repo_root).as_posix()
                        if not is_ignored(rel):
                            try:
                                files[rel] = file_path.read_bytes()
                            except OSError as exc:
                                unreadable.append(f"{rel}: {exc}")
        else:
            if target.is_file():
                rel = target.relative_to(repo_root).as_posix()
                if not is_ignored(rel):
                    try:
                        files[rel] = target.read_bytes()
                    except OSError as exc:
                        unreadable.append(f"{rel}: {exc}")

    # Fold shared build inputs into every lane's digest.
    for prefix in SHARED_BUILD_INPUTS:
        target = repo_root / prefix
        if prefix.endswith("/"):
            if target.is_dir():
                for root, _, filenames in os.walk(target):
                    for fname in filenames:
                        file_path = Path(root) / fname
                        rel = file_path.relative_to(repo_root).as_posix()
                        if not is_ignored(rel):
                            try:
                                files[rel] = file_path.read_bytes()
                            except OSError as exc:
                                unreadable.append(f"{rel}: {exc}")
        else:
            if target.is_file():
                rel = target.relative_to(repo_root).as_posix()
                if not is_ignored(rel):
                    try:
                        files[rel] = target.read_bytes()
                    except OSError as exc:
                        unreadable.append(f"{rel}: {exc}")

    if unreadable:
        # Surface unreadable files as warnings; caller surfaces as errors.
        # Keep files dict without those entries but record the failure.
        # Store on the dict for caller to inspect via side-channel attribute.
        # Use an attribute on the dict object via a global.
        scan_lane_files._last_unreadable = unreadable  # type: ignore[attr-defined]
    else:
        scan_lane_files._last_unreadable = []  # type: ignore[attr-defined]

    if extra_files:
        for rel_path, content in extra_files.items():
            norm_rel = rel_path.replace("\\", "/")
            if is_ignored(norm_rel):
                continue
            # Shared inputs belong to every lane; admit them regardless of classify_path.
            if _is_shared_input(norm_rel) or lane in classify_path(norm_rel):
                files[norm_rel] = content

    return files


def compute_lane_digest(
    lane: str,
    repo_root: Path = REPO_ROOT,
    extra_files: dict[str, bytes] | None = None,
) -> str:
    """Deterministic SHA-256 digest of lane inputs plus shared build inputs."""
    lane_files = scan_lane_files(lane, repo_root=repo_root, extra_files=extra_files)
    hasher = hashlib.sha256()
    for rel_path in sorted(lane_files.keys()):
        file_sha = hashlib.sha256(lane_files[rel_path]).hexdigest()
        hasher.update(f"{rel_path}:{file_sha}\n".encode())
    return hasher.hexdigest()


def compute_all_lane_digests(
    repo_root: Path = REPO_ROOT,
    extra_files: dict[str, bytes] | None = None,
) -> dict[str, str]:
    return {
        lane: compute_lane_digest(lane, repo_root=repo_root, extra_files=extra_files)
        for lane in ("site", "explorer", "corpus")
    }


def _check_least_privilege(perms: Any) -> str | None:
    """Return error message if perms is not exactly {'contents': 'read'}."""
    if perms is None:
        return "missing explicit permissions block"
    if isinstance(perms, dict):
        if perms != {"contents": "read"}:
            non_read = {k: v for k, v in perms.items() if v != "read" or k != "contents"}
            if non_read:
                return f"has non-least-privilege permissions: {non_read} (must be contents: read)"
            return "permissions must be exactly {'contents': 'read'}"
        return None
    # Scalar form (e.g. 'write-all', 'read-all', or stray string)
    return f"permissions must be 'contents: read' dict, got {perms!r} (scalar permissions are not least-privilege)"


def verify_workflow_isolation(lane: str, repo_root: Path) -> list[str]:  # noqa: C901
    errors: list[str] = []
    workflow_rel = LANE_WORKFLOWS.get(lane)
    if not workflow_rel:
        return errors

    workflow_path = repo_root / workflow_rel
    if not workflow_path.is_file():
        errors.append(f"required workflow file missing: {workflow_rel}")
        return errors

    try:
        data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"failed to parse workflow YAML {workflow_rel}: {exc}")
        return errors

    if not isinstance(data, dict):
        errors.append(f"workflow {workflow_rel} is not a mapping")
        return errors

    # Check least-privilege permissions at top level
    perms = data.get("permissions")
    perm_err = _check_least_privilege(perms)
    if perm_err:
        errors.append(f"workflow {workflow_rel} {perm_err}")

    # Check job-level permissions override
    jobs = data.get("jobs", {})
    if isinstance(jobs, dict):
        for job_name, job_def in jobs.items():
            if not isinstance(job_def, dict):
                continue
            job_perms = job_def.get("permissions")
            if job_perms is None:
                continue
            job_err = _check_least_privilege(job_perms)
            if job_err:
                errors.append(f"workflow {workflow_rel} job '{job_name}' {job_err}")

    # Verify no deployment / pages write credentials (text scan is still a backstop)
    text = workflow_path.read_text(encoding="utf-8")
    if "deploy-pages" in text or "pages: write" in text or "id-token: write" in text:
        errors.append(f"workflow {workflow_rel} contains deployment or token write steps (must be decoupled)")

    # Verify artifact declarations via parsed steps, not plain substring
    expected_artifacts = LANE_ARTIFACTS.get(lane, ())
    found_artifacts: set[str] = set()
    if isinstance(jobs, dict):
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
                if isinstance(uses, str) and uses.startswith("actions/upload-artifact"):
                    with_cfg = step.get("with", {})
                    if isinstance(with_cfg, dict):
                        name = with_cfg.get("name")
                        if isinstance(name, str):
                            found_artifacts.add(name)
                        # Also check path field for artifact name hints
                        path_val = with_cfg.get("path", "")
                        if isinstance(path_val, str):
                            for art in expected_artifacts:
                                if art in path_val:
                                    # path contains artifact but name is authoritative; don't add
                                    pass
    for artifact in expected_artifacts:
        if artifact not in found_artifacts:
            errors.append(
                f"workflow {workflow_rel} does not declare required lane artifact: {artifact} (must be actions/upload-artifact with name: {artifact})"
            )

    return errors


def verify_lane_isolation(  # noqa: C901
    lane: str,
    repo_root: Path = REPO_ROOT,
    changed_paths: Sequence[str] | None = None,
    check_mutations: bool = True,
) -> LaneIsolationReport:
    errors: list[str] = []
    details: dict[str, Any] = {}

    lane_files = scan_lane_files(lane, repo_root=repo_root)
    unreadable = getattr(scan_lane_files, "_last_unreadable", [])  # type: ignore[attr-defined]
    if unreadable:
        errors.append(f"unreadable lane files for '{lane}': {unreadable}")
        details["unreadable_files"] = unreadable
    digest = compute_lane_digest(lane, repo_root=repo_root)
    file_count = len(lane_files)
    artifacts = list(LANE_ARTIFACTS.get(lane, ()))

    # 1. Workflow checks
    workflow_errors = verify_workflow_isolation(lane, repo_root=repo_root)
    errors.extend(workflow_errors)
    details["workflow_checks"] = workflow_errors if workflow_errors else "OK"

    # 2. Changed paths boundary checks
    if changed_paths:
        contaminating_paths: list[tuple[str, list[str]]] = []
        unclassified_paths: list[str] = []
        for path in changed_paths:
            normalized = path.strip().replace("\\", "/")
            if not normalized or is_ignored(normalized):
                continue
            if _is_shared_input(normalized):
                continue
            path_lanes = classify_path(normalized)
            if not path_lanes:
                unclassified_paths.append(normalized)
            elif lane not in path_lanes:
                contaminating_paths.append((normalized, sorted(path_lanes)))
        if contaminating_paths:
            errors.append(
                f"changed paths violate lane '{lane}' isolation: "
                f"{[p for p, _ in contaminating_paths]} belong to other lanes"
            )
        if unclassified_paths:
            errors.append(
                f"changed paths contain unclassified inputs not owned by any lane: "
                f"{unclassified_paths} (must be allowlisted as SHARED_BUILD_INPUTS or assigned to a lane)"
            )
        details["changed_paths_checked"] = len(changed_paths)
        details["contaminating_paths"] = contaminating_paths
        details["unclassified_paths"] = unclassified_paths

    # 3. Lane ownership consistency check (static, not a mathematical proof of artifact isolation)
    mutation_isolated = False
    if check_mutations:
        baseline_digests = compute_all_lane_digests(repo_root=repo_root)
        unrelated_lanes = [other for other in ("site", "explorer", "corpus") if other != lane]
        mutation_failures: list[str] = []

        synthetic_modifications = {
            "site": {"docs/_synthetic_isolation_probe.md": b"# synthetic site modification\n"},
            "explorer": {"results-explorer/synthetic_probe.ts": b"export const synthetic = true;\n"},
            "corpus": {"results-data/bundles/synthetic_probe.json": b'{"synthetic": true}\n'},
        }

        for other_lane in unrelated_lanes:
            mod = synthetic_modifications.get(other_lane, {})
            other_mutated_digests = compute_all_lane_digests(repo_root=repo_root, extra_files=mod)
            if other_mutated_digests[lane] != baseline_digests[lane]:
                mutation_failures.append(
                    f"modifying '{other_lane}' mutated '{lane}' digest from "
                    f"{baseline_digests[lane]} to {other_mutated_digests[lane]}"
                )
            if other_mutated_digests[other_lane] == baseline_digests[other_lane]:
                mutation_failures.append(f"synthetic modification in '{other_lane}' failed to change its own digest")

        target_mod = synthetic_modifications.get(lane, {})
        target_mutated_digests = compute_all_lane_digests(repo_root=repo_root, extra_files=target_mod)
        for other_lane in unrelated_lanes:
            if target_mutated_digests[other_lane] != baseline_digests[other_lane]:
                mutation_failures.append(
                    f"modifying '{lane}' mutated unrelated '{other_lane}' digest from "
                    f"{baseline_digests[other_lane]} to {target_mutated_digests[other_lane]}"
                )

        # Shared inputs must affect every lane (prove closure)
        shared_mod = {"benchbox/synthetic_shared_probe.py": b"# shared probe\n"}
        shared_mutated = compute_all_lane_digests(repo_root=repo_root, extra_files=shared_mod)
        for l in ("site", "explorer", "corpus"):
            if shared_mutated[l] == baseline_digests[l]:
                mutation_failures.append(
                    f"shared input modification failed to change '{l}' digest (SHARED_BUILD_INPUTS not folded)"
                )

        # Static disjoint sets + real-file ownership checks (excluding shared inputs)
        lane_filesets = {l: set(scan_lane_files(l, repo_root=repo_root).keys()) for l in ("site", "explorer", "corpus")}
        shared_files: set[str] = set()
        for p in lane_filesets["site"]:
            if _is_shared_input(p):
                shared_files.add(p)
        # Also collect shared files from other lanes (benchbox/pyproject folded into all)
        for l in ("explorer", "corpus"):
            for p in lane_filesets[l]:
                if _is_shared_input(p):
                    shared_files.add(p)
        for l in ("site", "explorer", "corpus"):
            for other in ("site", "explorer", "corpus"):
                if l >= other:
                    continue
                overlap = (lane_filesets[l] & lane_filesets[other]) - shared_files
                if overlap:
                    mutation_failures.append(f"lane '{l}' and '{other}' share non-shared files: {sorted(overlap)[:5]}")

        # Real-file classification: every non-shared file must classify to its lane.
        for l, files in lane_filesets.items():
            for rel in sorted(files):
                if _is_shared_input(rel):
                    continue
                owners = classify_path(rel)
                if l not in owners:
                    mutation_failures.append(
                        f"real file '{rel}' in lane '{l}' does not classify to that lane (classify_path={sorted(owners)})"
                    )

        # Vacuity guard: site and explorer must have at least one owned file
        for l in ("site", "explorer"):
            owned = [p for p in lane_filesets[l] if not _is_shared_input(p)]
            if not owned:
                mutation_failures.append(f"lane '{l}' has no owned (non-shared) files; mutation check is vacuous")

        # Real-file mutation: mutating a real file in one lane must not affect other lanes.
        # Deterministically pick the lexicographically first owned file per lane.
        for other_lane in unrelated_lanes:
            owned = sorted(p for p in lane_filesets[other_lane] if not _is_shared_input(p))
            if not owned:
                continue
            victim = owned[0]
            victim_path = repo_root / victim
            try:
                orig = victim_path.read_bytes()
            except OSError as exc:
                mutation_failures.append(f"cannot read real lane file '{victim}' for mutation check: {exc}")
                continue
            mutated = orig + b"\n# isolation-mutation-probe\n"
            real_mod = {victim: mutated}
            mutated_digests = compute_all_lane_digests(repo_root=repo_root, extra_files=real_mod)
            if mutated_digests[other_lane] == baseline_digests[other_lane]:
                mutation_failures.append(
                    f"real file mutation '{victim}' failed to change its own lane '{other_lane}' digest"
                )
            if mutated_digests[lane] != baseline_digests[lane]:
                mutation_failures.append(f"real file mutation '{victim}' in '{other_lane}' mutated '{lane}' digest")
        # Mutate own lane's real file and verify isolation of unrelated lanes
        own_owned = sorted(p for p in lane_filesets[lane] if not _is_shared_input(p))
        if own_owned:
            victim = own_owned[0]
            try:
                orig = (repo_root / victim).read_bytes()
                mutated = orig + b"\n# isolation-mutation-probe\n"
                real_mod = {victim: mutated}
                mutated_digests = compute_all_lane_digests(repo_root=repo_root, extra_files=real_mod)
                for other_lane in unrelated_lanes:
                    if mutated_digests[other_lane] != baseline_digests[other_lane]:
                        mutation_failures.append(
                            f"real file mutation '{victim}' in '{lane}' mutated unrelated '{other_lane}' digest"
                        )
                if mutated_digests[lane] == baseline_digests[lane]:
                    mutation_failures.append(
                        f"real file mutation '{victim}' in '{lane}' failed to change its own digest"
                    )
            except OSError as exc:
                mutation_failures.append(f"cannot read real lane file '{victim}' for mutation check: {exc}")

        if mutation_failures:
            errors.extend(mutation_failures)
        else:
            mutation_isolated = True

        details["lane_ownership_consistency"] = "OK" if mutation_isolated else mutation_failures
        # Keep legacy key for backwards compatibility
        details["mutation_isolation"] = details["lane_ownership_consistency"]

    success = len(errors) == 0
    return LaneIsolationReport(
        lane=lane,
        digest=digest,
        file_count=file_count,
        artifacts=artifacts,
        success=success,
        errors=errors,
        mutation_isolation_verified=mutation_isolated,
        details=details,
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify publication lane isolation.")
    parser.add_argument(
        "--lane",
        choices=["site", "explorer", "corpus", "all"],
        default="site",
        help="Publication lane to verify (default: site)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root directory",
    )
    parser.add_argument(
        "--changed-paths",
        nargs="*",
        help="List of changed paths to check against lane boundary",
    )
    parser.add_argument(
        "--changed-paths-file",
        type=Path,
        help="File containing newline-delimited changed paths",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON report",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = args.repo_root.resolve()

    # Fail closed: if --changed-paths was explicitly supplied it must carry at least
    # one non-empty path. With nargs="*" a bare `--changed-paths` would otherwise
    # silently become [] and skip contamination checks.
    if args.changed_paths is not None:
        non_empty = [p for p in args.changed_paths if p.strip()]
        if not non_empty and args.changed_paths_file is None:
            print("error: --changed-paths supplied but no paths provided (fails closed)", file=sys.stderr)
            return 1

    changed_paths: list[str] = []
    if args.changed_paths:
        changed_paths.extend(args.changed_paths)
    if args.changed_paths_file and args.changed_paths_file.is_file():
        changed_paths.extend(args.changed_paths_file.read_text(encoding="utf-8").splitlines())
    elif args.changed_paths_file and not args.changed_paths_file.is_file():
        print(f"changed-paths file not found: {args.changed_paths_file}", file=sys.stderr)
        return 1

    lanes_to_verify = ["site", "explorer", "corpus"] if args.lane == "all" else [args.lane]
    reports: list[LaneIsolationReport] = []
    all_success = True

    for lane in lanes_to_verify:
        report = verify_lane_isolation(
            lane=lane,
            repo_root=repo_root,
            changed_paths=changed_paths if changed_paths else None,
            check_mutations=True,
        )
        reports.append(report)
        if not report.success:
            all_success = False

    if args.json:
        payload = [r.to_dict() for r in reports] if len(reports) > 1 else reports[0].to_dict()
        print(json.dumps(payload, indent=2))
    else:
        for report in reports:
            status = "PASS" if report.success else "FAIL"
            # Keep legacy phrasing for PASS to preserve test compatibility, use clarified on FAIL
            if report.success:
                print(f"[{status}] Publication lane '{report.lane}' isolation verified:")
            else:
                print(f"[{status}] Publication lane '{report.lane}' isolation check:")
            print(f"  - Digest: {report.digest}")
            print(f"  - Files in lane: {report.file_count}")
            print(f"  - Artifacts: {', '.join(report.artifacts)}")
            print(f"  - Lane ownership consistency: {'OK' if report.mutation_isolation_verified else 'FAILED'}")
            if report.errors:
                print("  - Errors:")
                for err in report.errors:
                    print(f"    * {err}")

    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
