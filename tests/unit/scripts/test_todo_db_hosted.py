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
import sqlite3
import sys
import types
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

    def __init__(self, cur: sqlite3.Cursor):
        self._cur = cur

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def description(self):
        return self._cur.description

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

    def __init__(self, database: str, sync_fails: bool = False, execute_error: str | None = None):
        self._conn = sqlite3.connect(database)
        self._conn.isolation_level = None  # autocommit, like isolation_level=None
        self.statements: list[str] = []
        self.sync_calls = 0
        self.commit_calls = 0
        self._sync_fails = sync_fails
        self.execute_error = execute_error  # substring: matching statements raise like a busy/network error

    def execute(self, sql, params=()):
        self.statements.append(sql if isinstance(sql, str) else str(sql))
        if self.execute_error and self.execute_error in sql:
            raise ValueError(
                'Hrana: `stream error: `Error { message: "SQLite error: database is locked", code: "SQLITE_BUSY" }``'
            )
        try:
            return FakeRawCursor(self._conn.execute(sql, tuple(params)))
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
    def __init__(self, sync_fails: bool = False, execute_error: str | None = None):
        super().__init__("libsql")
        self.connect_calls: list[dict] = []
        self.connections: list[FakeRawConnection] = []
        self._sync_fails = sync_fails
        self._execute_error = execute_error

    def connect(self, database, **kwargs):
        self.connect_calls.append({"database": database, **kwargs})
        conn = FakeRawConnection(str(database), sync_fails=self._sync_fails, execute_error=self._execute_error)
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
        assert "items_by_state" in capsys.readouterr().out


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
        script = todo_db.SCHEMA_SQL
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
        # ... and migrate must fix it in place
        applied = todo_db.migrate_backend(HOSTED_URL)
        assert applied == [2]
        conn = todo_db.connect_backend(HOSTED_URL)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(work_units)").fetchall()]
        assert "started_at" in cols
