#!/usr/bin/env python3
"""todo_db.py - DB-backed TODO tracker (local SQLite or hosted libsql/Turso).

Implements the G2 gate of _project/specs/todo-db-tracker.md. The CLI is the
only sanctioned write path; every lifecycle invariant lives in code here, not
in skill prose.

Usage:
    uv run --project _project/scripts -- python _project/scripts/todo_db.py <command> ...

Backend selection (first match wins):
- --db PATH_OR_URL          explicit; libsql:// or https:// selects hosted
- TODO_DB_PATH              local SQLite file (also what tests use)
- TODO_DB_URL               hosted libsql database (Turso); requires
                            TODO_DB_AUTH_TOKEN; per-worktree embedded
                            replica at <git root>/.todo-db/replica.db
                            (override: TODO_DB_REPLICA); plaintext
                            http:// is refused
- default                   <git main root>/.todo-db/todo.sqlite (gitignored)

Hosted mode keeps the exact write-transaction discipline of local mode:
BEGIN IMMEDIATE write transactions are delegated statement-by-statement to
the primary, so check-then-act gates serialize against every other writer.
On sync failure, reads degrade to the stale replica with a banner; writes
fail loudly (no offline queue, by design).

Deviations from the spec DDL (recorded in the spec):
- `items.category` column added (nullable) so the importer is lossless.
- scope-rule matching uses fnmatch semantics ('*' crosses '/'); a trailing
  slash explicitly means the named directory and all descendants.
"""

from __future__ import annotations

import argparse
import fnmatch
import getpass
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Make this script's own directory importable so the findings sibling resolves
# whether todo_db runs via `uv run ... todo_db.py` (dir already on sys.path[0])
# or is loaded by file path in tests (spec_from_file_location adds nothing).
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Alias THIS module as "todo_db" so the findings sibling's `import todo_db`
# binds this exact instance instead of re-executing the file under the canonical
# name. Without it, running as __main__ (`python todo_db.py`) or loading under a
# synthetic name in tests would create a SECOND todo_db instance, and a
# TodoError raised inside todo_findings would then be a different class than the
# one main() catches -- a traceback instead of a clean exit 2. setdefault never
# clobbers a genuine prior import of todo_db. Guarded with .get(): a few tests
# exec this file via a loader that does not pre-register the module, so
# sys.modules[__name__] may be absent -- skip the alias there (those paths do
# not cross the findings boundary).
_self_module = sys.modules.get(__name__)
if _self_module is not None:
    sys.modules.setdefault("todo_db", _self_module)

# Sibling module: findings-domain schema + `todo finding` CLI (phase 3). Imported
# here (not lazily) because SCHEMA_SQL and MIGRATIONS below compose its DDL. The
# import cycle (todo_findings imports todo_db) is safe: the alias above keeps it a
# single instance, and todo_findings defines its schema constants before it first
# touches todo_db. See todo_findings.py's header.
import todo_findings  # noqa: E402

SCHEMA_VERSION = 4

# Applied in order by `todo migrate`. v3 lands the findings domain; v4 adds the
# lossless homes for legacy capture fields and makes finding_links.target_item
# DEFERRABLE. Both deltas come from todo_findings, and each version's delta is
# FROZEN once released -- v3's statements must keep producing exactly v3 so a v2
# database can still climb through it. That a migrated database ends up identical
# to a fresh one is pinned by a test rather than by sharing one DDL string, since
# ALTER-based deltas can never be literally the same text as the CREATEs.
MIGRATIONS: dict[int, list[str]] = {
    2: [
        "ALTER TABLE work_units ADD COLUMN started_at TEXT",
        "ALTER TABLE work_units ADD COLUMN started_worktree TEXT",
        "ALTER TABLE work_units ADD COLUMN started_branch TEXT",
    ],
    3: todo_findings.finding_schema_statements(),
    4: todo_findings.finding_migration_v4_statements(),
}

PRIORITIES = ("critical", "high", "medium-high", "medium", "low")
STATES = ("planning", "active", "done", "dropped")
# Legal item-state transitions; everything else is rejected.
TRANSITIONS = {
    ("planning", "active"),
    ("active", "done"),
    ("planning", "dropped"),
    ("active", "dropped"),
}
UNIT_STATUSES = ("pending", "in_progress", "done")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
WID_RE = re.compile(r"^w[0-9]{1,3}$")
DEFAULT_LEASE_TTL_HOURS = 24

_CORE_SCHEMA_SQL = """
CREATE TABLE items (
  id             TEXT PRIMARY KEY,
  title          TEXT NOT NULL CHECK (length(title) BETWEEN 5 AND 200),
  worktree       TEXT NOT NULL,
  priority       TEXT NOT NULL CHECK (priority IN
                   ('critical','high','medium-high','medium','low')),
  state          TEXT NOT NULL DEFAULT 'planning' CHECK (state IN
                   ('planning','active','done','dropped')),
  blocked_reason TEXT,
  category       TEXT,
  description    TEXT NOT NULL CHECK (length(description) >= 10),
  approach       TEXT,
  claimed_by     TEXT,
  claimed_at     TEXT,
  created_at     TEXT NOT NULL,
  completed_at   TEXT,
  completed_pr   INTEGER
);

CREATE TABLE work_units (
  item_id  TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  wid      TEXT NOT NULL CHECK (wid GLOB 'w[0-9]'
             OR wid GLOB 'w[0-9][0-9]'
             OR wid GLOB 'w[0-9][0-9][0-9]'),
  summary  TEXT NOT NULL CHECK (length(summary) BETWEEN 5 AND 200),
  status   TEXT NOT NULL DEFAULT 'pending' CHECK (status IN
             ('pending','in_progress','done')),
  evidence TEXT,
  notes    TEXT,
  started_at TEXT,
  started_worktree TEXT,
  started_branch TEXT,
  PRIMARY KEY (item_id, wid)
);

CREATE TABLE work_needs (
  item_id   TEXT NOT NULL,
  wid       TEXT NOT NULL,
  needs_wid TEXT NOT NULL,
  PRIMARY KEY (item_id, wid, needs_wid),
  FOREIGN KEY (item_id, wid)       REFERENCES work_units(item_id, wid) ON DELETE CASCADE,
  FOREIGN KEY (item_id, needs_wid) REFERENCES work_units(item_id, wid) ON DELETE CASCADE
);

CREATE TABLE item_deps (
  item_id    TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  needs_item TEXT NOT NULL REFERENCES items(id),
  PRIMARY KEY (item_id, needs_item)
);

CREATE TABLE scope_rules (
  item_id   TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  kind      TEXT NOT NULL CHECK (kind IN ('only_modify','do_not_modify')),
  path_glob TEXT NOT NULL,
  PRIMARY KEY (item_id, kind, path_glob)
);

CREATE TABLE verifications (
  item_id     TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  seq         INTEGER NOT NULL,
  description TEXT NOT NULL,
  command     TEXT,
  expected    TEXT,
  last_run    TEXT,
  last_result TEXT CHECK (last_result IN ('pass','fail') OR last_result IS NULL),
  PRIMARY KEY (item_id, seq)
);

CREATE TABLE preserves (
  item_id  TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  behavior TEXT NOT NULL,
  PRIMARY KEY (item_id, behavior)
);

CREATE TABLE anti_patterns (
  item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  dont    TEXT NOT NULL,
  why     TEXT NOT NULL,
  instead TEXT NOT NULL,
  PRIMARY KEY (item_id, dont)
);

CREATE TABLE prior_art (
  item_id  TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  path     TEXT NOT NULL,
  concept  TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('reuse','extend','supersede')),
  PRIMARY KEY (item_id, path, concept)
);

CREATE TABLE deferrals (
  id              INTEGER PRIMARY KEY,
  from_item       TEXT NOT NULL REFERENCES items(id),
  summary         TEXT NOT NULL,
  reason          TEXT NOT NULL,
  resolution      TEXT NOT NULL DEFAULT 'open' CHECK (resolution IN
                    ('open','promoted','dismissed')),
  resolved_item   TEXT REFERENCES items(id),
  resolved_reason TEXT,
  created_at      TEXT NOT NULL
);

CREATE TABLE events (
  seq     INTEGER PRIMARY KEY,
  at      TEXT NOT NULL,
  actor   TEXT NOT NULL,
  item_id TEXT,
  action  TEXT NOT NULL,
  detail  TEXT
);

CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE INDEX idx_items_state ON items(state);
CREATE INDEX idx_deferrals_open ON deferrals(from_item, resolution);
"""

# The full current schema = core (items domain) + findings domain (phase 3). A
# fresh bootstrap runs this; an existing older DB reaches the same schema by
# climbing MIGRATIONS (v3 lands the findings tables, v4 the lossless columns,
# finding_sections, and the DEFERRABLE link FK).
SCHEMA_SQL = _CORE_SCHEMA_SQL + todo_findings.FINDINGS_SCHEMA_SQL


class TodoError(Exception):
    """Lifecycle or validation violation; rendered to stderr, exit 2."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Harness-neutral actor resolution: TODO_ACTOR is the universal override any
# agent harness can set; the session vars cover known harnesses.
ACTOR_ENV_VARS = ("TODO_ACTOR", "CLAUDE_SESSION_ID", "CODEX_SESSION_ID", "AGENT_SESSION_ID")


def default_actor() -> str:
    for var in ACTOR_ENV_VARS:
        value = os.environ.get(var)
        if value:
            return value
    return f"{getpass.getuser()}@{socket.gethostname()}"


# Per-database configuration, stored in `meta`. Convention-flavored lint rules
# are opt-out so the tracker stays generic outside this project.
CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "lint.require_w0_revalidation": ("on", "off"),
    "lint.require_scope_rules": ("on", "off"),
}


def get_config(conn: sqlite3.Connection, key: str) -> str:
    if key not in CONFIG_KEYS:
        raise TodoError(f"unknown config key {key!r}; known: {', '.join(sorted(CONFIG_KEYS))}")
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else "on"


def set_config(conn: sqlite3.Connection, actor: str, key: str, value: str) -> None:
    if key not in CONFIG_KEYS:
        raise TodoError(f"unknown config key {key!r}; known: {', '.join(sorted(CONFIG_KEYS))}")
    if value not in CONFIG_KEYS[key]:
        raise TodoError(f"config {key} accepts 'on' or 'off', got {value!r}")
    with _write_txn(conn):
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
        log_event(conn, actor, None, "config", {"key": key, "value": value})


def git_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return Path.cwd()
    return Path(result.stdout.strip())


def git_main_root() -> Path:
    """Root of the MAIN repository, even when run from a linked worktree.

    All worktrees of a clone must share one tracker database (eval finding:
    per-worktree DBs fragment state into invisible islands), so the default
    DB path resolves through the common git dir, not the worktree root.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return git_root()
    common = Path(result.stdout.strip())
    return common.parent if common.name == ".git" else git_root()


def resolve_db_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("TODO_DB_PATH")
    if env:
        return Path(env)
    return git_main_root() / ".todo-db" / "todo.sqlite"


def _normalize_url(value: str) -> str:
    """Trim whitespace and lowercase the scheme (schemes are case-insensitive
    per RFC 3986, so HTTP:// must not bypass scheme checks)."""
    value = value.strip()
    scheme, sep, rest = value.partition("://")
    return scheme.lower() + sep + rest if sep else value


def _is_hosted_url(value: str) -> bool:
    # http:// is recognized so it can be REJECTED with a clear error at
    # connect time (a Bearer token must never travel over plaintext), rather
    # than silently treated as a local file path.
    return _normalize_url(value).startswith(("libsql://", "https://", "http://"))


def _require_secure_url(url: str) -> str:
    url = _normalize_url(url)
    if url.startswith("http://"):
        raise TodoError(
            "refusing plaintext http:// for the hosted backend (the auth token would"
            " be sent unencrypted); use https:// or libsql://"
        )
    return url


def _resolve_backend(explicit: str | None) -> tuple[Path | str, bool]:
    """Return ``(backend, implicit_default_local)`` using CLI precedence."""
    if explicit:
        return (_normalize_url(explicit) if _is_hosted_url(explicit) else Path(explicit)), False
    env_path = os.environ.get("TODO_DB_PATH")
    if env_path:
        return Path(env_path), False
    env_url = os.environ.get("TODO_DB_URL")
    if env_url:
        return _normalize_url(env_url), False
    return git_main_root() / ".todo-db" / "todo.sqlite", True


def resolve_backend(explicit: str | None) -> Path | str:
    """Pick the backend: --db > TODO_DB_PATH > TODO_DB_URL > local fallback."""
    return _resolve_backend(explicit)[0]


def hosted_replica_path() -> Path:
    """Per-worktree embedded-replica location (override: TODO_DB_REPLICA).

    Deliberately git_root(), not git_main_root(): the replica is a cache of
    the shared primary, and many processes syncing one shared replica file
    concurrently is a corruption hazard. Cross-worktree sharing happens at
    the primary, not the cache.
    """
    env = os.environ.get("TODO_DB_REPLICA")
    return Path(env) if env else git_root() / ".todo-db" / "replica.db"


def _git_location() -> tuple[str | None, str | None]:
    """(worktree toplevel, branch) of the CWD, for resume/recovery stamps."""

    def _out(*args: str) -> str | None:
        result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
        return result.stdout.strip() or None if result.returncode == 0 else None

    return _out("rev-parse", "--show-toplevel"), _out("rev-parse", "--abbrev-ref", "HEAD")


def _schema_statements() -> list[str]:
    # SCHEMA_SQL is our own controlled DDL: no string literals containing ';'.
    return [statement.strip() for statement in SCHEMA_SQL.split(";") if statement.strip()]


def _ensure_schema(conn: sqlite3.Connection) -> None:
    version = _schema_version(conn)
    if version is None:
        # Atomic bootstrap: per-statement inside one write transaction, so a
        # mid-DDL failure (network drop on a hosted primary, a racing
        # first-connect) rolls back completely instead of leaving partial
        # tables without `meta` that wedge every later connect. Not
        # executescript: it auto-commits, and some libsql client builds
        # document it unimplemented.
        with _write_txn(conn):
            if _schema_version(conn) is None:  # re-check under the write lock
                for statement in _schema_statements():
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
        version = _schema_version(conn)
    if version < SCHEMA_VERSION:
        raise TodoError(
            f"database schema_version={version}, CLI expects {SCHEMA_VERSION}; run `todo migrate` to upgrade it"
        )
    elif version > SCHEMA_VERSION:
        raise TodoError(f"database schema_version={version} is newer than this CLI ({SCHEMA_VERSION}); use a newer CLI")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Autocommit mode: every multi-statement write goes through _write_txn,
    # which takes the write lock up front (BEGIN IMMEDIATE) so check-then-act
    # gates cannot race a concurrent writer.
    conn.isolation_level = None
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    _ensure_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# Hosted backend (Turso / libsql embedded replica)
#
# The libsql Python client is close to sqlite3 but not close enough (observed
# live against Turso, libsql==0.1.11): rows are plain tuples with no
# row_factory, cursors are not iterable, and constraint violations surface as
# ValueError (locally "UNIQUE constraint failed: ...", remotely wrapped in
# Hrana text with code SQLITE_CONSTRAINT). The adapter below closes exactly
# those gaps so every code path above runs unchanged on either backend.


class _HostedRow:
    """sqlite3.Row stand-in: index + name access, dict(row) via keys().

    libsql's cursor.description reports column names verbatim from the SQL
    keyword casing that produced them rather than the SELECT-list casing (observed
    live against Turso: the `anti_patterns.instead` column - "instead" being
    a keyword via INSTEAD OF triggers - comes back as "INSTEAD"). sqlite3.Row
    has no such quirk and is case-insensitive on name access besides. Names
    are lowercased at construction so keys()/dict(row) match local sqlite3.Row
    output exactly, and __getitem__ additionally lowercases the lookup key as
    a second line of defense for any future case mismatch.
    """

    __slots__ = ("_names", "_values")

    def __init__(self, names: list[str], values: tuple):
        self._names = [name.lower() for name in names]
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return self._values[self._names.index(key.lower())]
            except ValueError:
                raise IndexError(f"no such column: {key}") from None
        return self._values[key]

    def keys(self) -> list[str]:
        return list(self._names)

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"_HostedRow({dict(zip(self._names, self._values))!r})"


def _map_hosted_error(exc: BaseException) -> sqlite3.Error:
    """Translate libsql's ValueError surface back onto sqlite3 exceptions.

    Constraint violations keep their IntegrityError identity (gates depend on
    it); everything else — SQLITE_BUSY, network drops mid-statement — becomes
    OperationalError so main()'s sqlite3.Error boundary turns it into a clean
    exit 2 instead of a traceback."""
    message = str(exc)
    if "constraint" in message.lower():
        return sqlite3.IntegrityError(message)
    return sqlite3.OperationalError(message)


class _HostedCursor:
    def __init__(self, raw):
        self._raw = raw

    def _wrap(self, values) -> _HostedRow | None:
        if values is None:
            return None
        names = [column[0] for column in (self._raw.description or [])]
        return _HostedRow(names, tuple(values))

    def fetchone(self) -> _HostedRow | None:
        return self._wrap(self._raw.fetchone())

    def fetchall(self) -> list[_HostedRow]:
        return [self._wrap(values) for values in self._raw.fetchall()]

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                return
            yield row

    @property
    def lastrowid(self):
        return self._raw.lastrowid

    @property
    def rowcount(self):
        return self._raw.rowcount


class _HostedConnection:
    """Duck-typed subset of sqlite3.Connection over the libsql client."""

    def __init__(self, raw):
        self._raw = raw
        self.stale = False  # set when the freshness sync at connect failed

    def execute(self, sql: str, params=()) -> _HostedCursor:
        try:
            return _HostedCursor(self._raw.execute(sql, tuple(params)))
        except ValueError as exc:
            raise _map_hosted_error(exc) from exc

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()

    def sync(self) -> None:
        self._raw.sync()


def _redacted(exc: BaseException, secret: str) -> str:
    return str(exc).replace(secret, "<redacted>") if secret else str(exc)


def _auth_token() -> str:
    return os.environ.get("TODO_DB_AUTH_TOKEN") or ""


@contextmanager
def _replica_setup_lock(replica: Path):
    """Serialize replica open+sync across processes of the same worktree.

    libsql's embedded replica does not document concurrent multi-process
    sync safety, so setup is guarded by an advisory flock; it is released
    once the connection is established (post-setup reads are plain SQLite).
    No-op on platforms without fcntl.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover - non-POSIX
        yield
        return
    lock_path = replica.with_suffix(".db.lock")
    try:
        # O_NOFOLLOW: a planted symlink at the lock path must fail loudly,
        # never truncate its target (lock dirs may live on shared hosts).
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError as exc:
        raise TodoError(f"cannot open replica lock {lock_path}: {exc}") from exc
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _import_libsql():
    try:
        import libsql  # deferred: only hosted mode needs it
    except ImportError as exc:
        raise TodoError("hosted tracker requires the `libsql` package; run `uv sync` in _project/scripts") from exc
    return libsql


def _hosted_raw_connect(url: str, sync_required: bool) -> _HostedConnection:
    # Use the normalized return (trimmed whitespace, lowercased scheme) for the
    # actual connect, not just the security check: direct helper callers do not
    # pass through resolve_backend(), so without this a whitespace-padded or
    # uppercase-scheme URL would reach libsql.connect() un-normalized.
    url = _require_secure_url(url)
    token = os.environ.get("TODO_DB_AUTH_TOKEN") or ""
    if not token:
        raise TodoError("hosted tracker: set TODO_DB_AUTH_TOKEN when TODO_DB_URL points at a remote database")
    libsql = _import_libsql()
    replica = hosted_replica_path()
    replica.parent.mkdir(parents=True, exist_ok=True)
    with _replica_setup_lock(replica):
        raw = libsql.connect(str(replica), sync_url=url, auth_token=token, isolation_level=None)
        conn = _HostedConnection(raw)
        try:
            conn.sync()
        except Exception as exc:
            if sync_required:
                raise TodoError(f"hosted tracker: cannot sync with the primary: {_redacted(exc, token)}") from exc
            # Degraded mode per spec: reads serve the stale replica with a banner;
            # writes will fail loudly at the primary (no offline write queue).
            conn.stale = True
            print(
                f"warning: STALE replica — sync with the primary failed ({_redacted(exc, token)}); "
                "reads may be outdated and writes will fail",
                file=sys.stderr,
            )
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _hosted_read_connect(url: str) -> _HostedConnection:
    """Remote-only connection (no embedded replica) for read-only commands.

    Queries go straight to the primary over HTTP, so a read-only auth token
    works and no schema-bootstrap write is ever attempted (a read-only token
    cannot drive embedded-replica sync, which would leave an empty replica and
    trip the bootstrap write). Slower per query than the local replica, so read
    paths that use this must be bulk — see export_all().
    """
    url = _require_secure_url(url)
    token = os.environ.get("TODO_DB_AUTH_TOKEN") or ""
    if not token:
        raise TodoError("hosted tracker: set TODO_DB_AUTH_TOKEN when TODO_DB_URL points at a remote database")
    libsql = _import_libsql()
    return _HostedConnection(libsql.connect(url, auth_token=token))


def connect_hosted(url: str, *, read_only: bool = False) -> _HostedConnection:
    if read_only:
        conn = _hosted_read_connect(url)
        version = _schema_version(conn)
        if version is None:
            conn.close()
            raise TodoError("hosted tracker: no schema found on the primary")
        if version != SCHEMA_VERSION:
            conn.close()
            raise TodoError(
                f"database schema_version={version}, CLI expects {SCHEMA_VERSION}; run `todo migrate` to upgrade it"
            )
        return conn
    conn = _hosted_raw_connect(url, sync_required=False)
    if conn.stale and _schema_version(conn) is None:
        # A never-synced replica cannot bootstrap the schema while the
        # primary is down — that would be a delegated write. Fail cleanly.
        conn.close()
        raise TodoError(
            "hosted tracker: the primary is unreachable and this worktree's replica"
            " has no schema yet; retry when the network is back"
        )
    _ensure_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# Hosted bulk transfer (Hrana pipeline)
#
# Interactive write transactions round-trip per statement (~0.15s RTT), which
# is correct for CLI-scale writes but hopeless for the one-shot YAML import:
# measured live, the row-by-row path ran at ~10 items/min (≈2.5h for the full
# tree). The importer therefore stages into a temp local SQLite through the
# exact same gated code, then bulk-copies rows to the primary with batched
# parameterized statements over the Hrana HTTP pipeline — one round-trip per
# few hundred statements, all inside a single baton-chained transaction.

# Insert order respects foreign keys; DELETE (--replace) runs in reverse.
TRANSFER_TABLES = (
    "items",
    "work_units",
    "work_needs",
    "item_deps",
    "scope_rules",
    "verifications",
    "preserves",
    "anti_patterns",
    "prior_art",
    "deferrals",
    "events",
)

# Tables whose data is written to the repo-committed export snapshot
# (_project/todo-db-export/, via write_export). This is deliberately the ITEMS
# DOMAIN ONLY -- a *subset* of the full backup/restore scope (TRANSFER_TABLES),
# maintained as an INDEPENDENT literal, not derived from TRANSFER_TABLES, so
# adding a table to the backup scope never silently widens what gets committed.
# It exists so the version-controlled provenance snapshot can never carry a
# table that must not be committed -- notably any findings-domain table, whose
# review prose is deliberately not version-controlled and travels via the CI
# artifact channel only (see _project/specs/findings-domain.md, "Export
# boundary"). The pinning test
# (tests/unit/scripts/test_todo_db_export_allowlist.py) asserts the export
# covers exactly this set, so any `finding%` table fails CLOSED by
# construction: the exporter never reads it, and it cannot be added to this
# allowlist without the test rejecting the finding-prefixed name.
EXPORT_TABLE_ALLOWLIST = frozenset(
    {
        "items",
        "work_units",
        "work_needs",
        "item_deps",
        "scope_rules",
        "verifications",
        "preserves",
        "anti_patterns",
        "prior_art",
        "deferrals",
        "events",
    }
)

# The item-nested part of the committed export (items + its child tables,
# assembled by _export_all_unlocked into items.jsonl). `events` is committed
# separately (events.jsonl) because config-scoped events carry item_id = NULL
# and do not nest under any item. Together these must exhaust
# EXPORT_TABLE_ALLOWLIST -- asserted in write_export so drift between the
# exporter's coverage and the allowlist fails loudly instead of silently
# dropping or leaking a table.
_ITEM_NESTED_EXPORT_TABLES = frozenset(
    {
        "items",
        "work_units",
        "work_needs",
        "item_deps",
        "scope_rules",
        "verifications",
        "preserves",
        "anti_patterns",
        "prior_art",
        "deferrals",
    }
)


def _hrana_endpoint(url: str) -> str:
    url = _require_secure_url(url)
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://") :]
    return url.rstrip("/") + "/v2/pipeline"


def _hrana_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, int):  # covers bool
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, (bytes, bytearray)):
        import base64

        return {"type": "blob", "base64": base64.b64encode(bytes(value)).decode("ascii")}
    return {"type": "text", "value": str(value)}


def _build_no_redirect_opener():
    """Opener that refuses ALL redirects: urllib preserves the Authorization
    header across them (even an https->http downgrade), so following one
    would replay the Bearer token at a response-chosen URL."""
    import urllib.request

    class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    return urllib.request.build_opener(_RefuseRedirects)


_HTTP_OPENER = None


def _http_post_response(request, timeout: float):
    global _HTTP_OPENER
    if _HTTP_OPENER is None:
        _HTTP_OPENER = _build_no_redirect_opener()
    return _HTTP_OPENER.open(request, timeout=timeout)


def _post_pipeline(endpoint: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    import http.client
    import urllib.request

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with _http_post_response(request, timeout=60) as response:
            body = response.read()
    # OSError covers URLError, TimeoutError/socket.timeout, and connection
    # resets; HTTPException covers mid-response protocol failures. All must
    # surface as TodoError so the CLI exits 2 instead of tracebacking.
    except (OSError, http.client.HTTPException) as exc:
        raise TodoError(f"hosted pipeline request failed: {_redacted(exc, token)}") from exc
    try:
        return json.loads(body)
    except ValueError as exc:
        raise TodoError(f"hosted pipeline returned a non-JSON response: {_redacted(exc, token)}") from exc


def _pipeline_execute(
    url: str,
    token: str,
    stmts: list[tuple[str, list[Any]]],
    *,
    stream: dict[str, Any] | None = None,
    close: bool = False,
    post=None,
) -> dict[str, Any]:
    """Run one pipeline request; `stream` carries baton + base_url between
    requests on the same Hrana stream (the spec allows the server to move a
    stream to another host via base_url)."""
    post = post or _post_pipeline
    requests_payload: list[dict[str, Any]] = [
        {"type": "execute", "stmt": {"sql": sql, "args": [_hrana_value(arg) for arg in args]}} for sql, args in stmts
    ]
    if close:
        requests_payload.append({"type": "close"})
    baton = stream.get("baton") if stream else None
    base = (stream.get("base_url") if stream else None) or url
    response = post(_hrana_endpoint(base), token, {"baton": baton, "requests": requests_payload})
    # Update stream state BEFORE scanning for errors so a cleanup close after
    # a raise still targets the right stream on the right host.
    if stream is not None:
        stream["baton"] = response.get("baton")
        if response.get("base_url"):
            stream["base_url"] = response["base_url"]
    for result in response.get("results", []):
        if result.get("type") == "error":
            message = result.get("error", {}).get("message", "unknown error")
            raise TodoError(f"hosted pipeline error: {message}")
    return response


def bulk_transfer(
    staging: sqlite3.Connection,
    url: str,
    token: str,
    *,
    replace: bool = False,
    require_empty: bool = False,
    post=None,
    batch_size: int = 400,
    tables: tuple[str, ...] | None = None,
) -> dict[str, int]:
    """Copy all tracker rows from a staged local database to the primary,
    atomically, in one baton-chained transaction.

    Failure discipline (Hrana keeps executing later requests in a pipeline
    after a statement error, and SQLite statement errors do not abort the
    transaction): COMMIT is sent alone, in its own final request, only after
    every data batch's results came back clean; on any error the stream is
    explicitly closed, which rolls the whole transfer back. The
    `require_empty` guard runs inside the same BEGIN IMMEDIATE transaction,
    so no other writer can populate the target between check and transfer.
    """
    # `tables` lets a caller move a DIFFERENT table set over the same pipeline --
    # the findings domain uses it for the phase-5 import. It deliberately does NOT
    # widen TRANSFER_TABLES or EXPORT_TABLE_ALLOWLIST: the committed export stays
    # items-domain only, and the phase-2 pinning test still fails closed on any
    # `finding%` table. Insert order must respect foreign keys; DELETE runs reversed.
    transfer_tables = TRANSFER_TABLES if tables is None else tuple(tables)
    stmts: list[tuple[str, list[Any]]] = []
    if replace:
        for table in reversed(transfer_tables):
            stmts.append((f"DELETE FROM {table}", []))
    rows_total = 0
    for table in transfer_tables:
        columns = [row["name"] for row in staging.execute(f"PRAGMA table_info({table})")]
        insert = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})"
        for row in staging.execute(f"SELECT {', '.join(columns)} FROM {table}"):
            stmts.append((insert, list(row)))
            rows_total += 1
    batches = [stmts[i : i + batch_size] for i in range(0, len(stmts), batch_size)]
    stream: dict[str, Any] = {"baton": None, "base_url": None}

    def _close_stream() -> None:
        try:
            _pipeline_execute(url, token, [], stream=stream, close=True, post=post)
        except Exception:  # best effort; the server also rolls back on stream timeout
            pass

    try:
        total_sql = "SELECT " + " + ".join(f"(SELECT count(*) FROM {table})" for table in transfer_tables)
        guard = _pipeline_execute(
            url,
            token,
            [("BEGIN IMMEDIATE", []), (total_sql, [])],
            stream=stream,
            post=post,
        )
        # Counts EVERY transfer table, not just items: an itemless events row
        # (e.g. from `todo config`) would otherwise pass the guard and abort
        # mid-transfer on an events.seq collision with a cryptic error.
        existing = int(guard["results"][1]["response"]["result"]["rows"][0][0]["value"])
        if existing and require_empty:
            raise TodoError(
                f"hosted database is not empty ({existing} tracker row(s));"
                " rerun with --replace to clear the tracker tables and re-import"
            )
        for batch in batches:
            _pipeline_execute(url, token, batch, stream=stream, post=post)
        _pipeline_execute(url, token, [("COMMIT", [])], stream=stream, close=True, post=post)
    except BaseException:
        _close_stream()
        raise
    return {"rows": rows_total, "batches": len(batches) + 2}


# Commands that only read: connected remote-only (no embedded replica) so a
# read-only hosted token works. Kept minimal — `export` is the automated
# read-only-token consumer and its reader is bulk; interactive reads keep the
# fast embedded replica (which needs a read-write token anyway).
READ_ONLY_COMMANDS = frozenset({"export"})

_IMPLICIT_LOCAL_READ_COMMANDS = frozenset({"check-scope", "deps", "export", "lint", "list", "ready", "show", "stats"})


def _command_mutates_tracker(args: argparse.Namespace) -> bool:
    """Whether the parsed command can modify tracker state (fail closed)."""
    if args.command == "init":
        return False
    if args.command == "import-yaml":
        return not args.dry_run
    if args.command == "verify":
        return args.run is not None
    if args.command == "config":
        return args.value is not None
    if args.command == "finding":
        # The nested `finding` subcommands share one top-level command name, so
        # classify by the subcommand (create/candidates/list/show are draft-only
        # or read-only; sync/dismiss/triage/link/promote mutate). Interactive
        # finding reads use the normal embedded-replica path, exactly like item
        # `list`/`show`, so they are absent from READ_ONLY_COMMANDS by design.
        return todo_findings.finding_command_mutates(args)
    return args.command not in _IMPLICIT_LOCAL_READ_COMMANDS


def _report_backend(backend: Path | str, *, implicit_default_local: bool) -> None:
    if isinstance(backend, Path):
        print(f"todo backend: local ({backend})", file=sys.stderr)
        if implicit_default_local:
            print(
                "WARNING: LOCAL FALLBACK DB - NOT the production tracker; "
                "set --db, TODO_DB_PATH, or TODO_DB_URL explicitly.",
                file=sys.stderr,
            )
        return
    # Never print the hosted URL or token: the backend kind is enough.
    print("todo backend: hosted", file=sys.stderr)


def connect_backend(backend: Path | str, *, read_only: bool = False) -> sqlite3.Connection | _HostedConnection:
    if isinstance(backend, Path):
        return connect(backend)
    return connect_hosted(backend, read_only=read_only)


def migrate_backend(backend: Path | str) -> list[int]:
    """Apply pending schema migrations on either backend; returns versions applied."""
    if isinstance(backend, Path):
        return migrate_db(backend)
    # Hosted: a fresh sync is a hard requirement — migrating a stale replica
    # against an already-migrated primary would corrupt the version record.
    conn = _hosted_raw_connect(backend, sync_required=True)
    try:
        version = _schema_version(conn)
        if version is None:
            _ensure_schema(conn)  # fresh database: created at the current version
            return []
        applied: list[int] = []
        for target in sorted(MIGRATIONS):
            if version < target:
                with _write_txn(conn):
                    current = _schema_version(conn)
                    if current is not None and current >= target:
                        # a concurrent migrator won the race; not an error
                        version = current
                        continue
                    for statement in MIGRATIONS[target]:
                        conn.execute(statement)
                    conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(target),))
                version = target
                applied.append(target)
        return applied
    finally:
        conn.close()


def migrate_db(db_path: Path) -> list[int]:
    """Apply pending schema migrations; returns the versions applied."""
    if not db_path.exists():
        # Nothing to migrate — a fresh connect() creates the current schema.
        connect(db_path).close()
        return []
    raw = sqlite3.connect(db_path)
    raw.row_factory = sqlite3.Row
    try:
        version = _schema_version(raw)
        if version is None:
            raise TodoError(f"{db_path} exists but has no tracker schema")
        applied: list[int] = []
        for target in sorted(MIGRATIONS):
            if version < target:
                for statement in MIGRATIONS[target]:
                    raw.execute(statement)
                raw.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(target),))
                raw.commit()
                version = target
                applied.append(target)
        return applied
    finally:
        raw.close()


@contextmanager
def _write_txn(conn: sqlite3.Connection):
    """Serialize a check-then-act write: BEGIN IMMEDIATE holds the write lock
    for the whole block, so gates (deferral check, lease check, dep check)
    cannot be invalidated by a concurrent writer between read and update."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        try:
            conn.rollback()
        except Exception:  # noqa: S110 - never mask the original failure
            pass
        raise
    else:
        conn.commit()


def _schema_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
    if row is None:
        return None
    got = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    return int(got["value"]) if got else None


def log_event(
    conn: sqlite3.Connection,
    actor: str,
    item_id: str | None,
    action: str,
    detail: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO events (at, actor, item_id, action, detail) VALUES (?, ?, ?, ?, ?)",
        (utc_now(), actor, item_id, action, json.dumps(detail or {}, sort_keys=True)),
    )


# ---------------------------------------------------------------------------
# Graph helpers


def _reachable(edges: dict[str, set[str]], start: str, target: str) -> bool:
    """True if `target` is reachable from `start` following `edges`."""
    seen: set[str] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(edges.get(node, ()))
    return False


def _check_no_cycle(edges: dict[str, set[str]], src: str, dst: str, kind: str) -> None:
    """Reject adding edge src->dst if dst can already reach src."""
    if src == dst:
        raise TodoError(f"{kind} dependency of {src!r} on itself")
    if _reachable(edges, dst, src):
        raise TodoError(f"{kind} dependency cycle: {src!r} -> {dst!r} closes a loop")


def _item_dep_edges(conn: sqlite3.Connection) -> dict[str, set[str]]:
    edges: dict[str, set[str]] = {}
    for row in conn.execute("SELECT item_id, needs_item FROM item_deps"):
        edges.setdefault(row["item_id"], set()).add(row["needs_item"])
    return edges


def _work_need_edges(conn: sqlite3.Connection, item_id: str) -> dict[str, set[str]]:
    edges: dict[str, set[str]] = {}
    for row in conn.execute("SELECT wid, needs_wid FROM work_needs WHERE item_id = ?", (item_id,)):
        edges.setdefault(row["wid"], set()).add(row["needs_wid"])
    return edges


# ---------------------------------------------------------------------------
# Core operations (the write chokepoint)


def _require_item(conn: sqlite3.Connection, item_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise TodoError(f"no such item: {item_id!r}")
    return row


def _lease_expired(claimed_at: str | None, ttl_hours: float) -> bool:
    if not claimed_at:
        return True
    then = datetime.strptime(claimed_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - then > timedelta(hours=ttl_hours)


def _transition(conn: sqlite3.Connection, item: sqlite3.Row, new_state: str) -> None:
    if (item["state"], new_state) not in TRANSITIONS:
        hint = ""
        if item["state"] == "planning" and new_state == "done":
            hint = f"; claim it first via `todo claim {item['id']}`"
        raise TodoError(f"illegal transition {item['state']!r} -> {new_state!r} for {item['id']!r}{hint}")
    conn.execute("UPDATE items SET state = ? WHERE id = ?", (new_state, item["id"]))


def create_item(
    conn: sqlite3.Connection,
    actor: str,
    *,
    item_id: str,
    title: str,
    worktree: str,
    priority: str,
    description: str,
    category: str | None = None,
    approach: str | None = None,
    state: str = "planning",
    blocked_reason: str | None = None,
    created_at: str | None = None,
    work: list[dict[str, Any]] | None = None,
    deps: list[str] | None = None,
    scope: list[tuple[str, str]] | None = None,
    verifications: list[dict[str, str]] | None = None,
    preserves: list[str] | None = None,
    anti_patterns: list[tuple[str, str, str]] | None = None,
    prior_art: list[tuple[str, str, str]] | None = None,
    completed_at: str | None = None,
    completed_pr: int | None = None,
    _in_txn: bool = False,
) -> None:
    if not SLUG_RE.match(item_id):
        raise TodoError(f"invalid item id (slug) {item_id!r}")
    if priority not in PRIORITIES:
        raise TodoError(f"invalid priority {priority!r}; one of {', '.join(PRIORITIES)}")
    # 'done' is importer-only: the archive bridge records already-finished
    # items directly. Live work must still travel planning -> active -> done
    # through the gated transitions.
    if state not in ("planning", "active", "done"):
        raise TodoError(f"new items must start planning, active, or done (import), not {state!r}")
    if state != "done" and (completed_at or completed_pr):
        raise TodoError("completed_at/completed_pr are only valid with state='done' (import)")

    def _write_rows() -> None:
        try:
            conn.execute(
                "INSERT INTO items (id, title, worktree, priority, state, blocked_reason,"
                " category, description, approach, created_at, completed_at, completed_pr)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item_id,
                    title,
                    worktree,
                    priority,
                    state,
                    blocked_reason,
                    category,
                    description,
                    approach,
                    created_at or utc_now(),
                    completed_at,
                    completed_pr,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise TodoError(f"cannot create {item_id!r}: {exc}") from exc
        for unit in work or []:
            _insert_work_unit(conn, item_id, unit)
        # Needs edges only after all units exist so FK failures are ours to phrase.
        for unit in work or []:
            for needs in unit.get("needs", []):
                _insert_work_need(conn, item_id, unit["id"], needs)
        for dep in deps or []:
            add_item_dep(conn, item_id, dep)
        for kind, glob in scope or []:
            conn.execute(
                "INSERT OR IGNORE INTO scope_rules (item_id, kind, path_glob) VALUES (?, ?, ?)",
                (item_id, kind, glob),
            )
        for seq, ver in enumerate(verifications or [], start=1):
            conn.execute(
                "INSERT INTO verifications (item_id, seq, description, command, expected) VALUES (?, ?, ?, ?, ?)",
                (item_id, seq, ver["description"], ver.get("command"), ver.get("expected")),
            )
        for behavior in preserves or []:
            conn.execute(
                "INSERT OR IGNORE INTO preserves (item_id, behavior) VALUES (?, ?)",
                (item_id, behavior),
            )
        for dont, why, instead in anti_patterns or []:
            conn.execute(
                "INSERT OR IGNORE INTO anti_patterns (item_id, dont, why, instead) VALUES (?, ?, ?, ?)",
                (item_id, dont, why, instead),
            )
        for path, concept, decision in prior_art or []:
            if decision not in ("reuse", "extend", "supersede"):
                raise TodoError(f"invalid prior_art decision {decision!r}")
            conn.execute(
                "INSERT OR IGNORE INTO prior_art (item_id, path, concept, decision) VALUES (?, ?, ?, ?)",
                (item_id, path, concept, decision),
            )
        log_event(conn, actor, item_id, "create", {"title": title, "state": state})

    if _in_txn:
        # Caller (promote_deferral) already holds the write transaction, so
        # the whole promote — gate, item creation, resolution — is one txn.
        _write_rows()
    else:
        with _write_txn(conn):
            _write_rows()


def _insert_work_unit(conn: sqlite3.Connection, item_id: str, unit: dict[str, Any]) -> None:
    wid = unit["id"]
    if not WID_RE.match(wid):
        raise TodoError(f"invalid work-unit id {wid!r} on {item_id!r} (expect w0..w999)")
    status = unit.get("status", "pending")
    if status not in UNIT_STATUSES:
        raise TodoError(f"invalid work-unit status {status!r} on {item_id}:{wid}")
    try:
        conn.execute(
            "INSERT INTO work_units (item_id, wid, summary, status, evidence, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, wid, unit["summary"], status, unit.get("evidence"), unit.get("notes")),
        )
    except sqlite3.IntegrityError as exc:
        raise TodoError(f"cannot add work unit {item_id}:{wid}: {exc}") from exc


def _insert_work_need(conn: sqlite3.Connection, item_id: str, wid: str, needs_wid: str) -> None:
    edges = _work_need_edges(conn, item_id)
    _check_no_cycle(edges, wid, needs_wid, "work-unit")
    try:
        conn.execute(
            "INSERT INTO work_needs (item_id, wid, needs_wid) VALUES (?, ?, ?)",
            (item_id, wid, needs_wid),
        )
    except sqlite3.IntegrityError as exc:
        raise TodoError(f"work need {item_id}:{wid} -> {needs_wid} references a missing unit: {exc}") from exc


def add_item_dep(conn: sqlite3.Connection, item_id: str, needs_item: str) -> None:
    edges = _item_dep_edges(conn)
    _check_no_cycle(edges, item_id, needs_item, "item")
    try:
        conn.execute(
            "INSERT INTO item_deps (item_id, needs_item) VALUES (?, ?)",
            (item_id, needs_item),
        )
    except sqlite3.IntegrityError as exc:
        raise TodoError(f"dependency {item_id!r} -> {needs_item!r} references a missing item: {exc}") from exc


def claim_item(
    conn: sqlite3.Connection,
    actor: str,
    item_id: str,
    ttl_hours: float = DEFAULT_LEASE_TTL_HOURS,
) -> dict[str, Any]:
    with _write_txn(conn):
        item = _require_item(conn, item_id)
        if item["state"] not in ("planning", "active"):
            raise TodoError(f"{item_id!r} is {item['state']}; cannot claim")
        holder = item["claimed_by"]
        if holder and holder != actor and not _lease_expired(item["claimed_at"], ttl_hours):
            raise TodoError(
                f"{item_id!r} is claimed by {holder!r} since {item['claimed_at']};"
                " expired leases release via `todo sweep-stale`,"
                " or pick another item from `todo ready`"
            )
        unmet = [
            row["needs_item"]
            for row in conn.execute(
                "SELECT d.needs_item FROM item_deps d JOIN items n ON n.id = d.needs_item"
                " WHERE d.item_id = ? AND n.state != 'done'",
                (item_id,),
            )
        ]
        if unmet:
            raise TodoError(
                f"{item_id!r} has unmet dependencies: {', '.join(unmet)};"
                " finish those first, or pick another item from `todo ready`"
            )
        # BEGIN IMMEDIATE already serializes this block; the conditional
        # predicate + rowcount check is defense-in-depth so a future caller
        # that skips the txn still cannot silently overwrite a live claim.
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=ttl_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        acquired = conn.execute(
            "UPDATE items SET claimed_by = ?, claimed_at = ? WHERE id = ?"
            " AND (claimed_by IS NULL OR claimed_by = ? OR claimed_at < ?)",
            (actor, utc_now(), item_id, actor, cutoff),
        )
        if acquired.rowcount != 1:
            current = _require_item(conn, item_id)
            raise TodoError(f"{item_id!r} was claimed concurrently by {current['claimed_by']!r}")
        if item["state"] == "planning":
            _transition(conn, item, "active")
        log_event(conn, actor, item_id, "claim", {"previous_holder": holder})
    return work_order(conn, item_id)


def release_item(conn: sqlite3.Connection, actor: str, item_id: str) -> None:
    with _write_txn(conn):
        item = _require_item(conn, item_id)
        if item["claimed_by"] is None:
            return
        conn.execute("UPDATE items SET claimed_by = NULL, claimed_at = NULL WHERE id = ?", (item_id,))
        log_event(conn, actor, item_id, "release", {"holder": item["claimed_by"]})


def start_unit(conn: sqlite3.Connection, actor: str, item_id: str, wid: str) -> None:
    with _write_txn(conn):
        _require_item(conn, item_id)
        unit = _require_unit(conn, item_id, wid)
        if unit["status"] == "done":
            raise TodoError(f"{item_id}:{wid} is already done")
        _require_unit_needs_done(conn, item_id, wid)
        worktree, branch = _git_location()
        conn.execute(
            "UPDATE work_units SET status = 'in_progress',"
            " started_at = ?, started_worktree = ?, started_branch = ?"
            " WHERE item_id = ? AND wid = ?",
            (utc_now(), worktree, branch, item_id, wid),
        )
        log_event(conn, actor, item_id, "start", {"wid": wid, "worktree": worktree, "branch": branch})


def done_unit(conn: sqlite3.Connection, actor: str, item_id: str, wid: str, evidence: str) -> None:
    if not evidence or not evidence.strip():
        raise TodoError('evidence is required to mark a work unit done; pass --evidence "<command run / commit / PR>"')
    with _write_txn(conn):
        _require_item(conn, item_id)
        _require_unit(conn, item_id, wid)
        _require_unit_needs_done(conn, item_id, wid)
        # Implicit start: stamp the location if `start` was skipped, so the
        # record of where the work happened survives either path.
        worktree, branch = _git_location()
        conn.execute(
            "UPDATE work_units SET status = 'done', evidence = ?,"
            " started_at = COALESCE(started_at, ?),"
            " started_worktree = COALESCE(started_worktree, ?),"
            " started_branch = COALESCE(started_branch, ?)"
            " WHERE item_id = ? AND wid = ?",
            (evidence, utc_now(), worktree, branch, item_id, wid),
        )
        log_event(conn, actor, item_id, "done", {"wid": wid, "evidence": evidence})


def _require_unit(conn: sqlite3.Connection, item_id: str, wid: str) -> sqlite3.Row:
    unit = conn.execute("SELECT * FROM work_units WHERE item_id = ? AND wid = ?", (item_id, wid)).fetchone()
    if unit is None:
        raise TodoError(f"no such work unit: {item_id}:{wid}")
    return unit


def _require_unit_needs_done(conn: sqlite3.Connection, item_id: str, wid: str) -> None:
    unmet = [
        row["needs_wid"]
        for row in conn.execute(
            "SELECT n.needs_wid FROM work_needs n JOIN work_units u"
            " ON u.item_id = n.item_id AND u.wid = n.needs_wid"
            " WHERE n.item_id = ? AND n.wid = ? AND u.status != 'done'",
            (item_id, wid),
        )
    ]
    if unmet:
        raise TodoError(
            f"{item_id}:{wid} needs unfinished units: {', '.join(unmet)};"
            f" finish them first via `todo done {item_id} <wid> --evidence ...`"
        )


def defer_work(
    conn: sqlite3.Connection,
    actor: str,
    item_id: str,
    summary: str,
    reason: str,
    allow_terminal: bool = False,
) -> int:
    """Record deferred work. `allow_terminal` is importer-only: it lets the
    archive bridge attach historical deferrals to already-done items; the CLI
    path must refuse, or terminal items regrow the buried-deferral class."""
    with _write_txn(conn):
        item = _require_item(conn, item_id)
        if item["state"] in ("done", "dropped") and not allow_terminal:
            raise TodoError(
                f"{item_id!r} is {item['state']}; deferrals on terminal items would be"
                " invisible — create a planning item instead (todo create / promote)"
            )
        cursor = conn.execute(
            "INSERT INTO deferrals (from_item, summary, reason, created_at) VALUES (?, ?, ?, ?)",
            (item_id, summary, reason, utc_now()),
        )
        deferral_id = cursor.lastrowid
        log_event(conn, actor, item_id, "defer", {"deferral_id": deferral_id, "summary": summary})
    assert deferral_id is not None
    return deferral_id


def promote_deferral(
    conn: sqlite3.Connection,
    actor: str,
    deferral_id: int,
    *,
    new_item_id: str,
    title: str | None = None,
    priority: str = "medium",
    worktree: str | None = None,
    description: str | None = None,
    category: str | None = None,
    approach: str | None = None,
    scope: list[tuple[str, str]] | None = None,
    verifications: list[dict[str, str]] | None = None,
    preserves: list[str] | None = None,
    work: list[dict[str, Any]] | None = None,
) -> None:
    # One transaction end to end: the gate read, the item creation, and the
    # resolution update. Split phases let two actors promote one deferral
    # (or a promote overwrite a concurrent dismiss) — found by adversarial
    # review; the conditional UPDATE is the same defense-in-depth pattern as
    # claim_item.
    with _write_txn(conn):
        row = _require_deferral(conn, deferral_id)
        if row["resolution"] != "open":
            raise TodoError(f"deferral {deferral_id} is already {row['resolution']}")
        parent = _require_item(conn, row["from_item"])
        create_item(
            conn,
            actor,
            item_id=new_item_id,
            title=title or row["summary"][:200],
            worktree=worktree or parent["worktree"],
            priority=priority,
            description=description
            or (
                f"Promoted from deferral #{deferral_id} of {parent['id']}.\n"
                f"Deferred: {row['summary']}\nReason deferred: {row['reason']}"
            ),
            # Guardrails are accepted here so a promoted item is not born
            # without scope, a ladder or work units. They are create-time only
            # in this wrapper, so an item that misses them cannot be repaired
            # here at all -- `update` is a standalone-only verb (todo-db >= 0.3)
            # and deliberately not a wrapper handler -- and `check-scope`
            # passes trivially in the meantime, which is worse than failing.
            category=category,
            approach=approach,
            scope=scope,
            verifications=verifications,
            preserves=preserves,
            work=work,
            _in_txn=True,
        )
        resolved = conn.execute(
            "UPDATE deferrals SET resolution = 'promoted', resolved_item = ? WHERE id = ? AND resolution = 'open'",
            (new_item_id, deferral_id),
        )
        if resolved.rowcount != 1:
            raise TodoError(f"deferral {deferral_id} was resolved concurrently")
        log_event(
            conn,
            actor,
            row["from_item"],
            "promote",
            {"deferral_id": deferral_id, "new_item": new_item_id},
        )


def dismiss_deferral(conn: sqlite3.Connection, actor: str, deferral_id: int, reason: str) -> None:
    if not reason.strip():
        raise TodoError("a dismissal reason is required")
    with _write_txn(conn):
        row = _require_deferral(conn, deferral_id)
        if row["resolution"] != "open":
            raise TodoError(f"deferral {deferral_id} is already {row['resolution']}")
        conn.execute(
            "UPDATE deferrals SET resolution = 'dismissed', resolved_reason = ? WHERE id = ?",
            (reason, deferral_id),
        )
        log_event(
            conn,
            actor,
            row["from_item"],
            "dismiss",
            {"deferral_id": deferral_id, "reason": reason},
        )


def _require_deferral(conn: sqlite3.Connection, deferral_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM deferrals WHERE id = ?", (deferral_id,)).fetchone()
    if row is None:
        raise TodoError(f"no such deferral: {deferral_id}")
    return row


def complete_item(conn: sqlite3.Connection, actor: str, item_id: str, pr: int | None) -> None:
    with _write_txn(conn):
        item = _require_item(conn, item_id)
        # State legality first: "claim it" is more fundamental guidance than
        # any unit-level detail on an item that was never started.
        if item["state"] != "active":
            hint = f"; claim it first via `todo claim {item_id}`" if item["state"] == "planning" else ""
            raise TodoError(f"illegal transition {item['state']!r} -> 'done' for {item_id!r}{hint}")
        undone = [
            row["wid"]
            for row in conn.execute(
                "SELECT wid FROM work_units WHERE item_id = ? AND status != 'done'",
                (item_id,),
            )
        ]
        if undone:
            raise TodoError(
                f"cannot complete {item_id!r}: work units not done: {', '.join(undone)};"
                f" mark each via `todo done {item_id} <wid> --evidence ...`"
            )
        open_deferrals = [
            f"#{row['id']} {row['summary']}"
            for row in conn.execute(
                "SELECT id, summary FROM deferrals WHERE from_item = ? AND resolution = 'open'",
                (item_id,),
            )
        ]
        if open_deferrals:
            raise TodoError(
                f"cannot complete {item_id!r}: unresolved deferrals: {'; '.join(open_deferrals)};"
                " resolve each via `todo promote <deferral-id> --to-item <slug>`"
                ' or `todo dismiss <deferral-id> --reason "..."`'
            )
        if item["blocked_reason"]:
            raise TodoError(
                f"cannot complete {item_id!r} while blocked: {item['blocked_reason']};"
                f" clear it via `todo unblock {item_id}`"
            )
        _transition(conn, item, "done")
        conn.execute(
            "UPDATE items SET completed_at = ?, completed_pr = ?, claimed_by = NULL, claimed_at = NULL WHERE id = ?",
            (utc_now(), pr, item_id),
        )
        log_event(conn, actor, item_id, "complete", {"pr": pr})


def drop_item(conn: sqlite3.Connection, actor: str, item_id: str, reason: str) -> None:
    if not reason.strip():
        raise TodoError("a drop reason is required")
    with _write_txn(conn):
        item = _require_item(conn, item_id)
        open_deferrals = conn.execute(
            "SELECT count(*) AS n FROM deferrals WHERE from_item = ? AND resolution = 'open'",
            (item_id,),
        ).fetchone()["n"]
        if open_deferrals:
            raise TodoError(
                f"cannot drop {item_id!r}: {open_deferrals} unresolved deferral(s);"
                " resolve each via `todo promote <deferral-id> --to-item <slug>`"
                ' or `todo dismiss <deferral-id> --reason "..."`'
            )
        _transition(conn, item, "dropped")
        conn.execute("UPDATE items SET claimed_by = NULL, claimed_at = NULL WHERE id = ?", (item_id,))
        log_event(conn, actor, item_id, "drop", {"reason": reason})


def block_item(conn: sqlite3.Connection, actor: str, item_id: str, reason: str) -> None:
    if not reason.strip():
        raise TodoError("a block reason is required")
    with _write_txn(conn):
        item = _require_item(conn, item_id)
        if item["state"] in ("done", "dropped"):
            raise TodoError(f"{item_id!r} is {item['state']}; cannot block")
        conn.execute("UPDATE items SET blocked_reason = ? WHERE id = ?", (reason, item_id))
        log_event(conn, actor, item_id, "block", {"reason": reason})


def unblock_item(conn: sqlite3.Connection, actor: str, item_id: str) -> None:
    with _write_txn(conn):
        _require_item(conn, item_id)
        conn.execute("UPDATE items SET blocked_reason = NULL WHERE id = ?", (item_id,))
        log_event(conn, actor, item_id, "unblock", None)


def sweep_stale(conn: sqlite3.Connection, actor: str, ttl_hours: float = DEFAULT_LEASE_TTL_HOURS) -> list[str]:
    released = []
    with _write_txn(conn):
        rows = conn.execute("SELECT id, claimed_by, claimed_at FROM items WHERE claimed_by IS NOT NULL").fetchall()
        for row in rows:
            if _lease_expired(row["claimed_at"], ttl_hours):
                # Conditional on the exact lease observed (same defense as
                # claim_item): if the lease changed hands since the read —
                # e.g. a renewal the sweeping replica had not seen — the
                # release must not fire on the live claim.
                swept = conn.execute(
                    "UPDATE items SET claimed_by = NULL, claimed_at = NULL"
                    " WHERE id = ? AND claimed_by = ? AND claimed_at IS ?",
                    (row["id"], row["claimed_by"], row["claimed_at"]),
                )
                if swept.rowcount != 1:
                    continue
                log_event(
                    conn,
                    actor,
                    row["id"],
                    "sweep",
                    {"stale_holder": row["claimed_by"], "claimed_at": row["claimed_at"]},
                )
                released.append(row["id"])
    return released


# ---------------------------------------------------------------------------
# Read side


def ready_items(
    conn: sqlite3.Connection,
    actor: str,
    ttl_hours: float = DEFAULT_LEASE_TTL_HOURS,
) -> list[dict[str, Any]]:
    out = []
    for row in conn.execute(
        "SELECT * FROM items WHERE state IN ('planning','active') AND blocked_reason IS NULL ORDER BY priority, id"
    ):
        holder = row["claimed_by"]
        if holder and holder != actor and not _lease_expired(row["claimed_at"], ttl_hours):
            continue
        unmet = conn.execute(
            "SELECT count(*) AS n FROM item_deps d JOIN items n2 ON n2.id = d.needs_item"
            " WHERE d.item_id = ? AND n2.state != 'done'",
            (row["id"],),
        ).fetchone()["n"]
        if unmet:
            continue
        out.append(dict(row))
    priority_rank = {p: i for i, p in enumerate(PRIORITIES)}
    out.sort(key=lambda item: (priority_rank[item["priority"]], item["id"]))
    return out


def ready_units(conn: sqlite3.Connection, item_id: str) -> tuple[list[dict], list[dict]]:
    ready, blocked = [], []
    for unit in conn.execute(
        "SELECT * FROM work_units WHERE item_id = ? AND status != 'done' ORDER BY wid",
        (item_id,),
    ):
        unmet = [
            row["needs_wid"]
            for row in conn.execute(
                "SELECT n.needs_wid FROM work_needs n JOIN work_units u"
                " ON u.item_id = n.item_id AND u.wid = n.needs_wid"
                " WHERE n.item_id = ? AND n.wid = ? AND u.status != 'done'",
                (item_id, unit["wid"]),
            )
        ]
        entry = dict(unit)
        if unmet:
            entry["unmet"] = unmet
            blocked.append(entry)
        else:
            ready.append(entry)
    return ready, blocked


def get_item(conn: sqlite3.Connection, item_id: str) -> dict[str, Any]:
    item = dict(_require_item(conn, item_id))
    item["work"] = [
        {
            **dict(row),
            "needs": [
                n["needs_wid"]
                for n in conn.execute(
                    "SELECT needs_wid FROM work_needs WHERE item_id = ? AND wid = ? ORDER BY needs_wid",
                    (item_id, row["wid"]),
                )
            ],
        }
        for row in conn.execute("SELECT * FROM work_units WHERE item_id = ? ORDER BY wid", (item_id,))
    ]
    item["deps"] = [
        row["needs_item"]
        for row in conn.execute(
            "SELECT needs_item FROM item_deps WHERE item_id = ? ORDER BY needs_item",
            (item_id,),
        )
    ]
    item["scope"] = [
        dict(row)
        for row in conn.execute(
            "SELECT kind, path_glob FROM scope_rules WHERE item_id = ? ORDER BY kind, path_glob",
            (item_id,),
        )
    ]
    item["verifications"] = [
        dict(row) for row in conn.execute("SELECT * FROM verifications WHERE item_id = ? ORDER BY seq", (item_id,))
    ]
    item["preserves"] = [
        row["behavior"]
        for row in conn.execute("SELECT behavior FROM preserves WHERE item_id = ? ORDER BY behavior", (item_id,))
    ]
    item["anti_patterns"] = [
        dict(row)
        for row in conn.execute(
            "SELECT dont, why, instead FROM anti_patterns WHERE item_id = ? ORDER BY dont",
            (item_id,),
        )
    ]
    item["prior_art"] = [
        dict(row)
        for row in conn.execute(
            "SELECT path, concept, decision FROM prior_art WHERE item_id = ? ORDER BY path, concept",
            (item_id,),
        )
    ]
    item["deferrals"] = [
        dict(row) for row in conn.execute("SELECT * FROM deferrals WHERE from_item = ? ORDER BY id", (item_id,))
    ]
    return item


def work_order(conn: sqlite3.Connection, item_id: str) -> dict[str, Any]:
    item = get_item(conn, item_id)
    ready, blocked = ready_units(conn, item_id)
    item["ready_units"] = ready
    item["blocked_units"] = blocked
    return item


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    def counts(query: str) -> dict[str, int]:
        return {row[0]: row[1] for row in conn.execute(query)}

    return {
        "items_by_state": counts("SELECT state, count(*) FROM items GROUP BY state"),
        "open_by_priority": counts(
            "SELECT priority, count(*) FROM items WHERE state IN ('planning','active') GROUP BY priority"
        ),
        "open_by_worktree": counts(
            "SELECT worktree, count(*) FROM items WHERE state IN ('planning','active') GROUP BY worktree"
        ),
        "deferrals_by_resolution": counts("SELECT resolution, count(*) FROM deferrals GROUP BY resolution"),
        "claimed": counts("SELECT claimed_by, count(*) FROM items WHERE claimed_by IS NOT NULL GROUP BY claimed_by"),
        # Additive findings-domain key (phase 4). Present but empty when there are
        # no findings; existing items-domain keys above are untouched.
        "findings_by_disposition": todo_findings.findings_by_disposition(conn),
    }


# ---------------------------------------------------------------------------
# Scope check, verify, lint


def _scope_glob_matches(path: str, glob: str) -> bool:
    """Match a scope glob, treating a trailing slash as a recursive directory."""
    if glob.endswith("/"):
        directory = glob.rstrip("/")
        return path == directory or path.startswith(f"{directory}/")
    return fnmatch.fnmatch(path, glob)


def check_paths(files: list[str], rules: list[dict[str, str]]) -> list[str]:
    """Return violation messages for changed files vs scope rules."""
    only = [r["path_glob"] for r in rules if r["kind"] == "only_modify"]
    deny = [r["path_glob"] for r in rules if r["kind"] == "do_not_modify"]
    violations = []
    for path in files:
        # The tracker's own state directory is never scope-relevant
        # (eval finding: it false-positived on worktrees with stale gitignores).
        if path == ".todo-db" or path.startswith(".todo-db/"):
            continue
        candidates = (path, str((Path.cwd() / path).resolve())) if not Path(path).is_absolute() else (path,)
        if any(_scope_glob_matches(candidate, glob) for candidate in candidates for glob in deny):
            violations.append(f"{path}: matches do_not_modify")
        elif only and not any(_scope_glob_matches(candidate, glob) for candidate in candidates for glob in only):
            violations.append(f"{path}: outside only_modify allowlist")
    return violations


def changed_files(base: str | None) -> list[str]:
    if base:
        cmd = ["git", "diff", "--name-only", f"{base}...HEAD"]
    else:
        cmd = ["git", "diff", "--name-only", "HEAD"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise TodoError(f"git diff failed: {result.stderr.strip()}")
    files = [line for line in result.stdout.splitlines() if line.strip()]
    # Untracked files are invisible to `git diff` but are still scope-relevant:
    # a brand-new out-of-scope file must not slip past the check (live-UAT finding).
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=False,
    )
    if untracked.returncode == 0:
        files.extend(line for line in untracked.stdout.splitlines() if line.strip())
    return sorted(set(files))


def run_verification(conn: sqlite3.Connection, actor: str, item_id: str, seq: int) -> tuple[str, str]:
    row = conn.execute("SELECT * FROM verifications WHERE item_id = ? AND seq = ?", (item_id, seq)).fetchone()
    if row is None:
        raise TodoError(f"no verification seq={seq} on {item_id!r}")
    if not row["command"]:
        raise TodoError(f"verification seq={seq} on {item_id!r} has no command")
    proc = subprocess.run(row["command"], shell=True, capture_output=True, text=True, check=False)
    output = (proc.stdout or "") + (proc.stderr or "")
    passed = proc.returncode == 0
    result = "pass" if passed else "fail"
    with _write_txn(conn):
        conn.execute(
            "UPDATE verifications SET last_run = ?, last_result = ? WHERE item_id = ? AND seq = ?",
            (utc_now(), result, item_id, seq),
        )
        log_event(conn, actor, item_id, "verify", {"seq": seq, "result": result})
    return result, output


EVIDENCE_PIN_RE = re.compile(r"verified on|@ [0-9a-f]{7,}|\bPASS\b", re.IGNORECASE)


# A rung is graded ONLY on its command's exit status (see run_verification);
# `expected` is human acceptance text and is never evaluated. So an expectation
# that names a string which must be ABSENT from the output describes something
# the exit code cannot encode -- unless the command asserts on output itself.
# Such a rung can never pass, however correct the implementation is.
_EXPECTED_NEGATES_OUTPUT_RE = re.compile(
    r"\bnot\s+['\"]|must not\s+(?:print|contain|report|emit|include|output|show)|"
    r"(?:does not|doesn't)\s+(?:print|contain|report|emit|include|output|show)|"
    r"no longer\s+(?:print|contain|report|emit|include|output|show)s?\b",
    re.IGNORECASE,
)
# Constructs that turn output into an exit status, or compose an assertion.
_COMMAND_ASSERTS_ON_OUTPUT_RE = re.compile(
    r"(?:^|[\s|;&])(?:grep|rg)\b|test\s|\[\s|&&|\|\||^\s*!|\bassert\b|--check\b",
    re.IGNORECASE,
)
_JQ_EXIT_STATUS_RE = re.compile(r"(?:^|[|;&]\s*)jq\b[^|;&\n]*?(?:--exit-status\b|-e(?:\s|$))", re.IGNORECASE)


def _command_asserts_on_output(command: str) -> bool:
    """Return whether a verification command makes output affect its exit status."""
    return bool(_COMMAND_ASSERTS_ON_OUTPUT_RE.search(command) or _JQ_EXIT_STATUS_RE.search(command))


def _unsatisfiable_verifications(item: dict) -> list[int]:
    """Return seqs of rungs whose command cannot express their expectation."""
    offenders = []
    for ver in item["verifications"]:
        command = ver.get("command") or ""
        expected = ver.get("expected") or ""
        if not command:
            continue
        if _EXPECTED_NEGATES_OUTPUT_RE.search(expected) and not _command_asserts_on_output(command):
            offenders.append(ver["seq"])
    return offenders


def lint_item(conn: sqlite3.Connection, item_id: str) -> list[str]:
    item = get_item(conn, item_id)
    findings = []
    if not item["verifications"]:
        findings.append("no verification steps recorded")
    elif not any(v["command"] for v in item["verifications"]):
        findings.append("verification steps exist but none has a runnable command")
    unsatisfiable = _unsatisfiable_verifications(item)
    if unsatisfiable:
        findings.append(
            f"verification seq {unsatisfiable} expects output that must be absent, but the command is graded "
            "only on exit status - make the command self-asserting (exit 0 iff satisfied), e.g. pipe to `grep -q` "
            "or negate with `!`"
        )
    if get_config(conn, "lint.require_scope_rules") == "on" and item["work"] and not item["scope"]:
        findings.append("has work units but no scope rules (only_modify/do_not_modify)")
    if (
        get_config(conn, "lint.require_w0_revalidation") == "on"
        and EVIDENCE_PIN_RE.search(item["description"] or "")
        and not any(unit["wid"] == "w0" for unit in item["work"])
    ):
        findings.append("description cites point-in-time evidence but has no w0 re-validation unit")
    if not item["work"] and item["state"] in ("planning", "active"):
        findings.append("no work breakdown")
    return findings


# ---------------------------------------------------------------------------
# Export


@contextmanager
def _read_txn(conn: Any):
    """Hold one consistent read snapshot across the complete export bundle."""
    conn.execute("BEGIN")
    try:
        yield
    except BaseException:
        try:
            conn.rollback()
        except Exception:  # noqa: S110 - never mask the original failure
            pass
        raise
    else:
        conn.commit()


def _export_all_unlocked(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    # Bulk read: one SELECT per table, assembled in Python. Produces output
    # byte-identical to per-item get_item() but with ~11 round-trips instead of
    # thousands, so a remote (no-embedded-replica) read-only connection stays
    # fast enough for the export job. Ordering within every child list mirrors
    # get_item()'s per-item ORDER BY exactly.
    items: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in conn.execute("SELECT * FROM items ORDER BY id"):
        d = dict(row)
        d["work"] = []
        d["deps"] = []
        d["scope"] = []
        d["verifications"] = []
        d["preserves"] = []
        d["anti_patterns"] = []
        d["prior_art"] = []
        d["deferrals"] = []
        items[d["id"]] = d
        order.append(d["id"])

    work_index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in conn.execute("SELECT * FROM work_units ORDER BY item_id, wid"):
        w = dict(row)
        w["needs"] = []
        items[w["item_id"]]["work"].append(w)
        work_index[(w["item_id"], w["wid"])] = w
    for row in conn.execute("SELECT item_id, wid, needs_wid FROM work_needs ORDER BY item_id, wid, needs_wid"):
        work_index[(row["item_id"], row["wid"])]["needs"].append(row["needs_wid"])
    for row in conn.execute("SELECT item_id, needs_item FROM item_deps ORDER BY item_id, needs_item"):
        items[row["item_id"]]["deps"].append(row["needs_item"])
    for row in conn.execute("SELECT item_id, kind, path_glob FROM scope_rules ORDER BY item_id, kind, path_glob"):
        items[row["item_id"]]["scope"].append({"kind": row["kind"], "path_glob": row["path_glob"]})
    for row in conn.execute("SELECT * FROM verifications ORDER BY item_id, seq"):
        items[row["item_id"]]["verifications"].append(dict(row))
    for row in conn.execute("SELECT item_id, behavior FROM preserves ORDER BY item_id, behavior"):
        items[row["item_id"]]["preserves"].append(row["behavior"])
    # Use dict(row) (as get_item does), consistent with every other table
    # here: `instead` is a SQL keyword and the hosted libsql cursor once
    # reported it back as "INSTEAD" while local sqlite3 preserved the SELECT
    # casing "instead" - _HostedRow now lowercases column names at
    # construction (see its docstring) so both backends agree, but dict(row)
    # remains the right idiom regardless of casing.
    for row in conn.execute("SELECT item_id, dont, why, instead FROM anti_patterns ORDER BY item_id, dont"):
        anti = dict(row)
        items[anti.pop("item_id")]["anti_patterns"].append(anti)
    for row in conn.execute("SELECT item_id, path, concept, decision FROM prior_art ORDER BY item_id, path, concept"):
        items[row["item_id"]]["prior_art"].append(
            {"path": row["path"], "concept": row["concept"], "decision": row["decision"]}
        )
    for row in conn.execute("SELECT * FROM deferrals ORDER BY from_item, id"):
        items[row["from_item"]]["deferrals"].append(dict(row))

    return [items[i] for i in order]


def export_all(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    with _read_txn(conn):
        return _export_all_unlocked(conn)


def _export_events_unlocked(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    # The append-only provenance trail. Ordered by the monotonic `seq` PK for a
    # deterministic, reproducible diff. Row data (including the `at` timestamp)
    # is real tracker state, not generation-time state, so the ordering + values
    # are stable across runs -- the committed snapshot's clean-diff property.
    return [dict(row) for row in conn.execute("SELECT * FROM events ORDER BY seq")]


def export_events(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    with _read_txn(conn):
        return _export_events_unlocked(conn)


# The tables todo-db's `restore-legacy` importer requires in a snapshot
# (todo_db/database.py::restore_legacy). Stated explicitly so the tie to the
# committed-export allowlist is checkable rather than incidental.
RESTORE_LEGACY_REQUIRED_TABLES = frozenset(
    {
        "items",
        "events",
        "work_units",
        "work_needs",
        "item_deps",
        "scope_rules",
        "verifications",
        "preserves",
        "anti_patterns",
        "prior_art",
        "deferrals",
        "meta",
    }
)

# A migration snapshot is a BACKUP artifact, so it is scoped to the full
# backup/restore set (TRANSFER_TABLES) plus `meta` for schema provenance -- NOT
# to EXPORT_TABLE_ALLOWLIST. The two happen to hold the same names today, but
# they answer different questions: the allowlist is "what may be committed to
# Git", deliberately maintained as an independent literal so the committed
# surface never widens by accident. Deriving a migration snapshot from it would
# invert that: legitimately narrowing what gets committed would silently narrow
# what a migration carries, which is precisely the kind of silent data loss this
# snapshot exists to avoid.
#
# Findings ARE carried, as of todo-db PR #1. They were excluded before only
# because restore-legacy discarded unknown tables, so shipping review prose
# would have leaked it for nothing. That importer now loads the findings domain
# and rejects anything it does not recognise, so omitting them here would make
# the migration silently lossy instead.
RESTORE_LEGACY_OPTIONAL_TABLES = frozenset(
    {
        "findings",
        "finding_evidence",
        "finding_links",
        "finding_events",
        "finding_sections",
    }
)
SNAPSHOT_TABLES = frozenset(TRANSFER_TABLES) | {"meta"} | RESTORE_LEGACY_OPTIONAL_TABLES


def _snapshot_order_by(conn: sqlite3.Connection, table: str) -> str:
    """ORDER BY the table's primary key so a snapshot is reproducible."""
    pk = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})") if row["pk"]]
    return f" ORDER BY {', '.join(pk)}" if pk else ""


def build_snapshot(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """Raw per-table dump for todo-db's `restore-legacy` importer.

    This is a different SHAPE from the committed export, not a reformatting of
    it. ``write_export`` denormalizes: child rows are nested inside each item in
    items.jsonl. ``restore_legacy`` wants the opposite -- normalized tables it
    can load directly -- and explicitly strips the nested keys, so the committed
    export is structurally invalid as importer input.

    Carries the findings domain as well as the tracker tables. It is safe to
    include review prose here precisely because a snapshot is never committed:
    ``write_snapshot`` refuses any destination inside a Git work tree. The
    committed export remains findings-free via a separate allowlist.
    """
    # Fail closed against the importer's contract, which is: every required
    # table must be present, and nothing outside required|optional may be --
    # todo-db rejects unrecognised tables rather than ignoring them. Checking
    # both directions here turns a future mismatch into a build-time error
    # instead of a failed or silently lossy cutover.
    missing = sorted(RESTORE_LEGACY_REQUIRED_TABLES - SNAPSHOT_TABLES)
    unacceptable = sorted(SNAPSHOT_TABLES - RESTORE_LEGACY_REQUIRED_TABLES - RESTORE_LEGACY_OPTIONAL_TABLES)
    if missing or unacceptable:
        raise RuntimeError(
            "snapshot scope disagrees with restore-legacy's contract; a migration "
            "would fail or lose data.\n"
            f"  required by restore-legacy but not dumped: {missing}\n"
            f"  dumped but the importer would reject: {unacceptable}\n"
            "Reconcile RESTORE_LEGACY_REQUIRED_TABLES / RESTORE_LEGACY_OPTIONAL_TABLES with the importer."
        )
    # One read snapshot across every table. Two independent SELECTs with a
    # concurrent write between them would produce a bundle that no point in
    # time ever had -- e.g. a scope_rules row referencing an absent item.
    with _read_txn(conn):
        return {
            # Table names come from a module constant, never from input.
            table: [dict(row) for row in conn.execute(f"SELECT * FROM {table}{_snapshot_order_by(conn, table)}")]
            for table in sorted(SNAPSHOT_TABLES)
        }


def _enclosing_work_tree(path: Path) -> Path | None:
    """The Git work tree containing ``path``, if any.

    Deliberately NOT ``git_main_root()``: agents work in pool worktrees
    (BenchBox.pool-NN), which are separate roots, so a main-root check passes a
    destination straight into a checkout. Walk instead, and accept ``.git`` as
    either a directory (clone) or a file (linked worktree).
    """
    probe = path if path.is_dir() else path.parent
    while True:
        if (probe / ".git").exists():
            return probe
        if probe == probe.parent:
            return None
        probe = probe.parent


def write_snapshot(conn: sqlite3.Connection, path: Path) -> Path:
    """Write a migration snapshot, refusing to place it inside the repo.

    A snapshot is a full tracker dump including every deferral and event body.
    PR #1327 established that such payloads stay out of Git; the committed
    export is the curated artifact. Rather than trust the caller to remember,
    refuse a destination inside the work tree.
    """
    resolved = path.expanduser().resolve()
    if _enclosing_work_tree(resolved) is not None:
        raise SystemExit(
            f"refusing to write a tracker snapshot inside a Git work tree ({resolved}).\n"
            "Snapshots carry every deferral and event body and must not reach Git; "
            "write it outside the checkout, e.g. ~/todo-db-backups/."
        )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with open(resolved, "w", encoding="utf-8") as handle:
        json.dump(build_snapshot(conn), handle, sort_keys=True, indent=2)
        handle.write("\n")
    return resolved


def write_export(conn: sqlite3.Connection, out_dir: Path) -> tuple[Path, Path, Path]:
    # Fail closed: the exporter's own coverage (item-nested tables + events)
    # must equal the committed-snapshot allowlist. If a future change teaches
    # the exporter a new table without allowlisting it (or allowlists one the
    # exporter does not emit), this raises instead of silently leaking or
    # dropping data. Findings tables are excluded by construction -- they are
    # neither in _ITEM_NESTED_EXPORT_TABLES nor EXPORT_TABLE_ALLOWLIST -- so
    # their review prose can never reach the version-controlled snapshot.
    covered = _ITEM_NESTED_EXPORT_TABLES | {"events"}
    if covered != EXPORT_TABLE_ALLOWLIST:
        raise RuntimeError(
            "committed export coverage drifted from EXPORT_TABLE_ALLOWLIST: "
            f"covered={sorted(covered)} allowlist={sorted(EXPORT_TABLE_ALLOWLIST)}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    # One read snapshot for the WHOLE bundle: items and events must come from the
    # same consistent view, or a concurrent write between two transactions could
    # emit an events.jsonl row referencing an item absent from items.jsonl.
    with _read_txn(conn):
        items = _export_all_unlocked(conn)
        events = _export_events_unlocked(conn)
    jsonl_path = out_dir / "items.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    events_path = out_dir / "events.jsonl"
    with open(events_path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    index_path = out_dir / "index.md"
    with open(index_path, "w", encoding="utf-8") as handle:
        handle.write("# TODO export\n\n| id | state | priority | worktree | title |\n")
        handle.write("|---|---|---|---|---|\n")
        for item in items:
            handle.write(
                f"| {item['id']} | {item['state']} | {item['priority']} | {item['worktree']} | {item['title']} |\n"
            )
    return jsonl_path, events_path, index_path


# ---------------------------------------------------------------------------
# YAML importer (one-off bridge from the legacy tree)

STATUS_MAP = {
    "not started": ("planning", None),
    "identified": ("planning", None),
    "in progress": ("active", None),
    "under review": ("active", None),
    "blocked": ("active", "imported from YAML status: Blocked"),
}


def _slugify(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def _parse_anti_pattern(text: str) -> tuple[str, str, str]:
    """Split 'DO NOT x -- because y -- do z instead' free text into (dont, why, instead).

    Real entries use '--' or '-' separators and often omit the 'instead' part.
    """
    cleaned = re.sub(r"(?i)^\s*do not\s+", "", text.strip())
    parts = re.split(r"\s+--\s+|\s+[-—]\s+", cleaned, maxsplit=2)
    dont = parts[0].strip()
    why = re.sub(r"(?i)^because\s+", "", parts[1].strip()) if len(parts) > 1 else "(unstated)"
    instead = parts[2].strip() if len(parts) > 2 else "(not specified)"
    return dont, why, instead


def _parse_prior_art(text: str) -> tuple[str, str, str]:
    decision = "reuse"
    for candidate in ("supersede", "extend", "reuse"):
        if re.search(rf"\b{candidate}\b", text, re.IGNORECASE):
            decision = candidate
            break
    first = text.split()[0].rstrip(":,;") if text.split() else text
    return first, text.strip(), decision


def _coerce_verifications(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if isinstance(raw, dict) and "commands" in raw:
        for command in raw.get("commands") or []:
            out.append({"description": str(command), "command": str(command)})
    elif isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                out.append(
                    {
                        "description": str(entry.get("description", "")) or "(no description)",
                        "command": entry.get("command"),
                        "expected": entry.get("expected_output"),
                    }
                )
            else:
                out.append({"description": str(entry)})
    return out


def _parse_yaml_tree(todo_dir: Path, report: dict[str, Any]) -> list[dict[str, Any]]:
    import yaml  # deferred: only the importer needs it

    parsed: list[dict[str, Any]] = []
    for path in sorted(todo_dir.rglob("*.yaml")):
        if "_indexes" in path.parts:
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            report["warnings"].append(f"{path}: unparseable YAML: {exc}")
            continue
        if not isinstance(data, dict):
            report["skipped"].append(f"{path}: not a mapping")
            continue
        data["_path"] = path
        parsed.append(data)
    for data in parsed:
        raw_id = str(data.get("id") or data["_path"].stem)
        item_id = raw_id if SLUG_RE.match(raw_id) else _slugify(raw_id)
        if item_id != raw_id:
            report["warnings"].append(f"{data['_path']}: id {raw_id!r} sanitized to {item_id!r}")
        data["_id"] = item_id
    return parsed


def _coerce_work_units(
    data: dict[str, Any], report: dict[str, Any], lenient: bool = False
) -> list[dict[str, Any]] | None:
    """Coerce work[] into insertable units.

    Strict (open items): any invalid unit id rejects the whole item (None).
    Lenient (archive): invalid units are dropped with a warning — the record
    matters more than a perfect work graph for finished items.
    """
    work = []
    for unit in data.get("work") or []:
        wid = str(unit.get("id", ""))
        summary = str(unit.get("summary", "")).strip() or "(no summary recorded)"
        if len(summary) < 5:
            summary = f"(w) {summary}"
        status = unit.get("status", "pending")
        duplicate = any(existing["id"] == wid for existing in work)
        if not WID_RE.match(wid) or status not in UNIT_STATUSES or duplicate:
            if not lenient:
                report["warnings"].append(f"{data['_path']}: invalid work unit {wid!r}; item skipped")
                return None
            report["warnings"].append(f"{data['_path']}: invalid archive work unit {wid!r} dropped")
            continue
        work.append(
            {
                "id": wid,
                "summary": summary[:200],
                "status": status,
                "needs": [str(n) for n in unit.get("needs") or []],
                "notes": unit.get("notes"),
            }
        )
    if lenient:
        # Dropped units must not leave dangling needs edges behind.
        surviving = {unit["id"] for unit in work}
        for unit in work:
            unit["needs"] = [n for n in unit["needs"] if n in surviving]
    return work


def _effective_state(data: dict[str, Any], report: dict[str, Any]) -> tuple[str, str | None]:
    """Resolve (state, blocked_reason), warning on tree/status drift."""
    path = data["_path"]
    status = str(data.get("status", "Not Started")).strip().lower()
    if data.get("_archive"):
        if status != "completed":
            report["warnings"].append(
                f"{path}: archive file has status {status!r} (tree/status drift); imported as done"
            )
        return "done", None
    if status == "completed":
        report["warnings"].append(
            f"{path}: status Completed inside the open tree (tree/status drift); imported as done"
        )
        return "done", None
    state, blocked_reason = STATUS_MAP.get(status, ("planning", None))
    if status not in STATUS_MAP:
        report["warnings"].append(f"{path}: unknown status {status!r}; imported as planning")
    return state, blocked_reason


def _archive_title_description(data: dict[str, Any]) -> tuple[str, str]:
    """Title/description with archive-lenient fallbacks (legacy files miss both)."""
    stem = data["_path"].stem
    title = str(data.get("title") or "").strip() or f"Archived item {stem}"
    if len(title) < 5:
        title = f"Archived: {title}"
    description = str(data.get("description") or "").strip()
    if len(description) < 10:
        description = (description + "\n(no description recorded in archive)").strip()
    return title[:200], description


def _legacy_dep_candidates(data: dict[str, Any], report: dict[str, Any]) -> list[str]:
    """Extract dep slugs from the deprecated `dependencies:` forms (blocked_by paths)."""
    raw = data.get("dependencies")
    if not raw:
        return []
    report["counts"]["legacy_dependencies_field"] += 1
    if not isinstance(raw, dict):
        return []
    return [Path(str(entry)).stem for entry in raw.get("blocked_by") or []]


def _import_one(conn: sqlite3.Connection, actor: str, data: dict[str, Any], report: dict[str, Any]) -> bool:
    """Create one item (plus deferrals) from parsed YAML; True when imported."""
    path = data["_path"]
    is_archive = bool(data.get("_archive"))
    state, blocked_reason = _effective_state(data, report)
    priority = str(data.get("priority", "medium")).strip().lower()
    if priority not in PRIORITIES:
        report["warnings"].append(f"{path}: unknown priority {priority!r}; using medium")
        priority = "medium"
    work = _coerce_work_units(data, report, lenient=state == "done")
    if work is None:
        report["skipped"].append(str(path))
        return False
    if data.get("tasks") and not data.get("work"):
        report["counts"]["legacy_tasks_structure"] += 1
    scope_limit = data.get("scope_limit") or {}
    scope = [(kind, str(glob)) for kind in ("only_modify", "do_not_modify") for glob in scope_limit.get(kind) or []]
    created = str((data.get("metadata") or {}).get("created_date") or "") or None
    created_at = f"{created}T00:00:00Z" if created and "T" not in created else created
    completed = str(data.get("completed_date") or "") or None
    completed_at = f"{completed}T00:00:00Z" if completed and "T" not in completed else completed
    if is_archive:
        title, description = _archive_title_description(data)
    else:
        title = str(data.get("title", ""))[:200]
        description = str(data.get("description", ""))
    try:
        create_item(
            conn,
            actor,
            item_id=data["_id"],
            title=title,
            worktree=str(data.get("worktree") or path.parent.parent.name),
            priority=priority,
            description=description,
            category=data.get("category"),
            approach=data.get("approach"),
            state=state,
            blocked_reason=blocked_reason,
            created_at=created_at or utc_now(),
            completed_at=completed_at if state == "done" else None,
            work=work,
            scope=scope,
            verifications=_coerce_verifications(data.get("verification")),
            preserves=[str(p) for p in data.get("must_preserve") or []],
            anti_patterns=[_parse_anti_pattern(str(a)) for a in data.get("anti_patterns") or []],
            prior_art=[_parse_prior_art(str(p)) for p in data.get("prior_art") or []],
        )
    except TodoError as exc:
        report["skipped"].append(f"{path}: {exc}")
        return False
    for entry in data.get("deferred") or []:
        if isinstance(entry, dict):
            defer_work(
                conn,
                actor,
                data["_id"],
                str(entry.get("summary", "(no summary)")),
                str(entry.get("reason") or "(none recorded)"),
                allow_terminal=state == "done",
            )
    return True


def _assign_unique_ids(parsed: list[dict[str, Any]], report: dict[str, Any]) -> None:
    """Resolve id collisions: open-tree items win; archive duplicates get a suffix."""
    seen: set[str] = set()
    for data in parsed:
        item_id = data["_id"]
        if item_id in seen:
            base = f"{item_id}-archived" if data.get("_archive") else f"{item_id}-2"
            candidate, n = base, 2
            while candidate in seen:
                n += 1
                candidate = f"{base}-{n}"
            report["warnings"].append(f"{data['_path']}: id {item_id!r} already imported; stored as {candidate!r}")
            data["_id"] = candidate
        seen.add(data["_id"])


def import_yaml_tree(
    conn: sqlite3.Connection,
    actor: str,
    todo_dir: Path,
    done_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "imported": [],
        "skipped": [],
        "warnings": [],
        "counts": {
            "open_items": 0,
            "done_items": 0,
            "deps_resolved": 0,
            "deps_dangling": 0,
            "legacy_tasks_structure": 0,
            "legacy_dependencies_field": 0,
        },
    }
    parsed = _parse_yaml_tree(todo_dir, report)
    if done_dir is not None:
        archive = _parse_yaml_tree(done_dir, report)
        for data in archive:
            data["_archive"] = True
        parsed.extend(archive)
    _assign_unique_ids(parsed, report)
    known_ids = {data["_id"] for data in parsed}

    # Two passes so item_deps can point at any imported item, open or archived.
    deferred_deps: list[tuple[str, str, Path]] = []
    for data in parsed:
        if dry_run:
            if _coerce_work_units(data, report, lenient=bool(data.get("_archive"))) is None:
                report["skipped"].append(str(data["_path"]))
                continue
        elif not _import_one(conn, actor, data, report):
            continue
        for dep in (data.get("deps") or {}).get("needs") or []:
            deferred_deps.append((data["_id"], str(dep), data["_path"]))
        for dep in _legacy_dep_candidates(data, report):
            deferred_deps.append((data["_id"], dep, data["_path"]))
        report["imported"].append(data["_id"])
        report["counts"]["done_items" if data.get("_archive") else "open_items"] += 1

    if not dry_run:
        for item_id, dep, path in deferred_deps:
            if dep not in known_ids:
                report["counts"]["deps_dangling"] += 1
                report["warnings"].append(f"{path}: dependency {dep!r} not in import set (dangling); skipped")
                continue
            try:
                with _write_txn(conn):
                    add_item_dep(conn, item_id, dep)
                report["counts"]["deps_resolved"] += 1
            except TodoError as exc:
                report["warnings"].append(f"{path}: dependency {dep!r} rejected: {exc}")
    return report


# ---------------------------------------------------------------------------
# CLI


def _print_work_order(order: dict[str, Any]) -> None:
    print(f"== {order['id']} [{order['priority']}] {order['title']}")
    print(f"state={order['state']} worktree={order['worktree']} claimed_by={order['claimed_by'] or '-'}")
    if order["blocked_reason"]:
        print(f"BLOCKED: {order['blocked_reason']}")
    if order["scope"]:
        print("-- scope")
        for rule in order["scope"]:
            print(f"   {rule['kind']}: {rule['path_glob']}")
    if order["preserves"]:
        print("-- must preserve")
        for behavior in order["preserves"]:
            print(f"   {behavior}")
    if order["anti_patterns"]:
        print("-- anti-patterns")
        for anti in order["anti_patterns"]:
            print(f"   DO NOT {anti['dont']} — {anti['why']} — instead: {anti['instead']}")
    if order["verifications"]:
        print("-- verification ladder (narrowest first)")
        for ver in order["verifications"]:
            cmd = f" :: {ver['command']}" if ver["command"] else ""
            expected = f" — expected: {ver['expected']}" if ver.get("expected") else ""
            print(f"   {ver['seq']}. {ver['description']}{cmd}{expected}")
    ready = order.get("ready_units", [])
    blocked = order.get("blocked_units", [])
    print("-- ready units" if ready else "-- no ready units")
    for unit in ready:
        resume = ""
        if unit["status"] == "in_progress" and unit.get("started_branch"):
            resume = (
                f" (resumable: branch {unit['started_branch']}"
                f" @ {unit.get('started_worktree') or '?'}, since {unit.get('started_at')})"
            )
        print(f"   {unit['wid']} [{unit['status']}] {unit['summary']}{resume}")
    for unit in blocked:
        print(f"   {unit['wid']} BLOCKED on {','.join(unit['unmet'])}: {unit['summary']}")
    open_defs = [d for d in order["deferrals"] if d["resolution"] == "open"]
    if open_defs:
        print("-- open deferrals (must be promoted/dismissed before complete)")
        for deferral in open_defs:
            print(f"   #{deferral['id']} {deferral['summary']}")


def main(argv: list[str] | None = None) -> int:
    # Keep the historical shell wrapper and legacy implementation available
    # until a released standalone package has passed shadow-migration and human
    # cutover gates.  The opt-in route is intentionally environment-gated so a
    # normal BenchBox checkout cannot silently switch databases.
    if os.environ.get("BENCHBOX_TODO_DB_STANDALONE") == "1":
        from todo_db_standalone_compat import main as standalone_main

        return standalone_main(argv)
    parser = argparse.ArgumentParser(description="Database-backed TODO tracker")
    parser.add_argument(
        "--db",
        help="database path, or libsql://... / https://... URL for the hosted backend"
        " (default: <git main root>/.todo-db/todo.sqlite, or TODO_DB_URL when set)",
    )
    parser.add_argument("--actor", help="override actor identity for the audit log")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the database schema")

    p = sub.add_parser("import-yaml", help="import the legacy _project/TODO and _project/DONE trees")
    p.add_argument("--todo-dir", default=None)
    p.add_argument("--done-dir", default=None)
    p.add_argument("--skip-done", action="store_true", help="import only the open TODO tree")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true", help="print every skip/warning line")
    p.add_argument(
        "--replace",
        action="store_true",
        help="hosted backend only: clear the tracker tables before importing (same transaction)",
    )

    p = sub.add_parser("create", help="create an item (flags, or --from - for a JSON payload)")
    p.add_argument("id", nargs="?")
    p.add_argument(
        "--from", dest="from_source", metavar="-|FILE", help="read a JSON item payload from stdin (-) or a file"
    )
    p.add_argument("--title")
    p.add_argument("--worktree")
    p.add_argument("--priority", choices=PRIORITIES)
    p.add_argument("--description")
    p.add_argument("--category")
    p.add_argument("--approach")
    p.add_argument("--work", action="append", default=[], metavar="WID:SUMMARY[:needs=w1,w2]")
    p.add_argument("--needs", action="append", default=[], metavar="ITEM_ID")
    p.add_argument("--only-modify", action="append", default=[], metavar="GLOB")
    p.add_argument("--do-not-modify", action="append", default=[], metavar="GLOB")
    p.add_argument("--preserve", action="append", default=[], metavar="BEHAVIOR")
    p.add_argument(
        "--verify",
        action="append",
        default=[],
        metavar="DESC[::COMMAND[::EXPECTED]]",
        help=(
            "A verification rung. COMMAND is graded ONLY on its exit status, so it must be "
            "self-asserting: exit 0 if and only if the criterion holds. Assert on output by "
            "composing (`cmd | grep -q PATTERN`), and on expected failure by negating (`! cmd`). "
            "EXPECTED is human acceptance text and is never evaluated - it documents the rung, "
            "it does not check it."
        ),
    )

    for name, help_text in (
        ("show", "show one item"),
        ("claim", "claim an item and print its work order"),
        ("release", "release a claim"),
        ("deps", "show dependency edges"),
        ("unblock", "clear the blocked flag"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("id")
        if name == "show":
            p.add_argument("--json", action="store_true")

    p = sub.add_parser("start", help="mark a work unit in progress")
    p.add_argument("id")
    p.add_argument("wid")
    p = sub.add_parser("done", help="mark a work unit done (evidence required)")
    p.add_argument("id")
    p.add_argument("wid")
    p.add_argument("--evidence", required=True)

    p = sub.add_parser("defer", help="record deferred work on an item")
    p.add_argument("id")
    p.add_argument("--summary", required=True)
    p.add_argument("--reason", required=True)
    p = sub.add_parser("promote", help="promote a deferral to a planning item")
    p.add_argument("deferral_id", type=int)
    p.add_argument("--to-item", required=True)
    p.add_argument("--title")
    p.add_argument("--priority", default="medium", choices=PRIORITIES)
    p.add_argument("--worktree")
    p.add_argument("--description")
    p.add_argument("--category")
    p.add_argument("--approach")
    p.add_argument("--only-modify", action="append", default=[], metavar="GLOB")
    p.add_argument("--do-not-modify", action="append", default=[], metavar="GLOB")
    p.add_argument("--preserve", action="append", default=[], metavar="BEHAVIOR")
    p.add_argument("--verify", action="append", default=[], metavar="DESC[::COMMAND[::EXPECTED]]")
    p.add_argument("--work", action="append", default=[], metavar="WID:SUMMARY[:needs=w1,w2]")

    p = sub.add_parser("dismiss", help="dismiss a deferral with a reason")
    p.add_argument("deferral_id", type=int)
    p.add_argument("--reason", required=True)

    p = sub.add_parser("complete", help="complete an item (gated)")
    p.add_argument("id")
    p.add_argument("--pr", type=int)
    p = sub.add_parser("drop", help="drop an item with a reason")
    p.add_argument("id")
    p.add_argument("--reason", required=True)
    p = sub.add_parser("block", help="flag an item blocked")
    p.add_argument("id")
    p.add_argument("--reason", required=True)

    p = sub.add_parser("list", help="list items")
    p.add_argument("--state", choices=STATES)
    p.add_argument("--worktree")
    p.add_argument("--priority", choices=PRIORITIES)
    sub.add_parser("ready", help="project-wide ready queue")
    sub.add_parser("stats", help="counts by state/priority/worktree/deferral")

    p = sub.add_parser("check-scope", help="git diff --name-only vs scope rules")
    p.add_argument("id")
    p.add_argument("--base", help="diff BASE...HEAD instead of the working tree")
    p.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when the item has no scope rules (nothing was checked)",
    )

    p = sub.add_parser("verify", help="list or run verification steps")
    p.add_argument("id")
    p.add_argument("--run", type=int, metavar="SEQ")

    p = sub.add_parser("lint", help="mechanical quality checks")
    p.add_argument(
        "--include-done",
        action="store_true",
        help="lint every item including done/dropped (audit mode; implies --all)",
    )
    p.add_argument("id", nargs="?")
    p.add_argument("--all", action="store_true")

    p = sub.add_parser("sweep-stale", help="release expired claims")
    p.add_argument("--ttl-hours", type=float, default=DEFAULT_LEASE_TTL_HOURS)

    sub.add_parser("migrate", help="apply pending schema migrations to the database")

    p = sub.add_parser("config", help="list, get, or set per-database configuration")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")

    p = sub.add_parser("export", help="deterministic JSONL + markdown index")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--out", default=None)
    g.add_argument(
        "--snapshot",
        default=None,
        metavar="FILE",
        help=(
            "instead of the committed export, write a single-JSON raw table dump for "
            "todo-db's restore-legacy importer. Must be outside the repository."
        ),
    )

    pf = sub.add_parser("finding", help="findings domain: capture, sync, triage, promote")
    todo_findings.add_finding_subparsers(pf)

    args = parser.parse_args(argv)
    actor = args.actor or default_actor()

    # Zero-credential capture: `finding create` writes (and `finding candidates`
    # reads) only the local drafts directory -- no backend, no network, no token.
    # Handled before any backend resolution so capture works with no creds (R5).
    if args.command == "finding" and args.finding_command in todo_findings.FINDING_OFFLINE_SUBCOMMANDS:
        try:
            return todo_findings.run_offline(actor, args)
        except TodoError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    backend, implicit_default_local = _resolve_backend(args.db)
    _report_backend(backend, implicit_default_local=implicit_default_local)
    if implicit_default_local and _command_mutates_tracker(args):
        print(
            "error: refusing to write through the implicit local fallback; "
            "select a backend with --db, TODO_DB_PATH, or TODO_DB_URL",
            file=sys.stderr,
        )
        return 2
    if args.command == "migrate":
        # Must run before connect(): connect refuses an outdated schema.
        try:
            applied = migrate_backend(backend)
        except TodoError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except sqlite3.Error as exc:
            print(f"error: database failure: {_redacted(exc, _auth_token())}", file=sys.stderr)
            return 2
        if applied:
            print(f"applied migration(s) to v{', v'.join(str(v) for v in applied)}")
            return 0
    try:
        conn = connect_backend(backend, read_only=args.command in READ_ONLY_COMMANDS)
    except TodoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except sqlite3.Error as exc:
        print(f"error: database failure: {_redacted(exc, _auth_token())}", file=sys.stderr)
        return 2

    try:
        return _dispatch(conn, actor, args)
    except TodoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except sqlite3.Error as exc:
        # SQLITE_BUSY, lock contention, network drops mid-statement: a clean
        # exit 2 with the token redacted, never a traceback.
        print(f"error: database failure: {_redacted(exc, _auth_token())}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        # Downstream pipe closed early (e.g. `todo ready | head`); not an error.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 0
    finally:
        conn.close()


def _cmd_init(conn, actor, args):
    print(f"schema v{SCHEMA_VERSION} ready")
    return 0


def _print_capped(label: str, lines: list[str], verbose: bool, cap: int = 25) -> None:
    shown = lines if verbose else lines[:cap]
    for line in shown:
        print(f"  {label}: {line}")
    if len(lines) > len(shown):
        print(f"  {label}: ... +{len(lines) - len(shown)} more (use --verbose)")


def _print_import_report(report: dict[str, Any], verbose: bool) -> None:
    print(
        f"imported: {len(report['imported'])}  skipped: {len(report['skipped'])}  warnings: {len(report['warnings'])}"
    )
    print(f"  counts: {json.dumps(report['counts'], sort_keys=True)}")
    _print_capped("skip", report["skipped"], verbose)
    _print_capped("warn", report["warnings"], verbose)


def _cmd_import_yaml(conn, actor, args):
    todo_dir = Path(args.todo_dir) if args.todo_dir else git_root() / "_project" / "TODO"
    done_dir = None
    if not args.skip_done:
        done_dir = Path(args.done_dir) if args.done_dir else git_root() / "_project" / "DONE"
    backend = resolve_backend(args.db)
    hosted = isinstance(backend, str)
    if args.replace and not (hosted and not args.dry_run):
        raise TodoError("--replace only applies to a live import into the hosted backend")
    if hosted and not args.dry_run:
        # Bulk path: stage through the exact same gated code into a temp local
        # database, then copy rows to the primary in one batched transaction.
        # The row-by-row path is ~2.5h over the network; this is seconds.
        # Target-state enforcement (empty unless --replace) happens INSIDE the
        # transfer's BEGIN IMMEDIATE transaction, so no concurrent writer can
        # slip rows in between a pre-check and the transfer.
        token = os.environ.get("TODO_DB_AUTH_TOKEN") or ""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            staging = connect(Path(tmp) / "staging.sqlite")
            try:
                report = import_yaml_tree(staging, actor, todo_dir, done_dir=done_dir, dry_run=False)
                summary = bulk_transfer(
                    staging,
                    backend,
                    token,
                    replace=args.replace,
                    require_empty=not args.replace,
                )
            finally:
                staging.close()
        _print_import_report(report, args.verbose)
        print(f"  bulk transfer: {summary['rows']} row(s) in {summary['batches']} batch(es)")
        return 0
    report = import_yaml_tree(conn, actor, todo_dir, done_dir=done_dir, dry_run=args.dry_run)
    _print_import_report(report, args.verbose)
    return 0


def _parse_work_flag(specs: list[str]) -> list[dict[str, Any]]:
    work = []
    for spec in specs:
        parts = spec.split(":", 2)
        if len(parts) < 2:
            raise TodoError(f"--work expects WID:SUMMARY[:needs=...], got {spec!r}")
        needs = []
        if len(parts) == 3 and parts[2].startswith("needs="):
            needs = [n for n in parts[2][len("needs=") :].split(",") if n]
        work.append({"id": parts[0], "summary": parts[1], "needs": needs})
    return work


def _parse_verify_flag(specs: list[str]) -> list[dict[str, str]]:
    verifications = []
    for spec in specs:
        fields = spec.split("::")
        entry = {"description": fields[0]}
        if len(fields) > 1:
            entry["command"] = fields[1]
        if len(fields) > 2:
            entry["expected"] = fields[2]
        verifications.append(entry)
    return verifications


def create_from_payload(conn: sqlite3.Connection, actor: str, payload: dict[str, Any]) -> str:
    """Create an item from a structured JSON payload (the `create --from` path)."""
    for required in ("id", "title", "worktree", "priority", "description"):
        if not payload.get(required):
            raise TodoError(f"payload missing required field: {required!r}")

    def _triple(entry: Any, keys: tuple[str, str, str]) -> tuple[str, str, str]:
        if isinstance(entry, dict):
            try:
                return tuple(str(entry[k]) for k in keys)  # type: ignore[return-value]
            except KeyError as exc:
                raise TodoError(f"payload entry {entry!r} missing key {exc}") from exc
        return tuple(str(v) for v in entry)  # type: ignore[return-value]

    scope_map = payload.get("scope") or {}
    scope = [(kind, str(glob)) for kind in ("only_modify", "do_not_modify") for glob in scope_map.get(kind) or []]
    create_item(
        conn,
        actor,
        item_id=str(payload["id"]),
        title=str(payload["title"]),
        worktree=str(payload["worktree"]),
        priority=str(payload["priority"]),
        description=str(payload["description"]),
        category=payload.get("category"),
        approach=payload.get("approach"),
        work=payload.get("work") or [],
        deps=[str(d) for d in payload.get("deps") or []],
        scope=scope,
        verifications=payload.get("verifications") or [],
        preserves=[str(p) for p in payload.get("preserves") or []],
        anti_patterns=[_triple(e, ("dont", "why", "instead")) for e in payload.get("anti_patterns") or []],
        prior_art=[_triple(e, ("path", "concept", "decision")) for e in payload.get("prior_art") or []],
    )
    return str(payload["id"])


def _cmd_create(conn, actor, args):
    if args.from_source:
        if args.from_source == "-":
            raw = sys.stdin.read()
        else:
            raw = Path(args.from_source).read_text(encoding="utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TodoError(f"--from payload is not valid JSON: {exc}") from exc
        if args.id and not payload.get("id"):
            payload["id"] = args.id
        item_id = create_from_payload(conn, actor, payload)
        print(f"created {item_id}")
        return 0
    missing = [flag for flag in ("id", "title", "worktree", "priority", "description") if not getattr(args, flag)]
    if missing:
        raise TodoError(f"create requires {', '.join(missing)} (or use --from - with a JSON payload)")
    scope = [("only_modify", g) for g in args.only_modify]
    scope += [("do_not_modify", g) for g in args.do_not_modify]
    create_item(
        conn,
        actor,
        item_id=args.id,
        title=args.title,
        worktree=args.worktree,
        priority=args.priority,
        description=args.description,
        category=args.category,
        approach=args.approach,
        work=_parse_work_flag(args.work),
        deps=args.needs,
        scope=scope,
        verifications=_parse_verify_flag(args.verify),
        preserves=args.preserve,
    )
    print(f"created {args.id}")
    return 0


def _cmd_show(conn, actor, args):
    if args.json:
        print(json.dumps(get_item(conn, args.id), indent=2, sort_keys=True))
    else:
        _print_work_order(work_order(conn, args.id))
    return 0


def _cmd_claim(conn, actor, args):
    _print_work_order(claim_item(conn, actor, args.id))
    return 0


def _cmd_release(conn, actor, args):
    release_item(conn, actor, args.id)
    print(f"released {args.id}")
    return 0


def _cmd_start(conn, actor, args):
    start_unit(conn, actor, args.id, args.wid)
    print(f"{args.id}:{args.wid} in_progress")
    return 0


def _cmd_done(conn, actor, args):
    done_unit(conn, actor, args.id, args.wid, args.evidence)
    print(f"{args.id}:{args.wid} done")
    return 0


def _cmd_defer(conn, actor, args):
    deferral_id = defer_work(conn, actor, args.id, args.summary, args.reason)
    print(f"deferral #{deferral_id} recorded on {args.id} (must be promoted or dismissed before complete)")
    return 0


def _cmd_promote(conn, actor, args):
    promote_deferral(
        conn,
        actor,
        args.deferral_id,
        new_item_id=args.to_item,
        title=args.title,
        priority=args.priority,
        worktree=args.worktree,
        description=args.description,
        category=args.category,
        approach=args.approach,
        scope=([("only_modify", g) for g in args.only_modify] + [("do_not_modify", g) for g in args.do_not_modify])
        or None,
        verifications=_parse_verify_flag(args.verify) if args.verify else None,
        preserves=args.preserve or None,
        work=_parse_work_flag(args.work) if args.work else None,
    )
    print(f"deferral #{args.deferral_id} promoted to {args.to_item}")
    return 0


def _cmd_dismiss(conn, actor, args):
    dismiss_deferral(conn, actor, args.deferral_id, args.reason)
    print(f"deferral #{args.deferral_id} dismissed")
    return 0


def _cmd_complete(conn, actor, args):
    complete_item(conn, actor, args.id, args.pr)
    print(f"{args.id} done" + (f" (PR #{args.pr})" if args.pr else ""))
    return 0


def _cmd_drop(conn, actor, args):
    drop_item(conn, actor, args.id, args.reason)
    print(f"{args.id} dropped")
    return 0


def _cmd_block(conn, actor, args):
    block_item(conn, actor, args.id, args.reason)
    print(f"{args.id} blocked")
    return 0


def _cmd_unblock(conn, actor, args):
    unblock_item(conn, actor, args.id)
    print(f"{args.id} unblocked")
    return 0


def _cmd_deps(conn, actor, args):
    item = get_item(conn, args.id)
    for dep in item["deps"]:
        state = conn.execute("SELECT state FROM items WHERE id = ?", (dep,)).fetchone()
        print(f"{args.id} needs {dep} [{state['state'] if state else '?'}]")
    if not item["deps"]:
        print(f"{args.id} has no dependencies")
    return 0


def _cmd_list(conn, actor, args):
    query = "SELECT id, state, priority, worktree, title FROM items WHERE 1=1"
    params: list[Any] = []
    for field in ("state", "worktree", "priority"):
        value = getattr(args, field)
        if value:
            query += f" AND {field} = ?"
            params.append(value)
    query += " ORDER BY state, priority, id"
    for row in conn.execute(query, params):
        print(f"{row['id']:55s} {row['state']:8s} {row['priority']:12s} {row['worktree']}")
    return 0


_BANNER_ASCII = {ord("→"): "->", ord("—"): "--"}


def _emit_findings_banner(conn, open_count: int | None = None) -> None:
    """Print the untriaged-findings hint to stderr, never stdout. Best-effort: a
    hint must never break ``ready``/``stats`` core output, so any failure here is
    swallowed after the stdout contract is met.

    ``open_count`` lets a caller that already counted findings (``stats``) pass
    the number through instead of paying a second aggregate.

    Two stderr hazards are handled explicitly, because the guard alone cannot:

    * ``sys.stderr is None`` -- when fd 2 is closed (``2>&-``) CPython sets it to
      None and ``print(..., file=None)`` falls back to *stdout*, which would put
      the hint in the machine-readable stream. Bail out instead.
    * a strict non-UTF-8 stream -- the banner carries ``->``/``--`` as ``→``/``—``.
      CPython's default stderr uses ``errors='backslashreplace'`` and C locales
      get coerced to UTF-8 (PEP 538), so this needs an explicitly strict stream
      (``PYTHONIOENCODING=ascii:strict``, or a ``reconfigure``d stderr) to bite --
      uncommon, but cheap to survive: fall back to an ASCII transliteration
      rather than losing the hint."""
    if sys.stderr is None:
        return
    try:
        banner = todo_findings.surfacing_banner(conn, open_count=open_count)
        if not banner:
            return
        try:
            print(banner, file=sys.stderr)
        except UnicodeEncodeError:
            print(banner.translate(_BANNER_ASCII), file=sys.stderr)
    except Exception:
        return


def _cmd_ready(conn, actor, args):
    for item in ready_items(conn, actor):
        claim_note = " (claimed by you)" if item["claimed_by"] == actor else ""
        print(f"{item['id']:55s} {item['priority']:12s} {item['worktree']}{claim_note}")
    _emit_findings_banner(conn)
    return 0


def _cmd_stats(conn, actor, args):
    computed = stats(conn)
    print(json.dumps(computed, indent=2, sort_keys=True))
    # Reuse the disposition breakdown already computed above rather than issuing
    # a second `count(*) WHERE disposition='open'` for the banner.
    _emit_findings_banner(conn, open_count=computed["findings_by_disposition"].get("open", 0))
    return 0


def _cmd_check_scope(conn, actor, args):
    item = get_item(conn, args.id)
    files = changed_files(args.base)

    # An item with no scope rules has nothing to violate, so check_paths()
    # returns clean and the command used to print "scope OK" -- announcing a
    # passed check while performing none. Every item promoted before the
    # guardrail flags existed has empty scope, so this reported OK on diffs it
    # had never looked at. Say what actually happened instead.
    if not item["scope"]:
        print(f"SCOPE_UNCHECKED: no scope rules on {args.id!r}; {len(files)} changed file(s) were not checked")
        return 1 if getattr(args, "strict", False) else 0

    violations = check_paths(files, item["scope"])
    for violation in violations:
        print(violation)
    if violations:
        return 1
    print(f"scope OK ({len(files)} changed file(s))")
    return 0


def _cmd_verify(conn, actor, args):
    if args.run is not None:
        result, output = run_verification(conn, actor, args.id, args.run)
        tail = "\n".join(output.splitlines()[-10:])
        print(f"seq {args.run}: {result}")
        if tail:
            print(tail)
        return 0 if result == "pass" else 1
    item = get_item(conn, args.id)
    for ver in item["verifications"]:
        status = f" [{ver['last_result']} @ {ver['last_run']}]" if ver["last_result"] else ""
        cmd = f" :: {ver['command']}" if ver["command"] else ""
        expected = f" — expected: {ver['expected']}" if ver.get("expected") else ""
        print(f"{ver['seq']}. {ver['description']}{cmd}{expected}{status}")
    return 0


def _cmd_lint(conn, actor, args):
    # --all lints the open backlog, which is what a triage pass wants. An audit
    # of *authored quality* needs the finished ones too: a rung whose command
    # can never express its expectation is invisible to --all once the item is
    # done, and that is exactly where such rungs accumulate -- every offender
    # found in the 2026-07-26 sweep sat on a done item.
    # getattr: programmatic callers construct a minimal namespace, so a new
    # optional flag must not become a required attribute.
    include_done = getattr(args, "include_done", False)
    if args.all or include_done:
        states = "('planning','active','done','dropped')" if include_done else "('planning','active')"
        targets = [row["id"] for row in conn.execute(f"SELECT id FROM items WHERE state IN {states} ORDER BY id")]
    else:
        targets = [args.id]
    if targets == [None]:
        raise TodoError("lint requires an item id or --all")
    total = 0
    for target in targets:
        findings = lint_item(conn, target)
        total += len(findings)
        for finding in findings:
            print(f"{target}: {finding}")
    print(f"{total} finding(s) across {len(targets)} item(s)")
    return 1 if total else 0


def _cmd_sweep_stale(conn, actor, args):
    released = sweep_stale(conn, actor, args.ttl_hours)
    print(f"released {len(released)} stale claim(s)" + (f": {', '.join(released)}" if released else ""))
    return 0


def _cmd_export(conn, actor, args):
    if args.snapshot:
        path = write_snapshot(conn, Path(args.snapshot))
        print(f"wrote {path}")
        return 0
    out_dir = Path(args.out) if args.out else git_main_root() / ".todo-db" / "export"
    jsonl_path, events_path, index_path = write_export(conn, out_dir)
    print(f"wrote {jsonl_path}, {events_path} and {index_path}")
    return 0


def _cmd_config(conn, actor, args):
    if args.key is None:
        for key in sorted(CONFIG_KEYS):
            print(f"{key}={get_config(conn, key)}")
    elif args.value is None:
        print(get_config(conn, args.key))
    else:
        set_config(conn, actor, args.key, args.value)
        print(f"{args.key}={args.value}")
    return 0


def _cmd_migrate(conn, actor, args):
    # Reached only when the DB is already current (main() migrates before
    # connecting for this command); report the no-op for clarity.
    print(f"schema v{SCHEMA_VERSION}: up to date")
    return 0


_HANDLERS = {
    "init": _cmd_init,
    "import-yaml": _cmd_import_yaml,
    "create": _cmd_create,
    "show": _cmd_show,
    "claim": _cmd_claim,
    "release": _cmd_release,
    "start": _cmd_start,
    "done": _cmd_done,
    "defer": _cmd_defer,
    "promote": _cmd_promote,
    "dismiss": _cmd_dismiss,
    "complete": _cmd_complete,
    "drop": _cmd_drop,
    "block": _cmd_block,
    "unblock": _cmd_unblock,
    "deps": _cmd_deps,
    "list": _cmd_list,
    "ready": _cmd_ready,
    "stats": _cmd_stats,
    "check-scope": _cmd_check_scope,
    "verify": _cmd_verify,
    "lint": _cmd_lint,
    "sweep-stale": _cmd_sweep_stale,
    "export": _cmd_export,
    "migrate": _cmd_migrate,
    "config": _cmd_config,
}


def _dispatch(conn: sqlite3.Connection, actor: str, args: argparse.Namespace) -> int:
    # `finding` is dispatched by name (not via _HANDLERS) so this module never
    # references a todo_findings symbol at load time -- keeping the todo_db <->
    # todo_findings import cycle resolvable regardless of load order.
    if args.command == "finding":
        return todo_findings.dispatch_finding(conn, actor, args)
    return _HANDLERS[args.command](conn, actor, args)


if __name__ == "__main__":
    sys.exit(main())
