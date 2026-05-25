"""ABC conformance test: detect signature drift in PlatformAdapter subclasses.

Uses ast.parse to inspect method signatures without importing heavy SDKs.
Any concrete adapter that overrides create_schema, load_data, or execute_query
must use the same positional parameter names as the base PlatformAdapter ABC.

Failure here means the orchestrator will likely get a TypeError or silently
bind the wrong values (the root cause of C2/C3 in the 13-pattern audit).

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# ABC positional parameters (after self) for each checked method.
# Adapters may ADD keyword-only parameters, but must not change the order
# or names of these leading positionals.
_ABC_SIGNATURES: dict[str, list[str]] = {
    "create_schema": ["benchmark", "connection"],
    "load_data": ["benchmark", "connection", "data_dir"],
    "execute_query": ["connection", "query", "query_id"],
}

# Files to skip — these are not concrete adapter modules.
_SKIP_FILES = {
    "__init__.py",
    "_spark_helpers.py",
    "adapter_factory.py",
    "cloud_shared.py",
    "presto_trino_utils.py",
    "questdb_rewriter.py",
    "datafusion_query_transformer.py",
    "datafusion_write_transformer.py",
}

_PLATFORMS_DIR = Path(__file__).parents[3] / "benchbox" / "platforms"
_SKIP_DIRS = frozenset({"base", "credentials", "dataframe"})


def _positional_params(funcdef: ast.FunctionDef) -> list[str]:
    """Return positional (non-self, non-*args, non-**kwargs) parameter names."""
    args = funcdef.args
    # args.args includes 'self'; skip index 0
    positional = [a.arg for a in args.args[1:]]
    # Stop before *args / **kwargs
    return positional


def _collect_adapter_method_overrides() -> list[tuple[str, str, str, list[str]]]:
    """Walk platform .py files and collect (file, class, method, params) for overrides.

    Returns a list of (relative_path, class_name, method_name, positional_params)
    for every method in _ABC_SIGNATURES that is overridden in a non-base class.
    """
    overrides: list[tuple[str, str, str, list[str]]] = []

    for py_file in sorted(_PLATFORMS_DIR.rglob("*.py")):
        relative_path = py_file.relative_to(_PLATFORMS_DIR)
        if any(part in _SKIP_DIRS for part in relative_path.parts):
            continue
        if py_file.name in _SKIP_FILES:
            continue

        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue  # broken file — a different test will catch it

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            # Only look at classes that plausibly inherit from PlatformAdapter
            # (either directly or via a mixin chain). We check by name heuristic.
            base_names = set()
            for base in node.bases:
                if isinstance(base, ast.Name):
                    base_names.add(base.id)
                elif isinstance(base, ast.Attribute):
                    base_names.add(base.attr)

            is_abstract_base = node.name in {"PlatformAdapter", "BaseDdlOptimizer"}
            if is_abstract_base:
                continue  # skip the ABC itself

            for item in node.body:
                if not isinstance(item, ast.FunctionDef):
                    continue
                if item.name not in _ABC_SIGNATURES:
                    continue
                params = _positional_params(item)
                overrides.append((relative_path.as_posix(), node.name, item.name, params))

    return overrides


_OVERRIDES = _collect_adapter_method_overrides()


@pytest.mark.parametrize("file_name,class_name,method_name,actual_params", _OVERRIDES)
def test_method_signature_matches_abc(
    file_name: str,
    class_name: str,
    method_name: str,
    actual_params: list[str],
) -> None:
    """Verify that the override's leading positional params match the ABC contract."""
    expected = _ABC_SIGNATURES[method_name]
    # The adapter may append extra keyword-only params after the required ones.
    # We only check that the required leading params match.
    leading = actual_params[: len(expected)]

    assert leading == expected, (
        f"{file_name}::{class_name}.{method_name} positional params {actual_params!r} "
        f"do not match ABC contract {expected!r}.\n"
        f"The orchestrator calls this method with positional args in the ABC order; "
        f"mismatched names indicate parameter binding bugs (see C2/C3 audit findings)."
    )
