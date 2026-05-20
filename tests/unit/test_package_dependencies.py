"""Package dependency metadata guardrails."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[import-not-found]

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "benchbox"
STDLIB_MODULES = frozenset(getattr(sys, "stdlib_module_names", ()))

ENTRYPOINTS = {
    "import benchbox": "import benchbox",
    "benchbox --help": """
from click.testing import CliRunner
from benchbox.cli.main import cli

result = CliRunner().invoke(cli, ["--help"])
if result.exit_code != 0:
    raise RuntimeError(result.output)
""",
}


def _pyproject() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _core_dependencies() -> dict[str, Requirement]:
    pyproject = _pyproject()
    dependencies = {}
    for entry in pyproject["project"]["dependencies"]:
        requirement = Requirement(entry)
        dependencies[canonicalize_name(requirement.name)] = requirement
    return dependencies


def _optional_dependency_names() -> set[str]:
    optional = set()
    for entries in _pyproject()["project"].get("optional-dependencies", {}).values():
        for entry in entries:
            optional.add(canonicalize_name(Requirement(entry).name))
    return optional


def _packages_distributions() -> dict[str, list[str]]:
    script = """
import importlib.metadata
import json

print(json.dumps(importlib.metadata.packages_distributions(), sort_keys=True))
"""
    output = subprocess.check_output([sys.executable, "-c", script], cwd=REPO_ROOT, text=True)
    return json.loads(output)


def _loaded_benchbox_modules(statement: str) -> dict[str, str]:
    script = f"""
import json
import sys

{statement}

modules = {{
    name: module.__file__
    for name, module in sys.modules.items()
    if name.startswith("benchbox") and getattr(module, "__file__", None)
}}
print(json.dumps(modules, sort_keys=True))
"""
    output = subprocess.check_output([sys.executable, "-c", script], cwd=REPO_ROOT, text=True)
    return json.loads(output)


def _top_level_import_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module.partition(".")[0])
    return imports


def _direct_third_party_imports(statement: str) -> set[str]:
    imported = set()
    for raw_path in _loaded_benchbox_modules(statement).values():
        path = Path(raw_path).resolve()
        if not path.is_relative_to(PACKAGE_ROOT):
            continue
        for import_name in _top_level_import_names(path):
            if import_name == "benchbox" or import_name in STDLIB_MODULES or import_name.startswith("_"):
                continue
            imported.add(import_name)
    return imported


def _canonical_distribution_names(import_name: str, package_distributions: dict[str, list[str]]) -> set[str]:
    distributions = package_distributions.get(import_name, [import_name])
    return {canonicalize_name(distribution) for distribution in distributions}


def _import_names_for_distributions(
    distribution_names: set[str], package_distributions: dict[str, list[str]]
) -> set[str]:
    import_names = set()
    for import_name, distributions in package_distributions.items():
        if any(canonicalize_name(distribution) in distribution_names for distribution in distributions):
            import_names.add(import_name)
    return import_names


def test_pandas_is_core_dependency_while_top_level_import_path_requires_it() -> None:
    dependencies = _core_dependencies()

    assert "pandas" in dependencies
    assert str(dependencies["pandas"].specifier) == ">=2.0.0"


@pytest.mark.parametrize(("entrypoint", "statement"), ENTRYPOINTS.items(), ids=list(ENTRYPOINTS))
def test_eager_third_party_imports_are_declared_core_dependencies(entrypoint: str, statement: str) -> None:
    core_dependency_names = set(_core_dependencies())
    package_distributions = _packages_distributions()
    imported = _direct_third_party_imports(statement)

    undeclared = {
        import_name: sorted(_canonical_distribution_names(import_name, package_distributions))
        for import_name in imported
        if not (_canonical_distribution_names(import_name, package_distributions) & core_dependency_names)
    }

    assert not undeclared, f"{entrypoint} has undeclared eager third-party imports: {undeclared}"


@pytest.mark.parametrize(("entrypoint", "statement"), ENTRYPOINTS.items(), ids=list(ENTRYPOINTS))
def test_optional_only_dependencies_stay_off_eager_import_paths(entrypoint: str, statement: str) -> None:
    core_dependency_names = set(_core_dependencies())
    optional_only_names = _optional_dependency_names() - core_dependency_names
    package_distributions = _packages_distributions()
    optional_only_import_names = _import_names_for_distributions(optional_only_names, package_distributions)

    imported_optional_only = _direct_third_party_imports(statement) & optional_only_import_names

    assert not imported_optional_only, (
        f"{entrypoint} eagerly imports optional-only dependencies: {sorted(imported_optional_only)}"
    )
