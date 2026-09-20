"""Static check that DataFrame query impls only call real frame methods.

Value-level gates execute queries, so a query module that calls a method the
frame type does not implement (the ``rename_columns``/``with_column`` class:
Polars names that :class:`UnifiedLazyFrame` does not provide) fails only when
that query runs. This module AST-checks every ``*_expression_impl`` in a query
module without importing or executing it: names flowing from
``ctx.get_table(...)`` through the module's frame-wrapping helpers and fluent
method chains are frame-typed, and every method called on a frame-typed value
must exist on the frame API set the caller supplies (``dir()`` of the frame
class under test).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FrameApiViolation:
    """One call on a frame-typed value to a method outside the frame API."""

    module: str
    function: str
    line: int
    method: str

    def describe(self) -> str:
        return f"{self.module}:{self.function}:{self.line}: frame has no method {self.method!r}"


def _is_frame_expr(node: ast.AST, frame_vars: set[str]) -> bool:
    """Whether an expression evaluates to a frame-typed value."""
    if isinstance(node, ast.Name):
        return node.id in frame_vars
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr == "collect":
                # .collect() leaves the lazy frame world (native eager frame).
                return False
            if func.attr == "get_table":
                # ctx.get_table(...) is the primary frame source.
                return True
            return _is_frame_expr(func.value, frame_vars)
        if isinstance(func, ast.Name) and node.args:
            # Module wrapper idiom (_strip_audit_columns(frame, ...)): a plain
            # helper call whose first argument is frame-typed returns a frame.
            return _is_frame_expr(node.args[0], frame_vars)
        return False
    if isinstance(node, ast.Attribute):
        return _is_frame_expr(node.value, frame_vars)
    return False


def _collect_frame_vars(func: ast.FunctionDef) -> set[str]:
    """Names bound to frame-typed values, by fixed-point over assignments."""
    frame_vars: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(func):
            if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                continue
            value = node.value
            if value is None:
                continue
            targets = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            else:
                targets = [node.target]
            if _is_frame_expr(value, frame_vars):
                for target in targets:
                    if isinstance(target, ast.Name) and target.id not in frame_vars:
                        frame_vars.add(target.id)
                        changed = True
                    elif isinstance(target, (ast.Tuple, ast.List)):
                        for elt in target.elts:
                            if isinstance(elt, ast.Name) and elt.id not in frame_vars:
                                frame_vars.add(elt.id)
                                changed = True
    return frame_vars


def check_expression_impl_frame_api(
    func: ast.FunctionDef, *, module: str, frame_api: frozenset[str]
) -> list[FrameApiViolation]:
    """Check one ``*_expression_impl`` for calls to missing frame methods."""
    frame_vars = _collect_frame_vars(func)
    violations: list[FrameApiViolation] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        func_node = node.func
        if not isinstance(func_node, ast.Attribute):
            continue
        if func_node.attr.startswith("_"):
            continue
        if _is_frame_expr(func_node.value, frame_vars) and func_node.attr not in frame_api:
            violations.append(
                FrameApiViolation(
                    module=module,
                    function=func.name,
                    line=node.lineno,
                    method=func_node.attr,
                )
            )
    return violations


def check_module_frame_api(path: Path, *, frame_api: frozenset[str]) -> list[FrameApiViolation]:
    """Check every ``*_expression_impl`` in the module at *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[FrameApiViolation] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.endswith("_expression_impl"):
            violations.extend(check_expression_impl_frame_api(node, module=path.name, frame_api=frame_api))
    return violations


def iter_query_modules(root: Path) -> list[Path]:
    """Registered DataFrame query modules: every ``dataframe_queries`` module tree."""
    modules: list[Path] = []
    for candidate in sorted(root.rglob("dataframe_queries*.py")):
        if ".venv" in candidate.parts or "node_modules" in candidate.parts:
            continue
        modules.append(candidate)
    for candidate in sorted(root.rglob("dataframe_queries/*.py")):
        if ".venv" in candidate.parts or "node_modules" in candidate.parts:
            continue
        modules.append(candidate)
    return modules
