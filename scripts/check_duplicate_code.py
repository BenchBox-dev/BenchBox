#!/usr/bin/env python3
"""Detect duplicate and near-duplicate functions across the benchbox codebase.

Uses Python's built-in ``ast`` module to structurally hash every function body,
then reports groups of functions whose AST structure is identical (Type-2 clones
in the clone-detection literature: same structure, different identifiers/literals).

Exit codes:
  0 - duplicate ratio is within the configured threshold
  1 - duplicate ratio exceeds the threshold (or other error)

Integration points:
  • ``make duplicate-check``
  • ``uv run -- python scripts/check_duplicate_code.py``
  • CI: add as a step after tests in test.yml

Configuration lives in ``pyproject.toml`` under ``[tool.benchbox.duplicates]``.
"""

from __future__ import annotations

import argparse
import ast
import collections
import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FunctionInfo:
    """A single function occurrence in the codebase."""

    name: str
    file: str
    line: int
    end_line: int

    @property
    def lines(self) -> int:
        return self.end_line - self.line + 1


@dataclass
class DuplicateGroup:
    """A group of structurally-identical functions."""

    structural_hash: str
    functions: list[FunctionInfo] = field(default_factory=list)

    @property
    def copies(self) -> int:
        return len(self.functions)

    @property
    def representative_lines(self) -> int:
        return self.functions[0].lines if self.functions else 0

    @property
    def duplicated_lines(self) -> int:
        """Lines that are duplicates (total minus the 'original')."""
        return self.representative_lines * (self.copies - 1)


@dataclass(frozen=True)
class IgnoreRule:
    """Path-scoped ignore rule for function names."""

    function_names: frozenset[str]
    path_contains: tuple[str, ...]

    def matches(self, *, function_name: str, filepath: str) -> bool:
        if function_name not in self.function_names:
            return False
        if not self.path_contains:
            return True
        return any(marker in filepath for marker in self.path_contains)


# ---------------------------------------------------------------------------
# AST-based structural hashing
# ---------------------------------------------------------------------------


class _FunctionHasher(ast.NodeVisitor):
    """Walk a module AST and collect structural hashes for every function."""

    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self.results: list[tuple[str, FunctionInfo]] = []

    # ------------------------------------------------------------------
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._process(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._process(node)
        self.generic_visit(node)

    # ------------------------------------------------------------------
    def _process(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if node.name in _IGNORE_FUNCTION_NAMES:
            return
        for rule in _IGNORE_RULES:
            if rule.matches(function_name=node.name, filepath=self.filepath):
                return

        end = node.end_lineno or node.lineno
        num_lines = end - node.lineno + 1
        if num_lines < _MIN_FUNCTION_LINES:
            return

        structural = self._structural_signature(node)
        h = hashlib.sha256(structural.encode()).hexdigest()[:20]
        info = FunctionInfo(
            name=node.name,
            file=self.filepath,
            line=node.lineno,
            end_line=end,
        )
        self.results.append((h, info))

    # ------------------------------------------------------------------
    @staticmethod
    def _structural_signature(node: ast.AST) -> str:
        """Build a string that captures control-flow structure while ignoring names.

        This deliberately *strips* identifiers, string literals, and numeric
        constants so that two functions with identical logic but different
        variable/column names hash to the same value (Type-2 clone detection).
        """
        tokens: list[str] = []
        for child in ast.walk(node):
            kind = type(child).__name__

            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                tokens.append(f"{kind}(a={len(child.args.args)})")
            elif isinstance(child, ast.Call):
                tokens.append(f"Call(n={len(child.args)},kw={len(child.keywords)})")
            elif isinstance(child, ast.BinOp):
                tokens.append(f"BinOp({type(child.op).__name__})")
            elif isinstance(child, ast.UnaryOp):
                tokens.append(f"UnaryOp({type(child.op).__name__})")
            elif isinstance(child, ast.BoolOp):
                tokens.append(f"BoolOp({type(child.op).__name__})")
            elif isinstance(child, ast.Compare):
                ops = ",".join(type(o).__name__ for o in child.ops)
                tokens.append(f"Cmp({ops})")
            elif isinstance(
                child,
                (
                    ast.For,
                    ast.While,
                    ast.If,
                    ast.With,
                    ast.Try,
                    ast.ExceptHandler,
                    ast.Return,
                    ast.Yield,
                    ast.YieldFrom,
                    ast.Raise,
                    ast.Assert,
                ),
            ):
                tokens.append(kind)
            elif isinstance(child, ast.Assign):
                tokens.append(f"Assign(t={len(child.targets)})")
            elif isinstance(child, ast.AugAssign):
                tokens.append(f"AugAssign({type(child.op).__name__})")
            elif isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                tokens.append(kind)
            elif isinstance(child, ast.Attribute):
                tokens.append("Attr")
            elif isinstance(child, ast.Subscript):
                tokens.append("Subscript")
            elif isinstance(child, ast.Starred):
                tokens.append("Starred")
            elif isinstance(child, ast.JoinedStr):
                tokens.append("FString")

        return "|".join(tokens)


_MIN_FUNCTION_LINES = 10  # default; overridden by config / CLI
_IGNORE_FUNCTION_NAMES: set[str] = set()
_IGNORE_RULES: list[IgnoreRule] = []


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def scan_directory(
    root: Path,
    *,
    min_lines: int = _MIN_FUNCTION_LINES,
    exclude_patterns: list[str] | None = None,
    ignore_function_names: list[str] | None = None,
    ignore_rules: list[dict[str, Any]] | None = None,
) -> dict[str, DuplicateGroup]:
    """Scan *root* for Python files and return duplicate-function groups."""
    global _MIN_FUNCTION_LINES, _IGNORE_FUNCTION_NAMES, _IGNORE_RULES
    _MIN_FUNCTION_LINES = min_lines
    _IGNORE_FUNCTION_NAMES = set(ignore_function_names or [])
    _IGNORE_RULES = _parse_ignore_rules(ignore_rules or [])

    excludes = set(exclude_patterns or [])
    hash_map: dict[str, list[FunctionInfo]] = collections.defaultdict(list)
    files_scanned = 0
    functions_analyzed = 0

    for pyfile in sorted(root.rglob("*.py")):
        rel = str(pyfile.relative_to(root.parent if root.name != "." else root))
        if any(excl in rel for excl in excludes):
            continue
        try:
            source = pyfile.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(pyfile))
        except (SyntaxError, UnicodeDecodeError):
            continue

        hasher = _FunctionHasher(str(pyfile))
        hasher.visit(tree)
        files_scanned += 1
        functions_analyzed += len(hasher.results)

        for h, info in hasher.results:
            hash_map[h].append(info)

    groups: dict[str, DuplicateGroup] = {}
    for h, funcs in hash_map.items():
        if len(funcs) > 1:
            groups[h] = DuplicateGroup(structural_hash=h, functions=funcs)

    return groups


def _parse_ignore_rules(raw_rules: list[dict[str, Any]]) -> list[IgnoreRule]:
    """Parse path-scoped ignore rules from config."""
    parsed: list[IgnoreRule] = []
    for idx, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            raise ValueError(f"ignore_rules[{idx}] must be a mapping")

        names = raw.get("function_names") or raw.get("functions")
        if not isinstance(names, list) or not names:
            raise ValueError(f"ignore_rules[{idx}] must define non-empty function_names list")
        function_names = frozenset(name.strip() for name in names if isinstance(name, str) and name.strip())
        if not function_names:
            raise ValueError(f"ignore_rules[{idx}] has no valid function names")

        path_contains = raw.get("path_contains", [])
        if path_contains is None:
            path_contains = []
        if not isinstance(path_contains, list):
            raise ValueError(f"ignore_rules[{idx}] path_contains must be a list")
        clean_markers = tuple(marker.strip() for marker in path_contains if isinstance(marker, str) and marker.strip())

        parsed.append(IgnoreRule(function_names=function_names, path_contains=clean_markers))
    return parsed


def compute_stats(groups: dict[str, DuplicateGroup]) -> dict[str, int | float]:
    """Compute summary statistics from duplicate groups."""
    total_dup_lines = sum(g.duplicated_lines for g in groups.values())
    total_instances = sum(g.copies - 1 for g in groups.values())
    return {
        "groups": len(groups),
        "duplicate_instances": total_instances,
        "duplicated_lines": total_dup_lines,
    }


# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------


def _load_config(pyproject_path: Path) -> dict:
    """Load [tool.benchbox.duplicates] from pyproject.toml."""
    if not pyproject_path.exists():
        return {}
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    return data.get("tool", {}).get("benchbox", {}).get("duplicates", {})


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _format_report(
    groups: dict[str, DuplicateGroup],
    stats: dict[str, int | float],
    *,
    top_n: int = 20,
    verbose: bool = False,
) -> str:
    """Format a human-readable report."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("Duplicate Code Report (AST structural clone detection)")
    lines.append("=" * 72)
    lines.append(f"Duplicate function groups: {stats['groups']}")
    lines.append(f"Total duplicate instances: {stats['duplicate_instances']}")
    lines.append(f"Estimated duplicated lines: {stats['duplicated_lines']}")
    lines.append("")

    ranked = sorted(groups.values(), key=lambda g: g.duplicated_lines, reverse=True)

    if ranked:
        lines.append(f"Top {min(top_n, len(ranked))} groups by duplicated lines:")
        lines.append("-" * 72)

    for i, group in enumerate(ranked[:top_n]):
        names = sorted({f.name for f in group.functions})
        lines.append(
            f"  {i + 1:3d}. {group.copies} copies, ~{group.representative_lines} lines each "
            f"({group.duplicated_lines} dup lines): {', '.join(names[:3])}"
        )
        if verbose:
            for func in group.functions:
                lines.append(f"       {func.file}:{func.line}")
        else:
            # Show first 3 locations
            for func in group.functions[:3]:
                lines.append(f"       {func.file}:{func.line} - {func.name}()")
            if group.copies > 3:
                lines.append(f"       ... and {group.copies - 3} more")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


def _json_report(groups: dict[str, DuplicateGroup], stats: dict[str, int | float]) -> str:
    """Produce a machine-readable JSON report."""
    import json

    ranked = sorted(groups.values(), key=lambda g: g.duplicated_lines, reverse=True)
    data = {
        "summary": stats,
        "groups": [
            {
                "hash": g.structural_hash,
                "copies": g.copies,
                "lines_each": g.representative_lines,
                "duplicated_lines": g.duplicated_lines,
                "functions": [
                    {"name": f.name, "file": f.file, "line": f.line, "end_line": f.end_line} for f in g.functions
                ],
            }
            for g in ranked
        ],
    }
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect duplicate functions via AST structural hashing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s                                   # Check with defaults from pyproject.toml
  %(prog)s --source-root benchbox --threshold 25000
  %(prog)s --min-lines 15 --verbose          # Verbose report, larger functions only
  %(prog)s --json                            # Machine-readable output
  %(prog)s --report-only                     # Report without failing
""",
    )
    parser.add_argument(
        "--source-root",
        default=None,
        help="Directory to scan (default: from pyproject.toml or 'benchbox')",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="Max allowed duplicated lines (default: from pyproject.toml or 25000)",
    )
    parser.add_argument(
        "--min-lines",
        type=int,
        default=None,
        help="Minimum function size to consider (default: from pyproject.toml or 10)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=20,
        help="Number of top duplicate groups to show (default: 20)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show all locations for each duplicate group",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output machine-readable JSON",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Report duplicates without failing",
    )
    parser.add_argument(
        "--pyproject",
        default="pyproject.toml",
        help="Path to pyproject.toml for config (default: pyproject.toml)",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    config = _load_config(Path(args.pyproject))

    source_root = Path(args.source_root or config.get("source_root", "benchbox"))
    threshold = args.threshold if args.threshold is not None else config.get("threshold", 25000)
    min_lines = args.min_lines if args.min_lines is not None else config.get("min_lines", 10)
    exclude_patterns = config.get("exclude_patterns", [])
    ignore_function_names = config.get("ignore_function_names", [])
    ignore_rules = config.get("ignore_rules", [])

    if not source_root.is_dir():
        print(f"error: source root '{source_root}' is not a directory")
        return 1

    groups = scan_directory(
        source_root,
        min_lines=min_lines,
        exclude_patterns=exclude_patterns,
        ignore_function_names=ignore_function_names,
        ignore_rules=ignore_rules,
    )
    stats = compute_stats(groups)

    if args.json_output:
        print(_json_report(groups, stats))
    else:
        print(_format_report(groups, stats, top_n=args.top_n, verbose=args.verbose))

    duplicated_lines = stats["duplicated_lines"]

    if args.json_output:
        pass  # JSON consumers parse the output themselves
    elif duplicated_lines > threshold:
        print(f"FAIL: {duplicated_lines} duplicated lines exceeds threshold of {threshold}")
        if not args.report_only:
            return 1
    else:
        print(f"PASS: {duplicated_lines} duplicated lines within threshold of {threshold}")

    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv or sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
