#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAX_LISTED = 60
MAX_DIFFED_TARGETS = 25
MAX_DIFF_LINES = 40


def _load_checker() -> ModuleType:
    path = ROOT / "make" / "check_makefile_inventory.py"
    spec = importlib.util.spec_from_file_location("check_makefile_inventory", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def changed_make_paths(base: str) -> list[str]:
    return [line for line in _git("diff", "--name-only", base, "HEAD", "--", "Makefile", "make").splitlines() if line]


def inventory_at(checker: ModuleType, ref: str, destination: Path) -> dict[str, Any]:
    for path in _git("ls-tree", "-r", "--name-only", ref, "--", "Makefile", "make").splitlines():
        if path == "Makefile" or path.endswith(".mk"):
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_git("show", f"{ref}:{path}"), encoding="utf-8")
    return checker.build_inventory(destination)


def _rule_text(inventory: dict[str, Any], target: str) -> list[str]:
    lines: list[str] = []
    for record in inventory["rules"][target]:
        lines.append(record["header"])
        lines.extend(record["recipe"].splitlines())
    return lines


def _listing(title: str, names: list[str]) -> list[str]:
    if not names:
        return []
    shown = [f"- `{name}`" for name in names[:MAX_LISTED]]
    if len(names) > MAX_LISTED:
        shown.append(f"- ... and {len(names) - MAX_LISTED} more")
    return [f"**{title} ({len(names)})**", "", *shown, ""]


def render(base: dict[str, Any], head: dict[str, Any], paths: list[str]) -> str:
    base_public = set(base["public_targets"])
    head_public = set(head["public_targets"])
    removed = sorted(base_public - head_public)
    added = sorted(head_public - base_public)
    changed = sorted(
        target for target in base_public & head_public if _rule_text(base, target) != _rule_text(head, target)
    )
    lines = [
        "### Make interface changes",
        "",
        f"Files: {', '.join(f'`{path}`' for path in paths)}",
        "",
        f"Public targets: {len(base_public)} at base, {len(head_public)} at head. Informational only.",
        "",
    ]
    lines += _listing("Removed public targets", removed)
    lines += _listing("Added public targets", added)
    lines += _listing("Public targets with a changed header or recipe", changed)
    if base["default_goal"] != head["default_goal"]:
        lines += [f"Default goal: `{base['default_goal']}` at base, `{head['default_goal']}` at head.", ""]
    if base["include_order"] != head["include_order"]:
        lines += ["Include order changed.", ""]
    private = sorted(
        target
        for target in (set(base["rules"]) | set(head["rules"])) - base_public - head_public
        if base["rules"].get(target) != head["rules"].get(target)
    )
    lines += _listing("Other targets added, removed or changed", private)
    for kind, title in (("variables", "Variables"), ("macros", "Macros")):
        names = sorted(
            name for name in set(base[kind]) | set(head[kind]) if base[kind].get(name) != head[kind].get(name)
        )
        lines += _listing(f"{title} added, removed or changed", names)
    if base["semantic_sha256"] == head["semantic_sha256"]:
        lines += ["Make's evaluation is unchanged.", ""]
    elif not (removed or added or changed):
        lines += ["No public target or recipe changed, but Make's evaluation changed.", ""]
    for target in changed[:MAX_DIFFED_TARGETS]:
        diff = list(
            difflib.unified_diff(_rule_text(base, target), _rule_text(head, target), "base", "head", lineterm="", n=1)
        )
        if len(diff) > MAX_DIFF_LINES:
            diff = [*diff[:MAX_DIFF_LINES], "... diff truncated"]
        lines += [
            f"<details><summary><code>{target}</code></summary>",
            "",
            "```diff",
            *diff,
            "```",
            "",
            "</details>",
            "",
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args(argv)
    try:
        paths = changed_make_paths(args.base_ref)
        if not paths:
            return 0
        checker = _load_checker()
        with tempfile.TemporaryDirectory() as scratch:
            base = inventory_at(checker, args.base_ref, Path(scratch))
        head = checker.build_inventory(ROOT)
        text = render(base, head, paths)
    except Exception as exc:
        text = f"### Make interface changes\n\nNot computed: {type(exc).__name__}: {exc}\n"
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
