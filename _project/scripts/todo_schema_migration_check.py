#!/usr/bin/env python3
"""Fail closed when the locked todo-db package or rollout record drift.

This guard is stdlib-only so the required ``ci-paths`` job can inspect the
vendored wheel before dependency installation. Package migration correctness
belongs to todo-db; BenchBox pins the exact release, schema handshake, and
deployment evidence that make that release safe to consume.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import zipfile
from pathlib import Path


class SchemaMigrationError(ValueError):
    """The locked package/schema contract is incomplete or inconsistent."""


def _integer_assignment(source_text: str, name: str, source: Path) -> int:
    module = ast.parse(source_text, filename=str(source))
    for node in module.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, int):
                    return value.value
                raise SchemaMigrationError(f"{source}: {name} must be an integer literal")
    raise SchemaMigrationError(f"{source}: missing {name} assignment")


def _package_contract(wheel: Path) -> tuple[int, list[int]]:
    try:
        with zipfile.ZipFile(wheel) as archive:
            database_source = archive.read("todo_db/database.py").decode("utf-8")
            versions = sorted(
                int(match.group(1))
                for name in archive.namelist()
                if (match := re.fullmatch(r"todo_db/migrations/([0-9]{3})_[^/]+\.sql", name))
            )
    except (OSError, KeyError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise SchemaMigrationError(f"{wheel}: cannot inspect locked todo-db wheel: {exc}") from exc
    schema_version = _integer_assignment(database_source, "SCHEMA_VERSION", wheel)
    expected = list(range(1, schema_version + 1))
    if versions != expected:
        raise SchemaMigrationError(f"{wheel}: package migrations {versions!r} must be contiguous {expected!r}")
    return schema_version, versions


def validate_contract(*, package_wheel: Path, inventory: Path) -> None:
    schema_version, _ = _package_contract(package_wheel)

    try:
        inventory_text = inventory.read_text(encoding="utf-8")
        record = json.loads(inventory_text)
    except (json.JSONDecodeError, OSError) as exc:
        raise SchemaMigrationError(f"{inventory}: cannot read migration inventory: {exc}") from exc
    if re.search(r"(?i)(?:libsql://|TODO_DB_AUTH_TOKEN|(?:auth[_-]?)?token\s*[:=])", inventory_text):
        raise SchemaMigrationError(f"{inventory}: migration inventory must not contain backend URLs or tokens")
    if record.get("schema_version") != schema_version:
        raise SchemaMigrationError(
            f"{inventory}: schema_version={record.get('schema_version')!r} does not match package schema {schema_version}"
        )
    entries = record.get("migrations")
    if not isinstance(entries, list) or not entries:
        raise SchemaMigrationError(f"{inventory}: migrations must be a non-empty list")
    revisions = [entry.get("revision") for entry in entries if isinstance(entry, dict)]
    if len(revisions) != len(entries) or revisions != list(range(2, schema_version + 1)):
        raise SchemaMigrationError(
            f"{inventory}: BenchBox deployment revisions {revisions!r} must cover 2..{schema_version}"
        )
    for entry in entries:
        revision = entry["revision"]
        for field in ("summary", "deployment_order"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise SchemaMigrationError(f"{inventory}: revision {revision} needs non-empty {field}")
    evidence = entries[-1].get("deployment_evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        raise SchemaMigrationError(f"{inventory}: current revision {schema_version} needs deployment_evidence")
    evidence_path = Path(evidence)
    if evidence_path.is_absolute() or ".." in evidence_path.parts:
        raise SchemaMigrationError(f"{inventory}: deployment_evidence must be a repository-relative path")
    repo_root = package_wheel.resolve().parents[3]
    if not (repo_root / evidence_path).is_file():
        raise SchemaMigrationError(f"{inventory}: deployment_evidence path does not exist")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    wheels = sorted((root / "_project/scripts/vendor").glob("todo_db-*-py3-none-any.whl"))
    if len(wheels) != 1:
        raise SchemaMigrationError(f"expected exactly one vendored todo-db wheel, found {len(wheels)}")
    validate_contract(
        package_wheel=wheels[0],
        inventory=root / "_project/todo-schema-migrations.json",
    )
    print("TODO package/schema migration contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
