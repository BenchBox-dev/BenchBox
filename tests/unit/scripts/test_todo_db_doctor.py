"""Guards for `todo doctor` -- the preflight the batch workflow mandates.

The batch contract requires a side-effect-free health check before the first
claim, and HALTS on exit 4 so a dead token cannot desynchronize the tracker from
the work. These pin the parts that contract actually depends on:

  - the command exists and is reachable through the project wrapper (its absence
    was the original capability gap);
  - exit 4 is reserved for AUTH failures and is distinguishable from exit 2
    (unreachable), including the `JWT error: InvalidToken` shape the hosted
    transport really emits;
  - the check is read-only: it makes no tracker write and emits no audit event;
  - neither the DSN nor the token is ever printed.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MODULE_PATH = _REPO_ROOT / "_project" / "scripts" / "todo_db.py"

_spec = importlib.util.spec_from_file_location("todo_db_under_test", _MODULE_PATH)
assert _spec and _spec.loader
todo_db = importlib.util.module_from_spec(_spec)
sys.modules["todo_db_under_test"] = todo_db
_spec.loader.exec_module(todo_db)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

_HOSTED_URL = "libsql://example-doctor.turso.io"
_SECRET = "super-secret-token-value"


@pytest.fixture
def local_db(tmp_path: Path) -> Path:
    db = tmp_path / "todo.sqlite"
    assert todo_db.main(["--db", str(db), "init"]) == 0
    return db


def test_doctor_is_exposed_by_the_wrapper_cli(capsys):
    """The capability gap that started this: `doctor` must be a real subcommand.

    The batch contract mandates this preflight, so its absence from the wrapper
    turned a required gate into one every session recorded as "skipped".
    """
    with pytest.raises(SystemExit) as excinfo:
        todo_db.main(["doctor", "--help"])
    assert excinfo.value.code == 0
    assert "--json" in capsys.readouterr().out


def test_doctor_reports_healthy_local_backend(local_db, capsys):
    assert todo_db.main(["--db", str(local_db), "doctor"]) == todo_db.DOCTOR_EXIT_OK
    out = capsys.readouterr().out
    assert "OK   reachable" in out
    assert f"v{todo_db.SCHEMA_VERSION}" in out


def test_doctor_does_not_create_a_missing_local_database(tmp_path, capsys):
    db = tmp_path / "missing" / "todo.sqlite"

    assert todo_db.main(["--db", str(db), "doctor"]) == todo_db.DOCTOR_EXIT_FAIL

    assert not db.exists()
    assert not db.parent.exists()
    assert "FAIL reachable" in capsys.readouterr().out


def test_doctor_reports_an_existing_schemaless_database_as_a_schema_failure(tmp_path, capsys):
    db = tmp_path / "empty.sqlite"
    db.touch()

    assert todo_db.main(["--db", str(db), "doctor"]) == todo_db.DOCTOR_EXIT_FAIL

    out = capsys.readouterr().out
    assert "OK   reachable" in out
    assert "FAIL schema" in out
    assert "no schema found" in out


@pytest.mark.parametrize(
    ("version", "guidance"),
    [(todo_db.SCHEMA_VERSION - 1, "migrate"), (todo_db.SCHEMA_VERSION + 1, "newer CLI")],
)
def test_read_only_local_connect_rejects_incompatible_schema(local_db, version, guidance):
    conn = sqlite3.connect(local_db)
    try:
        conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(version),))
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(todo_db.TodoError, match=rf"schema_version={version}.*{guidance}"):
        todo_db.connect_backend(local_db, read_only=True)


def test_doctor_json_is_machine_readable(local_db, capsys):
    assert todo_db.main(["--db", str(local_db), "doctor", "--json"]) == todo_db.DOCTOR_EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == todo_db.DOCTOR_EXIT_OK
    names = {c["check"] for c in payload["checks"]}
    assert {"backend", "identity", "auth", "reachable", "schema"} <= names
    assert all(c["status"] in {"OK", "WARN", "FAIL", "SKIP"} for c in payload["checks"])


def test_missing_hosted_token_is_exit_4_not_2(monkeypatch, capsys):
    """A missing token must be the AUTH exit, which is what makes batch HALT."""
    monkeypatch.delenv("TODO_DB_AUTH_TOKEN", raising=False)
    assert todo_db.main(["--db", _HOSTED_URL, "doctor"]) == todo_db.DOCTOR_EXIT_AUTH
    out = capsys.readouterr().out
    assert "FAIL auth" in out
    # Reachability must not be attempted -- one root cause, not two.
    assert "SKIP reachable" in out


def test_rejected_token_is_classified_as_auth_not_a_plain_outage(monkeypatch, capsys):
    """`JWT error: InvalidToken` is the real hosted shape and MUST be exit 4.

    It contains no space in "InvalidToken", so a naive "invalid token" marker
    misses it and returns 2 -- letting a batch keep running against a dead token
    instead of halting. That regression is what this pins.
    """
    monkeypatch.setenv("TODO_DB_AUTH_TOKEN", _SECRET)

    def boom(*_args, **_kwargs):
        raise RuntimeError('Hrana: `api error: `status=400 Bad Request, body={"error":"JWT error: InvalidToken"}``')

    monkeypatch.setattr(todo_db, "connect_backend", boom)
    assert todo_db.main(["--db", _HOSTED_URL, "doctor"]) == todo_db.DOCTOR_EXIT_AUTH
    assert "auth failure" in capsys.readouterr().out


def test_expired_token_is_classified_as_auth(monkeypatch, capsys):
    monkeypatch.setenv("TODO_DB_AUTH_TOKEN", _SECRET)

    def boom(*_args, **_kwargs):
        raise RuntimeError("JWT token has expired")

    monkeypatch.setattr(todo_db, "connect_backend", boom)
    assert todo_db.main(["--db", _HOSTED_URL, "doctor"]) == todo_db.DOCTOR_EXIT_AUTH
    assert "auth failure" in capsys.readouterr().out


def test_expired_tls_certificate_is_a_plain_outage(monkeypatch, capsys):
    monkeypatch.setenv("TODO_DB_AUTH_TOKEN", _SECRET)

    def boom(*_args, **_kwargs):
        raise RuntimeError("TLS certificate has expired")

    monkeypatch.setattr(todo_db, "connect_backend", boom)
    assert todo_db.main(["--db", _HOSTED_URL, "doctor"]) == todo_db.DOCTOR_EXIT_FAIL
    out = capsys.readouterr().out
    assert "FAIL reachable" in out
    assert "auth failure" not in out


def test_plain_outage_is_exit_2_not_auth(monkeypatch, capsys):
    """An unreachable backend must NOT be reported as an auth failure.

    A false auth positive sends the operator to re-mint a token when the database
    is simply down, so the marker set stays narrow.
    """
    monkeypatch.setenv("TODO_DB_AUTH_TOKEN", _SECRET)

    def boom(*_args, **_kwargs):
        raise sqlite3.OperationalError("connection refused")

    monkeypatch.setattr(todo_db, "connect_backend", boom)
    assert todo_db.main(["--db", _HOSTED_URL, "doctor"]) == todo_db.DOCTOR_EXIT_FAIL
    assert "FAIL reachable" in capsys.readouterr().out


def test_doctor_never_prints_the_dsn_or_the_token(monkeypatch, capsys):
    monkeypatch.setenv("TODO_DB_AUTH_TOKEN", _SECRET)

    def boom(*_args, **_kwargs):
        raise RuntimeError(f"connect failed for {_HOSTED_URL} using {_SECRET}")

    monkeypatch.setattr(todo_db, "connect_backend", boom)
    todo_db.main(["--db", _HOSTED_URL, "doctor"])
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert _SECRET not in combined, "doctor leaked the auth token"
    assert _HOSTED_URL not in combined, "doctor leaked the hosted DSN"


def test_doctor_makes_no_tracker_write(local_db):
    """Side-effect-free: no item/event rows, and nothing mutated."""

    def snapshot() -> list[tuple]:
        conn = sqlite3.connect(local_db)
        try:
            conn.row_factory = sqlite3.Row
            return [
                tuple(r)
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            ] + [(conn.execute("SELECT count(*) FROM events").fetchone()[0],)]
        finally:
            conn.close()

    before = snapshot()
    assert todo_db.main(["--db", str(local_db), "doctor"]) == todo_db.DOCTOR_EXIT_OK
    assert snapshot() == before, "doctor mutated the database"


def test_doctor_is_classified_as_a_read_command():
    """It must never be gated as a write, or it could not diagnose a frozen tracker."""
    assert "doctor" in todo_db._IMPLICIT_LOCAL_READ_COMMANDS


def test_implicit_local_fallback_is_warned_not_failed(monkeypatch, tmp_path, capsys):
    """The scratch DB is usable but is NOT the production tracker -- warn, don't fail."""
    monkeypatch.delenv("TODO_DB_PATH", raising=False)
    monkeypatch.delenv("TODO_DB_URL", raising=False)
    db = tmp_path / "fallback.sqlite"
    assert todo_db.main(["--db", str(db), "init"]) == 0

    monkeypatch.setattr(todo_db, "_resolve_backend", lambda _explicit: (db, True, False, None))
    assert todo_db.main(["doctor"]) == todo_db.DOCTOR_EXIT_OK
    assert "WARN identity" in capsys.readouterr().out


def test_config_discovered_url_is_selected_not_implicit(monkeypatch, tmp_path, capsys):
    """Tracked config.json selects hosted; doctor treats it as explicit identity."""
    monkeypatch.delenv("TODO_DB_PATH", raising=False)
    monkeypatch.delenv("TODO_DB_URL", raising=False)
    monkeypatch.delenv("TODO_DB_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(todo_db, "git_main_root", lambda: tmp_path)
    cfg = tmp_path / ".todo-db"
    cfg.mkdir()
    (cfg / "config.json").write_text(json.dumps({"url": _HOSTED_URL}), encoding="utf-8")

    rc = todo_db.main(["doctor"])
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert rc == todo_db.DOCTOR_EXIT_AUTH  # hosted selected, token missing
    assert "WARN identity" not in captured.out
    assert "backend selected explicitly" in captured.out or "OK   identity" in captured.out
    assert "TODO_DB_AUTH_TOKEN is not set" in captured.out
    assert _HOSTED_URL not in combined
    assert _SECRET not in combined


def test_doctor_config_path_never_leaks_url_on_connect_failure(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("TODO_DB_PATH", raising=False)
    monkeypatch.delenv("TODO_DB_URL", raising=False)
    monkeypatch.setenv("TODO_DB_AUTH_TOKEN", _SECRET)
    monkeypatch.setattr(todo_db, "git_main_root", lambda: tmp_path)
    cfg = tmp_path / ".todo-db"
    cfg.mkdir()
    (cfg / "config.json").write_text(json.dumps({"url": _HOSTED_URL}), encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise RuntimeError(f"connect failed for {_HOSTED_URL} using {_SECRET}")

    monkeypatch.setattr(todo_db, "connect_backend", boom)

    rc = todo_db.main(["doctor"])
    combined = "".join(capsys.readouterr())
    assert rc in (todo_db.DOCTOR_EXIT_FAIL, todo_db.DOCTOR_EXIT_AUTH)
    assert _HOSTED_URL not in combined
    assert _SECRET not in combined
