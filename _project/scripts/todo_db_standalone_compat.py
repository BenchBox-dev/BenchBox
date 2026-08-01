#!/usr/bin/env python3
"""Opt-in BenchBox compatibility adapter for the standalone ``todo-db`` CLI.

The existing ``_project/scripts/todo`` entry point is deliberately unchanged.
The legacy Python tracker remains the default until a released standalone
package is selected explicitly with ``BENCHBOX_TODO_DB_STANDALONE=1``.  This
module owns BenchBox-only routing and presentation policy; lifecycle state,
identity checks, migrations, and audit writes are delegated to ``todo-db``.

This adapter uses an argv list and never a shell.  That matters for hosted DSNs
and tokens: neither is interpolated into a command string, and known token
values are redacted before forwarding delegated output.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

COMMANDS = frozenset(
    {
        "init",
        "migrate",
        "create",
        "show",
        "claim",
        "renew",
        "release",
        "deps",
        "unblock",
        "start",
        "done",
        "defer",
        "promote",
        "dismiss",
        "complete",
        "drop",
        "block",
        "list",
        "ready",
        "stats",
        "check-scope",
        "verify",
        "lint",
        "export",
        "config",
        "import-yaml",
        "sweep-stale",
    }
)

GLOBAL_VALUE_OPTIONS = frozenset({"--actor", "--db", "--project-id", "--repository"})


def _repo_root() -> Path:
    configured = os.environ.get("BENCHBOX_REPO_ROOT")
    if configured:
        return Path(configured).resolve()
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return Path.cwd().resolve()


def _command_index(argv: list[str]) -> tuple[int, str] | None:
    index = 0
    while index < len(argv):
        value = argv[index]
        if value in GLOBAL_VALUE_OPTIONS:
            index += 2
            continue
        if any(value.startswith(f"{option}=") for option in GLOBAL_VALUE_OPTIONS):
            index += 1
            continue
        if value in COMMANDS:
            return index, value
        index += 1
    return None


def _has_option(argv: Iterable[str], name: str) -> bool:
    return any(value == name or value.startswith(f"{name}=") for value in argv)


def _has_database_environment() -> bool:
    return any(os.environ.get(name) for name in ("TODO_DB_PATH", "TODO_DB_URL"))


def _with_identity(argv: list[str], command_index: int) -> list[str]:
    before = argv[:command_index]
    after = argv[command_index:]
    identity: list[str] = []
    if not _has_option(argv, "--project-id"):
        identity.extend(["--project-id", os.environ.get("BENCHBOX_TODO_DB_PROJECT_ID", "benchbox")])
    if not _has_option(argv, "--repository"):
        identity.extend(
            [
                "--repository",
                os.environ.get("BENCHBOX_TODO_DB_REPOSITORY", "https://github.com/joeharris76/BenchBox"),
            ]
        )
    return before + identity + after


def _option_value(argv: list[str], name: str) -> tuple[str | None, list[str]]:
    remaining: list[str] = []
    value: str | None = None
    index = 0
    while index < len(argv):
        current = argv[index]
        if current == name:
            if index + 1 >= len(argv):
                raise ValueError(f"{name} requires a value")
            value = argv[index + 1]
            index += 2
            continue
        prefix = f"{name}="
        if current.startswith(prefix):
            value = current[len(prefix) :]
            index += 1
            continue
        remaining.append(current)
        index += 1
    return value, remaining


def _redact(text: str, secrets: Iterable[str]) -> str:
    result = text
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    return result


def _delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> subprocess.CompletedProcess[str]:
    executable = shlex.split(os.environ.get("BENCHBOX_TODO_DB_COMMAND", "todo-db"))
    if not executable:
        raise RuntimeError("BENCHBOX_TODO_DB_COMMAND must not be empty")
    environment = os.environ.copy()
    version = subprocess.run(
        executable + ["--version"],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    reported = version.stdout.strip()
    if version.returncode or not reported.startswith("todo-db "):
        raise RuntimeError("standalone todo-db command does not expose a compatible --version handshake")
    expected = os.environ.get("BENCHBOX_TODO_DB_EXPECTED_VERSION")
    if expected and reported != f"todo-db {expected}":
        raise RuntimeError(f"standalone todo-db version mismatch: expected {expected}, got {reported}")
    return subprocess.run(
        executable + argv,
        cwd=cwd,
        env=environment,
        capture_output=capture,
        text=True,
        check=False,
    )


def _item_rows(envelope: dict[str, Any]) -> list[dict[str, Any]]:
    tables = envelope.get("tables") or {}
    items = [dict(row) for row in tables.get("items") or []]
    units = tables.get("work_units") or []
    needs = tables.get("work_needs") or []
    deps = tables.get("item_deps") or []
    scope = tables.get("scope_rules") or []
    verifications = tables.get("verifications") or []
    preserves = tables.get("preserves") or []
    anti_patterns = tables.get("anti_patterns") or []
    prior_art = tables.get("prior_art") or []
    deferrals = tables.get("deferrals") or []
    for item in items:
        item_id = item["id"]
        item["work"] = []
        for unit in units:
            if unit["item_id"] != item_id:
                continue
            child = dict(unit)
            child["needs"] = sorted(
                edge["needs_wid"] for edge in needs if edge["item_id"] == item_id and edge["wid"] == unit["wid"]
            )
            item["work"].append(child)
        item["work"].sort(key=lambda row: row["wid"])
        item["deps"] = sorted(edge["needs_item"] for edge in deps if edge["item_id"] == item_id)
        item["scope"] = sorted(
            (
                {key: value for key, value in dict(row).items() if key != "item_id"}
                for row in scope
                if row["item_id"] == item_id
            ),
            key=lambda row: (row["kind"], row["path_glob"]),
        )
        item["verifications"] = sorted(
            (dict(row) for row in verifications if row["item_id"] == item_id), key=lambda row: row["seq"]
        )
        item["preserves"] = sorted(row["behavior"] for row in preserves if row["item_id"] == item_id)
        item["anti_patterns"] = sorted(
            (
                {key: value for key, value in dict(row).items() if key != "item_id"}
                for row in anti_patterns
                if row["item_id"] == item_id
            ),
            key=lambda row: row["dont"],
        )
        item["prior_art"] = sorted(
            (
                {key: value for key, value in dict(row).items() if key != "item_id"}
                for row in prior_art
                if row["item_id"] == item_id
            ),
            key=lambda row: (row["path"], row["concept"]),
        )
        item["deferrals"] = sorted(
            (dict(row) for row in deferrals if row["from_item"] == item_id), key=lambda row: row["id"]
        )
    return sorted(items, key=lambda row: row["id"])


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def _write_legacy_export(
    output_dir: Path, envelope: dict[str, Any], lossless_dir: Path | None = None
) -> tuple[Path, Path, Path, Path]:
    """Write the committed items-domain views, plus the lossless envelope.

    ``output_dir`` receives ONLY the items-domain views -- ``items.jsonl``,
    ``events.jsonl``, ``index.md`` -- because it is the version-controlled export
    snapshot. The lossless ``todo-db.json`` (every table, including the findings
    domain whose review prose is deliberately not version-controlled) goes to
    ``lossless_dir``, which defaults to a sibling *outside* ``output_dir`` so the
    workflow's `git add` can never stage it. It remains the complete recovery
    artifact the restore round-trip replays.

    ``events.jsonl`` is derived from THIS envelope, not left over from a separate
    main-path export: both committed views therefore come from one read snapshot,
    so an item can never be missing the event that created it.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    lossless_dir = lossless_dir if lossless_dir is not None else output_dir.parent / f"{output_dir.name}-lossless"
    lossless_dir.mkdir(parents=True, exist_ok=True)
    legacy_envelope = output_dir / "todo-db.json"
    if legacy_envelope.exists() or legacy_envelope.is_symlink():
        if not legacy_envelope.is_file() and not legacy_envelope.is_symlink():
            raise ValueError(f"legacy export path is not a file: {legacy_envelope}")
        legacy_envelope.unlink()
    lossless_path = lossless_dir / "todo-db.json"
    items_path = output_dir / "items.jsonl"
    events_path = output_dir / "events.jsonl"
    index_path = output_dir / "index.md"
    items = _item_rows(envelope)
    _atomic_write(lossless_path, _canonical_json(envelope))
    _atomic_write(items_path, "".join(_canonical_json(item) for item in items))
    events = sorted((dict(row) for row in envelope.get("events") or []), key=lambda row: row["seq"])
    _atomic_write(events_path, "".join(_canonical_json(event) for event in events))
    lines = ["# TODO export", "", "| id | state | priority | worktree | title |", "|---|---|---|---|---|"]
    for item in items:
        lines.append(f"| {item['id']} | {item['state']} | {item['priority']} | {item['worktree']} | {item['title']} |")
    _atomic_write(index_path, "\n".join(lines) + "\n")
    return lossless_path, items_path, events_path, index_path


def _export(argv: list[str], cwd: Path) -> int:
    out_dir, without_out = _option_value(argv, "--out")
    # The lossless envelope is written outside --out (the committed snapshot);
    # --lossless-out relocates it, e.g. to a CI artifact staging directory.
    lossless_out, without_out = _option_value(without_out, "--lossless-out")
    output_dir = Path(out_dir).expanduser() if out_dir else cwd / ".todo-db" / "export"
    lossless_dir = Path(lossless_out).expanduser() if lossless_out else None
    with tempfile.TemporaryDirectory(prefix="benchbox-todo-db-export-") as temporary:
        standalone_output = Path(temporary) / "todo-db.json"
        located = _command_index(without_out)
        if located is None:
            raise ValueError("export command disappeared while processing --out")
        delegated = without_out[: located[0] + 1] + ["--output", str(standalone_output)] + without_out[located[0] + 1 :]
        delegated_location = _command_index(delegated)
        assert delegated_location is not None
        delegated = _with_identity(delegated, delegated_location[0])
        result = _delegate(delegated, command="export", cwd=cwd)
        secrets = (os.environ.get("TODO_DB_AUTH_TOKEN", ""), os.environ.get("TODO_DB_RO_AUTH_TOKEN", ""))
        if result.returncode and result.stdout:
            sys.stdout.write(_redact(result.stdout, secrets))
        if result.stderr:
            sys.stderr.write(_redact(result.stderr, secrets))
        if result.returncode:
            return result.returncode
        envelope = json.loads(standalone_output.read_text(encoding="utf-8"))
        lossless, items, events, index = _write_legacy_export(output_dir, envelope, lossless_dir)
        print(f"wrote {items}, {events} and {index} (lossless envelope: {lossless})")
        return 0


def _main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    located = _command_index(args)
    if located is None:
        result = _delegate(args, command="", cwd=_repo_root())
        secrets = (os.environ.get("TODO_DB_AUTH_TOKEN", ""), os.environ.get("TODO_DB_RO_AUTH_TOKEN", ""))
        if result.stdout:
            sys.stdout.write(_redact(result.stdout, secrets))
        if result.stderr:
            sys.stderr.write(_redact(result.stderr, secrets))
        return result.returncode
    command_index, command = located
    root = _repo_root()
    if not _has_option(args, "--db") and not _has_database_environment():
        args[command_index:command_index] = ["--db", str(root / ".todo-db" / "todo.sqlite")]
        command_index += 2
    if command == "export":
        return _export(args, root)
    delegated = _with_identity(args, command_index)
    if command == "import-yaml":
        import_index = _command_index(delegated)
        assert import_index is not None
        if not _has_option(delegated, "--todo-dir"):
            delegated[import_index[0] + 1 : import_index[0] + 1] = ["--todo-dir", str(root / "_project" / "TODO")]
        if not _has_option(delegated, "--done-dir") and "--skip-done" not in delegated:
            import_index = _command_index(delegated)
            assert import_index is not None
            delegated[import_index[0] + 1 : import_index[0] + 1] = ["--done-dir", str(root / "_project" / "DONE")]
    result = _delegate(delegated, command=command, cwd=root)
    secrets = (os.environ.get("TODO_DB_AUTH_TOKEN", ""), os.environ.get("TODO_DB_RO_AUTH_TOKEN", ""))
    if result.stdout:
        sys.stdout.write(_redact(result.stdout, secrets))
    if result.stderr:
        sys.stderr.write(_redact(result.stderr, secrets))
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except FileNotFoundError as exc:
        print(f"error: standalone todo-db command not found: {exc.filename}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
