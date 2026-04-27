#!/usr/bin/env python3
"""Check for Windows anti-patterns in the benchbox codebase.

Uses AST analysis to find patterns that compile and run on Linux/macOS
but silently misbehave or fail on Windows:

  1. os.access(path, os.X_OK) - always returns True on Windows; use
     .suffix == ".exe" or os.name checks instead.
  2. Unguarded Unix-only signals (SIGTERM, SIGKILL, SIGHUP, SIGUSR1/2,
     SIGCHLD, SIGPIPE) - these don't exist on Windows; guard with
     `if hasattr(signal, ...)`.

Usage:
    uv run -- python scripts/check_windows_antipatterns.py
    uv run -- python scripts/check_windows_antipatterns.py --path benchbox/
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Unix-only signal names that do not exist on Windows
_UNIX_SIGNALS = {"SIGTERM", "SIGKILL", "SIGHUP", "SIGUSR1", "SIGUSR2", "SIGCHLD", "SIGPIPE"}

# Default search roots (relative to repo root)
_DEFAULT_ROOTS = ["benchbox"]


@dataclass(frozen=True)
class Violation:
    file: Path
    line: int
    col: int
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}:{self.col}: {self.code} {self.message}"


class WindowsAntipatternsVisitor(ast.NodeVisitor):
    """AST visitor that collects Windows anti-pattern violations."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.violations: list[Violation] = []

    def _add(self, node: ast.AST, code: str, message: str) -> None:
        self.violations.append(
            Violation(
                file=self.path,
                line=node.lineno,  # type: ignore[attr-defined]
                col=node.col_offset,  # type: ignore[attr-defined]
                code=code,
                message=message,
            )
        )

    # ------------------------------------------------------------------ #
    # WA001: os.access(path, os.X_OK)                                     #
    # ------------------------------------------------------------------ #

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        self._check_os_access(node)
        self._check_getattr_signal(node)
        self.generic_visit(node)

    def _check_os_access(self, node: ast.Call) -> None:
        """Flag os.access(_, os.X_OK) - a no-op on Windows (always True)."""
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "access"):
            return
        if not (isinstance(func.value, ast.Name) and func.value.id == "os"):
            return
        # Check that one of the arguments is os.X_OK
        all_args = list(node.args) + [kw.value for kw in node.keywords]
        for arg in all_args:
            if (
                isinstance(arg, ast.Attribute)
                and arg.attr == "X_OK"
                and isinstance(arg.value, ast.Name)
                and arg.value.id == "os"
            ):
                self._add(
                    node,
                    "WA001",
                    "os.access(path, os.X_OK) is always True on Windows - "
                    "use `path.suffix == '.exe'` check or guard with `if os.name != 'nt'`",
                )
                return

    def _check_getattr_signal(self, node: ast.Call) -> None:
        """Flag getattr(signal, 'SIGXXX') - 2-arg form raises AttributeError on Windows."""
        if not (isinstance(node.func, ast.Name) and node.func.id == "getattr"):
            return
        if len(node.args) != 2:
            return
        if not (isinstance(node.args[0], ast.Name) and node.args[0].id == "signal"):
            return
        if not (isinstance(node.args[1], ast.Constant) and node.args[1].value in _UNIX_SIGNALS):
            return
        sig_name = node.args[1].value
        self._add(
            node,
            "WA002",
            f"getattr(signal, '{sig_name}') raises AttributeError on Windows - "
            f"use getattr(signal, '{sig_name}', None) or guard with `if hasattr(signal, '{sig_name}')`",
        )

    # ------------------------------------------------------------------ #
    # WA002: unguarded Unix-only signal constants                         #
    # ------------------------------------------------------------------ #

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        self._check_unix_signal(node)
        self.generic_visit(node)

    def _check_unix_signal(self, node: ast.Attribute) -> None:
        """Flag signal.SIGTERM etc. outside a hasattr() guard."""
        if node.attr not in _UNIX_SIGNALS:
            return
        if not (isinstance(node.value, ast.Name) and node.value.id == "signal"):
            return
        self._add(
            node,
            "WA002",
            f"signal.{node.attr} does not exist on Windows - "
            f"guard with `if hasattr(signal, '{node.attr}')` or `if os.name != 'nt'`",
        )


def _is_platform_check(node: ast.expr) -> bool:
    """True if node is a platform guard (os.name, sys.platform, or platform.system())."""
    if not isinstance(node, ast.Compare):
        return False
    if not (len(node.ops) == 1 and len(node.comparators) == 1):
        return False
    op = node.ops[0]
    val = node.comparators[0]
    if not isinstance(op, (ast.Eq, ast.NotEq)):
        return False
    left = node.left

    # os.name == "nt" / os.name != "nt"
    if (
        isinstance(left, ast.Attribute)
        and left.attr == "name"
        and isinstance(left.value, ast.Name)
        and left.value.id == "os"
        and isinstance(val, ast.Constant)
        and val.value == "nt"
    ):
        return True

    # sys.platform == "win32" / sys.platform != "win32"
    if (
        isinstance(left, ast.Attribute)
        and left.attr == "platform"
        and isinstance(left.value, ast.Name)
        and left.value.id == "sys"
        and isinstance(val, ast.Constant)
        and val.value == "win32"
    ):
        return True

    # platform.system() == "Windows" / platform.system() != "Windows"
    if (
        isinstance(left, ast.Call)
        and isinstance(left.func, ast.Attribute)
        and left.func.attr == "system"
        and isinstance(left.func.value, ast.Name)
        and left.func.value.id == "platform"
        and isinstance(val, ast.Constant)
        and val.value == "Windows"
    ):
        return True

    return False


def _collect_os_access_lines(node: ast.AST, guarded_lines: set[int]) -> None:
    """Add line numbers of os.access(..., os.X_OK) calls found within node to guarded_lines."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "access"
            and isinstance(func.value, ast.Name)
            and func.value.id == "os"
        ):
            continue
        for arg in list(child.args) + [kw.value for kw in child.keywords]:
            if (
                isinstance(arg, ast.Attribute)
                and arg.attr == "X_OK"
                and isinstance(arg.value, ast.Name)
                and arg.value.id == "os"
            ):
                guarded_lines.add(child.lineno)


def _collect_os_name_guarded_lines(tree: ast.AST) -> set[int]:
    """Return line numbers of os.access() calls guarded by a platform check.

    Recognises these patterns:
      - `os.name != "nt" and os.access(..., os.X_OK)`
      - `sys.platform != "win32" and os.access(..., os.X_OK)`
      - `platform.system() != "Windows" and os.access(..., os.X_OK)`
      - `if os.name != "nt": ... os.access(...) ...`
      - (and == / or equivalents for the bool-op forms)
    """
    guarded_lines: set[int] = set()

    for node in ast.walk(tree):
        # Pattern: `<platform check> and/or os.access(..., os.X_OK)`
        if isinstance(node, ast.BoolOp):
            has_guard = any(_is_platform_check(v) for v in node.values)
            if has_guard:
                for v in node.values:
                    _collect_os_access_lines(v, guarded_lines)

        # Pattern: `if <platform check>: ... os.access(...) ...`
        # Walk only node.body (true branch) - the orelse branch is NOT guarded.
        if isinstance(node, ast.If) and _is_platform_check(node.test):
            for stmt in node.body:
                for child in ast.walk(stmt):
                    _collect_os_access_lines(child, guarded_lines)

    return guarded_lines


def _extract_hasattr_signal_from_node(n: ast.AST) -> str | None:
    """Return signal name if n is `hasattr(_, 'SIGNAME')`, else None."""
    if (
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "hasattr"
        and len(n.args) >= 2
        and isinstance(n.args[1], ast.Constant)
        and n.args[1].value in _UNIX_SIGNALS
    ):
        return n.args[1].value  # type: ignore[return-value]
    return None


def _hasattr_signal_in_call(node: ast.Call) -> str | None:
    """Return signal name from a standalone `hasattr(signal, 'SIG*')` call."""
    return _extract_hasattr_signal_from_node(node)


def _getattr_signal_in_call(node: ast.Call) -> str | None:
    """Return signal name from a 3-arg `getattr(signal, 'SIG*', default)` call."""
    if (
        isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 3
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "signal"
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value in _UNIX_SIGNALS
    ):
        return node.args[1].value  # type: ignore[return-value]
    return None


def _guard_signals_from_if_test(test: ast.AST) -> set[str]:
    """Return signal names this `if` test guards via hasattr(...)."""
    signals: set[str] = set()
    direct = _extract_hasattr_signal_from_node(test)
    if direct:
        signals.add(direct)
    elif isinstance(test, ast.BoolOp):
        for value in test.values:
            sig = _extract_hasattr_signal_from_node(value)
            if sig:
                signals.add(sig)
    return signals


def _handler_catches_attr_error(h: ast.ExceptHandler) -> bool:
    """True if handler catches AttributeError or is a bare except."""
    if h.type is None:
        return True
    if isinstance(h.type, ast.Name) and h.type.id == "AttributeError":
        return True
    if isinstance(h.type, ast.Tuple):
        return any(isinstance(t, ast.Name) and t.id == "AttributeError" for t in h.type.elts)
    return False


def _iter_signal_attrs(stmts: list[ast.stmt]):
    """Yield ast.Attribute nodes of form `signal.SIG*` inside a list of stmts."""
    for stmt in stmts:
        for child in ast.walk(stmt):
            if (
                isinstance(child, ast.Attribute)
                and child.attr in _UNIX_SIGNALS
                and isinstance(child.value, ast.Name)
                and child.value.id == "signal"
            ):
                yield child


def _collect_guarded_signal_lines(tree: ast.AST) -> set[tuple[int, str]]:
    """Return set of (lineno, signal_name) that appear inside hasattr/getattr/try guards."""
    guarded: set[tuple[int, str]] = set()

    class _HasattrFinder(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            sig = _hasattr_signal_in_call(node) or _getattr_signal_in_call(node)
            if sig:
                guarded.add((node.lineno, sig))
            self.generic_visit(node)

        def visit_If(self, node: ast.If) -> None:  # noqa: N802
            guard_signals = _guard_signals_from_if_test(node.test)
            if guard_signals:
                for sig_name in guard_signals:
                    for child in ast.walk(node):
                        if hasattr(child, "lineno"):
                            guarded.add((child.lineno, sig_name))  # type: ignore[attr-defined]
            self.generic_visit(node)

        def visit_Try(self, node: ast.Try) -> None:  # noqa: N802
            if any(_handler_catches_attr_error(h) for h in node.handlers):
                for child in _iter_signal_attrs(node.body):
                    guarded.add((child.lineno, child.attr))
            self.generic_visit(node)

    _HasattrFinder().visit(tree)
    return guarded


def _has_noqa(lines: list[str], v: Violation) -> bool:
    """Return True if the source line suppresses this violation with # noqa: WAxxx."""
    if v.line > len(lines):
        return False
    line = lines[v.line - 1]  # 1-indexed
    noqa_match = re.search(r"#\s*noqa:\s*([\w,\s]+)", line)
    if noqa_match:
        codes = {c.strip() for c in noqa_match.group(1).split(",")}
        return v.code in codes
    return False


def check_file(path: Path) -> list[Violation]:
    """Return violations found in a single Python source file."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    visitor = WindowsAntipatternsVisitor(path)
    visitor.visit(tree)

    if not visitor.violations:
        return []

    # Apply noqa suppression BEFORE post-filters (takes precedence)
    source_lines = source.splitlines()
    after_noqa = [v for v in visitor.violations if not _has_noqa(source_lines, v)]

    if not after_noqa:
        return []

    # Post-filter WA001: remove os.access violations guarded by a platform check
    os_name_guarded = _collect_os_name_guarded_lines(tree)

    # Post-filter WA002: remove violations that are inside hasattr/getattr/try guards
    signal_guarded = _collect_guarded_signal_lines(tree)

    filtered: list[Violation] = []
    for v in after_noqa:
        if v.code == "WA001" and v.line in os_name_guarded:
            continue
        if v.code == "WA002":
            sig_name = next((s for s in _UNIX_SIGNALS if s in v.message), "")
            if sig_name and (v.line, sig_name) in signal_guarded:
                continue
        filtered.append(v)

    return filtered


def check_tree(roots: list[Path]) -> tuple[list[Violation], int]:
    """Recursively check all .py files under the given roots.

    Returns a tuple of (violations, file_count).
    """
    violations: list[Violation] = []
    file_count = 0
    for root in roots:
        for py_file in sorted(root.rglob("*.py")):
            violations.extend(check_file(py_file))
            file_count += 1
    return violations, file_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--path",
        metavar="DIR",
        action="append",
        dest="paths",
        help="Directory to scan (repeatable; default: benchbox/)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent
    roots = [repo_root / p for p in (args.paths or _DEFAULT_ROOTS)]

    missing = [r for r in roots if not r.exists()]
    if missing:
        print(f"error: paths not found: {', '.join(str(m) for m in missing)}", file=sys.stderr)
        return 2

    violations, file_count = check_tree(roots)

    if violations:
        print(f"Found {len(violations)} Windows anti-pattern violation(s):\n")
        for v in violations:
            print(f"  {v}")
        print()
        print("See scripts/check_windows_antipatterns.py for remediation guidance.")
        return 1

    print(f"No Windows anti-pattern violations found ({file_count} files checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
