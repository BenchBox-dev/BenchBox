"""Report slow test modules reached by the PR and nightly workflows.

This is diagnostic while the broad slow lane is being observed. A workflow
reference to a file is counted only when it appears in a run command, not in
comments or documentation.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TEST_PATH = re.compile(r"tests/[A-Za-z0-9_./-]+/test_[A-Za-z0-9_-]+\.py|tests/test_[A-Za-z0-9_-]+\.py")


def _run_commands(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "run" and isinstance(child, str):
                yield child
            else:
                yield from _run_commands(child)
    elif isinstance(value, list):
        for child in value:
            yield from _run_commands(child)


def _marker_names(node: ast.AST) -> set[str]:
    return {
        child.attr
        for child in ast.walk(node)
        if isinstance(child, ast.Attribute)
        and isinstance(child.value, ast.Attribute)
        and child.value.attr == "mark"
        and isinstance(child.value.value, ast.Name)
        and child.value.value.id == "pytest"
    }


def _declared_markers(nodes: list[ast.stmt]) -> set[str]:
    for node in nodes:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets
        ):
            return _marker_names(node.value)
    return set()


def _has_uncredentialed_slow_test(tree: ast.Module) -> bool:
    module_markers = _declared_markers(tree.body)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            marker_sets = [module_markers | set().union(*(_marker_names(item) for item in node.decorator_list))]
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            class_markers = module_markers | _declared_markers(node.body)
            class_markers |= set().union(*(_marker_names(item) for item in node.decorator_list))
            marker_sets = [
                class_markers | set().union(*(_marker_names(item) for item in child.decorator_list))
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_")
            ]
        else:
            continue
        if any(
            "slow" in markers and not {"stress", "resource_heavy", "live_integration"} & markers
            for markers in marker_sets
        ):
            return True
    return False


def _slow_modules() -> set[str]:
    modules: set[str] = set()
    for path in (ROOT / "tests").rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if _has_uncredentialed_slow_test(tree):
            modules.add(path.relative_to(ROOT).as_posix())
    return modules


def _named_modules(workflow: str) -> set[str]:
    path = ROOT / ".github" / "workflows" / workflow
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {match for command in _run_commands(document) for match in TEST_PATH.findall(command)}


def main() -> None:
    slow = _slow_modules()
    pr = slow & _named_modules("pr.yml")
    nightly = slow & _named_modules("nightly.yml")
    print(f"Slow test modules: {len(slow)}")
    print(f"Named in PR workflow: {len(pr)}")
    print(f"Named in nightly workflow: {len(nightly)}")
    print(f"Not named in PR workflow: {len(slow - pr)}")
    for path in sorted(slow - pr):
        print(f"  {path}")


if __name__ == "__main__":
    main()
