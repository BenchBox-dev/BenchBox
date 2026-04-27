"""Compatibility lint - errors on unregistered dialect branches in benchbox/core/.

Dialect branches (``if dialect in (...)``, ``if dialect == "..."``) inside
``benchbox/core/`` must be either:

  (a) inside a ``@compat_local``-decorated callable (legitimate type mapping,
      storage layout, or rendering), or
  (b) registered in the sql_compat rule registry.

Exits 1 if any unregistered branches are found (error mode as of W16).

Additionally, in warn-only mode (not causing a non-zero exit), the linter
reports rule reason strings that do not begin with an approved consequence prefix
defined in benchbox/sql_compat/_reason_conventions.py. Promotion to error mode
for reason-string violations is a separate follow-up after all rules comply.

Scope note: this linter covers ``benchbox/core/`` only (configurable via
``--root``). The ``benchbox/platforms/`` directory is NOT scanned - DDL
optimization logic in ``_optimize_table_definition`` methods there is governed
by manual ``ddl_optimize`` registry rule entries, not by lint enforcement.
See ADR adr-sql-compat-phase-aware-pipeline.md §DDL Centralization.

Usage:
    uv run scripts/compat_lint.py
    uv run scripts/compat_lint.py --root benchbox/core/other_module
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.inventory import _extract_platforms, _should_scan

# ---------------------------------------------------------------------------
# Decorator detection
# ---------------------------------------------------------------------------

_DECORATOR_NAME = "compat_local"


def _is_compat_local(decorator_node: ast.expr) -> bool:
    """Return True if *decorator_node* is a @compat_local or @compat_local(...)."""
    # @compat_local(kind=..., ...)
    if isinstance(decorator_node, ast.Call):
        func = decorator_node.func
        if isinstance(func, ast.Name) and func.id == _DECORATOR_NAME:
            return True
        if isinstance(func, ast.Attribute) and func.attr == _DECORATOR_NAME:
            return True
    # @compat_local  (bare, no-arg form)
    if isinstance(decorator_node, ast.Name) and decorator_node.id == _DECORATOR_NAME:
        return True
    return False


def _compat_local_ranges(tree: ast.Module) -> list[tuple[int, int]]:
    """Return (start_line, end_line) pairs for all @compat_local-decorated functions."""
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not hasattr(node, "end_lineno"):
            continue
        if any(_is_compat_local(dec) for dec in node.decorator_list):
            ranges.append((node.lineno, node.end_lineno))  # type: ignore[attr-defined]
    return ranges


def _inside_ranges(lineno: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= lineno <= end for start, end in ranges)


# ---------------------------------------------------------------------------
# Dialect-branch detection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _DialectBranch:
    lineno: int
    platforms: tuple[str, ...]
    enclosing_function: str | None


def _build_parent_map(tree: ast.Module) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _enclosing_function_name(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str | None:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
        current = parents.get(current)
    return None


def _dialect_branches(tree: ast.Module) -> list[_DialectBranch]:
    """Return all detected dialect-branch if-statements in *tree*."""
    parents = _build_parent_map(tree)
    branches: list[_DialectBranch] = []
    seen: set[int] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        function_name = _enclosing_function_name(node, parents)

        if isinstance(test, ast.Compare) and len(test.ops) == 1:
            left = test.left
            comparators = test.comparators
            op = test.ops[0]

            # if dialect in (...) / if dialect == "x"
            if isinstance(left, ast.Name) and left.id == "dialect":
                if isinstance(op, (ast.In, ast.Eq)):
                    platforms = tuple(_extract_platforms(comparators[0]))
                    if platforms and node.lineno not in seen:
                        branches.append(_DialectBranch(node.lineno, platforms, function_name))
                        seen.add(node.lineno)
                        continue

            # if "platform" in dialect
            for comp in comparators:
                if isinstance(comp, ast.Name) and comp.id == "dialect":
                    platforms = tuple(_extract_platforms(left))
                    if platforms and node.lineno not in seen:
                        branches.append(_DialectBranch(node.lineno, platforms, function_name))
                        seen.add(node.lineno)

        # if dialect == "a" or dialect == "b"
        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
            platforms: list[str] = []
            for val in test.values:
                if isinstance(val, ast.Compare) and isinstance(val.ops[0], ast.Eq):
                    if isinstance(val.left, ast.Name) and val.left.id == "dialect":
                        platforms.extend(_extract_platforms(val.comparators[0]))
            if platforms and node.lineno not in seen:
                branches.append(_DialectBranch(node.lineno, tuple(sorted(set(platforms))), function_name))
                seen.add(node.lineno)

    return sorted(branches, key=lambda branch: branch.lineno)


# ---------------------------------------------------------------------------
# Registry coverage
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_registry_rules() -> None:
    import benchbox.sql_compat.rules as rules_pkg

    for _, module_name, ispkg in pkgutil.walk_packages(rules_pkg.__path__, rules_pkg.__name__ + "."):
        if ispkg:
            continue
        importlib.import_module(module_name)


def _benchmark_from_path(filepath: Path, root: Path) -> str | None:
    rel = filepath.relative_to(root)
    if len(rel.parts) < 2:
        return None
    return rel.parts[0]


def _infer_phase(filepath: Path, branch: _DialectBranch) -> Phase | None:
    if branch.enclosing_function in {"_supports_primary_keys", "_pk_lock_bypass_required"}:
        return Phase.SCHEMA_EMIT

    filename = filepath.name
    if filename == "schema.py":
        return Phase.SCHEMA_EMIT
    if filename in {"benchmark.py", "queries.py"}:
        return Phase.QUERY_SOURCE
    if filename == "platform_registry.py":
        return Phase.BENCHMARK_GATE
    return None


def _platform_candidates(platform: str) -> set[str]:
    candidates = {platform.lower()}
    try:
        from benchbox.core.platform_registry import PlatformRegistry

        candidates.add(PlatformRegistry.resolve_platform_name(platform))
    except Exception:
        pass
    return {candidate for candidate in candidates if candidate}


def _branch_is_registry_covered(filepath: Path, root: Path, branch: _DialectBranch) -> bool:
    phase = _infer_phase(filepath, branch)
    if phase is None or not branch.platforms:
        return False

    benchmark = _benchmark_from_path(filepath, root)
    if phase is not Phase.BENCHMARK_GATE and benchmark is None:
        return False

    _load_registry_rules()
    from benchbox.sql_compat.registry import REGISTRY

    rules = list(REGISTRY.all_rules())
    for platform in branch.platforms:
        candidates = _platform_candidates(platform)
        if not any(
            key_phase is phase
            and key_platform in candidates
            and (phase is Phase.BENCHMARK_GATE or key_benchmark == benchmark)
            for (key_phase, key_platform, key_benchmark, _query_id), _entry in rules
        ):
            return False
    return True


# ---------------------------------------------------------------------------
# Lint run
# ---------------------------------------------------------------------------


def _rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root.parent))


def lint(root: Path) -> list[str]:
    """Return warning strings for all unexempted dialect branches under *root*."""
    warnings: list[str] = []

    for filepath in sorted(root.rglob("*.py")):
        if not _should_scan(filepath):
            continue
        try:
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(filepath))
        except (SyntaxError, UnicodeDecodeError):
            continue

        exempt_ranges = _compat_local_ranges(tree)
        branches = _dialect_branches(tree)

        rel = _rel(filepath, root)
        for branch in branches:
            if _inside_ranges(branch.lineno, exempt_ranges):
                continue
            if _branch_is_registry_covered(filepath, root, branch):
                continue
            warnings.append(
                f"{rel}:{branch.lineno}: unregistered dialect branch - register a rule or apply @compat_local"
            )

    return warnings


# ---------------------------------------------------------------------------
# Reason-string convention check (warn-only)
# ---------------------------------------------------------------------------


def _reason_convention_warnings() -> list[str]:
    """Return warning strings for rules whose reason does not match its support level's prefix.

    Each support level in REASON_PREFIXES has a single canonical consequence prefix.
    A rule is warned when its support level is in the convention's scope but its
    reason does not start with that level's specific prefix. This rules out the
    substring-overlap loophole between INFORMATIONAL ("Workload runs;") and
    SKIPPED_DDL_FRAGMENT ("Workload runs; auxiliary DDL is suppressed."): a rule
    must use the prefix that matches its declared support level, not just any
    approved prefix.

    Warn-only; does not contribute to the exit code. Promotion to error mode is
    a follow-up after all existing rules comply with the convention.
    """
    from benchbox.sql_compat._reason_conventions import REASON_PREFIXES

    _load_registry_rules()
    from benchbox.sql_compat.registry import REGISTRY

    warnings: list[str] = []
    for _key, entry in REGISTRY.all_rules():
        decision = entry.decision
        level = decision.support_level.value
        if level not in REASON_PREFIXES:
            # NATIVE / TRANSLATED / REWRITTEN have no convention-bound prefix today.
            continue
        expected_prefix = REASON_PREFIXES[level][0]
        reason = decision.reason or ""
        if not reason.startswith(expected_prefix):
            warnings.append(
                f"rule '{decision.rule_id}' ({level}): reason should start with {expected_prefix!r}. "
                f"Got: {reason!r}. "
                f"See benchbox/sql_compat/_reason_conventions.py."
            )
    return warnings


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="BenchBox compatibility lint")
    parser.add_argument(
        "--root",
        default="benchbox/core",
        help="Directory to scan (default: benchbox/core)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"ERROR: root not found: {root}", file=sys.stderr)
        return 1

    warnings = lint(root)
    for w in warnings:
        print(f"COMPAT-WARN: {w}", file=sys.stderr)

    summary = f"{len(warnings)} unregistered dialect branch(es) found in {root}"
    print(summary, file=sys.stderr)

    reason_warnings = _reason_convention_warnings()
    for w in reason_warnings:
        print(f"REASON-WARN: {w}", file=sys.stderr)
    if reason_warnings:
        print(
            f"REASON-WARN: {len(reason_warnings)} rule reason(s) do not follow the approved prefix convention "
            "(warn-only; does not affect exit code).",
            file=sys.stderr,
        )

    return 1 if warnings else 0


if __name__ == "__main__":
    sys.exit(main())
