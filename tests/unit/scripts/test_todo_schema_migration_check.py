from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "_project" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import todo_db  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.fast]

SPEC = importlib.util.spec_from_file_location(
    "todo_schema_migration_check", SCRIPTS_DIR / "todo_schema_migration_check.py"
)
assert SPEC and SPEC.loader
todo_schema_migration_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(todo_schema_migration_check)


def _contract_paths(root: Path = REPO_ROOT) -> dict[str, Path]:
    return {
        "tracker": root / "_project/scripts/todo_db.py",
        "wrapper": root / "_project/scripts/todo",
        "inventory": root / "_project/todo-schema-migrations.json",
    }


def test_todo_schema_migration_contract_is_current() -> None:
    todo_schema_migration_check.validate_contract(**_contract_paths())


def test_todo_schema_migration_contract_rejects_cli_bump_without_migration(tmp_path: Path) -> None:
    tracker = tmp_path / "todo_db.py"
    tracker.write_text(
        "SCHEMA_VERSION = 5\nMIGRATIONS = {2: ['a'], 3: ['b'], 4: ['c']}\n"
        "MIGRATION_STATEMENT_COUNTS = {2: 1, 3: 1, 4: 1}\n",
        encoding="utf-8",
    )
    paths = _contract_paths()
    with pytest.raises(todo_schema_migration_check.SchemaMigrationError, match="contiguous"):
        todo_schema_migration_check.validate_contract(
            tracker=tracker, wrapper=paths["wrapper"], inventory=paths["inventory"]
        )


def test_todo_schema_migration_contract_rejects_wrapper_revision_skew(tmp_path: Path) -> None:
    wrapper = tmp_path / "todo"
    wrapper.write_text("TODO_SCHEMA_VERSION=3\n", encoding="utf-8")
    paths = _contract_paths()
    with pytest.raises(todo_schema_migration_check.SchemaMigrationError, match="does not match CLI"):
        todo_schema_migration_check.validate_contract(
            tracker=paths["tracker"], wrapper=wrapper, inventory=paths["inventory"]
        )


def test_todo_schema_migration_contract_requires_current_deployment_evidence(tmp_path: Path) -> None:
    inventory = tmp_path / "migrations.json"
    record = json.loads(_contract_paths()["inventory"].read_text(encoding="utf-8"))
    record["migrations"][-1].pop("deployment_evidence")
    inventory.write_text(json.dumps(record), encoding="utf-8")
    paths = _contract_paths()
    with pytest.raises(todo_schema_migration_check.SchemaMigrationError, match="deployment_evidence"):
        todo_schema_migration_check.validate_contract(
            tracker=paths["tracker"], wrapper=paths["wrapper"], inventory=inventory
        )


def test_todo_schema_migration_contract_requires_statement_count_inventory(tmp_path: Path) -> None:
    inventory = tmp_path / "migrations.json"
    record = json.loads(_contract_paths()["inventory"].read_text(encoding="utf-8"))
    record["migrations"][-1].pop("statement_count")
    inventory.write_text(json.dumps(record), encoding="utf-8")
    paths = _contract_paths()

    with pytest.raises(todo_schema_migration_check.SchemaMigrationError, match="statement_count"):
        todo_schema_migration_check.validate_contract(
            tracker=paths["tracker"], wrapper=paths["wrapper"], inventory=inventory
        )


def test_todo_schema_migration_contract_requires_static_count_contract(tmp_path: Path) -> None:
    tracker = tmp_path / "todo_db.py"
    tracker.write_text(
        "SCHEMA_VERSION = 2\nMIGRATIONS = {2: build_migration()}\n",
        encoding="utf-8",
    )
    paths = _contract_paths()

    with pytest.raises(todo_schema_migration_check.SchemaMigrationError, match="MIGRATION_STATEMENT_COUNTS"):
        todo_schema_migration_check.validate_contract(
            tracker=tracker, wrapper=paths["wrapper"], inventory=paths["inventory"]
        )


def _database_at_revision(path: Path, revision: int) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (str(revision),))
    conn.commit()
    conn.close()


def test_todo_schema_revision_cli_ahead_refuses_read_connection(tmp_path: Path) -> None:
    database = tmp_path / "older.sqlite"
    _database_at_revision(database, todo_db.SCHEMA_VERSION - 1)
    with pytest.raises(todo_db.TodoError, match=r"run `todo migrate`"):
        todo_db.connect(database)


def test_todo_schema_revision_database_ahead_refuses_unknown_revision(tmp_path: Path) -> None:
    database = tmp_path / "newer.sqlite"
    _database_at_revision(database, todo_db.SCHEMA_VERSION + 1)
    with pytest.raises(todo_db.TodoError, match="newer than this CLI"):
        todo_db.connect(database)
    with pytest.raises(todo_db.TodoError, match="newer than this CLI"):
        todo_db.migrate_db(database)


def test_todo_schema_migration_revision_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "revision-3.sqlite"
    _database_at_revision(database, 3)
    monkeypatch.setitem(
        todo_db.MIGRATIONS,
        4,
        ["CREATE TABLE migration_probe (value TEXT)", "NOT VALID SQL"],
    )

    with pytest.raises(sqlite3.OperationalError):
        todo_db.migrate_db(database)

    conn = sqlite3.connect(database)
    version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    probe = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='migration_probe'").fetchone()
    conn.close()
    assert version == "3"
    assert probe is None


def _inventory_with(tmp_path: Path, mutate) -> Path:
    record = json.loads(_contract_paths()["inventory"].read_text(encoding="utf-8"))
    mutate(record)
    inventory = tmp_path / "migrations.json"
    inventory.write_text(json.dumps(record), encoding="utf-8")
    return inventory


def _expect(inventory: Path, match: str) -> None:
    paths = _contract_paths()
    with pytest.raises(todo_schema_migration_check.SchemaMigrationError, match=match):
        todo_schema_migration_check.validate_contract(
            tracker=paths["tracker"], wrapper=paths["wrapper"], inventory=inventory
        )


def test_an_empty_migration_is_rejected_unless_declared_a_fence(tmp_path: Path) -> None:
    """The guard this relaxation must not lose: a migration that ends up empty by
    accident -- a builder returning [] -- still fails closed."""

    def undeclare(record):
        record["migrations"][-1].pop("kind")

    _expect(_inventory_with(tmp_path, undeclare), "has no statements")


def test_a_fence_may_not_smuggle_ddl(tmp_path: Path) -> None:
    """The other direction: "fence" must not become a way to ship unreviewed DDL
    under a label that says there is none."""

    def claim_fence(record):
        record["migrations"][-2]["kind"] = "fence"

    _expect(_inventory_with(tmp_path, claim_fence), "must carry no DDL")


def test_a_fence_needs_a_written_rationale(tmp_path: Path) -> None:
    def blank_rationale(record):
        record["migrations"][-1]["fence_rationale"] = "   "

    _expect(_inventory_with(tmp_path, blank_rationale), "fence_rationale")


def test_a_negative_statement_count_is_never_legal(tmp_path: Path) -> None:
    """Relaxing `<= 0` to `< 0` must not have opened the door wider than intended."""
    tracker = tmp_path / "todo_db.py"
    tracker.write_text(
        "SCHEMA_VERSION = 2\nMIGRATIONS = {2: ['a']}\nMIGRATION_STATEMENT_COUNTS = {2: -1}\n",
        encoding="utf-8",
    )
    paths = _contract_paths()
    with pytest.raises(todo_schema_migration_check.SchemaMigrationError, match="non-negative"):
        todo_schema_migration_check.validate_contract(
            tracker=tracker, wrapper=paths["wrapper"], inventory=paths["inventory"]
        )
