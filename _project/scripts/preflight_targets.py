#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path, PurePosixPath

SOURCE_ROOTS = ("benchbox/", "scripts/", "_project/scripts/")
TESTS_ROOT = "tests"


def _git_lines(repo: Path, *args: str) -> list[str]:
    proc = subprocess.run(["git", *args], cwd=repo, check=True, text=True, capture_output=True, timeout=120)
    return [line for line in proc.stdout.splitlines() if line]


def changed_paths(repo: Path, base_ref: str) -> list[str]:
    base = _git_lines(repo, "merge-base", base_ref, "HEAD")[0]
    names = set(_git_lines(repo, "diff", "--name-only", "--no-renames", f"{base}...HEAD"))
    names.update(_git_lines(repo, "diff", "--name-only", "--no-renames", "HEAD"))
    names.update(_git_lines(repo, "ls-files", "--others", "--exclude-standard"))
    return sorted(names)


def changed_python(repo: Path, paths: list[str]) -> list[str]:
    return [path for path in paths if path.endswith(".py") and (repo / path).is_file()]


def _is_test_file(path: str) -> bool:
    pure = PurePosixPath(path)
    return pure.parts[:1] == (TESTS_ROOT,) and pure.name.startswith("test_") and pure.suffix == ".py"


def _test_index(repo: Path) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for path in sorted((repo / TESTS_ROOT).rglob("test_*.py")):
        index.setdefault(path.name, []).append(path.relative_to(repo).as_posix())
    return index


#: Explicit changed-file → test mapping for files the name-based rules miss.
#: Minimal-integration-subset decision: changes to the shared platform stub
#: installers (tests/integration/platforms/common.py) select the DuckLake
#: integration suite. It passes-or-skips cleanly in the CI default environment
#: (no credentials or services required) while still exercising a real
#: integration path. Fast-tier membership is unchanged: the stub smoke tests
#: covering common.py directly stay fast and keep mapping to themselves.
EXTRA_TEST_MAP: dict[str, list[str]] = {
    "tests/integration/platforms/common.py": ["tests/integration/test_ducklake_integration.py"],
}


def map_tests(repo: Path, paths: list[str]) -> list[str]:
    index = _test_index(repo)
    selected: set[str] = set()
    for path in paths:
        if not path.endswith(".py"):
            continue
        if _is_test_file(path):
            if (repo / path).is_file():
                selected.add(path)
        elif path.startswith(SOURCE_ROOTS):
            module = PurePosixPath(path).stem
            if module != "__init__":
                selected.update(index.get(f"test_{module}.py", ()))
        selected.update(EXTRA_TEST_MAP.get(path, ()))
    return sorted(selected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("python", "tests"))
    parser.add_argument("--base-ref", default="origin/develop")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        paths = changed_paths(args.repo_root, args.base_ref)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, IndexError) as exc:
        print(f"preflight_targets: cannot compute changed paths against {args.base_ref}: {exc}", file=sys.stderr)
        return 2
    selected = changed_python(args.repo_root, paths) if args.kind == "python" else map_tests(args.repo_root, paths)
    for path in selected:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
