#!/usr/bin/env python3
"""Audit open corpus-mirror PRs for set-equivalence against the protected base.

For each open mirror PR targeting the protected publication branch, compute
whether the PR adds any corpus path that is new to the base branch's union:

    ADDITIVE  - the PR adds at least one corpus path not already on base
    NOOP      - every added corpus path already exists on base (pure subset)
    EMPTY     - the PR adds no corpus paths at all
    ERROR     - the PR could not be audited (operational failure)

This is a reporting tool, not a gate: by default it exits 0 even when it finds
NOOP/EMPTY (retire-able) PRs. Pass ``--strict-union`` to exit 3 when any
NOOP/EMPTY PR is present.

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

CORPUS_PREFIXES = (
    "results-data/",
    "results-data/corpus-inventory.json",
    "results-data/CORPUS_NOTES.md",
)


@dataclass
class MirrorPRAudit:
    number: int
    title: str
    head_ref: str
    added_path_count: int
    new_to_union: bool
    duplicate_count: int
    verdict: str
    added_paths: list[str] = field(default_factory=list)
    new_paths: list[str] = field(default_factory=list)


def _run(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run a subprocess against REPO_ROOT with text output, raising on failure."""
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=merged_env,
        check=True,
    )


def _is_corpus_path(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/")
    if not normalized:
        return False
    for prefix in CORPUS_PREFIXES:
        if normalized == prefix.rstrip("/") or normalized.startswith(prefix):
            return True
    return False


def _list_open_prs(repo: str, base: str) -> list[dict[str, Any]]:
    result = _run(
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
            "--json",
            "number,title,headRefName,files",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh pr list failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _list_base_corpus_paths(repo: str, base: str) -> set[str]:
    """Return the set of corpus paths present on the base branch tree."""
    if not base:
        raise RuntimeError("empty base ref provided; cannot compute the protected union")
    result = _run(
        ["gh", "api", f"repos/{repo}/git/trees/{base}?recursive=1"],
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh api git/trees failed for base '{base}': {result.stderr.strip()}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise RuntimeError(f"gh api returned non-JSON for base '{base}': {exc}") from exc
    tree = payload.get("tree", [])
    if not isinstance(tree, list):
        raise RuntimeError(f"gh api tree for base '{base}' is not a list")
    return {entry["path"] for entry in tree if _is_corpus_path(entry.get("path", ""))}


def _audit_pr(pr: dict[str, Any], base_paths: set[str]) -> MirrorPRAudit:
    number = int(pr.get("number", 0))
    head_ref = pr.get("headRefName", "")

    files = pr.get("files") or []
    added_paths = sorted({f.get("path") for f in files if isinstance(f, dict) and _is_corpus_path(f.get("path", ""))})
    if not added_paths:
        return MirrorPRAudit(
            number=number,
            title=pr.get("title", ""),
            head_ref=head_ref,
            added_path_count=0,
            new_to_union=False,
            duplicate_count=0,
            verdict="EMPTY",
        )

    new_paths = sorted(path for path in added_paths if path not in base_paths)
    duplicate_count = sum(1 for path in added_paths if path in base_paths)
    if new_paths:
        verdict = "ADDITIVE"
    else:
        verdict = "NOOP"
    return MirrorPRAudit(
        number=number,
        title=pr.get("title", ""),
        head_ref=head_ref,
        added_path_count=len(added_paths),
        new_to_union=bool(new_paths),
        duplicate_count=duplicate_count,
        verdict=verdict,
        added_paths=added_paths,
        new_paths=new_paths,
    )


def audit_mirror_prs(repo: str, base: str) -> list[MirrorPRAudit]:
    """Audit every open mirror PR against the base branch's corpus union."""
    base_paths = _list_base_corpus_paths(repo, base)
    prs = _list_open_prs(repo, base)
    return [_audit_pr(pr, base_paths) for pr in prs]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit corpus mirror PRs for set-equivalence.")
    parser.add_argument("--repo", required=True, help="GitHub repository (owner/repo).")
    parser.add_argument("--base", required=True, help="Protected base branch (e.g. published-results).")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON output.")
    parser.add_argument(
        "--strict-union",
        action="store_true",
        help="Exit 3 if any NOOP/EMPTY (retire-able) PR is found.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        audits = audit_mirror_prs(args.repo, args.base)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    retire_able = [a for a in audits if a.verdict in ("NOOP", "EMPTY")]

    if args.json:
        payload = {
            "mode": "set-equivalence",
            "base": args.base,
            "count": len(audits),
            "prs": [asdict(a) for a in audits],
        }
        print(json.dumps(payload, indent=2))
    else:
        if not audits:
            print(f"[audit ok] 0 mirror PRs open against '{args.base}'")
        else:
            for audit in audits:
                print(
                    f"PR #{audit.number} ({audit.head_ref}): "
                    f"added_path_count={audit.added_path_count} "
                    f"new_to_union={audit.new_to_union!s} "
                    f"duplicate_count={audit.duplicate_count} "
                    f"verdict={audit.verdict}"
                )

    if args.strict_union and retire_able:
        print(
            f"strict-union: {len(retire_able)} retire-able PR(s) found ({[a.number for a in retire_able]}).",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
