#!/usr/bin/env python3
"""Audit open corpus-mirror PRs for content-equivalence against the protected base.

For each open mirror PR targeting the protected publication branch, this tool
compares the *blob content* (git blob SHA) of every mirrored path the PR
touches against the base branch tree, and classifies the PR:

    ADDITIVE  - adds at least one mirrored path that is new to the base
    MUTATING  - adds no new path, but changes the content of, or removes, an
                existing mirrored path (a genuine refresh — NOT retire-able)
    NOOP      - every mirrored path it touches already exists on base with
                byte-identical content (pure redundant re-mirror)
    EMPTY     - touches no mirrored path at all
    ERROR     - the PR could not be audited (operational failure)

Only NOOP and EMPTY are retire-able. This is a reporting tool, not a gate: by
default it exits 0 even when it finds retire-able PRs. Pass ``--strict-union``
to exit 3 when any NOOP/EMPTY PR is present.

Runs read-only against GitHub; requires a ``gh`` CLI on PATH.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

# Every path that .github/workflows/sync-results-data-to-published.yml mirrors
# from develop onto published-results (drift-detection + build-overlay lists).
# A mirror PR that only touches paths outside this set is EMPTY, not
# retire-able-because-empty in a way that discards corpus content.
MIRRORED_PREFIXES: tuple[str, ...] = (
    "results-data/bundles/",
    "results-data/corpus-inventory.json",
    "results-data/CORPUS_NOTES.md",
    "results-data/SEED_CORPUS_SPEC.md",
    "results-data/README.md",
    "results-data/validate_corpus.py",
    "results-data/generate_corpus_inventory.py",
    "benchbox/validation/bundle.py",
    "benchbox/core/results/query_status.py",
    "scripts/validate_submission.py",
    "scripts/generate_corpus_inventory.py",
)

_RETIRE_ABLE = ("NOOP", "EMPTY")


@dataclass
class MirrorPRAudit:
    number: int
    title: str
    head_ref: str
    mirrored_file_count: int
    new_paths: list[str] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)
    removed_paths: list[str] = field(default_factory=list)
    noop_paths: list[str] = field(default_factory=list)
    verdict: str = "ERROR"
    error: str | None = None

    @property
    def retire_able(self) -> bool:
        return self.verdict in _RETIRE_ABLE


def _run(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run a subprocess against REPO_ROOT with text output (no raise-on-failure)."""
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=merged_env,
        check=False,
    )


def _run_checked(args: list[str], what: str) -> str:
    result = _run(args)
    if result.returncode != 0:
        raise RuntimeError(f"{what} failed (exit {result.returncode}): {result.stderr.strip()}")
    return result.stdout


def _is_mirrored_path(rel_path: str) -> bool:
    normalized = (rel_path or "").replace("\\", "/")
    if not normalized:
        return False
    for prefix in MIRRORED_PREFIXES:
        if prefix.endswith("/"):
            if normalized == prefix.rstrip("/") or normalized.startswith(prefix):
                return True
        elif normalized == prefix:
            return True
    return False


def _list_open_prs(repo: str, base: str) -> list[dict[str, Any]]:
    out = _run_checked(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--base",
            base,
            "--state",
            "open",
            "--limit",
            "200",
            "--json",
            "number,title,headRefName",
        ],
        "gh pr list",
    )
    return json.loads(out)


def _list_pr_files(repo: str, number: int) -> list[dict[str, Any]]:
    """Return every changed file for a PR, following pagination fully.

    ``gh pr list --json files`` silently caps at 100 files; the REST
    ``pulls/{n}/files`` endpoint with ``--paginate`` does not.
    """
    out = _run_checked(
        [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repo}/pulls/{number}/files?per_page=100",
        ],
        f"gh api pulls/{number}/files",
    )
    pages = json.loads(out)
    files: list[dict[str, Any]] = []
    for page in pages:
        if isinstance(page, list):
            files.extend(page)
    return files


def _base_blob_shas(repo: str, base: str) -> dict[str, str]:
    """Map mirrored path -> git blob SHA on the base branch tree."""
    if not base:
        raise RuntimeError("empty base ref provided; cannot compute the protected base")
    out = _run_checked(
        ["gh", "api", f"repos/{repo}/git/trees/{base}?recursive=1"],
        f"gh api git/trees for base '{base}'",
    )
    try:
        payload = json.loads(out)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh api returned non-JSON for base '{base}': {exc}") from exc
    if payload.get("truncated"):
        raise RuntimeError(
            f"base tree for '{base}' is truncated; cannot compute a complete "
            "content baseline (refusing to classify against a partial tree)"
        )
    tree = payload.get("tree", [])
    if not isinstance(tree, list):
        raise RuntimeError(f"gh api tree for base '{base}' is not a list")
    shas: dict[str, str] = {}
    for entry in tree:
        if not isinstance(entry, dict) or entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        if _is_mirrored_path(path):
            shas[path] = str(entry.get("sha", ""))
    return shas


def _audit_pr(pr: dict[str, Any], base_shas: dict[str, str], repo: str) -> MirrorPRAudit:
    number = int(pr.get("number", 0))
    audit = MirrorPRAudit(
        number=number,
        title=pr.get("title", ""),
        head_ref=pr.get("headRefName", ""),
        mirrored_file_count=0,
    )

    try:
        files = _list_pr_files(repo, number)
    except RuntimeError as exc:
        audit.verdict = "ERROR"
        audit.error = str(exc)
        return audit

    mirrored = [f for f in files if isinstance(f, dict) and _is_mirrored_path(f.get("filename", ""))]
    audit.mirrored_file_count = len(mirrored)

    if not mirrored:
        audit.verdict = "EMPTY"
        return audit

    for f in mirrored:
        path = f.get("filename", "")
        status = f.get("status", "")
        head_sha = str(f.get("sha", ""))
        if status == "removed":
            audit.removed_paths.append(path)
        elif path not in base_shas:
            audit.new_paths.append(path)
        elif head_sha and head_sha == base_shas[path]:
            audit.noop_paths.append(path)
        else:
            audit.changed_paths.append(path)

    for bucket in (audit.new_paths, audit.changed_paths, audit.removed_paths, audit.noop_paths):
        bucket.sort()

    if audit.new_paths:
        audit.verdict = "ADDITIVE"
    elif audit.changed_paths or audit.removed_paths:
        audit.verdict = "MUTATING"
    else:
        audit.verdict = "NOOP"
    return audit


def audit_mirror_prs(repo: str, base: str) -> list[MirrorPRAudit]:
    """Audit every open mirror PR against the base branch's mirrored content."""
    base_shas = _base_blob_shas(repo, base)
    prs = _list_open_prs(repo, base)
    return [_audit_pr(pr, base_shas, repo) for pr in prs]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit corpus mirror PRs for content-equivalence.")
    parser.add_argument("--repo", required=True, help="GitHub repository (owner/repo).")
    parser.add_argument("--base", required=True, help="Protected base branch (e.g. published-results).")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output.")
    parser.add_argument(
        "--strict-union",
        action="store_true",
        help="Exit 3 if any NOOP/EMPTY (retire-able) PR is found.",
    )
    return parser.parse_args(argv)


def _audit_to_dict(a: MirrorPRAudit) -> dict[str, Any]:
    d = asdict(a)
    d["retire_able"] = a.retire_able
    return d


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        audits = audit_mirror_prs(args.repo, args.base)
    except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    retire_able = [a for a in audits if a.retire_able]
    errored = [a for a in audits if a.verdict == "ERROR"]

    if args.json:
        payload = {
            "mode": "content-equivalence",
            "base": args.base,
            "count": len(audits),
            "retire_able": [a.number for a in retire_able],
            "errored": [a.number for a in errored],
            "prs": [_audit_to_dict(a) for a in audits],
        }
        print(json.dumps(payload, indent=2))
    elif not audits:
        print(f"[audit ok] 0 mirror PRs open against '{args.base}'")
    else:
        for audit in audits:
            print(
                f"PR #{audit.number} ({audit.head_ref}): "
                f"mirrored_files={audit.mirrored_file_count} "
                f"new={len(audit.new_paths)} changed={len(audit.changed_paths)} "
                f"removed={len(audit.removed_paths)} noop={len(audit.noop_paths)} "
                f"verdict={audit.verdict}" + (f" error={audit.error}" if audit.error else "")
            )

    if errored:
        print(
            f"warning: {len(errored)} PR(s) could not be audited ({[a.number for a in errored]}).",
            file=sys.stderr,
        )
    if args.strict_union and retire_able:
        print(
            f"strict-union: {len(retire_able)} retire-able PR(s) found ({[a.number for a in retire_able]}).",
            file=sys.stderr,
        )
        return 3
    if errored:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
