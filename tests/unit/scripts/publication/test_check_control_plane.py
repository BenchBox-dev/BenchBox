"""Unit tests for publication control-plane checker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.publication import check_control_plane as control_mod

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_strict_without_live_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(control_mod, "check_codeowners", list)
    rc = control_mod.main(["--strict"])
    assert rc != 0


def test_local_without_strict_can_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(control_mod, "check_codeowners", list)
    rc = control_mod.main([])
    assert rc == 0


def test_combined_role_is_rejected() -> None:
    with pytest.raises(SystemExit):
        control_mod.main(["--role", "all"])


def test_check_codeowners_missing_patterns(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    codeowners = tmp_path / "CODEOWNERS"
    codeowners.write_text("# incomplete\n*.py @dev\n", encoding="utf-8")
    monkeypatch.setattr(control_mod, "ROOT", tmp_path.parent)
    # mock .github directory
    gh_dir = tmp_path.parent / ".github"
    gh_dir.mkdir(parents=True, exist_ok=True)
    (gh_dir / "CODEOWNERS").write_text("# incomplete\n*.py @dev\n", encoding="utf-8")

    errors = control_mod.check_codeowners()
    assert any("publication/**" in err for err in errors)
    assert any("scripts/publication/**" in err for err in errors)


def test_check_permissions_journal_role() -> None:
    # Journal role requires ONLY contents write
    journal_perms = {"contents": "write"}
    assert control_mod.check_permissions(journal_perms, role="journal") == []

    # Missing contents fails
    assert len(control_mod.check_permissions({}, role="journal")) == 1
    assert control_mod.check_permissions({"contents": "read"}, role="journal")
    assert control_mod.check_permissions({"contents": "write", "workflows": "write"}, role="journal")


def test_check_permissions_legacy_app_role() -> None:
    # Legacy app role requires contents, pull_requests, and workflows
    full_perms = {"contents": "write", "pull_requests": "write", "workflows": "write"}
    assert control_mod.check_permissions(full_perms, role="legacy_app") == []

    # Journal-only perms fail legacy_app check
    journal_perms = {"contents": "write"}
    errors = control_mod.check_permissions(journal_perms, role="legacy_app")
    assert len(errors) == 2
    assert "pull_requests" in "\n".join(errors)
    assert "workflows" in "\n".join(errors)


def test_check_branch_protection_passes_when_safe() -> None:
    gh_output = json.dumps(
        {
            "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": False},
        }
    )
    errors = control_mod.check_branch_protection("BenchBox-dev/BenchBox", "publication", gh_output=gh_output)
    assert errors == []


def test_check_branch_protection_detects_force_push() -> None:
    gh_output = json.dumps(
        {
            "allow_force_pushes": {"enabled": True},
            "allow_deletions": {"enabled": False},
        }
    )
    errors = control_mod.check_branch_protection("BenchBox-dev/BenchBox", "publication", gh_output=gh_output)
    assert len(errors) == 1
    assert "permits force pushes" in errors[0]


def test_check_branch_protection_detects_deletion() -> None:
    gh_output = json.dumps(
        {
            "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": True},
        }
    )
    errors = control_mod.check_branch_protection("BenchBox-dev/BenchBox", "publication", gh_output=gh_output)
    assert len(errors) == 1
    assert "permits deletions" in errors[0]


def test_check_branch_protection_handles_api_error() -> None:
    errors = control_mod.check_branch_protection("BenchBox-dev/BenchBox", "publication", gh_output="invalid json")
    assert len(errors) == 1
    assert "lacks verified protection rules" in errors[0]
