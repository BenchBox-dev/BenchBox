#!/usr/bin/env python3
"""Check per-module cyclomatic complexity using ruff C901 output.

Parses ruff's C901 (mccabe) violations and reports per-module summaries.
Mirrors the structure of check_module_coverage.py for consistency.

Usage:
    uv run -- python scripts/check_complexity.py
    uv run -- python scripts/check_complexity.py --max-complexity 15
    uv run -- python scripts/check_complexity.py --warn-complexity 12 --max-complexity 20
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

# Matches ruff concise output: "file.py:line:col: C901 `func` is too complex (N > M)"
_C901_RE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):\d+: C901 `(?P<func>[^`]+)` is too complex \((?P<score>\d+) > \d+\)"
)


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    func: str
    score: int


@dataclass
class ModuleSummary:
    module: str
    violations: list[Violation] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.violations)

    @property
    def worst(self) -> int:
        return max((v.score for v in self.violations), default=0)

    @property
    def mean(self) -> float:
        if not self.violations:
            return 0.0
        return sum(v.score for v in self.violations) / len(self.violations)


def _module_key(filepath: str, source_root: str) -> str:
    """Extract module key from filepath (e.g. 'benchbox/core' from 'benchbox/core/runner/runner.py')."""
    parts = filepath.replace("\\", "/").split("/")
    root_idx = None
    for i, p in enumerate(parts):
        if p == source_root:
            root_idx = i
            break
    if root_idx is None:
        return source_root
    if len(parts) <= root_idx + 2:
        return source_root
    return f"{parts[root_idx]}/{parts[root_idx + 1]}"


def _run_ruff(source_root: str) -> list[Violation]:
    """Run ruff with C901 at threshold=1 to capture all complexity scores."""
    cmd = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--select",
        "C901",
        "--config",
        "lint.mccabe.max-complexity=1",
        "--output-format",
        "concise",
        source_root,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # ruff returns non-zero when violations are found; that's expected.
    violations = []
    for line in result.stdout.splitlines():
        m = _C901_RE.match(line)
        if m:
            violations.append(
                Violation(
                    file=m.group("file"),
                    line=int(m.group("line")),
                    func=m.group("func"),
                    score=int(m.group("score")),
                )
            )
    return violations


def _load_config(pyproject_path: Path) -> dict:
    """Load [tool.benchbox.complexity] from pyproject.toml."""
    if not pyproject_path.exists():
        return {}
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    return data.get("tool", {}).get("benchbox", {}).get("complexity", {})


def _parse_exclusion_key(key: str) -> tuple[str, str]:
    """Parse 'file:function' exclusion into (file, function)."""
    parts = key.rsplit(":", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", key


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source-root",
        default="benchbox",
        help="Source root directory to scan (default: benchbox)",
    )
    parser.add_argument(
        "--max-complexity",
        type=int,
        default=None,
        help="Hard ceiling - functions above this fail the check (default: from pyproject.toml or 20)",
    )
    parser.add_argument(
        "--warn-complexity",
        type=int,
        default=None,
        help="Advisory threshold - functions above this are printed as warnings (default: from pyproject.toml or 15)",
    )
    parser.add_argument(
        "--pyproject",
        default="pyproject.toml",
        help="Path to pyproject.toml for loading config (default: pyproject.toml)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Show top N most complex functions (default: 20)",
    )
    parser.add_argument(
        "--per-module",
        action="store_true",
        default=True,
        help="Show per-module summary (default: True)",
    )
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Report only - do not fail with non-zero exit code",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    config = _load_config(Path(args.pyproject))
    max_complexity = args.max_complexity or config.get("max_complexity", 20)
    warn_complexity = args.warn_complexity or config.get("warn_complexity", 15)
    exclude_modules = set(config.get("exclude_modules", []))
    exclude_functions = set()
    for key in config.get("exclude_functions", []):
        exclude_functions.add(_parse_exclusion_key(key))

    violations = _run_ruff(args.source_root)
    if not violations:
        print("No functions found - is the source root correct?")
        return 1

    # Filter excluded functions
    filtered = []
    for v in violations:
        norm_file = v.file.replace("\\", "/")
        if (norm_file, v.func) in exclude_functions:
            continue
        module = _module_key(v.file, args.source_root)
        if module in exclude_modules:
            continue
        filtered.append(v)

    # --- Per-module summary ---
    modules: dict[str, ModuleSummary] = {}
    for v in filtered:
        module = _module_key(v.file, args.source_root)
        if module not in modules:
            modules[module] = ModuleSummary(module=module)
        modules[module].violations.append(v)

    # Only show functions above warn threshold
    warnings = [v for v in filtered if warn_complexity <= v.score <= max_complexity]
    failures = [v for v in filtered if v.score > max_complexity]

    # --- Report ---
    print(f"Cyclomatic Complexity Report (warn={warn_complexity}, max={max_complexity})")
    print(f"{'=' * 72}")

    # Top N most complex functions
    top_n = sorted(filtered, key=lambda v: v.score, reverse=True)[: args.top]
    if top_n:
        print(f"\nTop {min(args.top, len(top_n))} most complex functions:")
        func_width = max(len(v.func) for v in top_n)
        file_width = max(len(f"{v.file}:{v.line}") for v in top_n)
        for v in top_n:
            loc = f"{v.file}:{v.line}"
            status = "FAIL" if v.score > max_complexity else ("WARN" if v.score >= warn_complexity else "    ")
            print(f"  {v.score:>4}  {v.func:<{func_width}}  {loc:<{file_width}}  {status}")

    # Per-module summary
    if args.per_module and modules:
        print("\nPer-module summary:")
        mod_width = max(len(m.module) for m in modules.values())
        print(f"  {'Module':<{mod_width}}  {'Count':>5}  {'Worst':>5}  {'Mean':>6}")
        print(f"  {'-' * mod_width}  {'-' * 5}  {'-' * 5}  {'-' * 6}")
        for m in sorted(modules.values(), key=lambda m: m.worst, reverse=True):
            print(f"  {m.module:<{mod_width}}  {m.count:>5}  {m.worst:>5}  {m.mean:>6.1f}")

    # Summary counts
    total = len(filtered)
    print(f"\nTotal functions scanned: {total}")
    print(f"  Warnings (>{warn_complexity}): {len(warnings)}")
    print(f"  Failures (>{max_complexity}): {len(failures)}")

    if failures:
        print(f"\nFAILED: {len(failures)} function(s) exceed max complexity of {max_complexity}")
        for v in sorted(failures, key=lambda v: v.score, reverse=True):
            print(f"  {v.score:>4}  {v.func}  ({v.file}:{v.line})")
        if args.no_fail:
            print("(--no-fail specified, exiting 0)")
            return 0
        return 1

    print(f"\nPASSED: all functions within complexity limit of {max_complexity}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv or sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
