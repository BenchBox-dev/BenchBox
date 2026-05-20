"""Tests for scripts/check_dependency_audit.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_dependency_audit.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_dependency_audit", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_project(root: Path, pyproject_dependencies: str, source: str) -> None:
    (root / "benchbox").mkdir()
    (root / "benchbox" / "__init__.py").write_text("", encoding="utf-8")
    (root / "benchbox" / "sample.py").write_text(source, encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f"""
[project]
name = "fixture"
version = "0.0.0"
dependencies = [
{pyproject_dependencies}
]
""",
        encoding="utf-8",
    )


def test_declared_but_unused_dependency_is_reported(tmp_path: Path) -> None:
    audit = _load_script()
    _write_project(
        tmp_path,
        '    "click>=8",\n    "rich>=13",',
        "import click\n",
    )

    result = audit.audit_dependencies(tmp_path, ["benchbox"])

    assert result.imported_without_declaration == {}
    assert sorted(result.declared_without_import) == ["rich"]


def test_imported_but_undeclared_dependency_is_reported(tmp_path: Path) -> None:
    audit = _load_script()
    _write_project(
        tmp_path,
        '    "click>=8",',
        "import click\nimport undeclared_pkg\n",
    )

    result = audit.audit_dependencies(tmp_path, ["benchbox"])

    assert result.declared_without_import == {}
    assert result.imported_without_declaration == {
        "undeclared_pkg": ["benchbox/sample.py:2"],
    }


def test_namespace_import_can_satisfy_declared_distribution(tmp_path: Path) -> None:
    audit = _load_script()
    _write_project(
        tmp_path,
        '    "google-cloud-bigquery>=3",',
        "from google.cloud import bigquery\n",
    )

    result = audit.audit_dependencies(tmp_path, ["benchbox"])

    assert result.declared_without_import == {}
    assert result.imported_without_declaration == {}


def test_allowlisted_cli_plugin_dependency_can_have_no_import_site(tmp_path: Path) -> None:
    audit = _load_script()
    _write_project(tmp_path, '    "pytest>=8",', "")

    result = audit.audit_dependencies(tmp_path, ["benchbox"])

    assert result.declared_without_import == {}
    assert result.allowed_declared_without_import == {"pytest"}


def test_relocated_audit_runs_without_project_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    audit = _load_script()
    _write_project(tmp_path, '    "click>=8",', "import click\n")

    assert not (tmp_path / "_project").exists()
    assert audit.main(["--root", str(tmp_path), "--scan-path", "benchbox"]) == 0

    out = capsys.readouterr().out
    assert "All checks passed." in out
    assert "skipping" not in out.lower()
