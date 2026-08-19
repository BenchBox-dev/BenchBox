from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "_project/scripts/todo_schema_migration_check.py"
SPEC = importlib.util.spec_from_file_location("todo_schema_migration_check", SCRIPT)
assert SPEC and SPEC.loader
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _contract_paths(root: Path = REPO_ROOT) -> dict[str, Path]:
    return {
        "package_dir": check._installed_package_dir(root / "_project/scripts"),
        "wrapper": root / "_project/scripts/todo",
        "inventory": root / "_project/todo-schema-migrations.json",
        "repo_root": root,
    }


def _package(
    path: Path,
    *,
    schema: int = 6,
    migrations: tuple[int, ...] = (1, 2, 3, 4, 5, 6),
    database: str | None = None,
) -> Path:
    """Build a fake installed todo_db package tree."""
    (path / "migrations").mkdir(parents=True)
    (path / "database.py").write_text(database or f"SCHEMA_VERSION = {schema}\n", encoding="utf-8")
    for revision in migrations:
        (path / "migrations" / f"{revision:03d}_migration.sql").write_text("SELECT 1;\n", encoding="utf-8")
    return path


def _inventory(tmp_path: Path, mutate) -> Path:
    record = json.loads(_contract_paths()["inventory"].read_text(encoding="utf-8"))
    mutate(record)
    path = tmp_path / "todo-schema-migrations.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_package_schema_migration_contract_is_current() -> None:
    check.validate_contract(**_contract_paths())


def test_package_migrations_must_be_contiguous(tmp_path: Path) -> None:
    paths = _contract_paths() | {"package_dir": _package(tmp_path / "todo_db", migrations=(1, 2, 4, 5, 6))}
    with pytest.raises(check.SchemaMigrationError, match="must be contiguous"):
        check.validate_contract(**paths)


def test_package_must_expose_literal_schema_version(tmp_path: Path) -> None:
    package = _package(tmp_path / "todo_db", database="SCHEMA_VERSION = current_schema()\n")
    with pytest.raises(check.SchemaMigrationError, match="integer literal"):
        check.validate_contract(**(_contract_paths() | {"package_dir": package}))


def test_missing_package_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(check.SchemaMigrationError, match="cannot inspect"):
        check.validate_contract(**(_contract_paths() | {"package_dir": tmp_path / "absent"}))


def test_unsynced_venv_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(check.SchemaMigrationError, match="run `uv sync"):
        check._installed_package_dir(tmp_path)


def test_wrapper_schema_must_match_package(tmp_path: Path) -> None:
    wrapper = tmp_path / "todo"
    wrapper.write_text("TODO_SCHEMA_VERSION=4\n", encoding="utf-8")
    with pytest.raises(check.SchemaMigrationError, match="does not match package schema 6"):
        check.validate_contract(**(_contract_paths() | {"wrapper": wrapper}))


def test_inventory_schema_must_match_package(tmp_path: Path) -> None:
    paths = _contract_paths()
    inventory = _inventory(tmp_path, lambda record: record.update(schema_version=4))
    with pytest.raises(check.SchemaMigrationError, match="does not match package schema 6"):
        check.validate_contract(**(paths | {"inventory": inventory}))


def test_current_deployment_revision_requires_evidence(tmp_path: Path) -> None:
    paths = _contract_paths()
    inventory = _inventory(tmp_path, lambda record: record["migrations"][-1].pop("deployment_evidence"))
    with pytest.raises(check.SchemaMigrationError, match="needs deployment_evidence"):
        check.validate_contract(**(paths | {"inventory": inventory}))


def test_inventory_rejects_credentials(tmp_path: Path) -> None:
    paths = _contract_paths()
    inventory = _inventory(
        tmp_path,
        lambda record: record["migrations"][-1].update(summary="token=secret"),
    )
    with pytest.raises(check.SchemaMigrationError, match="must not contain backend URLs or tokens"):
        check.validate_contract(**(paths | {"inventory": inventory}))
