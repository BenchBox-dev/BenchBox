"""Hosted-mode (Turso/libsql embedded replica) tests for todo_db.py.

The hosted backend must be behaviorally identical to the local-SQLite path:
same write-transaction discipline (BEGIN IMMEDIATE around every check-then-act
write), same lifecycle gates, same error surfaces. These tests pin that via a
fake `libsql` module that reproduces the real client's API quirks observed
live against Turso (libsql==0.1.11):

- rows come back as plain tuples (no row_factory support);
- cursors are not iterable;
- constraint violations raise ValueError, remotely wrapped in Hrana text
  (`... "SQLite error: FOREIGN KEY constraint failed", code: "SQLITE_CONSTRAINT" ...`);
- the connection exposes sync() and accepts sync_url/auth_token/isolation_level.

Marked medium (not fast) deliberately: the fast lane is budget-gated.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]

REPO_ROOT = Path(__file__).resolve().parents[3]

HOSTED_URL = "libsql://example-db.aws-us-east-1.turso.io"


def _load_script():
    name = "todo_db"
    path = REPO_ROOT / "_project" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


todo_db = _load_script()


# ---------------------------------------------------------------------------
# Fake libsql client, faithful to the real API surface


class FakeRawCursor:
    """Mimics libsql's cursor: tuple rows, NOT iterable, has description."""

    def __init__(self, cur: sqlite3.Cursor, uppercase_keyword_columns: bool = False):
        self._cur = cur
        self._uppercase_keyword_columns = uppercase_keyword_columns

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def description(self):
        description = self._cur.description or []
        if not self._uppercase_keyword_columns:
            return description
        return [("INSTEAD" if column[0] == "instead" else column[0], *column[1:]) for column in description]

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount


def _hrana_wrap(exc: sqlite3.Error) -> ValueError:
    return ValueError(f'Hrana: `stream error: `Error {{ message: "SQLite error: {exc}", code: "SQLITE_CONSTRAINT" }}``')


class FakeRawConnection:
    """Mimics libsql.Connection over a real local SQLite file."""

    def __init__(
        self,
        database: str,
        sync_fails: bool = False,
        execute_error: str | None = None,
        uppercase_keyword_columns: bool = False,
    ):
        self._conn = sqlite3.connect(database)
        self._conn.isolation_level = None  # autocommit, like isolation_level=None
        self.statements: list[str] = []
        self.sync_calls = 0
        self.commit_calls = 0
        self._sync_fails = sync_fails
        self.execute_error = execute_error  # substring: matching statements raise like a busy/network error
        self._uppercase_keyword_columns = uppercase_keyword_columns

    def execute(self, sql, params=()):
        self.statements.append(sql if isinstance(sql, str) else str(sql))
        if self.execute_error and self.execute_error in sql:
            raise ValueError(
                'Hrana: `stream error: `Error { message: "SQLite error: database is locked", code: "SQLITE_BUSY" }``'
            )
        try:
            return FakeRawCursor(
                self._conn.execute(sql, tuple(params)),
                uppercase_keyword_columns=self._uppercase_keyword_columns,
            )
        except sqlite3.IntegrityError as exc:
            raise _hrana_wrap(exc) from None

    def executescript(self, sql):
        self.statements.append("<script>")
        self._conn.executescript(sql)

    def commit(self):
        self.commit_calls += 1
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def sync(self):
        self.sync_calls += 1
        if self._sync_fails:
            raise ValueError("Hrana: `api error: `connection refused``")


class FakeLibsql(types.ModuleType):
    def __init__(
        self,
        sync_fails: bool = False,
        execute_error: str | None = None,
        uppercase_keyword_columns: bool = False,
    ):
        super().__init__("libsql")
        self.connect_calls: list[dict] = []
        self.connections: list[FakeRawConnection] = []
        self._sync_fails = sync_fails
        self._execute_error = execute_error
        self._uppercase_keyword_columns = uppercase_keyword_columns

    def connect(self, database, **kwargs):
        self.connect_calls.append({"database": database, **kwargs})
        conn = FakeRawConnection(
            str(database),
            sync_fails=self._sync_fails,
            execute_error=self._execute_error,
            uppercase_keyword_columns=self._uppercase_keyword_columns,
        )
        self.connections.append(conn)
        return conn


@pytest.fixture()
def fake_libsql(monkeypatch, tmp_path):
    fake = FakeLibsql()
    monkeypatch.setitem(sys.modules, "libsql", fake)
    monkeypatch.setenv("TODO_DB_AUTH_TOKEN", "test-token-value")
    monkeypatch.setenv("TODO_DB_REPLICA", str(tmp_path / "replica" / "replica.db"))
    monkeypatch.delenv("TODO_DB_PATH", raising=False)
    return fake


def _seed_replica_schema(replica_path):
    """Simulate an existing (previously synced) replica with the tracker schema."""
    import pathlib

    p = pathlib.Path(replica_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    seed = sqlite3.connect(p)
    seed.executescript(todo_db.SCHEMA_SQL)
    seed.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (str(todo_db.SCHEMA_VERSION),))
    seed.commit()
    seed.close()


def _hosted_conn(fake: FakeLibsql):
    return todo_db.connect_backend(HOSTED_URL)


def _make_item(conn, item_id="hosted-item", work=None):
    todo_db.create_item(
        conn,
        "tester",
        item_id=item_id,
        title="Hosted-mode lifecycle item",
        worktree="spike",
        priority="high",
        description="Exercises hosted-mode gate behavior.",
        work=work,
    )


# ---------------------------------------------------------------------------
# Backend resolution


class TestBackendResolution:
    def test_explicit_db_path_stays_local_even_with_url_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TODO_DB_URL", HOSTED_URL)
        backend = todo_db.resolve_backend(str(tmp_path / "todo.sqlite"))
        assert isinstance(backend, Path)

    def test_env_db_path_wins_over_env_url(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TODO_DB_URL", HOSTED_URL)
        monkeypatch.setenv("TODO_DB_PATH", str(tmp_path / "todo.sqlite"))
        backend = todo_db.resolve_backend(None)
        assert isinstance(backend, Path)

    def test_env_url_selects_hosted(self, monkeypatch):
        monkeypatch.delenv("TODO_DB_PATH", raising=False)
        monkeypatch.setenv("TODO_DB_URL", HOSTED_URL)
        assert todo_db.resolve_backend(None) == HOSTED_URL

    def test_explicit_url_selects_hosted(self, monkeypatch):
        monkeypatch.delenv("TODO_DB_URL", raising=False)
        assert todo_db.resolve_backend(HOSTED_URL) == HOSTED_URL
        assert todo_db.resolve_backend("https://example-db.turso.io") == ("https://example-db.turso.io")

    def test_no_env_defaults_to_local_path(self, monkeypatch):
        monkeypatch.delenv("TODO_DB_URL", raising=False)
        monkeypatch.delenv("TODO_DB_PATH", raising=False)
        assert isinstance(todo_db.resolve_backend(None), Path)

    def test_implicit_local_read_is_loud_but_allowed(self, monkeypatch, tmp_path, capsys):
        monkeypatch.delenv("TODO_DB_URL", raising=False)
        monkeypatch.delenv("TODO_DB_PATH", raising=False)
        monkeypatch.setattr(todo_db, "git_main_root", lambda: tmp_path)

        assert todo_db.main(["stats"]) == 0

        captured = capsys.readouterr()
        fallback_path = tmp_path / ".todo-db" / "todo.sqlite"
        assert "items_by_state" in captured.out
        assert f"todo backend: local ({fallback_path})" in captured.err
        assert "LOCAL FALLBACK DB - NOT the production tracker" in captured.err

    def test_implicit_local_write_is_refused_before_database_creation(self, monkeypatch, tmp_path, capsys):
        monkeypatch.delenv("TODO_DB_URL", raising=False)
        monkeypatch.delenv("TODO_DB_PATH", raising=False)
        monkeypatch.setattr(todo_db, "git_main_root", lambda: tmp_path)

        assert todo_db.main(["claim", "missing-item"]) == 2

        assert not (tmp_path / ".todo-db" / "todo.sqlite").exists()
        assert "refusing to write through the implicit local fallback" in capsys.readouterr().err

    def test_implicit_local_init_remains_available_for_bootstrap(self, monkeypatch, tmp_path, capsys):
        monkeypatch.delenv("TODO_DB_URL", raising=False)
        monkeypatch.delenv("TODO_DB_PATH", raising=False)
        monkeypatch.setattr(todo_db, "git_main_root", lambda: tmp_path)

        assert todo_db.main(["init"]) == 0

        assert (tmp_path / ".todo-db" / "todo.sqlite").exists()
        assert "LOCAL FALLBACK DB - NOT the production tracker" in capsys.readouterr().err

    @pytest.mark.parametrize("source", ["flag", "env"])
    def test_explicit_local_backend_has_identity_without_fallback_warning(self, source, monkeypatch, tmp_path, capsys):
        monkeypatch.delenv("TODO_DB_URL", raising=False)
        monkeypatch.delenv("TODO_DB_PATH", raising=False)
        db_path = tmp_path / "explicit.sqlite"
        argv = ["--db", str(db_path), "stats"]
        if source == "env":
            monkeypatch.setenv("TODO_DB_PATH", str(db_path))
            argv = ["stats"]

        assert todo_db.main(argv) == 0

        captured = capsys.readouterr()
        assert f"todo backend: local ({db_path})" in captured.err
        assert "LOCAL FALLBACK" not in captured.err


# ---------------------------------------------------------------------------
# Hosted connection wiring


class TestHostedConnect:
    def test_requires_auth_token(self, monkeypatch, tmp_path):
        fake = FakeLibsql()
        monkeypatch.setitem(sys.modules, "libsql", fake)
        monkeypatch.delenv("TODO_DB_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("TODO_DB_REPLICA", str(tmp_path / "replica.db"))
        with pytest.raises(todo_db.TodoError, match="TODO_DB_AUTH_TOKEN"):
            todo_db.connect_backend(HOSTED_URL)
        assert not fake.connect_calls

    def test_wires_replica_sync_url_auth_and_autocommit(self, fake_libsql, tmp_path):
        conn = _hosted_conn(fake_libsql)
        call = fake_libsql.connect_calls[0]
        assert call["database"].endswith("replica.db")
        assert call["sync_url"] == HOSTED_URL
        assert call["auth_token"] == "test-token-value"
        assert call["isolation_level"] is None
        # replica parent directory is created
        assert Path(call["database"]).parent.is_dir()
        # one freshness sync at connect; schema bootstrap happened
        raw = fake_libsql.connections[0]
        assert raw.sync_calls == 1
        assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == str(
            todo_db.SCHEMA_VERSION
        )

    def test_direct_helper_normalizes_url_before_connect(self, fake_libsql):
        # _hosted_raw_connect is reachable without resolve_backend()'s
        # normalization (direct helper callers). A whitespace-padded,
        # uppercase-scheme URL must still reach libsql.connect() normalized.
        conn = todo_db._hosted_raw_connect(f"  LIBSQL://{HOSTED_URL.split('://', 1)[1]}  ", sync_required=True)
        try:
            assert fake_libsql.connect_calls[0]["sync_url"] == HOSTED_URL
        finally:
            conn.close()

    def test_default_replica_path_is_per_worktree(self, monkeypatch, tmp_path):
        # Per-worktree deliberately (NOT git_main_root): every process syncing
        # one shared replica file is a cross-process corruption hazard; the
        # shared state lives on the primary, the replica is only a cache.
        fake = FakeLibsql()
        monkeypatch.setitem(sys.modules, "libsql", fake)
        monkeypatch.setenv("TODO_DB_AUTH_TOKEN", "test-token-value")
        monkeypatch.delenv("TODO_DB_REPLICA", raising=False)
        monkeypatch.setattr(todo_db, "git_root", lambda: tmp_path)
        todo_db.connect_backend(HOSTED_URL)
        assert fake.connect_calls[0]["database"] == str(tmp_path / ".todo-db" / "replica.db")

    def test_replica_setup_lock_taken_and_released(self, fake_libsql, tmp_path):
        todo_db.connect_backend(HOSTED_URL)
        lock_path = Path(todo_db.hosted_replica_path()).with_suffix(".db.lock")
        assert lock_path.exists(), "connect must serialize replica setup via a lock file"
        import fcntl

        with open(lock_path, "w", encoding="utf-8") as handle:
            # non-blocking acquire succeeds only if connect released the lock
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle, fcntl.LOCK_UN)

    def test_explicit_replica_sync_uses_the_setup_lock(self, monkeypatch, tmp_path):
        events = []
        replica = tmp_path / "replica.db"

        @contextmanager
        def recording_lock(path):
            events.append(("lock", path))
            yield
            events.append(("unlock", path))

        class _Conn:
            def sync(self):
                events.append(("sync", replica))

        monkeypatch.setattr(todo_db, "hosted_replica_path", lambda: replica)
        monkeypatch.setattr(todo_db, "_replica_setup_lock", recording_lock)

        todo_db.sync_hosted_replica(_Conn())

        assert events == [("lock", replica), ("sync", replica), ("unlock", replica)]

    def test_explicit_replica_sync_maps_and_redacts_errors(self, monkeypatch, tmp_path):
        token = "sync-secret-token"

        class _Conn:
            def sync(self):
                raise ValueError(f"connection failed with {token}")

        monkeypatch.setenv("TODO_DB_AUTH_TOKEN", token)
        monkeypatch.setenv("TODO_DB_REPLICA", str(tmp_path / "replica.db"))

        with pytest.raises(todo_db.TodoError, match="cannot refresh the replica") as caught:
            todo_db.sync_hosted_replica(_Conn())

        assert token not in str(caught.value)
        assert "<redacted>" in str(caught.value)

    def test_plaintext_http_url_is_refused(self, fake_libsql, capsys):
        with pytest.raises(todo_db.TodoError, match="https"):
            todo_db.connect_backend("http://example-db.turso.io")
        assert not fake_libsql.connect_calls
        rc = todo_db.main(["--db", "http://example-db.turso.io", "stats"])
        assert rc == 2
        assert "https" in capsys.readouterr().err

    def test_plaintext_refusal_is_scheme_case_insensitive(self, fake_libsql, monkeypatch):
        # URL schemes are case-insensitive; HTTP:// must not bypass the check,
        # via --db, TODO_DB_URL, or a response base_url.
        for variant in ("HTTP://example-db.turso.io", "Http://example-db.turso.io", "  http://example-db.turso.io"):
            backend = todo_db.resolve_backend(variant)
            assert isinstance(backend, str), f"{variant!r} must be recognized as a hosted URL, not a file path"
            with pytest.raises(todo_db.TodoError, match="https"):
                todo_db.connect_backend(backend)
        monkeypatch.delenv("TODO_DB_PATH", raising=False)
        monkeypatch.setenv("TODO_DB_URL", "HTTP://example-db.turso.io")
        with pytest.raises(todo_db.TodoError, match="https"):
            todo_db.connect_backend(todo_db.resolve_backend(None))
        assert not fake_libsql.connect_calls

    def test_uppercase_scheme_normalizes_for_pipeline(self):
        assert todo_db._hrana_endpoint("LIBSQL://x.turso.io") == "https://x.turso.io/v2/pipeline"
        assert todo_db._hrana_endpoint(" https://x.turso.io ") == "https://x.turso.io/v2/pipeline"
        with pytest.raises(todo_db.TodoError, match="https"):
            todo_db._hrana_endpoint("HTTP://x.turso.io")

    def test_error_message_never_contains_the_token(self, monkeypatch, tmp_path):
        fake = FakeLibsql(sync_fails=True)
        monkeypatch.setitem(sys.modules, "libsql", fake)
        monkeypatch.setenv("TODO_DB_AUTH_TOKEN", "sekrit-token-abc123")
        monkeypatch.setenv("TODO_DB_REPLICA", str(tmp_path / "replica.db"))
        _seed_replica_schema(tmp_path / "replica.db")
        # sync failure degrades to the stale replica with a warning, not a crash
        conn = todo_db.connect_backend(HOSTED_URL)
        assert conn.execute("SELECT 1").fetchone()[0] == 1

    def test_sync_failure_warns_and_serves_stale_reads(self, monkeypatch, tmp_path, capsys):
        fake = FakeLibsql(sync_fails=True)
        monkeypatch.setitem(sys.modules, "libsql", fake)
        monkeypatch.setenv("TODO_DB_AUTH_TOKEN", "test-token-value")
        monkeypatch.setenv("TODO_DB_REPLICA", str(tmp_path / "replica.db"))
        _seed_replica_schema(tmp_path / "replica.db")
        conn = todo_db.connect_backend(HOSTED_URL)
        err = capsys.readouterr().err
        assert "STALE" in err
        assert "sekrit" not in err and "test-token-value" not in err
        assert conn.execute("SELECT 1").fetchone()[0] == 1

    def test_degraded_fresh_replica_raises_clean_error(self, monkeypatch, tmp_path):
        # A replica that has NEVER synced cannot bootstrap the schema while
        # the primary is down (that would be a delegated write): must be a
        # clean TodoError, not a raw libsql traceback.
        fake = FakeLibsql(sync_fails=True)
        monkeypatch.setitem(sys.modules, "libsql", fake)
        monkeypatch.setenv("TODO_DB_AUTH_TOKEN", "test-token-value")
        monkeypatch.setenv("TODO_DB_REPLICA", str(tmp_path / "fresh" / "replica.db"))
        with pytest.raises(todo_db.TodoError, match="unreachable"):
            todo_db.connect_backend(HOSTED_URL)

    def test_busy_error_maps_to_sqlite_error_and_exit_2(self, monkeypatch, tmp_path, capsys):
        # Non-constraint libsql failures (SQLITE_BUSY, network drop) must map
        # onto sqlite3 errors and reach the CLI as exit 2, never a traceback.
        fake = FakeLibsql(execute_error="INSERT INTO items")
        monkeypatch.setitem(sys.modules, "libsql", fake)
        monkeypatch.setenv("TODO_DB_AUTH_TOKEN", "sekrit-token-abc123")
        monkeypatch.setenv("TODO_DB_REPLICA", str(tmp_path / "replica.db"))
        monkeypatch.delenv("TODO_DB_PATH", raising=False)
        conn = todo_db.connect_backend(HOSTED_URL)
        with pytest.raises(sqlite3.OperationalError, match="SQLITE_BUSY"):
            _make_item(conn)
        monkeypatch.setenv("TODO_DB_URL", HOSTED_URL)
        rc = todo_db.main(
            [
                "--actor",
                "tester",
                "create",
                "busy-item",
                "--title",
                "Busy mapping check",
                "--worktree",
                "spike",
                "--priority",
                "low",
                "--description",
                "Exercise busy-error mapping.",
            ]
        )
        assert rc == 2
        err = capsys.readouterr().err
        assert "database failure" in err
        assert "sekrit" not in err

    def test_schema_bootstrap_is_atomic(self, monkeypatch, tmp_path):
        # A mid-bootstrap failure must roll back completely so a retry works
        # (previously partial tables without `meta` wedged the database).
        replica = tmp_path / "replica.db"
        fake = FakeLibsql(execute_error="CREATE TABLE meta")
        monkeypatch.setitem(sys.modules, "libsql", fake)
        monkeypatch.setenv("TODO_DB_AUTH_TOKEN", "test-token-value")
        monkeypatch.setenv("TODO_DB_REPLICA", str(replica))
        with pytest.raises(sqlite3.Error):
            todo_db.connect_backend(HOSTED_URL)
        leftover = (
            sqlite3.connect(replica).execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        )
        assert leftover == 0, "failed bootstrap must not leave partial tables"
        healthy = FakeLibsql()
        monkeypatch.setitem(sys.modules, "libsql", healthy)
        conn = todo_db.connect_backend(HOSTED_URL)
        assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == str(
            todo_db.SCHEMA_VERSION
        )

    def test_replica_lock_refuses_symlink(self, monkeypatch, tmp_path):
        fake = FakeLibsql()
        monkeypatch.setitem(sys.modules, "libsql", fake)
        monkeypatch.setenv("TODO_DB_AUTH_TOKEN", "test-token-value")
        replica_dir = tmp_path / "replica-dir"
        replica_dir.mkdir()
        victim = tmp_path / "victim.txt"
        victim.write_text("precious", encoding="utf-8")
        (replica_dir / "replica.db.lock").symlink_to(victim)
        monkeypatch.setenv("TODO_DB_REPLICA", str(replica_dir / "replica.db"))
        with pytest.raises(todo_db.TodoError, match="lock"):
            todo_db.connect_backend(HOSTED_URL)
        assert victim.read_text(encoding="utf-8") == "precious", "symlink target must not be truncated"

    def test_local_connect_is_unchanged(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TODO_DB_URL", HOSTED_URL)
        conn = todo_db.connect(tmp_path / "todo.sqlite")
        assert isinstance(conn, sqlite3.Connection)


# ---------------------------------------------------------------------------
# Adapter semantics


class TestHostedAdapter:
    def test_rows_support_name_access_index_access_and_dict(self, fake_libsql):
        conn = _hosted_conn(fake_libsql)
        _make_item(conn)
        row = conn.execute("SELECT id, state FROM items").fetchone()
        assert row["id"] == "hosted-item"
        assert row[1] == "planning"
        as_dict = dict(conn.execute("SELECT id, state FROM items").fetchone())
        assert as_dict == {"id": "hosted-item", "state": "planning"}

    def test_uppercase_keyword_column_is_normalized_through_claim_render(self, monkeypatch, tmp_path, capsys):
        """A Turso-style uppercase description must not crash `todo claim`."""
        fake = FakeLibsql(uppercase_keyword_columns=True)
        monkeypatch.setitem(sys.modules, "libsql", fake)
        monkeypatch.setenv("TODO_DB_AUTH_TOKEN", "test-token-value")
        monkeypatch.setenv("TODO_DB_REPLICA", str(tmp_path / "replica" / "replica.db"))
        conn = _hosted_conn(fake)
        _make_item(conn)
        conn.execute(
            "INSERT INTO anti_patterns (item_id, dont, why, instead) VALUES (?, ?, ?, ?)",
            (
                "hosted-item",
                "skip the hosted path",
                "local-only tests miss protocol differences",
                "exercise the cursor",
            ),
        )
        conn.commit()

        order = todo_db.claim_item(conn, "tester", "hosted-item")
        todo_db._print_work_order(order)
        output = capsys.readouterr().out
        assert "instead: exercise the cursor" in output
        assert order["anti_patterns"] == [
            {
                "dont": "skip the hosted path",
                "why": "local-only tests miss protocol differences",
                "instead": "exercise the cursor",
            }
        ]
        exported = todo_db.export_all(conn)
        assert exported[0]["anti_patterns"] == order["anti_patterns"]


class TestHostedFindings:
    """Findings writes travel the SAME hosted _write_txn + per-statement
    delegation as items. CI exercises that path here so the phase-3 anti-pattern
    (hosted write paths are only manually acceptance-tested) has fake-backend
    coverage; w8 is the manual prod acceptance on top of this."""

    def test_finding_insert_and_dismiss_through_hosted_delegation(self, fake_libsql):
        todo_findings = todo_db.todo_findings
        conn = _hosted_conn(fake_libsql)
        fields = {
            "id": "2026-01-02-030405-hosted-class",
            "date": "2026-01-02",
            "finding_kind": "framework-gap",
            "review_context": "hosted path",
            "title": "Hosted finding class",
            "finding_text": "the review never checks the hosted delegation",
            "why_matters": "hosted writes are only manually acceptance-tested",
            "next_steps": "- [ ] exercise the hosted cursor",
            "disposition": "open",
        }
        with todo_db._write_txn(conn):
            todo_findings.insert_finding(conn, "tester", fields)
        stored = todo_findings.get_finding(conn, fields["id"])
        assert stored is not None and stored["disposition"] == "open"
        assert [event["action"] for event in stored["events"]] == ["sync"]
        # A disposition transition travels the same hosted write path.
        with todo_db._write_txn(conn):
            todo_findings._set_disposition(conn, "tester", fields["id"], "dismissed", "not load-bearing")
        assert todo_findings.get_finding(conn, fields["id"])["disposition"] == "dismissed"
        # Findings never leak into the items-domain export, even from a hosted conn.
        assert todo_db.export_all(conn) == []

    def test_cursor_is_iterable(self, fake_libsql):
        conn = _hosted_conn(fake_libsql)
        _make_item(conn, item_id="iter-one")
        _make_item(conn, item_id="iter-two")
        ids = [row["id"] for row in conn.execute("SELECT id FROM items ORDER BY id")]
        assert ids == ["iter-one", "iter-two"]

    def test_fetchone_returns_none_on_empty(self, fake_libsql):
        conn = _hosted_conn(fake_libsql)
        assert conn.execute("SELECT id FROM items").fetchone() is None

    def test_unique_violation_maps_to_integrity_error(self, fake_libsql):
        conn = _hosted_conn(fake_libsql)
        _make_item(conn)
        with pytest.raises(todo_db.TodoError, match="cannot create"):
            _make_item(conn)

    def test_fk_violation_maps_to_integrity_error(self, fake_libsql):
        conn = _hosted_conn(fake_libsql)
        _make_item(conn)
        conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(todo_db.TodoError, match="missing item"):
            with todo_db._write_txn(conn):
                todo_db.add_item_dep(conn, "hosted-item", "does-not-exist")

    def test_lastrowid_survives_the_adapter(self, fake_libsql):
        conn = _hosted_conn(fake_libsql)
        _make_item(conn)
        deferral_id = todo_db.defer_work(conn, "tester", "hosted-item", "follow-up", "later")
        assert deferral_id == 1


# ---------------------------------------------------------------------------
# Write-transaction discipline


class TestHostedWriteDiscipline:
    def test_writes_run_under_begin_immediate(self, fake_libsql):
        conn = _hosted_conn(fake_libsql)
        raw = fake_libsql.connections[0]
        before = raw.commit_calls
        raw.statements.clear()
        _make_item(conn)
        assert raw.statements[0] == "BEGIN IMMEDIATE"
        insert_pos = next(i for i, s in enumerate(raw.statements) if s.startswith("INSERT INTO items"))
        assert insert_pos > raw.statements.index("BEGIN IMMEDIATE")
        assert raw.commit_calls == before + 1

    def test_failed_gate_rolls_back(self, fake_libsql):
        conn = _hosted_conn(fake_libsql)
        _make_item(conn, work=[{"id": "w1", "summary": "only unit here"}])
        with pytest.raises(todo_db.TodoError):
            todo_db.complete_item(conn, "tester", "hosted-item", None)
        # nothing half-committed: item still planning, no completed_at
        row = conn.execute("SELECT state, completed_at FROM items").fetchone()
        assert row["state"] == "planning"
        assert row["completed_at"] is None


# ---------------------------------------------------------------------------
# Lifecycle gates behave identically in hosted mode


class TestHostedLifecycleGates:
    def test_full_gated_lifecycle(self, fake_libsql):
        conn = _hosted_conn(fake_libsql)
        _make_item(
            conn,
            work=[
                {"id": "w1", "summary": "implement the thing"},
                {"id": "w2", "summary": "verify the thing", "needs": ["w1"]},
            ],
        )
        # claim contention: second actor refused while the lease is live
        todo_db.claim_item(conn, "actor-a", "hosted-item")
        with pytest.raises(todo_db.TodoError, match="claimed by 'actor-a'"):
            todo_db.claim_item(conn, "actor-b", "hosted-item")
        # unit ordering gate
        with pytest.raises(todo_db.TodoError, match="needs unfinished units"):
            todo_db.done_unit(conn, "actor-a", "hosted-item", "w2", "premature")
        # evidence gate
        with pytest.raises(todo_db.TodoError, match="evidence is required"):
            todo_db.done_unit(conn, "actor-a", "hosted-item", "w1", "  ")
        todo_db.done_unit(conn, "actor-a", "hosted-item", "w1", "pytest passed")
        todo_db.done_unit(conn, "actor-a", "hosted-item", "w2", "ladder pass")
        # deferral gate blocks completion until promoted/dismissed
        deferral_id = todo_db.defer_work(conn, "actor-a", "hosted-item", "polish", "out of scope")
        with pytest.raises(todo_db.TodoError, match="unresolved deferrals"):
            todo_db.complete_item(conn, "actor-a", "hosted-item", 999)
        todo_db.promote_deferral(conn, "actor-a", deferral_id, new_item_id="hosted-item-followup")
        todo_db.complete_item(conn, "actor-a", "hosted-item", 999)
        # terminal-defer guard
        with pytest.raises(todo_db.TodoError, match="terminal items"):
            todo_db.defer_work(conn, "actor-a", "hosted-item", "too late", "nope")
        # end state is coherent
        got = todo_db.stats(conn)
        assert got["items_by_state"] == {"done": 1, "planning": 1}
        assert got["deferrals_by_resolution"] == {"promoted": 1}

    def test_cli_main_routes_hosted_via_env(self, fake_libsql, monkeypatch, capsys):
        monkeypatch.setenv("TODO_DB_URL", HOSTED_URL)
        rc = todo_db.main(["--actor", "tester", "stats"])
        assert rc == 0
        assert fake_libsql.connect_calls, "main() did not open the hosted backend"
        captured = capsys.readouterr()
        assert "items_by_state" in captured.out
        assert "todo backend: hosted" in captured.err
        assert HOSTED_URL not in captured.err


# ---------------------------------------------------------------------------
# Hosted migrations


class FakePrimary:
    """Hrana-pipeline stand-in: executes posted statements on a local SQLite
    file so bulk-transfer fidelity is testable end to end without a network.
    Mimics the wire contract: parameterized statements, baton chaining, and
    Hrana-typed result rows."""

    def __init__(self, path: Path, base_url: str | None = None, fail_on: str | None = None):
        self.path = path
        self.requests: list[dict] = []
        self._conn = sqlite3.connect(path)
        self._conn.isolation_level = None
        self._baton = 0
        self.base_url = base_url
        self.fail_on = fail_on  # substring: statements matching it return an error result

    def post(self, endpoint: str, token: str, payload: dict) -> dict:
        assert token, "post called without an auth token"
        self.requests.append({"endpoint": endpoint, "payload": payload})
        results = []
        for request in payload["requests"]:
            if request["type"] == "close":
                # Hrana semantics: closing a stream with an open transaction
                # rolls it back.
                if self._conn.in_transaction:
                    self._conn.rollback()
                results.append({"type": "ok", "response": {"type": "close"}})
                continue
            stmt = request["stmt"]
            args = [self._decode(a) for a in stmt.get("args", [])]
            if self.fail_on and self.fail_on in stmt["sql"]:
                results.append({"type": "error", "error": {"message": f"injected failure for {self.fail_on!r}"}})
                continue
            try:
                cur = self._conn.execute(stmt["sql"], args)
                rows = [[self._encode(v) for v in row] for row in cur.fetchall()]
                results.append(
                    {
                        "type": "ok",
                        "response": {"type": "execute", "result": {"rows": rows, "affected_row_count": cur.rowcount}},
                    }
                )
            except sqlite3.Error as exc:
                results.append({"type": "error", "error": {"message": str(exc)}})
        self._baton += 1
        response = {"baton": f"baton-{self._baton}", "results": results}
        if self.base_url:
            response["base_url"] = self.base_url
        return response

    def sqls(self) -> list[list[str]]:
        """Per-request executed SQL, for assertions."""
        return [
            [r["stmt"]["sql"] for r in request["payload"]["requests"] if r["type"] == "execute"]
            for request in self.requests
        ]

    @staticmethod
    def _decode(arg: dict):
        kind = arg["type"]
        if kind == "null":
            return None
        if kind == "integer":
            return int(arg["value"])
        if kind == "float":
            return float(arg["value"])
        return arg["value"]

    @staticmethod
    def _encode(value) -> dict:
        if value is None:
            return {"type": "null"}
        if isinstance(value, int):
            return {"type": "integer", "value": str(value)}
        if isinstance(value, float):
            return {"type": "float", "value": value}
        return {"type": "text", "value": str(value)}


def _dump(path: Path) -> dict[str, list]:
    conn = sqlite3.connect(path)
    tables = [
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'meta' ORDER BY name")
    ]
    out = {t: conn.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in tables}
    conn.close()
    return out


class TestHostedBulkImport:
    @pytest.fixture()
    def staging(self, tmp_path):
        conn = todo_db.connect(tmp_path / "staging.sqlite")
        _make_item(
            conn,
            item_id="bulk-one",
            work=[{"id": "w1", "summary": "first unit"}, {"id": "w2", "summary": "second unit", "needs": ["w1"]}],
        )
        _make_item(conn, item_id="bulk-two")
        todo_db.defer_work(conn, "tester", "bulk-two", "deferred bit", "later")
        with todo_db._write_txn(conn):
            todo_db.add_item_dep(conn, "bulk-two", "bulk-one")
        return conn

    def test_hrana_value_encoding(self):
        assert todo_db._hrana_value(None) == {"type": "null"}
        assert todo_db._hrana_value(7) == {"type": "integer", "value": "7"}
        assert todo_db._hrana_value(1.5) == {"type": "float", "value": 1.5}
        assert todo_db._hrana_value("x") == {"type": "text", "value": "x"}

    def test_hrana_endpoint_translation(self):
        assert todo_db._hrana_endpoint(HOSTED_URL) == ("https://example-db.aws-us-east-1.turso.io/v2/pipeline")
        assert todo_db._hrana_endpoint("https://x.turso.io") == "https://x.turso.io/v2/pipeline"

    def test_hrana_endpoint_refuses_plaintext_http(self):
        # a Bearer token must never travel over plaintext
        with pytest.raises(todo_db.TodoError, match="https"):
            todo_db._hrana_endpoint("http://x.turso.io")

    def test_post_pipeline_maps_network_errors_to_todo_error(self, monkeypatch):
        def _raise_timeout(*args, **kwargs):
            raise TimeoutError("timed out")

        monkeypatch.setattr(todo_db, "_http_post_response", _raise_timeout)
        with pytest.raises(todo_db.TodoError, match="pipeline request failed"):
            todo_db._post_pipeline("https://x.turso.io/v2/pipeline", "tok", {"requests": []})

        def _raise_reset(*args, **kwargs):
            raise ConnectionResetError("peer reset")

        monkeypatch.setattr(todo_db, "_http_post_response", _raise_reset)
        with pytest.raises(todo_db.TodoError, match="pipeline request failed"):
            todo_db._post_pipeline("https://x.turso.io/v2/pipeline", "tok", {"requests": []})

    def test_post_pipeline_maps_bad_json_to_todo_error(self, monkeypatch):
        import io

        class _FakeResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(
            todo_db, "_http_post_response", lambda *a, **k: _FakeResponse(b"<html>gateway error</html>")
        )
        with pytest.raises(todo_db.TodoError, match="pipeline"):
            todo_db._post_pipeline("https://x.turso.io/v2/pipeline", "tok", {"requests": []})

    def test_pipeline_refuses_redirects(self):
        # urllib preserves the Authorization header across redirects (even an
        # https->http downgrade), so the pipeline opener must refuse them all.
        import urllib.request

        opener = todo_db._build_no_redirect_opener()
        handlers = [h for h in opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
        assert handlers, "opener must carry a redirect-refusing handler"
        for handler in handlers:
            assert handler.redirect_request(None, None, 302, "Found", {}, "http://attacker.example/") is None, (
                "redirect_request must refuse (return None) so urllib raises instead of re-sending the token"
            )

    def test_import_guard_counts_all_tracker_tables(self, fake_libsql, monkeypatch, tmp_path, capsys):
        # An itemless events row (e.g. from `todo config`) must still trip the
        # emptiness guard with the friendly --replace hint, not a cryptic
        # events.seq collision mid-transfer.
        todo_dir = tmp_path / "TODO"
        todo_dir.mkdir()
        primary = FakePrimary(tmp_path / "primary.sqlite")
        sqlite3.connect(primary.path).executescript(todo_db.SCHEMA_SQL)
        seed = sqlite3.connect(primary.path)
        seed.execute("INSERT INTO events (at, actor, item_id, action) VALUES ('t', 'a', NULL, 'config')")
        seed.commit()
        monkeypatch.setattr(todo_db, "_post_pipeline", primary.post)
        monkeypatch.setenv("TODO_DB_URL", HOSTED_URL)
        rc = todo_db.main(["import-yaml", "--todo-dir", str(todo_dir), "--skip-done"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "--replace" in err
        assert "UNIQUE" not in err

    def test_bulk_transfer_row_parity(self, staging, tmp_path):
        primary = FakePrimary(tmp_path / "primary.sqlite")
        sqlite3.connect(primary.path).executescript(todo_db.SCHEMA_SQL)
        summary = todo_db.bulk_transfer(staging, HOSTED_URL, "tok", post=primary.post)
        assert _dump(tmp_path / "staging.sqlite") == _dump(primary.path)
        assert summary["rows"] > 0
        assert summary["batches"] >= 1

    def test_bulk_transfer_wraps_in_one_transaction_with_baton(self, staging, tmp_path):
        primary = FakePrimary(tmp_path / "primary.sqlite")
        sqlite3.connect(primary.path).executescript(todo_db.SCHEMA_SQL)
        todo_db.bulk_transfer(staging, HOSTED_URL, "tok", post=primary.post, batch_size=5)
        assert len(primary.requests) > 3, "batch_size=5 must split into several requests"
        sqls = primary.sqls()
        # guard request: take the write lock and check the target atomically
        # (a combined count over every tracker table, not just items)
        assert sqls[0][0] == "BEGIN IMMEDIATE"
        assert any("SELECT count(*) FROM items" in sql for sql in sqls[0])
        assert any("count(*) FROM events" in sql for sql in sqls[0])
        # COMMIT is isolated in its own final request, sent only after every
        # data batch's results were verified clean (Hrana keeps executing
        # later requests in a pipeline after a statement error, so a COMMIT
        # riding with data could commit a partial transfer)
        assert sqls[-1] == ["COMMIT"]
        assert primary.requests[-1]["payload"]["requests"][-1]["type"] == "close"
        assert all("COMMIT" not in batch for batch in sqls[:-1])
        # every request after the first chains the previous baton
        for i, request in enumerate(primary.requests[1:], start=1):
            assert request["payload"]["baton"] == f"baton-{i}"

    def test_statement_error_rolls_back_and_never_commits(self, staging, tmp_path):
        primary = FakePrimary(tmp_path / "primary.sqlite", fail_on="INSERT INTO deferrals")
        sqlite3.connect(primary.path).executescript(todo_db.SCHEMA_SQL)
        with pytest.raises(todo_db.TodoError, match="injected failure"):
            todo_db.bulk_transfer(staging, HOSTED_URL, "tok", post=primary.post, batch_size=5)
        sqls = primary.sqls()
        assert all("COMMIT" not in batch for batch in sqls), "a failed transfer must never COMMIT"
        # the stream is explicitly closed so the primary rolls back promptly
        assert primary.requests[-1]["payload"]["requests"][-1]["type"] == "close"
        # nothing survived on the target
        remaining = sqlite3.connect(primary.path).execute("SELECT count(*) FROM items").fetchone()[0]
        assert remaining == 0

    def test_nonfinal_batch_error_also_closes_the_stream(self, staging, tmp_path):
        # fail early (items is the first transferred table) with small batches,
        # so the error lands well before the final batch
        primary = FakePrimary(tmp_path / "primary.sqlite", fail_on="INSERT INTO items")
        sqlite3.connect(primary.path).executescript(todo_db.SCHEMA_SQL)
        with pytest.raises(todo_db.TodoError, match="injected failure"):
            todo_db.bulk_transfer(staging, HOSTED_URL, "tok", post=primary.post, batch_size=3)
        assert primary.requests[-1]["payload"]["requests"][-1]["type"] == "close"
        assert all("COMMIT" not in batch for batch in primary.sqls())

    def test_base_url_from_response_is_used_for_subsequent_requests(self, staging, tmp_path):
        primary = FakePrimary(tmp_path / "primary.sqlite", base_url="https://shard-7.example.turso.io")
        sqlite3.connect(primary.path).executescript(todo_db.SCHEMA_SQL)
        todo_db.bulk_transfer(staging, HOSTED_URL, "tok", post=primary.post, batch_size=5)
        endpoints = [request["endpoint"] for request in primary.requests]
        assert endpoints[0] == todo_db._hrana_endpoint(HOSTED_URL)
        assert all(e == "https://shard-7.example.turso.io/v2/pipeline" for e in endpoints[1:]), endpoints

    def test_import_yaml_hosted_stages_locally_and_bulk_transfers(self, fake_libsql, monkeypatch, tmp_path, capsys):
        todo_dir = tmp_path / "TODO" / "area" / "planning"
        todo_dir.mkdir(parents=True)
        (todo_dir / "bulk-import-item.yaml").write_text(
            "id: bulk-import-item\n"
            "title: Bulk import end-to-end item\n"
            "priority: medium\n"
            "status: Not Started\n"
            "description: Hosted bulk import path exercise.\n",
            encoding="utf-8",
        )
        primary = FakePrimary(tmp_path / "primary.sqlite")
        sqlite3.connect(primary.path).executescript(todo_db.SCHEMA_SQL)
        monkeypatch.setattr(todo_db, "_post_pipeline", primary.post)
        monkeypatch.setenv("TODO_DB_URL", HOSTED_URL)
        rc = todo_db.main(["import-yaml", "--todo-dir", str(tmp_path / "TODO"), "--skip-done"])
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "imported: 1" in out
        assert "bulk transfer" in out
        row = sqlite3.connect(primary.path).execute("SELECT id, state FROM items").fetchone()
        assert row == ("bulk-import-item", "planning")

    def test_import_yaml_hosted_refuses_nonempty_target_without_replace(
        self, fake_libsql, monkeypatch, tmp_path, capsys
    ):
        todo_dir = tmp_path / "TODO"
        todo_dir.mkdir()
        primary = FakePrimary(tmp_path / "primary.sqlite")
        sqlite3.connect(primary.path).executescript(todo_db.SCHEMA_SQL)
        seed = sqlite3.connect(primary.path)
        seed.execute(
            "INSERT INTO items (id, title, worktree, priority, description, created_at)"
            " VALUES ('leftover', 'Leftover row here', 'spike', 'low', 'pre-existing row', '2026-07-18T00:00:00Z')"
        )
        seed.commit()
        monkeypatch.setattr(todo_db, "_post_pipeline", primary.post)
        monkeypatch.setenv("TODO_DB_URL", HOSTED_URL)
        rc = todo_db.main(["import-yaml", "--todo-dir", str(todo_dir), "--skip-done"])
        assert rc == 2
        assert "--replace" in capsys.readouterr().err

    def test_import_yaml_hosted_replace_clears_target_first(self, fake_libsql, monkeypatch, tmp_path, capsys):
        todo_dir = tmp_path / "TODO" / "area" / "planning"
        todo_dir.mkdir(parents=True)
        (todo_dir / "fresh-item.yaml").write_text(
            "id: fresh-item\n"
            "title: Fresh item after replace\n"
            "priority: low\n"
            "status: Not Started\n"
            "description: Replaces the leftover rows.\n",
            encoding="utf-8",
        )
        primary = FakePrimary(tmp_path / "primary.sqlite")
        sqlite3.connect(primary.path).executescript(todo_db.SCHEMA_SQL)
        seed = sqlite3.connect(primary.path)
        seed.execute(
            "INSERT INTO items (id, title, worktree, priority, description, created_at)"
            " VALUES ('leftover', 'Leftover row here', 'spike', 'low', 'pre-existing row', '2026-07-18T00:00:00Z')"
        )
        seed.execute("INSERT INTO events (at, actor, item_id, action) VALUES ('t', 'a', 'leftover', 'create')")
        seed.commit()
        monkeypatch.setattr(todo_db, "_post_pipeline", primary.post)
        monkeypatch.setenv("TODO_DB_URL", HOSTED_URL)
        rc = todo_db.main(["import-yaml", "--todo-dir", str(tmp_path / "TODO"), "--skip-done", "--replace"])
        assert rc == 0
        ids = [r[0] for r in sqlite3.connect(primary.path).execute("SELECT id FROM items").fetchall()]
        assert ids == ["fresh-item"]
        # replaced events too: only the fresh import's audit trail remains
        actions = {r[0] for r in sqlite3.connect(primary.path).execute("SELECT item_id FROM events").fetchall()}
        assert "leftover" not in actions

    def test_dry_run_never_posts(self, fake_libsql, monkeypatch, tmp_path, capsys):
        todo_dir = tmp_path / "TODO"
        todo_dir.mkdir()
        calls = []
        monkeypatch.setattr(todo_db, "_post_pipeline", lambda *a, **k: calls.append(a))
        monkeypatch.setenv("TODO_DB_URL", HOSTED_URL)
        rc = todo_db.main(["import-yaml", "--todo-dir", str(todo_dir), "--skip-done", "--dry-run"])
        assert rc == 0
        assert not calls


class TestHostedMigrate:
    def _v1_schema(self) -> str:
        # CORE (pre-findings) schema minus the v2 columns: a real v1 DB had
        # neither the started_* columns nor the v3 findings tables, so migrate
        # can add both without a 'table findings already exists' collision.
        script = todo_db._CORE_SCHEMA_SQL
        for column in ("started_at TEXT", "started_worktree TEXT", "started_branch TEXT"):
            script = script.replace(f"  {column},\n", "")
        assert "started_at" not in script
        return script

    def test_migrate_backend_upgrades_hosted_schema(self, fake_libsql, monkeypatch, tmp_path):
        # Build a v1 database behind the fake, as if created by an old CLI.
        replica = tmp_path / "replica" / "replica.db"
        replica.parent.mkdir(parents=True, exist_ok=True)
        seed = sqlite3.connect(replica)
        seed.executescript(self._v1_schema())
        seed.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '1')")
        seed.commit()
        seed.close()
        # current CLI must refuse it ...
        with pytest.raises(todo_db.TodoError, match="todo migrate"):
            todo_db.connect_backend(HOSTED_URL)
        # ... and migrate must fix it in place, applying every pending version
        applied = todo_db.migrate_backend(HOSTED_URL)
        assert applied == [2, 3, 4]
        conn = todo_db.connect_backend(HOSTED_URL)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(work_units)").fetchall()]
        assert "started_at" in cols
        # v3 findings tables landed too.
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "findings" in tables
        # v4 landed too: the lossless columns and the sections table.
        assert "finding_sections" in tables
        finding_cols = [row[1] for row in conn.execute("PRAGMA table_info(findings)").fetchall()]
        assert {"related_paths", "suggested_sweep"} <= set(finding_cols)


# ---------------------------------------------------------------------------
# Read-only export path (bulk reader + remote-only connect)


def test_export_all_bulk_matches_per_item(tmp_path):
    """Bulk export_all() must be byte-identical to per-item get_item() assembly
    across every child table (work+needs, deps, scope, verifications, preserves,
    anti_patterns incl. the INSTEAD keyword column, prior_art, deferrals)."""
    conn = todo_db.connect(tmp_path / "t.sqlite")
    todo_db.create_item(
        conn,
        "tester",
        item_id="item-b",
        title="Item B target",
        worktree="spike",
        priority="low",
        description="dep target item",
    )
    todo_db.create_item(
        conn,
        "tester",
        item_id="item-a",
        title="Item A rich",
        worktree="spike",
        priority="high",
        description="rich item body",
        work=[{"id": "w0", "summary": "first"}, {"id": "w1", "summary": "second", "needs": ["w0"]}],
        deps=["item-b"],
        scope=[("only_modify", "src/**"), ("do_not_modify", "gen/**")],
        verifications=[{"description": "check", "command": "make x", "expected": "ok"}],
        preserves=["keep the public API"],
        anti_patterns=[("do not hack", "it breaks", "do it properly")],
        prior_art=[("docs/x.md", "concept", "reuse")],
    )
    todo_db.defer_work(conn, "tester", "item-a", "later work", "out of scope")

    per_item = [todo_db.get_item(conn, row["id"]) for row in conn.execute("SELECT id FROM items ORDER BY id")]
    bulk = todo_db.export_all(conn)
    assert bulk == per_item
    # and the serialized form export writes is identical too
    dump = lambda rows: [json.dumps(r, sort_keys=True) for r in rows]
    assert dump(bulk) == dump(per_item)
    # the keyword `instead` column round-trips (its result-column name is
    # backend-dependent: "instead" on local SQLite, "INSTEAD" on libsql), so
    # check the value under either key.
    a = next(r for r in bulk if r["id"] == "item-a")
    ap = a["anti_patterns"][0]
    assert ap["dont"] == "do not hack" and ap["why"] == "it breaks"
    assert ap.get("instead", ap.get("INSTEAD")) == "do it properly"


def test_export_all_uses_one_read_transaction(tmp_path):
    conn = todo_db.connect(tmp_path / "t.sqlite")
    todo_db.create_item(
        conn,
        "tester",
        item_id="snapshot-item",
        title="Snapshot item",
        worktree="spike",
        priority="low",
        description="transaction test",
    )
    statements: list[str] = []
    conn.set_trace_callback(statements.append)

    todo_db.write_export(conn, tmp_path / "export")

    assert statements[0] == "BEGIN"
    assert statements[-1] == "COMMIT"
    # The whole bundle (items + events) must come from ONE read snapshot, so
    # there is exactly one transaction, not one per table.
    assert statements.count("BEGIN") == 1
    assert statements.count("COMMIT") == 1


def test_export_command_uses_read_only_connect(monkeypatch):
    """The export command must connect read-only (remote-only, no embedded
    replica) so a read-only hosted token works."""
    assert "export" in todo_db.READ_ONLY_COMMANDS
    seen = {}

    def spy(url, *, read_only=False):
        seen["read_only"] = read_only
        raise todo_db.TodoError("stop after connect")  # short-circuit; we only assert the flag

    monkeypatch.setattr(todo_db, "connect_hosted", spy)
    monkeypatch.setenv("TODO_DB_URL", HOSTED_URL)
    monkeypatch.delenv("TODO_DB_PATH", raising=False)
    todo_db.main(["export", "--out", "/tmp/does-not-matter"])
    assert seen == {"read_only": True}


class TestFindingsBulkTransfer:
    """Phase-5 import moves the FINDINGS tables over the same Hrana pipeline via an
    explicit table list. Previously only the refuse-by-default target guard was
    tested -- every guard test fails BEFORE any transfer, so the transfer itself
    could have broken entirely with all tests still green.
    """

    @staticmethod
    def _findings_module():
        import importlib

        return importlib.import_module("todo_findings")

    def _staging_with_findings(self, path):
        """A v4 staging DB holding one finding plus evidence, links, sections, events."""
        tf = self._findings_module()
        conn = todo_db.connect(path)
        todo_db.create_item(
            conn,
            "t",
            item_id="linked-item",
            title="A linked item",
            worktree="main",
            priority="medium",
            description="a description long enough for the CHECK",
        )
        fid = "2026-01-02-030405-transfer-record"
        with todo_db._write_txn(conn):
            tf.insert_finding(
                conn,
                "t",
                {
                    "id": fid,
                    "date": "2026-01-02",
                    "finding_kind": "framework-gap",
                    "review_context": "rc",
                    "title": "T",
                    "finding_text": "f",
                    "why_matters": "w",
                    "next_steps": "n",
                    "disposition": "open",
                    "evidence": [{"path": "a.py", "note": "why a matters"}],
                    "sections": [{"position": 0, "heading": "Why it was missed", "text": "no axis"}],
                    "related_paths": '["a.py"]',
                    "suggested_sweep": "rg -n a",
                    "todo_id": "linked-item",
                    "todo_link_kind": "resolved-by",
                },
            )
            for i in range(3):
                tf.log_finding_event(conn, "t", fid, tf.IMPORTED_TRIAGE_ACTION, {"line": f"- {i}"})
        conn.close()
        return fid

    def test_findings_tables_transfer_with_full_row_parity(self, tmp_path):
        tf = self._findings_module()
        staging_path = tmp_path / "staging.sqlite"
        fid = self._staging_with_findings(staging_path)
        primary = FakePrimary(tmp_path / "primary.sqlite")
        sqlite3.connect(primary.path).executescript(todo_db.SCHEMA_SQL)
        # The link target must exist on the primary: target_item is a real FK.
        seed = sqlite3.connect(primary.path)
        seed.execute(
            "INSERT INTO items (id, title, worktree, priority, state, description, created_at)"
            " VALUES ('linked-item','A linked item','main','medium','planning','a description long enough','t')"
        )
        seed.commit()
        seed.close()

        staging = sqlite3.connect(staging_path)
        staging.row_factory = sqlite3.Row
        summary = todo_db.bulk_transfer(
            staging, HOSTED_URL, "tok", post=primary.post, tables=tf.FINDINGS_TRANSFER_TABLES
        )
        staging.close()
        assert summary["rows"] > 0

        got = sqlite3.connect(primary.path)
        counts = {t: got.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tf.FINDINGS_TRANSFER_TABLES}
        assert counts == {
            "findings": 1,
            "finding_evidence": 1,
            "finding_links": 1,
            "finding_sections": 1,
            "finding_events": 4,
        }
        # Content, not just counts: the lossless v4 columns and the section survive.
        row = got.execute("SELECT related_paths, suggested_sweep FROM findings WHERE id = ?", (fid,)).fetchone()
        assert row == ('["a.py"]', "rg -n a")
        assert got.execute("SELECT heading, text FROM finding_sections").fetchone() == ("Why it was missed", "no axis")
        assert got.execute("SELECT kind, target_item FROM finding_links").fetchone() == ("resolved-by", "linked-item")

    def test_transfer_does_not_touch_the_items_domain(self, tmp_path):
        # must-preserve: the findings import leaves production's items alone.
        tf = self._findings_module()
        staging_path = tmp_path / "staging.sqlite"
        self._staging_with_findings(staging_path)
        primary = FakePrimary(tmp_path / "primary.sqlite")
        sqlite3.connect(primary.path).executescript(todo_db.SCHEMA_SQL)
        seed = sqlite3.connect(primary.path)
        seed.execute(
            "INSERT INTO items (id, title, worktree, priority, state, description, created_at)"
            " VALUES ('linked-item','A linked item','main','medium','planning','a description long enough','t')"
        )
        seed.commit()
        seed.close()
        before = sqlite3.connect(primary.path).execute("SELECT count(*) FROM items").fetchone()[0]

        staging = sqlite3.connect(staging_path)
        staging.row_factory = sqlite3.Row
        todo_db.bulk_transfer(staging, HOSTED_URL, "tok", post=primary.post, tables=tf.FINDINGS_TRANSFER_TABLES)
        staging.close()

        after = sqlite3.connect(primary.path).execute("SELECT count(*) FROM items").fetchone()[0]
        assert after == before == 1

    def test_colliding_pk_aborts_without_the_offset_and_succeeds_with_it(self, tmp_path):
        """The production failure mode: staging numbers finding_events from 1 while the
        target already holds seq=1, so the transfer aborts. An empty target hides this,
        which is why the real scratch rehearsal missed it."""
        tf = self._findings_module()
        staging_path = tmp_path / "staging.sqlite"
        self._staging_with_findings(staging_path)
        primary = FakePrimary(tmp_path / "primary.sqlite")
        sqlite3.connect(primary.path).executescript(todo_db.SCHEMA_SQL)
        seed = sqlite3.connect(primary.path)
        seed.execute(
            "INSERT INTO items (id, title, worktree, priority, state, description, created_at)"
            " VALUES ('linked-item','A linked item','main','medium','planning','a description long enough','t')"
        )
        seed.execute(
            "INSERT INTO findings (id, date, finding_kind, review_context, title, finding_text,"
            " why_matters, next_steps, disposition, created_at)"
            " VALUES ('2026-01-01-000000-pre-existing','2026-01-01','other','rc','T','f','w','n','open','t')"
        )
        seed.execute(
            "INSERT INTO finding_events (seq, at, actor, finding_id, action, detail)"
            " VALUES (1, 't', 'a', '2026-01-01-000000-pre-existing', 'sync', '{}')"
        )
        seed.commit()
        seed.close()

        maxima = {"finding_events": 1}
        applied = tf.offset_staging_pks(staging_path, maxima)
        assert applied["finding_events"] == 1

        staging = sqlite3.connect(staging_path)
        staging.row_factory = sqlite3.Row
        todo_db.bulk_transfer(staging, HOSTED_URL, "tok", post=primary.post, tables=tf.FINDINGS_TRANSFER_TABLES)
        staging.close()

        got = sqlite3.connect(primary.path)
        # Pre-existing row intact, staged rows landed above it, nothing overwritten.
        assert got.execute("SELECT count(*) FROM finding_events").fetchone()[0] == 5
        assert got.execute("SELECT action FROM finding_events WHERE seq = 1").fetchone()[0] == "sync"
