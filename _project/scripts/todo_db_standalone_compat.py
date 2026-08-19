#!/usr/bin/env python3
"""BenchBox compatibility adapter for the locked ``todo-db`` CLI.

The stable ``_project/scripts/todo`` entry point always routes here. This module
owns BenchBox-only routing and presentation policy; lifecycle state,
identity checks, migrations, and audit writes are delegated to ``todo-db``.

This adapter uses an argv list and never a shell.  That matters for hosted DSNs
and tokens: neither is interpolated into a command string, and known token
values are redacted before forwarding delegated output.
"""

from __future__ import annotations

import json
import os
import re
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
        "update",
        "scope-update",
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
        "freeze",
        "finding",
        "audit",
        "agent",
        "doctor",
    }
)

STANDALONE_ONLY_COMMANDS = frozenset({"init-project", "restore", "restore-legacy"})

GLOBAL_VALUE_OPTIONS = frozenset({"--actor", "--db", "--project-id", "--replica", "--repository"})
OFFLINE_FINDING_SUBCOMMANDS = frozenset({"create", "candidates"})
PACKAGE_COMMAND_TRANSLATIONS = {"scope-update": "update"}
EXTENSION_COMMANDS = frozenset({"renew", "freeze"})
READ_ONLY_COMMANDS = frozenset({"show", "deps", "list", "ready", "stats", "check-scope", "lint", "audit", "doctor"})
AGENT_READ_ONLY_SUBCOMMANDS = frozenset({"instructions", "next", "context", "claims"})
_READY_BANNER_RE = re.compile(
    r"^(?P<open>\d+) open finding\(s\), (?P<drafts>\d+) unsynced draft\(s\) -- todo-db finding candidates$"
)
_DEFAULT_EXPECTED_TODO_DB_VERSION = "0.4.2"


def _repo_root() -> Path:
    configured = os.environ.get("BENCHBOX_REPO_ROOT")
    if configured:
        return Path(configured).resolve()
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return Path.cwd().resolve()


def _command_index(argv: list[str]) -> tuple[int, str] | None:
    return _command_index_from(argv, COMMANDS)


def _command_index_from(argv: list[str], commands: frozenset[str]) -> tuple[int, str] | None:
    index = 0
    while index < len(argv):
        value = argv[index]
        if value in GLOBAL_VALUE_OPTIONS:
            index += 2
            continue
        if any(value.startswith(f"{option}=") for option in GLOBAL_VALUE_OPTIONS):
            index += 1
            continue
        return (index, value) if value in commands else None
    return None


def _is_root_help(argv: list[str]) -> bool:
    saw_help = False
    index = 0
    while index < len(argv):
        value = argv[index]
        if value in GLOBAL_VALUE_OPTIONS:
            index += 2
            continue
        if any(value.startswith(f"{option}=") for option in GLOBAL_VALUE_OPTIONS):
            index += 1
            continue
        if value in {"-h", "--help"}:
            saw_help = True
            index += 1
            continue
        return False
    return saw_help


def _print_root_help() -> None:
    commands = ",".join(sorted(COMMANDS))
    print(
        f"usage: todo [GLOBAL OPTIONS] {{{commands}}} ...\n\n"
        "BenchBox compatibility wrapper for the locked todo-db package.\n"
        "Run 'todo <command> --help' for command-specific options.\n\n"
        "Standalone recovery commands are intentionally unavailable through this wrapper."
    )


def _has_option(argv: Iterable[str], name: str) -> bool:
    return any(value == name or value.startswith(f"{name}=") for value in argv)


def _has_database_environment() -> bool:
    return any(os.environ.get(name) for name in ("TODO_DB_PATH", "TODO_DB_URL"))


def _has_config_json(root: Path) -> bool:
    return (root / ".todo-db" / "config.json").is_file()


def _is_offline_finding_command(args: list[str], command_index: int, command: str) -> bool:
    """Return whether a finding command only reads or writes local drafts."""
    subcommand = args[command_index + 1] if command_index + 1 < len(args) else None
    return command == "finding" and subcommand in OFFLINE_FINDING_SUBCOMMANDS


def _can_run_without_database(args: list[str], command_index: int, command: str) -> bool:
    return (
        any(value in {"-h", "--help", "--version"} for value in args)
        or command == "doctor"
        or _is_offline_finding_command(args, command_index, command)
        or (command == "agent" and args[command_index + 1 : command_index + 2] == ["instructions"])
    )


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


def _forward_result(result: subprocess.CompletedProcess[str]) -> int:
    secrets = (os.environ.get("TODO_DB_AUTH_TOKEN", ""), os.environ.get("TODO_DB_RO_AUTH_TOKEN", ""))
    if result.stdout:
        sys.stdout.write(_redact(result.stdout, secrets))
    if result.stderr:
        sys.stderr.write(_redact(result.stderr, secrets))
    return result.returncode


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
    expected = os.environ.get("BENCHBOX_TODO_DB_EXPECTED_VERSION", _DEFAULT_EXPECTED_TODO_DB_VERSION)
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


def _delegate_extension(argv: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a BenchBox compatibility verb against the package-opened database."""
    environment = os.environ.copy()
    module_root = str(Path(__file__).resolve().parents[2])
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (module_root, environment.get("PYTHONPATH", "")) if value
    )
    return subprocess.run(
        [sys.executable, "-m", "_project.scripts.todo_db_standalone_extensions", *argv],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _initialize_missing_local_read_target(
    argv: list[str], *, command: str, cwd: Path
) -> subprocess.CompletedProcess[str] | None:
    """Preserve the legacy wrapper's create-on-first-local-read behavior."""
    explicit_target, _ = _option_value(argv, "--db")
    target = explicit_target or os.environ.get("TODO_DB_PATH", "")
    candidate = Path(target).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    if command not in {"list", "ready", "stats"} or not target or "://" in target or candidate.exists():
        return None
    located = _command_index(argv)
    assert located is not None
    return _delegate(argv[: located[0]] + ["init"], command="init", cwd=cwd)


def _findings_banner(open_count: int, draft_count: int) -> str | None:
    if not open_count and not draft_count:
        return None
    parts: list[str] = []
    destinations: list[str] = []
    if open_count:
        parts.append(f"{open_count} open finding(s)")
        destinations.append("todo finding list --disposition open")
    if draft_count:
        parts.append(f"{draft_count} unsynced draft(s)")
        destinations.append("todo finding candidates")
    return f"→ {', '.join(parts)} awaiting triage — see: {'; '.join(destinations)}"


def _normalize_findings_banner(result: subprocess.CompletedProcess[str], *, command: str) -> None:
    """Restore BenchBox's stderr-only ready/stats findings warning."""
    if result.returncode:
        return
    banner: str | None = None
    if command == "ready":
        lines = result.stdout.splitlines()
        if lines and (match := _READY_BANNER_RE.fullmatch(lines[-1])):
            banner = _findings_banner(int(match["open"]), int(match["drafts"]))
            result.stdout = "\n".join(lines[:-1]) + ("\n" if len(lines) > 1 else "")
    elif command == "stats":
        try:
            stats = json.loads(result.stdout)
            banner = _findings_banner(
                int((stats.get("findings_by_disposition") or {}).get("open", 0)),
                int(stats.get("unsynced_drafts", 0)),
            )
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            return
    if banner:
        result.stderr = result.stderr.rstrip("\n") + ("\n" if result.stderr else "") + banner + "\n"


def _preserve_stats_activity(
    result: subprocess.CompletedProcess[str], argv: list[str], *, cwd: Path
) -> subprocess.CompletedProcess[str]:
    """Restore BenchBox's activity fingerprint on standalone stats output."""
    if result.returncode:
        return result
    located = _command_index(argv)
    assert located is not None
    activity = _delegate_extension(argv[: located[0]] + ["activity"], cwd=cwd)
    if activity.returncode:
        return activity
    try:
        stats = json.loads(result.stdout)
        stats.update(json.loads(activity.stdout))
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return subprocess.CompletedProcess(
            argv,
            2,
            stdout="",
            stderr=f"error: standalone stats activity payload is invalid: {exc}\n",
        )
    result.stdout = _canonical_json(stats)
    return result


def _command_mutates_tracker(argv: list[str], command: str) -> bool:
    if any(value in {"-h", "--help", "--version"} for value in argv):
        return False
    if command in READ_ONLY_COMMANDS:
        return False
    if command == "agent":
        located = _command_index(argv)
        assert located is not None
        subcommand = argv[located[0] + 1] if located[0] + 1 < len(argv) else None
        return subcommand not in AGENT_READ_ONLY_SUBCOMMANDS
    if command == "import-yaml":
        return not _has_option(argv, "--dry-run")
    if command == "verify":
        return _has_option(argv, "--run")
    located = _command_index(argv)
    if located is None:
        return True
    trailing = argv[located[0] + 1 :]
    if command == "config":
        return len([value for value in trailing if not value.startswith("--")]) >= 2
    if command == "finding":
        return bool(trailing) and trailing[0] not in {"create", "candidates", "list", "show"}
    return True


def _database_can_have_freeze(argv: list[str], cwd: Path) -> bool:
    explicit_target, _ = _option_value(argv, "--db")
    target = explicit_target or os.environ.get("TODO_DB_PATH") or os.environ.get("TODO_DB_URL")
    if target:
        if "://" in target:
            return True
        candidate = Path(target).expanduser()
        if not candidate.is_absolute():
            candidate = cwd / candidate
        return candidate.exists()
    return _has_config_json(cwd)


def _append_claim_context(result: subprocess.CompletedProcess[str], argv: list[str], *, cwd: Path) -> None:
    """Render BenchBox's full binding work order after a package claim."""
    located = _command_index(argv)
    assert located is not None
    item_index = located[0] + 1
    if item_index >= len(argv):
        return
    detail = _delegate(argv[: located[0]] + ["show", argv[item_index], "--json"], command="show", cwd=cwd)
    if detail.returncode:
        return
    try:
        item = json.loads(detail.stdout)
    except json.JSONDecodeError:
        return
    lines: list[str] = []
    if item.get("preserves"):
        lines.append("-- must preserve")
        lines.extend(f"   {behavior}" for behavior in item["preserves"])
    if item.get("anti_patterns"):
        lines.append("-- anti-patterns")
        lines.extend(
            f"   DO NOT {entry['dont']} — {entry['why']} — instead: {entry['instead']}"
            for entry in item["anti_patterns"]
        )
    if item.get("verifications"):
        lines.append("-- verification ladder (narrowest first)")
        for entry in item["verifications"]:
            command = f" :: {entry['command']}" if entry.get("command") else ""
            expected = f" — expected: {entry['expected']}" if entry.get("expected") else ""
            lines.append(f"   {entry['seq']}. {entry['description']}{command}{expected}")
    if lines:
        result.stdout = result.stdout.rstrip("\n") + "\n" + "\n".join(lines) + "\n"


def _delegate_compat_command(argv: list[str], *, command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    initialized = _initialize_missing_local_read_target(argv, command=command, cwd=cwd)
    if initialized is not None and initialized.returncode:
        return initialized
    if _command_mutates_tracker(argv, command) and _database_can_have_freeze(argv, cwd):
        located = _command_index(argv)
        assert located is not None
        guard = _delegate_extension(argv[: located[0]] + ["freeze-guard"], cwd=cwd)
        if guard.returncode:
            return guard
    result = _delegate_extension(argv, cwd=cwd) if command == "renew" else _delegate(argv, command=command, cwd=cwd)
    if command == "stats" and not any(value in {"-h", "--help", "--version"} for value in argv):
        result = _preserve_stats_activity(result, argv, cwd=cwd)
    if command == "claim" and result.returncode == 0:
        _append_claim_context(result, argv, cwd=cwd)
    if command == "defer" and result.returncode == 2 and " is terminal;" in result.stderr:
        result.stderr += "error: terminal items cannot accept deferrals\n"
    if command in {"ready", "stats"}:
        _normalize_findings_banner(result, command=command)
    return result


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
        # Claim generation tokens coordinate private mutations and must remain
        # only in the separate lossless recovery artifact, never public views.
        item.pop("claim_token", None)
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


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def _write_legacy_export(
    output_dir: Path, envelope: dict[str, Any], lossless_content: bytes, lossless_dir: Path | None = None
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
    _atomic_write_bytes(lossless_path, lossless_content)
    _atomic_write(items_path, "".join(_canonical_json(item) for item in items))
    events = sorted((dict(row) for row in envelope.get("events") or []), key=lambda row: row["seq"])
    _atomic_write(events_path, "".join(_canonical_json(event) for event in events))
    lines = ["# TODO export", "", "| id | state | priority | worktree | title |", "|---|---|---|---|---|"]
    for item in items:
        lines.append(f"| {item['id']} | {item['state']} | {item['priority']} | {item['worktree']} | {item['title']} |")
    _atomic_write(index_path, "\n".join(lines) + "\n")
    return lossless_path, items_path, events_path, index_path


def _export(argv: list[str], cwd: Path) -> int:
    if any(value in {"-h", "--help"} for value in argv):
        print(
            "usage: todo export [-h] [--out DIRECTORY] [--lossless-out DIRECTORY]\n\n"
            "Write deterministic compatibility views and a separate lossless recovery envelope.\n\n"
            "options:\n"
            "  -h, --help            show this help message and exit\n"
            "  --out DIRECTORY       compatibility-view directory (default: .todo-db/export)\n"
            "  --lossless-out DIRECTORY\n"
            "                        lossless recovery-envelope directory"
        )
        return 0
    if "--version" in argv:
        return _forward_result(_delegate(argv, command="export", cwd=cwd))
    if _has_option(argv, "--output"):
        print(
            "error: BenchBox compatibility export uses --out DIRECTORY; "
            "use --lossless-out DIRECTORY to place the recovery envelope",
            file=sys.stderr,
        )
        return 2
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
        lossless_content = standalone_output.read_bytes()
        envelope = json.loads(lossless_content)
        lossless, items, events, index = _write_legacy_export(output_dir, envelope, lossless_content, lossless_dir)
        print(f"wrote {items}, {events} and {index} (lossless envelope: {lossless})")
        return 0


def _main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    located = _command_index(args)
    if located is None:
        standalone_only = _command_index_from(args, STANDALONE_ONLY_COMMANDS)
        if standalone_only is not None:
            print(
                f"error: BenchBox compatibility wrapper does not expose standalone-only "
                f"'{standalone_only[1]}'; use the locked todo-db package directly in an approved recovery workflow",
                file=sys.stderr,
            )
            return 2
        if not args or _is_root_help(args):
            _print_root_help()
            return 0
        return _forward_result(_delegate(args, command="", cwd=_repo_root()))
    command_index, command = located
    root = _repo_root()
    # Refuse loudly if no DB is configured via env, --db, or config.json; honor
    # config.json as configured. Doctor and local-draft finding commands remain
    # intentionally database-free.
    has_db = _has_database_environment() or _has_option(args, "--db") or _has_config_json(root)
    if not has_db and not _can_run_without_database(args, command_index, command):
        print(
            f"error: package-only shim cannot route '{command}' without explicit --db, TODO_DB_PATH/URL, or .todo-db/config.json; refusing to create fork DB at {root / '.todo-db' / 'todo.sqlite'}",
            file=sys.stderr,
        )
        return 2
    if command in PACKAGE_COMMAND_TRANSLATIONS:
        command = PACKAGE_COMMAND_TRANSLATIONS[command]
        args[command_index] = command
    if command == "freeze":
        return _forward_result(_delegate_extension(args, cwd=root))
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
    finding_drafts_env_was_missing = command == "finding" and not os.environ.get("TODO_DB_FINDING_DRAFTS_DIR")
    if finding_drafts_env_was_missing:
        os.environ["TODO_DB_FINDING_DRAFTS_DIR"] = str(Path.home() / ".benchbox" / "finding-drafts")
    try:
        result = _delegate_compat_command(delegated, command=command, cwd=root)
    finally:
        if finding_drafts_env_was_missing:
            os.environ.pop("TODO_DB_FINDING_DRAFTS_DIR", None)
    return _forward_result(result)


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
