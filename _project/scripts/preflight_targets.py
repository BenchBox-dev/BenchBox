#!/usr/bin/env python3
"""List the changed Python files and the test files that cover them.

`make pr-preflight` lints the changed Python files and runs only their tests.
Changed paths are the branch diff against the merge base with the base ref,
plus staged, unstaged, and untracked files.

Test mapping:

* a changed ``tests/**/test_*.py`` maps to itself;
* a changed ``benchbox/**/<mod>.py`` or ``scripts/<mod>.py`` maps to every
  ``tests/**/test_<mod>.py``.

Usage:
  python _project/scripts/preflight_targets.py python [--base-ref origin/develop]
  python _project/scripts/preflight_targets.py tests [--base-ref origin/develop]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path, PurePosixPath

SOURCE_ROOTS = ("benchbox/", "scripts/")
TESTS_ROOT = "tests"


def _git_lines(repo: Path, *args: str) -> list[str]:
    proc = subprocess.run(["git", *args], cwd=repo, check=True, text=True, capture_output=True, timeout=120)
    return [line for line in proc.stdout.splitlines() if line]


def changed_paths(repo: Path, base_ref: str) -> list[str]:
    """Return existing changed paths, sorted, relative to *repo*."""
    base = _git_lines(repo, "merge-base", base_ref, "HEAD")[0]
    names = set(_git_lines(repo, "diff", "--name-only", "--diff-filter=d", f"{base}...HEAD"))
    names.update(_git_lines(repo, "diff", "--name-only", "--diff-filter=d", "HEAD"))
    names.update(_git_lines(repo, "ls-files", "--others", "--exclude-standard"))
    return sorted(name for name in names if (repo / name).is_file())


def changed_python(paths: list[str]) -> list[str]:
    return [path for path in paths if path.endswith(".py")]


def _is_test_file(path: str) -> bool:
    pure = PurePosixPath(path)
    return pure.parts[:1] == (TESTS_ROOT,) and pure.name.startswith("test_") and pure.suffix == ".py"


def _test_index(repo: Path) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for path in sorted((repo / TESTS_ROOT).rglob("test_*.py")):
        index.setdefault(path.name, []).append(path.relative_to(repo).as_posix())
    return index


def map_tests(repo: Path, paths: list[str]) -> list[str]:
    index = _test_index(repo)
    selected: set[str] = set()
    for path in changed_python(paths):
        if _is_test_file(path):
            selected.add(path)
        elif path.startswith(SOURCE_ROOTS):
            module = PurePosixPath(path).stem
            if module != "__init__":
                selected.update(index.get(f"test_{module}.py", ()))
    return sorted(selected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", choices=("python", "tests"))
    parser.add_argument("--base-ref", default="origin/develop")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        paths = changed_paths(args.repo_root, args.base_ref)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, IndexError) as exc:
        print(f"preflight_targets: cannot compute changed paths against {args.base_ref}: {exc}", file=sys.stderr)
        return 2
    selected = changed_python(paths) if args.kind == "python" else map_tests(args.repo_root, paths)
    for path in selected:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
