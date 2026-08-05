"""Tests for turso auto-provisioning of the hosted backend.

`_project/scripts/todo_db.py` resolves its backend with precedence
--db > TODO_DB_PATH > TODO_DB_URL > implicit local fallback. When none of the
three explicit knobs are set, it now attempts to auto-provision a hosted
backend via the maintainer's already-logged-in `turso` CLI before falling
back to the local scratch database (see `_try_turso_auto_provision` and
`_resolve_backend`). These tests pin:

  - success mints a URL + token and selects the hosted backend transparently;
  - any failure (turso absent, mint failure) falls through to the existing
    local-fallback behavior, whose write-refusal error now names `turso auth
    login` alongside the existing remediations;
  - auto-provisioning is never attempted when an explicit backend
    (--db/TODO_DB_PATH/TODO_DB_URL) is configured;
  - the minted token and URL are never printed, including through `doctor`.

The repo-wide `conftest.py` autouse fixture forces `shutil.which("turso")` to
report absent by default, so these tests must explicitly opt back in via
their own `shutil.which` monkeypatch wherever they simulate turso being
present.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MODULE_PATH = _REPO_ROOT / "_project" / "scripts" / "todo_db.py"

_spec = importlib.util.spec_from_file_location("todo_db_turso_autoprovision_under_test", _MODULE_PATH)
assert _spec and _spec.loader
todo_db = importlib.util.module_from_spec(_spec)
sys.modules["todo_db_turso_autoprovision_under_test"] = todo_db
_spec.loader.exec_module(todo_db)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

_URL = "libsql://benchbox-todo-test.turso.io"
_TOKEN = "sekrit-mint-token-xyz"  # noqa: S105 - test fixture value, not a real credential


def _make_fake_turso_run(db_name: str = "benchbox-todo", *, url: str = _URL, token: str = _TOKEN):
    """A subprocess.run stand-in that answers `turso db show`/`tokens create`
    for the given db name and delegates every other command (notably `git
    ...`) to the real subprocess.run."""
    real_run = todo_db.subprocess.run
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        if cmd[:1] == ["turso"]:
            if cmd == ["turso", "db", "show", db_name, "--url"]:
                return SimpleNamespace(returncode=0, stdout=f"{url}\n", stderr="")
            if cmd == ["turso", "db", "tokens", "create", db_name, "--expiration", "1d"]:
                return SimpleNamespace(returncode=0, stdout=f"{token}\n", stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="unexpected turso invocation")
        return real_run(cmd, *args, **kwargs)

    return fake_run, calls


def _clear_backend_env(monkeypatch):
    monkeypatch.delenv("TODO_DB_PATH", raising=False)
    monkeypatch.delenv("TODO_DB_URL", raising=False)
    monkeypatch.delenv("TODO_DB_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TODO_DB_TURSO_DB", raising=False)


class TestAutoProvisionSuccess:
    def test_success_selects_hosted_backend_and_propagates_env(self, monkeypatch):
        _clear_backend_env(monkeypatch)
        monkeypatch.setattr(todo_db.shutil, "which", lambda name: "/usr/bin/turso" if name == "turso" else None)
        fake_run, calls = _make_fake_turso_run()
        monkeypatch.setattr(todo_db.subprocess, "run", fake_run)

        backend, implicit_default_local, auto_provisioned = todo_db._resolve_backend(None)

        assert backend == _URL
        assert implicit_default_local is False
        assert auto_provisioned is True
        # Downstream readers (_auth_token(), connect_hosted(), ...) all key off
        # these two env vars -- auto-provisioning must behave exactly as if
        # they had been set explicitly.
        assert os.environ["TODO_DB_URL"] == _URL
        assert os.environ["TODO_DB_AUTH_TOKEN"] == _TOKEN
        assert ["turso", "db", "show", "benchbox-todo", "--url"] in calls
        assert ["turso", "db", "tokens", "create", "benchbox-todo", "--expiration", "1d"] in calls

    def test_custom_db_name_from_env(self, monkeypatch):
        _clear_backend_env(monkeypatch)
        monkeypatch.setenv("TODO_DB_TURSO_DB", "my-custom-db")
        monkeypatch.setattr(todo_db.shutil, "which", lambda name: "/usr/bin/turso" if name == "turso" else None)
        fake_run, calls = _make_fake_turso_run(db_name="my-custom-db")
        monkeypatch.setattr(todo_db.subprocess, "run", fake_run)

        backend, _implicit, auto_provisioned = todo_db._resolve_backend(None)

        assert backend == _URL
        assert auto_provisioned is True
        assert ["turso", "db", "show", "my-custom-db", "--url"] in calls

    def test_report_backend_names_auto_provisioning(self, capsys):
        todo_db._report_backend(_URL, implicit_default_local=False, auto_provisioned=True)
        err = capsys.readouterr().err
        assert "hosted (auto-provisioned via turso CLI)" in err
        assert _URL not in err
        assert _TOKEN not in err


class TestAutoProvisionFailureFallsThrough:
    def test_turso_absent_falls_through_to_local_fallback(self, monkeypatch, tmp_path, capsys):
        _clear_backend_env(monkeypatch)
        monkeypatch.setattr(todo_db, "git_main_root", lambda: tmp_path)
        # shutil.which("turso") already reports absent via the repo-wide
        # autouse fixture; this is asserted explicitly here too.
        assert todo_db.shutil.which("turso") is None

        backend, implicit_default_local, auto_provisioned = todo_db._resolve_backend(None)

        assert isinstance(backend, Path)
        assert implicit_default_local is True
        assert auto_provisioned is False

    def test_turso_present_but_show_fails_falls_through(self, monkeypatch, tmp_path):
        _clear_backend_env(monkeypatch)
        monkeypatch.setattr(todo_db, "git_main_root", lambda: tmp_path)
        monkeypatch.setattr(todo_db.shutil, "which", lambda name: "/usr/bin/turso" if name == "turso" else None)

        def fake_run(cmd, *args, **kwargs):
            if cmd[:1] == ["turso"]:
                return SimpleNamespace(returncode=1, stdout="", stderr="not logged in")
            return todo_db.subprocess.run(cmd, *args, **kwargs)

        monkeypatch.setattr(todo_db.subprocess, "run", fake_run)

        backend, implicit_default_local, auto_provisioned = todo_db._resolve_backend(None)

        assert isinstance(backend, Path)
        assert implicit_default_local is True
        assert auto_provisioned is False

    def test_write_refusal_error_names_turso_auth_login_remediation(self, monkeypatch, tmp_path, capsys):
        _clear_backend_env(monkeypatch)
        monkeypatch.setattr(todo_db, "git_main_root", lambda: tmp_path)

        rc = todo_db.main(["claim", "missing-item"])

        assert rc == 2
        err = capsys.readouterr().err
        assert "refusing to write through the implicit local fallback" in err
        assert "turso auth login" in err
        assert "TODO_DB_URL" in err
        assert "TODO_DB_PATH" in err
        assert not (tmp_path / ".todo-db" / "todo.sqlite").exists()


class TestAutoProvisionNeverInvokedWithExplicitBackend:
    def test_explicit_flag_skips_auto_provision(self, monkeypatch, tmp_path):
        monkeypatch.delenv("TODO_DB_URL", raising=False)

        def boom(*_args, **_kwargs):
            raise AssertionError("auto-provisioning must not run when --db is explicit")

        monkeypatch.setattr(todo_db, "_try_turso_auto_provision", boom)

        backend, implicit_default_local, auto_provisioned = todo_db._resolve_backend(str(tmp_path / "todo.sqlite"))

        assert isinstance(backend, Path)
        assert implicit_default_local is False
        assert auto_provisioned is False

    def test_env_todo_db_path_skips_auto_provision(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TODO_DB_PATH", str(tmp_path / "todo.sqlite"))
        monkeypatch.delenv("TODO_DB_URL", raising=False)

        def boom(*_args, **_kwargs):
            raise AssertionError("auto-provisioning must not run when TODO_DB_PATH is set")

        monkeypatch.setattr(todo_db, "_try_turso_auto_provision", boom)

        backend, implicit_default_local, auto_provisioned = todo_db._resolve_backend(None)

        assert isinstance(backend, Path)
        assert implicit_default_local is False
        assert auto_provisioned is False

    def test_env_todo_db_url_skips_auto_provision(self, monkeypatch):
        monkeypatch.delenv("TODO_DB_PATH", raising=False)
        monkeypatch.setenv("TODO_DB_URL", "libsql://explicit-env.turso.io")
        monkeypatch.setenv("TODO_DB_AUTH_TOKEN", "explicit-env-token")

        def boom(*_args, **_kwargs):
            raise AssertionError("auto-provisioning must not run when TODO_DB_URL is set")

        monkeypatch.setattr(todo_db, "_try_turso_auto_provision", boom)

        backend, implicit_default_local, auto_provisioned = todo_db._resolve_backend(None)

        assert backend == "libsql://explicit-env.turso.io"
        assert implicit_default_local is False
        assert auto_provisioned is False


class TestDoctorRedactsAutoProvisionedSecrets:
    def test_doctor_never_prints_the_auto_provisioned_url_or_token(self, monkeypatch, capsys):
        _clear_backend_env(monkeypatch)
        monkeypatch.setattr(todo_db.shutil, "which", lambda name: "/usr/bin/turso" if name == "turso" else None)
        fake_run, _calls = _make_fake_turso_run()
        monkeypatch.setattr(todo_db.subprocess, "run", fake_run)

        def boom(*_args, **_kwargs):
            raise RuntimeError(f"connect failed for {_URL} using {_TOKEN}")

        monkeypatch.setattr(todo_db, "connect_backend", boom)

        rc = todo_db.main(["doctor"])

        assert rc in (todo_db.DOCTOR_EXIT_FAIL, todo_db.DOCTOR_EXIT_AUTH)
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert _TOKEN not in combined
        assert _URL not in combined
        assert "auto-provisioned" in combined

    def test_doctor_json_never_prints_the_auto_provisioned_url_or_token(self, monkeypatch, capsys):
        _clear_backend_env(monkeypatch)
        monkeypatch.setattr(todo_db.shutil, "which", lambda name: "/usr/bin/turso" if name == "turso" else None)
        fake_run, _calls = _make_fake_turso_run()
        monkeypatch.setattr(todo_db.subprocess, "run", fake_run)

        def boom(*_args, **_kwargs):
            raise RuntimeError(f"connect failed for {_URL} using {_TOKEN}")

        monkeypatch.setattr(todo_db, "connect_backend", boom)

        todo_db.main(["doctor", "--json"])

        combined = "".join(capsys.readouterr())
        assert _TOKEN not in combined
        assert _URL not in combined
