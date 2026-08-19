#!/usr/bin/env python3
"""Fail closed when the locked todo-db package, wrapper, or rollout record drift.

This guard is stdlib-only, but it inspects the todo-db package as installed into
``_project/scripts/.venv`` rather than a committed wheel, because the runtime is
pinned by git tag and has no artifact to inspect before installation. It therefore
runs in the dependency-synced ``lint`` job rather than the dependency-free
``ci-paths`` job. Package migration correctness belongs to todo-db; BenchBox pins
the exact release, schema handshake, and deployment evidence that make that
release safe to consume.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
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


def _installed_package_dir(scripts_root: Path) -> Path:
    """Locate the todo_db package inside the scripts project's virtualenv."""
    candidates = sorted((scripts_root / ".venv" / "lib").glob("python3.*/site-packages/todo_db"))
    if len(candidates) != 1:
        raise SchemaMigrationError(
            f"{scripts_root}: expected exactly one installed todo_db package, found {len(candidates)}; "
            "run `uv sync --project _project/scripts` first"
        )
    return candidates[0]


def _package_contract(package_dir: Path) -> tuple[int, list[int]]:
    try:
        database_source = (package_dir / "database.py").read_text(encoding="utf-8")
        versions = sorted(
            int(match.group(1))
            for path in (package_dir / "migrations").glob("*.sql")
            if (match := re.fullmatch(r"([0-9]{3})_[^/]+\.sql", path.name))
        )
    except (OSError, UnicodeDecodeError) as exc:
        raise SchemaMigrationError(f"{package_dir}: cannot inspect installed todo-db package: {exc}") from exc
    schema_version = _integer_assignment(database_source, "SCHEMA_VERSION", package_dir)
    expected = list(range(1, schema_version + 1))
    if versions != expected:
        raise SchemaMigrationError(f"{package_dir}: package migrations {versions!r} must be contiguous {expected!r}")
    return schema_version, versions


def validate_contract(*, package_dir: Path, wrapper: Path, inventory: Path, repo_root: Path) -> None:
    schema_version, _ = _package_contract(package_dir)

    wrapper_text = wrapper.read_text(encoding="utf-8")
    wrapper_match = re.search(r"(?m)^TODO_SCHEMA_VERSION=([0-9]+)$", wrapper_text)
    if wrapper_match is None:
        raise SchemaMigrationError(f"{wrapper}: missing literal TODO_SCHEMA_VERSION declaration")
    if int(wrapper_match.group(1)) != schema_version:
        raise SchemaMigrationError(
            f"{wrapper}: TODO_SCHEMA_VERSION={wrapper_match.group(1)} does not match package schema {schema_version}"
        )

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
    if not (repo_root / evidence_path).is_file():
        raise SchemaMigrationError(f"{inventory}: deployment_evidence path does not exist")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    validate_contract(
        package_dir=_installed_package_dir(root / "_project/scripts"),
        wrapper=root / "_project/scripts/todo",
        inventory=root / "_project/todo-schema-migrations.json",
        repo_root=root,
    )
    print("TODO package/schema migration contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
