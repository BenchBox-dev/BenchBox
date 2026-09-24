#!/usr/bin/env python3
"""Decide whether a pr.yml run needs the heavy test tier.

The heavy tier (medium-test, correctness-gate, plan-capture-gate,
tpch-binary-framing, and the postgres/datafusion/clickhouse integration
samples) runs only when needed:

    heavy-needed = needs-code-ci
                   AND (event is merge_group
                        OR soundness paths touched
                        OR packaging-needed)

Soundness uses the UNION of the base-ref copy and the PR (working tree)
copy of ``_project/scripts/auto_merge_soundness_paths.py``: a PR that
rewrites the predicate itself must not silently narrow what counts as a
soundness path. Both copies are stdlib-only.

Fail-closed: any lookup error, missing input, ambiguous match, or
classification failure reports ``heavy-needed=true`` so the tier runs.
The process still exits 0 (the safe direction is encoded in the output,
not the exit code) unless invoked with ``--check``, where true maps to
exit 0, false maps to exit 1, and a lookup error maps to exit 0.

The event gate lives HERE, not in a workflow ``if:``: downstream jobs
read this lookup's outputs on every event, and references to a skipped
job's outputs do not evaluate reliably. Non-code-routed trees report
``heavy-needed=false`` without any further lookup.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable

PREDICATE_REPO_PATH = "_project/scripts/auto_merge_soundness_paths.py"
MERGE_GROUP_EVENT = "merge_group"


class HeavyTierError(RuntimeError):
    """The lookup could not complete; the caller must fail closed."""


def _load_predicate_copy(name: str, source: str) -> Any:
    """Load one predicate copy from source text under a unique module name."""
    spec = importlib.util.spec_from_loader(name, loader=None)
    if spec is None:
        raise HeavyTierError(f"could not build a module spec for predicate copy {name!r}")
    module = importlib.util.module_from_spec(spec)
    try:
        exec(compile(source, f"<{name}>", "exec"), module.__dict__)
    except Exception as exc:
        raise HeavyTierError(f"predicate copy {name!r} failed to execute: {exc}") from exc
    if not callable(getattr(module, "any_soundness_path", None)):
        raise HeavyTierError(f"predicate copy {name!r} exposes no any_soundness_path")
    return module


def _read_base_copy(base_ref: str, repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "show", f"{base_ref}:{PREDICATE_REPO_PATH}"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise HeavyTierError(f"could not read base-ref copy of the predicate: {exc}") from exc


def _read_pr_copy(repo_root: Path) -> str:
    path = repo_root / PREDICATE_REPO_PATH
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HeavyTierError(f"could not read PR copy of the predicate: {exc}") from exc


def soundness_touched(
    changed_paths: Iterable[str],
    base_ref: str,
    repo_root: Path,
    read_base: Callable[[str, Path], str] | None = None,
    read_pr: Callable[[Path], str] | None = None,
) -> tuple[bool, str]:
    """Return ``(touched, reason)`` over the union of both predicate copies."""
    paths = [str(path) for path in changed_paths]
    base_source = (read_base or _read_base_copy)(base_ref, repo_root)
    pr_source = (read_pr or _read_pr_copy)(repo_root)
    base_module = _load_predicate_copy("soundness_base_copy", base_source)
    pr_module = _load_predicate_copy("soundness_pr_copy", pr_source)
    base_hit = bool(base_module.any_soundness_path(paths))
    pr_hit = bool(pr_module.any_soundness_path(paths))
    if base_hit or pr_hit:
        which = "+".join(name for name, hit in (("base", base_hit), ("pr", pr_hit)) if hit)
        return True, f"soundness path touched (predicate copies: {which})"
    return False, "no soundness path touched under either predicate copy"


def heavy_needed(
    decision: dict[str, Any],
    event: str,
    base_ref: str,
    repo_root: Path,
    read_base: Callable[[str, Path], str] | None = None,
    read_pr: Callable[[Path], str] | None = None,
) -> dict[str, Any]:
    """Return ``{heavy_needed, reason}``; lookup failure fails closed to true."""
    try:
        needs_code_ci = bool(decision.get("needs_code_ci"))
        if not needs_code_ci:
            return {"heavy_needed": False, "reason": "not a code-routed tree; the light lane already covers it"}
        if event == MERGE_GROUP_EVENT:
            return {"heavy_needed": True, "reason": "merge_group runs keep the full tier on every code-routed tree"}
        if bool(decision.get("packaging_needed")):
            return {"heavy_needed": True, "reason": "packaging paths touched (packaging carve-out)"}
        changed = decision.get("changed_paths")
        if not isinstance(changed, list):
            raise HeavyTierError("decision has no changed_paths list")
        touched, reason = soundness_touched(changed, base_ref, repo_root, read_base, read_pr)
        if touched:
            return {"heavy_needed": True, "reason": f"{reason} (soundness carve-out)"}
        return {"heavy_needed": False, "reason": f"{reason}; pull_request runs skip the heavy tier"}
    except Exception as exc:
        return {"heavy_needed": True, "reason": f"lookup failed closed: {exc}"}


def _write_github_output(path: Path, needed: bool) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"heavy-needed={'true' if needed else 'false'}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-in", type=Path, default=None)
    parser.add_argument("--event", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    parser.add_argument("--base-ref", default=os.environ.get("GITHUB_BASE_REF", "origin/develop"))
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--github-output", type=Path, default=None)
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="Exit 0 when heavy-needed is true, else exit 1")
    args = parser.parse_args(argv)

    if args.decision_in is None:
        result: dict[str, Any] = {"heavy_needed": True, "reason": "lookup failed closed: no decision input"}
    else:
        try:
            decision = json.loads(args.decision_in.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            decision = None
            result = {"heavy_needed": True, "reason": f"lookup failed closed: unreadable decision: {exc}"}
        if decision is not None:
            if not isinstance(decision, dict):
                result = {"heavy_needed": True, "reason": "lookup failed closed: decision is not an object"}
            else:
                result = heavy_needed(decision, args.event, args.base_ref, args.repo_root)

    needed = bool(result["heavy_needed"])
    reason = str(result["reason"])
    print(f"heavy-needed={'true' if needed else 'false'}")
    print(reason)
    if args.github_output is not None:
        _write_github_output(args.github_output, needed)
    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(f"Heavy tier needed: `{str(needed).lower()}` ({reason}).\n")
    if args.check:
        return 0 if needed else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
