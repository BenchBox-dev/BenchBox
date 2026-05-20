"""Package dependency metadata guardrails."""

from __future__ import annotations

from pathlib import Path

import pytest
from packaging.requirements import Requirement

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[import-not-found]

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[2]


def _core_dependencies() -> dict[str, Requirement]:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = {}
    for entry in pyproject["project"]["dependencies"]:
        requirement = Requirement(entry)
        dependencies[requirement.name.lower()] = requirement
    return dependencies


def test_pandas_is_core_dependency_while_top_level_import_path_requires_it() -> None:
    dependencies = _core_dependencies()

    assert "pandas" in dependencies
    assert str(dependencies["pandas"].specifier) == ">=2.0.0"
