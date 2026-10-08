#!/usr/bin/env python3
# Copyright 2026 Joe Harris / BenchBox Project
# Licensed under the MIT License.

from __future__ import annotations

import re
import sys
from pathlib import Path

SHADOWED_MODULES: frozenset[str] = frozenset(
    [
        "aggregate",
        "benchmarks",
        "calculate_qphh",
        "compare",
        "compare_dataframes",
        "compare_plans",
        "convert",
        "datagen",
        "download_answers",
        "export",
        "plan_history",
        "profile",
        "report",
        "results",
        "run",
        "run_official",
        "shell",
        "show_plan",
        "tuning_group",
        "visualize",
    ]
)

_MODULE_PATTERN = "|".join(re.escape(m) for m in sorted(SHADOWED_MODULES))
UNSAFE_RE = re.compile(
    r"""(?:unittest\.)?(?:mock\.)?patch\(["']benchbox\.cli\.commands\.(?:""" + _MODULE_PATTERN + r""")\.[^"']+["']"""
)


def check_file(path: Path) -> list[tuple[int, str]]:
    violations: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return violations
    for lineno, line in enumerate(text.splitlines(), 1):
        if UNSAFE_RE.search(line):
            violations.append((lineno, line.strip()))
    return violations


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    test_dir = repo_root / "tests"

    if not test_dir.is_dir():
        print(f"ERROR: test directory not found: {test_dir}", file=sys.stderr)
        return 2

    all_violations: dict[Path, list[tuple[int, str]]] = {}
    for test_file in sorted(test_dir.rglob("*.py")):
        violations = check_file(test_file)
        if violations:
            all_violations[test_file] = violations

    if not all_violations:
        print("check_patch_safety: OK - no unsafe patch() calls found.")
        return 0

    print("ERROR: Unsafe patch() string paths detected.\n")
    print("These calls resolve the target via getattr() on the commands package,")
    print("which returns the re-exported Click Command instead of the submodule.")
    print("They fail on Python 3.10 and pass on 3.12+ only by accident (import order).\n")
    print("Fix: use patch.object(_module, 'attr') with a direct sys.modules reference.")
    print("Example:\n")
    print("  import sys as _sys")
    print("  __import__('benchbox.cli.commands.run')")
    print("  _run_module = _sys.modules['benchbox.cli.commands.run']\n")
    print("  # Replace:")
    print("  patch('benchbox.cli.commands.run.SystemProfiler')")
    print("  # With:")
    print("  patch.object(_run_module, 'SystemProfiler')\n")
    print("See tests/unit/cli/test_run_command_interactive_paths.py for a full example.\n")

    total = 0
    for path, violations in sorted(all_violations.items()):
        rel = path.relative_to(repo_root)
        for lineno, line in violations:
            print(f"  {rel}:{lineno}: {line}")
            total += 1

    print(f"\nTotal: {total} violation(s) in {len(all_violations)} file(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
