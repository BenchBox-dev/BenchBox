from __future__ import annotations

import importlib.util
import json
import zipfile
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
    wheels = sorted((root / "_project/scripts/vendor").glob("todo_db-*-py3-none-any.whl"))
    assert len(wheels) == 1
    return {
        "package_wheel": wheels[0],
        "wrapper": root / "_project/scripts/todo",
        "inventory": root / "_project/todo-schema-migrations.json",
    }


def _wheel(path: Path, *, schema: int = 5, migrations: tuple[int, ...] = (1, 2, 3, 4, 5)) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("todo_db/database.py", f"SCHEMA_VERSION = {schema}\n")
        for revision in migrations:
            archive.writestr(f"todo_db/migrations/{revision:03d}_migration.sql", "SELECT 1;\n")
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
    paths = _contract_paths()
    with pytest.raises(check.SchemaMigrationError, match="must be contiguous"):
        check.validate_contract(
            package_wheel=_wheel(tmp_path / "todo_db.whl", migrations=(1, 2, 4, 5)),
            wrapper=paths["wrapper"],
            inventory=paths["inventory"],
        )


def test_wheel_must_expose_literal_schema_version(tmp_path: Path) -> None:
    wheel = tmp_path / "todo_db.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("todo_db/database.py", "SCHEMA_VERSION = current_schema()\n")
    paths = _contract_paths()
    with pytest.raises(check.SchemaMigrationError, match="integer literal"):
        check.validate_contract(package_wheel=wheel, wrapper=paths["wrapper"], inventory=paths["inventory"])


def test_corrupt_wheel_fails_closed(tmp_path: Path) -> None:
    wheel = tmp_path / "todo_db.whl"
    wheel.write_text("not a zip", encoding="utf-8")
    paths = _contract_paths()
    with pytest.raises(check.SchemaMigrationError, match="cannot inspect"):
        check.validate_contract(package_wheel=wheel, wrapper=paths["wrapper"], inventory=paths["inventory"])


def test_wrapper_schema_must_match_package(tmp_path: Path) -> None:
    wrapper = tmp_path / "todo"
    wrapper.write_text("TODO_SCHEMA_VERSION=4\n", encoding="utf-8")
    paths = _contract_paths()
    with pytest.raises(check.SchemaMigrationError, match="does not match package schema 5"):
        check.validate_contract(package_wheel=paths["package_wheel"], wrapper=wrapper, inventory=paths["inventory"])


def test_inventory_schema_must_match_package(tmp_path: Path) -> None:
    paths = _contract_paths()
    inventory = _inventory(tmp_path, lambda record: record.update(schema_version=4))
    with pytest.raises(check.SchemaMigrationError, match="does not match package schema 5"):
        check.validate_contract(package_wheel=paths["package_wheel"], wrapper=paths["wrapper"], inventory=inventory)


def test_current_deployment_revision_requires_evidence(tmp_path: Path) -> None:
    paths = _contract_paths()
    inventory = _inventory(tmp_path, lambda record: record["migrations"][-1].pop("deployment_evidence"))
    with pytest.raises(check.SchemaMigrationError, match="needs deployment_evidence"):
        check.validate_contract(package_wheel=paths["package_wheel"], wrapper=paths["wrapper"], inventory=inventory)


def test_inventory_rejects_credentials(tmp_path: Path) -> None:
    paths = _contract_paths()
    inventory = _inventory(
        tmp_path,
        lambda record: record["migrations"][-1].update(summary="token=secret"),
    )
    with pytest.raises(check.SchemaMigrationError, match="must not contain backend URLs or tokens"):
        check.validate_contract(package_wheel=paths["package_wheel"], wrapper=paths["wrapper"], inventory=inventory)
