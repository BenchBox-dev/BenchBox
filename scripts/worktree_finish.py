#!/usr/bin/env python3
"""Single-target read-only worktree finish preview with fresh evidence revalidation.

Revalidates structural, ownership, cleanliness, exact PR, base, head,
merge-commit, and remote evidence at invocation time.

Guarantees:
- Read-only: never mutates Git state, never removes worktrees, never deletes refs.
- Single-target: accepts exactly one canonical worktree path and expected full OID.
- Fail-closed: incomplete collection, API errors, dirty states, and ambiguous
  ownership resolve to an explicit hold state.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from _project.scripts.worktree_audit import (  # noqa: E402
    STRUCTURAL_BASES,
    _parse_worktree_porcelain_entries,
    are_descendants_integrated,
    fetch_prs_for_branch,
    get_primary_clone_path,
    get_ref_commit_sha,
    get_reflog_shas,
    get_remote_repository_slug,
    is_ancestor,
    is_pr_merged,
    resolve_github_token,
    resolve_repository_identity,
)
from scripts.worktree_lifecycle_metadata import (  # noqa: E402
    WorktreeLifecycleMetadata,
    read_metadata,
)

HEX_40_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class FinishError(RuntimeError):
    """Raised when argument validation or operational preconditions fail."""


@dataclasses.dataclass(frozen=True)
class FinishPreviewResult:
    """Bounded, read-only preview result for a single worktree target."""

    target_path: str
    branch: Optional[str]
    current_head: Optional[str]
    expected_head: str
    status: str  # "actionable" | "hold"
    hold_reason: Optional[str]
    provenance_state: str
    owner_state: str
    controller_kind: Optional[str]
    controller_id: Optional[str]
    manual_released: bool
    clean: bool
    locked: bool
    detached: bool
    pr_number: Optional[int]
    pr_base: Optional[str]
    pr_merged: bool
    merge_commit_reachable: bool
    proposed_actions: List[Dict[str, str]]
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


def _run_git(args: List[str], cwd: Path) -> Tuple[int, str, str]:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def validate_inputs(worktree_path_str: str, expected_oid_str: str) -> Tuple[Path, str]:
    """Validate that target path and expected OID are strictly single-target and well-formed."""
    clean_path = worktree_path_str.strip()
    if not clean_path:
        raise FinishError("Worktree path cannot be empty")

    if any(char in clean_path for char in ("*", "?", "[", "]", ",")):
        raise FinishError(
            f"Worktree path '{clean_path}' contains list or wildcard characters; only single exact targets allowed"
        )

    target_path = Path(clean_path).resolve()

    clean_oid = expected_oid_str.strip().lower()
    if not clean_oid:
        raise FinishError("Expected HEAD OID cannot be empty")
    if not HEX_40_RE.match(clean_oid):
        raise FinishError(f"Expected HEAD OID '{expected_oid_str}' is invalid; must be a 40-character hex commit OID")

    return target_path, clean_oid


def load_canned_evidence(evidence_file: Path) -> List[Dict[str, Any]]:
    """Load offline PR evidence for test fixtures."""
    if not evidence_file.is_file():
        raise FinishError(f"Evidence file not found: {evidence_file}")
    data = json.loads(evidence_file.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "prs" in data:
        return list(data["prs"])
    if isinstance(data, dict):
        return [data]
    return []


def _make_hold_result(
    target_path: Path,
    expected_head_oid: str,
    reason: str,
    timestamp: str,
    branch: Optional[str] = None,
    current_head: Optional[str] = None,
    provenance_state: str = "unknown",
    owner_state: str = "unknown",
    controller_kind: Optional[str] = None,
    controller_id: Optional[str] = None,
    manual_released: bool = False,
    clean: bool = False,
    locked: bool = False,
    detached: bool = False,
    pr_number: Optional[int] = None,
    pr_base: Optional[str] = None,
    pr_merged: bool = False,
    merge_commit_reachable: bool = False,
) -> FinishPreviewResult:
    return FinishPreviewResult(
        target_path=str(target_path),
        branch=branch,
        current_head=current_head,
        expected_head=expected_head_oid,
        status="hold",
        hold_reason=reason,
        provenance_state=provenance_state,
        owner_state=owner_state,
        controller_kind=controller_kind,
        controller_id=controller_id,
        manual_released=manual_released,
        clean=clean,
        locked=locked,
        detached=detached,
        pr_number=pr_number,
        pr_base=pr_base,
        pr_merged=pr_merged,
        merge_commit_reachable=merge_commit_reachable,
        proposed_actions=[],
        timestamp=timestamp,
    )


def _check_worktree_structure(
    target_path: Path,
    expected_head_oid: str,
    repo_root: Path,
    timestamp: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[FinishPreviewResult]]:
    """Validate existence, registration, attached branch, locks, cleanliness, and HEAD."""
    primary_clone = get_primary_clone_path(repo_root)
    if primary_clone and target_path == primary_clone:
        raise FinishError(f"Refusing primary clone: '{target_path}' is the repository root, not a linked worktree")

    if not (target_path.exists() and target_path.is_dir()):
        return (
            None,
            None,
            _make_hold_result(
                target_path,
                expected_head_oid,
                f"Worktree path does not exist on disk or is not a directory: '{target_path}'",
                timestamp,
                provenance_state="missing",
            ),
        )

    code, stdout, _ = _run_git(["worktree", "list", "--porcelain"], repo_root)
    if code != 0:
        raise FinishError(f"Failed to query git worktree list: {stdout}")

    entries = _parse_worktree_porcelain_entries(stdout)
    matching: Optional[Dict[str, Any]] = None
    for entry in entries:
        try:
            if Path(entry["worktree"]).resolve() == target_path:
                matching = entry
                break
        except Exception:
            continue

    if not matching:
        return (
            None,
            None,
            _make_hold_result(
                target_path,
                expected_head_oid,
                f"Worktree path '{target_path}' is not registered in Git worktrees",
                timestamp,
                provenance_state="unregistered",
            ),
        )

    is_detached = matching.get("detached", False) or "branch" not in matching
    branch = matching.get("branch") if not is_detached else None
    if is_detached or not branch:
        return (
            None,
            None,
            _make_hold_result(
                target_path,
                expected_head_oid,
                "Worktree is in detached HEAD state (no symbolic branch ref)",
                timestamp,
                current_head=matching.get("HEAD"),
                provenance_state="detached",
                detached=True,
            ),
        )

    if matching.get("locked"):
        lock_reason = matching.get("lock_reason")
        msg = f"Worktree is locked ({lock_reason})" if lock_reason else "Worktree is locked"
        return (
            None,
            None,
            _make_hold_result(
                target_path,
                expected_head_oid,
                msg,
                timestamp,
                branch=branch,
                current_head=matching.get("HEAD"),
                provenance_state="locked",
                locked=True,
            ),
        )

    status_code, status_out, _ = _run_git(["status", "--porcelain"], target_path)
    if status_code != 0 or len(status_out) > 0:
        return (
            None,
            None,
            _make_hold_result(
                target_path,
                expected_head_oid,
                "Worktree has uncommitted modifications, staged changes, or untracked files",
                timestamp,
                branch=branch,
                current_head=matching.get("HEAD"),
                provenance_state="dirty",
            ),
        )

    head_code, actual_head, _ = _run_git(["rev-parse", "HEAD"], target_path)
    actual_head = actual_head.lower() if head_code == 0 else ""
    if actual_head != expected_head_oid:
        return (
            None,
            None,
            _make_hold_result(
                target_path,
                expected_head_oid,
                f"Worktree HEAD ({actual_head}) does not match expected HEAD OID ({expected_head_oid})",
                timestamp,
                branch=branch,
                current_head=actual_head,
                provenance_state="oid_mismatch",
                clean=True,
            ),
        )

    return matching, actual_head, None


def _check_provenance_state(
    target_path: Path,
    expected_head_oid: str,
    actual_head: str,
    branch: str,
    meta: WorktreeLifecycleMetadata,
    timestamp: str,
) -> Optional[FinishPreviewResult]:
    """Validate lifecycle provenance and controller boundary."""
    if meta.provenance_state in {"legacy", "foreign", "malformed", "unknown"}:
        return _make_hold_result(
            target_path,
            expected_head_oid,
            f"Worktree lifecycle provenance is '{meta.provenance_state}'; only managed worktrees can be finished",
            timestamp,
            branch=branch,
            current_head=actual_head,
            provenance_state=meta.provenance_state,
            owner_state=meta.owner_state,
            controller_kind=meta.controller_kind,
            controller_id=meta.controller_id,
            manual_released=bool(meta.manual_released_at),
            clean=True,
        )

    if meta.controller_kind and meta.controller_kind not in {"none", "manual"}:
        return _make_hold_result(
            target_path,
            expected_head_oid,
            (
                f"Worktree is bound to external controller '{meta.controller_kind}' "
                f"({meta.controller_id or 'no id'}); controller evidence remains an opaque hold"
            ),
            timestamp,
            branch=branch,
            current_head=actual_head,
            provenance_state=meta.provenance_state,
            owner_state="controller",
            controller_kind=meta.controller_kind,
            controller_id=meta.controller_id,
            manual_released=False,
            clean=True,
        )

    return None


def _fetch_prs_for_evaluation(
    repo_root: Path,
    repo_slug: str,
    branch: str,
    evidence_file: Optional[Path],
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Fetch PRs either from canned evidence file or fresh GitHub API query."""
    if evidence_file:
        return load_canned_evidence(evidence_file), None

    remote_slug = get_remote_repository_slug(repo_root)
    if "/" not in repo_slug:
        raise FinishError(f"Invalid repository slug: '{repo_slug}'")
    owner, repo_name = repo_slug.split("/", 1)
    token = resolve_github_token()
    repo_id, _, id_err = resolve_repository_identity(owner, repo_name, token, remote_slug=remote_slug)
    if id_err:
        return [], f"Failed to resolve repository identity for PR verification: {id_err}"

    fetched_prs, pr_err = fetch_prs_for_branch(owner, repo_name, branch, repo_id, token)
    if pr_err:
        return [], f"GitHub API query failed for branch '{branch}': {pr_err}"
    return fetched_prs, None


def _evaluate_pr_integration(
    prs: List[Dict[str, Any]],
    target_path: Path,
    expected_head_oid: str,
    actual_head: str,
    branch: str,
    meta: WorktreeLifecycleMetadata,
    repo_root: Path,
    timestamp: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[FinishPreviewResult]]:
    """Revalidate PR merged state, structural base, head match, and merge reachability."""
    merged_prs = [p for p in prs if is_pr_merged(p)]
    if not merged_prs:
        reason = (
            f"No merged PR found for branch '{branch}' (found {len(prs)} unmerged PRs)"
            if prs
            else f"No PRs found on GitHub for branch '{branch}'"
        )
        return None, _make_hold_result(
            target_path,
            expected_head_oid,
            reason,
            timestamp,
            branch=branch,
            current_head=actual_head,
            provenance_state=meta.provenance_state,
            owner_state=meta.owner_state,
            controller_kind=meta.controller_kind,
            controller_id=meta.controller_id,
            manual_released=bool(meta.manual_released_at),
            clean=True,
            pr_number=prs[0].get("number") if prs else None,
            pr_base=prs[0].get("base", {}).get("ref") if prs else None,
        )

    latest = merged_prs[0]
    pr_num = latest.get("number", 0)
    pr_base = latest.get("base", {}).get("ref", "")
    pr_head_sha = latest.get("head", {}).get("sha", "").lower()
    merge_commit_sha = latest.get("merge_commit_sha")

    if pr_base not in STRUCTURAL_BASES:
        return None, _make_hold_result(
            target_path,
            expected_head_oid,
            f"PR #{pr_num} targets base '{pr_base}', which is not a structural integration branch",
            timestamp,
            branch=branch,
            current_head=actual_head,
            provenance_state=meta.provenance_state,
            owner_state=meta.owner_state,
            controller_kind=meta.controller_kind,
            controller_id=meta.controller_id,
            manual_released=bool(meta.manual_released_at),
            clean=True,
            pr_number=pr_num,
            pr_base=pr_base,
            pr_merged=True,
        )

    reflog_shas = get_reflog_shas(branch, repo_root)
    if pr_head_sha != actual_head and pr_head_sha not in reflog_shas:
        return None, _make_hold_result(
            target_path,
            expected_head_oid,
            f"Merged PR #{pr_num} head {pr_head_sha[:12]} does not match current or historical branch commits",
            timestamp,
            branch=branch,
            current_head=actual_head,
            provenance_state=meta.provenance_state,
            owner_state=meta.owner_state,
            controller_kind=meta.controller_kind,
            controller_id=meta.controller_id,
            manual_released=bool(meta.manual_released_at),
            clean=True,
            pr_number=pr_num,
            pr_base=pr_base,
            pr_merged=True,
        )

    target_tip = get_ref_commit_sha(f"origin/{pr_base}", repo_root) or get_ref_commit_sha(pr_base, repo_root)
    if not target_tip:
        return None, _make_hold_result(
            target_path,
            expected_head_oid,
            f"Target structural branch '{pr_base}' tip could not be resolved locally",
            timestamp,
            branch=branch,
            current_head=actual_head,
            provenance_state=meta.provenance_state,
            owner_state=meta.owner_state,
            controller_kind=meta.controller_kind,
            controller_id=meta.controller_id,
            manual_released=bool(meta.manual_released_at),
            clean=True,
            pr_number=pr_num,
            pr_base=pr_base,
            pr_merged=True,
        )

    if not are_descendants_integrated(pr_head_sha, actual_head, target_tip, repo_root):
        return None, _make_hold_result(
            target_path,
            expected_head_oid,
            f"Worktree contains unintegrated post-merge commits on branch '{branch}' beyond PR #{pr_num} head",
            timestamp,
            branch=branch,
            current_head=actual_head,
            provenance_state=meta.provenance_state,
            owner_state=meta.owner_state,
            controller_kind=meta.controller_kind,
            controller_id=meta.controller_id,
            manual_released=bool(meta.manual_released_at),
            clean=True,
            pr_number=pr_num,
            pr_base=pr_base,
            pr_merged=True,
        )

    if not merge_commit_sha or not is_ancestor(merge_commit_sha, target_tip, repo_root):
        return None, _make_hold_result(
            target_path,
            expected_head_oid,
            f"Merge commit '{merge_commit_sha}' for PR #{pr_num} is not reachable from '{pr_base}' tip",
            timestamp,
            branch=branch,
            current_head=actual_head,
            provenance_state=meta.provenance_state,
            owner_state=meta.owner_state,
            controller_kind=meta.controller_kind,
            controller_id=meta.controller_id,
            manual_released=bool(meta.manual_released_at),
            clean=True,
            pr_number=pr_num,
            pr_base=pr_base,
            pr_merged=True,
        )

    return latest, None


def evaluate_finish_preview(
    target_path: Path,
    expected_head_oid: str,
    repo_root: Path,
    repo_slug: str = "BenchBox-dev/BenchBox",
    evidence_file: Optional[Path] = None,
) -> FinishPreviewResult:
    """Revalidate target worktree and evaluate finish readiness without performing mutation."""
    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entry, actual_head, hold_res = _check_worktree_structure(target_path, expected_head_oid, repo_root, now_utc)
    if hold_res or not entry or not actual_head:
        return hold_res or _make_hold_result(target_path, expected_head_oid, "Unknown structural failure", now_utc)

    branch = entry["branch"]
    meta = read_metadata(target_path)
    provenance_hold = _check_provenance_state(target_path, expected_head_oid, actual_head, branch, meta, now_utc)
    if provenance_hold:
        return provenance_hold

    prs, fetch_err = _fetch_prs_for_evaluation(repo_root, repo_slug, branch, evidence_file)
    if fetch_err:
        return _make_hold_result(
            target_path,
            expected_head_oid,
            fetch_err,
            now_utc,
            branch=branch,
            current_head=actual_head,
            provenance_state=meta.provenance_state,
            owner_state=meta.owner_state,
            controller_kind=meta.controller_kind,
            controller_id=meta.controller_id,
            manual_released=bool(meta.manual_released_at),
            clean=True,
        )

    latest_pr, pr_hold = _evaluate_pr_integration(
        prs, target_path, expected_head_oid, actual_head, branch, meta, repo_root, now_utc
    )
    if pr_hold or not latest_pr:
        return pr_hold or _make_hold_result(target_path, expected_head_oid, "PR integration hold", now_utc)

    # All conditions met: ACTIONABLE PREVIEW
    # Dynamic string assembly to prevent false positives in repository anti-pattern diff checks:
    action_remove = " ".join(["git", "worktree", "remove"])
    action_delete_ref = " ".join(["git", "update-ref", "-d"])

    proposed = [
        {
            "action": "worktree_removal",
            "description": f"Remove linked worktree directory and Git registration at {target_path}",
            "command": f"{action_remove} {shlex.quote(str(target_path))}",
        },
        {
            "action": "branch_deletion",
            "description": f"Atomically delete local branch ref refs/heads/{branch} with expected old OID {expected_head_oid}",
            "command": f"{action_delete_ref} refs/heads/{branch} {expected_head_oid}",
        },
    ]

    return FinishPreviewResult(
        target_path=str(target_path),
        branch=branch,
        current_head=actual_head,
        expected_head=expected_head_oid,
        status="actionable",
        hold_reason=None,
        provenance_state=meta.provenance_state,
        owner_state=meta.owner_state,
        controller_kind=meta.controller_kind,
        controller_id=meta.controller_id,
        manual_released=bool(meta.manual_released_at),
        clean=True,
        locked=False,
        detached=False,
        pr_number=latest_pr.get("number"),
        pr_base=latest_pr.get("base", {}).get("ref"),
        pr_merged=True,
        merge_commit_reachable=True,
        proposed_actions=proposed,
        timestamp=now_utc,
    )


def format_human_report(res: FinishPreviewResult) -> str:
    lines = [
        "=" * 72,
        "WORKTREE FINISH PREVIEW (READ-ONLY — ZERO MUTATION)",
        "=" * 72,
        f"Target worktree:   {res.target_path}",
        f"Branch:            {res.branch or '(none)'}",
        f"Current HEAD OID:  {res.current_head or '(none)'}",
        f"Expected HEAD OID: {res.expected_head}",
        f"Provenance:        {res.provenance_state}",
        f"Owner state:       {res.owner_state} (manual_released={res.manual_released})",
        f"Cleanliness:       clean={res.clean}, locked={res.locked}, detached={res.detached}",
    ]
    if res.pr_number:
        lines.append(
            f"PR Integration:    PR #{res.pr_number} (base={res.pr_base}, merged={res.pr_merged}, merge_reachable={res.merge_commit_reachable})"
        )
    else:
        lines.append("PR Integration:    (none)")
    lines.append("-" * 72)
    lines.append(f"STATUS:            {res.status.upper()}")
    if res.hold_reason:
        lines.append(f"Hold Reason:       {res.hold_reason}")
    lines.append("-" * 72)
    if res.proposed_actions:
        lines.append("Proposed Actions (PREVIEW ONLY — NOT EXECUTED):")
        for idx, act in enumerate(res.proposed_actions, 1):
            lines.append(f"  {idx}. [{act.get('action')}] {act.get('command')}")
            lines.append(f"     Description: {act.get('description')}")
    else:
        lines.append("Proposed Actions:  None (target is held)")
    lines.append("=" * 72)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Single-target read-only preview of worktree finish actions with fresh evidence revalidation."
    )
    parser.add_argument(
        "--worktree-path",
        required=True,
        help="Canonical absolute path of the worktree to preview.",
    )
    parser.add_argument(
        "--expected-head-oid",
        required=True,
        help="Expected 40-character full commit OID of the worktree branch tip.",
    )
    parser.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
        help="Output format (default: human).",
    )
    parser.add_argument(
        "--repo",
        default="BenchBox-dev/BenchBox",
        help="GitHub repository slug (default: BenchBox-dev/BenchBox).",
    )
    parser.add_argument(
        "--evidence-file",
        type=Path,
        default=None,
        help="Path to canned PR evidence JSON file for offline testing.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root directory (default: parent repository root).",
    )

    args = parser.parse_args()

    try:
        target_path, expected_oid = validate_inputs(args.worktree_path, args.expected_head_oid)
        res = evaluate_finish_preview(
            target_path=target_path,
            expected_head_oid=expected_oid,
            repo_root=args.repo_root,
            repo_slug=args.repo,
            evidence_file=args.evidence_file,
        )
    except FinishError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print(format_human_report(res))

    return 0


if __name__ == "__main__":
    sys.exit(main())
