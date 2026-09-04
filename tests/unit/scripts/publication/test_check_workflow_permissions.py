"""Unit tests for workflow permissions audit script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

SCRIPT = Path(__file__).parents[4] / "scripts/publication/check_workflow_permissions.py"
SPEC = importlib.util.spec_from_file_location("check_workflow_permissions", SCRIPT)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


def test_normalize_permissions() -> None:
    assert checker._normalize_permissions(None) is None
    assert checker._normalize_permissions("write-all") == "write-all"
    assert checker._normalize_permissions({"Contents": "READ", "Pages": "WRITE"}) == {
        "contents": "read",
        "pages": "write",
    }


def test_general_permissions_detects_write_all(tmp_path: Path) -> None:
    bad_wf = tmp_path / "bad.yml"
    data = {
        "name": "Bad",
        "permissions": "write-all",
        "jobs": {
            "test": {
                "runs-on": "ubuntu-latest",
                "steps": [],
            }
        },
    }
    errors = checker.check_general_workflow_permissions(bad_wf, data)
    assert any("write-all" in err for err in errors)


def test_general_permissions_detects_job_write_all(tmp_path: Path) -> None:
    bad_wf = tmp_path / "bad_job.yml"
    data = {
        "name": "Bad Job",
        "jobs": {
            "test": {
                "permissions": "write-all",
                "runs-on": "ubuntu-latest",
                "steps": [],
            }
        },
    }
    errors = checker.check_general_workflow_permissions(bad_wf, data)
    assert any("write-all" in err for err in errors)


def test_general_permissions_detects_unknown_scope(tmp_path: Path) -> None:
    bad_wf = tmp_path / "unknown_scope.yml"
    data = {
        "name": "Unknown Scope",
        "permissions": {"nonexistent-scope": "read"},
        "jobs": {"test": {"runs-on": "ubuntu-latest", "steps": []}},
    }
    errors = checker.check_general_workflow_permissions(bad_wf, data)
    assert any("unknown top-level permission scope" in err for err in errors)


def test_publication_deploy_permissions_valid_structure(tmp_path: Path) -> None:
    wf = tmp_path / "publication-deploy.yml"
    data = {
        "name": "Publication Deploy",
        "permissions": {"contents": "read"},
        "jobs": {
            "build": {
                "permissions": {"contents": "read"},
                "runs-on": "ubuntu-latest",
                "steps": [],
            },
            "deploy": {
                "permissions": {"contents": "read", "pages": "write", "id-token": "write"},
                "runs-on": "ubuntu-latest",
                "steps": [],
            },
            "verify": {
                "permissions": {"contents": "read"},
                "runs-on": "ubuntu-latest",
                "steps": [],
            },
            "rollback": {
                "permissions": {"actions": "read", "contents": "read", "pages": "write", "id-token": "write"},
                "runs-on": "ubuntu-latest",
                "steps": [],
            },
        },
    }
    errors = checker.check_publication_deploy_permissions(wf, data)
    assert errors == []


def test_publication_deploy_permissions_detects_missing_jobs(tmp_path: Path) -> None:
    wf = tmp_path / "publication-deploy.yml"
    data = {
        "name": "Incomplete",
        "jobs": {"build": {}},
    }
    errors = checker.check_publication_deploy_permissions(wf, data)
    assert any("missing required publication pipeline jobs" in err for err in errors)


def test_publication_deploy_permissions_detects_build_write(tmp_path: Path) -> None:
    wf = tmp_path / "publication-deploy.yml"
    data = {
        "name": "Unsafe Build",
        "jobs": {
            "build": {"permissions": {"contents": "write"}},
            "deploy": {"permissions": {"contents": "read"}},
            "verify": {"permissions": {"contents": "read"}},
            "rollback": {"permissions": {"contents": "read"}},
        },
    }
    errors = checker.check_publication_deploy_permissions(wf, data)
    assert any("declared write permissions" in err and "build" in err for err in errors)


def test_publication_deploy_permissions_requires_deploy_pages_write(tmp_path: Path) -> None:
    wf = tmp_path / "publication-deploy.yml"
    data = {
        "name": "Missing Pages Write",
        "jobs": {
            "build": {"permissions": {"contents": "read"}},
            "deploy": {"permissions": {"contents": "read"}},
            "verify": {"permissions": {"contents": "read"}},
            "rollback": {"permissions": {"contents": "read"}},
        },
    }
    errors = checker.check_publication_deploy_permissions(wf, data)
    assert any("only the deploy job may receive Pages write" in err for err in errors)


def test_publication_deploy_permissions_detects_rollback_pages_write(tmp_path: Path) -> None:
    wf = tmp_path / "publication-deploy.yml"
    data = {
        "name": "Forbidden Rollback Pages Write",
        "jobs": {
            "build": {"permissions": {"contents": "read"}},
            "deploy": {"permissions": {"contents": "read", "pages": "write", "id-token": "write"}},
            "verify": {"permissions": {"contents": "read"}},
            "rollback": {"permissions": {"actions": "write", "pages": "write", "id-token": "write"}},
        },
    }
    errors = checker.check_publication_deploy_permissions(wf, data)
    assert any("rollback may restore only an attested artifact" in err for err in errors)


def test_repo_publication_deploy_passes_audit() -> None:
    real_wf = Path(__file__).parents[4] / ".github" / "workflows" / "publication-deploy.yml"
    assert real_wf.is_file()
    text = real_wf.read_text(encoding="utf-8")
    assert "actions/deploy-pages@v4" in text
    assert "actions/upload-pages-artifact@v3" in text
    errors = checker.audit_workflow_file(real_wf, strict=True)
    assert errors == [], f"Errors found in real publication-deploy.yml: {errors}"


def test_main_all_workflows_pass() -> None:
    rc = checker.main([])
    assert rc == 0
